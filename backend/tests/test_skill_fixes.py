"""Personal skills: save from every chat mode, score matches, apply in Documents."""

import asyncio
import inspect

from app.config import get_settings  # noqa: F401
from computer_skills.loader import (
    catalog,
    load_skill,
    match_skills,
    preload_skills_block,
    user_skill_preamble,
)
from computer_tools import SKILL_TOOL_NAMES, response_tool_names
from conversations import conversation_manager
from db_conversations import DatabaseConversationManager
from skill_commands import apply_skill_turn, guard_unsaved_claim, mark_skill_saved

_PHRASE = (
    "Запомни как скил {name}: служебные письма, на вы, без смайлов и без воды в тексте."
)


def _save_phrase(name: str) -> str:
    return _PHRASE.format(name=name)


def test_description_words_do_not_steal_legal_or_fire_on_kogda():
    mgr = DatabaseConversationManager()
    uid = 96011
    mgr.save_user_skill(
        uid,
        name="loose_alpha",
        description="проверь договор поставки перед ответом",
        body="Скил А: всегда начинай с фразы СЛОТ-АЛЬФА и не отступай.",
        triggers="поставк",
    )
    mgr.save_user_skill(
        uid,
        name="loose_beta",
        description="договор нужно сверить по пунктам",
        body="Скил Б: всегда начинай с фразы СЛОТ-БЕТА и не отступай.",
        triggers="сверк",
    )
    mgr.save_user_skill(
        uid,
        name="when_skill",
        description="Когда нужен короткий ответ без воды",
        body="Скил КОГДА: отвечай ровно одним словом и без пояснений.",
        triggers="",
    )
    try:
        audit = match_skills("проверь договор аренды", user_id=uid, sandbox=False)
        assert "legal" in audit
        assert "loose_alpha" not in audit
        assert "loose_beta" not in audit
        accidental = match_skills("Когда будет готово расписание?", user_id=uid, sandbox=False)
        assert "when_skill" not in accidental
    finally:
        for name in ("loose_alpha", "loose_beta", "when_skill"):
            mgr.delete_user_skill(uid, name)


def test_explicit_custom_triggers_keep_a_builtin_slot():
    mgr = DatabaseConversationManager()
    uid = 96012
    mgr.save_user_skill(
        uid,
        name="deal_one",
        description="Личный регламент сделок",
        body="Первый свой регламент сделки: коротко и на вы, без воды.",
        triggers="договор",
    )
    mgr.save_user_skill(
        uid,
        name="deal_two",
        description="Второй регламент сделок",
        body="Второй свой регламент сделки: нумерованный список из трёх пунктов.",
        triggers="договор",
    )
    try:
        matched = match_skills("проверь договор аренды", user_id=uid, sandbox=False, limit=2)
        assert any(name in {"deal_one", "deal_two"} for name in matched)
        assert any(name in {"legal", "verify"} for name in matched)
    finally:
        mgr.delete_user_skill(uid, "deal_one")
        mgr.delete_user_skill(uid, "deal_two")


def test_skill_tools_are_offered_in_each_chat_profile():
    profiles = {
        "auto": dict(attach_tools=True, chat_only=True, force_web=False, skill_tools=True),
        "auto_web": dict(attach_tools=True, chat_only=True, force_web=True, skill_tools=True),
        "luna": dict(attach_tools=True, chat_only=True, force_web=False, skill_tools=True),
        "deepseek": dict(attach_tools=True, chat_only=True, force_web=False, skill_tools=True),
        "documents": dict(attach_tools=False, chat_only=False, force_web=False, skill_tools=True),
        "documents_web": dict(attach_tools=True, chat_only=False, force_web=True, skill_tools=True),
        "photo": dict(attach_tools=False, chat_only=False, force_web=False, skill_tools=True),
        "astra": dict(attach_tools=True, chat_only=False, force_web=False, skill_tools=True),
        "pilot_employee": dict(attach_tools=True, chat_only=False, force_web=False, skill_tools=True),
        "search": dict(attach_tools=True, chat_only=False, force_web=True, skill_tools=True),
        "research_fallback": dict(attach_tools=True, chat_only=False, force_web=True, skill_tools=True),
        "research_synth": dict(attach_tools=False, chat_only=False, force_web=False, skill_tools=True),
    }
    for mode, flags in profiles.items():
        names = response_tool_names(**flags)
        assert "save_skill" in names, mode
        assert SKILL_TOOL_NAMES <= names, mode
        assert "ssh_exec" not in names or mode in {"astra", "pilot_employee"}, mode
    silent = response_tool_names(attach_tools=False, chat_only=False, force_web=False, skill_tools=False)
    assert "save_skill" not in silent


