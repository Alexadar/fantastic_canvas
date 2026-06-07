cloud_bridge — cross-kernel comms through a **zero-trust relay** (CONTRACT v1).

Same verbs + wire frames as `kernel_bridge` (both ride the `bridge_core` engine),
but a different transport. Instead of dialling a remote `web_ws`, **both peers dial
OUT** (WSS) to a relay (`../fantastic_relay`) that authenticates each leg by a
control-plane token, **pairs** them by `(tenant_id, rendezvous)`, and forwards
**opaque** frames. The two peers then run a mutually-authenticated **TLS 1.3**
handshake over that opaque pipe (vetted stdlib `ssl` driven over a `MemoryBIO` — no
hand-rolled crypto, no socket) and tunnel the `call`/`reply`/`event` frames as TLS
application data. The relay sees only ciphertext + metadata, never content, and a
forged route simply fails the TLS handshake (impersonation impossible).

Identity is a self-signed **Ed25519** cert whose key IS the device `peer_id` —
so the relay token's `peer_id` and the E2E identity are the same key (no binding
gap). Peer-approval = **pinning**: each side trusts only the approved devices'
certs as TLS anchors (`approved_peer_certs`), so an un-approved peer can't complete
the handshake.

Verbs (identical to kernel_bridge): `boot` (dial + pair + TLS handshake), `forward`
(await reply), `watch_remote`/`unwatch_remote` (stream), `reconnect`, `reflect`.

Compose a leg with `transport=cloud_bridge` + `relay_url`, `tenant_id`, `peer_id`,
`rendezvous` (+ optional `partner_peer_id`), an `id_key` (b64url Ed25519 device
identity → its self-signed cert is the TLS identity), `approved_peer_certs` (the
PEM device list to pin), a token source (`token` | `token_provider` |
`dev_token=true`), and a role (`tls_role` / `initiator`, else derived from
`peer_id < partner_peer_id`). Both legs quote the same `rendezvous` with distinct
`peer_id`s. The relay holds no content and no long-lived secrets; E2E is the
client's job (this bundle) — see the relay's `CONTRACT.md`. Weak binding: the peer
is addressed by relay URL + identity only, no shared types.
