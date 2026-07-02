# 21 · Agent navigation — the `@`-palette + Esc home

Status: implemented

**Easy navigation through agents, AI-first, not complex.** One gesture — `@` —
navigates AND discovers: it opens a palette of every character you can face
(`ai` pinned first, then your open rooms, then agents you haven't met), and
picking one walks you into their room. Esc always steps *back*, ending at the
brain. Shift-Tab remains the lazy walk; the palette is the deliberate one.

## Design

```text
│              │ (transcript of the active room)                │
│              ┌──────────────────────────────┐                 │
│              │ @ rooms & agents             │  ← palette floats over the
│              │ ▸ @ai                        │    transcript bottom while the
│              │   @sh •                      │    @sender is being edited.
│              │   @ws                        │    ▸ = selection (magenta),
│              │   @kernel  opens room        │    • = unread, dim = not yet
│              │   @web     opens room        │    opened (picking opens it)
│              │ ↑↓ · ⏎ enter room · ⇥ complete · esc │
│              └──────────────────────────────┘                 │
│   @a▸ _                                                       │  ← typing filters
```

**Mechanics** (`chat::palette_items` — pure + unit-tested; overlay in
`render_palette`; keys in `handle_input`):

- **Opening**: `@` on an empty message enters the sender edit (as before) and the
  palette appears. Typing **filters** (prefix match); every keystroke resets the
  selection to the top.
- **Ordering — AI first**: `ai` is pinned to the top (the brain is home), then the
  OPEN rooms in tab order (unread `•` shown), then **known-but-unopened kernel
  agents** (dim, tagged `opens room`). Discovery and navigation are one list.
- **⏎ picks + enters**: the selection becomes the sender and the bare line is
  submitted — for an open room that just walks you in; for a fresh kernel agent
  the room opens **on its reflect** (bare `@id` → reflect: the introduction).
  `@ws` shows its tree. No new routing — the palette drives the existing bare-`@`
  semantics.
- **⇥ completes** to the selection and stays composing (so you can type a verb);
  landing on an open room turns to face it.
- **Esc cancels** the sender edit, restoring the sender as it was (`sender_prev`).
- **No match**: the panel says so; ⏎ falls back to the typed fragment → the nogo
  flash. You can't wander into a room that doesn't exist.

**Esc = back/home (one ladder)**: cancel a setup flow → release the PTY → cancel
the sender edit → **home to `@ai`**. Wherever you are, Esc walks you back toward
the brain. AI-first: `@ai` is always one Esc away.

**Visual language**: the palette reuses the setup-flow Select styling (`▸` mark,
magenta selection, dim hint row) — one system, nothing new to learn.

## UX

1. **`@` on an empty line** → *expect* the palette with `▸ @ai` on top, your rooms,
   then dim discoverable agents. *feel:* the cast of characters, brain first.
2. **Type `k`** → *expect* it filters to `@kernel`. *feel:* find by name, instantly.
3. **⏎ on a dim agent** → *expect* its room opens showing its reflect. *feel:*
   walking up to someone new and getting an introduction.
4. **⏎ on `@sh •`** → *expect* you're in the shell room, unread cleared. *feel:*
   answering whoever called.
5. **Esc mid-edit** → *expect* the palette closes, the sender restored. *feel:*
   never lost.
6. **Esc from any room** → *expect* you're facing `@ai` again. *feel:* home.

## Drive

```script
wait 2500
key space
wait 600
type @
wait 300
shot palette_open
type k
wait 200
shot palette_filtered
key enter
wait 2000
shot entered_kernel_room
key esc
wait 300
shot home_at_ai
```

## Judge

- **Palette opens on `@`** — PASS if the panel lists `@ai` first with the selection
  mark, open rooms next, dim unopened agents last.
- **Filter** — PASS if typing narrows the list by prefix.
- **⏎ enters** — PASS if picking `kernel` opens/focuses its room (a fresh agent
  shows its reflect).
- **Esc ladder** — PASS if Esc cancels the edit (sender restored), and from plain
  chat lands you in `@ai`.
- **Overall** — PASS if moving between agents feels like one effortless gesture,
  with the brain as the center of gravity.
