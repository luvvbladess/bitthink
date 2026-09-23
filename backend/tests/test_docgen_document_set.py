"""Комплект документов в режиме «Документы»: заказ «переработай комплект и
разработай недостающие» без названного числа файлов раньше планировался как
один документ — человек получал оглавление одного тома вместо комплекта."""

from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path

import asyncio

import docgen_router as dg
from docgen_router import Chunk, Section


SET_REQUEST = (
    "Подготовь комплект документов по заданию: переработай имеющиеся документы "
    "и разработай недостающие, оформление по требованиям."
)


def test_document_set_wording_is_detected():
    assert dg._wants_document_set(SET_REQUEST)
    assert dg._wants_document_set("нужен пакет документов на тендер")
    assert dg._wants_document_set("добавь недостающие документы")
    assert dg._wants_document_set("переработай эти документы и разработай остальные")
    assert not dg._wants_document_set("сделай ИТТ по шаблону")
    assert not dg._wants_document_set("напиши документацию на 300 страниц")


def test_set_without_count_is_planned_as_separate_documents():
    asked = []

    async def fake_plan(user_text, chunks, user_id, extra_instruction="",
                        want_count=None, as_chapters=False, as_documents=False):
        asked.append((want_count, as_chapters, as_documents))
        return (
            [
                Section(id=0, title="Пояснительная записка", brief="Переработка: ПЗ_старая.docx. Обновить данные.",
                        complexity="complex"),
                Section(id=1, title="Программа испытаний", brief="Разработка: по заданию, раздел 4.",
                        complexity="complex"),
                Section(id=2, title="Ведомость документов", brief="Разработка: перечень комплекта.",
                        complexity="simple"),
            ],
            set(), False,
        )

    async def fake_expand(chapter, user_text, catalog, per_chapter, user_id):
        return [Section(id=0, title="Раздел", brief="", complexity="simple",
                        document=chapter.document, document_brief=chapter.document_brief)]

    orig_plan, orig_expand = dg._plan_outline, dg._expand_chapter
    dg._plan_outline, dg._expand_chapter = fake_plan, fake_expand
    try:
        sections, _, failed = asyncio.run(dg._plan_document(SET_REQUEST, [], 1))
    finally:
        dg._plan_outline, dg._expand_chapter = orig_plan, orig_expand

    assert not failed
    assert asked == [(None, True, True)], "a set without a count must ask the planner for the list itself"
    assert {s.document for s in sections} == {
        "Пояснительная записка", "Программа испытаний", "Ведомость документов",
    }
    by_doc = {s.document: s.document_brief for s in sections}
    assert by_doc["Пояснительная записка"].startswith("Переработка: ПЗ_старая.docx")
    assert by_doc["Программа испытаний"].startswith("Разработка")


def test_counted_set_does_not_seed_titles_from_source_files():
    """Три исходника и «3 документа»: без проверки комплекта «Задание.docx»
    стало бы одним из документов, потому что число файлов совпало с заказом."""
    chunks = [
        Chunk(id=0, doc_name="Задание.docx", title="t", text="задание"),
        Chunk(id=1, doc_name="Данные.xlsx", title="t", text="данные"),
        Chunk(id=2, doc_name="ПЗ.docx", title="t", text="пз"),
    ]
    planned = []

    async def fake_plan(user_text, chunks, user_id, extra_instruction="",
                        want_count=None, as_chapters=False, as_documents=False):
        planned.append(want_count)
        return (
            [Section(id=i, title=t, brief="Разработка: x", complexity="simple")
             for i, t in enumerate(["А", "Б", "В"])],
            set(), False,
        )

    async def fake_expand(chapter, user_text, catalog, per_chapter, user_id):
        return [Section(id=0, title="Раздел", brief="", complexity="simple", document=chapter.document)]

    orig_plan, orig_expand = dg._plan_outline, dg._expand_chapter
    dg._plan_outline, dg._expand_chapter = fake_plan, fake_expand
    try:
        sections, _, _ = asyncio.run(dg._plan_document(
            "подготовь комплект из 3 документов по заданию", chunks, 1,
        ))
    finally:
        dg._plan_outline, dg._expand_chapter = orig_plan, orig_expand

    assert planned == [3], "the planner must build the list, not the source file names"
    assert "Задание" not in {s.document for s in sections}


def test_set_prompt_asks_for_rework_and_new_documents():
    captured = {}

    async def fake_chat(messages, **kwargs):
        captured["prompt"] = messages[-1]["content"]
        return '{"sections": [{"title": "А", "brief": "Разработка: x"}]}', [], "", []

    orig = dg.get_chat_response
    dg.get_chat_response = fake_chat
    try:
        asyncio.run(dg._plan_outline(SET_REQUEST, [], 1, as_chapters=True, as_documents=True))
    finally:
        dg.get_chat_response = orig

    prompt = captured["prompt"]
    assert "КОМПЛЕКТА" in prompt
    assert "Переработка:" in prompt and "Разработка:" in prompt
    assert "наименование изделия/узла" not in prompt, "a generic set must not get the ИТТ-per-node wording"


