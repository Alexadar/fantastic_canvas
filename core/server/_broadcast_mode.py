"""Broadcast mode — readonly streaming to viewers."""

import json
import logging
import secrets as _secrets

from fastapi import WebSocket, WebSocketDisconnect

from . import _state

logger = logging.getLogger(__name__)

# Broadcast mode state
broadcast_viewers: set[WebSocket] = set()
broadcast_enabled: bool = False
broadcast_token: str = ""


async def broadcast_viewer_ws(ws: WebSocket, token: str = ""):
    """Readonly WebSocket for broadcast viewers."""
    global broadcast_enabled, broadcast_token
    if not broadcast_enabled or token != broadcast_token:
        await ws.close(code=4001, reason="Broadcast not active or invalid token")
        return
    await ws.accept()
    broadcast_viewers.add(ws)
    logger.info(f"Broadcast viewer connected ({len(broadcast_viewers)} viewers)")
    state = _state.engine.get_state()
    await ws.send_text(json.dumps({"type": "state", "state": state}, default=str))
    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            if msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        broadcast_viewers.discard(ws)
        logger.info(f"Broadcast viewer disconnected ({len(broadcast_viewers)} viewers)")


async def start_broadcast():
    """Start broadcast mode. Returns token for viewers to connect."""
    global broadcast_enabled, broadcast_token
    broadcast_token = _secrets.token_urlsafe(16)
    broadcast_enabled = True
    return {"token": broadcast_token, "url": f"/ws/broadcast?token={broadcast_token}"}


async def stop_broadcast():
    """Stop broadcast mode and disconnect all viewers."""
    global broadcast_enabled
    broadcast_enabled = False
    for ws in list(broadcast_viewers):
        try:
            await ws.close(code=1000, reason="Broadcast ended")
        except Exception:
            pass
    broadcast_viewers.clear()
    return {"ok": True}


async def broadcast_status():
    """Check broadcast mode status."""
    return {"enabled": broadcast_enabled, "viewers": len(broadcast_viewers)}
