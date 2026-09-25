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


def test_collect_deliverables_bundles_a_document_set_instead_of_dropping(tmp_path, monkeypatch):
    """18 документов комплекта: раньше приходили первые 8, остальные молча
    терялись. Теперь, если отдельными карточками не влезает, всё уходит
    одним архивом с папками."""
    import base64
    import json
    import time
    import zipfile
    from io import BytesIO

    from app.services.workspace_fs import BUNDLE_NAME, MAX_DELIVER_FILES, user_root

    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    uid = 94030
    folder = user_root(uid) / "komplekt"
    folder.mkdir()
    for i in range(1, 19):
        (folder / f"{i:02d}_Документ.docx").write_bytes(b"PK\x03\x04fake-docx")
    (folder / "src").mkdir()
    (folder / "src" / "01_Документ.md").write_text("текст", encoding="utf-8")
    (folder / "build.py").write_text("print(1)\n", encoding="utf-8")

    payload = json.loads(collect_deliverables(uid, time.time() - 30))
    assert len(payload) == 1 and payload[0]["name"] == BUNDLE_NAME, [p["name"] for p in payload]
    with zipfile.ZipFile(BytesIO(base64.b64decode(payload[0]["data_b64"]))) as archive:
        names = archive.namelist()
    docx = [n for n in names if n.endswith(".docx")]
    assert len(docx) == 18 > MAX_DELIVER_FILES
    assert "komplekt/18_Документ.docx" in names
    assert not any(n.endswith((".py", ".md")) for n in names), "scripts and drafts are not deliverables"


def test_collect_deliverables_keeps_small_sets_as_separate_files(tmp_path, monkeypatch):
    import json
    import time

    from app.services.workspace_fs import user_root

    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    uid = 94031
    root = user_root(uid)
    for i in range(3):
        (root / f"doc{i}.docx").write_bytes(b"PK\x03\x04fake-docx")
    payload = json.loads(collect_deliverables(uid, time.time() - 30))
    assert sorted(p["name"] for p in payload) == ["doc0.docx", "doc1.docx", "doc2.docx"]


def test_director_detects_document_package_tasks():
    import director_router as dr

    assert dr._is_document_package_task("Подготовь комплект документов по заданию")
    assert dr._is_document_package_task("Документы 1-5 из реестра komplekt/00_Реестр.md")
    assert dr._is_document_package_task("нужно 18 документов")
    assert dr._is_document_package_task("переработай имеющиеся документы")
    assert not dr._is_document_package_task("найди курс доллара")
    assert not dr._is_document_package_task("разбери договор")


def test_director_file_choice_line_is_parsed_and_removed():
    import director_router as dr

    files = ["01_ПМИ_СПО.docx", "01_Программа_и_методика_испытаний_СПО.docx", "02_Протокол_испытаний_СПО.docx"]
    answer = "Готово, собрал ПМИ и протокол.\n\n**Файлы для пользователя:** «01_ПМИ_СПО.docx»; 02_Протокол_испытаний_СПО.docx"
    text, chosen = dr._split_file_choice(answer, files)
    assert text == "Готово, собрал ПМИ и протокол."
    assert chosen == ["01_ПМИ_СПО.docx", "02_Протокол_испытаний_СПО.docx"]
    # No line, or names that are not real files: no decision, everything goes out.
    assert dr._split_file_choice("Готово.", files) == ("Готово.", None)
    assert dr._split_file_choice("Готово.\nФайлы для пользователя: итог.docx", files)[1] is None


def test_only_chosen_deliverables_reach_the_chat():
    from turn_scope import choose_deliverables, pick_deliverables

    files = [{"filename": "01_ПМИ_СПО.docx"}, {"filename": "черновик.docx"}, {"filename": "02_Протокол.docx"}]
    choose_deliverables(["01_ПМИ_СПО.docx", "02_Протокол.docx"])
    assert [f["filename"] for f in pick_deliverables(files)] == ["01_ПМИ_СПО.docx", "02_Протокол.docx"]
    # The choice is used once; the next reply without a choice gets everything.
    assert len(pick_deliverables(files)) == 3
    # A choice that matches nothing must not lose the work.
    choose_deliverables(["нет_такого.docx"])
    assert len(pick_deliverables(files)) == 3


