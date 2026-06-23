# Changing the addressee (the `@sender` composer)

Status: implemented

> **Shipped** (see [12_chat.md](12_chat.md) for the full surface). The addressee
> became a per-character **room** + an editable **`@sender`** field on the input:
> **Shift-Tab** turns to the next open room (rolls over the characters you know);
> **Tab** completes the `@sender` against every known character (base + open tabs +
> kernel agents); **Backspace** past an empty message edits the sender in place;
> a send to an unknown character is a **nogo** (the `@sender` flashes red). The one
> deviation from the proposal below: Shift-Tab cycles *open rooms* (not the full
> known set) to avoid spawning a tab per agent on every keypress — untabbed agents
> are reached by name + Tab, opened on send. The rest landed as designed.

**Problem.** Chat is one surface with many recipients (`@ai`, `@kernel`, `@sh`,
`@ws`, and any spawned workspace agent). Today you retarget by typing the full
`@name` on a line; the sticky target persists and the prompt shows `@kernel ▸`.
That's good, but **retyping a long `@agent-id` every time you switch is friction**,
and which addressees even exist isn't discoverable.

**Recommendation — make the prompt the switcher.** The addressee should be
*persistent, visible, and cyclable*: set it once, see it always in the `▸` prompt,
and change it with **zero typing**. Three complementary mechanisms, cheapest-first:

1. **`Shift+Tab` cycles the sticky target** through the live addressee ring →
   `@ai → @kernel → @sh → @ws → <spawned agents…> → @ai`, updating the prompt
   instantly. This is the zero-typing fast path. (It reuses the muscle memory of
   the old "Shift+Tab to change mode" — now that modes are gone, it cycles
   *who you're talking to* instead, which is the thing that actually varies.)
2. **`@` + `Tab` autocompletes** an addressee inline — type `@ke`▸Tab → `@kernel`.
   The precise path, essential for spawned agents with arbitrary ids.
3. **Bare `@name` ⏎ retargets only** (no empty send) — an explicit one-shot set
   when you know the name and don't want to cycle.

The `@<target> ▸` prompt is always the live truth of where the next line goes — the
switch is *visible state you steer*, never hidden.

## Design

```text
   host: 2 agents · ws: rust · @ai · @kernel · @sh · @ws · ⇧⇥ switch · Ctrl+F focus
                                                            └─ hint added to status

   … transcript …
                                                    ·                 *
   @kernel ▸ _                ← Shift+Tab →    @sh ▸ _    ← Shift+Tab →   @ws ▸ _

   ── `@` + Tab autocomplete popover (anchored at the input) ──
   @ke_                                                     │ kernel
   ┌──────────────┐   ↑/↓ move · Tab/⏎ pick · Esc cancel    │ ai
   │ ▸ kernel     │                                          │ sh
   │   …          │   (only shows on `@`+Tab; lists the      │ ws
   └──────────────┘    live ring incl. spawned agent ids)    │ rust-wk-01
```

- **The ring is live.** It's `@ai`, `@kernel`, `@sh`, `@ws`, plus every spawned
  workspace agent the manager knows — built from the kernel's reflect, not a
  hardcoded list. New agents appear in the cycle and the popover automatically.
- **Prompt = source of truth.** `@<target> ▸` always names the next recipient;
  `color_for(target)` tints the caret so the *who* is also a glance of color.
- **Status hint.** Add `⇧⇥ switch` to the status line so the fast path is
  discoverable without docs.
- **Sticky semantics unchanged.** A line with no `@` still goes to the sticky
  target; `@name …` on a line both retargets and sends (one-shot override that also
  updates sticky). Shift+Tab and `@`+Tab only move the sticky — they never send.

## UX

1. **Talking to `@ai`, want the kernel** → *expect* one `Shift+Tab` flips the
   prompt to `@kernel ▸` (or a couple taps to reach it). *feel:* instant, no typing.
2. **Want a spawned agent `rust-wk-01`** → *expect* `@`+Tab pops the list, arrow/
   type to it, Tab picks. *feel:* discoverable; I didn't memorize the id.
3. **Know exactly where** → *expect* `@kernel reflect ⏎` sends there and leaves the
   sticky on `@kernel`. *feel:* explicit override still works.
4. **At all times** → *expect* the prompt shows the current target. *feel:* I'm
   never unsure who hears my next line.

## Drive (once built)

```text
# wait 2500 ; key space ; wait 600 ; shot at_ai          # prompt @ai ▸
# key shift-tab ; wait 200 ; shot at_kernel               # prompt @kernel ▸
# key shift-tab ; wait 200 ; shot at_sh                   # prompt @sh ▸
# type @ke ; key tab ; wait 200 ; shot autocomplete       # @kernel completed
```
(*Harness note: add a `shift-tab` key mapping to `screenshot.rs` when building.*)

## Judge

- **Zero-typing cycle** — PASS if `Shift+Tab` advances the prompt target through
  the ring and wraps; FAIL if it sends a message or does nothing.
- **Live ring** — PASS if a spawned agent appears in the cycle / popover (not just
  the four built-ins).
- **Visible truth** — PASS if the `▸` prompt always matches the actual next
  recipient (and is sender-tinted).
- **Autocomplete** — PASS if `@`+Tab completes / lists known addressees including
  arbitrary spawned ids.
- **No accidental send** — PASS if switching never emits a message.
- **Overall** — PASS if changing who you talk to feels like flicking a selector,
  not retyping an address.
