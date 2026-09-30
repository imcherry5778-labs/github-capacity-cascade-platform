#!/usr/bin/env bash
# Local-only upstream Istio distribution with recorded release checksum.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=versions.env
source "$ROOT/versions.env"
[[ "$(uname -s)/$(uname -m)" == Linux/x86_64 ]] || { echo 'P4-W1 fixture requires Linux/amd64' >&2; exit 1; }
dist="$ROOT/.tmp/p4-tools/istio-$ISTIO_VERSION"
if [[ ! -x "$dist/bin/istioctl" ]]; then
  mkdir -p "$ROOT/.tmp/p4-tools"
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  curl -fsSL --retry 3 --max-time 180 \
    "https://github.com/istio/istio/releases/download/$ISTIO_VERSION/istio-$ISTIO_VERSION-linux-amd64.tar.gz" -o "$work/istio.tgz"
  printf '%s  %s\n' "$ISTIO_LINUX_AMD64_SHA256" "$work/istio.tgz" | sha256sum -c - >/dev/null
  tar -xzf "$work/istio.tgz" -C "$ROOT/.tmp/p4-tools"
fi
[[ "$("$dist/bin/istioctl" version --remote=false -o json | jq -r .clientVersion.version)" == "$ISTIO_VERSION" ]]
