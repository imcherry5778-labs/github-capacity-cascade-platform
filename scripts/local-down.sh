#!/usr/bin/env bash
# P1 local cluster 전체와 runtime output(kubeconfig, journey state/credential)을 제거하고 잔여 resource가 없는지 확인한다.
#   explicit (make down)                    같은 이름의 cluster를 사용자 권한으로 삭제한다.
#   owned (LOCAL_CLUSTER_OWNERSHIP_MARKER)  local-run.sh가 만든 cluster와 server container ID가 같을 때만 삭제한다.
#                                           cluster 부재가 확인되면 runtime output만 제거한다. ID 불일치, 조회 실패,
#                                           server ID 없는 cluster처럼 ownership이 모호하면 아무것도 건드리지 않고 실패한다.
# Cleanup 권한이 확인되면 cluster 삭제 결과와 무관하게 runtime output을 제거하고, 삭제/잔여 실패는 exit code로 드러낸다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$ROOT/.tmp/bin:$PATH"
CLUSTER=capacity-cascade-local
RUNTIME_OUTPUT=("$ROOT/.tmp/kubeconfig" "$ROOT/.tmp/journey" "$ROOT/.tmp/rendered" "$ROOT/.tmp/port-forward.log")

log() { printf '[local-down] %s\n' "$*"; }
rc=0

"$ROOT/scripts/install-tools.sh" >/dev/null || { echo "pinned tool install failed" >&2; rc=1; }

# local-up.sh의 create와 같은 lock으로 delete를 직렬화한다.
exec 9>"${TMPDIR:-/tmp}/k3d-$CLUSTER.lock"
if ! flock -w 300 9; then
  echo "timed out after 300s waiting for $CLUSTER create/delete lock; nothing removed" >&2
  exit 1
fi

# Owned mode는 k3d가 cluster 부재를 확인했거나, 존재하는 cluster의 server container ID가 marker와 같을 때만 진행한다.
# 조회 실패, server ID 없이 존재하는 cluster, ID 불일치처럼 ownership이 모호하면 아무것도 건드리지 않고 실패한다.
# (k3d cluster get은 부재와 조회 실패를 구분하지 않으므로 존재 여부는 k3d cluster list로 판정한다.)
if [[ -n "${LOCAL_CLUSTER_OWNERSHIP_MARKER:-}" ]]; then
  refuse() { echo "$*; leaving cluster $CLUSTER and runtime output untouched" >&2; exit 1; }
  clusters="$(k3d cluster list -o json)" || refuse "cannot inspect k3d clusters"
  exists="$(jq --arg name "$CLUSTER" 'any(.[]; .name == $name)' <<<"$clusters")" || refuse "cannot parse k3d cluster list"
  if [[ "$exists" == true ]]; then
    server_id="$(docker ps -aq --no-trunc --filter "label=k3d.cluster=$CLUSTER" --filter label=k3d.role=server)" ||
      refuse "cannot inspect cluster ownership"
    [[ -n "$server_id" ]] || refuse "cluster exists but its server identity is unavailable"
    [[ "$server_id" == "$(cat "$LOCAL_CLUSTER_OWNERSHIP_MARKER")" ]] ||
      refuse "cluster (server $server_id) was not created by this invocation"
  elif [[ "$exists" != false ]]; then
    refuse "cannot parse k3d cluster list"
  fi
fi

if k3d cluster get "$CLUSTER" >/dev/null 2>&1; then
  log "deleting k3d cluster $CLUSTER"
  if ! k3d cluster delete "$CLUSTER"; then
    echo "k3d cluster delete $CLUSTER failed" >&2
    rc=1
  fi
else
  log "cluster $CLUSTER not found"
fi

# Cluster 삭제가 실패해도 local credential/runtime output은 반드시 제거한다.
rm -rf "${RUNTIME_OUTPUT[@]}" || rc=1

if k3d cluster get "$CLUSTER" >/dev/null 2>&1; then
  echo "residual k3d cluster: $CLUSTER" >&2
  rc=1
fi
# k3d network에는 k3d.cluster label이 없으므로 이름(k3d-<cluster>)으로 확인한다.
for kind in container volume network; do
  case "$kind" in
    container) args=(ps -a --filter "label=k3d.cluster=$CLUSTER" --format '{{.Names}}') ;;
    volume) args=(volume ls --filter "label=k3d.cluster=$CLUSTER" --format '{{.Name}}') ;;
    network) args=(network ls --filter "name=^k3d-$CLUSTER\$" --format '{{.Name}}') ;;
  esac
  if ! found="$(docker "${args[@]}")"; then
    echo "cannot inspect residual docker $kind" >&2
    rc=1
  elif [[ -n "$found" ]]; then
    echo "residual docker $kind: $found" >&2
    rc=1
  fi
done
if [[ "$rc" -ne 0 ]]; then
  echo "[local-down] FAIL cleanup incomplete for $CLUSTER (runtime output removal attempted)" >&2
  exit "$rc"
fi
log "PASS removed runtime output; no residual cluster/container/volume/network for $CLUSTER"
