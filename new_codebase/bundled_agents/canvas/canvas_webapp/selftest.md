# canvas_webapp selftest

> scopes: webapp, web, bus
> requires: `uv sync`; running webapp serve; browser for visual + bus tests
> out-of-scope: deep iframe content (each child agent has its own selftest)

Spatial UI host. Tests get_webapp, frame filtering, drag persistence,
bganim default + override + live refresh, browser bus integration.

## Pre-flight

```bash
cd new_codebase
rm -rf .fantastic
PORT=18904
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
CB=$(curl -s -X POST http://localhost:$PORT/core/call -H 'content-type: application/json' \
  -d '{"type":"create_agent","handler_module":"canvas_backend.tools"}' | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
CW=$(curl -s -X POST http://localhost:$PORT/core/call -H 'content-type: application/json' \
  -d "{\"type\":\"create_agent\",\"handler_module\":\"canvas_webapp.tools\",\"upstream_id\":\"$CB\"}" | python -c "import json,sys;print(json.load(sys.stdin)['id'])")

curl -s -X POST "http://localhost:$PORT/$CW/call" -H 'content-type: application/json' \
  -d '{"type":"get_webapp"}' | python -m json.tool
```
Expected: `{url, default_width:800, default_height:600, title:"canvas"}`.

### Test 2: served HTML has same-bundle exclusion + bus reference

```bash
curl -s "http://localhost:$PORT/$CW/" | grep -ic "same-bundle siblings"
curl -s "http://localhost:$PORT/$CW/" | grep -c "BroadcastChannel"
```
Expected: first ≥ 1 (recursion guard comment), second 0 (canvas itself
doesn't use the bus — that's per-agent. Only checks transport.js has it,
and transport.js is fetched separately).

### Test 3 (manual, browser): canvas filters webapps only

