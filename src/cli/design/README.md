# `fantastic` — design ⋈ UX contracts (LLM-guided)

These markdown files are the **single source of truth for how the TUI looks and
feels** — and they are *runnable*. Each file is a **design + UX contract** that
serves three jobs at once:

1. **Design spec** — what the screen should *look* like (layout map, theme,
   glyphs, an ASCII mock of the target frame).
2. **UX flow** — what the user *does* and what should *happen* (and how it should
   *feel*): numbered `do → expect → feel` steps.
3. **LLM-guided test** — a `script` block drives the real binary in a headful
   PTY; an LLM (you) captures frames and **judges them against §Design and
   §UX**. The rubric is prose, checked by a model — not brittle string asserts.

This is the discipline we're mastering: *design statements and UX statements that
both **generate/check the UI** and **check the flow**, as one artifact.* Change the
look → update the §Design mock here first, then the code, then re-run and judge.
Change a flow → update §UX here first. The contract leads; the code follows.

## File format

```text
# <Screen / flow name>            ← what this surface is
Status: implemented | proposed    ← is it built, or a design we're proposing?

## Design                         ← the look. ASCII mock + layout map + theme notes.
## UX                             ← numbered `do → expect → feel` flow steps.
## Drive            (script)      ← harness verbs; omit for `proposed` until built.
## Judge                          ← LLM rubric over BOTH design + UX. PASS/FAIL prose.
```

## Running one (for implemented contracts)

The shared headful harness (PTY + vt100 → text frames) lives in
`../../shared/term/examples/screenshot.rs`; `../../tui/e2e/run.sh` extracts the
`script` block and runs it:

```sh
# from src/ — runs this design file's script, writes frames to /tmp/ft-e2e/<name>/
sh tui/e2e/run.sh "$(pwd)/cli/design/12_chat.md"
FT_COLS=120 FT_ROWS=34 sh tui/e2e/run.sh "$(pwd)/cli/design/10_attract.md"   # resize
```

Frames are plain text (`NN_<label>.txt`). Colors don't survive the dump, but
**layout, the `█` block-font title, message rails, and spacing do** — which is
what the rubric judges. Theme/color claims are verified by reading the code path
named in §Design (e.g. `fill_black`, `gradient`), not the frame.

## How an LLM judges a run

1. Run the `script`; read every frame.
2. For each §UX step, find the frame that should show its `expect` and confirm it.
3. Compare the settled frame to the §Design ASCII mock — same regions, same
   anchoring, nothing boxed/clipped/empty-where-it-should-be-full.
4. Write a one-line **PASS/FAIL per §Judge bullet**, then an overall verdict. On
   FAIL, name the frame + the gap, and (if it's a design drift) propose the mock
   or code change. This is the loop we use to keep the UI eye-pleasing.

## Index

Start with **[00_map.md](00_map.md)** — the state machine that ties every screen
together. It is the canonical baseline this folder develops from.

| # | Screen / flow | Status | File |
|---|---------------|--------|------|
| 00 | Screen & UX map | orientation | [00_map.md](00_map.md) |
| 10 | Attract screen | implemented | [10_attract.md](10_attract.md) |
| 11 | Intro movie | implemented | [11_intro_movie.md](11_intro_movie.md) |
| 12 | Chat surface | implemented | [12_chat.md](12_chat.md) |
| 13 | AI turn (stream + interrupt) | implemented | [13_ai_turn.md](13_ai_turn.md) |
| 14 | Kernel routing | implemented | [14_kernel_routing.md](14_kernel_routing.md) |
| 15 | Shell viewport | implemented | [15_shell_viewport.md](15_shell_viewport.md) |
| 16 | Workspace kernel | implemented | [16_workspace_kernel.md](16_workspace_kernel.md) |
| 17 | Exit affordances | implemented | [17_exit.md](17_exit.md) |
| 18 | Headless / manager CLI | implemented | [18_headless_cli.md](18_headless_cli.md) |
| 20 | Connector onboarding (dry brain · /setup) | implemented | [20_provider_onboarding.md](20_provider_onboarding.md) |
| 21 | Addressee switch (rooms + composer) | implemented | [21_addressee_switch.md](21_addressee_switch.md) |

**Numbering**: `00` orientation · `10–18` implemented screens/flows (user-journey
order) · `20+` proposed. Add a screen → new number here + in `00_map.md`.
