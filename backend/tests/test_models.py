import asyncio
import inspect
from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app
from routing import best_route, computer_requires_web, current_turn_has_files, openai_tool_flags, packed_has_open_documents, turn_requires_web
from search_engine import query_requires_web
import search_engine
from kimi_client import (
    _search_today_note,
    drop_empty_list_items,
    extract_domain_sources,
    kimi_result_is_grounded,
    strip_source_links,
)
from conversations import Message
from db_conversations import (
    DatabaseConversationManager,
    MessageData,
    build_document_contexts,
    pack_chat_history,
    query_needs_documents,
)
from director_router import (
    DIRECT_ANSWER_MODEL,
    PLANNER_MODEL,
    _select_composer_model,
)


def test_public_model_catalog_hides_internal_routes():
    app.dependency_overrides[get_current_user] = lambda: "models-catalog@example.com"
    try:
        response = TestClient(app).get("/models")
        assert response.status_code == 200
        ids = {model["id"] for model in response.json()["models"]}
        assert ids == {"auto", "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-6-astra", "director", "studio"}
        assert "none" in response.json()["reasoningEfforts"]
        assert "deepseek-v4-pro" not in ids
        assert "kimi-k2.6" not in ids
        payload = response.json()
        assert payload["researchModel"] is None
        assert payload["computerAvailable"] is False
        assert payload["studioAvailable"] is False
        assert payload["astraAvailable"] is False
        assert payload["multipliers"]["gpt-5.6-sol"] == 32
        assert payload["multipliers"]["gpt-6-astra"] == 90
    finally:
        app.dependency_overrides.clear()


def test_free_user_cannot_select_locked_expert_model():
    app.dependency_overrides[get_current_user] = lambda: "models-locked@example.com"
    try:
        response = TestClient(app).post("/models/select", json={"model": "gpt-5.6-sol"})
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_best_route_balances_cost_and_complexity_without_router_tokens():
    assert best_route("Привет, как приготовить омлет?", "none", True) == ("deepseek-v4-flash", False)
    assert best_route("Проанализируй архитектуру и сделай ревью кода", "none", True) == ("deepseek-v4-pro", False)
    assert best_route("Объясни тему глубоко", "medium", True) == ("deepseek-v4-pro", True)
    assert best_route("Короткий вопрос", "none", False) == ("gpt-5.6-luna", False)


def test_auto_route_uses_request_volume_not_a_single_analysis_verb():
    simple = "Сравни плюсы и минусы удалённой работы"
    assert best_route(simple, "none", True) == ("deepseek-v4-flash", False)
    assert best_route(simple, "none", False) == ("gpt-5.6-luna", False)

    detailed = "Сравни два подхода. " + ("Учти стоимость, риски, сроки и ограничения команды. " * 24)
    assert best_route(detailed, "none", True) == ("deepseek-v4-pro", False)


def test_computer_orchestrator_is_smart_but_direct_hop_stays_economy():
    # The orchestrator (round planning) drives every hiring/coordination decision
    # in Pilot, so it targets Terra quality by default; a lone reply with no
    # employees hired is still ordinary economy work.
    assert PLANNER_MODEL == "gpt-5.6-terra"
    assert DIRECT_ANSWER_MODEL == "gpt-5.6-luna"


def test_computer_orchestrator_downgrades_gracefully_below_terra_tier(monkeypatch):
    import director_router as dr
    import conversations

    monkeypatch.setattr(
        conversations.conversation_manager, "get_subscription", lambda _uid: {"tier": "pro"}
    )
    assert dr._clamped_planner_model(1) == "gpt-5.6-luna"

    monkeypatch.setattr(
        conversations.conversation_manager, "get_subscription", lambda _uid: {"tier": "proplus"}
    )
    assert dr._clamped_planner_model(1) == "gpt-5.6-terra"


def test_computer_composer_escalates_only_for_heavy_or_document_work():
    small_journal = [{"status": "ok", "result": "Короткий проверенный результат."}]
    assert _select_composer_model("Сравни два тарифа", small_journal) == "gpt-5.6-luna"
    assert _select_composer_model("Проверь договор", small_journal, "Текст документа") == "gpt-5.6-terra"

    large_journal = [
        {"status": "ok", "result": "x" * 3000}
        for _ in range(6)
    ]
    assert _select_composer_model("Собери вывод", large_journal) == "gpt-5.6-terra"
    photo_journal = [
        {"status": "ok", "result": "a"},
        {"status": "ok", "result": "b"},
    ]
    assert _select_composer_model("где снято это фото", photo_journal) == "gpt-5.6-terra"


def test_pilot_hires_astra_only_for_dense_contract_work(monkeypatch):
    import director_router as dr

    monkeypatch.setattr(
        dr,
        "_employee_models",
        lambda _uid: ["gpt-5.6-luna", "gpt-5.6-sol", "gpt-6-astra"],
    )
    assert not dr._task_warrants_astra("сравни три сайта")
    assert not dr._task_warrants_astra("проверь договор")
    assert dr._task_warrants_astra("проверь договор", "пункт " * 80)

    parsed = dr._parse_director_plan(
        '{"status":"continue","new_employees":['
        '{"role":"A","task":"one","model":"gpt-6-astra"},'
        '{"role":"B","task":"two","model":"gpt-6-astra"}'
        "]}"
    )
    assert parsed["new_employees"][0]["model"] == "gpt-6-astra"

    cheap = dr._clamp_employee_plan(parsed, 1, "сравни три сайта")
    assert [item["model"] for item in cheap["new_employees"]] == ["gpt-5.6-sol", "gpt-5.6-sol"]

    heavy = dr._clamp_employee_plan(parsed, 1, "проверь договор", "пункт " * 80)
    assert [item["model"] for item in heavy["new_employees"]] == ["gpt-6-astra", "gpt-5.6-sol"]

    already = [{"model": "gpt-6-astra"}]
    second = dr._clamp_employee_plan(parsed, 1, "проверь договор", "пункт " * 80, already)
    assert all(item["model"] != "gpt-6-astra" for item in second["new_employees"])


