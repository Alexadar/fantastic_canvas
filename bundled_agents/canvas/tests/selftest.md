# Fantastic Canvas Self-Test

**Comprehensive end-to-end test harness** for Claude Code. Covers everything
we've built: core, CLI, AI bundles, web bundle (HTTP + WS transport), canvas,
terminal, content aliases, files, scheduler, VFX, delete-lock, hierarchy,
and the `@{agent_id}` CLI routing layer with `cli_sync` + tool-call
round-trip.

A **narrower CLI-only** selftest (core + AI bundles, no web/UI) lives at
`core/tests/selftest.md`. That file is a subset of this one (Part 15 below).
If you only need to verify the CLI surface, run it instead — it's faster
and doesn't require uvicorn or a browser.

**For Claude Code (automated):** Read this file end-to-end, then run the
pre-flight reset below, start the server in a background shell, and execute
the tests in order. Report results using the summary table at the end.

**Before you start — ASK THE USER:**

> Which AI provider should I use for this selftest?
> - **Ollama** (local): which endpoint and which model? (e.g. `http://localhost:11434` + `gemma4:e2b`)
> - **Anthropic**: confirm `ANTHROPIC_API_KEY` is set in `.env` and name the model.
> - **OpenAI**: confirm `OPENAI_API_KEY` is set in `.env` and name the model.
> - **None** — skip Part 12 (AI bundle) and Part 15 (CLI `cli_sync`).

Record the user's answer explicitly in the final report. Without a live
provider you MUST skip Part 12 and Part 15 — do not silently fail them,
and do not invent a provider. The remaining parts (0–11, 13–14) still run
fine without AI.

## Pre-flight step 1: verify the declared LLM backend actually works

**Do this BEFORE wiping anything.** If the user described an LLM backend to
use during this session, confirm it's reachable first — there's no point
wiping state and rebuilding only to discover the provider is down.

- **Ollama**: `curl -s http://localhost:11434/api/tags | head` — should return
  a JSON list of models. Confirm the specific model the user named is listed
  (or `ollama pull <model>` works).
- **Anthropic**: verify `ANTHROPIC_API_KEY` is set in `.env`; do a small
  sanity probe (e.g. a minimal `messages.create` via `curl`) before trusting it.
- **OpenAI**: same — key in `.env`, minimal probe against `/v1/models`.

If the backend check fails, **stop and report to the user** — do not wipe
`.fantastic`. If the user has not provided any backend at all, skip Parts 12
and 15 entirely and note that in the final report.

## Pre-flight step 2: wipe and rebuild like a user

Only after step 1 passes, run these from the project root:

```bash
# Stop any running server
pkill -f "fantastic" 2>/dev/null; sleep 1

# Wipe persistent state (this IS destructive — confirms the "user flow")
rm -rf .fantastic

# Start Core fresh — NO bundles are auto-added anymore.
# (Core prints a hint "No agents yet. To bootstrap ... type: add quickstart")
uv run fantastic  # run in a background shell; drive via stdin/FIFO
```

Then add the bundles this selftest needs, **explicitly** (the CLI never
auto-creates agents):

```
add web       # creates web_<hex6>, starts uvicorn on :8888
add canvas    # creates canvas_<hex6>
```

Port 8888 is the web bundle default. If `web_configure` is exercised later
(Test 43), the port may change — substitute `{{PORT}}` accordingly.

**ID substitution:** Tests below still reference `web_main` and
`canvas_main` as stable names (legacy from quickstart). On a fresh `add web`
/ `add canvas` flow, the agents get random IDs like `web_a0ca4f` /
`canvas_5fbf33`. Either:

- rename them to match: `rename_agent agent_id=<web_hex> display_name="web"`
  and use the hex ids wherever the text says `web_main`, OR
- read the ids once with `list_agents` and substitute mentally.

The dispatch layer does NOT require any particular id, so any web agent id
works as the WS channel for `call(WEB, ...)`.

You are testing a running Fantastic Canvas instance. The server is at `http://localhost:{{PORT}}`.

