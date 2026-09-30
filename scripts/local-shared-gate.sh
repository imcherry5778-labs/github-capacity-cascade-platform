#!/usr/bin/env bash
# P4-W1 healthy fixture + same-cluster removal, after P1/P2/P3 normal checks.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=versions.env
source "$ROOT/versions.env"
export PATH="$ROOT/.tmp/bin:$PATH" KUBECONFIG="$ROOT/.tmp/kubeconfig"
: "${LOCAL_CLUSTER_OWNERSHIP_MARKER:?requires invocation-owned local-run}"
: "${SHARED_GATE_BASELINE_RESULT:?requires current invocation baseline}"
DIRECT=http://127.0.0.1:13000
GATED=http://127.0.0.1:18080
validator="$ROOT/scripts/validate-shared-gate.py"
istioctl="$ROOT/.tmp/p4-tools/istio-$ISTIO_VERSION/bin/istioctl"
pf_direct="" pf_gate="" work=""

fail() { echo "[shared-gate] FAIL $*" >&2; exit 1; }
owned_cluster() {
  local server
  server="$(docker ps -aq --no-trunc --filter label=k3d.cluster=capacity-cascade-local --filter label=k3d.role=server)" ||
    fail 'cannot inspect cluster ownership'
  [[ -n "$server" && "$server" == "$(cat "$LOCAL_CLUSTER_OWNERSHIP_MARKER")" ]] ||
    fail 'fixture cluster was not created by this invocation'
}
on_exit() {
  local rc=$?
  trap - EXIT
  if [[ "$rc" -ne 0 && "${fixture_up:-false}" == true && ! -e "$out/checks.jsonl" ]]; then
    python3 "$validator" capture "$out" >"$out/path.json" || true
  fi
  for pid in "$pf_direct" "$pf_gate"; do
    if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
  done
  if [[ -n "$work" ]]; then rm -rf "$work"; fi
  if [[ "$rc" -ne 0 && -n "${out:-}" ]]; then
    jq -nc --arg after "${phase:-start}" '{phase:"failure",outcome:"failed",after_phase:$after}' >>"$out/phases.jsonl"
  fi
  exit "$rc"
}
trap on_exit EXIT
phase() { phase="$1"; jq -nc --arg phase "$phase" --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --argjson elapsed "$SECONDS" '{phase:$phase,outcome:"success",timestamp_utc:$ts,elapsed_seconds:$elapsed}' >>"$out/phases.jsonl"; }
wait_http() {
  local deadline=$((SECONDS + 180))
  while (( SECONDS < deadline )); do
    if curl -fsS --retry 0 --max-time 3 "$1/api/healthz" >/dev/null 2>&1; then return; fi
    sleep 2
  done
  fail 'endpoint readiness timeout'
}
journey() {
  local label="$1" endpoint="$2"
  FORGEJO_URL="$DIRECT" JOURNEY_ENDPOINT_URL="$endpoint" JOURNEY_GATE_CORRELATION=1 \
    JOURNEY_DIR="$ROOT/.tmp/journey" RESULTS_ROOT="$out/$label" RESULT_CONTEXT_FILE="$work/context.json" \
    FORGEJO_ADMIN_USERNAME="$(kubectl -n forgejo get secret forgejo-admin -o jsonpath='{.data.username}' | base64 -d)" \
    FORGEJO_ADMIN_PASSWORD="$(kubectl -n forgejo get secret forgejo-admin -o jsonpath='{.data.password}' | base64 -d)" \
    "$ROOT/tests/e2e/forgejo-developer-journey.sh" create
}
stable_snapshot() {
  kubectl -n forgejo get deployment/forgejo service/forgejo-http -o json |
    jq -S '[.items[] | {kind,uid:.metadata.uid,spec}]' >"$1"
}

