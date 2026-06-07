"""End-to-end TLS 1.3 mutual auth for cloud_bridge (E2E decision 2026-06-07).

Replaces the prior hand-rolled Noise layer. TLS does the WHOLE security-critical
handshake — mutual authentication, forward secrecy, transcript integrity,
downgrade protection — via a vetted stack (Python stdlib `ssl`, here driven over
the relay's opaque byte pipe with `MemoryBIO`, no socket). We write NO crypto.

Identity = a self-signed **Ed25519** cert (RFC 8410/8422) whose key IS the device
`peer_id` identity — so the relay token's `peer_id` and the TLS cert are the same
key (no separate static, no key-binding gap). Peer-approval = **pinning**: each
side trusts ONLY the approved peers' certs as TLS anchors (`load_verify_locations`),
so an un-approved or relay-forged peer simply fails the handshake. The cert is
DETERMINISTIC from the key (fixed serial/validity + Ed25519's deterministic
signature), so a peer's cert is stable across reboots and safe to pin by value.
"""

from __future__ import annotations

import ssl
from datetime import datetime, timezone

# Fixed validity so the cert is deterministic from the key (stable to pin).
_NOT_BEFORE = datetime(2020, 1, 1, tzinfo=timezone.utc)
_NOT_AFTER = datetime(2050, 1, 1, tzinfo=timezone.utc)


def self_signed_cert(ed25519_priv: bytes) -> tuple[bytes, bytes]:
    """Deterministic self-signed Ed25519 cert (PEM) + PKCS8 key (PEM) for a device
    identity key. Same key → same cert bytes (pinning is stable across reboots)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.x509.oid import NameOID

    from cloud_bridge._token import b64url

    key = Ed25519PrivateKey.from_private_bytes(ed25519_priv)
    cn = b64url(key.public_key().public_bytes_raw())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(_NOT_BEFORE)
        .not_valid_after(_NOT_AFTER)
        # CA:TRUE so the self-signed leaf can act as its own trust anchor when pinned.
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, None)  # Ed25519 signs with algorithm=None
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return cert_pem, key_pem


def cert_pem_for(ed25519_priv: bytes) -> bytes:
    """Just the cert PEM (e.g. to publish into an account device list)."""
    return self_signed_cert(ed25519_priv)[0]


def peer_pubkey_from_der(der: bytes) -> bytes:
    """The raw Ed25519 public key of a peer's DER cert (its durable `peer_id`)."""
    from cryptography import x509

    return x509.load_der_x509_certificate(der).public_key().public_bytes_raw()


def make_context(
    *,
    server: bool,
    cert_pem: bytes,
    key_pem: bytes,
    approved_certs_pem: list[bytes],
) -> ssl.SSLContext:
    """A TLS 1.3-only, mutually-authenticated context that pins the peer to the
    approved device certs. Raises if no approved certs are given (fail closed)."""
    import os
    import tempfile

    if not approved_certs_pem:
        raise ValueError(
            "cloud_bridge TLS: no approved_peer_certs to pin (fail closed)"
        )

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    if server:
        # No post-handshake session tickets — keeps the steady state strictly
        # one-directional per side (read never has to produce outbound records).
        ctx.num_tickets = 0

    # load_cert_chain needs a path; one temp file carrying cert + key.
    tf = tempfile.NamedTemporaryFile("wb", suffix=".pem", delete=False)
    try:
        tf.write(cert_pem + b"\n" + key_pem)
        tf.flush()
        tf.close()
        ctx.load_cert_chain(tf.name)
    finally:
        os.unlink(tf.name)

    # Pin: trust ONLY the approved device certs as anchors.
    ctx.load_verify_locations(cadata=b"\n".join(approved_certs_pem).decode("ascii"))
    return ctx