def test_pilot_injects_memory_and_custom_prompt_into_planner_employee_and_composer(monkeypatch):
    """Регрессия: раньше _plan_round/_execute_employee/_compose_answer собирали свои
    промпты с нуля и никогда не видели ни память пользователя, ни активный кастомный
    промпт ("как отвечать") — из-за этого Пилот "не помнил" и "не слушался" инструкций,
    даже когда обычный чат с той же памятью работал нормально."""
    import director_router as dr
    import conversations

    monkeypatch.setattr(
        conversations.conversation_manager,
        "get_user_memory",
        lambda _uid: {"enabled": True, "notes": "- Обращайся на «ты»\n- Всегда отвечай таблицей"},
    )
    monkeypatch.setattr(
        conversations.conversation_manager,
        "get_active_custom_prompt",
        lambda _uid: "Всегда отвечай только на английском языке.",
    )

    prefs = dr._preference_context(1)
    assert "на «ты»" in prefs
    assert "таблицей" in prefs
    assert "английском" in prefs

    captured: list[str] = []

    async def fake_get_chat_response(messages, **_kwargs):
        captured.append(messages[-1]["content"])
        return '{"status": "done"}', [], "", []

    monkeypatch.setattr("openai_client.get_chat_response", fake_get_chat_response)
    asyncio.run(dr._plan_round("Сравни два тарифа", [], 1))
    assert any("английском" in text and "таблицей" in text for text in captured)

    captured.clear()

    async def fake_employee_response(messages, **_kwargs):
        captured.append(messages[-1]["content"])
        return "готово", [], "", []

    monkeypatch.setattr("openai_client.get_chat_response", fake_employee_response)
    asyncio.run(
        dr._execute_employee({"role": "Поиск", "task": "найди цену", "model": "gpt-5.6-luna"}, 1, [], 1)
    )
    assert any("английском" in text and "буквально" in text for text in captured)

    captured.clear()

    async def fake_compose_response(messages, **_kwargs):
        captured.append(messages[-1]["content"])
        return "ответ", [], "", []

    monkeypatch.setattr("openai_client.get_chat_response", fake_compose_response)
    asyncio.run(
        dr._compose_answer(
            "Сравни два тарифа",
            [{"round": 1, "role": "Поиск", "task": "найди цену", "model": "gpt-5.6-luna", "status": "ok", "result": "$10"}],
            1,
        )
    )
    assert any("английском" in text and "буквально" in text for text in captured)


def test_pilot_planner_employee_and_composer_see_chat_history(monkeypatch):
    """История передаётся строкой history_text во все три этапа Пилота, не
    только текущий вопрос без контекста прошлых сообщений."""
    import director_router as dr

    history_text = "Пользователь: МАРКЕР_ИСТОРИИ – всегда считай сроки в неделях, не в днях."
    captured: list[str] = []

    async def fake_get_chat_response(messages, **_kwargs):
        captured.append(messages[-1]["content"])
        return '{"status": "done"}', [], "", []

    monkeypatch.setattr("openai_client.get_chat_response", fake_get_chat_response)
    asyncio.run(dr._plan_round("посчитай стоимость", [], 1, history_text=history_text))
    assert any("МАРКЕР_ИСТОРИИ" in text for text in captured)

    captured.clear()

    async def fake_employee_response(messages, **_kwargs):
        captured.append(messages[-1]["content"])
        return "готово", [], "", []

    monkeypatch.setattr("openai_client.get_chat_response", fake_employee_response)
    asyncio.run(
        dr._execute_employee(
            {"role": "Расчёт", "task": "посчитай стоимость", "model": "gpt-5.6-luna"},
            1,
            [],
            1,
            history_text=history_text,
        )
    )
    assert any("МАРКЕР_ИСТОРИИ" in text for text in captured)

    captured.clear()

    async def fake_compose_response(messages, **_kwargs):
        captured.append(messages[-1]["content"])
        return "ответ", [], "", []

    monkeypatch.setattr("openai_client.get_chat_response", fake_compose_response)
    asyncio.run(
        dr._compose_answer(
            "посчитай стоимость",
            [
                {
                    "round": 1,
                    "role": "Расчёт",
                    "task": "посчитай стоимость",
                    "model": "gpt-5.6-luna",
                    "status": "ok",
                    "result": "1000",
                }
            ],
            1,
            history_text=history_text,
        )
    )
    assert any("МАРКЕР_ИСТОРИИ" in text for text in captured)


