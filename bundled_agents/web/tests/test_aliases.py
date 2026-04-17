"""Tests for the alias verbs + /content/ HTTP route owned by the web bundle."""


# ─── dispatch verbs ────────────────────────────────────────────────


async def test_alias_file_relative(engine_with_web, tmp_path):
    eng, web_id, web = engine_with_web
    target = tmp_path / "NOTES.md"
    target.write_text("# hi\n")
    # Explicit absolute path — the alias tool stores it relative to
    # project_dir when possible, which is tmp_path here.
    tr = await web._alias(agent_id=web_id, kind="file", path=str(target))
    assert "alias_id" in tr.data
    assert tr.data["alias_path"].startswith("/content/")
    entries = web.load_aliases(web_id)
    entry = entries[tr.data["alias_id"]]
    assert entry["type"] == "file"
    assert entry["path"] == "NOTES.md"
    assert entry["relative"] is True


async def test_alias_file_requires_path(engine_with_web):
    _, web_id, web = engine_with_web
    tr = await web._alias(agent_id=web_id, kind="file")
    assert "path required" in tr.data["error"]


async def test_alias_url(engine_with_web):
    _, web_id, web = engine_with_web
    tr = await web._alias(agent_id=web_id, kind="url", url="https://example.com")
    assert "alias_id" in tr.data
    entries = web.load_aliases(web_id)
    e = entries[tr.data["alias_id"]]
    assert e["type"] == "url" and e["url"] == "https://example.com"


async def test_alias_rejects_unknown_kind(engine_with_web):
    _, web_id, web = engine_with_web
    tr = await web._alias(agent_id=web_id, kind="ftp", url="ftp://x")
    assert "kind must be" in tr.data["error"]


async def test_alias_rejects_non_web_agent(engine_with_web):
    eng, _, web = engine_with_web
    other = eng.store.create_agent(bundle="canvas")
    tr = await web._alias(agent_id=other["id"], kind="url", url="https://x")
    assert "not a web agent" in tr.data["error"]


async def test_aliases_list(engine_with_web, tmp_path):
    _, web_id, web = engine_with_web
    (tmp_path / "a.txt").write_text("x")
    await web._alias(agent_id=web_id, kind="file", path="a.txt")
    await web._alias(agent_id=web_id, kind="url", url="https://ex.com")
    tr = await web._aliases(agent_id=web_id)
    kinds = {a["type"] for a in tr.data["aliases"]}
    assert kinds == {"file", "url"}


async def test_unalias(engine_with_web):
    _, web_id, web = engine_with_web
    added = await web._alias(agent_id=web_id, kind="url", url="https://ex.com")
    aid = added.data["alias_id"]
    tr = await web._unalias(agent_id=web_id, alias_id=aid)
    assert tr.data["removed"] is True
    assert aid not in web.load_aliases(web_id)
    # Idempotent second call returns removed=False.
    tr2 = await web._unalias(agent_id=web_id, alias_id=aid)
    assert tr2.data["removed"] is False


async def test_aliases_persist_across_cache_reload(engine_with_web):
    _, web_id, web = engine_with_web
    tr = await web._alias(agent_id=web_id, kind="url", url="https://keep.me")
    # Simulate a fresh process — wipe the in-memory cache, then reload.
    web._aliases_cache.clear()
    reloaded = web.load_aliases(web_id)
    assert tr.data["alias_id"] in reloaded


# ─── HTTP route (FastAPI TestClient) ──────────────────────────────


async def test_content_route_serves_file(engine_with_web, tmp_path):
    from fastapi.testclient import TestClient
    from bundled_agents.web.app import make_app

    eng, web_id, web = engine_with_web
    target = tmp_path / "NOTES.md"
    target.write_text("# hi\nline2\n")
    added = await web._alias(agent_id=web_id, kind="file", path=str(target))
    aid = added.data["alias_id"]

    app = make_app(web_id, eng)
    r = TestClient(app).get(f"/content/{aid}")
    assert r.status_code == 200
    assert "# hi" in r.text


async def test_content_route_redirects_url(engine_with_web):
    from fastapi.testclient import TestClient
    from bundled_agents.web.app import make_app

    eng, web_id, web = engine_with_web
    added = await web._alias(agent_id=web_id, kind="url", url="https://example.com")
    aid = added.data["alias_id"]

    app = make_app(web_id, eng)
    r = TestClient(app).get(f"/content/{aid}", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "https://example.com"


async def test_content_route_unknown_404(engine_with_web):
    from fastapi.testclient import TestClient
    from bundled_agents.web.app import make_app

    eng, web_id, _ = engine_with_web
    app = make_app(web_id, eng)
    r = TestClient(app).get("/content/does-not-exist")
    assert r.status_code == 404
