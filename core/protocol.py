"""Wire protocol for agent ↔ web bridge over WebSocket.

Language-agnostic. This module is the canonical reference.
Web bundles in any language/runtime can implement this protocol.

─── Connection ─────────────────────────────────────────────────

  Each agent has its own URL and its own WS channel:
    HTTP GET  {base}/{agent_id}/           → agent's HTML UI (with transport.js injected)
    HTTP GET  {base}/{agent_id}/<asset>    → static file from that agent's bundle web/dist/
    WS        {base}/{agent_id}/ws         → protocol channel bound to agent's bus inbox

─── Message shapes (JSON, single-line) ─────────────────────────

  Client → Server:

    `call` — invoke a dispatch tool, await reply
      { "type": "call", "tool": "<name>", "args": {...}, "id": "<uuid>" }

    `emit` — fire-and-forget event into the agent's bus inbox
      { "type": "emit", "event": "<name>", "data": {...} }

  Server → Client:

    `reply` — successful response to a `call`
      { "type": "reply", "id": "<uuid>", "data": {...} }

    `error` — failure response to a `call`
      { "type": "error", "id": "<uuid>", "error": "<msg>" }

    `event` — unsolicited push (from bus, dispatch broadcasts, scheduler, etc.)
      { "type": "event", "event": "<name>", "data": {...} }

─── Semantics ──────────────────────────────────────────────────

- Each WS connection is scoped to ONE agent_id (parsed from URL path).
- UI agents NEVER know about WS. They only use the injected `fantastic_transport()`
  global (see bundled_agents/_web_shared/transport.ts).
- Dispatch tool names are registered in _DISPATCH. Anything in _DISPATCH is callable.
- Events are free-form strings; bundles define their own vocabulary.
- Event mirroring (transport.watch / unwatch): one agent can ask the bus to forward
  a copy of another agent's events into its own inbox. Implemented via internal
  dispatches `_bus_watch` and `_bus_unwatch`.
- Static assets are served as plain HTTP GET, NOT through the protocol.

─── Why not REST ───────────────────────────────────────────────

The protocol is WS-only because the system is fundamentally event-driven.
Agents emit; agents listen. A request/reply RPC layer (the `call/reply` pair)
sits on top for synchronous-feeling invocations, but the substrate is events.

No REST endpoints. No HTTP polling.
"""

PROTOCOL_VERSION = "1.0"

# Client → Server message types
MSG_CALL = "call"
MSG_EMIT = "emit"

# Server → Client message types
MSG_REPLY = "reply"
MSG_ERROR = "error"
MSG_EVENT = "event"

# Internal dispatch names (not user-facing tools)
BUS_WATCH = "_bus_watch"
BUS_UNWATCH = "_bus_unwatch"


def describe() -> dict:
    """Return machine-readable protocol spec (same as frontend's transport.description())."""
    return {
        "version": PROTOCOL_VERSION,
        "capabilities": ["dispatch", "events", "bidirectional", "watch"],
        "message_shapes": {
            "call": {
                "type": "call",
                "tool": "<dispatch tool name>",
                "args": "<object>",
                "id": "<uuid string>",
            },
            "emit": {
                "type": "emit",
                "event": "<event name>",
                "data": "<object>",
            },
            "reply": {
                "type": "reply",
                "id": "<uuid string, matches call.id>",
                "data": "<object>",
            },
            "error": {
                "type": "error",
                "id": "<uuid string, matches call.id>",
                "error": "<message>",
            },
            "event": {
                "type": "event",
                "event": "<event name>",
                "data": "<object>",
            },
        },
    }
