# Fantastic Canvas Self-Test

You are testing a running Fantastic Canvas instance. The server is at `http://localhost:{{PORT}}`.
Run each test using `curl`. Replace `{{PORT}}` with actual port. Report PASS/FAIL for each.

**Important**: All API responses use `agent_id` (not `id`) as the agent identifier field. Content alias tools return plain string paths, not dicts.

---

## Part 1: Core API

### Test 1: Schema discovery
```bash
curl -s http://localhost:{{PORT}}/api/schema | python3 -c "import sys,json; d=json.load(sys.stdin); tools=d.get('tools',d); print(f'Tools: {len(tools)}'); assert len(tools) > 10"
```
Expected: 15+ tools.

### Test 2: List agents
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "list_agents", "args": {}}'
```
Expected: `{"result": [...]}`.

### Test 3: Create terminal agent
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "create_agent", "args": {"template": "terminal", "options": {"x": 200, "y": 200}}}'
```
Expected: `{"result": {"agent_id": "...", ...}}`. Agent appears on canvas instantly.
Save the `agent_id` as `TERM_ID`.

### Test 4: Execute Python
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "execute_python", "args": {"code": "print(40+2)", "agent_id": "TERM_ID"}}'
```
Expected: result containing `"42"`.

### Test 5: Create HTML agent + post output
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "create_agent", "args": {"template": "html", "options": {"x": 600, "y": 200}}}'
```
Save as `HTML_ID`. Then:
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "post_output", "args": {"agent_id": "HTML_ID", "html": "<h1 style=\"color:#ff44ff\">SELFTEST OK</h1>"}}'
```
Expected: "SELFTEST OK" visible on canvas in magenta.

### Test 6: Unknown tool error format
```bash
curl -s -w "\nHTTP:%{http_code}" http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "nonexistent_tool", "args": {}}'
```
Expected: HTTP 200 with `{"error": "Unknown tool 'nonexistent_tool'"}`.

---

## Part 2: Agent Operations

### Test 7: Read agent
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "read_agent", "args": {"agent_id": "TERM_ID"}}'
```
Expected: agent dict with `agent_id`, `bundle`, `source`, `output_html`.

### Test 8: Rename agent
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "rename_agent", "args": {"agent_id": "TERM_ID", "display_name": "Test Terminal"}}'
```
Expected: `{"result": {"agent_id": "...", "display_name": "Test Terminal"}}`.

### Test 9: Update agent (set delete_lock)
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "update_agent", "args": {"agent_id": "TERM_ID", "options": {"delete_lock": true}}}'
```
Expected: success.

### Test 10: Delete locked agent (should fail)
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "delete_agent", "args": {"agent_id": "TERM_ID"}}'
```
Expected: error mentioning "delete_lock" or "locked".

### Test 11: Unlock and delete
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "update_agent", "args": {"agent_id": "TERM_ID", "options": {"delete_lock": false}}}'
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "delete_agent", "args": {"agent_id": "TERM_ID"}}'
```
Expected: agent deleted, disappears from canvas.

### Test 12: Delete HTML agent (cleanup)
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "delete_agent", "args": {"agent_id": "HTML_ID"}}'
```

---

## Part 3: Canvas Operations

### Test 13: Move agent
Create a terminal first, then:
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "move_agent", "args": {"agent_id": "AGENT_ID", "x": 500, "y": 300}}'
```
Expected: `{"result": {"agent_id": "...", "x": 500, "y": 300}}`. Agent moves on canvas.

### Test 14: Resize agent
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "resize_agent", "args": {"agent_id": "AGENT_ID", "width": 1200, "height": 800}}'
```
Expected: success. Enforces min 250x100.

### Test 15: Spatial discovery
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "spatial_discovery", "args": {"agent_id": "AGENT_ID"}}'
```
Expected: list of nearby agents sorted by distance.

### Test 16: Canvas state
```bash
curl -s http://localhost:{{PORT}}/api/state | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f'Agents: {len(d.get(\"agents\", []))}')
print(f'VFX: {\"yes\" if d.get(\"scene_vfx_js\") else \"no\"}')
"
```

Clean up the test agent after.

---

## Part 4: Terminal Operations

### Test 17: Terminal output
Create a terminal agent, wait a moment for shell init, then:
```bash
curl -s http://localhost:{{PORT}}/api/terminal/TERM_ID/output
```
Expected: `{"output": "...", "lines": N}`.

### Test 18: Terminal write
```bash
curl -s http://localhost:{{PORT}}/api/terminal/TERM_ID/write -X POST -H "Content-Type: application/json" \
  -d '{"data": "echo SELFTEST_TERMINAL\n"}'
```
Then read output (Test 17) — should contain `SELFTEST_TERMINAL`.

### Test 19: Terminal signal (SIGINT)
```bash
curl -s http://localhost:{{PORT}}/api/terminal/TERM_ID/signal -X POST -H "Content-Type: application/json" \
  -d '{"signal": 2}'
```
Expected: `{"ok": true}`.

