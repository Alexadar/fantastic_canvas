# 13 · AI turn (status + interrupt)

Status: implemented · live-gated (needs a provider)

`@ai <text>` drives the brain. A live **status indicator** (`⟳ thinking…`) shows
while it works; the answer arrives complete (atomic) at the bottom; `Ctrl+C`
interrupts. One turn at a time; extra lines queue and concatenate. (Token-by-token
streaming is deferred — see the §Atomic-answer note for why.)

## Design

```text
   │ you: summarize this repo
   │ brain: ⟳ thinking…                                    ← status indicator (no tokens yet)
   │ brain: It's a multi-runtime kernel manager that…▌     ← live token stream, ▌ caret
   @ai ▸ _
```

**Mechanics** (`submit_chat` → `Route::Ai` → `fire_ai_turn`):
- Push your line, then `start_stream(brain, you)` opens an empty `Streaming`
  message. `Transcript::on_event` routes backend events: `token` appends text ·
  `say` → dim `Note` · `status` with a tool → dim `Tool` line · `done` seals.
- **Live status via `watch`** — the ollama backend (cli-round-trip route) emits its
  token/status events to the **brain's own inbox**, NOT ours. `fire_ai_turn` calls
  `kernel.watch(brain, CLIENT_ID)` once to mirror that inbox into our `"fantastic"`
  inbox. We consume ONLY the `status` events from it (the phase indicator).
- **Status indicator** — `status` events carry a `phase`; `App.ai_phase` tracks it
  (`sending → thinking → generating`) and shows `⟳ <phase>…` on the brain line until
  the answer arrives. Cleared when the turn ends.
- **Atomic answer = send completion** (`ai_rx`): the blocking reply's `response`
  (or `✗ error`) is the authority — `close_stream` fills the empty brain line with
  it and seals. Token events are deliberately NOT rendered live: appending tokens
  races with the AI queue's cross-turn boundaries (the shared `brain` stream key)
  and **splits answers** (observed: "How can I help you" … queued lines … "today?").
  Correct token-by-token streaming needs per-turn stream ids in the kernel protocol
  — a follow-up. Today: live phase indicator + the complete answer, correctly ordered.
- **One in-flight turn + queue-concat (Claude-Code style, AI-only)**: `chat_busy`
  guards re-entry — extra `@ai` lines typed mid-turn show immediately and **queue**
  (`App.pending`). When the turn ends, the whole queue is **concatenated with `\n`**
  and sent as ONE next turn (not N separate turns). Only `@ai` queues; other rooms
  dispatch immediately.
- **Config (hermetic + hydrated)**: backend + model are REQUIRED and explicit —
  nothing is guessed. Precedence: env (`FANTASTIC_AI_BACKEND`/`FANTASTIC_AI_MODEL`)
  > the persisted **`<app_home>/settings.json`** (hydrated into env at startup by
  `fantastic_host::hydrate_ai_env`). Set it once: `fantastic config set ai.backend
  ollama` + `fantastic config set ai.model gemma4:12b` (then `@ai` works every
  launch, no exports). Unset → a clear `✗ set FANTASTIC_AI_MODEL …` (no guess).
- **Lazy provision**: first turn calls `ai::ensure_brain` (file_bridge history +
  backend agent at app-home). Provisioning errors surface as a `✗ …` line in the
  same transcript (see 20 for the proposed onboarding card that drives this config
  from inside the chat).
- **Error path (no hang)**: a backend error (e.g. an uninstalled model →
  `ollama: HTTP 404`) comes back as the reply's `error`; `fire_ai_turn` sends `✗ …`
  through `ai_rx` and `close_stream` writes it into the brain line. The turn always
  resolves — it never hangs on an empty `brain:`.
- **Interrupt**: `Ctrl+C` once → `interrupt_live` flips the live message to
  `Interrupted`, clears busy, and sends `{type:interrupt}` to the brain. The
  partial text stays (you keep what streamed). (A *second* Ctrl+C in the window
  exits the app — see 17.)
- **Sender color**: `ai`/`brain` get a stable non-white rail via `color_for`.

**Thin shell**: the agentic loop, tools, prompt assembly all live in the kernel
backend — the TUI only opens a stream, routes events, and renders. No AI logic here.

## UX

1. **`@ai <question>` ⏎** → *expect* your line, then a reply that grows live at the
   bottom (bottom-anchored, hugging the input). *feel:* a brain thinking out loud,
   not a spinner then a dump.
2. **Brain uses a tool** → *expect* a dim `[tool …]` line appears inline. *feel:*
   you can see it working.
3. **`Ctrl+C` mid-stream** → *expect* the stream stops, the message marked
   interrupted, partial text retained, prompt ready. *feel:* I'm back in control
   instantly; nothing lost.
4. **`@ai` again while a turn runs** → *expect* it's deferred (your line kept),
   not interleaved. *feel:* one conversation at a time.

## Drive

```script
# Requires a reachable provider (ollama default). In CI this is ollama-gated;
# run locally with ollama up, or set FANTASTIC_AI_BACKEND + a key.
wait 2500
key space
wait 600
type @ai say the single word OK and nothing else
key enter
wait 4000
shot ai_reply
```

## Judge

- **Streaming** — PASS if the reply appears as a growing message at the bottom
  (capture mid-stream across waits if possible), not all-at-once after a freeze.
- **Bottom-anchored** — PASS if the live message hugs the input.
- **Interrupt** — PASS if `Ctrl+C` halts the stream and keeps partial text (manual).
- **No-provider path** — PASS if, with no provider, the turn yields a clean `✗`
  line (today) / the onboarding card (once 20 ships) — never a hang.
- **Overall** — PASS if it feels like a live, interruptible chat with a brain.
