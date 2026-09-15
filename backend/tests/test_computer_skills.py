import asyncio

from app.config import get_settings  # noqa: F401
from app.security.redact import redact_text, strip_secret_args
from app.services.chat_access import ingest_from_text, redact_for_user, resolve
from app.services.connectors import list_public, secret_values
from computer_skills.loader import catalog, load_skill
from computer_tools import COMPUTER_TOOL_NAMES, run_computer_tool, skills_prompt


EXPECTED_SKILLS = {
    "api",
    "brief",
    "browser",
    "canvas",
    "code",
    "compare",
    "debug",
    "deck",
    "documents",
    "email",
    "extract",
    "humanize",
    "images",
    "infographic",
    "legal",
    "minutes",
    "ops",
    "pdf",
    "prices",
    "privacy",
    "research",
    "rewrite",
    "science",
    "spreadsheet",
    "sql",
    "ssh",
    "studio_render",
    "verify",
    "visual_system",
    "workspace",
}


def test_skills_catalog_covers_core_playbooks():
    catalog.cache_clear()
    names = {item["name"] for item in catalog()}
    assert names == EXPECTED_SKILLS
    text = load_skill("humanize")
    assert "канцелярита" in text or "живой" in text.lower()
    assert "самодостаточный HTML" in load_skill("canvas")
    assert "load_skill" in skills_prompt()
    assert "browser" in skills_prompt()
    assert "api" in skills_prompt()
    assert "http_request" in load_skill("api")
    assert "python_run" in load_skill("code")
    assert "ssh_exec" in load_skill("ops")
    assert "pandas" in load_skill("spreadsheet")
    assert "forget_access" in load_skill("privacy")
    assert "слайды → deck" in skills_prompt()
    assert "фото → images" in skills_prompt()
    assert "Не решай заранее" in skills_prompt()
    assert "уже вложен" in skills_prompt()
    assert "не цитируй" in skills_prompt()


def test_match_skills_preloads_photo_and_code_playbooks():
    from computer_skills.loader import match_skills, preload_skills_block

    photo = match_skills("найди где снято фото", has_images=True)
    assert photo[0] == "images"
    assert "research" in photo
    code = match_skills("найди ошибку в коде")
    assert code[0] == "code"
    assert match_skills("привет") == []
    assert "infographic" in match_skills("сделать схему процесса ERS")
    contract = match_skills("разбери этот договор и найди риски")
    assert "legal" in contract
    assert "documents" in contract
    audit = match_skills("проверь договор поставки")
    assert audit[0] == "verify"
    assert "documents" in audit or "legal" in audit
    assert "science" in match_skills("рассчитай интеграл по x")
    assert "minutes" in match_skills("сделай протокол встречи")
    assert "rewrite" in match_skills("перепиши этот абзац, сохрани структуру")
    assert "pdf" in match_skills("собери pdf из отчёта")
    assert "sql" in match_skills("напиши select из таблицы users")
    assert "legal" in match_skills("разбери оферту и претензию")
    block = preload_skills_block("найди где снято фото", has_images=True)
    assert "Скилы уже подобраны" in block
    assert "image_search" in block


def test_chat_scope_skips_sandbox_playbooks():
    from computer_skills.loader import CHAT_SKILLS, match_skills, preload_skills_block, skill_scope

    assert skill_scope("rewrite") == "chat"
    assert skill_scope("code") == "sandbox"
    assert skill_scope("bitship_tone", "custom") == "chat"
    assert "legal" in CHAT_SKILLS
    assert "documents" not in CHAT_SKILLS
    chat_contract = match_skills("разбери этот договор и найди риски", sandbox=False)
    assert "legal" in chat_contract
    assert "documents" not in chat_contract
    assert "code" not in match_skills("найди ошибку в коде", sandbox=False)
    assert "rewrite" in match_skills("перепиши этот абзац, сохрани структуру", sandbox=False)
    photo = match_skills("найди где снято фото", has_images=True, sandbox=False)
    assert "images" not in photo
    chat_block = preload_skills_block("перепиши абзац, сохрани структуру", sandbox=False)
    assert "Песочницы нет" in chat_block
    assert "rewrite" in chat_block.lower() or "структур" in chat_block.lower()
    assert "# code" not in chat_block


def test_computer_tool_descriptions_include_when_not_to_use():
    from computer_tools import COMPUTER_TOOLS_RESPONSES

    by_name = {item["name"]: item["description"] for item in COMPUTER_TOOLS_RESPONSES}
    assert "Не localhost" in by_name["browse_page"]
    assert "query" in by_name["browse_page"]
    assert "Не проси прислать" in by_name["read_chat_document"]
    assert "не интернет" in by_name["search_chats"].lower()
    assert "read_chat_document" in by_name["list_chat_files"]
    assert "image_search" in by_name["list_chat_files"]
    assert "Яндекс" in by_name["image_search"]
    assert "памяти" in by_name["image_search"]
    assert "без регулярок" in by_name["workspace_grep"]
    assert "до кода" in by_name["load_skill"] or "Перед кодом" in by_name["load_skill"]
    assert "запомни" in by_name["save_skill"]
    assert "свои" in by_name["delete_skill"].lower() or "свой" in by_name["delete_skill"].lower()
    assert "не спрашивай" in by_name["python_run"]
    assert "не PDF" in by_name["studio_build"].lower() or "infographic" in by_name["studio_build"]