Provision additional agents:
```bash
TB=$(curl -s -X POST ... terminal_backend ... | …id)
TW=$(curl -s -X POST ... terminal_webapp upstream_id=TB ... | …id)
```
Open `http://localhost:$PORT/$CW/` in browser.
Expected: ONE frame visible (terminal_webapp), with title "xterm".
Backend agents (TB, CB, file_agent) → NOT framed (404'd via get_webapp).
Regression signal: extra empty frames → get_webapp probe filter regressed.

### Test 4 (manual, browser): drag persists position

In browser, drag the terminal_webapp frame to a new spot. Then:
```bash
curl -s -X POST http://localhost:$PORT/core/call -H 'content-type: application/json' \
  -d "{\"type\":\"list_agents\"}" | python -c "import json,sys; [print(a['id'], a.get('x'), a.get('y')) for a in json.load(sys.stdin)['agents'] if 'terminal_webapp' in a['handler_module']]"
```
Expected: x/y match the drop position roughly.

### Test 5 (manual, browser): two canvases don't iframe each other

Provision a second canvas pair:
```bash
CB2=$(... canvas_backend ...)
CW2=$(... canvas_webapp upstream_id=CB2 ...)
```
Open `/$CW/` in tab A and `/$CW2/` in tab B.
Expected: neither tab shows a frame for the OTHER canvas. Same-bundle
exclusion rule kicks in. Drag in A → does NOT cause infinite frame
recursion or jitter in B.

### Test 6: bganim default loads via get_bganim

```bash
curl -s -X POST "http://localhost:$PORT/$CW/call" -H 'content-type: application/json' \
  -d '{"type":"get_bganim"}' | python -m json.tool | grep -F '"origin": "default"'
curl -s -X POST "http://localhost:$PORT/$CW/call" -H 'content-type: application/json' \
  -d '{"type":"get_bganim"}' | python -c "import json,sys; d=json.load(sys.stdin); print('chars:', len(d['source']))"
```
Expected: origin matches; source ≥ 200 chars.

### Test 7: set_bganim without file_agent_id → failfast

```bash
curl -s -X POST "http://localhost:$PORT/$CW/call" -H 'content-type: application/json' \
  -d '{"type":"set_bganim","source":"target.set(0,0,0); color.set(\"white\");"}' | python -m json.tool | grep -F "file_agent_id required"
```
Expected: matches.

### Test 8: set_bganim with file_agent_id writes + emits event

```bash
FA=$(curl -s -X POST "http://localhost:$PORT/core/call" -H 'content-type: application/json' \
  -d '{"type":"create_agent","handler_module":"file.tools"}' | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
curl -s -X POST "http://localhost:$PORT/core/call" -H 'content-type: application/json' \
  -d "{\"type\":\"update_agent\",\"id\":\"$CW\",\"file_agent_id\":\"$FA\"}" >/dev/null
curl -s -X POST "http://localhost:$PORT/$CW/call" -H 'content-type: application/json' \
  -d '{"type":"set_bganim","source":"target.set(0,0,0); color.set(\"white\");"}' | python -m json.tool | grep -F '"ok": true'
# read it back through the file agent
curl -s -X POST "http://localhost:$PORT/$FA/call" -H 'content-type: application/json' \
  -d "{\"type\":\"read\",\"path\":\".fantastic/agents/$CW/bganim.js\"}" | python -m json.tool | grep -F 'target.set(0,0,0)'
# get_bganim now reports origin:file
curl -s -X POST "http://localhost:$PORT/$CW/call" -H 'content-type: application/json' \
  -d '{"type":"get_bganim"}' | python -m json.tool | grep -F '"origin": "file"'
# reflect shows bganim_origin and file_agent_id
curl -s -X POST "http://localhost:$PORT/$CW/call" -H 'content-type: application/json' \
  -d '{"type":"reflect"}' | python -m json.tool | grep -F '"bganim_origin": "file"'
```
Expected: every grep matches.

### Test 9: get_bganim_guide returns the prompt spec

```bash
curl -s -X POST "http://localhost:$PORT/$CW/call" -H 'content-type: application/json' \
  -d '{"type":"get_bganim_guide"}' | python -c "import json,sys; d=json.load(sys.stdin); g=d['guide']; print('chars:',len(g),'has_api:','target' in g and 'count' in g)"
```
Expected: chars > 1000; has_api: True.

### Test 10 (manual, browser): default bg + live refresh

Open `http://localhost:$PORT/$CW/` in a browser.
Expected: a magenta→cyan particle galaxy spiral drifting behind any
iframes. **No sliders, no HUD, no labels** — just the animation.
Then in another shell:
```bash
curl -s -X POST "http://localhost:$PORT/$CW/call" -H 'content-type: application/json' \
  -d '{"type":"set_bganim","source":"const a=i*0.05+time*0.5; target.set(Math.cos(a)*40, Math.sin(a*2)*15, Math.sin(a)*40); color.setHSL((i/count+time*0.05)%1, 1, 0.6);"}'
```
Expected: the browser tab's particle motion changes within ~1s without
a page reload.
Regression signal: page reloads, white flash, or particles freeze →
either the watch wiring broke or the rAF loop crashed on rebuild.

### Test 11: terminal pair lifecycle (programmatic — mirrors dblclick + close)

Verifies that the substrate supports the create-pair / cascade-delete
flow that the canvas_webapp UI exercises on dblclick / "×":

```bash
# 1. dblclick create — backend first, then webapp pointing at it
TB=$(curl -s -X POST "http://localhost:$PORT/core/call" -H 'content-type: application/json' \
  -d '{"type":"create_agent","handler_module":"terminal_backend.tools"}' | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
TW=$(curl -s -X POST "http://localhost:$PORT/core/call" -H 'content-type: application/json' \
  -d "{\"type\":\"create_agent\",\"handler_module\":\"terminal_webapp.tools\",\"upstream_id\":\"$TB\",\"x\":120,\"y\":80}" | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
echo "  created TB=$TB TW=$TW"

# 2. webapp's upstream_id points at backend
curl -s -X POST "http://localhost:$PORT/$TW/call" -H 'content-type: application/json' \
  -d '{"type":"reflect"}' | python -m json.tool | grep -F "\"upstream_id\": \"$TB\""

# 3. close — webapp first, then backend (mirrors × button order)
curl -s -X POST "http://localhost:$PORT/core/call" -H 'content-type: application/json' \
  -d "{\"type\":\"delete_agent\",\"id\":\"$TW\"}" | python -m json.tool | grep -F '"deleted": true'
curl -s -X POST "http://localhost:$PORT/core/call" -H 'content-type: application/json' \
  -d "{\"type\":\"delete_agent\",\"id\":\"$TB\"}" | python -m json.tool | grep -F '"deleted": true'

# 4. neither lingers
curl -s -X POST "http://localhost:$PORT/core/call" -H 'content-type: application/json' \
  -d '{"type":"list_agents"}' | python -c "
import json, sys
d = json.load(sys.stdin)
ids = {a['id'] for a in d['agents']}
print('PASS' if '$TB' not in ids and '$TW' not in ids else f'FAIL leftover={ids & {\"$TB\",\"$TW\"}}')
"
```
Expected: every grep matches AND final line prints `PASS`.
Regression signal: orphan agent in `list_agents` after delete → cascade
ordering broken or `delete_agent` regressed.

### Test 12 (manual, browser): dblclick spawns pair, "×" cascades, ⟳ reloads, pan/wheel hygiene

Open `http://localhost:$PORT/$CW/` in a browser.

**Spawn + close:**
- **Dblclick** on empty canvas → a new xterm frame appears at the click
  position. (Backend `terminal_backend_xxx` + webapp `terminal_webapp_xxx`
  are both created; only the webapp is iframed.)
- Type a command in the xterm — works (proves the upstream_id link).
- Click **×** on the frame head → both agents deleted; frame disappears.

**Reload button (⟳):**
- Spawn another frame. Click **⟳** on its head. The iframe reloads
  (you'll see xterm re-init briefly); other frames are unaffected.
- The button emits `reload_html` to that agent's inbox; transport.js's
  universal listener calls `location.reload()` inside the iframe.
  Same plumbing as `set_html` on an html_agent.

**Wheel over a cell:**
- Move the mouse OVER a frame body (not the header). Scroll wheel.
  Expected: scroll happens INSIDE the cell (xterm scrollback,
  chat scroll, etc.). The canvas does NOT zoom.
- Move to empty canvas. Wheel zooms (cursor-anchored).

**Drag-pan across cells:**
- Hold left-mouse on empty canvas, drag across a frame to the other
  side. Pan continues uninterrupted (frame's iframe doesn't trap
  the cursor mid-drag). On mouseup, `pointer-events: auto` returns
  to iframes — clicking inside works again.

Regression signals:
- ⟳ reloads ALL frames (or the whole page) → universal listener wired
  too aggressively.
- Wheel over a cell zooms canvas → `agent-frame` skip in wheel handler regressed.
- Drag pan stops mid-cell → `.panning .agent-frame iframe { pointer-events: none }` regressed.

### Test 13 (manual, browser BUS): direct iframe-to-iframe via BroadcastChannel

Per `_kernel/reflect.browser_bus`, agents can bypass the kernel:
- Open browser devtools console on tab A (the canvas page).
- In console:
  ```js
  const ch = new BroadcastChannel('fantastic');
  ch.addEventListener('message', e => console.log('bus:', e.data));
  ```
- Open tab B (any other agent webapp) — in its devtools:
  ```js
  fantastic_transport().bus.broadcast({type:'ping', text:'hi from B'});
  ```
- Expected: tab A's console prints `bus: {type:'ping', source_id:'<B>', text:'hi from B'}`.
Regression signal: nothing logs → transport.js missing the bus or
BroadcastChannel name changed.

## Summary

| # | Test | Pass |
|---|------|------|
| 1 | get_webapp descriptor | |
| 2 | HTML has same-bundle guard | |
| 3 (manual) | filters to webapps only | |
| 4 (manual) | drag persists x/y | |
| 5 (manual) | two canvases don't recurse | |
| 6 | get_bganim default origin | |
| 7 | set_bganim failfast w/o file_agent_id | |
| 8 | set_bganim writes + reflect/get switch to "file" | |
| 9 | get_bganim_guide returns spec | |
| 10 (manual) | browser bg + live refresh | |
| 11 | terminal-pair lifecycle (create + cascade-delete) | |
| 12 (manual) | browser dblclick spawns pair, × cascades | |
| 13 (manual) | browser bus delivers across iframes | |
