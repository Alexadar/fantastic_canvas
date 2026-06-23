# 11 · Intro movie

Status: implemented

A small, scripted **19xx-game / demoscene cutscene** that teaches what Fantastic
*is* (everything is an agent · one verb `send` · `reflect` · compose · the brain).
Plays automatically after 10s idle on attract, or manually via `/intro` in chat.
Loops; any key exits to chat.

## Design

The movie is a `Vec<Box<dyn Scene>>` (`movie::storyboard`) — **add/reorder a scene
by editing one line**. Five scenes, played in order, looping:

```text
SCENE 1/5  SEND        [core] ─────●───▶ [web]      "ONE VERB: send(target,payload)"
SCENE 2/5  REFLECT     ┌ reflect → ───────┐         "AGENTS DESCRIBE THEMSELVES"
                       │ { id:"web",       │          capability emerges
                       │   verbs:[…] }     │  (typewriter)
SCENE 3/5  COMPOSE     [core]──[file]──[web]──[brain] "COMPOSE A LIVING SYSTEM"
                       (nodes pop in, wire up)
SCENE 4/5  BRAIN       [file]◀●  [web]◀●  ●▶[ui]      "THE BRAIN DRIVES THE SAME send"
                          ╲   [brain]   ╱   (packets pulse out)
SCENE 5/5  CREDITS     ◀ color-cycling marquee scroller ▶ + sine block baseline
```

**Per-scene chrome** (every frame): a dim `SCENE n/5` counter top-right, and a
blinking `▶ SHIFT-TAB ▶` exit hint centered on the bottom row (~1.5 Hz). Each
scene gets local progress `t∈[0,1]` + a global `clock` for continuous effects
(blink, 4-color CGA cycle, starfield drift). The whole area clears each frame
(no ghosts); all "randomness" is a seeded xorshift, so the cutscene is **identical
every run** (deterministic → testable).

Durations: Send 4.0s · Reflect 4.4s · Compose 5.0s · Brain 4.4s · Credits 6.0s
(≈23.8s total, `Movie::total_secs()` — the attract loop uses it to know one pass
finished).

> Note: the on-screen hint still says `SHIFT-TAB` and the credits say "press
> SHIFT-TAB" — a leftover from the old mode-switch era. Now **any** key exits the
> movie to chat. Design TODO: change the hint to `▶ PRESS ANY KEY ▶` for honesty.

## UX

1. **Idle 10s on attract** → *expect* the movie starts at SCENE 1/5. *feel:* an
   arcade cabinet rolling its demo reel.
2. **Watch** → *expect* scenes advance, the counter increments, effects animate
   smoothly, the exit hint blinks. *feel:* a tiny living explainer, not a slideshow.
3. **End of CREDITS** → *expect* loops back to SCENE 1 (from attract) or replays
   (from `/intro`). *feel:* continuous.
4. **Press any key** → *expect* cut to chat. *feel:* "ok, I get it — let me in."
5. **`/intro` typed in chat** → *expect* the same movie plays over the chat body;
   any key returns to chat. *feel:* a replay on demand.

## Drive

```script
# enter chat, then replay the movie manually and capture a few scenes
wait 2500
key space
wait 600
type /intro
key enter
stream 1500 6
```

## Judge

- **Scenes render** — PASS if frames show the box/packet/marquee motifs above and
  the `SCENE n/5` counter advances across the stream; FAIL if a scene is blank or
  the counter is stuck.
- **Determinism** — PASS if re-running yields the same frames (seeded noise).
- **Exit hint** — PASS if the bottom-row hint is present (blinking). (Flag if it
  still says SHIFT-TAB rather than "any key" — known TODO.)
- **Manual replay** — PASS if `/intro` plays it over chat and a key returns.
- **Overall** — PASS if it reads as a cool retro explainer a person enjoys watching.
