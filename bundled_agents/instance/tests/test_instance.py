"""Tests for `instance` bundle — instance agent lifecycle + verb handlers.

SSH spawn is mocked at the `asyncio.create_subprocess_shell` boundary.
WS probe is mocked at `_ws_open_probe`.
"""

from unittest.mock import AsyncMock, patch, MagicMock

from bundled_agents.instance import tools as inst


async def test_on_add_ws_creates_agent(engine, tmp_path):
    await inst.on_add(
        str(tmp_path), name="box1", transport="ws", url="ws://example:8888"
    )
    instances = [a for a in engine.store.list_agents() if a.get("bundle") == "instance"]
    assert len(instances) == 1
    a = instances[0]
    assert a["display_name"] == "box1"
    assert a["transport"] == "ws"
    assert a["url"] == "ws://example:8888"
    assert a["status"] == "stopped"


async def test_on_add_ssh_infers_transport(engine, tmp_path):
    await inst.on_add(str(tmp_path), name="gpu", ssh_host="gpu-box", remote_dir="/r")
    instances = [a for a in engine.store.list_agents() if a.get("bundle") == "instance"]
    assert instances[0]["transport"] == "ssh"
    assert instances[0]["ssh_host"] == "gpu-box"
    assert instances[0]["remote_dir"] == "/r"
    assert instances[0]["remote_cmd"] == "fantastic"


async def test_on_add_idempotent(engine, tmp_path):
    await inst.on_add(str(tmp_path), name="box1", transport="ws", url="ws://x:1")
    await inst.on_add(str(tmp_path), name="box1", transport="ws", url="ws://x:2")
    instances = [a for a in engine.store.list_agents() if a.get("bundle") == "instance"]
    assert len(instances) == 1
    # Second call is a no-op; url stays from first call.
    assert instances[0]["url"] == "ws://x:1"


async def test_on_add_rejects_bad_args(engine, tmp_path, capsys):
    # transport=ws without url
    await inst.on_add(str(tmp_path), name="a", transport="ws")
    # transport=ssh without ssh_host
    await inst.on_add(str(tmp_path), name="b", transport="ssh")
    instances = [a for a in engine.store.list_agents() if a.get("bundle") == "instance"]
    assert instances == []


async def test_instance_start_ws_healthy(engine, tmp_path):
    await inst.on_add(str(tmp_path), name="p", transport="ws", url="ws://x:1")
    aid = [a["id"] for a in engine.store.list_agents() if a["bundle"] == "instance"][0]
    with patch.object(inst, "_ws_open_probe", AsyncMock(return_value=True)):
        tr = await inst._start(agent_id=aid)
    assert tr.data["ok"] is True
    assert tr.data["status"] == "running"
    assert engine.get_agent(aid)["status"] == "running"


async def test_instance_start_ws_unresponsive(engine, tmp_path):
    await inst.on_add(str(tmp_path), name="p", transport="ws", url="ws://x:1")
    aid = [a["id"] for a in engine.store.list_agents() if a["bundle"] == "instance"][0]
    with patch.object(inst, "_ws_open_probe", AsyncMock(return_value=False)):
        tr = await inst._start(agent_id=aid)
    assert tr.data["ok"] is False
    assert tr.data["status"] == "unresponsive"


async def test_instance_start_ssh_spawns_tunnel(engine, tmp_path):
    await inst.on_add(str(tmp_path), name="gpu", ssh_host="h", remote_dir="/r")
    aid = [a["id"] for a in engine.store.list_agents() if a["bundle"] == "instance"][0]

    fake_proc = MagicMock()
    fake_proc.pid = 12345
    fake_proc.returncode = None

    async def fake_spawn(*args, **kwargs):
        return fake_proc

    with (
        patch.object(inst.asyncio, "create_subprocess_shell", fake_spawn),
        patch.object(inst, "_ws_open_probe", AsyncMock(return_value=True)),
        patch.object(inst, "_find_free_local_port", return_value=49999),
    ):
        tr = await inst._start(agent_id=aid)

    assert tr.data["ok"] is True
    a = engine.get_agent(aid)
    assert a["status"] == "running"
    assert a["tunnel_pid"] == 12345
    assert a["local_port"] == 49999
    assert a["url"] == "ws://127.0.0.1:49999"


async def test_instance_stop_ssh_kills_tunnel(engine, tmp_path):
    await inst.on_add(str(tmp_path), name="gpu", ssh_host="h")
    aid = [a["id"] for a in engine.store.list_agents() if a["bundle"] == "instance"][0]
    engine.update_agent_meta(
        aid,
        status="running",
        tunnel_pid=99999,
        local_port=49999,
        url="ws://127.0.0.1:49999",
    )
    with patch("os.kill", MagicMock()):
        tr = await inst._stop(agent_id=aid)
    assert tr.data["status"] == "stopped"
    a = engine.get_agent(aid)
    assert a["status"] == "stopped"
    assert a.get("tunnel_pid") is None
    assert a["url"] == ""


async def test_instance_call_proxies_ws(engine, tmp_path):
    await inst.on_add(str(tmp_path), name="p", transport="ws", url="ws://x:1")
    aid = [a["id"] for a in engine.store.list_agents() if a["bundle"] == "instance"][0]

    with patch.object(
        inst, "_ws_rpc", AsyncMock(return_value=[{"id": "a", "bundle": "canvas"}])
    ) as rpc:
        tr = await inst._call(agent_id=aid, tool="list_agents", args={})
    assert tr.data["ok"] is True
    assert tr.data["data"] == [{"id": "a", "bundle": "canvas"}]
    rpc.assert_called_once_with("ws://x:1", "list_agents", {})


async def test_instance_call_no_url(engine, tmp_path):
    await inst.on_add(str(tmp_path), name="p", transport="ws", url="ws://x:1")
    aid = [a["id"] for a in engine.store.list_agents() if a["bundle"] == "instance"][0]
    engine.update_agent_meta(aid, url="")
    tr = await inst._call(agent_id=aid, tool="list_agents")
    assert "error" in tr.data


async def test_instance_status_ws(engine, tmp_path):
    await inst.on_add(str(tmp_path), name="p", transport="ws", url="ws://x:1")
    aid = [a["id"] for a in engine.store.list_agents() if a["bundle"] == "instance"][0]
    with patch.object(inst, "_ws_open_probe", AsyncMock(return_value=True)):
        tr = await inst._status(agent_id=aid)
    assert tr.data["status"] == "running"
