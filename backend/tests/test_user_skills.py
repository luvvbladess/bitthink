import asyncio

from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.config import get_settings  # noqa: F401
from app.main import app
from computer_skills.loader import catalog, load_skill, match_skills
from computer_skills.store import validate_payload
from computer_tools import run_computer_tool
from db_conversations import DatabaseConversationManager


def test_validate_payload_rejects_builtin_name_and_secrets():
    try:
        validate_payload(name="code", description="когда код", body="Пиши коротко и проверяй скриптом.")
        assert False, "expected reserved name error"
    except ValueError as exc:
        assert "занято" in str(exc)
    try:
        validate_payload(
            name="bitship_tone",
            description="письма биципа",
            body="api_key=sk-secret-please-no",
        )
        assert False, "expected secret error"
    except ValueError as exc:
        assert "парол" in str(exc).lower() or "ключ" in str(exc).lower()
    ok = validate_payload(
        name="Bitship-Tone",
        description="Письма и договоры для Биципа",
        body="Обращение на ты. Результат в Word, не скрипт.",
        triggers="бицип, bitship, эрс",
    )
    assert ok["name"] == "bitship_tone"
    assert "бицип" in ok["triggers"]


def test_custom_skill_is_isolated_and_matched():
    mgr = DatabaseConversationManager()
    a, b = 94101, 94102
    mgr.save_user_skill(
        a,
        name="bitship_tone",
        title="Тон Биципа",
        description="Письма и договоры для Биципа",
        body="Обращение на ты. Коротко. Результат в Word.",
        triggers="бицип, bitship",
    )
    names_a = {item["name"] for item in catalog(a)}
    names_b = {item["name"] for item in catalog(b)}
    assert "bitship_tone" in names_a
    assert "bitship_tone" not in names_b
    assert "ваш" in __import__("computer_skills.loader", fromlist=["catalog_for_prompt"]).catalog_for_prompt(a)
    loaded = load_skill("bitship_tone", user_id=a)
    assert "на ты" in loaded
    assert "человека" in loaded
    assert "bitship_tone" in match_skills("напиши письмо для биципа", user_id=a)
    assert "bitship_tone" not in match_skills("напиши письмо для биципа", user_id=b)
    mgr.delete_user_skill(a, "bitship_tone")
    assert "bitship_tone" not in {item["name"] for item in catalog(a)}


def test_chat_save_and_list_skill_tools():
    uid = 94103
    saved = asyncio.run(
        run_computer_tool(
            "save_skill",
            {
                "name": "weekly_notes",
                "description": "Протокол планёрки по понедельникам",
                "body": "Коротко: решения, кто что делает, без стенограммы.",
                "triggers": "планёрк, понедельник",
            },
            user_id=uid,
        )
    )
    assert "weekly_notes" in saved
    listed = asyncio.run(run_computer_tool("list_skills", {}, user_id=uid))
    assert "weekly_notes" in listed
    assert "custom" in listed
    blocked = asyncio.run(
        run_computer_tool(
            "save_skill",
            {"name": "code", "description": "мой код", "body": "Всегда пиши на Python и проверяй."},
            user_id=uid,
        )
    )
    assert "занято" in blocked
    deleted = asyncio.run(run_computer_tool("delete_skill", {"name": "weekly_notes"}, user_id=uid))
    assert "удалён" in deleted


def test_skills_api_crud_and_builtin_guard():
    app.dependency_overrides[get_current_user] = lambda: "skills-user@example.com"
    try:
        client = TestClient(app)
        listed = client.get("/skills")
        assert listed.status_code == 200, listed.text
        body = listed.json()
        names = {item["name"] for item in body["items"]}
        assert "documents" in names
        assert "legal" in names
        assert body["custom_limit"] == 20
        builtin = next(item for item in body["items"] if item["name"] == "documents")
        assert builtin["origin"] == "builtin"
        assert builtin["body"] == ""
        assert builtin["description"]
        assert builtin["scope"] == "sandbox"
        legal = next(item for item in body["items"] if item["name"] == "legal")
        assert legal["scope"] == "chat"

        created = client.post(
            "/skills",
            json={
                "name": "office_tone",
                "title": "Офисный тон",
                "description": "Письма директору",
                "body": "На вы. Без смайлов. Короткий абзац.",
                "triggers": "директору, служебн",
            },
        )
        assert created.status_code == 200, created.text
        assert created.json()["origin"] == "custom"
        assert created.json()["name"] == "office_tone"
        assert created.json()["scope"] == "chat"

        clash = client.post(
            "/skills",
            json={"name": "deck", "description": "мои слайды", "body": "Всегда тёмная шапка и мало текста."},
        )
        assert clash.status_code == 400

        patched = client.patch("/skills/office_tone", json={"enabled": False})
        assert patched.status_code == 200
        assert patched.json()["enabled"] is False

        deleted = client.delete("/skills/office_tone")
        assert deleted.status_code == 200
        builtin = client.delete("/skills/documents")
        assert builtin.status_code in {403, 404}
    finally:
        app.dependency_overrides.clear()