owned_cluster
[[ -f "$SHARED_GATE_BASELINE_RESULT" ]] || fail 'direct baseline absent'
"$ROOT/scripts/install-shared-gate.sh"
id="$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')"
out="$ROOT/results/local/shared-gate-$id"
mkdir -m 0700 "$out"
work="$(mktemp -d "$ROOT/.tmp/shared-gate.XXXXXX")"
sha="$(git -C "$ROOT" rev-parse HEAD)" dirty=false
[[ -z "$(git -C "$ROOT" status --porcelain)" ]] || dirty=true
jq -n --arg sha "$sha" --argjson dirty "$dirty" '{sha:$sha,dirty:$dirty}' >"$out/source.json"
phase start
cp "$SHARED_GATE_BASELINE_RESULT" "$out/direct-baseline.json"
context_source="$(find "$(dirname "$SHARED_GATE_BASELINE_RESULT")" -name events.jsonl -print -quit)"
[[ -n "$context_source" ]] || fail 'direct baseline run context absent'
sed -n 1p "$context_source" | jq 'del(.record,.schema_version,.run_id,.phase,.started_at_utc,.scenario,.parameters,.measurement_boundary)' >"$work/context.json"
jq -e --arg sha "$sha" --argjson dirty "$dirty" '.source_sha == $sha and .dirty == $dirty' "$work/context.json" >/dev/null || fail 'baseline source differs'
kubectl -n forgejo port-forward --address 127.0.0.1 svc/forgejo-http 13000:3000 >"$work/direct.log" 2>&1 &
pf_direct=$!
wait_http "$DIRECT"
stable_snapshot "$work/stable-before.json"
phase direct-baseline

# Only a mesh-free, fresh owned Local cluster can host this temporary control plane.
[[ "$(kubectl get ns -o json | jq '[.items[] | select(.metadata.name == "istio-system" or .metadata.name == "shared-gate")] | length')" == 0 ]] || fail 'fixture namespaces already exist'
[[ "$(kubectl get crd -o json | jq '[.items[] | select(.spec.group | endswith("istio.io"))] | length')" == 0 ]] || fail 'preexisting Istio CRDs'
[[ "$(kubectl get crd -o json | jq '[.items[] | select(.spec.group == "gateway.networking.k8s.io")] | length')" == 0 ]] || fail 'unexpected Gateway API CRDs'
export EXT_AUTHZ_IMAGE="ext-authz-sim:$id"
docker build --build-arg "BASE_IMAGE=$EXT_AUTHZ_BASE_IMAGE" -t "$EXT_AUTHZ_IMAGE" "$ROOT/cmd/ext-authz-sim" >"$work/build.log" 2>&1
k3d image import "$EXT_AUTHZ_IMAGE" -c capacity-cascade-local >"$work/import.log" 2>&1
docker image inspect "$EXT_AUTHZ_IMAGE" --format '{{.Id}}' | jq -Rs --arg base "$EXT_AUTHZ_BASE_IMAGE" '{image_id:(.|rtrimstr("\n")),base_image:$base}' >"$out/app-image.json"
python3 "$validator" render "$work"
"$istioctl" manifest generate -f "$work/istio.yaml" >"$work/control-plane.yaml"
kubectl create namespace shared-gate >/dev/null
"$istioctl" install -y -f "$work/istio.yaml" --verify --readiness-timeout 300s
kubectl apply -f "$work/resources.yaml" >/dev/null
fixture_up=true
kubectl annotate -f "$work/control-plane.yaml" -f "$work/resources.yaml" "shared-gate-owner=$id" --overwrite >/dev/null
kubectl get -f "$work/control-plane.yaml" -f "$work/resources.yaml" -o json |
  jq '[.items[] | {kind,apiVersion,name:.metadata.name,namespace:(.metadata.namespace // ""),uid:.metadata.uid,owner:.metadata.annotations["shared-gate-owner"]}] | unique' >"$work/owned.json"
cp "$work/owned.json" "$out/owned-resources.json"
for deploy in p4-ingress haproxy ext-authz-sim; do
  kubectl -n shared-gate rollout status "deployment/$deploy" --timeout=300s
done
cp "$work/istio.yaml" "$out/istio-source.yaml"
cp "$work/resources.yaml" "$out/fixture-source.yaml"
phase install
kubectl -n shared-gate port-forward --address 127.0.0.1 svc/p4-ingress 18080:8080 >"$work/gated.log" 2>&1 &
pf_gate=$!
wait_http "$GATED"
python3 "$validator" runtime >"$out/runtime.json"
phase configuration

