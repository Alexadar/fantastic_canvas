cloud_bridge — cross-kernel comms through a **zero-trust relay** (CONTRACT v1).

Same verbs + wire frames as `kernel_bridge` (both ride the `bridge_core` engine),
but a different transport. Instead of dialling a remote `web_ws`, **both peers dial
OUT** (WSS) to a relay (`../fantastic_relay`) that authenticates each leg by a
control-plane token, **pairs** them by `(tenant_id, rendezvous)`, and forwards
**opaque** frames. The two peers then run a mutually-authenticated **TLS 1.3**
handshake over that opaque pipe (vetted pyOpenSSL over a memory BIO — no
hand-rolled crypto, no socket) and tunnel the `call`/`reply`/`event` frames as TLS
application data. The relay sees only ciphertext + metadata, never content, and a
forged route simply fails the TLS handshake (impersonation impossible).

Identity is a self-signed **Ed25519** cert whose key IS the device `peer_id` —
so the relay token's `peer_id` and the E2E identity are the same key (no binding
gap). Peer-approval = **pinning the device's PUBLIC KEY**: a custom TLS verify
callback checks the peer's Ed25519 pubkey is in `approved_peer_certs`, so an
un-approved peer can't complete the handshake. The cert itself is a disposable
carrier of that key — it may rotate or be non-deterministic across runtimes (e.g.
Swift's CryptoKit randomizes Ed25519 signatures); only the key is the identity.
All three host runtimes (python/rust/swift) interop any-to-any over this transport
— exercised against a live relay by `integration_tests/relay_e2e`.

Verbs (identical to kernel_bridge): `boot` (dial + pair + TLS handshake), `forward`
(await reply), `watch_remote`/`unwatch_remote` (stream), `reconnect`, `reflect`.

**Authorization** (separate from the TLS auth above — this is a *dispatch policy*).
A leg is symmetric by default: once connected, either side can `call` any
agent/verb on the other. Two independent, TYPED rules govern a leg, **enforced on
the receiver** (a compromised peer can't bypass them):
  - **`ingress_rule`** — the inbound FILTER, consulted at ONE choke point (the
    inbound `call` dispatch) like an nginx allow/deny rule.
  - **`egress_rule`** — the outbound DECORATOR, consulted by `forward` to stamp this
    leg's credential on the frame ENVELOPE (never the dispatched payload, so the
    target never sees it).

Each rule is `{"type": <name>, "env": <var>}` (or a bare string type). A legacy
`auth` shorthand sets BOTH directions to the same rule. Rule types:
  - `allow_all` (default ingress — absent ⇒ this, full duplex) / `silent` (default
    egress — present nothing)
  - `deny_inbound` (ingress: refuse every inbound `call`, reply `{error,
    reason:"unauthorized"}`; the peer can't `call`/`reflect` back)
  - `password` — kernel-GROUP membership by a shared secret. **ingress** authorizes a
    `call` only if its envelope `auth_token` matches the group token (from `env`,
    default `FANTASTIC_GROUP_TOKEN`, so the secret never touches the portable
    `.fantastic` workdir); **egress** PRESENTS that token. `auth:"password"` ⇒ a full
    group member (checks + presents); split the directions for a hub
    (`ingress_rule:"deny_inbound"` + `egress_rule:{type:"password",env:"FLEET"}`).
    Fail-closed: an unset/empty token refuses every inbound `call`. Confidential here
    (rides the peer↔peer TLS — the relay sees only ciphertext). Constant-time
    compare. The bridge-authz analog of the relay's `password` provider.

Each rule is resolved BY NAME from a registry — the `ingress_rules` / `egress_rules`
packages (one module per rule, the package `__init__` is the importer). Add a rule =
drop a module + register its name; the choke point never changes. A *stack* of rules
is itself a future composite rule, not an engine change. Inbound `watch`/`unwatch`
are already ignored ⇒ denied-by-omission. Engine defaults are permissive
(back-compat) by design — **securing a leg is the control plane's job**: it sets the
rules. Rules are TRANSITIONAL (inline plumbing), not invocational (agents).

Compose a leg with `transport=cloud_bridge` + `relay_url`, `tenant_id`, `peer_id`,
`rendezvous` (+ optional `partner_peer_id`), an `id_key` (b64url Ed25519 device
identity → its self-signed cert is the TLS identity), `approved_peer_certs` (the
PEM device list to pin), a token source (`token` | `token_provider` | `issue_url`
+ `password`/`provider` POSTed to the relay's `/issue` | `dev_token=true`), and a
role (`tls_role` / `initiator`, else derived from
`peer_id < partner_peer_id`), and optional `ingress_rule` / `egress_rule` (or the
`auth` shorthand for both). Both legs quote the same
`rendezvous` with distinct `peer_id`s. The relay holds no content and no long-lived secrets; E2E is the
client's job (this bundle) — see the relay's `CONTRACT.md`. Weak binding: the peer
is addressed by relay URL + identity only, no shared types.