### Test 20: Terminal restart
```bash
curl -s http://localhost:{{PORT}}/api/terminal/TERM_ID/restart -X POST
```
Expected: `{"ok": true}`. Terminal process restarts.

### Test 21: agent_call (inter-agent communication)
Create two terminal agents. Then:
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "agent_call", "args": {"target_agent_id": "TERM2_ID", "message": "echo hello from agent_call"}}'
```
Expected: message typed into TERM2's terminal. Check output shows `hello from agent_call`.

Clean up both agents after.

---

## Part 5: Content Aliases

### Test 22: File alias
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "content_alias_file", "args": {"file_path": "CLAUDE.md"}}'
```
Expected: `{"result": "/content/HEXID"}` — a string path. Extract the hex ID from the path (last segment after `/content/`).

### Test 23: Serve alias
Use the alias path from Test 22:
```bash
curl -s http://localhost:{{PORT}}/content/HEXID | head -5
```
Expected: contents of CLAUDE.md.

### Test 24: URL alias
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "content_alias_url", "args": {"url": "https://example.com"}}'
```
Expected: alias that redirects to example.com.

### Test 25: List aliases
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "get_aliases", "args": {}}'
```
Expected: list containing the aliases from Tests 22 and 24.

---

## Part 6: Handbook & Templates

### Test 26: Get handbook (full)
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "get_handbook", "args": {}}'
```
Expected: result with `text` containing CLAUDE.md content.

### Test 27: Get handbook (no core skills)
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "get_handbook", "args": {"skill": "nonexistent"}}'
```
Expected: error with "not found". Core skills were removed — use bundle-specific handbooks (Tests 28-29) instead.

### Test 28: Canvas handbook
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "get_handbook_canvas", "args": {"skill": "canvas-management"}}'
```
Expected: canvas management docs.

### Test 29: Terminal handbook
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "get_handbook_terminal", "args": {"skill": "terminal-control"}}'
```
Expected: terminal control docs.

### Test 30: List templates
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "list_templates", "args": {}}'
```
Expected: list of templates (canvas, terminal, html, etc.).

---

## Part 7: Conversation & Server Logs

### Test 31: Chat message
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "core_chat_message", "args": {"who": "selftest", "message": "Self-test running"}}'
```
Expected: result with `who`, `message`, `timestamp`.

### Test 32: Server logs
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "server_logs", "args": {"max_lines": 10}}'
```
Expected: list of log entries with `ts`, `level`, `name`, `message`.

---

## Part 8: Broadcast Mode

### Test 33: Broadcast status (initially off)
```bash
curl -s http://localhost:{{PORT}}/api/broadcast/status
```
Expected: `{"enabled": false, "viewers": 0}`.

### Test 34: Start broadcast
```bash
curl -s http://localhost:{{PORT}}/api/broadcast/start -X POST
```
Expected: `{"token": "...", "url": "/ws/broadcast?token=..."}`.

### Test 35: Broadcast status (active)
```bash
curl -s http://localhost:{{PORT}}/api/broadcast/status
```
Expected: `{"enabled": true, "viewers": 0}`.

### Test 36: Stop broadcast
```bash
curl -s http://localhost:{{PORT}}/api/broadcast/stop -X POST
```
Expected: `{"ok": true}`.

---

## Part 9: VFX

### Test 37: Update scene VFX
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "scene_vfx", "args": {"js_code": "var geo = new THREE.SphereGeometry(50); var mat = new THREE.MeshStandardMaterial({color: 0xff0000, emissive: 0x440000}); var mesh = new THREE.Mesh(geo, mat); mesh.position.set(0, 0, -500); scene.add(mesh); this.onFrame = function(dt, t) { mesh.rotation.y += 0.02; }; return function() { scene.remove(mesh); geo.dispose(); mat.dispose(); };"}}'
```
Expected: red spinning sphere appears in canvas background.

### Test 38: Push VFX data
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "scene_vfx_data", "args": {"data": {"test_value": 42}}}'
```
Expected: `"ok"`. Data accessible as `window.__vfxData` in VFX code.

### Test 39: Restore default VFX
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "scene_vfx", "args": {"js_code": ""}}'
```
Note: empty string clears custom VFX. Reload page to get default back.

---

## Part 10: REST Direct Endpoints

### Test 40: GET /api/state
```bash
curl -s http://localhost:{{PORT}}/api/state | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if 'agents' in d else 'MISSING agents')"
```

### Test 41: GET /api/handbook
```bash
curl -s "http://localhost:{{PORT}}/api/handbook" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Length: {len(d.get(\"handbook\",\"\"))}')"
```

### Test 42: GET /api/handbook (no skill param)
```bash
curl -s "http://localhost:{{PORT}}/api/handbook" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Length: {len(d.get(\"handbook\",\"\"))}')"
```
Expected: Non-empty handbook content (CLAUDE.md).