# GET remains non-mutating. Sentinel credentials/body exercise check exclusion.
status="$(curl -sS --retry 0 --max-time 10 -X GET -D "$work/deny.headers" -o "$work/deny.body" -w '%{http_code}' \
  -H 'x-gate-test-deny: true' -H 'Authorization: Bearer p4-exclusion-sentinel' \
  -H 'Cookie: p4-exclusion-sentinel' --data-binary 'p4-body-exclusion-sentinel' "$GATED/api/v1/version")"
decision="$(awk 'tolower($1) == "x-gate-decision:" {gsub("\r", "", $2); print $2}' "$work/deny.headers")"
jq -n --argjson status "$status" --arg decision "$decision" --argjson size "$(wc -c <"$work/deny.body")" \
  '{status:$status,decision_header:$decision,body_bytes:$size,sentinel_credentials_and_body_sent:true}' >"$out/deny.json"
[[ "$status/$decision" == 403/DENY ]] || fail 'controlled DENY did not block'
# Prove credential/body exclusion before sending actual developer credentials.
python3 "$validator" probe
phase deny
journey gated "$GATED"
phase gated
python3 "$validator" capture "$out" >"$out/path.json"

# Prove identity before deleting exact manifests. Never use blanket Istio purge.
owned_cluster
kubectl get -f "$work/control-plane.yaml" -f "$work/resources.yaml" -o json |
  jq '[.items[] | {kind,apiVersion,name:.metadata.name,namespace:(.metadata.namespace // ""),uid:.metadata.uid,owner:.metadata.annotations["shared-gate-owner"]}] | unique' >"$work/current.json"
cmp "$work/owned.json" "$work/current.json" || fail 'fixture ownership changed; not removing'
kill "$pf_gate"; wait "$pf_gate" 2>/dev/null || true; pf_gate=""
kubectl delete -f "$work/resources.yaml" --ignore-not-found --timeout=180s >/dev/null
kubectl delete -f "$work/control-plane.yaml" --ignore-not-found --timeout=180s >/dev/null
kubectl delete namespace istio-system --ignore-not-found --timeout=180s >/dev/null
[[ "$(kubectl get ns -o json | jq '[.items[] | select(.metadata.name == "istio-system" or .metadata.name == "shared-gate")] | length')" == 0 ]] || fail 'fixture namespaces remain'
[[ "$(kubectl get crd -o json | jq '[.items[] | select(.spec.group | endswith("istio.io"))] | length')" == 0 ]] || fail 'Istio CRDs remain'
python3 - "$work/owned.json" <<'PY'
import json, subprocess, sys
for r in json.load(open(sys.argv[1])):
    if r['namespace'] or r['kind'] == 'Namespace':
        continue  # Namespaces are already proven absent.
    group = r['apiVersion'].split('/')[0] if '/' in r['apiVersion'] else ''
    kind = r['kind'] + ('.' + group if group else '')
    result = subprocess.check_output(['kubectl', '--request-timeout=10s', 'get', kind, r['name'], '--ignore-not-found', '-o', 'name'], text=True)
    assert not result.strip(), 'experiment cluster-scoped resource remains'
PY
if curl -sS --retry 0 --max-time 3 "$GATED/api/healthz" >/dev/null 2>&1; then fail 'reliability endpoint still exists'; fi
stable_snapshot "$work/stable-after.json"
cmp "$work/stable-before.json" "$work/stable-after.json" || fail 'stable Forgejo identity/spec changed'
"$ROOT/scripts/local-verify.sh" gitops-ready
wait_http "$DIRECT"
jq -n '{namespaces_absent:true,istio_crds_absent:true,owned_cluster_resources_absent:true,
  reliability_endpoint_absent:true,stable_forgejo_spec_and_uid_unchanged:true,argo_synced_healthy:true,
  same_owned_cluster:true}' >"$out/removal.json"
phase remove
journey post-removal "$DIRECT"
phase post-removal
args=()
[[ "$dirty" != true ]] || args+=(--exploratory)
python3 "$validator" result "$out" "${args[@]}" >"$out/result.json"
echo "[shared-gate] completed healthy fixture and same-cluster removal; source_dirty=$dirty; evidence=$out"
