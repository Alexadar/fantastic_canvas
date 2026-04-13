"""Tests for file tools — list_files, read_file, write_file."""

from core.tools._content import _list_files, _read_file, _write_file


async def test_list_files_root(setup):
    engine, _, _ = setup
    # Create a file in the project dir
    (engine._project_dir / "hello.py").write_text("print('hi')")
    tr = await _list_files()
    files = tr.data["files"]
    names = [f["name"] for f in files]
    assert "hello.py" in names


async def test_list_files_subdir(setup):
    engine, _, _ = setup
    scripts = engine._project_dir / "scripts"
    scripts.mkdir()
    (scripts / "run.py").write_text("pass")
    tr = await _list_files(path="scripts")
    files = tr.data["files"]
    assert len(files) == 1
    assert files[0]["name"] == "run.py"


async def test_list_files_subdir_not_found(setup):
    tr = await _list_files(path="nonexistent")
    assert "error" in tr.data


async def test_read_file(setup):
    engine, _, _ = setup
    (engine._project_dir / "data.txt").write_text("hello world")
    tr = await _read_file(path="data.txt")
    assert tr.data["content"] == "hello world"
    assert tr.data["path"] == "data.txt"


async def test_read_file_nested(setup):
    engine, _, _ = setup
    sub = engine._project_dir / "src"
    sub.mkdir()
    (sub / "main.py").write_text("import os")
    tr = await _read_file(path="src/main.py")
    assert tr.data["content"] == "import os"


async def test_read_file_not_found(setup):
    tr = await _read_file(path="missing.py")
    assert "error" in tr.data
    assert "not found" in tr.data["error"].lower()


async def test_read_file_no_path(setup):
    tr = await _read_file(path="")
    assert "error" in tr.data


async def test_read_file_directory(setup):
    engine, _, _ = setup
    (engine._project_dir / "adir").mkdir()
    tr = await _read_file(path="adir")
    assert "error" in tr.data
    assert "directory" in tr.data["error"].lower()


async def test_read_file_outside_project(setup):
    tr = await _read_file(path="../../../etc/passwd")
    assert "error" in tr.data
    assert "outside" in tr.data["error"].lower()


async def test_write_file(setup):
    engine, _, _ = setup
    tr = await _write_file(path="output.py", content="print(1)")
    assert tr.data["written"] is True
    assert (engine._project_dir / "output.py").read_text() == "print(1)"


async def test_write_file_creates_dirs(setup):
    engine, _, _ = setup
    tr = await _write_file(path="steps/01/load.py", content="import pandas")
    assert tr.data["written"] is True
    assert (
        engine._project_dir / "steps" / "01" / "load.py"
    ).read_text() == "import pandas"


async def test_write_file_overwrites(setup):
    engine, _, _ = setup
    (engine._project_dir / "x.py").write_text("old")
    tr = await _write_file(path="x.py", content="new")
    assert tr.data["written"] is True
    assert (engine._project_dir / "x.py").read_text() == "new"


async def test_write_file_no_path(setup):
    tr = await _write_file(path="", content="x")
    assert "error" in tr.data


async def test_write_file_outside_project(setup):
    tr = await _write_file(path="../../../tmp/evil.py", content="x")
    assert "error" in tr.data
    assert "outside" in tr.data["error"].lower()


async def test_write_file_agent_scoped(setup):
    """Bare filename + agent_id → written to .fantastic/agents/{id}/."""
    engine, _, _ = setup
    engine.create_agent(bundle="terminal", agent_id="ag1")
    tr = await _write_file(path="script.py", content="x = 1", agent_id="ag1")
    assert tr.data["written"] is True
    assert tr.data["path"] == ".fantastic/agents/ag1/script.py"
    assert (
        engine._project_dir / ".fantastic" / "agents" / "ag1" / "script.py"
    ).read_text() == "x = 1"


async def test_write_file_agent_scoped_with_dir_unchanged(setup):
    """Path with directory component is NOT scoped even with agent_id."""
    engine, _, _ = setup
    tr = await _write_file(path="src/lib.py", content="pass", agent_id="ag1")
    assert tr.data["written"] is True
    assert tr.data["path"] == "src/lib.py"
    assert (engine._project_dir / "src" / "lib.py").read_text() == "pass"


async def test_write_file_no_agent_id_bare_filename(setup):
    """Bare filename without agent_id → written to project root."""
    engine, _, _ = setup
    tr = await _write_file(path="root.py", content="pass")
    assert tr.data["path"] == "root.py"
    assert (engine._project_dir / "root.py").exists()


async def test_write_then_read(setup):
    """Full round-trip: write a file, then read it back."""
    await _write_file(path="roundtrip.py", content="x = 42")
    tr = await _read_file(path="roundtrip.py")
    assert tr.data["content"] == "x = 42"


async def test_write_then_list(setup):
    """Write a file, then verify it appears in list_files."""
    await _write_file(path="new_script.py", content="pass")
    tr = await _list_files()
    names = [f["name"] for f in tr.data["files"]]
    assert "new_script.py" in names
