#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# macOS build script for Fantastic Canvas Electron app.
#
# Prerequisites:
#   - Node.js 20+
#   - npm install (in electron/)
#   - For signing: set APPLE_IDENTITY, APPLE_ID, APPLE_PASSWORD, APPLE_TEAM_ID
#     OR: KEYCHAIN_PROFILE (from `notarytool store-credentials`)
#
# Usage:
#   ./mac/build.sh              # build unsigned (dev)
#   ./mac/build.sh --sign       # build + sign + notarize
#   ./mac/build.sh --dmg        # build DMG
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ELECTRON_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ELECTRON_DIR"

SIGN=false
DMG=false

for arg in "$@"; do
  case $arg in
    --sign) SIGN=true ;;
    --dmg)  DMG=true ;;
    *)      echo "Unknown arg: $arg"; exit 1 ;;
  esac
done

# ── Preflight checks ──────────────────────────────────────────────
echo "==> Checking environment..."

if ! command -v node &>/dev/null; then
  echo "ERROR: Node.js not found. Install via: brew install node"
  exit 1
fi

if [ ! -d node_modules ]; then
  echo "==> Installing dependencies..."
  npm install
fi

# ── Signing validation ────────────────────────────────────────────
if $SIGN; then
  if [ -z "${APPLE_IDENTITY:-}" ] && [ -z "${KEYCHAIN_PROFILE:-}" ]; then
    echo "ERROR: Code signing requested but no credentials found."
    echo ""
    echo "Option A: Set environment variables:"
    echo "  export APPLE_IDENTITY='Developer ID Application: Your Name (TEAMID)'"
    echo "  export APPLE_ID='your@email.com'"
    echo "  export APPLE_PASSWORD='app-specific-password'"
    echo "  export APPLE_TEAM_ID='YOURTEAMID'"
    echo ""
    echo "Option B: Use keychain profile:"
    echo "  xcrun notarytool store-credentials 'fantastic-canvas' \\"
    echo "    --apple-id your@email.com --team-id YOURTEAMID --password ..."
    echo "  export KEYCHAIN_PROFILE='fantastic-canvas'"
    exit 1
  fi
  echo "==> Signing enabled (identity: ${APPLE_IDENTITY:-keychain:$KEYCHAIN_PROFILE})"
fi

# ── Build ─────────────────────────────────────────────────────────
echo "==> Building Electron app..."
npx electron-forge package --platform darwin --arch universal

echo ""
echo "==> Package complete: out/Fantastic Canvas-darwin-universal/"

# ── DMG ───────────────────────────────────────────────────────────
if $DMG; then
  echo "==> Creating DMG..."
  npx electron-forge make --platform darwin --arch universal
  echo "==> DMG created in out/make/"
fi

echo ""
echo "==> Done."
