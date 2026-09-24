#!/usr/bin/env bash
# versions.env의 pinned k3d/kubectl/helm을 repository-local .tmp/bin에 설치한다.
# Global developer environment는 변경하지 않으며, upstream이 publish한 SHA-256으로 검증한다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=versions.env
source "$ROOT/versions.env"
BIN="$ROOT/.tmp/bin"
mkdir -p "$BIN"

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$(uname -m)" in
  x86_64 | amd64) arch=amd64 ;;
  aarch64 | arm64) arch=arm64 ;;
  *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

sha256_of() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | awk '{print $1}'; else shasum -a 256 "$1" | awk '{print $1}'; fi
}

verify_sha256() { # file expected
  local actual
  actual="$(sha256_of "$1")"
  if [[ "$actual" != "$2" ]]; then
    echo "checksum mismatch for $1: expected $2, got $actual" >&2
    exit 1
  fi
}

fetch() { curl -fsSL --retry 3 -o "$2" "$1"; }

if [[ "$("$BIN/k3d" version 2>/dev/null | awk '/^k3d version/ {print $3}')" != "$K3D_VERSION" ]]; then
  base="https://github.com/k3d-io/k3d/releases/download/$K3D_VERSION"
  fetch "$base/k3d-$os-$arch" "$work/k3d"
  fetch "$base/checksums.txt" "$work/k3d.checksums"
  verify_sha256 "$work/k3d" "$(awk -v f="_dist/k3d-$os-$arch" '$2 == f {print $1}' "$work/k3d.checksums")"
  install -m 0755 "$work/k3d" "$BIN/k3d"
fi

if [[ "$("$BIN/kubectl" version --client -o json 2>/dev/null | jq -r .clientVersion.gitVersion)" != "$KUBECTL_VERSION" ]]; then
  base="https://dl.k8s.io/release/$KUBECTL_VERSION/bin/$os/$arch"
  fetch "$base/kubectl" "$work/kubectl"
  fetch "$base/kubectl.sha256" "$work/kubectl.sha256"
  verify_sha256 "$work/kubectl" "$(awk '{print $1}' "$work/kubectl.sha256")"
  install -m 0755 "$work/kubectl" "$BIN/kubectl"
fi

if [[ "$("$BIN/helm" version --template '{{.Version}}' 2>/dev/null)" != "$HELM_VERSION" ]]; then
  archive="helm-$HELM_VERSION-$os-$arch.tar.gz"
  fetch "https://get.helm.sh/$archive" "$work/$archive"
  fetch "https://get.helm.sh/$archive.sha256sum" "$work/$archive.sha256sum"
  verify_sha256 "$work/$archive" "$(awk '{print $1}' "$work/$archive.sha256sum")"
  tar -xzf "$work/$archive" -C "$work" "$os-$arch/helm"
  install -m 0755 "$work/$os-$arch/helm" "$BIN/helm"
fi

# k3d는 version 두 줄을 별도 write로 출력하므로 head가 먼저 종료하면 SIGPIPE(141)가 pipefail로 실패가 된다.
# 입력을 끝까지 읽는 sed로 첫 줄만 출력한다.
"$BIN/k3d" version | sed -n 1p
echo "kubectl $("$BIN/kubectl" version --client -o json | jq -r .clientVersion.gitVersion)"
echo "helm $("$BIN/helm" version --template '{{.Version}}')"
