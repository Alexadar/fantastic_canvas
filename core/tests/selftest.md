# Fantastic Core CLI Self-Test

> Last aligned with branch `claude/plan-ai-integration-Y0GLv` on 2026-04-13.
> If you're testing a later branch, cross-check the summary table against
> `git log main..HEAD` before trusting it.

**Scope: core + CLI + AI bundles ONLY.** No UI, no WebSocket, no HTTP tests,
no browser. This selftest drives the `fantastic` CLI interactively and
verifies the `@{agent_id}` routing layer, dispatch tool calls with
`key=val` kwargs, `cli_sync` with tool-call round-trip, the
`fantastic_agent` → AI-bundle proxy flow, **plus** the Snapchat CLI chrome
and the "nothing auto-created on fresh start" bootstrap invariant.

For the broader UI / transport / canvas selftest, see
`bundled_agents/canvas/tests/selftest.md`.

---

## For Claude Code (automated)

Read this file end-to-end, then:

1. Run the pre-flight backend check.
2. Wipe `.fantastic` and start `uv run fantastic` fresh.
3. Execute the tests below in order by writing to the input FIFO or typing
   into the interactive loop.
4. Report results using the summary table.

**Before you start — ASK THE USER:**

> Which AI provider should I use for this CLI selftest?
> - **Ollama** (local): which endpoint and which model? (e.g. `http://localhost:11434` + `gemma4:e2b`)
> - **Anthropic**: confirm `ANTHROPIC_API_KEY` is set in `.env` and name the model.
> - **OpenAI**: confirm `OPENAI_API_KEY` is set in `.env` and name the model.
> - **None** — skip Tests 2–8 (everything that needs a live AI agent).

Record the user'"'"'s answer explicitly in the final report. Without a live
provider, Tests 2–8 MUST be skipped — do not silently fail them, and do
not invent a provider. Tests 1, 9–11 still run without AI.

## Pre-flight step 1: verify the declared LLM backend works

Do this BEFORE wiping anything. If the user described an LLM backend, confirm
it's reachable first — no point wiping state only to discover the provider
is down.

- **Ollama**: `curl -s http://localhost:11434/api/tags | head` — confirms
  reachable; confirm the named model is listed.
- **Anthropic**: verify `ANTHROPIC_API_KEY` is in `.env`; do a minimal probe.
- **OpenAI**: same — key in `.env`, probe `/v1/models`.

If the check fails, STOP and report to the user. Do not wipe `.fantastic`.
If no provider was described, skip Tests 3–7 and note it in the final report.

## Pre-flight step 2: wipe and rebuild like a user

```bash
pkill -f "fantastic" 2>/dev/null; sleep 1
rm -rf .fantastic
uv run fantastic      # interactive, background; drive via stdin/FIFO
```

The CLI prints a hint on first start since no agents exist:
```
No agents yet. To bootstrap a default canvas+web, type:
    add quickstart
Or add bundles individually, e.g. `add web`, `add canvas`, `add ollama`.
```

Do NOT run `add quickstart` — it creates a web agent which is out of scope.

---

## CLI surface being tested

The CLI input loop accepts three shapes:

1. `@core <cmd>` — core commands (`add`, `remove`, `list`, `log`, `say`)
2. `@{agent_id} <tool> key=val ...` — invoke a dispatch tool on that agent
   (agent_id auto-injected)
3. `@{agent_id} <free text>` — call the bundle's `cli_sync(agent_id, text)`
   hook, which runs the full tool-calling loop synchronously and prints the
   accumulated reply

Values in `key=val` are coerced: `true`/`false`, ints, floats, JSON
(`{...}` / `[...]`), otherwise string. Use shell quoting for spaces:
`model="gemma2 small"`.

---

## Tests

### Test 1: `@core list` — bundles discovered

```
list
```
Expected: all bundles listed as `[available]` after fresh start. Includes
`canvas`, `terminal`, `html`, `web`, `fantastic_agent`, `quickstart`,
and one entry per AI bundle (`ollama`, `openai`, `anthropic`, `integrated`).

### Test 2: `add ollama` creates agent with discovered defaults

```
add ollama
```
Expected: `ollama 'main' created: ollama_<hex6>  model=<first-discovered>`.
Save the id as `AI_ID`.

For other providers (`add anthropic` / `add openai` / `add integrated`),
verify the same shape: one agent created per explicit `add`.

### Test 3: `@{id} <tool> key=val` — flat-kwarg dispatch

```
@AI_ID update_agent model=gemma4:e2b
```
(Substitute a model your provider actually serves.)
Expected: printed `update_agent: {'agent_id': 'AI_ID', 'model': '…'}`.
Verify `.fantastic/agents/AI_ID/agent.json` now contains the new `model`.

### Test 4: `@{id} read_agent` — agent_id auto-injected

```
@AI_ID read_agent
```
Expected: full metadata dict for the agent. Confirms that dispatch tools
called through `@{id}` automatically get `agent_id=<id>` injected.

### Test 5: Multi-field `update_agent` persists to `agent.json`

```
@AI_ID update_agent endpoint=http://localhost:11434 custom_tag=selftest
```
Expected: both fields in the response and in `agent.json`.

### Test 6: `@{id} <text>` runs `cli_sync`

```
@AI_ID reply with exactly the word: hello
```
Expected: the agentic loop runs, accumulates a final reply, prints under
the `AI_ID:` prefix. No streaming — one block at the end.

### Test 7: `@{id} <text>` with **tool call round-trip**