def test_director_picks_final_files_at_the_end(monkeypatch):
    import asyncio

    import director_router as dr
    from turn_scope import pick_deliverables

    candidates = ["01_ПМИ.docx", "01_ПМИ_черновик.docx", "02_Протокол.docx"]
    seen = {}

    async def fake_plan(_task, journal, _user_id, document_context="", history_text=""):
        if journal:
            return {"status": "done", "new_employees": []}
        return {"status": "continue", "new_employees": [{"role": "Документы", "task": "собери", "model": "gpt-6-luna"}]}

    async def fake_exec(employee, round_num, journal, user_id, document_context="", history_text="", has_images=False):
        return {**employee, "round": round_num, "status": "ok", "result": "ok", "reasoning": "", "search": []}

    async def fake_files(_user_id, _since):
        return candidates

    async def fake_compose(_task, _journal, _user_id, history_text="", document_context="", built_files=None):
        seen["offered"] = built_files
        return "Готово.\nФайлы для пользователя: 01_ПМИ.docx; 02_Протокол.docx", ""

    async def fake_status(*_args, **_kwargs):
        return None

    monkeypatch.setattr(dr, "_plan_round", fake_plan)
    monkeypatch.setattr(dr, "_execute_employee", fake_exec)
    monkeypatch.setattr(dr, "_new_file_names", fake_files)
    monkeypatch.setattr(dr, "_compose_answer", fake_compose)
    monkeypatch.setattr(dr, "_update_status", fake_status)
    monkeypatch.setattr(dr, "_sanitize_answer", lambda text: text)
    monkeypatch.setattr(dr, "_turn_has_images", lambda _uid: False)
    monkeypatch.setattr(dr, "_clamp_employee_plan", lambda plan, *_a, **_k: plan)

    async def run():
        answer, *_ = await dr.get_director_response([{"role": "user", "content": "сделай ПМИ и протокол"}], "сделай ПМИ и протокол", 1, None)
        return answer, pick_deliverables([{"filename": name} for name in candidates])

    answer, delivered = asyncio.run(run())
    assert answer == "Готово."
    assert seen["offered"] == candidates
    assert [f["filename"] for f in delivered] == ["01_ПМИ.docx", "02_Протокол.docx"]


def test_director_makes_a_package_one_document_at_a_time(monkeypatch):
    """Комплект: документ за документом, каждый выкладывается в чат сразу,
    в итоговом ответе те же файлы второй раз не уходят."""
    import asyncio

    import director_router as dr
    from turn_scope import delivery, pick_deliverables

    docs = [
        {"title": "Отчёт 2.6", "filename": "01_Отчет_2_6.docx", "brief": "по заданию"},
        {"title": "Отчёт 2.7", "filename": "02_Отчет_2_7.docx", "brief": "по заданию"},
        {"title": "Протокол", "filename": "03_Протокол.docx", "brief": "по заданию"},
    ]
    workspace: list[str] = []
    calls: list[str] = []
    posted: list[tuple[str, list[str]]] = []

    async def fake_docs(*_args, **_kwargs):
        return docs

    async def fake_exec(employee, round_num, journal, user_id, document_context="", history_text="", has_images=False):
        calls.append(employee["role"])
        # Everything posted so far is already in the chat before the next document starts.
        assert len(posted) == round_num - 1
        name = docs[round_num - 1]["filename"]
        # The protocol fails on the first try and is built on the retry.
        if name != "03_Протокол.docx" or calls.count(employee["role"]) == 2:
            workspace.append(name)
        return {**employee, "round": round_num, "status": "ok", "result": "ok", "reasoning": "", "search": []}

    async def fake_files(_user_id, _since):
        return [{"filename": name, "bytes": b"PK"} for name in workspace]

    async def fake_status(*_args, **_kwargs):
        return None

    async def post(text, files):
        posted.append((text, [f["filename"] for f in files]))

    monkeypatch.setattr(dr, "_plan_package_documents", fake_docs)
    monkeypatch.setattr(dr, "_execute_employee", fake_exec)
    monkeypatch.setattr(dr, "_new_files", fake_files)
    monkeypatch.setattr(dr, "_update_status", fake_status)
    monkeypatch.setattr(dr, "_sanitize_answer", lambda text: text)
    monkeypatch.setattr(dr, "_turn_has_images", lambda _uid: False)
    monkeypatch.setattr(dr, "_clamp_employee_plan", lambda plan, *_a, **_k: plan)

    async def run():
        text = "Заверши все остальные документы, делай файлы по одному"
        with delivery(post):
            answer, *_ = await dr.get_director_response([{"role": "user", "content": text}], text, 1, None)
            left = pick_deliverables([{"filename": name} for name in workspace] + [{"filename": "bundle.zip"}])
        return answer, left

    answer, left = asyncio.run(run())
    assert [names for _, names in posted] == [["01_Отчет_2_6.docx"], ["02_Отчет_2_7.docx"], ["03_Протокол.docx"]]
    assert posted[0][0].startswith("Готов документ 1 из 3: «Отчёт 2.6»")
    assert len(calls) == 4
    assert "3 из 3" in answer
    assert [f["filename"] for f in left] == ["bundle.zip"]


