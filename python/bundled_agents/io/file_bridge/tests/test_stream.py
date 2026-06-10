"""file_bridge — the SOURCE/SINK stream protocol (stateless cursor)."""

from __future__ import annotations

import base64


async def _open(kernel, **meta):
    r = await kernel.send(
        "kernel_state",
        {
            "type": "create_agent",
            "handler_module": "file_bridge.tools",
            "ingress_rule": "allow_all",
            **meta,
        },
    )
    return r["id"]


async def test_write_stream_then_read_stream_round_trips(
    seeded_kernel, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    fid = await _open(seeded_kernel, root="sd")
    blob = bytes(range(256)) * 40  # 10240 bytes, binary
    # push in 3 chunks (truncate on first, append after)
    off = 0
    for i, start in enumerate(range(0, len(blob), 4096)):
        chunk = blob[start : start + 4096]
        r = await seeded_kernel.send(
            fid,
            {
                "type": "write_stream",
                "path": "x.bin",
                "b64": base64.b64encode(chunk).decode("ascii"),
                "truncate": i == 0,
            },
        )
        assert r["written"] == len(chunk)
        off = r["size"]
    assert off == len(blob)
    # pull it back with the cursor until eof
    got = b""
    offset = 0
    while True:
        r = await seeded_kernel.send(
            fid,
            {"type": "read_stream", "path": "x.bin", "offset": offset, "length": 3000},
        )
        got += base64.b64decode(r["b64"])
        offset = r["next_offset"]
        if r["eof"]:
            break
    assert got == blob
    assert r["size"] == len(blob)


async def test_stream_verbs_sealed_by_default(seeded_kernel, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # NO ingress_rule → sealed; read_stream must be denied + taught
    r = await seeded_kernel.send(
        "kernel_state",
        {"type": "create_agent", "handler_module": "file_bridge.tools", "root": "s"},
    )
    fid = r["id"]
    d = await seeded_kernel.send(fid, {"type": "read_stream", "path": "x"})
    assert d["reason"] == "unauthorized" and "ingress_rule" in d.get("hint", "")