```
@AI_ID use the list_agents tool and tell me how many agents exist
```
Expected: the model invokes the `list_agents` dispatch tool mid-loop,
receives the result, and summarizes it in the final reply (e.g.
`"There is 1 agent."` when only `AI_ID` exists). Skip if your model
does not support tool-calling.

### Test 8: `add fantastic_agent` proxy + configure + round-trip

```
add fantastic_agent
```
Save the `fantastic_agent_<hex6>` as `FA_ID`.

```
@FA_ID fantastic_agent_configure upstream_agent_id=AI_ID upstream_bundle=ollama
```
(Use the correct `upstream_bundle` for your provider.)
Expected: `{'ok': True, 'agent_id': 'FA_ID', 'upstream_agent_id': 'AI_ID', 'upstream_bundle': '...'}`.

```
@FA_ID reply in one word: yes
```
Expected: message routed through `FA_ID` → `{upstream_bundle}_send` on
`AI_ID` → reply appears, and `.fantastic/agents/FA_ID/chat.json` now has
both the `user` and `assistant` messages.

### Test 9: Unknown `@{tag}`

```
@nope_xyz hello
```
Expected: `unknown: @nope_xyz` (or similar one-line error — no crash).

### Test 10: Dispatch error path

```
@AI_ID update_agent
```
Expected: `[ERROR] No options provided` — no crash, no halt.

### Test 11: `remove <bundle>` cascade

```
remove ollama
```
Then `list` — bundle is back to `[available]`, no instances. Verify
`.fantastic/agents/AI_ID/` has been deleted.

---

## Part C: CLI chrome + bootstrap invariants

These run without any AI provider. Capture stdout of the `fantastic`
process (tee the FIFO-driven shell or scrape the background-task output
file) and grep for the patterns below.

### Test C1: Fresh-start hint is printed

After `uv run fantastic` boots against a wiped `.fantastic`, captured
stdout MUST contain:
```
No agents yet. To bootstrap a default canvas+web, type:
    add quickstart
```
Regression signal: if this string is missing, core is silently auto-adding
something on boot. STOP and investigate before proceeding.

### Test C2: Nothing is auto-created

Immediately after boot, type `list` in the CLI. Expected output:
every bundle listed as `[available]`, zero instances. Verify
`ls .fantastic/agents/ 2>/dev/null` prints **no** directories.
Regression signal: if any agent exists, something is auto-creating.

### Test C3: Recursive bundle discovery finds `ai/*`

In the `list` output from C2, these bundle names MUST all appear:
`ollama`, `openai`, `anthropic`, `integrated`, `fantastic_agent`,
`canvas`, `terminal`, `html`, `web`, `quickstart`.
Proves the plugin loader's recursive scan descends into
`bundled_agents/ai/` (the AI bundles live at `ai/ollama/`,
`ai/openai/`, etc., not at the top level).

### Test C4: `add` is idempotent on display name

```
add ollama
add ollama
```
Second invocation MUST print `ollama 'main' already exists: ollama_<hex6>`
and NOT create a second agent. Verify `ls .fantastic/agents/ | grep ollama_`
returns exactly one directory.

### Test C5: `@{id} <tool>` exception path

```
@<ollama_id> update_agent
```
(No kwargs supplied — dispatch returns `{"error": "No options provided"}`.)
Expected: a single `[ERROR] …` line printed, prompt returns. Proves the
error-returning-ToolResult path in `_handle_agent_message` prints cleanly
and the prompt remains live.

### Test C6: Snapchat block renderer (visual / grep)

Against captured stdout, these exact ANSI substrings MUST appear:
- `\n\x1b[32m\x1b[1muser\x1b[0m\n\n` — user header: `\n`, green+bold, `\n\n`.
- `\x1b[32m█\x1b[0m ` — green bar + space (body line of a user message).
- `\n\x1b[35m\x1b[1mfantastic\x1b[0m\n\n` — `fantastic` messages are magenta.
- For any agent message, the bar color matches the name color
  (cyan `\x1b[36m` for bundles, yellow `\x1b[33m` for `ai`).

Prompt line (visible in the captured output right before each user
input):
- `\x1b[32m█\x1b[0m \x1b[32m>\x1b[0m ` — green bar, space, green `>`, space.

Regression signal: if any of these patterns are absent, `format_entry`
or the `prompt_toolkit` prompt shape has regressed.

---

## Summary

Report:

| # | Test | Pass |
|---|------|------|
| 1 | `@core list` | |
| 2 | `add ollama` creates agent | |
| 3 | `@{id} <tool> key=val` | |
| 4 | `@{id} read_agent` (auto-injected id) | |
| 5 | Multi-field `update_agent` persistence | |
| 6 | `cli_sync` reply | |
| 7 | `cli_sync` tool-call round-trip | |
| 8 | `fantastic_agent` proxy → upstream | |
| 9 | Unknown `@tag` | |
| 10 | Dispatch error path | |
| 11 | `remove` cascade | |
| C1 | Fresh-start hint printed | |
| C2 | Nothing auto-created | |
| C3 | Recursive discovery finds `ai/*` bundles | |
| C4 | `add` idempotency on display name | |
| C5 | `@{id} <text>` without `cli_sync` | |
| C6 | `@{id} <tool>` exception path | |
| C7 | Snapchat block renderer (visual) | |

Also report:
- Which AI provider was used.
- Whether tool-calling Test 7 was run or skipped (not all models support it).
- Any unexpected errors or crashes.

## Out of scope

- WebSocket dispatch, `fantastic_transport()`, any browser-based test.
- The `web` bundle, uvicorn hot-reload, content aliases HTTP serving,
  terminal PTY, canvas VFX, scheduler.
- For those, use `bundled_agents/canvas/tests/selftest.md`.