def test_director_builds_history_once_and_reuses_it_across_rounds(monkeypatch):
    """_run_director считает историю один раз (_format_chat_history) и прокидывает
    ту же строку планировщику, каждому сотруднику и сборщику ответа — без этого
    Пилот теряет контекст прошлых сообщений уже со второго раунда."""
    import director_router as dr

    seen: list[tuple[str, str]] = []

    async def fake_plan(_task, journal, _user_id, document_context="", history_text=""):
        seen.append(("plan", history_text))
        if journal:
            return {"status": "done", "new_employees": []}
        return {
            "status": "continue",
            "new_employees": [{"role": "A", "task": "t", "model": "gpt-5.6-luna"}],
        }

    async def fake_exec(employee, round_num, journal, user_id, document_context="", history_text="", has_images=False):
        seen.append(("exec", history_text))
        return {
            "round": round_num,
            "role": employee["role"],
            "task": employee["task"],
            "model": employee["model"],
            "status": "ok",
            "result": "ok",
            "reasoning": "",
            "search": [],
        }

    async def fake_compose(_task, _journal, _user_id, history_text="", document_context=""):
        seen.append(("compose", history_text))
        return "ответ", ""

    async def fake_status(*_args, **_kwargs):
        return None

    monkeypatch.setattr(dr, "_plan_round", fake_plan)
    monkeypatch.setattr(dr, "_execute_employee", fake_exec)
    monkeypatch.setattr(dr, "_compose_answer", fake_compose)
    monkeypatch.setattr(dr, "_update_status", fake_status)
    monkeypatch.setattr(dr, "_sanitize_answer", lambda text: text)

    messages = [
        {"role": "user", "content": "МАРКЕР_ИСТОРИИ: делай всё в фунтах, не в долларах"},
        {"role": "assistant", "content": "Хорошо, буду считать в фунтах."},
    ]
    messages += [{"role": "user", "content": f"вопрос {i}"} for i in range(3)]
    messages.append({"role": "user", "content": "посчитай стоимость проекта"})

    answer, files, _reasoning, _search = asyncio.run(
        dr.get_director_response(messages, "посчитай стоимость проекта", 1, None)
    )
    assert answer == "ответ"
    assert files == []
    assert seen, "история ни разу не дошла до раундов"
    assert all("МАРКЕР_ИСТОРИИ" in text for _stage, text in seen)
    assert {stage for stage, _ in seen} == {"plan", "exec", "compose"}


def test_reduce_heavy_context_summarizes_document_but_keeps_question_and_memory(monkeypatch):
    """Map-Reduce (reduce_heavy_context) должен ужимать только тяжёлый документ.
    Текущий вопрос пользователя и память/кастомный промпт (лёгкие system-сообщения)
    обязаны пережить сжатие целиком — это тот путь, который срабатывает раньше
    выбора режима (auto/director/kimi/...), так что баг здесь бьёт по всем режимам сразу."""
    import asyncio
    from handlers.core import reduce_heavy_context

    seen_chunks: list[str] = []

    async def fake_get_chat_response(map_prompt, **_kwargs):
        chunk_text = map_prompt[-1]["content"]
        seen_chunks.append(chunk_text)
        assert "MARKER_DOC_FACT" in chunk_text
        return "СЖАТЫЙ_ФАКТ_ИЗ_ДОКУМЕНТА", [], "", []

    monkeypatch.setattr("handlers.core.get_chat_response", fake_get_chat_response)

    heavy_doc = {
        "role": "system",
        "content": (
            "Пользователь предоставил документ для контекста: big.pdf\n\nСодержание:\n"
            + ("MARKER_DOC_FACT. " * 40_000)
        ),
    }
    memory_msg = {
        "role": "system",
        "content": "Устойчивые предпочтения человека из прошлых разговоров.\n\n- Отвечай кратко",
    }
    user_text = "МАРКЕР_ТЕКУЩЕГО_ВОПРОСА: подытожь документ"
    user_msg = {"role": "user", "content": user_text}
    messages = [heavy_doc, memory_msg, user_msg]

    result = asyncio.run(
        reduce_heavy_context(messages, user_text, None, user_id=1, model="kimi-k2.6")
    )

    assert seen_chunks, "Map-Reduce ни разу не вызвался — порог не был достигнут тестовыми данными"
    joined_system = "\n".join(str(m.get("content")) for m in result if m.get("role") == "system")
    assert "СЖАТЫЙ_ФАКТ_ИЗ_ДОКУМЕНТА" in joined_system
    assert "Отвечай кратко" in joined_system
    assert any(
        m.get("role") == "user" and "МАРКЕР_ТЕКУЩЕГО_ВОПРОСА" in str(m.get("content"))
        for m in result
    )


def test_runtime_context_use_skills_false_skips_autoload(monkeypatch):
    """Регрессия: без use_skills=False внутренние служебные вызовы (JSON-план
    Пилота, сборка финального ответа, Map-Reduce по документам) подмешивали
    случайный скил, подобранный по ключевым словам их СОБСТВЕННОГО шаблонного
    текста (а не реального вопроса человека), да ещё с инструкциями звать
    инструменты, которых у этих вызовов вообще нет (use_tools=False)."""
    from runtime_context import with_runtime_context

    # This is exactly the kind of boilerplate _plan_round sends as the "user"
    # message: full of keyword triggers ("сравни", "договор", "фото"...) that
    # have nothing to do with what the human actually asked.
    boilerplate_prompt = (
        "Ты Computer: оркестратор... Доступные модели: gpt-6-astra — самая дорогая, "
        "только разбор договора или аудита. Сравни варианты и реши, кого нанять."
    )
    messages = [
        {"role": "system", "content": "Ты Computer - оркестратор команды моделей."},
        {"role": "user", "content": boilerplate_prompt},
    ]

    with_skills = with_runtime_context(messages, use_skills=True, sandbox=False)
    without_skills = with_runtime_context(messages, use_skills=False, sandbox=False)

    assert len(without_skills) == len(messages) + 1  # only the date note
    assert len(with_skills) > len(without_skills)  # confirms the boilerplate DID spuriously match a skill


def test_director_service_calls_disable_skill_autoload():
    """_plan_round и _compose_answer шлют свой собственный шаблонный текст как
    user-сообщение — они обязаны звать get_chat_response с use_skills=False,
    иначе runtime_context подберёт скил по случайным словам шаблона."""
    import inspect
    import director_router as dr

    plan_source = inspect.getsource(dr._plan_round)
    assert "use_skills=False" in plan_source

    compose_source = inspect.getsource(dr._compose_answer)
    assert "use_skills=False" in compose_source

    # _answer_directly and _execute_employee are real single-hop/agent turns with
    # the actual user text (or an already explicitly preloaded skill) - they must
    # keep the default autoload behaviour.
    direct_source = inspect.getsource(dr._answer_directly)
    assert "use_skills=False" not in direct_source


