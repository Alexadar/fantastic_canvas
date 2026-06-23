# 18 · Headless / manager CLI

Status: implemented

The same binary, no game: when stdout isn't a tty (piped, CI, scripts) or a
subcommand is given, `fantastic` runs as a **headless kernel manager**. This is the
manager's "bare reach" — a thin CLI over the in-proc host + the workspace gateway.
No agentic logic here; it just composes, sends, and prints.

## Design

```text
$ fantastic --smoke                 # compose host, reflect the id-tree, exit (CI check)
  <ansi banner: N agents>
  { "id": "core", "children": [ … ] }

$ fantastic ai "what is this repo"  # one AI turn, print the final response
  <banner>
  It's a multi-runtime kernel manager…

$ fantastic demo                    # A→Z: assemble → serve → terminal, printing each step
$ fantastic | cat                   # non-tty → headless reflect (same as --smoke tree)

# Workspace gateway (per-dir, out-of-process kernels — the headless twin of @ws, 16):
$ fantastic up [--runtime rust|python|swift] [--container]   # attach-or-spawn in cwd
  spawned core at http://127.0.0.1:54321
  { "agents": [ … ] }
$ fantastic k <id> <verb> [k=v…]    # send a verb to the workspace over HTTP, print reply
$ fantastic down                    # graceful shutdown of cwd's workspace kernel
```

**Dispatch order** (`cli/src/main.rs::main`): gateway subcommands (`up`/`k`/`down`)
→ host subcommands (`demo`/`--smoke`/`ai`|`ask`) → else tty? TUI : headless reflect.
`--runtime` parsed by `runtime_from_args` (default rust); `--container` spawns a
podman/docker kernel. The image is **`FANTASTIC_IMAGE` (or `--image`), REQUIRED** —
by default no defaults: an unset image fails loud (never a guessed tag); and a
missing image is a hard error (never pulled, `gateway::image_present`).

**Why it matters**: kernels run on their own; the manager (game or CLI) is
*optional*. The headless CLI is how scripts, CI, and power users drive the exact
same manager surface without the arcade — and how `up`/`k`/`down` give the
workspace-kernel lifecycle a plain, pipeable face.

## UX

1. **`fantastic --smoke`** → *expect* a banner + the kernel id-tree, exit 0. *feel:*
   a clean health check.
2. **`fantastic | cat`** → *expect* the reflect tree (auto-headless on no tty).
   *feel:* it does the right thing when piped.
3. **`fantastic ai "…"`** → *expect* the final answer on stdout. *feel:* scriptable
   one-shot brain.
4. **`fantastic up` in a project dir** → *expect* `spawned/attached … <url>` + the
   tree. *feel:* CLI parity with `@ws up`.
5. **`fantastic k core reflect` then `fantastic down`** → *expect* the agent's
   record, then a clean stop. *feel:* drive + tear down from the shell.

## Drive (shell, not the PTY harness)

```sh
# from src/ (these are real, runnable checks — no headful harness needed)
cargo run -q -p fantastic -- --smoke        # banner + id-tree, exit 0
cargo run -q -p fantastic -- | cat          # non-tty → headless reflect
# live-gated (spawns a process): cargo run -q -p fantastic -- up --runtime rust
```

## Judge

- **Auto-headless** — PASS if piping (no tty) prints the reflect tree, not a TUI.
- **--smoke** — PASS if banner + id-tree print and exit code is 0.
- **ai one-shot** — PASS if `ai "…"` prints a response (provider-gated).
- **Gateway parity** — PASS if `up`/`k`/`down` mirror `@ws` semantics (attach-or-
  spawn, HTTP verb, graceful stop).
- **Overall** — PASS if the manager is fully usable without the game.
