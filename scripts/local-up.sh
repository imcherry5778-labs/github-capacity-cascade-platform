#!/usr/bin/env bash
# Fresh disposable k3d cluster를 만들고 local PostgreSQL + Forgejo를 배포한다.
# Credential은 실행 시 생성해 cluster Secret으로만 전달하며 Git/source values에 남기지 않는다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=versions.env
source "$ROOT/versions.env"
export PATH="$ROOT/.tmp/bin:$PATH"
export KUBECONFIG="$ROOT/.tmp/kubeconfig"
CLUSTER=capacity-cascade-local

log() { printf '[local-up] %s\n' "$*"; }

"$ROOT/scripts/install-tools.sh"

# 고정 이름 cluster의 create/delete는 checkout과 무관하게 같은 host의 모든 invocation 사이에서 하나의 lock으로
# 직렬화한다(local-down.sh와 같은 lock). k3d의 부재 확인과 create는 atomic하지 않고, create 실패 rollback은
# 같은 이름의 다른 invocation cluster node까지 삭제하므로 k3d create 자체가 동시에 실행되면 안 된다.
# Lock을 즉시 얻지 못하면 다른 invocation이 create/delete 중이므로 아무것도 만들거나 지우지 않고 실패한다.
exec 9>"${TMPDIR:-/tmp}/k3d-$CLUSTER.lock"
if ! flock -n 9; then
  echo "another $CLUSTER create/delete is in progress; not creating or cleaning up" >&2
  exit 1
fi

# Fresh lifecycle만 허용한다. 기존 cluster를 재사용하거나 덮어쓰지 않는다.
if k3d cluster get "$CLUSTER" >/dev/null 2>&1; then
  echo "cluster $CLUSTER already exists; run scripts/local-down.sh first" >&2
  exit 1
fi

log "creating k3d cluster $CLUSTER ($K3S_IMAGE)"
k3d cluster create --config "$ROOT/platform/local/k3d.yaml"
# Lock 안에서 부재를 확인하고 create에 성공한 이 invocation만 cleanup ownership을 얻는다.
# local-run.sh가 marker path를 전달하면 이 cluster의 server container ID를 ownership identity로 기록한다.
if [[ -n "${LOCAL_CLUSTER_OWNERSHIP_MARKER:-}" ]]; then
  server_id="$(docker ps -aq --no-trunc --filter "label=k3d.cluster=$CLUSTER" --filter label=k3d.role=server)"
  [[ -n "$server_id" ]] || { echo "created cluster $CLUSTER has no server container" >&2; exit 1; }
  printf '%s\n' "$server_id" >"$LOCAL_CLUSTER_OWNERSHIP_MARKER"
fi
exec 9>&-
( umask 077 && k3d kubeconfig get "$CLUSTER" >"$KUBECONFIG" )
kubectl wait node --all --for=condition=Ready --timeout=180s
# k3s는 bundled addon을 cluster 시작 후 비동기로 생성한다.
kubectl -n kube-system wait deployment/local-path-provisioner --for=create --timeout=180s
kubectl -n kube-system rollout status deployment/local-path-provisioner --timeout=180s

random_secret() { od -An -N24 -tx1 /dev/urandom | tr -d ' \n'; }

log "creating runtime credentials"
kubectl create namespace postgres
kubectl create namespace forgejo
forgejo_db_password="$(random_secret)"
kubectl -n postgres create secret generic postgres-credentials \
  --from-env-file=<(printf 'superuser-password=%s\nforgejo-password=%s\n' "$(random_secret)" "$forgejo_db_password")
kubectl -n forgejo create secret generic forgejo-db \
  --from-env-file=<(printf 'password=%s\n' "$forgejo_db_password")
kubectl -n forgejo create secret generic forgejo-admin \
  --from-env-file=<(printf 'username=platform-admin\npassword=%s\n' "$(random_secret)")
unset forgejo_db_password

log "deploying PostgreSQL ($POSTGRES_IMAGE)"
kubectl apply -f "$ROOT/platform/local/postgres.yaml"
kubectl -n postgres rollout status statefulset/postgres --timeout=300s

log "deploying Forgejo chart $FORGEJO_CHART_VERSION ($FORGEJO_IMAGE_TAG)"
helm upgrade --install forgejo "$FORGEJO_CHART" --version "$FORGEJO_CHART_VERSION" \
  --namespace forgejo \
  -f "$ROOT/platform/forgejo/values-common.yaml" \
  -f "$ROOT/platform/forgejo/values-local.yaml" \
  --wait --timeout 10m
kubectl -n forgejo rollout status deployment/forgejo --timeout=300s

log "PASS local platform is up (kubeconfig: .tmp/kubeconfig)"
