#!/usr/bin/env bash
# P1 local platform verification.
#   static       cluster 없이 shell lint, versions.env pin 일치, Helm render/config contract를 검사한다.
#   runtime      실행 중인 local platform의 contract, developer journey, Forgejo/PostgreSQL workload
#                replacement 후 state continuity를 검사한다. (backup/restore 검증이 아니다)
#   diagnostics  실패 분석용 cluster 상태를 출력한다.
# Readiness gate만 bounded wait를 사용하고, developer operation 자체는 retry하지 않는다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=versions.env
source "$ROOT/versions.env"
export PATH="$ROOT/.tmp/bin:$PATH"
export KUBECONFIG="$ROOT/.tmp/kubeconfig"
MODE="${1:?usage: local-verify.sh static|runtime|diagnostics}"

# values-local.yaml ROOT_URL과 같은 loopback endpoint (Local development exception).
LOCAL_PORT=13000
FORGEJO_URL="http://127.0.0.1:$LOCAL_PORT"
FORGEJO_IMAGE="code.forgejo.org/forgejo/forgejo:$FORGEJO_IMAGE_TAG"
JOURNEY_DIR="$ROOT/.tmp/journey"
JOURNEY="$ROOT/tests/e2e/forgejo-developer-journey.sh"

# Forgejo config contract. Static render(inline config)와 runtime app.ini에 같은 기준을 적용한다.
CONFIG_CONTRACT=(
  "database DB_TYPE postgres"
  "database NAME forgejo"
  "database USER forgejo"
  "database HOST postgres.postgres.svc.cluster.local:5432"
  "session PROVIDER db"
  "cache ADAPTER twoqueue"
  "cache HOST 50000"
  "queue TYPE level"
  "server DISABLE_SSH true"
  "server START_SSH_SERVER false"
  "server ROOT_URL $FORGEJO_URL/"
  "service DISABLE_REGISTRATION true"
  "repository DISABLE_MIGRATIONS true"
  "mirror ENABLED false"
  "packages ENABLED false"
  "actions ENABLED false"
)

pass() { printf '[local-verify] PASS %s\n' "$*"; }
fail() { printf '[local-verify] FAIL %s\n' "$*" >&2; exit 1; }

