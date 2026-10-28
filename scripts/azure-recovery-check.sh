#!/usr/bin/env bash
# P7 private-target doctor/native-session adapter. Explicit invocation only; no deployment/IAM.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:?doctor|session-login|session-verify}"
: "${P7_NAMESPACE:?}" "${P7_PRIVATE:?}" "${P7_POD:?}"
[[ "$P7_NAMESPACE" == p7-ops-* || "$P7_NAMESPACE" == forgejo ]] || exit 1
[[ -d "$P7_PRIVATE" && "$(stat -c %a "$P7_PRIVATE")" == 700 ]] || exit 1
k() { kubectl --request-timeout=15s -n "$P7_NAMESPACE" "$@"; }
cookie_header() {
  python3 - "$cookie" "$config" "${1:-required}" <<'PY'
import http.cookiejar, sys
from pathlib import Path
jar = http.cookiejar.MozillaCookieJar(sys.argv[1])
jar.load(ignore_discard=True, ignore_expires=True)
value = '; '.join(c.name + '=' + c.value for c in jar)
assert (value or sys.argv[3] == 'allow-empty') and not any(c in value for c in '\r\n"\\')
Path(sys.argv[2]).write_text('header = "Cookie: ' + value + '"\n' if value else '')
PY
}
if [[ "$MODE" == doctor ]]; then
  : "${P7_DOCTOR_OUTPUT:?}" "${P7_DOCTOR_SOURCE:--}"
  dir="$(mktemp -d "$P7_PRIVATE/doctor.XXXXXX")"
  trap 'rm -rf "$dir"' EXIT
  k get pod "$P7_POD" -o json >"$dir/pod.json"
  jq -e --arg ns "$P7_NAMESPACE" '.metadata.namespace == $ns and
    (if $ns == "forgejo" then .metadata.labels["app.kubernetes.io/name"] == "forgejo"
     else .metadata.labels["p7.campaign"] != null and .spec.automountServiceAccountToken == false
       and (.spec.containers | length) == 1 and .spec.containers[0].name == "forgejo"
       and (.spec.initContainers // [] | length) == 0 end)' "$dir/pod.json" >/dev/null
  k exec "$P7_POD" -c forgejo -- cat /data/gitea/conf/app.ini >"$dir/app.ini"
  k exec "$P7_POD" -c forgejo -- env >"$dir/env.txt"
  k exec "$P7_POD" -c forgejo -- forgejo --version >"$dir/version"
  version="$(sed -n 's/^[Ff]orgejo version \([^ ]*\).*/\1/p' "$dir/version")"
  jq -n --arg version "$version" --arg image "$(jq -r '.status.containerStatuses[] | select(.name=="forgejo") | .imageID' "$dir/pod.json")" \
    '{forgejo_version:$version,forgejo_image_id:$image}' >"$dir/metadata.json"
  k exec "$P7_POD" -c forgejo -- forgejo doctor check --list --config /data/gitea/conf/app.ini >"$dir/inventory.txt" 2>&1
  for check in paths check-db-version check-db-consistency check-user-type synchronize-repo-heads; do
    rc=0
    timeout -k 5s 150s kubectl --request-timeout=15s -n "$P7_NAMESPACE" exec "$P7_POD" -c forgejo -- \
      forgejo doctor check --run "$check" --config /data/gitea/conf/app.ini >"$dir/$check.txt" 2>&1 || rc=$?
    printf '%s\n' "$rc" >"$dir/$check.exit"
  done
  # Preserve the exact known paths diagnostic; any different finding fails the P3 validator.
  [[ ! -e "$P7_DOCTOR_OUTPUT" ]] || exit 1
  python3 "$ROOT/scripts/validate-recovery.py" doctor-upgrade "$dir" "${P7_DOCTOR_SOURCE:--}" "$P7_DOCTOR_OUTPUT"
elif [[ "$MODE" == session-login || "$MODE" == session-verify ]]; then
  : "${FORGEJO_URL:?}" "${DEV_USER:?}"
  : "${P7_PRIVATE_URL:?}"
  [[ "$P7_PRIVATE_URL" =~ ^http://127\.0\.0\.1:[0-9]+$ ]] || exit 1
  cookie="$P7_PRIVATE/cookies"
  config="$P7_PRIVATE/session-curl"
  response="$P7_PRIVATE/session-response"
  trap 'rm -f "$config" "$response" "$P7_PRIVATE/session-body"' EXIT
  if [[ "$MODE" == session-login ]]; then
    # Once per source fixture: trusted stable HTTPS or isolated fresh A tunnel.
    : "${DEV_PASSWORD:?}"
    [[ ! -e "$cookie" ]] || exit 1
    python3 "$ROOT/scripts/validate-operation-results.py" transport "$FORGEJO_URL" azure-aks "${JOURNEY_DNS_OVERRIDE:-}" >/dev/null
    login_url="$FORGEJO_URL"
    args=(-q --noproxy '*' --proto '=https' -sS --max-time 15)
    if [[ "$P7_NAMESPACE" == p7-ops-* ]]; then
      login_url="$P7_PRIVATE_URL"
      args=(-q --noproxy '*' --proto '=http' -sS --max-time 15)
    elif [[ -n "${JOURNEY_DNS_OVERRIDE:-}" ]]; then
      host="${FORGEJO_URL#https://}"
      args+=(--resolve "$host:443:$JOURNEY_DNS_OVERRIDE")
    fi
    curl "${args[@]}" -c "$cookie" -b "$cookie" "$login_url/user/login" >"$response"
    # Same optional form-token handling as the existing P3 session_login flow.
    csrf="$(python3 - "$response" <<'PY'
from html.parser import HTMLParser
from pathlib import Path
import sys
class CSRF(HTMLParser):
    value = ''
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('name') == '_csrf':
            self.value = attrs.get('value', '')
p = CSRF()
p.feed(Path(sys.argv[1]).read_text())
print(p.value)
PY
)"
    python3 - "$csrf" "$P7_PRIVATE/session-body" <<'PY'
import os, sys, urllib.parse
from pathlib import Path
fields = {'user_name': os.environ['DEV_USER'], 'password': os.environ['DEV_PASSWORD']}
if sys.argv[1]:
    fields['_csrf'] = sys.argv[1]
Path(sys.argv[2]).write_text(urllib.parse.urlencode(fields))
PY
    cookie_header allow-empty
    status="$(curl "${args[@]}" -c "$cookie" -K "$config" -X POST -H 'Content-Type: application/x-www-form-urlencoded' \
      --data-binary "@$P7_PRIVATE/session-body" -o "$response" -w '%{http_code}' "$login_url/user/login")"
    [[ "$status" == 302 || "$status" == 303 ]] || exit 1
    sha256sum "$cookie" | cut -d ' ' -f 1 >"$P7_PRIVATE/cookie.sha256"
  fi
  [[ "$(sha256sum "$cookie" | cut -d ' ' -f 1)" == "$(cat "$P7_PRIVATE/cookie.sha256")" ]] || exit 1
  # Original cookie values replayed through a private loopback tunnel. This is session-state
  # continuity, not a claim about browser Secure-cookie behavior over HTTP or public old-version routing.
  cookie_header
  status="$(curl -q --noproxy '*' --proto '=http' -sS --max-time 15 -K "$config" -o "$response" -w '%{http_code}' \
    "$P7_PRIVATE_URL/user/settings")"
  [[ "$status" == 200 ]] || exit 1
  grep -qF "$DEV_USER" "$response" || exit 1
  [[ "$(sha256sum "$cookie" | cut -d ' ' -f 1)" == "$(cat "$P7_PRIVATE/cookie.sha256")" ]] || exit 1
  echo 'same native session values accepted through private tunnel'
else
  echo 'usage: azure-recovery-check.sh doctor|session-login|session-verify' >&2
  exit 1
fi
