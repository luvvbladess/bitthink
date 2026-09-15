from app.config import get_settings  # noqa: F401
from app.services.workspace_fs import collect_deliverables, dispatch, resolve_in_jail, valid_pip_spec
from computer_skills.loader import catalog
from computer_tools import COMPUTER_TOOL_NAMES


def test_workspace_is_jailed_and_runs_python(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    monkeypatch.setenv("WORKSPACE_ALLOW_LOCAL_RUN", "1")
    uid = 94001
    written = dispatch(uid, "write", {"path": "scripts/hello.py", "content": "print('sandbox-ok', 2 + 2)\n"})
    assert "Записал" in written
    listing = dispatch(uid, "ls", {"path": "scripts"})
    assert "hello.py" in listing
    output = dispatch(uid, "run", {"path": "scripts/hello.py"})
    assert "sandbox-ok" in output
    assert "4" in output
    edited = dispatch(
        uid,
        "edit",
        {"path": "scripts/hello.py", "old_string": "2 + 2", "new_string": "3 + 3"},
    )
    assert "Записал" in edited
    assert "print('sandbox-ok', 3 + 3)" in dispatch(uid, "read", {"path": "scripts/hello.py"})


def test_workspace_rejects_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    uid = 94002
    dispatch(uid, "write", {"path": "keep.txt", "content": "in-jail"})
    for path in ("../secret.txt", "/etc/passwd", "..\\windows", "foo/../../etc/passwd"):
        try:
            resolve_in_jail(uid, path)
            raised = False
        except ValueError:
            raised = True
        assert raised, path
    other = dispatch(94003, "ls", {})
    assert "keep.txt" not in other


def test_python_dash_c_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    monkeypatch.setenv("WORKSPACE_ALLOW_LOCAL_RUN", "1")
    dispatch(94004, "write", {"path": "x.py", "content": "print(1)\n"})
    result = dispatch(94004, "run", {"path": "x.py", "argv": ["-c", "print(1)"]})
    assert "дефиса" in result or "начинаться" in result


def test_workspace_tools_and_skill_are_registered():
    catalog.cache_clear()
    names = {item["name"] for item in catalog()}
    assert "workspace" in names
    assert {"workspace_ls", "workspace_write", "python_run", "pip_install", "workspace_grep", "workspace_glob"} <= COMPUTER_TOOL_NAMES


def test_pip_specs_are_strict(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    monkeypatch.setenv("WORKSPACE_ALLOW_LOCAL_RUN", "1")
    assert valid_pip_spec("requests")
    assert valid_pip_spec("pandas==2.2.0")
    assert valid_pip_spec("scikit-learn")
    assert not valid_pip_spec("requests; rm -rf /")
    assert not valid_pip_spec("git+https://evil.example/x.git")
    assert not valid_pip_spec("../secret")
    assert not valid_pip_spec("http://example.com/x.whl")
    blocked = dispatch(94005, "pip", {"packages": ["git+https://evil.example/x.git"]})
    assert "Нельзя" in blocked
    from computer_skills.loader import load_skill

    skill = load_skill("workspace")
    assert "pip_install" in skill
    assert "сам решай" in skill.lower() or "не спрашивай" in skill.lower()
    assert "кнопкой" in skill.lower() or "скач" in skill.lower()


def test_collect_deliverables_returns_recent_xlsx(tmp_path, monkeypatch):
    import json
    import time

    from app.services.workspace_fs import user_root

    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    uid = 94010
    target = user_root(uid) / "optimized.xlsx"
    target.write_bytes(b"PK\x03\x04fake-xlsx")
    payload = json.loads(collect_deliverables(uid, time.time() - 30))
    assert payload and payload[0]["name"] == "optimized.xlsx"
    assert payload[0]["data_b64"]
    stale = json.loads(collect_deliverables(uid, time.time() + 120))
    assert stale == []
    listed = dispatch(uid, "deliverables", {"since": time.time() - 30})
    assert "optimized.xlsx" in listed


def test_collect_deliverables_auto_zips_python_sources(tmp_path, monkeypatch):
    import base64
    import json
    import time
    import zipfile
    from io import BytesIO

    from app.services.workspace_fs import user_root

    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    uid = 94011
    root = user_root(uid)
    (root / "bot.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "requirements.txt").write_text("aiogram\n", encoding="utf-8")
    payload = json.loads(collect_deliverables(uid, time.time() - 30))
    assert payload and payload[0]["name"] == "project.zip"
    data = base64.b64decode(payload[0]["data_b64"])
    with zipfile.ZipFile(BytesIO(data)) as archive:
        names = set(archive.namelist())
    assert "bot.py" in names
    assert "requirements.txt" in names


def test_collect_deliverables_skips_helper_scripts(tmp_path, monkeypatch):
    import json
    import time

    from app.services.workspace_fs import user_root

    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    uid = 94012
    root = user_root(uid)
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "calc_budget.py").write_text("print(82)\n", encoding="utf-8")
    (scripts / "extract_docx.py").write_text("print('doc')\n", encoding="utf-8")
    (scripts / "inspect_tz.py").write_text("print('tz')\n", encoding="utf-8")
    payload = json.loads(collect_deliverables(uid, time.time() - 30))
    assert payload == []


def test_collect_deliverables_prefers_document_over_scripts(tmp_path, monkeypatch):
    import json
    import time

    from app.services.workspace_fs import user_root

    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    uid = 94013
    root = user_root(uid)
    (root / "scripts").mkdir()
    (root / "scripts" / "inspect_tz.py").write_text("print('tz')\n", encoding="utf-8")
    (root / "dogovor.docx").write_bytes(b"PK\x03\x04fake-docx")
    payload = json.loads(collect_deliverables(uid, time.time() - 30))
    names = [item["name"] for item in payload]
    assert names == ["dogovor.docx"]


def test_collect_deliverables_skips_root_helper_scripts(tmp_path, monkeypatch):
    import json
    import time

    from app.services.workspace_fs import user_root

    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    uid = 94014
    root = user_root(uid)
    (root / "extract_docx.py").write_text("print('doc')\n", encoding="utf-8")
    (root / "inspect_tz.py").write_text("print('tz')\n", encoding="utf-8")
    payload = json.loads(collect_deliverables(uid, time.time() - 30))
    assert payload == []


def test_collect_deliverables_does_not_zip_markdown_notes(tmp_path, monkeypatch):
    import json
    import time

    from app.services.workspace_fs import user_root

    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    uid = 94015
    root = user_root(uid)
    (root / "dogovor.md").write_text("договор\n", encoding="utf-8")
    (root / "smeta.md").write_text("смета\n", encoding="utf-8")
    payload = json.loads(collect_deliverables(uid, time.time() - 30))
    names = [item["name"] for item in payload]
    assert "project.zip" not in names


def test_collect_deliverables_zips_bot_inside_scripts(tmp_path, monkeypatch):
    import base64
    import json
    import time
    import zipfile
    from io import BytesIO

    from app.services.workspace_fs import user_root

    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    uid = 94016
    root = user_root(uid)
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "bot.py").write_text("print('hi')\n", encoding="utf-8")
    (scripts / "requirements.txt").write_text("aiogram\n", encoding="utf-8")
    payload = json.loads(collect_deliverables(uid, time.time() - 30))
    assert payload and payload[0]["name"] == "project.zip"
    data = base64.b64decode(payload[0]["data_b64"])
    with zipfile.ZipFile(BytesIO(data)) as archive:
        names = set(archive.namelist())
    assert "scripts/bot.py" in names
    assert "scripts/requirements.txt" in names


def test_workspace_grep_glob_and_line_read(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    monkeypatch.setenv("WORKSPACE_ALLOW_LOCAL_RUN", "1")
    uid = 94120
    dispatch(uid, "write", {"path": "scripts/hello.py", "content": "alpha = 1\nprint('sandbox-ok')\nbeta = 2\n"})
    dispatch(uid, "write", {"path": "data/note.txt", "content": "unrelated\n"})
    found = dispatch(uid, "grep", {"pattern": "sandbox-ok", "glob": "*.py"})
    assert "scripts/hello.py:2:" in found
    assert "unrelated" not in found
    listed = dispatch(uid, "glob", {"pattern": "**/*.py"})
    assert "scripts/hello.py" in listed
    assert "note.txt" not in listed
    chunk = dispatch(uid, "read", {"path": "scripts/hello.py", "start_line": 2, "end_line": 2})
    assert "2|print('sandbox-ok')" in chunk
    assert "alpha" not in chunk
    other = dispatch(94121, "grep", {"pattern": "sandbox-ok"})
    assert "hello.py" not in other
    escaped = dispatch(uid, "grep", {"pattern": "ok", "path": "../secret"})
    assert "относительный" in escaped.lower() or ".." in escaped.lower() or "запрещ" in escaped.lower()


def test_sandbox_remote_payload_keeps_authenticated_user(monkeypatch):
    import asyncio
    from app.services import sandbox_client

    captured: dict = {}

    async def fake_remote(_url, payload):
        captured.update(payload)
        return "ok"

    monkeypatch.setenv("SANDBOX_URL", "http://sandbox:8090")
    monkeypatch.delenv("WORKSPACE_ALLOW_LOCAL_RUN", raising=False)
    monkeypatch.setattr(sandbox_client, "_remote", fake_remote)
    result = asyncio.run(
        sandbox_client.run_workspace_tool(
            "workspace_grep",
            {"pattern": "x", "user_id": 1, "op": "write"},
            user_id=94199,
        )
    )
    assert result == "ok"
    assert captured["user_id"] == 94199
    assert captured["op"] == "grep"
    assert captured["pattern"] == "x"
