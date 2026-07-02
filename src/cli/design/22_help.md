# 22 · Help — the `/help` overlay + input history + safe paste

Status: implemented

The surface must teach itself: `/help` overlays the whole key/command map (any
key closes); an unknown `/command` prints the command list instead of leaking to
an agent as text; the composer behaves like a real input (caret, history, safe
paste). The headless twin is `fantastic --help` (see 18).

## Design

```text
│            ┌──────────────────────────────────────────────┐   │
│            │ FANTASTIC — how to play                      │   │  ← centered card,
│            │                                              │   │    floats over chat
│            │   @             palette: ↑↓ pick · ⏎ enter…  │   │
│            │   @ai …         talk to the brain (streams…) │   │
│            │   @sh <cmd>     run in the live shell (Ctrl+F│   │
│            │   @ws …         workspace kernel: up · down… │   │
│            │   @<id> [verb]  drive any agent; bare @<id>… │   │
│            │   ⇧⇥ / Esc      next room / home to @ai      │   │
│            │   ↑ ↓           recall sent lines            │   │
│            │   PgUp PgDn     scroll history (wheel too…)  │   │
│            │   ←→ Home End   move the caret in the input  │   │
│            │   /commands     /help · /intro · /setup · /model │
│            │   exit          Ctrl+Q · Ctrl+C twice · hold q │ │
│            │                                              │   │
│            │   any key closes                             │   │
│            └──────────────────────────────────────────────┘   │
```

**Mechanics**:
- `/help` (`submit_chat`) → `help_open = true`; `render_help` floats the card
  centered over the chat; **any key** dismisses it (fully consumed).
- **Unknown `/cmd`** → never routed to an agent; a dim note answers:
  `unknown command /x — /help · /intro · /setup · /model`.
- The boot Rooms note advertises `/help`, `/setup`, and the `@`-palette — and
  scrollback (12) means it can always be paged back to.
- **Input history**: every submitted line is recallable with ↑/↓ (cap 100,
  consecutive dups collapse; the in-progress draft is stashed and restored).
- **Safe paste**: bracketed paste inserts a multi-line clip as ONE message
  (newlines shown as `⏎` in the prompt, kept in the sent text); flow fields get
  it flattened; a focused PTY receives it raw.

## UX

1. **`/help` ⏎** → *expect* the card; any key returns to chat untouched. *feel:*
   the manual is one word away, and it leaves when told.
2. **`/setpu` ⏎ (typo)** → *expect* the dim unknown-command note, nothing sent to
   the model. *feel:* the game catches my typo instead of embarrassing me.
3. **Paste a 3-line snippet at `@ai`** → *expect* one prompt line with `⏎` marks;
   ⏎ sends it as one message. *feel:* paste is safe.
4. **↑** → *expect* the previous line back, editable. *feel:* a real terminal.

## Drive

```script
wait 2500
key space
wait 600
type /help
key enter
wait 400
shot help_open
key space
wait 300
shot help_closed
type /bogus
key enter
wait 300
shot unknown_cmd_hint
```

## Judge

- **Overlay** — PASS if `/help` shows the card (routing, palette, exits, commands)
  and ANY key closes it without side effects.
- **Typo guard** — PASS if an unknown `/cmd` yields the hint note and never reaches
  an agent/model.
- **History** — PASS if ↑ recalls the last line (manual/units).
- **Paste** — PASS if a multi-line paste is one message, `⏎`-marked (manual).
- **Overall** — PASS if a stranger can learn the whole surface without leaving it.
