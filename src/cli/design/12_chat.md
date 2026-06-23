# Chat surface — rooms + smart composer

Status: implemented

Not one mixed feed — **a chat per character, and you tab between them.** Each
addressee (`@ai`, `@sh`, `@ws`, or any agent you address) owns its own room;
addressing someone *walks you into their room*; Shift-Tab turns to face the next.
The input is a smart `@sender` field you can edit, complete, and roll. It's the
game's conversation layer.

## Design

```text
┌ 110×30 — full-bleed dark sky; chat insets ~2 cells from every edge ────────────┐
│   ·          *              .                    ·            *           .     │  ← starfield
│   █                                                                            │  ← HEADER BANNER (3 rows):
│   █  FANTASTIC                                                                  │    neon-magenta bar │ title
│   █  @ai  @sh  @ws  @kernel  ·  ws:none · 6 agents · ⇧⇥ rooms · Ctrl+F          │    on the middle │ TAB BAR
│        ·                                                              *         │    on the bottom row.
│   *                  .          (each room shows ONLY its own chat)             │    active chip = bold+ul;
│                ·            messages grow UP from just above the input          │    •@id = unread dot
│   ·       *                                  .                    ·       *     │
│              │ → list_agents kernel                                             │  ← the @kernel room:
│              │ kernel: { "agents": [ { "id": "core" } ] }                       │    only its exchange
│        *                              ·                                 .       │  ← 1-row gap (stars)
│   @kernel ▸ list_agents_                                                        │  ← SMART COMPOSER
└────────────────────────────────────────────────────────────────────────────────┘
        └─ editable @sender ─┘ └ ▸ ┘ └─ message ─┘
```

**Per-character rooms** (`chat::Tabs`) — `@ai`/`@sh`/`@ws` are the base rooms;
addressing any agent (`@kernel`, `@web`, a spawned id) **opens its room on the
fly**. Each room is its own `Transcript`; the body renders only the active room's
history (so the brain's chat and the kernel's chat never bleed together). A room
that gets a message while you're elsewhere shows a `•` unread dot in the tab bar.

**Header banner** (`render_chat_header`, 3 rows) — a neon-magenta (`Indexed(165)`)
vertical `█` bar down the left, **`FANTASTIC`** (bright magenta, bold) on the
middle row, and the **tab bar** on the bottom row. Mirrors the headless
`ansi_banner` so the TUI and CLI share one mark.

**Tab bar** (bottom row of the header) = the indicator of who's in the world and
who you face. Each chip is `color_for(id)`-tinted; the active one is bold +
underlined. Tail shows ws state, agent count, and the `⇧⇥ rooms` / `Ctrl+F` hints.

**Smart composer** (`chat::Composer`) — the prompt is an **editable `@<sender>`
field + the message**:

- **Backspace past an empty message steps into the sender** — edit/delete the
  `@sender`, not just the text.
- **Tab completes** the sender against every known character (base rooms + open
  tabs + kernel agents); landing on an open room turns to face it.
- **Shift-Tab turns to the next open room** (rolls over the characters you know);
  the composer follows. New agents are reached by name + Tab, opened on send.
- **`@` on an empty message** jumps to retyping the sender from scratch; a space
  commits it back to the message.
- **Nogo**: a send to a sender that names no known character is **rejected** (the
  `@sender` flashes red), never sent.

**Bottom-anchored** — newest hugs the input; a short room leaves the empty space
(starfield) at the top. Anchoring counts visual rows so wrapped lines never clip.

**AI room specifics** (see [13_ai_turn.md](13_ai_turn.md)) — `@ai` streams live;
extra `@ai` lines typed mid-turn **queue** and fire in order; a backend error
**seals** the stream (you never get a hung empty `brain:`).

## UX

1. **Enter from attract** → *expect* the tab bar (`@ai @sh @ws` active `@ai`), a
   one-time Rooms note in the `@ai` room, the `@ai ▸` composer. *feel:* a console
   with rooms, not a blank box.
2. **`@kernel list_agents` ⏎** → *expect* a new `@kernel` chip appears, you're
   moved into it, and it shows only the `→ list_agents` + `core` reply. *feel:* you
   walked into the kernel's room.
3. **Shift-Tab** → *expect* the active chip advances `@ai→@sh→@ws→@kernel→…`, the
   body swaps to that room, the prompt retargets. *feel:* turning to face someone.
4. **Type `@we` then Tab** → *expect* it completes to `@web` (a known agent).
   *feel:* I don't memorize ids.
5. **Backspace from an empty message** → *expect* the cursor edits the `@sender`.
   *feel:* the addressee is mine to change, in place.
6. **`@ghost hi` ⏎** → *expect* the `@sender` flashes red, nothing sends. *feel:* I
   can't talk to someone who isn't there.
7. **AI replies while you're in another room** → *expect* a `•` on `@ai`. *feel:*
   someone's calling from the other room.

## Drive

```script
wait 2500
key space
wait 600
shot empty
type @kernel list_agents
key enter
wait 2500
shot kernel_reply
```

## Judge

- **Rooms isolate** — PASS if the `@kernel` room shows only its exchange and the
  `@ai` Rooms note is absent there; FAIL if histories bleed together.
- **Tab opens + switches** — PASS if `@kernel` appears in the bar and becomes the
  active (bold) chip with prompt `@kernel ▸`.
- **Tab bar** — PASS if chips render per open room with the active one distinct.
- **Composer** — PASS if the prompt is `@<sender> ▸ <message>` and the sender is
  visibly editable/colored (manual: Tab-complete, Shift-Tab, nogo flash).
- **Bottom-anchored** — PASS if the reply hugs the input, stars fill the top.
- **Overall** — PASS if it feels like walking between characters' rooms, not
  scrolling one mixed log.
