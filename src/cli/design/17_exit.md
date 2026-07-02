# 17 · Exit affordances

Status: implemented

Three ways out, designed so a stray key never quits but an intent to leave always
works — even while a PTY is focused and eating keystrokes.

## Design

| Gesture | Behavior | Works when PTY focused? |
|---------|----------|--------------------------|
| **`Ctrl+Q`** | Always quits, immediately. | **Yes** (the reliable one) |
| **`Ctrl+C` ×2** | First press: a `press Ctrl+C again to exit` note + does its normal job (SIGINT to shell, or interrupt an AI stream). Second press within the window: quit. | Yes |
| **Hold `q`** | Physical key-hold **started on an empty line** → arms on the 2nd fast repeat (the first typed `q` is reclaimed, a dim `hold q to exit…` note shows), consumes the run, quits at the streak. Typing text with q's never arms — no quitting mid-word. | **No** (suppressed — `q` must reach the shell) |

**Why three** (`ctrl_c_exits`, `q_hold_streak`, both pure + unit-tested):
- `Ctrl+C` is overloaded (interrupt vs. exit), so a single press never exits — it
  warns + does the interrupt; only a deliberate double-tap quits.
- Hold-`q` is a friendly arcade-ish "just hold to leave," but it must never fire
  from normal typing: it only ARMS when the hold starts on an EMPTY composer, and
  once armed the held q's are consumed (not typed). It stays disabled while
  `term_focused` (where `q` is a normal key).
- `Ctrl+Q` is the always-available escape hatch that bypasses both nuances and the
  PTY focus.

**Esc is NOT an exit** — it steps *back*: cancel a setup flow → release the PTY →
cancel a sender edit → **home to `@ai`**. One consistent ladder (see 21).

## UX

1. **`Ctrl+C` once (no stream/shell)** → *expect* a dim `press Ctrl+C again to
   exit` note; app stays. *feel:* a safety net, no accidental quit.
2. **`Ctrl+C` twice quickly** → *expect* the app exits. *feel:* deliberate.
3. **`Ctrl+C` during an AI stream** → *expect* the stream interrupts (17 defers to
   13); a *second* press exits. *feel:* interrupt first, exit only if I insist.
4. **Hold `q` on the EMPTY chat input** → *expect* a dim `hold q to exit…` note,
   the q's are consumed (not typed), then the app exits. *feel:* casual, arcade.
   Typing a word full of q's neither quits nor loses characters.
5. **Hold `q` while shell-focused** → *expect* `qqqq` reaches the shell, no exit.
   *feel:* the terminal owns my keys.
6. **`Ctrl+Q` anytime** → *expect* immediate exit. *feel:* the dependable door.

## Drive

```script
wait 2500
key space
wait 600
key ctrl-c
wait 300
shot warned          # expect the "press Ctrl+C again to exit" note
key ctrl-c
wait 500
shot exited          # expect the app has quit / terminal returns
```

## Judge

- **Single Ctrl+C warns** — PASS if the note appears and the app survives.
- **Double Ctrl+C exits** — PASS if the second press quits.
- **Hold-q exits, focus-suppressed, typing-safe** — PASS if a rapid `q` run from an
  empty line quits (with the hint note), typed q's inside a word never quit, and a
  shell-focused hold reaches the shell (trust `q_hold_streak` units + manual).
- **Ctrl+Q always** — PASS if it exits even with the PTY focused.
- **Overall** — PASS if leaving is easy on purpose and impossible by accident.