def test_map_reduce_summarizer_disables_skill_autoload():
    """Суммаризация кусков документа в Map-Reduce тоже должна отключать
    автоподбор скилов: это служебный вызов без инструментов, а не реальный ход."""
    import inspect
    from handlers import core as handlers_core

    source = inspect.getsource(handlers_core.reduce_heavy_context)
    assert "use_skills=False" in source


def test_astra_falls_back_when_api_model_is_missing():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "bot_core" / "openai_client.py").read_text(encoding="utf-8")
    assert "def _astra_unavailable" in source
    assert 'requested == "gpt-6-astra" and _astra_unavailable' in source
    assert 'model="gpt-5.6-sol"' in source
    assert "model_not_found" in source


def test_astra_is_sandbox_agent_not_web_only_chat():
    from config import ASTRA_AGENT_PROMPT
    from pathlib import Path

    assert openai_tool_flags("gpt-6-astra", False) == (True, False)
    assert openai_tool_flags("gpt-6-astra", True) == (True, False)
    assert openai_tool_flags("gpt-5.6-luna", True) == (True, True)
    assert openai_tool_flags("gpt-5.6-luna", False) == (False, False)
    assert "песочниц" in ASTRA_AGENT_PROMPT

    client = (Path(__file__).resolve().parents[1] / "app" / "bot_core" / "openai_client.py").read_text(encoding="utf-8")
    assert "if image_base64 and not is_astra" in client
    assert "max_loops = 12 if is_astra else 6" in client
    assert "force_web = bool(force_web_search and not is_astra)" in client
    assert "COMPUTER_TOOLS_RESPONSES" in client
    assert "_with_astra_agent_prompt" in client
    assert 'if effort in {"", "none"}:' in client
    assert 'if model == "gpt-6-astra":\n        return {"effort": "high"}' in client.replace("\r\n", "\n")


def test_computer_searches_by_default_but_skips_private_service_actions():
    assert computer_requires_web("Помоги продумать архитектуру кадрового сервиса")
    assert computer_requires_web("Сравни сервисы для автоматизации зарплаты")
    assert not computer_requires_web("Проверь мои непрочитанные письма")
    assert not computer_requires_web("Выполни команду на VPS и покажи свободный диск")


def test_attachments_skip_forced_web_in_auto_not_search_modes():
    question = "Проанализируй прикреплённые файлы."
    assert not turn_requires_web(question, "auto", has_documents=True)
    assert not turn_requires_web(question, "auto", has_images=True)
    assert not turn_requires_web(question, "studio", has_images=True)
    assert turn_requires_web(question, "kimi-k2.6", has_documents=True)
    assert turn_requires_web(question, "kimi-k2.6", has_images=True)
    assert turn_requires_web(question, "gpt-5.6-sol", research_mode=True, has_images=True)
    assert turn_requires_web(question, "gpt-5.6-terra", research_mode=True, has_documents=True)
    assert turn_requires_web("загугли курс доллара", "auto", has_documents=True)
    assert turn_requires_web("что нового", "kimi-k2.6")
    assert turn_requires_web("сделай обзор рынка", "gpt-5.6-sol", research_mode=True)
    assert turn_requires_web("зайди на сайт компании", "director")
    assert turn_requires_web("Проанализируй прикреплённые файлы.", "director", has_documents=True)
    assert turn_requires_web("сравни сервисы для отчёта", "director", has_images=True)


def test_leftover_files_do_not_count_as_current_turn_uploads():
    history = [
        {"role": "user", "content": "фото", "attachment": {"type": "image", "url": "/uploads/a.png"}},
        {"role": "assistant", "content": "Вижу кота."},
        {"role": "user", "content": "что нового по курсу доллара"},
    ]
    has_documents, has_images = current_turn_has_files(history)
    assert not has_documents
    assert not has_images
    fresh = [
        {"role": "assistant", "content": "Готово."},
        {"role": "user", "content": "file.pdf", "attachment": {"type": "document", "name": "file.pdf"}},
        {"role": "user", "content": "разбери документ"},
    ]
    has_documents, has_images = current_turn_has_files(fresh)
    assert has_documents
    assert not has_images


def test_open_document_bodies_count_even_when_upload_was_earlier():
    catalog = {
        "role": "system",
        "content": "Пользователь предоставил документ для контекста: old.pdf\n\nСодержание:\nФайл уже в этом чате. Полный текст не подмешан в этот ход.",
    }
    body = {
        "role": "system",
        "content": "Пользователь предоставил документ для контекста: invoice.pdf\n\nСодержание:\nСУММА 12000",
    }
    assert not packed_has_open_documents([catalog, {"role": "user", "content": "курс доллара"}])
    assert packed_has_open_documents([body, {"role": "user", "content": "Проверь"}])


def test_search_mode_sends_kimi_a_short_hop_not_full_docs():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "bot_core" / "handlers" / "core.py").read_text(encoding="utf-8")
    kimi_block = source.split('elif model == "kimi-k2.6":', 1)[1].split("elif model", 1)[0]
    assert "search_hop_messages" in kimi_block
    assert "force_web_search=web_required" in source
    director_block = source.split('elif model == "director":', 1)[1].split('elif model == "studio":', 1)[0]
    assert "get_director_response" in director_block
    assert "kimi_web_result" not in director_block
    assert "force_web_search=True" not in director_block
    astra_block = source.split('elif model == "gpt-6-astra":', 1)[1].split("else:", 1)[0]
    assert "use_tools=True" in astra_block
    assert "force_web_search=False" in astra_block
    assert "get_director_response" not in astra_block


