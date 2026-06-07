"""cloud_bridge transport — dial-OUT relay leg with end-to-end TLS 1.3 mTLS.

`CloudBridgeTransport` is a `bridge_core._BaseTransport`: it dials OUT (WSS) to the
relay, authenticates the WS with a subprotocol token, is paired by
`(tenant_id, rendezvous)`, then runs a **mutually-authenticated TLS 1.3 handshake
over the relay's opaque byte pipe** (stdlib `ssl` + `MemoryBIO`, no socket — see
`_tls.py`). After the handshake it tunnels the SAME kernel-bridge `call/reply/event`
frames as **TLS application data**, length-delimited, shipped as opaque binary WS
frames. The relay forwards ciphertext + sees nothing; a forged route fails the TLS
handshake (the impostor can't present a pinned cert).
"""

from __future__ import annotations

import asyncio
import json
import ssl
import struct
from typing import Any

from bridge_core._transport import ConnectionClosed, _BaseTransport

SUBPROTOCOL = "fantastic.relay.v1"
KEEPALIVE_TYPE = "keepalive"
HANDSHAKE_TIMEOUT = 15.0  # < the relay's 30s pair timeout
MAX_FRAME = 16 * 1024 * 1024  # reassembly cap (matches the relay's 16 MiB)
_LEN = struct.Struct(">I")  # 4-byte big-endian length prefix per frame
_READ = 65536


async def _drive(ws: Any, sslobj: ssl.SSLObject, incoming, outgoing, fn):
    """Run a TLS op (`do_handshake` / `write`) to completion over the WS pipe:
    flush outbound records the op produces, feed inbound records it needs."""
    while True:
        try:
            ret = fn()
        except ssl.SSLWantReadError:
            data = outgoing.read()
            if data:
                await ws.send(data)
            raw = await ws.recv()
            incoming.write(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
            continue
        except ssl.SSLWantWriteError:
            data = outgoing.read()
            if data:
                await ws.send(data)
            continue
        else:
            data = outgoing.read()
            if data:
                await ws.send(data)
            return ret


class CloudBridgeTransport(_BaseTransport):
    def __init__(
        self, ws, sslobj, incoming, outgoing, peer_identity: dict, heartbeat: float
    ) -> None:
        self._ws = ws
        self._ssl = sslobj
        self._in = incoming
        self._out = outgoing
        self.peer_identity = peer_identity  # {"pubkey": bytes}
        self._send_lock = asyncio.Lock()
        self._rbuf = bytearray()
        self._closed = False
        self._hb_interval = heartbeat
        self._hb_task: asyncio.Task | None = (
            asyncio.create_task(self._heartbeat())
            if heartbeat and heartbeat > 0
            else None
        )

    @classmethod
    async def connect(
        cls,
        relay_url: str,
        token: str,
        *,
        server: bool,
        cert_pem: bytes,
        key_pem: bytes,
        approved_certs_pem: list[bytes],
        expected_partner_pubkey: bytes | None = None,
        heartbeat: float = 30.0,
    ) -> "CloudBridgeTransport":
        import websockets

        from cloud_bridge._tls import make_context, peer_pubkey_from_der

        ws = await websockets.connect(
            relay_url, subprotocols=[SUBPROTOCOL, token], max_size=2**24
        )
        try:
            ctx = make_context(
                server=server,
                cert_pem=cert_pem,
                key_pem=key_pem,
                approved_certs_pem=approved_certs_pem,
            )
            incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
            sslobj = ctx.wrap_bio(incoming, outgoing, server_side=server)
            # Bounded handshake — a paired-but-silent peer must not hang boot forever.
            await asyncio.wait_for(
                _drive(ws, sslobj, incoming, outgoing, sslobj.do_handshake),
                HANDSHAKE_TIMEOUT,
            )
            der = sslobj.getpeercert(binary_form=True)
            peer_pub = peer_pubkey_from_der(der) if der else None
            if expected_partner_pubkey and peer_pub != expected_partner_pubkey:
                raise ConnectionClosed("cloud_bridge: peer cert != expected partner")
            return cls(ws, sslobj, incoming, outgoing, {"pubkey": peer_pub}, heartbeat)
        except Exception:
            try:
                await ws.close()
            except Exception:
                pass
            raise

    @property
    def closed(self) -> bool:
        return self._closed or getattr(self._ws, "closed", False)

    async def _heartbeat(self) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(self._hb_interval)
                if self._closed:
                    return
                try:
                    await self.send({"type": KEEPALIVE_TYPE})
                except ConnectionClosed:
                    return
        except asyncio.CancelledError:
            pass

    async def send(self, frame: dict) -> None:
        data = json.dumps(frame, default=str).encode("utf-8")
        payload = _LEN.pack(len(data)) + data  # length-delimited inside the TLS stream
        async with self._send_lock:
            try:
                await _drive(
                    self._ws,
                    self._ssl,
                    self._in,
                    self._out,
                    lambda: self._ssl.write(payload),
                )
            except Exception as e:
                raise ConnectionClosed(str(e)) from e

    async def _fill(self) -> None:
        """Pull one batch of decrypted bytes into `_rbuf`, feeding inbound WS
        records into the TLS engine as needed."""
        import websockets

        while True:
            try:
                chunk = self._ssl.read(_READ)
            except ssl.SSLWantReadError:
                try:
                    raw = await self._ws.recv()
                except websockets.ConnectionClosed as e:
                    raise ConnectionClosed(str(e)) from e
                self._in.write(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
                continue
            except ssl.SSLError as e:
                raise ConnectionClosed(f"cloud_bridge TLS error: {e}") from e
            if chunk == b"":
                raise ConnectionClosed("cloud_bridge: peer closed TLS")
            self._rbuf += chunk
            if len(self._rbuf) > MAX_FRAME + 4:
                raise ConnectionClosed("cloud_bridge: frame exceeds cap")
            return

    async def _recv_frame(self) -> dict:
        while True:
            if len(self._rbuf) >= 4:
                (n,) = _LEN.unpack_from(self._rbuf, 0)
                if n > MAX_FRAME:
                    raise ConnectionClosed("cloud_bridge: frame exceeds cap")
                if len(self._rbuf) >= 4 + n:
                    data = bytes(self._rbuf[4 : 4 + n])
                    del self._rbuf[: 4 + n]
                    return json.loads(data)
            await self._fill()

    async def recv(self) -> dict:
        while True:
            frame = await self._recv_frame()
            if frame.get("type") == KEEPALIVE_TYPE:
                continue  # heartbeat — never surface to the bridge read loop
            return frame

    async def close(self) -> None:
        self._closed = True
        if self._hb_task is not None and not self._hb_task.done():
            self._hb_task.cancel()
        try:
            await self._ws.close()
        except Exception:
            pass
