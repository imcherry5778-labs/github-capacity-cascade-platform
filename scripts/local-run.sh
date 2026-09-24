#!/usr/bin/env bash
# Fresh local lifecycle orchestration. 기존 cluster를 소유하지 않은 상태에서는 절대 cleanup하지 않는다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$ROOT/.tmp/bin:$PATH"
CLUSTER=capacity-cascade-local

"$ROOT/scripts/install-tools.sh" >/dev/null

# 이 invocation이 시작하기 전에 존재한 cluster는 명시적 사용자 상태다.
# local-up.sh도 같은 guard를 가지지만, cleanup trap을 설치하기 전에 ownership boundary를 확인한다.
if k3d cluster get "$CLUSTER" >/dev/null 2>&1; then
  echo "cluster $CLUSTER already exists; run make down explicitly first" >&2
  exit 1
fi

on_exit() {
  local rc="$1" cleanup_rc
  trap - EXIT
  set +e
  "$ROOT/scripts/local-down.sh"
  cleanup_rc=$?
  if [[ "$rc" -eq 0 && "$cleanup_rc" -ne 0 ]]; then
    rc=$cleanup_rc
  fi
  exit "$rc"
}
trap 'on_exit $?' EXIT

"$ROOT/scripts/local-up.sh"
"$ROOT/scripts/local-verify.sh" runtime
