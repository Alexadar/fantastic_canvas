"""WebSocket proxy — translates browser frames to/from kernel.send.

Two on-the-wire formats, picked automatically by payload content:

  TEXT FRAMES (JSON, default):
    C->S {type:"call",   target, payload, id}     -> kernel.send -> reply
    C->S {type:"emit",   target, payload}         -> kernel.emit (no reply)
    C->S {type:"watch",  src}                     -> mirror src's inbox into ours
    C->S {type:"unwatch", src}
    S->C {type:"reply",  id, data}                -> reply for a prior call
    S->C {type:"error",  id, error}               -> reply error
    S->C {type:"event",  payload}                 -> any event mirrored from kernel inbox

  BINARY FRAMES (when payload contains a `bytes` value anywhere):
    [4-byte BE uint32 H | H-byte JSON envelope | M-byte raw blob]
    Envelope JSON has the bytes value replaced by null and an extra
    field `_binary_path: "<dotted.path.to.bytes.field>"`. Receiver
    parses header, reads remaining bytes as the binary body, sets the
    body at `_binary_path` in the envelope, then handles it as a
    regular text-frame envelope.

The binary path eliminates base64 + JSON encoding for byte-heavy
payloads (audio, image, etc.). It's transparent to bundle handlers —
they receive `bytes` regardless of which wire format was used.
"""

from __future__ import annotations

import asyncio
import copy

from starlette.websockets import WebSocketState
import json
import logging
import secrets
import struct
from typing import Any

logger = logging.getLogger(__name__)


def _make_client_id() -> str:
    return f"_ws_{secrets.token_hex(3)}"


# ─── binary frame helpers ───────────────────────────────────────


def _find_bytes_path(obj: Any, prefix: str = "") -> tuple[str, bytes] | None:
    """Walk obj; return (dotted_path, value) of first bytes value, or None."""
    if isinstance(obj, bytes):
        return (prefix, obj)
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            r = _find_bytes_path(v, p)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            p = f"{prefix}.{i}" if prefix else str(i)
            r = _find_bytes_path(v, p)
            if r is not None:
                return r
    return None


def _set_path(obj: Any, path: str, value: Any) -> None:
    parts = path.split(".")
    for p in parts[:-1]:
        obj = obj[int(p)] if isinstance(obj, list) else obj[p]
    last = parts[-1]
    if isinstance(obj, list):
        obj[int(last)] = value
    else:
        obj[last] = value


def encode_outbound(envelope: dict) -> tuple[bytes, bool]:
    """Serialize an envelope for the wire.

    Returns (frame_data, is_binary). If any bytes value is found, returns
    a binary frame `[4-byte BE length | header JSON | body bytes]`.
    Otherwise returns UTF-8-encoded JSON text.
    """
    found = _find_bytes_path(envelope)
    if found is None:
        return json.dumps(envelope, default=str).encode("utf-8"), False
    path, body = found
    head_obj = copy.deepcopy(envelope)
    _set_path(head_obj, path, None)
    head_obj["_binary_path"] = path
    head_bytes = json.dumps(head_obj, default=str).encode("utf-8")
    return struct.pack(">I", len(head_bytes)) + head_bytes + body, True


def decode_inbound(data: bytes | str) -> dict:
    """Parse a wire frame back into an envelope dict.

    Text frames: JSON-decoded. Binary frames: reconstructed envelope
    with bytes body restored at `_binary_path`.
    """
    if isinstance(data, str):
        return json.loads(data)
    # Binary frame
    head_len = struct.unpack(">I", data[:4])[0]
    head = json.loads(data[4 : 4 + head_len].decode("utf-8"))
    body = data[4 + head_len :]
    path = head.pop("_binary_path", None)
    if path is not None:
        _set_path(head, path, body)
    return head


# ─── proxy loop ─────────────────────────────────────────────────