ini_get() { # INI_CONTENT SECTION KEY
  awk -v want="[$2]" -v k="$3" '
    /^[[:space:]]*\[/ { gsub(/[[:space:]]/, ""); section = $0; next }
    section == want && (i = index($0, "=")) > 0 {
      key = substr($0, 1, i - 1); gsub(/^[ \t]+|[ \t]+$/, "", key)
      if (key == k) { val = substr($0, i + 1); gsub(/^[ \t]+|[ \t]+$/, "", val); print val; exit }
    }' <<<"$1"
}

check_config() { # INI_CONTENT LABEL
  local entry section key expected actual
  for entry in "${CONFIG_CONTRACT[@]}"; do
    read -r section key expected <<<"$entry"
    actual="$(ini_get "$1" "$section" "$key")"
    [[ "$actual" == "$expected" ]] || fail "$2 [$section] $key: expected '$expected', got '$actual'"
  done
  pass "$2 config contract (${#CONFIG_CONTRACT[@]} keys)"
}

expect_line() { # FILE LINE  (앞뒤 공백을 제외한 exact line match)
  awk -v want="$2" '{ line = $0; gsub(/^[ \t]+|[ \t]+$/, "", line); if (line == want) found = 1 } END { exit !found }' \
    "$ROOT/$1" || fail "$1 does not contain '$2' (versions.env mismatch)"
}

# Rendered chart의 `<release>-inline-config` Secret stringData를 INI로 변환한다.
inline_config_ini() { # RENDERED_MANIFEST
  awk -v q="'" '
    /^---/ { target = 0; data = 0; next }
    /^  name: forgejo-inline-config$/ { target = 1; next }
    target && /^stringData:/ { data = 1; next }
    data && /^  [^ ]/ {
      line = substr($0, 3); i = index(line, ":")
      print "[" substr(line, 1, i - 1) "]"
      val = substr(line, i + 2)
      if (val != "|-" && val != "|" && val != "") { gsub("^[\"" q "]|[\"" q "]$", "", val); print val }
      next
    }
    data && /^    / { print substr($0, 5); next }
    data { data = 0 }' "$1"
}

static() {
  "$ROOT/scripts/install-tools.sh"
  # ShellCheck의 source= directive는 repository root 기준 relative path다.
  cd "$ROOT"
  local -a scripts=(scripts/*.sh tests/e2e/*.sh)
  local f rendered
  for f in "${scripts[@]}"; do bash -n "$f"; done
  shellcheck -x "${scripts[@]}"
  pass "shell syntax + shellcheck ($(shellcheck --version | awk '/^version:/ {print $2}'), ${#scripts[@]} files)"

  expect_line platform/local/k3d.yaml "image: $K3S_IMAGE"
  expect_line platform/local/postgres.yaml "image: $POSTGRES_IMAGE"
  expect_line platform/forgejo/values-common.yaml "tag: $FORGEJO_IMAGE_TAG"
  [[ "$(grep -c 'image:' "$ROOT/platform/local/postgres.yaml")" == 1 ]] || fail "unexpected extra image in postgres.yaml"
  pass "source pins match versions.env"

  mkdir -p "$ROOT/.tmp/rendered"
  rendered="$ROOT/.tmp/rendered/forgejo.yaml"
  helm template forgejo "$FORGEJO_CHART" --version "$FORGEJO_CHART_VERSION" --namespace forgejo \
    -f "$ROOT/platform/forgejo/values-common.yaml" -f "$ROOT/platform/forgejo/values-local.yaml" >"$rendered"
  pass "helm template chart $FORGEJO_CHART_VERSION (values.schema.json validated)"

  [[ "$(grep -c '^kind: Deployment$' "$rendered")" == 1 ]] || fail "expected exactly one Deployment"
  if grep -Eq '^kind: (StatefulSet|Ingress|HTTPRoute|TCPRoute|Route|Pod)$' "$rendered"; then
    fail "rendered bundled database, ingress/route or test Pod"
  fi
  grep -q '^  replicas: 1$' "$rendered" || fail "replicas is not 1"
  grep -A1 '^  strategy:$' "$rendered" | grep -q 'type: Recreate' || fail "strategy is not Recreate"
  if grep -E '^[[:space:]]+image:' "$rendered" | grep -vqF "image: \"$FORGEJO_IMAGE\""; then
    fail "rendered image other than $FORGEJO_IMAGE"
  fi
  if grep -q '^  name: forgejo-admin$' "$rendered"; then
    fail "chart rendered an admin Secret instead of using existingSecret"
  fi
  pass "render: single Deployment, replicas=1, Recreate, image=$FORGEJO_IMAGE, no bundled DB/ingress/admin Secret"

  check_config "$(inline_config_ini "$rendered")" "rendered"
}

PF_PID=""
start_port_forward() {
  stop_port_forward
  kubectl -n forgejo port-forward --address 127.0.0.1 svc/forgejo-http "$LOCAL_PORT:3000" >"$ROOT/.tmp/port-forward.log" 2>&1 &
  PF_PID=$!
}
stop_port_forward() {
  if [[ -n "$PF_PID" ]]; then
    kill "$PF_PID" 2>/dev/null || true
    wait "$PF_PID" 2>/dev/null || true
    PF_PID=""
  fi
}

wait_forgejo_healthy() { # LABEL  (/api/healthz는 DB 연결도 확인한다)
  local deadline remaining curl_timeout sleep_for
  deadline=$((SECONDS + 180))
  while (( SECONDS < deadline )); do
    remaining=$((deadline - SECONDS))
    curl_timeout=$((remaining < 5 ? remaining : 5))
    if curl -fsS --max-time "$curl_timeout" "$FORGEJO_URL/api/healthz" >/dev/null 2>&1; then
      pass "$1: Forgejo /api/healthz"
      return 0
    fi
    remaining=$((deadline - SECONDS))
    (( remaining > 0 )) || break
    sleep_for=$((remaining < 2 ? remaining : 2))
    sleep "$sleep_for"
  done
  fail "$1: Forgejo /api/healthz did not pass within 180s"
}

wait_replacement_pod() { # NAMESPACE POD OLD_UID
  local deadline remaining request_timeout uid
  deadline=$((SECONDS + 120))
  while (( SECONDS < deadline )); do
    remaining=$((deadline - SECONDS))
    request_timeout=$((remaining < 5 ? remaining : 5))
    uid="$(kubectl --request-timeout="${request_timeout}s" -n "$1" get pod "$2" -o jsonpath='{.metadata.uid}' 2>/dev/null || true)"
    if [[ -n "$uid" && "$uid" != "$3" ]]; then
      kubectl -n "$1" wait pod "$2" --for=condition=Ready --timeout=300s >/dev/null
      return 0
    fi
    remaining=$((deadline - SECONDS))
    (( remaining > 0 )) || break
    sleep 1
  done
  fail "replacement Pod $1/$2 was not created within 120s"
}

forgejo_pod() { kubectl -n forgejo get pod -l app.kubernetes.io/name=forgejo -o jsonpath='{.items[0].metadata.name}'; }
pod_field() { kubectl -n "$1" get pod "$2" -o jsonpath="$3"; }
pvc_identity() { kubectl -n "$1" get pvc "$2" -o jsonpath='{.metadata.uid}/{.spec.volumeName}'; }
secret_value() { kubectl -n "$1" get secret "$2" -o jsonpath="{.data.$3}" | base64 -d; }

journey() { FORGEJO_URL="$FORGEJO_URL" JOURNEY_DIR="$JOURNEY_DIR" "$JOURNEY" "$@"; }

# Forgejo가 아니라 외부 PostgreSQL에 developer journey metadata가 있는지 직접 조회한다.
check_database_state() { # LABEL
  local counts
  # shellcheck source=/dev/null
  source "$JOURNEY_DIR/state.env"
  # shellcheck source=/dev/null
  source "$JOURNEY_DIR/credentials.env"
  counts="$(kubectl -n postgres exec postgres-0 -c postgres -- psql -U forgejo -d forgejo -tA -F ' ' -c "
    SELECT count(*) FILTER (WHERE i.is_pull), count(*) FILTER (WHERE NOT i.is_pull)
    FROM repository r JOIN \"user\" u ON u.id = r.owner_id LEFT JOIN issue i ON i.repo_id = r.id
    WHERE u.lower_name = '$DEV_USER' AND r.lower_name = 'journey' AND r.is_private")"
  [[ "$counts" == "1 1" ]] || fail "$1: PostgreSQL pull/issue rows for $DEV_USER/journey = '$counts', expected '1 1'"
  pass "$1: PostgreSQL holds private repository + 1 pull request + 1 issue for $DEV_USER/journey"
}

check_repository_data() { # LABEL
  # shellcheck source=/dev/null
  source "$JOURNEY_DIR/credentials.env"
  kubectl -n forgejo exec "$(forgejo_pod)" -c forgejo -- test -d "/data/git/gitea-repositories/$DEV_USER/journey.git" ||
    fail "$1: repository not found on persistent volume"
  pass "$1: repository $DEV_USER/journey.git on /data persistent volume"
}

on_runtime_exit() {
  local rc=$?
  stop_port_forward
  if [[ "$rc" -ne 0 ]]; then diagnostics; fi
}

runtime() {
  "$ROOT/scripts/install-tools.sh" >/dev/null
  [[ -s "$KUBECONFIG" ]] || fail "missing .tmp/kubeconfig; run scripts/local-up.sh first"
  trap on_runtime_exit EXIT

  local server expected_server pod ini listening pvc pg_pvc old_pod new_pod pg_old pg_new restarts secret f
  local -a secrets

  # --- Platform contract ---
  server="$(kubectl version -o json | jq -r .serverVersion.gitVersion)"
  expected_server="${K3S_IMAGE#*:}"
  [[ "$server" == "${expected_server/-k3s/+k3s}" ]] || fail "k3s server $server does not match $K3S_IMAGE"
  pass "k3s server $server"

  kubectl -n postgres rollout status statefulset/postgres --timeout=300s >/dev/null
  [[ "$(pod_field postgres postgres-0 '{.spec.containers[0].image}')" == "$POSTGRES_IMAGE" ]] || fail "PostgreSQL image"
  pass "PostgreSQL ready image=$POSTGRES_IMAGE imageID=$(pod_field postgres postgres-0 '{.status.containerStatuses[0].imageID}')"

  kubectl -n forgejo rollout status deployment/forgejo --timeout=300s >/dev/null
  [[ "$(kubectl -n forgejo get deployment forgejo -o jsonpath='{.spec.replicas}/{.spec.strategy.type}/{.spec.template.spec.containers[0].image}')" \
    == "1/Recreate/$FORGEJO_IMAGE" ]] || fail "Forgejo Deployment replicas/strategy/image"
  pod="$(forgejo_pod)"
  pass "Forgejo ready replicas=1 strategy=Recreate image=$FORGEJO_IMAGE imageID=$(pod_field forgejo "$pod" '{.status.containerStatuses[0].imageID}')"

  for pvc in forgejo/forgejo-data postgres/data-postgres-0; do
    [[ "$(kubectl -n "${pvc%/*}" get pvc "${pvc#*/}" -o jsonpath='{.status.phase}/{.spec.storageClassName}')" == "Bound/local-path" ]] ||
      fail "PVC $pvc is not Bound on local-path"
  done
  [[ "$(pod_field forgejo "$pod" '{.spec.volumes[?(@.name=="data")].persistentVolumeClaim.claimName}')" == forgejo-data ]] ||
    fail "Forgejo /data is not backed by PVC forgejo-data"
  pass "persistent volumes Bound (forgejo-data -> Forgejo /data, data-postgres-0 -> PostgreSQL)"

  start_port_forward
  wait_forgejo_healthy "initial"
  [[ "$(curl -fsS "$FORGEJO_URL/api/v1/version" | jq -r .version)" == "${FORGEJO_IMAGE_TAG%-rootless}"* ]] ||
    fail "Forgejo version is not ${FORGEJO_IMAGE_TAG%-rootless}"
  pass "Forgejo version $(curl -fsS "$FORGEJO_URL/api/v1/version" | jq -r .version)"

  # app.ini에는 secret key/DB password가 있으므로 memory에서만 검사하고 출력/저장하지 않는다.
  ini="$(kubectl -n forgejo exec "$pod" -c forgejo -- cat /data/gitea/conf/app.ini)"
  check_config "$ini" "runtime app.ini"
  unset ini

  listening="$(kubectl -n forgejo exec "$pod" -c forgejo -- cat /proc/net/tcp /proc/net/tcp6 |
    awk '$4 == "0A" { split($2, a, ":"); print a[2] }' | while read -r hex; do echo "$((16#$hex))"; done |
    sort -nu | tr '\n' ' ')"
  [[ " $listening " == *" 3000 "* ]] || fail "Forgejo HTTP is not listening (ports: $listening)"
  [[ " $listening " != *" 2222 "* && " $listening " != *" 22 "* ]] || fail "SSH port is listening (ports: $listening)"
  pass "SSH disabled: Forgejo container listening TCP ports = ${listening% }"

  kubectl -n forgejo exec "$pod" -c forgejo -- test -d /data/queues/common || fail "level queue data dir missing"
  pass "level queue data on persistent volume (/data/queues/common)"

  # --- Developer journey ---
  FORGEJO_ADMIN_USERNAME="$(secret_value forgejo forgejo-admin username)" \
    FORGEJO_ADMIN_PASSWORD="$(secret_value forgejo forgejo-admin password)" journey create
  check_database_state "journey"
  check_repository_data "journey"

  # --- Forgejo workload replacement ---
  old_pod="$(pod_field forgejo "$pod" '{.metadata.uid}')"
  pvc="$(pvc_identity forgejo forgejo-data)"
  kubectl -n forgejo rollout restart deployment/forgejo >/dev/null
  kubectl -n forgejo rollout status deployment/forgejo --timeout=300s >/dev/null
  kubectl -n forgejo wait pod -l app.kubernetes.io/name=forgejo --for=condition=Ready --timeout=300s >/dev/null
  pod="$(forgejo_pod)"
  new_pod="$(pod_field forgejo "$pod" '{.metadata.uid}')"
  [[ "$(kubectl -n forgejo get pod -l app.kubernetes.io/name=forgejo -o name | wc -l)" == 1 ]] || fail "expected one Forgejo Pod"
  [[ "$new_pod" != "$old_pod" ]] || fail "Forgejo Pod was not replaced"
  [[ "$(pvc_identity forgejo forgejo-data)" == "$pvc" ]] || fail "Forgejo PVC changed"
  pass "Forgejo Pod replaced ($old_pod -> $new_pod), same PVC/PV $pvc"
  start_port_forward
  wait_forgejo_healthy "after Forgejo replacement"
  journey verify "after-forgejo-replacement"
  check_repository_data "after Forgejo replacement"

  # --- PostgreSQL workload replacement ---
  old_pod="$(pod_field forgejo "$pod" '{.metadata.uid}')"
  restarts="$(pod_field forgejo "$pod" '{.status.containerStatuses[0].restartCount}')"
  pg_old="$(pod_field postgres postgres-0 '{.metadata.uid}')"
  pg_pvc="$(pvc_identity postgres data-postgres-0)"
  kubectl -n postgres delete pod postgres-0 --wait=true >/dev/null
  wait_replacement_pod postgres postgres-0 "$pg_old"
  pg_new="$(pod_field postgres postgres-0 '{.metadata.uid}')"
  [[ "$pg_new" != "$pg_old" ]] || fail "PostgreSQL Pod was not replaced"
  [[ "$(pvc_identity postgres data-postgres-0)" == "$pg_pvc" ]] || fail "PostgreSQL PVC changed"
  pass "PostgreSQL Pod replaced ($pg_old -> $pg_new), same PVC/PV $pg_pvc"
  wait_forgejo_healthy "after PostgreSQL replacement"
  [[ "$(pod_field forgejo "$pod" '{.metadata.uid}/{.status.containerStatuses[0].restartCount}')" == "$old_pod/$restarts" ]] ||
    fail "Forgejo Pod restarted during PostgreSQL replacement"
  pass "Forgejo reconnected to replaced PostgreSQL without Pod restart"
  check_database_state "after PostgreSQL replacement"
  journey verify "after-postgres-replacement"

  # --- Secret / runtime output hygiene ---
  secrets=(
    "$(secret_value forgejo forgejo-admin password)"
    "$(secret_value forgejo forgejo-db password)"
    "$(secret_value postgres postgres-credentials superuser-password)"
  )
  # shellcheck source=/dev/null
  source "$JOURNEY_DIR/credentials.env"
  secrets+=("$DEV_TOKEN")
  for secret in "${secrets[@]}"; do
    [[ -n "$secret" ]] || fail "empty runtime secret"
  done
  if git -C "$ROOT" grep --untracked -qF -f <(printf '%s\n' "${secrets[@]}"); then
    fail "runtime secret found in Git-visible files"
  fi
  for f in .tmp/kubeconfig .tmp/journey/credentials.env .tmp/journey/state.env .tmp/port-forward.log .tmp/bin/kubectl; do
    git -C "$ROOT" check-ignore -q "$f" || fail "runtime output $f is not gitignored"
  done
  [[ -z "$(git -C "$ROOT" status --porcelain -- .tmp)" ]] || fail "runtime output visible to git status"
  pass "${#secrets[@]} runtime secrets absent from Git-visible files; kubeconfig/credential/temp output gitignored"

  pass "P1 runtime verification complete"
}

diagnostics() {
  echo "----- diagnostics -----" >&2
  kubectl get nodes,pods,pvc,svc -A -o wide >&2 || true
  kubectl get events -A --sort-by=.lastTimestamp 2>/dev/null | tail -n 40 >&2 || true
  kubectl -n forgejo logs deployment/forgejo --all-containers --tail=80 >&2 || true
  kubectl -n postgres logs statefulset/postgres --tail=80 >&2 || true
}

case "$MODE" in
  static) static ;;
  runtime) runtime ;;
  diagnostics) diagnostics ;;
  *) fail "unknown mode: $MODE" ;;
esac