def test_expanded_sections_inherit_the_document_brief():
    """The writer of a section must know the document is a rework of a given
    file; the expansion JSON has no such field, so it is stamped from the
    document-level plan."""
    async def fake_chat(messages, **kwargs):
        return '{"sections": [{"title": "Состав", "brief": "b"}, {"title": "Методика", "brief": "b"}]}', [], "", []

    orig = dg.get_chat_response
    dg.get_chat_response = fake_chat
    try:
        chapter = Section(id=0, title="Программа испытаний", brief="Переработка: ПИ.docx. Обновить.",
                          complexity="complex", document="Программа испытаний",
                          document_brief="Переработка: ПИ.docx. Обновить.")
        sections = asyncio.run(dg._expand_chapter(chapter, SET_REQUEST, "", 2, 1))
    finally:
        dg.get_chat_response = orig

    assert [s.document_brief for s in sections] == ["Переработка: ПИ.docx. Обновить."] * 2
    assert {s.document for s in sections} == {"Программа испытаний"}


def test_rework_source_is_found_by_file_name():
    chunks = [
        Chunk(id=0, doc_name="Исходный комплект.zip/03_Программа_испытаний.docx", title="t", text="x"),
        Chunk(id=1, doc_name="Задание.docx", title="t", text="x"),
    ]
    section = Section(id=0, title="Раздел", brief="", complexity="simple", document="Программа испытаний",
                      document_brief="Переработка: 03_Программа_испытаний.docx. Обновить методику.")
    assert dg._rework_source(section, chunks) == "Исходный комплект.zip/03_Программа_испытаний.docx"
    new_doc = Section(id=0, title="Раздел", brief="", complexity="simple", document="Акт",
                      document_brief="Разработка: акт приёмки.")
    assert dg._rework_source(new_doc, chunks) is None


def test_rework_section_context_leads_with_its_source_file():
    chunks = [
        Chunk(id=0, doc_name="ПЗ_старая.docx", title="Состав", text="Старый состав системы: насос Н-1.",
              tokens=frozenset({"старый", "состав", "системы", "насос"})),
        Chunk(id=1, doc_name="Задание.docx", title="Состав системы", text="Состав системы по заданию: насос Н-2.",
              tokens=frozenset({"состав", "системы", "заданию", "насос"}),
              title_tokens=frozenset({"состав", "системы"})),
    ]
    section = Section(id=0, title="Состав системы", brief="", complexity="simple",
                      document="Пояснительная записка",
                      document_brief="Переработка: ПЗ_старая.docx. Обновить состав по заданию.")
    block = dg._section_context(section, chunks, set())
    assert block.index("[ПЗ_старая.docx]") < block.index("[Задание.docx]"), block
    assert "Задание.docx" in block, "a set member must still see the shared task file"


def test_confirmation_lists_the_set_composition():
    outline = [
        Section(id=0, title="р", brief="", complexity="simple", document="Пояснительная записка",
                document_brief="Переработка: ПЗ.docx. Обновить."),
        Section(id=1, title="р", brief="", complexity="simple", document="Пояснительная записка",
                document_brief="Переработка: ПЗ.docx. Обновить."),
        Section(id=2, title="р", brief="", complexity="simple", document="Программа испытаний",
                document_brief="Разработка: по заданию."),
    ]
    text = "\n".join(dg._document_set_proposal(outline))
    assert dg._SET_PROPOSAL_MARKER in text
    assert "переработать: 1, разработать заново: 1" in text
    assert "1. Пояснительная записка – Переработка: ПЗ.docx" in text
    assert "2. Программа испытаний – Разработка" in text
    assert dg._document_set_proposal(outline[:1]) == [], "a single document needs no composition list"

    registry = dg._delivered_set_registry(outline)
    assert "1. Пояснительная записка – переработан" in registry
    assert "2. Программа испытаний – разработан" in registry


def test_short_message_after_proposal_is_a_revision():
    proposal = f"Документов: 3\n\n{dg._SET_PROPOSAL_MARKER}:\n1. А\n2. Б\n3. В"
    messages = [
        {"role": "user", "content": SET_REQUEST},
        {"role": "assistant", "content": proposal},
        {"role": "user", "content": "убери третий, добавь акт приёмки"},
    ]
    original, revisions = dg._set_request_chain(messages, "убери третий, добавь акт приёмки")
    assert original == SET_REQUEST
    assert revisions == ["убери третий, добавь акт приёмки"]

    # Second revision, then the start chip: phase two must see both edits.
    messages += [
        {"role": "assistant", "content": proposal},
        {"role": "user", "content": "и переименуй Б в «Руководство оператора»"},
        {"role": "assistant", "content": proposal},
        {"role": "user", "content": "Уточнения по задаче:\n1. Начинать генерацию? – " + dg._CONFIRM_START},
    ]
    original, revisions = dg._set_request_chain(messages, messages[-1]["content"])
    assert original == SET_REQUEST
    assert revisions == ["убери третий, добавь акт приёмки", "и переименуй Б в «Руководство оператора»"]


def test_message_without_proposal_is_not_a_revision():
    messages = [
        {"role": "user", "content": "Сделай ИТТ"},
        {"role": "assistant", "content": "Разделов: 8, примерно 12 стр."},
        {"role": "user", "content": "Сделай регламент"},
    ]
    original, revisions = dg._set_request_chain(messages, "Сделай регламент")
    assert original == "Сделай регламент"
    assert revisions == []


def test_long_new_order_after_proposal_starts_fresh():
    proposal = f"{dg._SET_PROPOSAL_MARKER}:\n1. А\n2. Б"
    fresh = "Подготовь новый комплект документов для другого объекта. " + "Подробности задания. " * 20
    messages = [
        {"role": "user", "content": SET_REQUEST},
        {"role": "assistant", "content": proposal},
        {"role": "user", "content": fresh},
    ]
    original, revisions = dg._set_request_chain(messages, fresh)
    assert original == fresh
    assert revisions == []
