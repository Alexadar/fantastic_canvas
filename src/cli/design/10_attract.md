# Attract screen

Status: implemented

The first thing you see: a 19xx-arcade **attract mode**. Dark sky, drifting white
stars, the word `FANTASTIC` in a crisp block font, and a blinking invite. Idle 10s
→ the intro movie plays, then loops back here. Any key → the chat surface.

## Design

```text
┌ 110×30, no chrome — full-bleed ───────────────────────────────────────────────┐
│   .        ·    *          ·            *        .            ·      *          │  ← starfield:
│ ·    *           .              ·                      *           .            │    white stars,
│        ·              *                    .              ·                *    │    dark (black) sky,
│                                                                                │    slow twinkle/drift
│            ████  ██  █  █ █████  ██  ████ █████ ███ ████                        │
│            █    █  █ ██ █   █   █  █ █      █    █  █                            │  ← FANTASTIC, block
│            ███  ████ █ ██   █   ████ ████   █    █  █                           │    font, magenta→violet
│            █    █  █ █  █   █   █  █    █   █    █  █                            │    gradient, centered
│            █    █  █ █  █   █   █  █ ████   █   ███ ████                         │
│        ·          *              .          ·             *          .         │
│                          P R E S S   A N Y   K E Y   T O   C O N T I N U E             │  ← blinks ~1 Hz,
│   *           .            ·               *          .            ·        *   │    dim, centered below
│        ·            *               .             ·            *          .     │
└────────────────────────────────────────────────────────────────────────────────┘
```

**Layout** — full-bleed, no margins (the chat surface adds margins; attract does
not). The title block is vertically centered; the blink sits one blank row below
it. Everything else is starfield.

**Theme (dark, always)** — sky is opaque black (`fill_black` fills the whole
buffer first; stars then draw `fg=White/dim, bg=Black`). There is no light theme.
Title gradient is a bright pink→magenta→violet ramp (`bg::gradient`), tuned to
read like the Claude-CLI accent — luminous, not muddy.

**The title is hand-built, not FIGlet.** `bg.rs` carries 5-row block glyphs,
integer-scaled to fit ≤92% width (capped ~30% of `min(w,h)`), and rendered with
**half-block** characters (`▀▄█`, two glyph rows per terminal row) so it's ~1.5–2×
shorter — terminal cells are ~2:1, so packing two rows per cell corrects the
otherwise vertically-stretched look (FANTASTIC renders in ~3 rows, not 5). This is
deliberate: a wide FIGlet banner downscaled to a small terminal turns to mush and
becomes illegible — the block font stays crisp at its native cell grid. Legibility
(you can read F-A-N-T-A-S-T-I-C) is the hard requirement.

## UX

1. **Launch (tty)** → *expect* the attract screen paints immediately (stars +
   title reveal top→bottom). *feel:* a game booting, not a CLI starting.
2. **Wait, doing nothing** → *expect* the "press any key" line blinks; after ~10s
   idle the intro movie starts; at its end you're back on attract. *feel:* a loop
   that's alive, never a frozen splash.
3. **Press any key** → *expect* instant cut to the chat surface (stars + a faint
   `FANTASTIC` persist in the background). *feel:* you *entered* the game; the
   world didn't disappear, it receded.

## Drive

```script
# boot → let the reveal animate → settle, capturing the stream
wait 200
stream 250 8
shot settled
```

## Judge

- **Legible title** — PASS if the `█` rows spell `FANTASTIC` and you can read each
  letter; FAIL if glyphs collide into mush or overflow the width.
- **Dark sky** — PASS if the field reads as scattered stars on an empty (black)
  ground, not a busy/inverted field. (Confirm `fill_black` + star `bg=Black` in
  code; the text dump can't show color.)
- **Centering & size** — PASS if the title is roughly centered and occupies
  ~⅓ of the smaller screen dimension (not tiny, not edge-to-edge).
- **Reveal motion** — across the `stream` frames, PASS if the title appears
  progressively (top rows before bottom), not all-at-once.
- **Overall** — PASS if it reads as an arcade attract screen a person would want
  to press a key on.