**Transport: WebSocket only.** Every agent has its own WS channel at
`ws://localhost:{{PORT}}/{agent_id}/ws`. The only HTTP endpoints are:
- `GET /_fantastic/transport.js` — the injected transport JS
- `GET /_fantastic/description.json` — protocol spec
- `GET /{agent_id}/` — serves that agent's HTML (with `<script src="/_fantastic/transport.js">` auto-injected)
- `GET /{agent_id}/<asset>` — static assets from that bundle's `web/dist/`
- `GET /content/{alias_id}` — content alias (file or redirect)

No REST API. Every dispatch call goes over the WS channel of some agent
(usually `web_main`, the root web agent). Use the Python helper below for
manual WS calls; `wscat`/`websocat` work too.

## Python helper (copy to a file or run inline)

Save as `selftest_call.py`:
```python
#!/usr/bin/env python3
"""Call a dispatch tool on a running Fantastic instance via WS."""
import asyncio, json, sys, uuid
import websockets

async def call(agent_id, tool, **args):
    url = f"ws://localhost:{PORT}/{agent_id}/ws"
    async with websockets.connect(url) as ws:
        req_id = str(uuid.uuid4())
        await ws.send(json.dumps({"type": "call", "tool": tool, "args": args, "id": req_id}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == req_id:
                if msg["type"] == "reply":
                    return msg["data"]
                raise RuntimeError(msg.get("error"))

PORT = int(sys.argv[1])
AGENT = sys.argv[2]  # e.g. "web_main"
TOOL = sys.argv[3]
ARGS = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
print(json.dumps(asyncio.run(call(AGENT, TOOL, **ARGS)), indent=2, default=str))
```

Usage: `python3 selftest_call.py {{PORT}} web_main list_agents '{}'`

Below, each test shows the equivalent call; `call(...)` is shorthand for the
Python helper. Tests marked **UI** need a browser; others are pure dispatch.

---

## Part 0: Transport & self-documentation

### Test 1: transport.js served
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:{{PORT}}/_fantastic/transport.js
```
Expected: `200`. Content is a small IIFE that defines `window.fantastic_transport`.

### Test 2: description.json served
```bash
curl -s http://localhost:{{PORT}}/_fantastic/description.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['version']); assert 'call' in d['message_shapes']"
```
Expected: protocol version + shape names.

### Test 3: Runtime introspection from browser console **UI**
Open any agent URL (e.g. `/canvas_main/`) in browser. In dev console:
```js
fantastic_transport().description().howToUse
```
Expected: markdown doc string. Confirms the injected global is live.

---

## Part 1: Core dispatch (symmetric with backend)

All calls below go through `web_main`'s WS channel (or any agent — they share the same `_DISPATCH`).

### Test 4: list_agents
```
call("web_main", "list_agents")
```
Expected: list of agents. `web_main` and `canvas_main` should appear after quickstart.

### Test 5: get_state
```
call("web_main", "get_state")
```
Expected: `{"agents": [...], ...}`.

### Test 6: Create terminal agent (auto-parents to canvas_main)
```
call("web_main", "create_agent", template="terminal", options={"x": 200, "y": 200})
```
Expected: agent dict. ID starts with `terminal_`. `parent` field = `canvas_main`. Save as `TERM_ID`.
**UI**: agent appears on canvas instantly (no reload).

### Test 7: Execute Python
```
call("web_main", "execute_python", agent_id=TERM_ID, code="print(40+2)")
```
Expected: output containing `"42"`.

### Test 8: Create HTML agent
```
call("web_main", "create_agent", template="html", options={"x": 600, "y": 200})
```
Save as `HTML_ID`.

### Test 9: Post output
```
call("web_main", "post_output", agent_id=HTML_ID, html="<h1 style='color:#ff44ff'>SELFTEST OK</h1>")
```
**UI**: "SELFTEST OK" visible on canvas in magenta.

### Test 10: Unknown tool error
```
call("web_main", "nonexistent_tool")
```
Expected: raises `RuntimeError("Unknown tool: nonexistent_tool")`.

---

## Part 2: Agent CRUD

### Test 11: read_agent
```
call("web_main", "read_agent", agent_id=TERM_ID)
```
Expected: agent dict with `agent_id`, `bundle`, `source`, `output_html`, `parent`.

### Test 12: rename_agent
```
call("web_main", "rename_agent", agent_id=TERM_ID, display_name="Test Terminal")
```
Expected: `{"display_name": "Test Terminal", ...}`.

### Test 13: update_agent (set delete_lock)
```
call("web_main", "update_agent", agent_id=TERM_ID, options={"delete_lock": True})
```
Expected: success.

### Test 14: delete_agent locked (should fail)
```
call("web_main", "delete_agent", agent_id=TERM_ID)
```
Expected: raises error containing `"delete-locked"`.

### Test 15: Unlock and delete
```
call("web_main", "update_agent", agent_id=TERM_ID, options={"delete_lock": False})
call("web_main", "delete_agent", agent_id=TERM_ID)
```
Expected: agent deleted. **UI**: disappears from canvas.

### Test 16: Delete HTML agent
```
call("web_main", "delete_agent", agent_id=HTML_ID)
```

---

## Part 3: Canvas layout

### Test 17: move_agent
Create a terminal, save as `AGENT_ID`, then:
```
call("web_main", "move_agent", agent_id=AGENT_ID, x=500, y=300)
```
Expected: `{"x": 500, "y": 300}`. **UI**: agent moves.

### Test 18: resize_agent
```
call("web_main", "resize_agent", agent_id=AGENT_ID, width=1200, height=800)
```
Expected: success. Enforces min 250×100.

### Test 19: spatial_discovery
```
call("web_main", "spatial_discovery", agent_id=AGENT_ID)
```
Expected: list of nearby agents sorted by distance.

Clean up the test agent.

---

## Part 4: Terminal (via dispatch, not REST)

### Test 20: Terminal page loads **UI**
Visit `http://localhost:{{PORT}}/<terminal_agent_id>/` in browser.
Expected: xterm.js page, `fantastic_transport()` global available, PTY connected.

