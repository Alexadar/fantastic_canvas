# 15 · Shell viewport (`@sh`)

Status: implemented

A real terminal is one keystroke away, inside the chat. `@sh <cmd>` runs in a live
PTY whose screen **breathes** into the chat body; `Ctrl+F` focuses it for full
interactivity; `Esc` (or `Ctrl+F`) releases back to the chat input.

## Design

```text
   │ you → sh:  $ ls -la                              ← command echoed as a chat line
   ┌ (breathing PTY viewport — the live terminal screen, rendered into chat) ┐
   │ total 24                                                                 │
   │ drwxr-xr-x  …  src                                                       │
   │ …                                                                        │
   └─────────────────────────────────────────────────────────────────────────┘
   @sh ▸ _            ·  Ctrl+F focus            (focused: keys go straight to PTY)
```

**Mechanics** (`Route::Shell` → `run_shell`; `TerminalSession` in `fantastic-term`):
- `@sh <cmd>` (or any bare line once sticky is `sh`) writes the command to the live
  PTY; its screen is sampled (`used_rows`) and rendered as a viewport in the chat
  body — it updates as the program runs ("breathing").
- **Room-scoped (`term_visible`)**: the PTY is shared but the viewport renders —
  and Ctrl+F / SIGINT apply — ONLY while you're in the `@sh` room
  (`term_active && active_id == "sh"`). In every other room the viewport is hidden;
  a long-lived `top`/`htop` keeps running but does NOT bleed into `@ai`/`@ws`/agent
  rooms. (Regression guard: before this gate, an active PTY streamed into every
  room.) Shift-Tab back to `@sh` to see it again.
- **Focus toggle**: `Ctrl+F` flips `term_focused` (only when the viewport is
  on-screen — i.e. the `@sh` room). Focused → `encode_key` sends every keypress to
  the PTY (full interactivity: vim, htop, REPLs); `Esc`/`Ctrl+F` release focus.
- **Signals**: `Ctrl+C` while focused or in the `@sh` room forwards `0x03` (SIGINT)
  to the shell; in any other room Ctrl+C interrupts the AI stream instead. The
  app-exit Ctrl+C still needs a *second* press (17); `q` is NOT hold-to-quit while
  focused.
- Sticky normalizes to `sh`, so follow-up bare lines keep running in the terminal.

## UX

1. **`@sh echo hi` ⏎** → *expect* the command echoes and the PTY viewport shows
   `hi`. *feel:* a terminal grew inside the chat.
2. **`Ctrl+F`** → *expect* focus moves into the viewport (chat input inert).
   *feel:* I'm typing in the shell now.
3. **Run something interactive (`htop`), then `Esc`** → *expect* live keys reach
   it; Esc returns to chat. *feel:* a real terminal, then back to the conversation.
4. **`Ctrl+C` in a running command** → *expect* the command is interrupted, app
   stays. *feel:* SIGINT, as in any shell.

## Drive

```script
wait 2500
key space
wait 600
type @sh echo hello-from-sh
key enter
wait 1200
shot sh_output
key ctrl-f
wait 300
shot sh_focused
```

## Judge

- **Viewport** — PASS if `hello-from-sh` shows in a breathing PTY region inside the
  chat (not a one-shot dumped line).
- **Focus** — PASS if `Ctrl+F` visibly changes focus (e.g. prompt/affordance), and
  Esc/Ctrl+F releases.
- **Signal isolation** — PASS if `Ctrl+C` interrupts the command but the app
  survives (manual; needs a long-running command).
- **Sticky** — PASS if a follow-up bare line runs in the same shell.
- **Overall** — PASS if "a terminal is one keystroke away" feels true.
