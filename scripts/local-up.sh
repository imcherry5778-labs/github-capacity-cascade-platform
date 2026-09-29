#!/usr/bin/env bash
# Fresh disposable k3d cluster를 만들고 PostgreSQL + Argo CD Core로 Forgejo를 배포한다.
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
if [[ -n "${LOCAL_RESTORE_SECRETS_FILE:-}" ]]; then
  [[ -f "$LOCAL_RESTORE_SECRETS_FILE" && "$(stat -c %a "$LOCAL_RESTORE_SECRETS_FILE")" == 600 ]] ||
    { echo "restore secrets must be a mode 0600 file" >&2; exit 1; }
  jq -e 'map(.metadata.namespace + "/" + .metadata.name) | sort ==
    ["forgejo/forgejo-admin","forgejo/forgejo-db","forgejo/forgejo-inline-config","postgres/postgres-credentials"]' \
    "$LOCAL_RESTORE_SECRETS_FILE" >/dev/null || { echo "restore secret inventory mismatch" >&2; exit 1; }
fi

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
# k3d cluster get은 runtime 조회 실패를 부재와 구분하지 않고, k3d cluster create도 같은 판정으로 create를 진행한 뒤
# 실패하면 같은 이름의 cluster node를 rollback 삭제한다. 따라서 local-down.sh와 같이 k3d cluster list가 부재를
# 성공적으로 확인한 경우에만 create한다. 조회/parse 실패는 아무것도 만들거나 지우지 않고 실패한다.
refuse() { echo "$*; not creating or cleaning up" >&2; exit 1; }
clusters="$(k3d cluster list -o json)" || refuse "cannot inspect k3d clusters"
exists="$(jq --arg name "$CLUSTER" 'any(.[]; .name == $name)' <<<"$clusters")" || refuse "cannot parse k3d cluster list"
if [[ "$exists" == true ]]; then
  echo "cluster $CLUSTER already exists; run scripts/local-down.sh first" >&2
  exit 1
elif [[ "$exists" != false ]]; then
  refuse "cannot parse k3d cluster list"
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
if [[ -n "${LOCAL_RESTORE_SECRETS_FILE:-}" ]]; then
  jq '{apiVersion:"v1",kind:"List",items:.}' "$LOCAL_RESTORE_SECRETS_FILE" | kubectl apply -f - >/dev/null
else
  forgejo_db_password="$(random_secret)"
  kubectl -n postgres create secret generic postgres-credentials \
    --from-env-file=<(printf 'superuser-password=%s\nforgejo-password=%s\n' "$(random_secret)" "$forgejo_db_password")
  kubectl -n forgejo create secret generic forgejo-db \
    --from-env-file=<(printf 'password=%s\n' "$forgejo_db_password")
  kubectl -n forgejo create secret generic forgejo-admin \
    --from-env-file=<(printf 'username=platform-admin\npassword=%s\n' "$(random_secret)")
  unset forgejo_db_password
fi

log "deploying PostgreSQL ($POSTGRES_IMAGE)"
kubectl apply -f "$ROOT/platform/local/postgres.yaml"
kubectl -n postgres rollout status statefulset/postgres --timeout=300s

log "installing Argo CD Core $ARGOCD_VERSION ($ARGOCD_COMMIT)"
mkdir -p "$ROOT/.tmp/rendered"
core_manifest="$ROOT/.tmp/rendered/argocd-core.yaml"
curl -fsSL --retry 3 \
  "https://raw.githubusercontent.com/argoproj/argo-cd/$ARGOCD_COMMIT/manifests/core-install.yaml" \
  -o "$core_manifest"
printf '%s  %s\n' "$ARGOCD_CORE_SHA256" "$core_manifest" | sha256sum -c -
kubectl create namespace argocd
kubectl -n argocd apply --server-side --force-conflicts -f "$core_manifest"
for crd in applications.argoproj.io appprojects.argoproj.io; do
  established=false
  for ((i=0;i<90;i++)); do
    if kubectl get crd "$crd" -o json | jq -e \
      'any(.status.conditions[]?; .type == "Established" and .status == "True")' >/dev/null; then
      established=true
      break
    fi
    sleep 2
  done
  [[ "$established" == true ]] || { echo "CRD $crd not Established within 180s" >&2; exit 1; }
done
for component in argocd-redis argocd-repo-server argocd-applicationset-controller; do
  kubectl -n argocd rollout status "deployment/$component" --timeout=300s
done
kubectl -n argocd rollout status statefulset/argocd-application-controller --timeout=300s

log "bootstrapping restricted Forgejo Application"
if [[ -n "${LOCAL_RESTORE_SECRETS_FILE:-}" ]]; then
  # Application을 만들면 autosync가 Forgejo를 시작한다. Restore caller만 완료 후 적용한다.
  log "restore target prepared without Forgejo Application or Pod"
  exit 0
fi
kubectl -n argocd apply -f "$ROOT/platform/argocd/forgejo-local.yaml"
"$ROOT/scripts/local-verify.sh" gitops-ready
kubectl -n forgejo rollout status deployment/forgejo --timeout=300s

log "PASS local platform is up (kubeconfig: .tmp/kubeconfig)"