### Test 21: process_input
Create a terminal, save as `TERM_ID`. Wait ~300ms for shell init, then:
```
call("web_main", "process_input", agent_id=TERM_ID, data="echo SELFTEST_TERMINAL\n")
```

### Test 22: terminal_output
```
call("web_main", "terminal_output", agent_id=TERM_ID, max_lines=50)
```
Expected: output containing `SELFTEST_TERMINAL`.

### Test 23: terminal_signal (SIGINT)
```
call("web_main", "terminal_signal", agent_id=TERM_ID, signal=2)
```

### Test 24: terminal_restart
```
call("web_main", "terminal_restart", agent_id=TERM_ID)
```
Expected: success. Emits `process_started` / `process_closed` events on bus.

### Test 25: agent_call (inter-agent via PTY)
Create a second terminal (`TERM2_ID`), then:
```
call("web_main", "agent_call", target_agent_id=TERM2_ID, message="echo hello from agent_call")
```
Expected: `{"delivered": True, "delivered_to_process": True}`.
Then `terminal_output(TERM2_ID)` should show `hello from agent_call`.

Clean up both agents.

---

## Part 5: Content aliases

### Test 26: content_alias_file
```
call("web_main", "content_alias_file", file_path="CLAUDE.md")
```
Expected: `{"alias_path": "/content/<hex>", "alias_id": "<hex>"}`.

### Test 27: Serve the alias
```bash
curl -s http://localhost:{{PORT}}/content/HEXID | head -5
```
Expected: first few lines of CLAUDE.md.

### Test 28: content_alias_url
```
call("web_main", "content_alias_url", url="https://example.com")
```
Expected: alias redirecting to example.com.

### Test 29: get_aliases
```
call("web_main", "get_aliases")
```
Expected: list with entries from tests 26 + 28.

---

## Part 6: Files (dispatch, not REST)

### Test 30: list_files
```
call("web_main", "list_files", path="")
```
Expected: project file tree. Excludes `.fantastic/`, `.git/`, `node_modules/`.

