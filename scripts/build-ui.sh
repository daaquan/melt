#!/usr/bin/env bash
# Builds ui/ (Dioxus) into src/melt/static/ui/, which the wheel ships and the
# API serves. Run it after any change under ui/ and commit the result, so
# `pip install` and `docker compose up` stay toolchain-free.
#
#   scripts/build-ui.sh            build and install into src/melt/static/ui
#   scripts/build-ui.sh --check    fail if the committed bundle is stale
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRATE="$ROOT/ui"
OUT="$ROOT/src/melt/static/ui"
TARGET="wasm32-unknown-unknown"
TOOLS="$CRATE/.tools"

check_only=0
[[ "${1:-}" == "--check" ]] && check_only=1

have() { command -v "$1" >/dev/null 2>&1; }

have cargo || { echo "build-ui: cargo not found; install Rust from https://rustup.rs" >&2; exit 1; }

# Every cargo/rustup call runs from inside the crate so ui/rust-toolchain.toml
# is the one that decides the compiler. rustup only reads that file relative to
# the working directory, never from --manifest-path.
if ! (cd "$CRATE" && rustup target list --installed 2>/dev/null | grep -qx "$TARGET"); then
  echo "build-ui: adding the $TARGET target"
  (cd "$CRATE" && rustup target add "$TARGET")
fi

# wasm-bindgen's CLI and the wasm-bindgen crate must be the same version or the
# generated glue will not match the module, so read it out of the lockfile.
wb_version="$(
  awk '/^name = "wasm-bindgen"$/ { found = 1; next }
       found && /^version = / { gsub(/[",]/, "", $3); print $3; exit }' "$CRATE/Cargo.lock"
)"
[[ -n "$wb_version" ]] || { echo "build-ui: no wasm-bindgen version in ui/Cargo.lock" >&2; exit 1; }

resolve_wasm_bindgen() {
  if [[ -n "${MELT_WASM_BINDGEN:-}" ]]; then
    echo "$MELT_WASM_BINDGEN"
    return
  fi
  if have wasm-bindgen && [[ "$(wasm-bindgen --version)" == "wasm-bindgen $wb_version" ]]; then
    command -v wasm-bindgen
    return
  fi
  local cached="$TOOLS/wasm-bindgen-$wb_version"
  if [[ ! -x "$cached" ]]; then
    local triple="x86_64-unknown-linux-musl"
    case "$(uname -s)-$(uname -m)" in
      Darwin-arm64)  triple="aarch64-apple-darwin" ;;
      Darwin-x86_64) triple="x86_64-apple-darwin" ;;
      Linux-aarch64) triple="aarch64-unknown-linux-gnu" ;;
    esac
    local name="wasm-bindgen-$wb_version-$triple"
    local url="https://github.com/rustwasm/wasm-bindgen/releases/download/$wb_version/$name.tar.gz"
    echo "build-ui: fetching wasm-bindgen $wb_version" >&2
    mkdir -p "$TOOLS"
    curl -sSfL "$url" | tar xz -C "$TOOLS"
    mv "$TOOLS/$name/wasm-bindgen" "$cached"
    rm -rf "$TOOLS/$name"
  fi
  echo "$cached"
}

WASM_BINDGEN="$(resolve_wasm_bindgen)"

(cd "$CRATE" && cargo build --target "$TARGET" --release)

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

"$WASM_BINDGEN" \
  --target web \
  --no-typescript \
  --out-name melt \
  --out-dir "$stage" \
  "$CRATE/target/$TARGET/release/melt-ui.wasm"

# No wasm-opt pass on purpose. The bundle is committed and CI rebuilds it to
# diff, so the output has to be the same bytes everywhere; a binaryen that only
# some machines have installed would break that. opt-level="z" plus LTO in
# ui/Cargo.toml already does most of the shrinking.

# Hand-written loaders live in ui/web/ and ride along into the bundle, so
# everything under src/melt/static/ui is reproducible from this script.
cp "$CRATE"/web/*.js "$stage/"

if [[ "$check_only" == 1 ]]; then
  if diff -r --brief "$OUT" "$stage" >/dev/null 2>&1; then
    echo "build-ui: committed bundle is current"
    exit 0
  fi
  echo "build-ui: src/melt/static/ui is stale; run scripts/build-ui.sh and commit" >&2
  diff -r --brief "$OUT" "$stage" >&2 || true
  exit 1
fi

mkdir -p "$(dirname "$OUT")"
rm -rf "$OUT"
cp -R "$stage" "$OUT"
# mktemp -d is 0700; the bundle has to stay readable for a non-root container.
chmod -R a+rX "$OUT"
echo "build-ui: wrote $OUT ($(du -h "$OUT/melt_bg.wasm" | cut -f1) wasm)"