async def run(ws, kernel, host_agent_id: str) -> None:
    """Drive one WebSocket connection."""
    client_id = _make_client_id()
    kernel._ensure_inbox(client_id)
    kernel.watch(host_agent_id, client_id)
    watching = {host_agent_id}

    async def drain_outbound() -> None:
        q = kernel._ensure_inbox(client_id)
        while True:
            payload = await q.get()
            if ws.application_state != WebSocketState.CONNECTED:
                return
            frame, is_bin = encode_outbound({"type": "event", "payload": payload})
            try:
                if is_bin:
                    await ws.send_bytes(frame)
                else:
                    await ws.send_text(frame.decode("utf-8"))
            except RuntimeError as e:
                # Same close race as _send_envelope: WS may close
                # between the state check and the send. Narrow catch.
                if "close message has been sent" not in str(e):
                    raise
                return

    drain_task = asyncio.create_task(drain_outbound())

    async def _send_envelope(envelope: dict) -> None:
        # Browser tab can close mid-call: an ollama `send` holds the WS
        # for tens of seconds while tokens stream; refreshing in that
        # window is normal. Two-step guard:
        #   1) check ws.application_state up front and skip if not
        #      CONNECTED — common case, no exception involved
        #   2) the close can still race in between the check and the
        #      actual send; narrow that to the ONE specific RuntimeError
        #      starlette raises ("Cannot call ... once a close message
        #      has been sent"). Any other RuntimeError is a real bug
        #      and propagates.
        if ws.application_state != WebSocketState.CONNECTED:
            return
        frame, is_bin = encode_outbound(envelope)
        try:
            if is_bin:
                await ws.send_bytes(frame)
            else:
                await ws.send_text(frame.decode("utf-8"))
        except RuntimeError as e:
            if "close message has been sent" not in str(e):
                raise

    # ─── inbound frame handlers ─────────────────────────────────
    async def _on_call(frame):
        target = frame.get("target", "")
        payload = frame.get("payload", {})
        fid = frame.get("id", "")
        try:
            reply = await kernel.send(target, payload)
            await _send_envelope({"type": "reply", "id": fid, "data": reply})
        except Exception as e:
            await _send_envelope({"type": "error", "id": fid, "error": str(e)})

    async def _on_emit(frame):
        await kernel.emit(frame.get("target", ""), frame.get("payload", {}))

    async def _on_watch(frame):
        src = frame.get("src", "")
        if src and src not in watching:
            kernel.watch(src, client_id)
            watching.add(src)

    async def _on_unwatch(frame):
        src = frame.get("src", "")
        if src in watching:
            kernel.unwatch(src, client_id)
            watching.discard(src)

    # `call` handlers may await for tens of seconds (LLM streams).
    # Awaiting them inline blocks the receive loop, so a peer-close
    # only registers AFTER the generation completes — backend keeps
    # burning resources on a now-orphaned conversation. Dispatch
    # `call` as a task and track pending; cancel on disconnect so
    # `kernel.send` (and downstream e.g. ollama_backend._run) sees
    # CancelledError and releases the lock immediately. The other
    # frame types (emit/watch/unwatch) are local state mutations —
    # cheap, awaited inline.
    pending: set[asyncio.Task] = set()

    FRAME_HANDLERS_INLINE = {
        "emit": _on_emit,
        "watch": _on_watch,
        "unwatch": _on_unwatch,
    }

    try:
        while True:
            try:
                msg = await ws.receive()
            except Exception:
                break
            # FastAPI/Starlette WebSocket.receive returns a dict with
            # 'type', 'text' or 'bytes'. Normalize.
            if msg.get("type") == "websocket.disconnect":
                break
            raw = msg.get("text")
            if raw is None:
                raw = msg.get("bytes")
            if raw is None:
                continue
            frame = decode_inbound(raw)
            ftype = frame.get("type")
            if ftype == "call":
                t = asyncio.create_task(_on_call(frame))
                pending.add(t)
                t.add_done_callback(pending.discard)
            else:
                inline = FRAME_HANDLERS_INLINE.get(ftype)
                if inline is not None:
                    await inline(frame)
            # Unknown frame types are silently dropped (forward-compat).
    finally:
        drain_task.cancel()
        # Cancel any in-flight `call` handlers so the underlying
        # kernel.send tasks unwind (ollama_backend honors
        # CancelledError, releases its FIFO lock, emits done).
        for t in list(pending):
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for src in watching:
            kernel.unwatch(src, client_id)
        kernel._inboxes.pop(client_id, None)