### Test 31: read_file
```
call("web_main", "read_file", path="CLAUDE.md")
```
Expected: `{"path": "CLAUDE.md", "content": "..."}`.

### Test 32: write_file (project path)
```
call("web_main", "write_file", path="_selftest_tmp.txt", content="hello")
```
Then `read_file` should return the same content. Delete the file after.

### Test 33: write_file (agent-scoped)
Create a terminal, save as `AGENT_ID`, then:
```
call("web_main", "write_file", path="note.txt", content="scoped", agent_id=AGENT_ID)
```
Expected: `{"path": ".fantastic/agents/<AGENT_ID>/note.txt", "written": true}`.
Clean up the agent.

---

## Part 7: Handbook & templates

### Test 34: get_handbook
```
call("web_main", "get_handbook")
```
Expected: dict with `text` = CLAUDE.md contents.

### Test 35: get_handbook_canvas
```
call("web_main", "get_handbook_canvas", skill="canvas-management")
```
Expected: canvas skill doc.

### Test 36: get_handbook_terminal
```
call("web_main", "get_handbook_terminal", skill="terminal-control")
```
Expected: terminal skill doc.

### Test 37: list_templates
```
call("web_main", "list_templates")
```
Expected: list including `canvas`, `terminal`, `html`, `web`, `ollama`, `openai`, `anthropic`, `integrated`, `fantastic_agent`, `quickstart`.

---

## Part 8: Conversation & server logs

### Test 38: core_chat_message
```
call("web_main", "core_chat_message", who="selftest", message="Self-test running")
```
Expected: `{"who": "selftest", "message": "Self-test running", "timestamp": <float>}`.

### Test 39: server_logs
```
call("web_main", "server_logs", max_lines=10)
```
Expected: list of log entries with `ts`, `level`, `name`, `message`.

---

## Part 9: VFX (canvas bundle)

### Test 40: scene_vfx update
```
call("web_main", "scene_vfx", js_code="""
var geo = new THREE.SphereGeometry(50);
var mat = new THREE.MeshStandardMaterial({color: 0xff0000, emissive: 0x440000});
var mesh = new THREE.Mesh(geo, mat);
mesh.position.set(0, 0, -500);
scene.add(mesh);
this.onFrame = function(dt, t) { mesh.rotation.y += 0.02; };
return function() { scene.remove(mesh); geo.dispose(); mat.dispose(); };
""")
```
**UI**: red spinning sphere in canvas background.

### Test 41: scene_vfx_data
```
call("web_main", "scene_vfx_data", data={"test_value": 42})
```
Expected: `{"ok": True}`. Available as `window.__vfxData` in VFX code.

### Test 42: Clear VFX
```
call("web_main", "scene_vfx", js_code="")
```
Reload canvas page to get defaults back.

---

## Part 10: Web bundle

### Test 43: web_configure (port hot-reload)
```
call("web_main", "web_configure", agent_id="web_main", port=9001)
```
Expected: uvicorn restarts on port 9001. Existing WS connections drop and transport auto-reconnects to new port (in-browser; manual testing needed).
Revert:
```
call("web_main", "web_configure", agent_id="web_main", port=8888)
```

### Test 44: Multiple web agents
Add a second web agent:
```
call("web_main", "create_agent", template="web")
# save id as WEB2
call("web_main", "web_configure", agent_id=WEB2, port=9002, base_route="/admin")
```
Open `http://localhost:9002/admin/web_main/` — should serve `web_main`'s info page (headless since `web` has no UI, but the transport is injected).
Clean up: `delete_agent(WEB2)`.

---

## Part 11: Scheduler

### Test 45: create_schedule (tool action)
Create a terminal (`AGENT_ID`), then:
```
call("web_main", "create_schedule",
     agent_id=AGENT_ID,
     action={"type": "tool", "tool": "terminal_output", "args": {"max_lines": 5}},
     interval_seconds=60)
```
Expected: schedule dict with `id` starting `sch_`, `run_count=0`, `next_run` ~60s in future.

