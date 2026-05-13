# core selftest

> scopes: kernel, cli, cascade
> requires: `uv sync`
> out-of-scope: web/HTTP, AI providers, PTY

System verbs are baked into the `Agent` class itself; every agent
answers them natively for its own children. The `core` *bundle*
directory still exists as workspace-historical, but the
behaviour-of-record lives in the substrate. Drives via subprocess
(`fantastic call …`) and the REPL via stdin.

## Pre-flight

All test state lives in `/tmp/core_test/`. Project tree is
not touched.

```bash
rm -rf /tmp/core_test
mkdir -p /tmp/core_test
cd /tmp/core_test
```

## Tests

### Test 1: kernel reflect (substrate primer)

```bash
fantastic reflect
```
Expected: JSON containing `primitive`, `envelope`, `tree`,
`browser_bus`, `binary_protocol`. The `tree` field carries the root
+ its descendants (default depth=full, distilled per node). After a
fresh start, `agent_count` >= 2 (root `core` + auto-seeded `cli`).
Regression signal: missing `browser_bus`, `binary_protocol`, or
`tree` → reflect primer regressed.

### Test 2: list_agents (flat all)

```bash
fantastic call core list_agents
```
Expected: `{"agents":[…]}` containing `core` (root). If the
invocation is interactive (stdin is a tty), `cli` is also present
as an ephemeral child — composed by Core, never persisted to disk.
Non-tty invocations (pipes, scripted) see only `core`.

### Test 3: create_agent + auto-boot

```bash
fantastic call core create_agent handler_module=file.tools
```
Expected: `{"id":"file_<hex6>", "handler_module":"file.tools",
"parent_id":"core"}`. File check:
`.fantastic/agents/file_<hex6>/agent.json` exists.

### Test 4: update_agent persists + emits agent_updated

```bash
ID=$(fantastic call core list_agents | python -c "import json,sys;print([a for a in json.load(sys.stdin)['agents'] if a['handler_module']=='file.tools'][0]['id'])")
fantastic call core update_agent id=$ID model=foo x=42
```
Expected: `{"updated":true,"id":"…","agent":{… "model":"foo", "x":42}}`.
File check: `agent.json` of that id contains `"model":"foo"` and
`"x":42`. Watchers of `core` see an `agent_updated` emit (verified
in pytest; fragile to drive via CLI).

### Test 5: delete_agent + cascade through subtree

```bash
fantastic call core delete_agent id=$ID
```
Expected: `{"deleted":true,"id":"<ID>"}`. File check:
`.fantastic/agents/<ID>/` directory removed.

### Test 6: REPL @-tag routing (cli mode)

```bash
echo "@core list_agents" | fantastic
```
Expected: prints the agents list under `fantastic>` prompt and
exits.

### Test 7: delete_lock refuses; clear via update_agent → succeeds

```bash
rm -rf .fantastic
ID=$(fantastic call core create_agent handler_module=file.tools delete_lock=true | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
# Locked → refused, response carries explicit `locked:true` and the
# `blocked_by` id (the deepest descendant with delete_lock — for a
# leaf, that's the agent itself).
fantastic call core delete_agent id=$ID | python -c "
import json, sys
d = json.load(sys.stdin)
ok = d.get('locked') is True and d.get('blocked_by') == sys.argv[1] and 'delete_lock' in d.get('error','')
print('locked-refusal: PASS' if ok else f'FAIL d={d}')
" $ID
test -d .fantastic/agents/$ID && echo "  record still on disk: OK"
# Unlock → delete succeeds.
fantastic call core update_agent id=$ID delete_lock=false >/dev/null
fantastic call core delete_agent id=$ID | python -c "
import json, sys
d = json.load(sys.stdin)
print('post-unlock-delete: PASS' if d.get('deleted') is True else f'FAIL d={d}')
"
test ! -d .fantastic/agents/$ID && echo "  record removed: OK"
rm -rf .fantastic
```
Expected: `locked-refusal: PASS`, record still on disk, then
`post-unlock-delete: PASS`, record removed.
Regression signal: `locked` flag or `blocked_by` missing from
response → LLM callers can't programmatically detect the refusal.

