#!/usr/bin/env bash
# P1 local cluster 전체와 runtime output(kubeconfig, journey state/credential)을 제거하고 잔여 resource가 없는지 확인한다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$ROOT/.tmp/bin:$PATH"
CLUSTER=capacity-cascade-local

log() { printf '[local-down] %s\n' "$*"; }

"$ROOT/scripts/install-tools.sh" >/dev/null

if k3d cluster get "$CLUSTER" >/dev/null 2>&1; then
  log "deleting k3d cluster $CLUSTER"
  k3d cluster delete "$CLUSTER"
else
  log "cluster $CLUSTER not found"
fi
rm -rf "$ROOT/.tmp/kubeconfig" "$ROOT/.tmp/journey" "$ROOT/.tmp/rendered" "$ROOT/.tmp/port-forward.log"

residual=0
if k3d cluster get "$CLUSTER" >/dev/null 2>&1; then
  echo "residual k3d cluster: $CLUSTER" >&2
  residual=1
fi
# k3d network에는 k3d.cluster label이 없으므로 이름(k3d-<cluster>)으로 확인한다.
for kind in container volume network; do
  case "$kind" in
    container) found="$(docker ps -a --filter "label=k3d.cluster=$CLUSTER" --format '{{.Names}}')" ;;
    volume) found="$(docker volume ls --filter "label=k3d.cluster=$CLUSTER" --format '{{.Name}}')" ;;
    network) found="$(docker network ls --filter "name=^k3d-$CLUSTER\$" --format '{{.Name}}')" ;;
  esac
  if [[ -n "$found" ]]; then
    echo "residual docker $kind: $found" >&2
    residual=1
  fi
done
if [[ "$residual" -ne 0 ]]; then
  exit 1
fi
log "PASS no residual cluster/container/volume/network for $CLUSTER"