### Test 46: list_schedules
```
call("web_main", "list_schedules", agent_id=AGENT_ID)
```
Expected: list containing the created schedule.

### Test 47: delete_schedule
```
call("web_main", "delete_schedule", agent_id=AGENT_ID, schedule_id="<sch_id>")
```
Expected: `{"deleted": True}`. Then `list_schedules` returns empty.

### Test 48: Schedules deleted with agent
Create a schedule, then delete the agent. Verify `.fantastic/agents/<AGENT_ID>/` no longer exists (cleans up `schedules.json` automatically).

---

## Part 12: AI bundle (optional — needs live provider)

**Skip this section if no AI server is available.**

### Test 49: Add ollama + fantastic_agent
```
call("web_main", "add_bundle", bundle_name="ollama")
call("web_main", "add_bundle", bundle_name="fantastic_agent")
```
Find the ollama agent id (`list_agents` → entry with `bundle=="ollama"`) → `OLLAMA_ID`.
Find the fantastic_agent id → `FA_ID`.

### Test 50: Configure fantastic_agent upstream
```
call("web_main", "fantastic_agent_configure",
     agent_id=FA_ID, upstream_agent_id=OLLAMA_ID, upstream_bundle="ollama")
```
Expected: success.

### Test 51: Save + send a message through fantastic_agent
```
call("web_main", "fantastic_agent_save_message", agent_id=FA_ID, role="user", text="hi")
call("web_main", "ollama_send", agent_id=OLLAMA_ID, text="hi")
```
**UI**: Open `/<FA_ID>/` in browser. Should show the saved message and AI response.

### Test 52: fantastic_agent_history
```
call("web_main", "fantastic_agent_history", agent_id=FA_ID)
```
Expected: reply with `messages` array containing the saved user message.

Clean up:
```
call("web_main", "delete_agent", agent_id=FA_ID)
call("web_main", "delete_agent", agent_id=OLLAMA_ID)
```

---

## Part 13: Agent hierarchy (post-quickstart)

### Test 53: web_main is root, canvas_main is child
```
web = call("web_main", "read_agent", agent_id="web_main")
canvas = call("web_main", "read_agent", agent_id="canvas_main")
assert web["bundle"] == "web" and web.get("is_container") is True
assert canvas["bundle"] == "canvas" and canvas.get("parent") == "web_main"
```

### Test 54: New agents auto-parent to canvas_main
Create a terminal:
```
t = call("web_main", "create_agent", template="terminal")
assert t["parent"] == "canvas_main"
```
Clean up.

### Test 55: Agent ID format
Verify `t["id"].startswith("terminal_")` and length == 15 (`terminal_` + 6 hex).

---

## Part 14: Delete Lock UI **UI**

### Test 56: Set delete_lock + visual check
```
a = call("web_main", "create_agent", template="terminal", options={"x": 200, "y": 400})
call("web_main", "update_agent", agent_id=a["id"], options={"delete_lock": True})
```
**UI**: lock icon (🔒), close button (×) visually disabled.

### Test 57: Attempt delete (fails)
```
call("web_main", "delete_agent", agent_id=a["id"])
```
Expected: error mentioning "delete-locked".

### Test 58: Unlock and delete
```
call("web_main", "update_agent", agent_id=a["id"], options={"delete_lock": False})
call("web_main", "delete_agent", agent_id=a["id"])
```
**UI**: lock → 🔓, then agent disappears.

---

## Part 15: CLI `@{agent_id}` routing (headless chat + config)

**Requires at least one AI provider configured** (Ollama reachable, or API key
in `.env`). If none is available, skip this entire section.

The CLI input loop accepts three shapes:

1. `@core <cmd>` — core commands (add / remove / list / log / say)
2. `@{agent_id} <tool> key=val ...` — invoke a dispatch tool on that agent
3. `@{agent_id} <free text>` — call the bundle's `cli_sync(agent_id, text)`
   hook, which runs the full tool-calling loop synchronously and prints the
   accumulated reply

Values in `key=val` are coerced: `true`/`false`, ints, floats, JSON
(`{...}` / `[...]`), otherwise string. Use shell quoting for spaces:
`model="gemma2 small"`.

