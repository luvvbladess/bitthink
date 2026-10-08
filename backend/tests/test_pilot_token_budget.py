import asyncio

from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path
from app.main import app
import director_router as dr
import openai_client
from computer_skills.loader import catalog, catalog_for_prompt, load_skill, match_skills
from conversations import conversation_manager

HEADER = "Пользователь предоставил документ для контекста:"


def _doc(name: str, chars: int, word: str = "договор") -> str:
    body = " ".join(f"{word}{i % 50} пункт {i}." for i in range(chars // 14))
    return f"{HEADER} {name}\n\nСодержание:\n{body}\n\nИспользуй эту информацию при ответе."


def test_trim_documents_keeps_every_file_and_points_to_the_rest():
    ctx = "\n\n".join([_doc("a.docx", 300_000), _doc("b.docx", 300_000)])
    out = dr._trim_documents(ctx, "проверь договор", 20_000)
    assert len(out) < 24_000
    assert "a.docx" in out and "b.docx" in out
    assert out.count("read_chat_document") == 2


def test_trim_documents_leaves_a_small_file_alone():
    ctx = _doc("small.docx", 4_000)
    assert dr._trim_documents(ctx, "что тут", 20_000) == ctx


def test_every_pilot_stage_sends_a_bounded_document(monkeypatch):
    sent: list[tuple[str, int]] = []

    async def fake_chat(messages, **kwargs):
        sent.append((kwargs.get("model", ""), sum(len(m.get("content") or "") for m in messages)))
        return '{"status": "done"}', [], "", []

    monkeypatch.setattr(openai_client, "get_chat_response", fake_chat)
    big = _doc("big.docx", 600_000)
    uid = 97001

    asyncio.run(dr._plan_round("проверь документ", [], uid, big, "история " * 20_000))
    asyncio.run(dr._compose_answer("проверь документ", [], uid, "история " * 20_000, big))
    employee = {"role": "Разбор", "task": "load_skill legal. Проверь договор", "model": "gpt-6-luna"}
    asyncio.run(dr._execute_employee(employee, 1, [], uid, big, "история " * 20_000))

    assert len(sent) == 3
    planner, composer, worker = (size for _, size in sent)
    # Before: each of these carried the full 600k-char file (and 160k of history).
    assert planner < 60_000, planner
    assert composer < 60_000, composer
    assert worker < 100_000, worker


def test_a_file_alone_no_longer_buys_the_expensive_composer():
    journal = [{"status": "ok", "result": "заметки " * 50}]
    doc = _doc("a.docx", 50_000)
    assert dr._select_composer_model("сделай краткое резюме", journal, doc) == dr.ECONOMY_COMPOSER_MODEL
    hard = "проверь договор на риски " + "и условия " * 50
    assert dr._select_composer_model(hard, journal, doc) == dr.QUALITY_COMPOSER_MODEL


def test_compact_catalog_is_much_smaller_and_keeps_custom_skills():
    uid = 97002
    conversation_manager.save_user_skill(
        uid, name="bitship_tone", description="Письма для Биципа", body="Обращение на ты. Коротко. Word."
    )
    full = catalog_for_prompt(uid)
    compact = catalog_for_prompt(uid, compact=True)
    assert len(compact) < len(full) * 0.7
    assert "deck" in compact and "load_skill" in compact
    assert "bitship_tone (ваш): Письма для Биципа" in compact
    conversation_manager.delete_user_skill(uid, "bitship_tone")


def test_planner_named_skill_is_preloaded_without_an_extra_hop():
    assert match_skills("load_skill documents. Собери отчёт.", user_id=97003)[0] == "documents"
    assert "documents" not in match_skills("Привет, как дела", user_id=97003)


def test_switched_off_skill_disappears_everywhere():
    uid = 97004
    assert "deck" in {item["name"] for item in catalog(uid)}
    conversation_manager.set_builtin_skill_enabled(uid, "deck", False)
    try:
        assert "deck" not in {item["name"] for item in catalog(uid)}
        assert "deck" not in match_skills("сделай презентацию на 10 слайдов", user_id=uid)
        assert "deck" not in match_skills("load_skill deck. Слайды", user_id=uid)
        assert "выключен" in load_skill("deck", user_id=uid)
        # Another person is unaffected.
        assert "deck" in {item["name"] for item in catalog(97005)}
    finally:
        conversation_manager.set_builtin_skill_enabled(uid, "deck", True)
    assert "deck" in {item["name"] for item in catalog(uid)}
    assert "выключен" not in load_skill("deck", user_id=uid)


def test_skills_api_switches_a_common_skill():
    app.dependency_overrides[get_current_user] = lambda: "skill-switch@example.com"
    try:
        client = TestClient(app)
        off = client.patch("/skills/legal", json={"enabled": False})
        assert off.status_code == 200, off.text
        assert off.json()["enabled"] is False and off.json()["origin"] == "builtin"
        listed = {item["name"]: item for item in client.get("/skills").json()["items"]}
        assert listed["legal"]["enabled"] is False
        assert listed["documents"]["enabled"] is True
        assert client.patch("/skills/legal", json={"body": "поменять текст"}).status_code == 400
        on = client.patch("/skills/legal", json={"enabled": True})
        assert on.json()["enabled"] is True
    finally:
        app.dependency_overrides.clear()


def test_only_the_first_planning_round_runs_on_the_expensive_model(monkeypatch):
    monkeypatch.setattr(
        conversation_manager, "get_subscription", lambda _uid: {"tier": "proplus"}
    )
    assert dr._clamped_planner_model(1) == "gpt-6-sol"
    assert dr._clamped_planner_model(1, first_round=False) == "gpt-6-luna"


def test_pilot_map_reduces_big_files_far_below_the_generic_threshold():
    from handlers import core
    from model_context import input_budget_tokens

    assert core.PILOT_MAP_REDUCE_TOKENS < input_budget_tokens("director") * 0.72 / 4


def test_light_tasks_skip_the_planner_but_orders_do_not():
    light = [
        "Какая сейчас цена нефти Brent?", "привет", "Что нового в последней версии Android?",
        "Объясни, чем отличается TCP от UDP", "Переведи на английский: добрый день",
    ]
    heavy = [
        "создай приложение", "сделай ПМИ и протокол", "Напиши скрипт на Python для парсинга",
        "Зайди на сайт и скачай отчёт", "Проверь почту", "Подготовь презентацию на 10 слайдов",
        "Какая цена нефти? " + "Подробности. " * 40,
    ]
    for text in light:
        assert dr._is_light_task(text, "", False, 1), text
    for text in heavy:
        assert not dr._is_light_task(text, "", False, 1), text
    assert not dr._is_light_task("Какая цена нефти?", "документ", False, 1)
    assert not dr._is_light_task("Какая цена нефти?", "", True, 1)


def test_expensive_models_are_for_hard_tasks_and_search_goes_to_luna(monkeypatch):
    monkeypatch.setattr(dr, "_employee_models", lambda _uid: ["gpt-5-nano", "gpt-6-luna", "kimi-k2.6", "deepseek-v4-pro", "gpt-6-sol"])
    plan = {"new_employees": [
        {"role": "a", "task": "t", "model": "gpt-6-sol"},
        {"role": "b", "task": "t", "model": "deepseek-v4-pro"},
        {"role": "c", "task": "t", "model": "kimi-k2.6"},
    ]}
    easy = dr._clamp_employee_plan(plan, 1, "Сравни Париж и Рим для поездки", "")["new_employees"]
    assert [e["model"] for e in easy] == ["gpt-6-luna"] * 3
    assert easy[2]["web"] is True and "web" not in easy[0]
    hard = dr._clamp_employee_plan(plan, 1, "Напиши скрипт на Python, который читает CSV", "")["new_employees"]
    assert [e["model"] for e in hard] == ["gpt-6-sol", "deepseek-v4-pro", "gpt-6-luna"]
    with_file = dr._clamp_employee_plan(plan, 1, "Проверь", _doc("a.docx", 5000))["new_employees"]
    assert with_file[0]["model"] == "gpt-6-sol"


def test_planner_runs_on_sol_only_for_complex_first_rounds(monkeypatch):
    monkeypatch.setattr(conversation_manager, "get_subscription", lambda _uid: {"tier": "proplus"})
    assert dr._clamped_planner_model(1, first_round=True, complex_task=True) == "gpt-6-sol"
    assert dr._clamped_planner_model(1, first_round=True, complex_task=False) == "gpt-6-luna"
    assert dr._clamped_planner_model(1, first_round=False, complex_task=True) == "gpt-6-luna"


def test_has_sources_needs_distinct_links():
    entry = {"search": [{"summary": "https://a.ru/x\nt"}, {"summary": "https://a.ru/x\nagain"}, {"summary": "plain note"}]}
    assert not dr._has_sources([entry])
    entry["search"].append({"summary": "https://b.ru/y\nt"})
    assert dr._has_sources([entry])


def test_marketplaces_skill_is_picked_for_shopping_requests_in_every_mode():
    from computer_skills.loader import builtin_names, skill_scope

    assert "marketplaces" in builtin_names() and skill_scope("marketplaces") == "chat"
    asks = [
        "Найди лучшее предложение на iPhone 15 128 ГБ в Москве",
        "где купить PlayStation 5 подешевле по России",
        "сравни цены на кофемашину DeLonghi на озоне и вайлдберриз",
        "подбери товар: наушники с шумоподавлением до 15 тысяч",
    ]
    for text in asks:
        assert "marketplaces" in match_skills(text, user_id=97010, sandbox=False), text
        assert "marketplaces" in match_skills(text, user_id=97010, sandbox=True), text
    assert "marketplaces" not in match_skills("Объясни, как работает кэш в браузере", user_id=97010)
    body = load_skill("marketplaces", user_id=97010)
    assert "Ozon" in body and "Лучший выбор" in body and "н/д" in body


def test_shopping_forces_a_web_search_and_is_not_a_light_task():
    from search_engine import query_requires_web

    assert query_requires_web("Найди лучшее предложение на ноутбук для учёбы")
    assert query_requires_web("где купить дешевле Dyson Airwrap")
    assert not query_requires_web("Объясни, чем отличается TCP от UDP")
    # A shopping request fans out over several stores: it must reach the planner, not the one-searcher shortcut.
    assert not dr._is_light_task("Найди лучшее предложение на iPhone 15 в Москве", "", False, 1)
    assert dr._is_light_task("Какая сейчас цена нефти Brent?", "", False, 1)