def test_director_detects_several_files_as_a_package():
    import director_router as dr

    assert dr._is_document_package_task("сделай три документа: акт, счёт и договор")
    assert dr._is_document_package_task("Заверши все остальные документы")
    assert dr._is_document_package_task("делай файлы по одному")
    assert not dr._is_document_package_task("сделай отчёт в Word")


def test_director_detects_file_requests():
    import director_router as dr

    assert dr._wants_file("Сделай аннотационный отчет.")
    assert dr._wants_file("подготовь отчёт по этапу 1")
    assert dr._wants_file("оформи это в Word")
    assert dr._wants_file("собери таблицу в формате xlsx")
    assert not dr._wants_file("что написано в отчете?")
    assert not dr._wants_file("найди курс доллара")


def test_director_hires_builder_when_requested_file_is_missing(monkeypatch):
    """Планировщик закрыл задачу на тексте без файла: Пилот один раз досылает сборщика."""
    import asyncio

    import director_router as dr

    hired: list[str] = []
    checks = iter([[], ["Аннотационный отчет.docx"]])
    composed: dict = {}

    async def fake_plan(_task, journal, _user_id, document_context="", history_text=""):
        if journal:
            return {"status": "done", "new_employees": []}
        return {"status": "continue", "new_employees": [{"role": "Текст", "task": "напиши текст", "model": "gpt-6-luna"}]}

    async def fake_exec(employee, round_num, journal, user_id, document_context="", history_text="", has_images=False):
        hired.append(employee["role"])
        return {**employee, "round": round_num, "status": "ok", "result": "ok", "reasoning": "", "search": []}

    async def fake_files(_user_id, _since):
        return next(checks)

    async def fake_compose(_task, _journal, _user_id, history_text="", document_context="", built_files=None):
        composed["files"] = built_files
        return "готово", ""

    async def fake_status(*_args, **_kwargs):
        return None

    monkeypatch.setattr(dr, "_plan_round", fake_plan)
    monkeypatch.setattr(dr, "_execute_employee", fake_exec)
    monkeypatch.setattr(dr, "_new_file_names", fake_files)
    monkeypatch.setattr(dr, "_compose_answer", fake_compose)
    monkeypatch.setattr(dr, "_update_status", fake_status)
    monkeypatch.setattr(dr, "_sanitize_answer", lambda text: text)
    monkeypatch.setattr(dr, "_turn_has_images", lambda _uid: False)
    monkeypatch.setattr(dr, "_clamp_employee_plan", lambda plan, *_a, **_k: plan)

    text = "Сделай аннотационный отчет."
    asyncio.run(dr.get_director_response([{"role": "user", "content": text}], text, 1, None))
    assert hired == ["Текст", "Сборка файла"]
    assert composed["files"] == ["Аннотационный отчет.docx"]