Drive the CLI by piping commands into the process, or attach to the
background shell that was started in pre-flight.

### Test 59: CLI — list agents via `@core`
Type in the CLI:
```
list
```
Expected: shows loaded bundles, including `web`, `canvas`, `quickstart`
after reset, and any ai bundle you add below.

### Test 60: CLI — add an AI bundle
```
add ollama
```
(or `add anthropic` / `add openai` / `add integrated` depending on provider).
Then `list` — confirm an `{bundle}_<hex6>` agent exists. Save that id as
`AI_ID`.

### Test 61: CLI — `@{id} update_agent` flat kwargs
```
@AI_ID update_agent model=qwen2.5:3b
```
Replace `model=...` with a model your provider actually serves. Expected:
printed result contains `model=...`, and `.fantastic/agents/AI_ID/agent.json`
now has the new `model` field.

### Test 62: CLI — `@{id} <message>` runs `cli_sync`
```
@AI_ID say hello in 3 words
```
Expected: the agentic loop runs, accumulates a final reply, and the reply
prints under the `{AI_ID}:` prefix. No streaming — one block at the end.

### Test 62b: CLI — tool call round-trip via `cli_sync`
```
@AI_ID use the list_agents tool and tell me how many agents exist
```
Expected: the model invokes the `list_agents` dispatch tool mid-loop,
receives the result, and summarizes it in the final reply (e.g.
`"There is 1 agent."` when only `AI_ID` exists). Confirms tool-calling
round-trip works end-to-end through the CLI path. Skip if your model does
not support tool-calling.

### Test 63: CLI — fantastic_agent proxy
```
add fantastic_agent
list
```
Save the `fantastic_agent_<hex6>` as `FA_ID`.

```
@FA_ID fantastic_agent_configure upstream_agent_id=AI_ID upstream_bundle=ollama
```
(Use the correct `upstream_bundle` for your provider.)
Expected: success, both fields set in `FA_ID`'s agent.json.

### Test 64: CLI — `@FA_ID <message>` routes to upstream
```
@FA_ID what is 2+2
```
Expected: message is saved to `FA_ID`'s `chat.json`, dispatched through
`{upstream_bundle}_send` on `AI_ID`, and the final AI reply prints + is saved
back under `assistant`.

### Test 65: CLI — unknown `@{tag}` rejected
```
@nope_xyz hello
```
Expected: `unknown: @nope_xyz` (or similar) — not a crash.

### Test 66: CLI — dispatch error path
```
@AI_ID update_agent
```
(No kwargs.)
Expected: printed `[ERROR] No options provided` — no crash.

Clean up:
```
@core remove fantastic_agent
@core remove ollama   # or whichever you added
```

---

## Summary

After running, report:

| Category | Tests | Pass | Fail |
|---|---|---|---|
| Transport / introspection | 1-3 | | |
| Core dispatch | 4-10 | | |
| Agent CRUD | 11-16 | | |
| Canvas layout | 17-19 | | |
| Terminal (dispatch) | 20-25 | | |
| Content aliases | 26-29 | | |
| Files | 30-33 | | |
| Handbook / templates | 34-37 | | |
| Conversation / logs | 38-39 | | |
| VFX | 40-42 | | |
| Web bundle | 43-44 | | |
| Scheduler | 45-48 | | |
| AI bundle (optional) | 49-52 | | |
| Hierarchy | 53-55 | | |
| Delete lock UI | 56-58 | | |
| CLI `@{id}` routing | 59-66, 62b | | |
| **TOTAL** | **67** | | |

Also report:
- Agents appear/disappear without reload (tests 6, 9, 15, 17)
- `fantastic_transport()` available on every agent page (test 3)
- `web_configure` hot-reload keeps clients connected (test 43)
- Quickstart hierarchy correct: web_main → canvas_main → children (test 53)
- New agents use `{bundle}_{hex6}` IDs (test 55)
- Any unexpected errors or missing fields
- GPU usage with canvas open (should be <15% idle)
