#!/usr/bin/env bash
# build-xcframework.sh — assemble Fantastic.xcframework for SPM.
#
# Cross-compiles fantastic-uniffi for every Apple slice the app
# needs, runs uniffi-bindgen to emit Swift bindings, then bundles
# the static libs + bindings into an XCFramework that the
# packaging/FantasticKernel/ Swift package consumes.
#
# Requires:
#   - macOS host (uses xcodebuild)
#   - rustup toolchain with the Apple targets installed
#   - uniffi-bindgen-cli (`cargo install uniffi-bindgen-cli`)
#
# Output: rust/packaging/FantasticKernel/Fantastic.xcframework
#         + rust/packaging/FantasticKernel/Sources/FantasticKernel/fantastic.swift

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUST_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PKG_DIR="$RUST_ROOT/packaging/FantasticKernel"
XCF_OUT="$PKG_DIR/Fantastic.xcframework"

TARGETS_DEVICE=("aarch64-apple-ios")
# `x86_64-apple-ios-sim` was removed from upstream Rust stable
# (Intel-Mac iOS simulator has been phased out by Apple + rustc).
# The simulator slice is Apple-Silicon-only going forward.
TARGETS_SIM=("aarch64-apple-ios-sim")
TARGETS_MAC=("aarch64-apple-darwin" "x86_64-apple-darwin")

# Sanity checks.
command -v rustup >/dev/null || { echo "build-xcframework: rustup missing"; exit 2; }
command -v xcodebuild >/dev/null || { echo "build-xcframework: xcodebuild missing (need macOS host)"; exit 2; }
command -v uniffi-bindgen >/dev/null || {
    echo "build-xcframework: uniffi-bindgen not installed. Run:"
    echo "    cargo install uniffi-bindgen-cli"
    exit 2
}

# Ensure every target is installed.
for t in "${TARGETS_DEVICE[@]}" "${TARGETS_SIM[@]}" "${TARGETS_MAC[@]}"; do
    rustup target add "$t" >/dev/null 2>&1 || true
done

cd "$RUST_ROOT"

# Build each slice.
echo "[xcf] building static libs..."
for t in "${TARGETS_DEVICE[@]}" "${TARGETS_SIM[@]}" "${TARGETS_MAC[@]}"; do
    cargo build --release --target "$t" -p fantastic-uniffi
done

# Bind once (Swift output is target-agnostic).
echo "[xcf] generating Swift bindings..."
BINDINGS_DIR="$(mktemp -d)"
trap 'rm -rf "$BINDINGS_DIR"' EXIT
uniffi-bindgen generate \
    "$RUST_ROOT/crates/fantastic-uniffi/src/fantastic.udl" \
    --language swift \
    --out-dir "$BINDINGS_DIR"

# Stage modulemap + module.modulemap so xcodebuild groups headers correctly.
HEADERS_DIR="$BINDINGS_DIR/Headers"
mkdir -p "$HEADERS_DIR"
mv "$BINDINGS_DIR/fantasticFFI.h" "$HEADERS_DIR/" 2>/dev/null || true
cat >"$HEADERS_DIR/module.modulemap" <<'MMAP'
module fantasticFFI {
    header "fantasticFFI.h"
    export *
}
MMAP

# Stage the iOS simulator slice. Used to lipo arm64-sim + x86_64-sim,
# but Intel-Mac iOS simulator was removed from rustc stable; just
# rename the arm64-sim lib for xcodebuild.
echo "[xcf] iOS sim slice (Apple Silicon only)..."
SIM_FAT="$BINDINGS_DIR/libfantastic_uniffi-iossim.a"
cp "$RUST_ROOT/target/aarch64-apple-ios-sim/release/libfantastic_uniffi.a" "$SIM_FAT"

echo "[xcf] lipo macOS slices..."
MAC_FAT="$BINDINGS_DIR/libfantastic_uniffi-macos.a"
lipo -create \
    "$RUST_ROOT/target/aarch64-apple-darwin/release/libfantastic_uniffi.a" \
    "$RUST_ROOT/target/x86_64-apple-darwin/release/libfantastic_uniffi.a" \
    -output "$MAC_FAT"

# Build the XCFramework.
echo "[xcf] xcodebuild -create-xcframework..."
rm -rf "$XCF_OUT"
mkdir -p "$PKG_DIR"
xcodebuild -create-xcframework \
    -library "$RUST_ROOT/target/aarch64-apple-ios/release/libfantastic_uniffi.a" \
      -headers "$HEADERS_DIR" \
    -library "$SIM_FAT" \
      -headers "$HEADERS_DIR" \
    -library "$MAC_FAT" \
      -headers "$HEADERS_DIR" \
    -output "$XCF_OUT"

# Drop Swift bindings into the SPM package's Sources dir.
SOURCES_DIR="$PKG_DIR/Sources/FantasticKernel"
mkdir -p "$SOURCES_DIR"
cp "$BINDINGS_DIR/fantastic.swift" "$SOURCES_DIR/"

echo
echo "[xcf] ✓ built $XCF_OUT"
echo "[xcf] ✓ Swift bindings at $SOURCES_DIR/fantastic.swift"