def test_explicit_phrase_saves_in_every_mode_without_the_model(monkeypatch):
    from handlers import core as core_mod
    import director_router
    import docgen_router
    import studio_router

    called = []

    def boom(*_args, **_kwargs):
        called.append("model")
        raise AssertionError("model must not run for an explicit skill command")

    monkeypatch.setattr(core_mod, "get_chat_response", boom)
    monkeypatch.setattr(director_router, "get_director_response", boom)
    monkeypatch.setattr(studio_router, "get_studio_response", boom)
    monkeypatch.setattr(docgen_router, "get_docgen_response", boom)

    modes = [
        "auto",
        "gpt-5-nano",
        "gpt-6-luna",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "director",
        "studio",
        "docgen",
        "kimi-k2.6",
        "gpt-6-sol",
        "gpt-6-astra",
    ]
    for index, model in enumerate(modes):
        uid = 96100 + index
        name = f"tone{index:02d}"
        conversation_manager.get_subscription(uid)
        conversation_manager.set_user_model(uid, model)
        from app.db.engine import SyncSessionLocal
        from app.db.models import Subscription

        with SyncSessionLocal() as session:
            sub = session.query(Subscription).filter_by(user_id=uid).one()
            sub.tier = "creator"
            session.commit()
        answer, files, _reasoning, _search = asyncio.run(
            core_mod.get_smart_response(uid, _save_phrase(name), [], None)
        )
        assert "сохранён" in answer and "не сохранён" not in answer, (model, answer)
        assert name in {item["name"] for item in catalog(uid)}
        assert files == []
        conversation_manager.delete_user_skill(uid, name)
    assert called == []


def test_failed_save_does_not_claim_success():
    turn = apply_skill_turn(96201, "Запомни как скил tiny: мало")
    assert turn is not None and turn.reply is not None
    assert "не сохранён" in turn.reply
    assert "tiny" not in {item["name"] for item in catalog(96201)}
    mark_skill_saved()
    assert "сохранён" in guard_unsaved_claim("Скил «x» сохранён")
    from skill_commands import begin_skill_turn

    begin_skill_turn()
    guarded = guard_unsaved_claim("Готово. Скил office_tone сохранён. Письмо ниже.")
    assert "не сохранён" in guarded
    assert "Письмо ниже" in guarded


def test_shared_room_does_not_quote_personal_rules():
    mgr = DatabaseConversationManager()
    uid = 96202
    body = "Секретный регламент: обращение на ты и только три пункта."
    mgr.save_user_skill(
        uid,
        name="quiet_tone",
        description="Письма команды",
        body=body,
        triggers="тихийтон",
    )
    try:
        hidden = load_skill("quiet_tone", user_id=uid, shared=True)
        assert body not in hidden
        assert "Настройках" in hidden
        block = preload_skills_block("письмо тихийтон", user_id=uid, sandbox=False, shared=True)
        assert body in block
        assert "не цитируй" in block.lower()
        shown = apply_skill_turn(uid, "Покажи скил quiet_tone")
        # No active shared conversation: full body is allowed in a private chat.
        assert shown is not None and body in (shown.reply or "")
    finally:
        mgr.delete_user_skill(uid, "quiet_tone")


def test_shared_show_points_at_settings(monkeypatch):
    mgr = DatabaseConversationManager()
    uid = 96203
    body = "Секретный регламент комнаты: только на вы и без шуток в письме."
    mgr.save_user_skill(uid, name="room_tone", description="Общий чат", body=body, triggers="комнатон")
    monkeypatch.setattr("computer_skills.loader.turn_is_shared", lambda _uid: True)
    try:
        shown = apply_skill_turn(uid, "Покажи скил room_tone")
        assert shown is not None and shown.reply is not None
        assert body not in shown.reply
        assert "Настройках" in shown.reply
        listed = apply_skill_turn(uid, "Покажи скилы")
        assert listed is not None and body not in (listed.reply or "")
        assert "Настройках" in (listed.reply or "")
    finally:
        mgr.delete_user_skill(uid, "room_tone")


def test_docgen_writer_applies_saved_skill_service_calls_do_not():
    import docgen_router

    uid = 96204
    conversation_manager.save_user_skill(
        uid,
        name="doc_tone",
        description="Тон договоров",
        body="Пиши раздел на вы, короткими пунктами, без вводных абзацев.",
        triggers="договор",
    )
    try:
        preamble = user_skill_preamble(uid, "Собери договор поставки для клиента")
        assert "на вы" in preamble
        assert "doc_tone" in preamble or "Тон" in preamble
        writer = inspect.getsource(docgen_router._write_section)
        assert "user_skill_preamble" in writer
        assert "use_skills=False" in writer
        for fn in (
            docgen_router._plan_outline,
            docgen_router._expand_chapter,
            docgen_router._label_replacement_candidates,
        ):
            assert "use_skills=False" in inspect.getsource(fn)
    finally:
        conversation_manager.delete_user_skill(uid, "doc_tone")


def test_studio_compose_includes_saved_skill_without_tool_loop():
    import studio_router

    uid = 96205
    conversation_manager.save_user_skill(
        uid,
        name="slide_tone",
        description="Тон слайдов",
        body="Заголовки короткие, без восклицательных знаков и без канцелярита.",
        triggers="слайд",
    )
    try:
        block = user_skill_preamble(uid, "Собери слайды про запуск")
        assert "без восклицательных" in block
        for fn in (studio_router._compose_spec, studio_router._compose_html):
            source = inspect.getsource(fn)
            assert "user_skill_preamble" in source
            assert "use_skills=False" in source
            assert "use_tools=False" in source
    finally:
        conversation_manager.delete_user_skill(uid, "slide_tone")


def test_save_stays_on_the_sender_not_the_other_person():
    guest, owner = 96206, 96207
    turn = apply_skill_turn(guest, _save_phrase("guest_only"))
    assert turn is not None and "сохранён" in (turn.reply or "")
    try:
        assert "guest_only" in {item["name"] for item in catalog(guest)}
        assert "guest_only" not in {item["name"] for item in catalog(owner)}
    finally:
        conversation_manager.delete_user_skill(guest, "guest_only")
