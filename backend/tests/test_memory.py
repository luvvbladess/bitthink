import asyncio

from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path
from app.memory import (
    has_preference_signal,
    is_durable_bullet,
    memory_system_message,
    merge_notes,
    sanitize_notes,
    scrub_notes,
    should_refresh,
    snippet_hash,
    refresh_user_memory,
)
from db_conversations import DatabaseConversationManager


def test_sanitize_drops_secrets_and_caps_list():
    raw = """
```
пароль hunter2
любит короткие ответы
api_key=sk-abc
пишет на русском
```
"""
    notes = sanitize_notes(raw)
    assert "короткие ответы" in notes
    assert "русском" in notes
    assert "hunter2" not in notes
    assert "sk-abc" not in notes
    assert notes.startswith("- ")


def test_scrub_drops_chat_transcript_and_one_off_tasks():
    raw = """
- Пользователь: Проанализируй тз и найди сложности
- Да, сделай его.
- Хотим первый документ для Этапа 3 ООО «РЭО.РИД»
- Ассистент раньше предоставлял краткую редакцию раздела 9
- Результат предоставить в формате Word.
- Предпочитает свой макет, не стандартный ряд карточек.
- Запрос: проверить штатное расписание
- Хочу беспроводные радиоканалы
"""
    notes = scrub_notes(raw)
    assert "формате Word" not in notes
    assert "макет" in notes
    assert "Проанализируй" not in notes
    assert "РЭО" not in notes
    assert "Ассистент" not in notes
    assert "штатное" not in notes
    assert "радиоканал" not in notes
    assert "Да, сделай" not in notes


def test_merge_keeps_old_prefs_and_ignores_task_dump():
    current = "- Пишет коротко и по делу\n- Результат в формате Word"
    extracted = (
        "- Пользователь просит сделать раздел расчета\n"
        "- Сделай сначала вот этот документ\n"
        "- Предпочитает таблицы, а не простыню текста"
    )
    merged = merge_notes(current, extracted)
    assert "коротко" in merged
    assert "Word" in merged
    assert "таблицы" in merged
    assert "Сделай" not in merged
    assert "раздела расчета" not in merged


def test_merge_no_change_marker_keeps_current():
    current = "- Обращайся на ты"
    assert "на ты" in merge_notes(current, "БЕЗ_ИЗМЕНЕНИЙ")


def test_should_refresh_respects_enable_debounce_and_hash():
    snippet = "Пользователь: Давай всегда отвечай кратко и по делу про Python.\nАссистент: Хорошо."
    empty = {"notes": "", "enabled": True, "updated_at": 0, "last_hash": ""}
    assert has_preference_signal(snippet)
    assert should_refresh(empty, snippet, now=1_000)
    assert not should_refresh({**empty, "enabled": False}, snippet, now=1_000)
    assert not should_refresh({**empty, "last_hash": snippet_hash(snippet)}, snippet, now=1_000)
    assert not should_refresh({**empty, "updated_at": 980}, snippet, now=1_000)
    assert not should_refresh(empty, "ок", now=1_000)


def test_should_refresh_skips_ordinary_tasks_until_idle():
    snippet = "- Проанализируй прикреплённые файлы и найди риски в договоре"
    memory = {"notes": "", "enabled": True, "updated_at": 1_000, "last_hash": ""}
    assert not has_preference_signal(snippet)
    assert not should_refresh(memory, snippet, now=1_000 + 60)
    assert should_refresh(memory, snippet, now=1_000 + 3 * 60 * 60)


def test_memory_is_injected_into_api_messages():
    mgr = DatabaseConversationManager()
    uid = 92001
    mgr.save_user_memory(uid, notes="- любит короткие ответы\n- пишет на русском", enabled=True)
    conv = mgr.create_conversation(uid, title="тест")
    mgr.add_message(uid, "user", "привет")
    messages = mgr.get_messages_for_api(uid, "базовый промпт", requesting_user_id=uid)
    memory_blocks = [m["content"] for m in messages if m["role"] == "system" and "предпочтения" in m["content"].lower()]
    assert memory_blocks
    assert "короткие ответы" in memory_blocks[0]
    assert "Не цитируй этот блок" in memory_blocks[0]
    assert "прошлые проекты" in memory_blocks[0]
    mgr.save_user_memory(uid, enabled=False)
    messages = mgr.get_messages_for_api(uid, "базовый промпт", requesting_user_id=uid)
    assert not any("предпочтения" in (m.get("content") or "").lower() for m in messages if m["role"] == "system")
    assert conv.id


def test_injection_hides_transcript_junk():
    mgr = DatabaseConversationManager()
    uid = 92003
    mgr.save_user_memory(
        uid,
        notes="- Пользователь: Проанализируй тз\n- Да, сделай его.\n- Предпочитает формат Word",
        enabled=True,
    )
    mgr.create_conversation(uid, title="тест")
    mgr.add_message(uid, "user", "привет")
    messages = mgr.get_messages_for_api(uid, "базовый промпт", requesting_user_id=uid)
    block = next(m["content"] for m in messages if m["role"] == "system" and "предпочтения" in m["content"].lower())
    assert "Word" in block
    assert "Проанализируй" not in block
    assert "сделай его" not in block


