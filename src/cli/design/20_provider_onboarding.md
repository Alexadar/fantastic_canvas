# 20 · Connector onboarding — dry brain · /setup · /model

Status: implemented

The tool is **hermetic with optional connectors** — nothing is configured until you
wire it. First-run UX: a **dry stand-in brain** answers `@ai` with setup guidance,
and **`/setup` · `/model`** add a provider + model + key through a **dynamic input**
(select / masked field). Keys live in the **OS keychain**, never on disk. Built
"fuzzy now, crystallize later" — the dry-brain trait + the input-control model are
the seams the bundled lite-LLM + a formal protocol fill later.

## Design

```text
First @ai with nothing set — the DRY stand-in answers (not a raw ✗):
   │ you: hello
   │ brain: No AI connector is set up yet.
   │        Run /setup to add a provider + model — the key is stored
   │        in your OS keychain. (/model to change later.)

/setup → a guided flow drives the dynamic input control:
   ⚙ Choose a provider                ⚙ Model id                ⚙ nvidia API key
   ▸ ollama                            ▸ meta/llama-3.1-8b        ▸ ••••••••••••••
     nvidia                            enter · esc cancel         enter · esc cancel
     anthropic                         (Field, plain text)        (Field, MASKED)
   ↑↓ select · enter · esc cancel
   (Select)

   → │ brain: connector set: ollama · gpt-oss:120b-cloud — @ai is ready.
```

**Dry stand-in brain** (`ai::dry`, the brain slot) — `config_status()` classifies the
(hydrated) env: `NoBackend` / `NoModel` / `NoKey(provider)` / `Ready`. When not
`Ready`, `dry_reply` returns guidance (a normal `@ai` message); the real brain only
provisions when `Ready`. A `Ready` turn that fails as **unreachable** (`is_unreachable`)
also gets dry "set another" guidance instead of a raw error. The `DryBrain` trait is
the protocol seam the bundled lite-LLM implements later.

**Dynamic input** (`input::Control`) — the input row is `Chat` (the composer)
normally; a flow switches it to `Select { options, cursor }` (↑/↓ + Enter) or
`Field { value, masked }` (type/Backspace + Enter, masked → `•`). **Esc** cancels the
flow. `SetupFlow` is the wizard: `/setup` = Provider→Model→(Key if nvidia/anthropic);
`/model` pre-fills the provider and jumps to Model. Pure + unit-tested.

**Keychain + CRUD** (`fantastic_host`) — settings hold `ai.backend`/`ai.model`; the key
goes to the OS keychain (`keyring`: Keychain / Secret Service / Credential Manager) via
`secret::*`, NEVER `settings.json`. `set_ai_connector` / `ai_config` (key as a bool) /
`clear_ai_connector` are the CRUD. No keychain → fails loud (set the key via env). On
flow done: persist + update env + **re-provision** (drop the old brain) → `@ai` ready.

**CLI parity** — `fantastic config set ai.key …` routes the key to the keychain (not
JSON); `fantastic config clear` deletes the connector.

## UX

1. **First `@ai` (no config)** → *expect* a `brain:` guidance line, not a raw `✗`.
   *feel:* it's onboarding me, not broken.
2. **`/setup`** → *expect* an arrow-key provider list; ↑/↓ + Enter. *feel:* a guided wizard.
3. **Model step** → *expect* a text field. **Key step** (nvidia/anthropic) → *expect* a
   **masked** field. *feel:* the key is never shown.
4. **Finish** → *expect* `connector set: … — @ai is ready`; the next `@ai` answers.
5. **`/model`** → *expect* it keeps the provider/key, just re-asks the model.
6. **Esc** mid-flow → *expect* back to chat, nothing saved.
7. **Configured model unreachable** → *expect* dry "set another / /model" guidance.

## Drive

```script
wait 2500
key space
wait 700
type @ai hello
key enter
wait 1000
shot dry
type /setup
key enter
wait 400
shot provider
key down
wait 200
key enter
wait 300
type meta/llama-3.1-8b
wait 400
shot model
key enter
wait 300
type sk-demo-key
wait 400
shot key_masked
key esc
```

## Judge

- **Dry, not raw** — PASS if first `@ai` with no config yields a `brain:` guidance line
  mentioning `/setup`, not a bare `✗`.
- **Select** — PASS if `/setup` shows the provider list with a cursor; ↑/↓ moves it.
- **Field + mask** — PASS if the model field shows typed text and the key field shows
  `•` dots (never the raw key).
- **Persisted + ready** — PASS if finishing posts "connector set … ready" and the key is
  in the keychain, NOT in `settings.json` (covered by the `ai_crud` e2e test).
- **Esc cancels** — PASS if Esc returns to the composer with nothing saved.
- **Overall** — PASS if a brand-new user gets from `@ai` to a working connector through
  the guided flow, with the key safe in the OS keychain.