def test_explicit_and_volatile_queries_require_web_search():
    assert query_requires_web("загугли самые популярные часы Casio и напиши рейтинг")
    assert query_requires_web("Какая сейчас цена биткоина?")
    assert query_requires_web("Последние новости OpenAI")
    assert query_requires_web(
        "соориентируй по самым крутым мэйн дамагерам в вузеринг вэйвс на данный момент"
    )
    assert query_requires_web("кто в мете в Wuthering Waves")
    assert query_requires_web("What's currently the best main DPS")
    assert turn_requires_web(
        "соориентируй по самым крутым мэйн дамагерам в вузеринг вэйвс на данный момент",
        "auto",
    )
    assert not query_requires_web("Объясни рекурсию на простом примере")
    assert not query_requires_web("Привет, как дела?")
    assert not query_requires_web("Как работает текущий указатель в C")
    assert str(datetime.now().year) in _search_today_note()


def test_openai_search_fallback_forces_tool_and_parses_all_source_shapes(monkeypatch):
    captured = {}
    response = SimpleNamespace(output=[
        SimpleNamespace(
            type="web_search_call",
            results=[SimpleNamespace(title="Object result", url="https://example.com/object", snippet="fresh")],
            action=SimpleNamespace(sources=[{"title": "Action source", "url": "https://example.com/action"}]),
        ),
        SimpleNamespace(
            type="message",
            content=[SimpleNamespace(annotations=[
                SimpleNamespace(type="url_citation", title="Citation", url="https://example.com/citation")
            ])],
        ),
    ])

    class FakeResponses:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return response

    class FakeClient:
        def __init__(self, **_kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr(search_engine, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(search_engine, "AsyncOpenAI", FakeClient)
    sources = asyncio.run(search_engine._search_openai_sources("актуальный рейтинг", 6))

    assert captured["tool_choice"] == "required"
    assert {source["url"] for source in sources} == {
        "https://example.com/object",
        "https://example.com/action",
        "https://example.com/citation",
    }


def test_prompt_style_source_lines_are_removed_from_answer():
    raw = """Факт подтверждён.

*Источник: [Example](https://example.com/review)*
*Источник: [Second](https://second.example/news)*
"""
    cleaned = strip_source_links(raw)
    assert cleaned == "Факт подтверждён."
    assert "Источник" not in cleaned
    assert "http" not in cleaned


def test_source_urls_and_inline_citation_numbers_are_removed_from_answer():
    raw = """Факт подтверждён [1]. Смотрите [обзор](https://example.com/review).

## Источники
[1] Example — https://example.com/review
[2] Second — https://second.example/news
"""
    cleaned = strip_source_links(raw)
    assert "Факт подтверждён." in cleaned
    assert "[1]" not in cleaned
    assert "обзор" in cleaned
    assert "http" not in cleaned
    assert "Источники" not in cleaned


def test_domain_citations_and_plain_source_footer_move_out_of_answer():
    raw = "Модель выпускается с 1989 года. (casio.com)\n\nИсточники: официальный каталог Casio. (casio.com)"
    cleaned = strip_source_links(raw)
    assert cleaned == "Модель выпускается с 1989 года."


def test_punycode_and_foreign_script_citation_artifacts_are_stripped():
    raw = (
        "Нужна лицензия (xn----7sbrkkdieeibji5b1g.xn--p1ai). "
        "Это касается перевозки.էական"
    )
    cleaned = strip_source_links(raw)
    assert "xn--" not in cleaned
    assert "էական" not in cleaned
    assert "лицензия" in cleaned
    assert "перевозки" in cleaned
    sources = extract_domain_sources(raw)
    assert any("xn--" in (item["summary"] + item["query"]) for item in sources)


def test_stripped_source_list_does_not_leave_empty_bullets():
    raw = """Самый вероятный порядок:

1. Нажмите Fn.
2. Перезагрузите ноутбук.

- https://asus.com/one
- (asus.com)
- [3]
• [4]
"""
    cleaned = strip_source_links(raw)
    assert "asus.com" not in cleaned
    assert "[3]" not in cleaned
    assert not any(line.strip() in {"-", "*", "•"} for line in cleaned.splitlines())
    assert "Перезагрузите ноутбук." in cleaned
    assert drop_empty_list_items("7. Готово.\n\n-\n-\n•\n8.\n") == "7. Готово."


def test_kimi_result_must_have_real_answer_and_multiple_sources():
    answer = "Проверенный результат поиска. " * 8
    sources = [
        {"query": "One", "summary": "https://one.example"},
        {"query": "Two", "summary": "https://two.example"},
    ]
    assert kimi_result_is_grounded(answer, sources)
    assert not kimi_result_is_grounded("❌ Ошибка API", sources)
    assert not kimi_result_is_grounded(answer, sources[:1])


def test_shared_search_uses_kimi_before_openai_and_never_calls_ddg(monkeypatch):
    calls = []

    async def fake_kimi(_query, _max_results):
        calls.append("kimi")
        return [
            {"title": "Casio рейтинг 2026", "url": "https://one.example/casio", "snippet": ""},
            {"title": "Популярные Casio", "url": "https://two.example/casio", "snippet": ""},
        ]

    async def forbidden_ddg(*_args):
        raise AssertionError("DDG must not be used")

    async def fake_openai(*_args):
        calls.append("openai")
        return []

    monkeypatch.setattr(search_engine, "_search_kimi_sources", fake_kimi)
    monkeypatch.setattr(search_engine, "_search_ddg", forbidden_ddg)
    monkeypatch.setattr(search_engine, "_search_openai_sources", fake_openai)
    sources = asyncio.run(search_engine.search_web("рейтинг популярных Casio 2026"))

    assert len(sources) == 2
    assert calls == ["kimi"]


def test_message_serialization_persists_structured_sources():
    sources = [{"query": "Casio", "summary": "https://casio.com"}]
    restored = Message(**Message(role="assistant", content="Ответ", search=sources).to_dict())
    assert restored.search == sources


def test_production_conversation_manager_accepts_structured_sources():
    assert "search" in inspect.signature(DatabaseConversationManager.add_message).parameters
    sources = [{"query": "Casio", "summary": "https://casio.com"}]
    assert MessageData(role="assistant", content="Ответ", search=sources).to_dict()["search"] == sources


def test_unrelated_question_keeps_file_catalog_not_bodies():
    documents = [
        {"filename": "one.txt", "content": "A" * 20_000},
        {"filename": "two.txt", "content": "B" * 30_000},
    ]
    packed = build_document_contexts(documents, "какой сейчас курс доллара", max_chars=60_000)
    assert [item["filename"] for item in packed] == ["one.txt", "two.txt"]
    assert all(len(item["content"]) < 400 for item in packed)
    assert all("не подмешан" in item["content"] for item in packed)


def test_check_verb_opens_leftover_document_bodies():
    packed = build_document_contexts(
        [{"filename": "invoice.pdf", "content": "СУММА 12000"}],
        "Китайские производители прислали обновленные файлы. Проверь",
        max_chars=20_000,
    )
    assert packed[0]["content"] == "СУММА 12000"
    assert "не подмешан" not in packed[0]["content"]


def test_bare_check_does_not_open_leftover_bodies():
    packed = build_document_contexts(
        [{"filename": "invoice.pdf", "content": "СУММА 12000"}],
        "Проверь что прислали после корректировок",
        max_chars=20_000,
    )
    assert "не подмешан" in packed[0]["content"]
    assert packed[0]["content"] != "СУММА 12000"


def test_web_followup_does_not_inherit_previous_file_question():
    packed = build_document_contexts(
        [{"filename": "invoice.pdf", "content": "СУММА 12000"}],
        "какой сейчас курс доллара",
        max_chars=20_000,
    )
    assert "не подмешан" in packed[0]["content"]
    assert not query_needs_documents("что в новостях про python")
    assert not query_needs_documents("посмотри сравни сервисы")


def test_named_file_opens_only_that_document():
    documents = [
        {"filename": "python.pdf", "content": "PYTHON_BODY"},
        {"filename": "invoice.pdf", "content": "INVOICE_BODY"},
    ]
    packed = build_document_contexts(documents, "новости про python", max_chars=20_000)
    by_name = {item["filename"]: item["content"] for item in packed}
    assert by_name["python.pdf"] == "PYTHON_BODY"
    assert "не подмешан" in by_name["invoice.pdf"]
    packed_act = build_document_contexts(
        [{"filename": "акт.pdf", "content": "АКТ_ТЕКСТ"}],
        "актуально ли это",
        max_chars=20_000,
    )
    assert "не подмешан" in packed_act[0]["content"]


def test_catalog_tells_model_not_to_ask_for_resend():
    packed = build_document_contexts(
        [{"filename": "invoice.pdf", "content": "A" * 8_000}],
        "какой сейчас курс доллара",
        max_chars=20_000,
    )
    text = packed[0]["content"].lower()
    assert "не подмешан" in packed[0]["content"]
    assert "не проси" in text
    assert "уже" in text


def test_file_question_opens_document_bodies():
    documents = [
        {"filename": "one.txt", "content": "A" * 20_000},
        {"filename": "two.txt", "content": "B" * 30_000},
    ]
    packed = build_document_contexts(documents, "проанализируй документ one.txt", max_chars=60_000)
    bodies = {item["filename"]: item["content"] for item in packed}
    assert bodies["one.txt"] == "A" * 20_000
    assert "не подмешан" not in bodies["one.txt"]


def test_forced_filename_opens_even_without_file_words():
    documents = [
        {"filename": "report.pdf", "content": "секретный пункт договора"},
        {"filename": "other.txt", "content": "B" * 8_000},
    ]
    packed = build_document_contexts(
        documents, "продолжи", max_chars=20_000, force_filenames={"report.pdf"}
    )
    by_name = {item["filename"]: item["content"] for item in packed}
    assert "секретный пункт договора" in by_name["report.pdf"]
    assert "не подмешан" in by_name["other.txt"]


def test_large_document_collection_is_bounded_and_query_relevant():
    documents = [
        {"filename": "one.txt", "content": "Введение. " * 900 + "УНИКАЛЬНЫЙ_РИСК договора " * 300},
        {"filename": "two.txt", "content": "Описание. " * 900 + "УНИКАЛЬНЫЙ_РИСК проекта " * 300},
    ]
    packed = build_document_contexts(documents, "найди уникальный риск", max_chars=18_000)
    assert [document["filename"] for document in packed] == ["one.txt", "two.txt"]
    assert sum(len(document["content"]) for document in packed) <= 18_000
    assert all("УНИКАЛЬНЫЙ_РИСК" in document["content"] for document in packed)


def test_holistic_large_document_query_samples_the_whole_file():
    content = "НАЧАЛО\n" + ("a" * 14_000) + "\nСЕРЕДИНА\n" + ("b" * 14_000) + "\nКОНЕЦ"
    packed = build_document_contexts(
        [{"filename": "large.txt", "content": content}],
        "проверь документ целиком",
        max_chars=18_000,
    )[0]["content"]
    assert "НАЧАЛО" in packed
    assert "СЕРЕДИНА" in packed
    assert "КОНЕЦ" in packed


def test_model_history_keeps_file_name_without_attachment_payload():
    history = [
        MessageData(role="user", content="invoice.pdf", attachment={"name": "invoice.pdf", "type": "document"}),
        MessageData(role="assistant", content="x" * 5_000),
        MessageData(role="user", content="последний вопрос"),
    ]
    packed = pack_chat_history(history, max_chars=6_000)
    assert any("invoice.pdf" in (message.content or "") for message in packed)
    assert any(message.content.endswith("последний вопрос") for message in packed)
    assert all(message.attachment is None for message in packed)
    assert sum(len(message.content or "") for message in packed) <= 6_000


def test_smart_memory_recalls_relevant_old_question_and_answer():
    history = [
        MessageData(role="user", content="Кодовое название проекта АЛЬБАТРОС"),
        MessageData(role="assistant", content="Проект АЛЬБАТРОС запускается в ноябре."),
    ]
    history.extend(
        MessageData(role="user" if index % 2 == 0 else "assistant", content=("обычный разговор " * 30) + str(index))
        for index in range(20)
    )

    packed = pack_chat_history(
        history,
        query="Когда запускается Альбатрос?",
        max_chars=4_000,
        recent_chars=2_000,
    )
    contents = [message.content for message in packed]
    assert any("Кодовое название" in content for content in contents)
    assert any("запускается в ноябре" in content for content in contents)
    assert contents[-1].endswith("19")
    assert sum(len(content) for content in contents) <= 4_000


def test_smart_memory_does_not_fill_context_with_unrelated_old_messages():
    full_old = "старое нерелевантное сообщение " * 100
    history = [MessageData(role="user", content=full_old)]
    history.extend(MessageData(role="assistant", content="свежий контекст " * 100) for _ in range(3))
    packed = pack_chat_history(history, query="совсем другая тема", max_chars=3_000, recent_chars=3_000)
    assert not any(full_old in (message.content or "") for message in packed)
    assert any("свежий контекст" in message.content for message in packed)
    assert sum(len(message.content or "") for message in packed) <= 3_000


def test_each_mode_has_one_shared_context_window():
    from model_context import input_budget_tokens, packing_char_budgets, packing_mode_id, window_for

    assert window_for("gpt-5-nano").context == 400_000
    assert window_for("gpt-5.6-luna").context == 1_050_000
    assert window_for("gpt-5.6-terra").context == 1_050_000
    assert window_for("gpt-5.6-sol").context == 1_050_000
    assert window_for("gpt-6-astra").context == 1_050_000
    assert window_for("kimi-k2.6").context == 262_144
    assert window_for("deepseek-v4-pro").context == 1_048_576
    assert packing_mode_id("auto") == "auto"
    assert packing_mode_id("director") == "director"
    assert packing_mode_id("kimi-k2.6") == "kimi-k2.6"

    mixed = ["auto", "director", "correspondent", "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-6-astra"]
    assert {window_for(mode).context for mode in mixed} == {1_050_000}
    assert len({packing_char_budgets(mode) for mode in mixed}) == 1

    luna_docs, luna_history, _ = packing_char_budgets("auto")
    kimi_docs, kimi_history, _ = packing_char_budgets("kimi-k2.6")
    assert luna_history > 200_000
    assert luna_docs > 100_000
    assert kimi_history < luna_history
    assert input_budget_tokens("kimi-k2.6") < input_budget_tokens("auto")


def test_search_hop_does_not_inherit_mode_window():
    from model_context import search_hop_messages

    huge_doc = {"role": "system", "content": "Пользователь предоставил документ для контекста: x\n" + ("А" * 50_000)}
    history = [
        huge_doc,
        {"role": "user", "content": "старый вопрос"},
        {"role": "assistant", "content": "старый ответ"},
        {"role": "user", "content": "что сейчас в новостях про python?"},
    ]
    hop = search_hop_messages(history, "что сейчас в новостях про python?")
    joined = "\n".join(str(item.get("content") or "") for item in hop)
    assert "А" * 100 not in joined
    assert "уже загружены файлы: x" in joined
    assert "Не проси пользователя прислать" in joined
    assert hop[-1]["role"] == "user"
    assert "python" in hop[-1]["content"]
    assert sum(len(str(item.get("content") or "")) for item in hop) < 20_000


def test_fit_messages_keeps_latest_image_and_compacts_older_turns():
    from model_context import MEMORY_LABEL, estimate_messages_tokens, fit_messages_to_model

    encoded = "aaaa"
    older = [{"role": "user" if index % 2 == 0 else "assistant", "content": ("блок истории " * 800) + str(index)} for index in range(120)]
    latest = {
        "role": "user",
        "content": [
            {"type": "text", "text": "А здесь что выбрать?"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
        ],
    }
    messages = [{"role": "system", "content": "Ты ассистент."}, *older, latest]
    fitted = fit_messages_to_model(messages, "kimi-k2.6")
    assert fitted[-1] is latest or fitted[-1]["content"] == latest["content"]
    assert any(
        isinstance(part, dict) and part.get("type") == "image_url"
        for part in fitted[-1]["content"]
    )
    assert estimate_messages_tokens(fitted) < estimate_messages_tokens(messages)
    assert any(MEMORY_LABEL in str(message.get("content", "")) for message in fitted)


def test_dialogue_soft_compact_keeps_document_system():
    from model_context import MEMORY_LABEL, compact_dialogue_tail, estimate_messages_tokens

    doc = {"role": "system", "content": "Пользователь предоставил документ для контекста\n" + ("D" * 80_000)}
    dialogue = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": ("ход разговора " * 500) + str(index)}
        for index in range(40)
    ]
    fitted = compact_dialogue_tail([doc, *dialogue])
    systems = [message for message in fitted if message.get("role") == "system"]
    chat = [message for message in fitted if message.get("role") != "system"]
    assert any("документ для контекста" in str(message.get("content")) and len(str(message.get("content"))) > 40_000 for message in systems)
    assert len(chat) <= 36
    assert any(MEMORY_LABEL in str(message.get("content", "")) for message in systems)
    assert estimate_messages_tokens(chat) < estimate_messages_tokens(dialogue)


def test_director_plan_keeps_parallel_employees():
    from director_router import MAX_PARALLEL_PER_ROUND, _enforce_caps, _parse_director_plan

    plan = _parse_director_plan(
        '{"status":"continue","new_employees":['
        '{"role":"A","task":"one","model":"gpt-5.6-luna"},'
        '{"role":"B","task":"two","model":"kimi-k2.6"},'
        '{"role":"C","task":"three","model":"gpt-5.6-luna"}'
        "]}"
    )
    assert plan["status"] == "continue"
    assert len(plan["new_employees"]) == 3
    crowded = {
        "status": "continue",
        "new_employees": plan["new_employees"]
        + [
            {"role": "D", "task": "four", "model": "gpt-5.6-luna"},
            {"role": "E", "task": "five", "model": "gpt-5.6-luna"},
        ],
    }
    assert len(_enforce_caps(1, 0, crowded)["new_employees"]) == MAX_PARALLEL_PER_ROUND


def test_computer_planner_asks_for_parallel_hires():
    import director_router as dr

    source = inspect.getsource(dr._plan_round)
    assert "ОДНОВРЕМЕННО" in source
    assert "параллельно" in source
    assert "2-" in source
    assert "image_search" in source
    assert "исследователь" in source.lower()
    assert "Простой вопрос без внешних действий" not in source
    assert "status=clarify" in source or '"clarify"' in source
    assert "gpt-6-astra" in inspect.getsource(dr._pool_description)
    assert "не больше одного" in inspect.getsource(dr._plan_round)


def test_computer_round_runs_employees_in_parallel(monkeypatch):
    import director_router as dr

    running = 0
    peak = 0

    async def fake_plan(_task, journal, _user_id, document_context="", history_text=""):
        if journal:
            return {"status": "done", "new_employees": []}
        return {
            "status": "continue",
            "new_employees": [
                {"role": "A", "task": "t1", "model": "gpt-5.6-luna"},
                {"role": "B", "task": "t2", "model": "gpt-5.6-luna"},
                {"role": "C", "task": "t3", "model": "kimi-k2.6"},
            ],
        }

    async def fake_exec(employee, round_num, journal, user_id, document_context="", history_text="", has_images=False):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return {
            "round": round_num,
            "role": employee["role"],
            "task": employee["task"],
            "model": employee["model"],
            "status": "ok",
            "result": "готово",
            "reasoning": "",
            "search": [],
        }

    async def fake_compose(*_args, **_kwargs):
        return "ответ", ""

    async def fake_status(*_args, **_kwargs):
        return None

    monkeypatch.setattr(dr, "_plan_round", fake_plan)
    monkeypatch.setattr(dr, "_execute_employee", fake_exec)
    monkeypatch.setattr(dr, "_compose_answer", fake_compose)
    monkeypatch.setattr(dr, "_update_status", fake_status)
    monkeypatch.setattr(dr, "_sanitize_answer", lambda text: text)

    answer, files, _reasoning, _search = asyncio.run(
        dr.get_director_response(
            [{"role": "user", "content": "сравни три сайта"}],
            "сравни три сайта",
            1,
            None,
        )
    )
    assert peak == 3
    assert answer == "ответ"
    assert files == []


def test_director_forces_image_search_when_planner_skips_a_photo_task(monkeypatch):
    import director_router as dr

    hired = []

    async def fake_plan(_task, journal, _user_id, document_context="", history_text=""):
        return {"status": "done", "new_employees": []}

    async def fake_exec(employee, round_num, journal, user_id, document_context="", history_text="", has_images=False):
        hired.append(employee["role"])
        return {
            "round": round_num,
            "role": employee["role"],
            "task": employee["task"],
            "model": employee["model"],
            "status": "ok",
            "result": "совпадение: Парк Победы",
            "reasoning": "",
            "search": [],
        }

    async def fake_compose(*_args, **_kwargs):
        return "Парк Победы", ""

    async def fake_status(*_args, **_kwargs):
        return None

    monkeypatch.setattr(dr, "_plan_round", fake_plan)
    monkeypatch.setattr(dr, "_execute_employee", fake_exec)
    monkeypatch.setattr(dr, "_compose_answer", fake_compose)
    monkeypatch.setattr(dr, "_update_status", fake_status)
    monkeypatch.setattr(dr, "_sanitize_answer", lambda text: text)
    monkeypatch.setattr(dr, "_turn_has_images", lambda _uid: True)

    answer, _files, _reasoning, _search = asyncio.run(
        dr.get_director_response(
            [{"role": "user", "content": "найди где снято это фото"}],
            "найди где снято это фото",
            1,
            None,
        )
    )
    assert hired == ["Поиск по фото", "Сверка"]
    assert answer == "Парк Победы"
    assert dr.MAX_ROUNDS >= 5
    assert dr.MAX_EMPLOYEES >= 12


def test_status_feed_keeps_distinct_parallel_searches():
    from status_feed import bind_status, push_status

    async def run():
        seen = []

        async def emit(text):
            seen.append(text)

        bind_status(emit)
        await push_status("search", "курс доллара")
        await push_status("search", "курс евро")
        await push_status("search", "ищу в интернете")
        await push_status("search", "ищу в интернете")
        return seen[-1]

    text = asyncio.run(run())
    assert "курс доллара" in text
    assert "курс евро" in text
    assert "ищу в интернете" not in text


def test_system_prompt_uses_agent_contract_not_generic_assistant():
    from config import SYSTEM_PROMPT

    assert "Bit-Think" in SYSTEM_PROMPT
    assert "Не спрашивай разрешение искать" in SYSTEM_PROMPT
    assert "read_chat_document" in SYSTEM_PROMPT
    assert "search_chats" in SYSTEM_PROMPT
    assert "workspace_grep" in SYSTEM_PROMPT
    assert "длинное тире" in SYSTEM_PROMPT
    assert "web_search" in SYSTEM_PROMPT
    assert "image_search" in SYSTEM_PROMPT
    assert "load_skill" in SYSTEM_PROMPT
    assert "Закрой задачу" in SYSTEM_PROMPT
    assert "могу подробнее" in SYSTEM_PROMPT
    assert "дружелюбный и полезный ассистент" not in SYSTEM_PROMPT.lower()