def test_unknown_skill_lists_available():
    result = load_skill("telepathy")
    assert "нет" in result.lower()
    assert "humanize" in result


def test_tool_args_never_keep_passwords_in_logs():
    cleaned = strip_secret_args({"url": "https://example.com/login", "password": "hunter2secret", "username": "ivan"})
    assert cleaned["password"] == "•••"
    assert cleaned["username"] == "ivan"
    assert "hunter2secret" not in redact_text("пароль hunter2secret", ["hunter2secret"])


def test_gmail_without_chat_creds_asks_for_message_data():
    result = asyncio.run(run_computer_tool("gmail_list", {}, user_id=93001))
    assert "настройк" not in result.lower()
    assert "чат" in result.lower() or "логин" in result.lower() or "парол" in result.lower()


def test_inline_gmail_is_encrypted_and_not_listed_as_secret():
    payload, error = resolve(
        93002,
        "gmail",
        {"email": "me@gmail.com", "app_password": "abcd-efgh-ijkl-mnop"},
    )
    assert error is None
    assert payload["email"] == "me@gmail.com"
    public = list_public(93002)
    assert any(item["type"] == "gmail" for item in public)
    assert "abcd-efgh-ijkl-mnop" not in str(public)
    assert "abcd-efgh-ijkl-mnop" in secret_values(93002)


def test_ingest_login_password_from_chat_text():
    ingest_from_text(
        93003,
        "зайди на https://cabinet.example.com логин ivan пароль SuperSecret99",
    )
    items = list_public(93003)
    assert items
    assert items[0]["type"] == "web"
    assert "SuperSecret99" not in str(items)
    assert "SuperSecret99" not in redact_for_user(93003, "пароль SuperSecret99")


def test_site_login_and_skill_tools_are_registered():
    assert {"workspace_ls", "workspace_write", "python_run", "pip_install", "workspace_grep", "search_chats", "list_chat_files", "image_search", "save_skill", "delete_skill"} <= COMPUTER_TOOL_NAMES
    listed = asyncio.run(run_computer_tool("list_skills", {}, user_id=1))
    assert "humanize" in listed
    loaded = asyncio.run(run_computer_tool("load_skill", {"name": "browser"}, user_id=1))
    assert "site_login" in loaded
    images = asyncio.run(run_computer_tool("load_skill", {"name": "images"}, user_id=1))
    assert "image_search" in images
    assert "Яндекс" in images


def test_chat_memory_tools_search_list_and_recent():
    from db_conversations import DatabaseConversationManager

    mgr = DatabaseConversationManager()
    uid = 93121
    mgr.create_conversation(uid, title="Поставка Ромашка")
    mgr.add_message(uid, "user", "Нужно сверить договор поставки с ООО Ромашка")
    mgr.add_message(uid, "assistant", "Сверю пункты договора.")
    mgr.add_document(uid, "act.pdf", "секретный текст акта не должен утечь в список")
    listed = asyncio.run(run_computer_tool("list_chat_files", {}, user_id=uid))
    assert "act.pdf" in listed
    assert "секретный текст" not in listed
    mgr.add_message(
        uid,
        "user",
        "photo.jpg",
        attachment={"type": "image", "name": "balcony.jpg", "url": "/uploads/chat/x/balcony.jpg", "mime_type": "image/jpeg"},
    )
    listed_photos = asyncio.run(run_computer_tool("list_chat_files", {}, user_id=uid))
    assert "balcony.jpg" in listed_photos
    assert "image_search" in listed_photos

    mgr.create_conversation(uid, title="Погода Сочи")
    mgr.add_message(uid, "user", "какая погода в Сочи на выходных")
    found = asyncio.run(run_computer_tool("search_chats", {"query": "Ромашка договор"}, user_id=uid))
    assert "Ромашка" in found
    assert "Поставка" in found
    assert "Погода Сочи" not in found
    recent = asyncio.run(run_computer_tool("recent_chats", {"limit": 5}, user_id=uid))
    assert "Погода Сочи" in recent
    assert "этот" in recent


def test_search_chats_redacts_labeled_secrets_and_fails_closed(monkeypatch):
    from db_conversations import DatabaseConversationManager

    mgr = DatabaseConversationManager()
    uid = 93122
    mgr.create_conversation(uid, title="Доступы")
    mgr.add_message(uid, "user", "логин ivan пароль: SuperSecret99 для кабинета")
    found = asyncio.run(run_computer_tool("search_chats", {"query": "кабинета"}, user_id=uid))
    assert "кабинета" in found
    assert "SuperSecret99" not in found

    def boom(_user_id):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.services.connectors.secret_values", boom)
    closed = mgr.search_user_chats(uid, "кабинета")
    assert "SuperSecret99" not in closed
    assert "[скрыто]" in closed


def test_browse_page_uses_query_excerpt(monkeypatch):
    async def fake_fetch(url):
        return url, ("вступление " * 50) + "курс доллара 92 рубля сегодня " + ("хвост " * 50)

    monkeypatch.setattr("web_scraper.fetch_url_content", fake_fetch)
    text = asyncio.run(
        run_computer_tool("browse_page", {"url": "https://example.com/fx", "query": "доллара"}, user_id=1)
    )
    assert "92" in text
    assert "Запрос: доллара" in text