### Test 43: GET /api/files
```bash
curl -s http://localhost:{{PORT}}/api/files | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Files: {len(d.get(\"files\", d))}')"
```

### Test 44: Bundle asset serving
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:{{PORT}}/bundles/terminal/index.html
```
Expected: HTTP 200.

---

## Part 11: Instance Management

### Test 45: List instances (initially empty or with self)
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "list_instances", "args": {}}'
```
Expected: list (may be empty or contain current instance).

### Test 46: Register external instance
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "register_instance", "args": {"url": "http://localhost:9999", "project_dir": "/tmp/fake", "name": "test-instance"}}'
```
Expected: result with `id`.

### Test 47: List registered instances
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "list_registered_instances", "args": {}}'
```
Expected: list containing the registered test instance.

### Test 48: Unregister instance
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "unregister_instance", "args": {"instance_id": "INSTANCE_ID"}}'
```
Expected: `{"result": {"id": "...", "unregistered": true}}`.

---

## Part 12: VSCode Plugin Lifecycle

The VSCode plugin is at https://github.com/Alexadar/vscode_fantastic.

### Test 49: Install plugin
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "add_bundle", "args": {"bundle_name": "vscode", "from_source": "https://github.com/Alexadar/vscode_fantastic.git"}}'
```
Expected: `{"result": {"installed": "vscode"}}`.

### Test 50: Add VSCode to canvas
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "add_bundle", "args": {"bundle_name": "vscode"}}'
```
Expected: `{"result": {"added": "vscode"}}`. VSCode agent appears on canvas instantly.

### Test 51: User interaction
Ask the user: "VSCode agent is on canvas. Please click START, verify it launches, then click STOP. Confirm when done."
Wait for user confirmation before proceeding.

### Test 52: Remove VSCode agent
Find the vscode agent_id (note: field is `agent_id`, not `id`):
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "list_agents", "args": {}}'
```
Find the entry where `bundle` is `"vscode"`, get its `agent_id`, then delete it:
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "delete_agent", "args": {"agent_id": "VSCODE_AGENT_ID"}}'
```
Expected: agent removed from canvas.

### Test 53: Verify plugin files remain after agent delete
Check `.fantastic/plugins/vscode/template.json` still exists (plugin installed, agent removed).

### Test 54: Re-add (plugin still installed)
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "add_bundle", "args": {"bundle_name": "vscode"}}'
```
Expected: new VSCode agent created from installed plugin.
Delete it again after verifying.

### Test 55: Uninstall plugin
Verify `.fantastic/plugins/vscode/` is removed. Currently manual:
```bash
rm -rf .fantastic/plugins/vscode
```
Then confirm `add_bundle vscode` fails with error (note: error is nested at `result.data.error`, not top-level):
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "add_bundle", "args": {"bundle_name": "vscode"}}'
```
Expected: response contains "Unknown bundle" somewhere in the result.

---

## Part 13: Delete Lock UI

### Test 56: Set delete_lock via API
Create a terminal agent, then lock it:
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "create_agent", "args": {"template": "terminal", "options": {"x": 200, "y": 400}}}'
```
Save `agent_id` as `LOCK_ID`. Then:
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "update_agent", "args": {"agent_id": "LOCK_ID", "options": {"delete_lock": true}}}'
```
Expected: success. On canvas: lock icon shows locked (🔒), close button (×) visually disabled.

### Test 57: Delete locked agent (should fail)
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "delete_agent", "args": {"agent_id": "LOCK_ID"}}'
```
Expected: error mentioning "delete_lock" or "locked".

### Test 58: Unlock and delete
```bash
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "update_agent", "args": {"agent_id": "LOCK_ID", "options": {"delete_lock": false}}}'
curl -s http://localhost:{{PORT}}/api/call -X POST -H "Content-Type: application/json" \
  -d '{"tool": "delete_agent", "args": {"agent_id": "LOCK_ID"}}'
```
Expected: first call unlocks (lock icon → 🔓, close re-enabled), second call deletes agent.

---

## Summary

After running all tests, report:

| Category | Tests | Pass | Fail |
|----------|-------|------|------|
| Core API | 1-6 | | |
| Agent Ops | 7-12 | | |
| Canvas Ops | 13-16 | | |
| Terminal Ops | 17-21 | | |
| Content Aliases | 22-25 | | |
| Handbook/Templates | 26-30 | | |
| Conversation/Logs | 31-32 | | |
| Broadcast Mode | 33-36 | | |
| VFX | 37-39 | | |
| REST Endpoints | 40-44 | | |
| Instance Mgmt | 45-48 | | |
| VSCode Plugin | 49-55 | | |
| Delete Lock UI | 56-58 | | |
| **TOTAL** | **58** | | |

Also report:
- Agents appeared/disappeared without browser reload (Tests 3, 5, 13, 50)
- Delete lock toggle reflects instantly on canvas (Tests 56, 58)
- Any unexpected errors or missing fields
- GPU usage with canvas open (should be <15% idle)
