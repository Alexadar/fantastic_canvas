"""Tests for `file` bundle — filesystem root agent + verb handlers."""

from bundled_agents.file import tools as file_mod


def _aid(engine, display: str = "project") -> str:
    return [
        a["id"]
        for a in engine.store.list_agents()
        if a.get("bundle") == "file" and a.get("display_name") == display
    ][0]


# ─── on_add ────────────────────────────────────────────────────────


async def test_on_add_creates_agent_with_empty_root(engine, tmp_path):
    await file_mod.on_add(str(tmp_path), name="project")
    aid = _aid(engine)
    a = engine.get_agent(aid)
    assert a["bundle"] == "file"
    assert a["root"] == ""
    assert a["readonly"] is False


async def test_on_add_idempotent(engine, tmp_path):
    await file_mod.on_add(str(tmp_path), name="x")
    await file_mod.on_add(str(tmp_path), name="x")
    aids = [a for a in engine.store.list_agents() if a.get("bundle") == "file"]
    assert len(aids) == 1


async def test_on_add_with_explicit_root_and_readonly(engine, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    await file_mod.on_add(str(tmp_path), name="r", root=str(other), readonly=True)
    a = engine.get_agent(_aid(engine, "r"))
    assert a["root"] == str(other)
    assert a["readonly"] is True


# ─── list ──────────────────────────────────────────────────────────


async def test_list_returns_tree(engine, tmp_path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("y")
    await file_mod.on_add(str(tmp_path), name="project")
    tr = await file_mod._list(agent_id=_aid(engine))
    names = [e["name"] for e in tr.data["files"]]
    assert "a.txt" in names and "sub" in names
    sub = next(e for e in tr.data["files"] if e["name"] == "sub")
    assert any(c["name"] == "b.txt" for c in sub["children"])


async def test_list_excludes_hidden(engine, tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: …")
    (tmp_path / "README").write_text("hi")
    await file_mod.on_add(str(tmp_path), name="project")
    tr = await file_mod._list(agent_id=_aid(engine))
    names = {e["name"] for e in tr.data["files"]}
    assert ".git" not in names
    assert "README" in names


async def test_list_custom_hidden(engine, tmp_path):
    (tmp_path / "drafts").mkdir()
    (tmp_path / "drafts" / "wip.md").write_text("")
    (tmp_path / "final.md").write_text("")
    await file_mod.on_add(str(tmp_path), name="project", hidden=["drafts"])
    tr = await file_mod._list(agent_id=_aid(engine))
    names = {e["name"] for e in tr.data["files"]}
    assert "drafts" not in names
    assert "final.md" in names


async def test_list_subdir(engine, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.txt").write_text("")
    await file_mod.on_add(str(tmp_path), name="project")
    tr = await file_mod._list(agent_id=_aid(engine), path="a")
    assert any(e["name"] == "x.txt" for e in tr.data["files"])


# ─── read ──────────────────────────────────────────────────────────


async def test_read_text(engine, tmp_path):
    (tmp_path / "hello.md").write_text("# hi")
    await file_mod.on_add(str(tmp_path), name="project")
    tr = await file_mod._read(agent_id=_aid(engine), path="hello.md")
    assert tr.data["content"] == "# hi"


async def test_read_image(engine, tmp_path):
    (tmp_path / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    await file_mod.on_add(str(tmp_path), name="project")
    tr = await file_mod._read(agent_id=_aid(engine), path="pic.png")
    assert tr.data["kind"] == "image"
    assert tr.data["mime"] == "image/png"
    assert tr.data["image_base64"]


async def test_read_missing(engine, tmp_path):
    await file_mod.on_add(str(tmp_path), name="project")
    tr = await file_mod._read(agent_id=_aid(engine), path="nope.md")
    assert "not found" in tr.data["error"]


# ─── write / delete / rename / mkdir ───────────────────────────────


async def test_write_then_read_roundtrip(engine, tmp_path):
    await file_mod.on_add(str(tmp_path), name="project")
    aid = _aid(engine)
    tr = await file_mod._write(agent_id=aid, path="a/b/c.txt", content="hi")
    assert tr.data["written"] is True
    tr2 = await file_mod._read(agent_id=aid, path="a/b/c.txt")
    assert tr2.data["content"] == "hi"


async def test_write_readonly_refused(engine, tmp_path):
    await file_mod.on_add(str(tmp_path), name="ro", readonly=True)
    tr = await file_mod._write(
        agent_id=_aid(engine, "ro"), path="x.txt", content="nope"
    )
    assert tr.data["error"] == "readonly"


async def test_delete(engine, tmp_path):
    (tmp_path / "gone.txt").write_text("bye")
    await file_mod.on_add(str(tmp_path), name="project")
    tr = await file_mod._delete(agent_id=_aid(engine), path="gone.txt")
    assert tr.data["deleted"] is True
    assert not (tmp_path / "gone.txt").exists()


async def test_rename(engine, tmp_path):
    (tmp_path / "a.txt").write_text("hi")
    await file_mod.on_add(str(tmp_path), name="project")
    tr = await file_mod._rename(
        agent_id=_aid(engine), old_path="a.txt", new_path="b.txt"
    )
    assert tr.data["new_path"] == "b.txt"
    assert (tmp_path / "b.txt").exists()
    assert not (tmp_path / "a.txt").exists()


async def test_mkdir(engine, tmp_path):
    await file_mod.on_add(str(tmp_path), name="project")
    tr = await file_mod._mkdir(agent_id=_aid(engine), path="new/sub")
    assert tr.data["created"] is True
    assert (tmp_path / "new" / "sub").is_dir()


# ─── path safety ───────────────────────────────────────────────────


async def test_list_escape_rejected(engine, tmp_path):
    (tmp_path / "inside").mkdir()
    await file_mod.on_add(str(tmp_path), name="project", root=str(tmp_path / "inside"))
    tr = await file_mod._list(agent_id=_aid(engine), path="../")
    assert "outside root" in tr.data["error"]


async def test_write_escape_rejected(engine, tmp_path):
    (tmp_path / "inside").mkdir()
    await file_mod.on_add(str(tmp_path), name="project", root=str(tmp_path / "inside"))
    tr = await file_mod._write(
        agent_id=_aid(engine), path="../outside.txt", content="x"
    )
    assert "outside root" in tr.data["error"]


# ─── multiple roots ────────────────────────────────────────────────


async def test_multiple_roots_independent(engine, tmp_path):
    a_root = tmp_path / "a"
    a_root.mkdir()
    b_root = tmp_path / "b"
    b_root.mkdir()
    (a_root / "only_a.txt").write_text("a")
    (b_root / "only_b.txt").write_text("b")

    await file_mod.on_add(str(tmp_path), name="a", root=str(a_root))
    await file_mod.on_add(str(tmp_path), name="b", root=str(b_root))
    aid_a, aid_b = _aid(engine, "a"), _aid(engine, "b")

    tr_a = await file_mod._list(agent_id=aid_a)
    tr_b = await file_mod._list(agent_id=aid_b)
    assert {e["name"] for e in tr_a.data["files"]} == {"only_a.txt"}
    assert {e["name"] for e in tr_b.data["files"]} == {"only_b.txt"}
