# 00 · Screen & UX map

Status: orientation (the canonical baseline)

This is the whole product surface, on one page — every screen, how they connect,
and which contract file owns each. **It is the point from which the design
develops.** Add a screen → add its number here + a contract file; change a
transition → update this diagram first.

## The state machine

```text
                       (tty launch)
                            │
                            ▼
                  ┌──────────────────┐   idle 10s    ┌──────────────────┐
                  │   10 ATTRACT     │ ───────────▶  │ 11 INTRO MOVIE   │
                  │ stars+FANTASTIC  │               │ 5 scenes, loops  │
                  │ "press any key"  │ ◀───────────  │  SCENE n/5       │
                  └──────────────────┘  movie ends   └──────────────────┘
                       │      ▲                            │
                 any key│      │ (never returns once       │ any key
                        ▼      │  you've entered chat)      ▼
                  ┌─────────────────────────────────────────────────┐
                  │                 12 CHAT  (one surface)           │
                  │  borderless · bottom-anchored · stars behind     │
                  │                                                  │
                  │  the `@`-router sends each line somewhere:       │
                  │   @ai   ──▶ 13 AI TURN     (stream + interrupt)  │
                  │   @<id> ──▶ 14 KERNEL      (verb / reflect)      │
                  │   @sh   ──▶ 15 SHELL       (breathing PTY)       │
                  │   @ws   ──▶ 16 WORKSPACE   (spawn/attach kernel) │
                  │   /intro ─▶ 11 INTRO MOVIE (manual replay)       │
                  └─────────────────────────────────────────────────┘
                        │                                   ▲
                        │ Ctrl+F focus ↔ Esc release        │ sticky target persists
                        ▼                                   │ (⇧⇥ / @-palette — 21)
                  ┌──────────────────┐                      │
                  │ 15 SHELL FOCUS   │ ─────────────────────┘
                  │ full PTY keys    │
                  └──────────────────┘

   17 EXIT (from anywhere): Ctrl+Q · Ctrl+C twice · hold q
   18 HEADLESS (no tty / subcommands): up · k · down · ai · demo · --smoke
```

## Routing rules (the heart of the chat)

Chat is **a room per character**: addressing someone opens/enters their room
(`chat::Tabs`); the active room is who you face. The input is a smart `@sender`
field (`chat::Composer`) — editable, Tab-completable, **nogo** on an unknown
sender. One line resolves against the active room (`chat::route`):

| You type                | Goes to        | Room after   | Contract |
|-------------------------|----------------|--------------|----------|
| `@ai <text>`            | the brain      | `ai`         | 13 |
| `<text>` (no `@`)       | active room    | unchanged    | (reuse)  |
| `@<id> <verb> [k=v…]`   | kernel agent   | `<id>` (opens) | 14 |
| `@<id>` (bare)          | reflect `<id>` | `<id>` (opens) | 14 |
| `@sh <cmd>` / `<cmd>`   | live PTY       | `sh`         | 15 |
| `@ws up [rt]` / `down`  | gateway        | `ws`         | 16 |
| `@ws <verb>`            | workspace root | `ws`         | 16 |
| `/intro`                | movie (local)  | unchanged    | 11 |
| `/setup` · `/model`     | connector wizard (local) | unchanged | 20 |
| `/help`                 | overlay (local) | unchanged   | 22 |
| `/…` (unknown)          | command hint (local) | unchanged | 22 |

Switching rooms (input affordances, no send): **`@` opens the palette** (ai first,
open rooms, discoverable agents — ↑↓/⏎/⇥/Esc) · **Shift-Tab** turns to the next
open room · **Esc** comes home to `@ai` · **Backspace** past an empty message edits
the sender. The prompt `@<sender> ▸` is the live truth of where the next line goes;
an unknown sender flashes red and is **not** sent. See [21](21_addressee_switch.md).

## Theme (global, all screens)

**Dark, always — no light theme.** Opaque black sky (`fill_black` fills the buffer
first), white/gray twinkling stars (`movie::starfield`, shared by attract + chat +
intro), one bright magenta→violet accent for the title and sender rails. See each
contract's §Design for the per-screen specifics.

## Index

| # | Screen / flow | Status | Contract |
|---|---------------|--------|----------|
| 00 | Screen & UX map (this) | orientation | `00_map.md` |
| 10 | Attract screen | implemented | `10_attract.md` |
| 11 | Intro movie | implemented | `11_intro_movie.md` |
| 12 | Chat surface | implemented | `12_chat.md` |
| 13 | AI turn (stream + interrupt) | implemented | `13_ai_turn.md` |
| 14 | Kernel routing | implemented | `14_kernel_routing.md` |
| 15 | Shell viewport | implemented | `15_shell_viewport.md` |
| 16 | Workspace kernel | implemented | `16_workspace_kernel.md` |
| 17 | Exit affordances | implemented | `17_exit.md` |
| 18 | Headless / manager CLI | implemented | `18_headless_cli.md` |
| 20 | Connector onboarding (dry brain · /setup) | implemented | `20_provider_onboarding.md` |
| 21 | Agent navigation (@-palette + Esc home) | implemented | `21_addressee_switch.md` |
| 22 | Help overlay · input history · safe paste | implemented | `22_help.md` |

See `README.md` for the contract format + how an LLM drives/judges a run.