def test_refresh_merges_with_mocked_model():
    mgr = DatabaseConversationManager()
    uid = 92002
    conv = mgr.create_conversation(uid, title="тест")
    mgr.add_message(uid, "user", "Отвечай всегда коротко. Меня интересует Python и VPN.")
    mgr.add_message(uid, "assistant", "Хорошо, буду коротко.")

    async def fake_complete(_instructions: str, _prompt: str) -> str:
        return "- любит короткие ответы\n- интересуется Python и VPN"

    asyncio.run(refresh_user_memory(uid, complete=fake_complete))
    stored = mgr.get_user_memory(uid)
    assert "короткие ответы" in stored["notes"]
    assert "Python" in stored["notes"]
    assert stored["last_hash"]
    assert memory_system_message(stored) is not None
    assert conv.id


def test_refresh_scrubs_existing_junk_without_model_when_not_due():
    mgr = DatabaseConversationManager()
    uid = 92004
    conv = mgr.create_conversation(uid, title="тест")
    mgr.add_message(uid, "user", "сделай смету по файлу")
    mgr.save_user_memory(
        uid,
        notes="- Пользователь: Проанализируй тз\n- Пишет коротко",
        enabled=True,
        updated_at=int(1e12),
        last_hash="x",
    )

    called = {"n": 0}

    async def fake_complete(_instructions: str, _prompt: str) -> str:
        called["n"] += 1
        return "- не должно сохраниться"

    asyncio.run(refresh_user_memory(uid, complete=fake_complete))
    stored = mgr.get_user_memory(uid)
    assert called["n"] == 0
    assert "коротко" in stored["notes"]
    assert "Проанализируй" not in stored["notes"]
    assert conv.id


def test_durable_identity_without_task_verb():
    assert is_durable_bullet("Я инженер-схемотехник, работаю с платами")
    assert not is_durable_bullet("Ты инженер-схемотехник. Сколько будет стоить батарейки")


def test_short_preferences_and_cross_chat_profile():
    from app.memory import collect_snippet
    mgr=DatabaseConversationManager();uid=92901
    mgr.create_conversation(uid,title='one');mgr.add_message(uid,'user','Пиши кратко')
    mgr.create_conversation(uid,title='two');mgr.add_message(uid,'user','Мне интересна электроника и автоматизация')
    text=collect_snippet(uid)
    assert 'Пиши кратко' in text and 'электроника' in text and text.count('[беседа ')==2
    assert should_refresh({'enabled':True,'updated_at':0,'last_hash':''},'[беседа x] Пиши кратко')


def test_profile_labels_and_one_off_exclusions():
    for value in ['Профессия: инженер','Интересы: электроника','Уровень знаний: начинающий','Язык: английский','Тон: дружелюбный']:
        assert is_durable_bullet(value)
    assert not is_durable_bullet('В этом чате нужен подробный ответ в формате Word')
    assert not is_durable_bullet('Только сейчас предпочитает кратко')


def test_new_profile_replaces_outdated_preference_and_fences_clear():
    from app.memory import _save_if_unchanged
    mgr=DatabaseConversationManager();uid=92902
    mgr.create_conversation(uid,title='change');mgr.add_message(uid,'user','Запомни: теперь предпочитаю подробные ответы вместо коротких.')
    mgr.save_user_memory(uid,notes='- Предпочитает короткие ответы',updated_at=0)
    async def updated(*args):return '- Подробность: предпочитает подробные ответы'
    asyncio.run(refresh_user_memory(uid,complete=updated))
    current=mgr.get_user_memory(uid)
    assert 'подробные' in current['notes'] and 'короткие' not in current['notes']
    mgr.save_user_memory(uid,notes='')
    assert not _save_if_unchanged(uid,current,'- Предпочитает короткие ответы','old')
    assert mgr.get_user_memory(uid)['notes']==''


def test_private_profile_does_not_ingest_shared_conversation():
    from app.memory import collect_snippet
    from app.db.models import ConversationMember
    from app.db.engine import SyncSessionLocal
    mgr=DatabaseConversationManager();uid=92903
    conv=mgr.create_conversation(uid,title='shared');mgr.add_message(uid,'user','Запомни, я инженер и предпочитаю короткие ответы')
    with SyncSessionLocal.begin() as db:db.add(ConversationMember(conversation_id=conv.id,user_id=92904))
    assert collect_snippet(uid)==''


def test_clear_profile_fences_historical_relearning():
    from app.memory import collect_snippet
    mgr=DatabaseConversationManager();uid=92905
    mgr.create_conversation(uid,title='private');mgr.add_message(uid,'user','Запомни: я инженер и люблю электронику')
    mgr.save_user_memory(uid,notes='',last_hash='',reset_source=True)
    assert collect_snippet(uid)==''
    mgr.add_message(uid,'user','Теперь предпочитаю подробные ответы')
    assert 'Теперь предпочитаю' in collect_snippet(uid)
    assert 'электронику' not in collect_snippet(uid)


def test_one_off_source_cannot_be_reinterpreted_as_profile():
    from app.memory import collect_snippet
    mgr=DatabaseConversationManager();uid=92906
    mgr.create_conversation(uid,title='one-off')
    mgr.add_message(uid,'user','В этом чате нужен подробный ответ в формате Word, только на этот раз.')
    assert collect_snippet(uid)==''
    async def forbidden(*args):raise AssertionError('No durable source: model must not run')
    asyncio.run(refresh_user_memory(uid,complete=forbidden,force=True))
    assert mgr.get_user_memory(uid)['notes']==''