### Test 8: on_delete cascade hook fires before record removal

`Agent.delete` cascades depth-first; for each descendant the substrate
calls `await agent.on_delete()` BEFORE detaching the record. Default
on_delete rmtrees the agent's disk dir. Bundles that need to tear
down process-memory state override by exposing
`async def on_delete(agent)` in their tools.py — substrate looks it
up and invokes it before the default rmtree (terminal_backend kills
its PTY, web drains uvicorn, kernel_bridge cancels its read loop).

```bash
rm -rf .fantastic
ID=$(fantastic call core create_agent handler_module=file.tools | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
# file.tools doesn't override on_delete — default rmtree fires.
fantastic call core delete_agent id=$ID | python -c "
import json, sys
d = json.load(sys.stdin)
print('default-on-delete: PASS' if d.get('deleted') is True else f'FAIL d={d}')"
test ! -d .fantastic/agents/$ID && echo "  record removed: OK"
rm -rf .fantastic
```
Expected: `default-on-delete: PASS` and `record removed: OK`.

### Test 9: cascade with nested children dies depth-first

```bash
rm -rf .fantastic
# Spawn a terminal_webapp — its _boot creates terminal_backend as a child.
PARENT=$(fantastic call core create_agent handler_module=terminal_webapp.tools | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
# Verify the child exists on disk under parent's agents/ dir.
test -d .fantastic/agents/$PARENT/agents && echo "  child dir present: OK"
# Cascade-delete the parent.
fantastic call core delete_agent id=$PARENT | python -c "
import json, sys
d = json.load(sys.stdin)
print('cascade-delete: PASS' if d.get('deleted') is True else f'FAIL d={d}')"
# Both records gone.
test ! -d .fantastic/agents/$PARENT && echo "  parent dir removed: OK"
rm -rf .fantastic
```
Expected: `child dir present: OK`, `cascade-delete: PASS`, `parent
dir removed: OK`. The cascade ran terminal_backend's `on_delete`
(real run would kill the PTY) before removing terminal_webapp.

### Test 10: unknown verb / unknown agent rejected cleanly (substrate safety net)

Every bundle's handler rejects unknown `type` values with a
deterministic error shape. This is the substrate's defense against
malformed tool_call output from LLMs (chat-template tokens leaking
into `function.name`, model hallucinating verbs, etc.).

```bash
rm -rf .fantastic
# Send a chat-template-fragment-shaped bogus verb. Quoting matters.
fantastic call core '<|"|list_agents<|"|' 2>&1 | python -c "
import sys
ok = 'unhandled system verb' in sys.stdin.read() or 'unknown' in sys.stdin.read()
print('unknown-verb-rejected: PASS' if ok else 'FAIL')"
# Send to a non-existent agent id.
fantastic call file_does_not_exist garbage_verb 2>&1 | python -c "
import sys
print('unknown-agent-rejected: PASS' if 'no agent' in sys.stdin.read() else 'FAIL')"
rm -rf .fantastic
```
Expected: both PASS lines.

## Cleanup

```bash
cd /
rm -rf /tmp/core_test
```

## Summary

| # | Test | Pass |
|---|------|------|
| 1 | kernel reflect contains primer fields + tree | |
| 2 | list_agents | |
| 3 | create_agent + auto-boot | |
| 4 | update_agent persists + emits | |
| 5 | delete_agent + dir removed | |
| 6 | REPL @-tag routes to handler | |
| 7 | delete_lock refuses; unlocks via update_agent | |
| 8 | on_delete cascade hook (default rmtree fires) | |
| 9 | cascade delete depth-first through nested children | |
| 10 | unknown verb / unknown agent rejected cleanly | |
