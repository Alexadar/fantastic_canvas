# ollama_webapp selftest

> scopes: webapp, web
> requires: `uv sync`; running webapp serve; for browser-manual test, a
> live ollama backend agent + browser
> out-of-scope: actual chat dialogue (covered by ollama_backend selftest)

Chat UI agent fronting an LLM backend.

## Pre-flight

```bash
cd new_codebase
rm -rf .fantastic
PORT=18903
pkill -9 -f "kernel.py serve" 2>/dev/null
uv run --active python kernel.py serve --port $PORT > /tmp/s.log 2>&1 &
SPID=$!
for i in $(seq 1 20); do grep -q "kernel up" /tmp/s.log 2>/dev/null && break; sleep 0.5; done
```

After all tests:
```bash
kill -9 $SPID 2>/dev/null; rm -rf .fantastic /tmp/s.log
```

## Tests

### Test 1: get_webapp descriptor

```bash
OW=$(curl -s -X POST http://localhost:$PORT/core/call -H 'content-type: application/json' \
  -d '{"type":"create_agent","handler_module":"ollama_webapp.tools","upstream_id":"upstream_x"}' | python -c "import json,sys;print(json.load(sys.stdin)['id'])")

curl -s -X POST "http://localhost:$PORT/$OW/call" -H 'content-type: application/json' \
  -d '{"type":"get_webapp"}' | python -m json.tool
```
Expected: `{url:"/<OW>/", default_width:360, default_height:480, title:"chat"}`.

### Test 2: served HTML has chat UI markers

```bash
curl -s "http://localhost:$PORT/$OW/" | grep -E "chat|messages|fantastic_transport" | wc -l
```
Expected: ≥ 3 lines match.

### Test 3: missing upstream_id → page error

```bash
OW2=$(curl -s -X POST http://localhost:$PORT/core/call -H 'content-type: application/json' \
  -d '{"type":"create_agent","handler_module":"ollama_webapp.tools"}' | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
curl -s "http://localhost:$PORT/$OW2/" | grep -F "upstream_id not set"
```
Expected: matches.

### Test 4 (manual, requires live ollama): chat in browser

Provision ollama_backend with file_agent_id; set ollama_webapp.upstream_id
to that backend; open `http://localhost:$PORT/<OW>/` in browser.
- Type "hi" → assistant tokens stream into a bubble.
- Refresh page → past messages reload from this tab's per-client thread (`chat_<client_id>.json`; the `client_id` is a uuid persisted in localStorage and passed on every `send`/`history` call).
Regression signal: tokens don't appear → upstream_id wiring broken,
or token events not reaching browser via watch.

## Summary

| # | Test | Pass |
|---|------|------|
| 1 | get_webapp descriptor | |
| 2 | served HTML has chat markers | |
| 3 | missing upstream_id → error | |
| 4 (manual) | chat streams + persists across reload | |
