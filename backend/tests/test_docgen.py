from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path

from docgen_router import (
    Chunk,
    _build_context_block,
    _classify_documents_hint,
    _document_previews,
    _select_relevant_chunks,
    _parse_outline_response,
)

# _extract_source_chunks(user_id) now reads via conversation_manager.get_documents
# (a raw DB read) instead of parsing chat messages — no cheap way to exercise that
# without a real DB, so per the task-9 brief it goes without a unit test here,
# same as _plan_outline/_write_section (covered by the manual smoke check instead).


def test_select_relevant_chunks_ranks_keyword_match_first():
    chunks = [
        Chunk(id=0, doc_name="d", title="Гидравлическая система", text="Давление в гидравлической системе буксира составляет 250 бар.", tokens=frozenset()),
        Chunk(id=1, doc_name="d", title="Штатное расписание", text="В экипаж входят капитан, механик и два матроса.", tokens=frozenset()),
        Chunk(id=2, doc_name="d", title="Электрооборудование", text="Генератор мощностью 500 кВт питает силовую установку.", tokens=frozenset()),
    ]

    selected = _select_relevant_chunks("Гидравлическая система", "Опиши давление в гидравлике буксира", chunks, top_k=2)

    assert selected[0].id == 0


def test_select_relevant_chunks_falls_back_to_first_chunks_when_no_match():
    chunks = [Chunk(id=i, doc_name="d", title=f"Часть {i}", text="нейтральный текст без общих слов", tokens=frozenset()) for i in range(3)]

    selected = _select_relevant_chunks("совершенно другая тема", "ничего общего", chunks, top_k=2)

    assert [c.id for c in selected] == [0, 1]


def test_build_context_block_respects_char_budget():
    chunks = [Chunk(id=i, doc_name="d", title="t", text="x" * 5000, tokens=frozenset()) for i in range(5)]

    block = _build_context_block(chunks, budget=8000)

    # Allow a small, bounded overhead per chunk for the "[doc_name] " label.
    assert len(block) <= 8000 + len(chunks) * 10


def test_parse_outline_response_extracts_sections_from_fenced_json():
    response = (
        '```json\n'
        '[{"title": "Введение", "brief": "Общее описание", "complexity": "simple"},'
        ' {"title": "Расчёт нагрузки", "brief": "Числа", "complexity": "complex"}]\n'
        '```'
    )

    sections = _parse_outline_response(response)

    assert [s.title for s in sections] == ["Введение", "Расчёт нагрузки"]
    assert sections[0].complexity == "simple"
    assert sections[1].complexity == "complex"


def test_parse_outline_response_returns_empty_on_garbage():
    assert _parse_outline_response("не json вообще") == []


def test_parse_outline_response_defaults_unknown_complexity_to_simple():
    response = '[{"title": "Раздел", "brief": "текст", "complexity": "нечто странное"}]'

    sections = _parse_outline_response(response)

    assert sections[0].complexity == "simple"


def test_parse_outline_response_skips_items_without_title():
    response = '[{"brief": "нет заголовка"}, {"title": "Есть заголовок", "brief": "ок"}]'

    sections = _parse_outline_response(response)

    assert [s.title for s in sections] == ["Есть заголовок"]


def test_classify_documents_hint_names_template_and_knowledge_files():
    chunks = [
        Chunk(id=0, doc_name="шаблон_итт.docx", title="t", text="x", tokens=frozenset()),
        Chunk(id=1, doc_name="данные.xlsx", title="t", text="x", tokens=frozenset()),
    ]

    hint = _classify_documents_hint(chunks)

    assert hint != ""
    assert "шаблон_итт.docx" in hint
    assert "данные.xlsx" in hint


def test_classify_documents_hint_empty_without_template_like_names():
    chunks = [
        Chunk(id=0, doc_name="данные.xlsx", title="t", text="x", tokens=frozenset()),
        Chunk(id=1, doc_name="отчёт.docx", title="t", text="x", tokens=frozenset()),
    ]

    assert _classify_documents_hint(chunks) == ""


def test_document_previews_produces_labeled_blocks_capped_per_doc():
    chunks = [
        Chunk(id=0, doc_name="a.docx", title="t", text="A" * 2000, tokens=frozenset()),
        Chunk(id=1, doc_name="b.docx", title="t", text="B" * 2000, tokens=frozenset()),
    ]

    previews = _document_previews(chunks, budget_per_doc=1500)

    assert "--- a.docx (начало файла) ---" in previews
    assert "--- b.docx (начало файла) ---" in previews
    a_block = previews.split("--- b.docx")[0]
    assert a_block.count("A") == 1500
    b_block = previews.split("--- b.docx")[1]
    assert b_block.count("B") == 1500
