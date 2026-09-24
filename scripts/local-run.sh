#!/usr/bin/env bash
# Fresh local lifecycle orchestration (make local).
# Ownership contract: local-up.sh가 create/delete lock 안에서 cluster 부재를 확인하고 create에 성공했을 때만
# 이 invocation 전용 marker에 server container ID가 기록된다. Marker가 있을 때만 종료 시(성공/실패 모두)
# 자신이 만든 cluster를 cleanup한다. Lock 획득 실패, 기존 cluster, create 실패처럼 ownership을 얻지 못한
# invocation은 cluster도 runtime output도 cleanup하지 않는다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER=capacity-cascade-local

marker="$(mktemp)"

on_exit() {
  local rc="$1" cleanup_rc=0
  trap - EXIT
  set +e
  if [[ -s "$marker" ]]; then
    LOCAL_CLUSTER_OWNERSHIP_MARKER="$marker" "$ROOT/scripts/local-down.sh"
    cleanup_rc=$?
  else
    echo "[local-run] this invocation did not create $CLUSTER; no automatic cleanup" >&2
  fi
  rm -f "$marker"
  if [[ "$rc" -eq 0 && "$cleanup_rc" -ne 0 ]]; then
    rc=$cleanup_rc
  fi
  exit "$rc"
}
trap 'on_exit $?' EXIT

LOCAL_CLUSTER_OWNERSHIP_MARKER="$marker" "$ROOT/scripts/local-up.sh"
"$ROOT/scripts/local-verify.sh" runtime
