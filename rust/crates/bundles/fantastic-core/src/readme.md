# This is a Fantastic kernel.

A tree of agents. One primitive: `send(target_id, payload) -> reply`.
Every agent answers `{"type":"reflect"}` — identity, verbs, state.

## One-call bootstrap

`reflect readme=true` — your first move: the addressed agent's identity
plus this readme, in one call. Read-only and lock-free. The default
target is the tree root (alias `kernel`), so `reflect readme=true` alone
hands you the whole substrate description (this file) next to the live
tree. Start there.

## The reflect surface

`reflect` is the one discovery verb. It returns the ADDRESSED agent
uniformly — `{id, sentence, display_name, description?, verbs?, ...state}`
— the root is NOT special. Compose what you get back with three flags:

- `tree=all|ids|none` (default `all`)
  - `all`  — the agent's whole subtree, nested + distilled
             (`{id, parent_id, handler_module, display_name, description?, children}`).
  - `ids`  — a flat list of descendant ids. Cheap. Use it to scan.
  - `none` — just the agent, no subtree.
- `bundles=all|ids|none` (default `none`)
  - `all`  — every installable bundle as `{name, handler_module}`.
  - `ids`  — just the bundle names.
  - `none` — omit (the usual case).
- `readme=true|false` (default `false`)
  - `true` — attach the addressed agent's `readme.md` (string or null),
             one agent at a time.

## Context hygiene

Reading reflect output is cheap; readmes are not. To explore without
flooding your context: SCAN with `reflect tree=ids bundles=ids` (ids
only), then DRILL into ONE id at a time with `reflect tree=all` or
`reflect readme=true`. Never pull every agent's readme at once — fetch
the single readme for the agent you are about to act on.

## The `description` field

Any agent may carry a short `description` — a one-line "what this agent
is for", set at create or update:
    create_agent handler_module=<bundle>.tools description="..."
    update_agent id=<agent> description="..."
It surfaces in every reflect (top-level and in each tree node), so a
single `reflect tree=all` tells you what every agent in the tree does at
a glance — no per-agent readme needed just for the overview.

## Transports — every way to talk to this kernel

The envelope is always `{"type":"<verb>", ...fields}`. `reflect` is
universal; per-verb signatures come from each agent's reflect `verbs`.

- in_process  — `send(target_id, payload)` from code inside the kernel.
- in_prompt   — LLM tool-call loops emit
                `<send id="<agent_id>" payload='{"type":"<verb>", ...}'/>`.
- cli         — `fantastic <agent_id> <verb> [k=v ...]`; shorthand
                `fantastic reflect [<agent_id>]`. One-shot; refused while
                a daemon owns the dir (use the web surface then).
- ws          — `ws://host:port/<agent_id>/ws`; frames
                `{"type":"call","target":..,"payload":..,"id":..}`.
- rest        — `POST http://host:port/<rest_id>/<target_id>` body=payload;
                browser-pastable `GET .../<rest_id>/_reflect[/<target>][?readme=1]`.
- binary      — for byte-heavy payloads, a WS binary frame
                `[4-byte BE uint32 H | H-byte JSON header | M-byte body]`;
                `_binary_path` names the body field. Skips base64.
- browser-bus — in a browser, `BroadcastChannel("fantastic")` carries
                `{type, target_id, source_id, ...}` between iframes,
                bypassing the kernel entirely (`fantastic_transport().bus`).

`kernel` is an alias for the tree root: send any verb to `kernel` and it
resolves to the root agent — handy for reflecting the whole tree without
knowing the root's id.

## Reach this kernel

Check `.fantastic/lock.json` first — it holds `{pid}`. One kernel per
dir, so the two paths are mutually exclusive:

**A daemon IS running** (lock.json has a live pid). The one-shot CLI is
locked out — go through the daemon's surface. Find it in the tree: a
`web.tools` node carries the HTTP `port`; its children are the surfaces.
  - `web_rest.tools` child → `POST http://localhost:<port>/<rest_id>/<target>`
    body=`{"type":"<verb>",...}`; or browser-pastable
    `GET http://localhost:<port>/<rest_id>/_reflect[/<target>][?readme=1]`
  - `web_ws.tools` child → `ws://localhost:<port>/<agent>/ws`
    (frames: `{"type":"call","target":..,"payload":..,"id":..}`)
  To get the tree itself: `GET http://localhost:<port>/<rest_id>/_reflect`.

**No daemon running** (no live pid). The one-shot CLI works — each call
spawns a fresh kernel, reads disk, dispatches, exits:
  - `fantastic reflect` — the agent tree (add `bundles=all` for the catalog)
  - `fantastic <id> <verb> [k=v ...]` — call any verb on any agent
  (one-shots don't see live process-memory state — they're disk-only.)

**A daemon is running but there's no `web.tools` node** → no HTTP surface
and one-shots are locked out. Tell the user to add one (don't guess a
port yourself):
    fantastic core create_agent handler_module=web.tools port=<N>
    fantastic <web_id> create_agent handler_module=web_ws.tools
    fantastic <web_id> create_agent handler_module=web_rest.tools
...then they restart the daemon.

## Mental model

Agents are recursive — an agent can own children. `create_agent
handler_module=<bundle>.tools` spawns one (as a child of whatever you
call it on); `delete_agent` cascades depth-first.

A `canvas_webapp` is a spatial UI; its `canvas_backend` child holds
members — `add_agent handler_module=X` spawns a member, `list_members`
lists them, `remove_agent` cascades one out. To drive a project's
canvas: reflect the canvas_backend with `readme=true`, then
add/inspect/remove members.

## If you are a terminal inside a canvas

You may be `claude` running in a `terminal_backend` PTY that is a member
of some canvas. To find the canvas you live on: reflect yourself, then
walk `parent_id` up the tree —
`terminal_backend → terminal_webapp → canvas_backend → canvas_webapp`.
Once you have the `canvas_backend` id, you can `add_agent` siblings next
to yourself, `list_members`, or reshape the canvas you're in. (If your
own agent id isn't obvious, `reflect tree=ids` shows every id — find the
`terminal_backend` node whose PTY is yours.)

To learn ANY agent: reflect it with `readme=true`.
