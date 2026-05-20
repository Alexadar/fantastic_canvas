#!/usr/bin/env bash
# compat-python.sh — black-box wire-protocol probes.
#
# Spins up a Rust kernel in a tempdir, exercises the documented HTTP +
# REST surface, asserts each response matches the contract. Run from
# the repo root or from rust/.
#
# CI parity: .github/workflows/compat.yml invokes this script. Any
# divergence from the documented wire shape fails the build.
#
# Environment:
#   FANTASTIC_RUST   path to the rust `fantastic` binary
#                    (default: rust/target/release/fantastic)
#   FANTASTIC_PORT   port to bind (default: 18181)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUST_BIN="${FANTASTIC_RUST:-$REPO_ROOT/rust/target/release/fantastic}"
PORT="${FANTASTIC_PORT:-18181}"

if [ ! -x "$RUST_BIN" ]; then
    echo "compat-python: building rust binary first..."
    (cd "$REPO_ROOT/rust" && cargo build --release --bin fantastic >/dev/null)
fi
test -x "$RUST_BIN" || { echo "compat-python: rust binary missing at $RUST_BIN"; exit 2; }

WORKDIR="$(mktemp -d)"
trap 'cleanup' EXIT

DAEMON_PID=""
cleanup() {
    if [ -n "$DAEMON_PID" ]; then
        kill "$DAEMON_PID" 2>/dev/null || true
        wait "$DAEMON_PID" 2>/dev/null || true
    fi
    rm -rf "$WORKDIR"
}

pass() { printf "  ✓ %s\n" "$1"; }
fail() { printf "  ✗ %s\n    %s\n" "$1" "$2"; exit 1; }

echo "[compat-python] workdir: $WORKDIR"
cd "$WORKDIR"

# ── stage agents ────────────────────────────────────────────────────
"$RUST_BIN" core create_agent handler_module=web.tools id=w port="$PORT" >/dev/null
"$RUST_BIN" w create_agent handler_module=web_rest.tools id=wr >/dev/null
"$RUST_BIN" w create_agent handler_module=web_ws.tools id=wws >/dev/null
"$RUST_BIN" core create_agent handler_module=file.tools id=ff root="$WORKDIR" >/dev/null
pass "staged web + web_rest + web_ws + file agents"

# ── boot daemon ─────────────────────────────────────────────────────
"$RUST_BIN" >"$WORKDIR/daemon.log" 2>&1 &
DAEMON_PID=$!
sleep 2
if ! kill -0 "$DAEMON_PID" 2>/dev/null; then
    fail "daemon failed to stay up" "$(cat "$WORKDIR/daemon.log" | head -10)"
fi
pass "daemon up (pid=$DAEMON_PID)"

# ── HTTP rendering surface ──────────────────────────────────────────
curl -sf -m 5 "http://localhost:$PORT/" >/dev/null \
    || fail "GET /" "endpoint not 200"
pass "GET /                    → 200"

curl -sf -m 5 "http://localhost:$PORT/transport.js" | head -c 50 | grep -q "fantastic_transport" \
    || fail "GET /transport.js" "missing fantastic_transport"
pass "GET /transport.js         → contains fantastic_transport"

# ── REST reflect ────────────────────────────────────────────────────
PRIMER="$(curl -sf -m 5 "http://localhost:$PORT/wr/_reflect")"
echo "$PRIMER" | grep -q '"primitive"' \
    || fail "GET /<rest>/_reflect" "missing 'primitive' key"
echo "$PRIMER" | grep -q '"transports"' \
    || fail "GET /<rest>/_reflect" "missing 'transports' key"
echo "$PRIMER" | grep -q '"available_bundles"' \
    || fail "GET /<rest>/_reflect" "missing 'available_bundles' key"
pass "GET /<rest>/_reflect      → primer keys present"

# ── REST POST dispatch ──────────────────────────────────────────────
LIST_REPLY="$(curl -sf -m 5 -X POST \
    -H "Content-Type: application/json" \
    -d '{"type":"list_agents"}' \
    "http://localhost:$PORT/wr/core")"
echo "$LIST_REPLY" | grep -q '"agents"' \
    || fail "POST /<rest>/core list_agents" "missing 'agents' key"
echo "$LIST_REPLY" | grep -q '"id":"w"' \
    || fail "POST /<rest>/core list_agents" "missing web agent w"
pass "POST /<rest>/core list_agents → agents array contains w"

# ── REST POST file verb ─────────────────────────────────────────────
FILE_REPLY="$(curl -sf -m 5 -X POST \
    -H "Content-Type: application/json" \
    -d '{"type":"reflect"}' \
    "http://localhost:$PORT/wr/ff")"
echo "$FILE_REPLY" | grep -q '"sentence"' \
    || fail "POST /<rest>/ff reflect" "missing 'sentence'"
echo "$FILE_REPLY" | grep -q 'Filesystem root' \
    || fail "POST /<rest>/ff reflect" "wrong sentence"
pass "POST /<rest>/ff reflect   → Filesystem root sentence"

# ── weak-load skip+log ──────────────────────────────────────────────
"$RUST_BIN" core create_agent handler_module=ghost_unknown.tools id=ghost_1 >/dev/null 2>&1 || true
mkdir -p "$WORKDIR/.fantastic/agents/ghost_planted"
cat >"$WORKDIR/.fantastic/agents/ghost_planted/agent.json" <<'JSON'
{"id":"ghost_planted","handler_module":"never_installed.tools","parent_id":"core"}
JSON
# Reboot daemon for the new on-disk record to be hydrated.
kill "$DAEMON_PID" 2>/dev/null
wait "$DAEMON_PID" 2>/dev/null || true
"$RUST_BIN" >"$WORKDIR/daemon2.log" 2>&1 &
DAEMON_PID=$!
sleep 2
grep -q "skipping agent ghost_planted: bundle never_installed.tools not installed in this runtime" \
    "$WORKDIR/daemon2.log" \
    || fail "weak-load" "expected skip line missing from $WORKDIR/daemon2.log"
pass "boot weak-load             → ghost_planted skip+log line present"

# ── all green ───────────────────────────────────────────────────────
echo
echo "[compat-python] ✓ all probes pass"
