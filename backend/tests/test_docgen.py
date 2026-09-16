from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path

from docgen_router import (
    MAX_CHUNK_CHARS_PER_SECTION,
    PLANNER_PREVIEW_BUDGET,
    Chunk,
    Section,
    _build_context_block,
    _classify_documents_hint,
    _document_previews,
    _expand_template_names,
    _section_context,
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


def test_build_context_block_labels_template_and_knowledge_when_both_present():
    chunks = [
        Chunk(id=0, doc_name="шаблон.docx", title="t", text="структура раздела", tokens=frozenset()),
        Chunk(id=1, doc_name="данные.xlsx", title="t", text="конкретные цифры", tokens=frozenset()),
    ]

    block = _build_context_block(chunks, budget=8000, template_names={"шаблон.docx"})

    assert "Формат по шаблону:" in block
    assert "Факты из базы знаний:" in block
    template_part, knowledge_part = block.split("Факты из базы знаний:")
    assert "[шаблон.docx] структура раздела" in template_part
    assert "[данные.xlsx] конкретные цифры" in knowledge_part


def test_build_context_block_falls_back_when_template_name_missing_from_chunks():
    chunks = [
        Chunk(id=0, doc_name="данные.xlsx", title="t", text="конкретные цифры", tokens=frozenset()),
        Chunk(id=1, doc_name="отчёт.docx", title="t", text="другой текст", tokens=frozenset()),
    ]

    block = _build_context_block(chunks, budget=8000, template_names={"несуществующий.docx"})

    assert block.startswith("Факты из базы знаний:")
    assert "Формат по шаблону:" not in block
    assert "[данные.xlsx] конкретные цифры" in block
    assert "[отчёт.docx] другой текст" in block


def test_build_context_block_labels_two_template_files_under_one_heading():
    chunks = [
        Chunk(id=0, doc_name="шаблон1.docx", title="t", text="структура раздела один", tokens=frozenset()),
        Chunk(id=1, doc_name="шаблон2.docx", title="t", text="структура раздела два", tokens=frozenset()),
        Chunk(id=2, doc_name="данные.xlsx", title="t", text="конкретные цифры", tokens=frozenset()),
    ]

    block = _build_context_block(chunks, budget=8000, template_names={"шаблон1.docx", "шаблон2.docx"})

    template_part, knowledge_part = block.split("Факты из базы знаний:")
    assert "[шаблон1.docx] структура раздела один" in template_part
    assert "[шаблон2.docx] структура раздела два" in template_part
    assert "[данные.xlsx] конкретные цифры" in knowledge_part


def test_parse_outline_response_extracts_sections_from_fenced_json():
    response = (
        '```json\n'
        '{"template_documents": [], "sections": '
        '[{"title": "Введение", "brief": "Общее описание", "complexity": "simple"},'
        ' {"title": "Расчёт нагрузки", "brief": "Числа", "complexity": "complex"}]}\n'
        '```'
    )

    sections, templates = _parse_outline_response(response)

    assert [s.title for s in sections] == ["Введение", "Расчёт нагрузки"]
    assert sections[0].complexity == "simple"
    assert sections[1].complexity == "complex"
    assert templates == []


def test_parse_outline_response_returns_empty_on_garbage():
    assert _parse_outline_response("не json вообще") == ([], [])


def test_parse_outline_response_defaults_unknown_complexity_to_simple():
    response = '{"sections": [{"title": "Раздел", "brief": "текст", "complexity": "нечто странное"}]}'

    sections, template = _parse_outline_response(response)

    assert sections[0].complexity == "simple"


def test_parse_outline_response_skips_items_without_title():
    response = '{"sections": [{"brief": "нет заголовка"}, {"title": "Есть заголовок", "brief": "ок"}]}'

    sections, template = _parse_outline_response(response)

    assert [s.title for s in sections] == ["Есть заголовок"]


def test_parse_outline_response_extracts_template_documents_array():
    response = '{"template_documents": ["a.docx", "b.docx"], "sections": [{"title": "Раздел", "brief": "текст"}]}'

    sections, templates = _parse_outline_response(response)

    assert templates == ["a.docx", "b.docx"]


def test_parse_outline_response_wraps_bare_template_document_string():
    response = '{"template_documents": "шаблон.docx", "sections": [{"title": "Раздел", "brief": "текст"}]}'

    sections, templates = _parse_outline_response(response)

    assert templates == ["шаблон.docx"]


def test_parse_outline_response_empty_list_when_key_missing():
    response = '{"sections": [{"title": "Раздел", "brief": "текст"}]}'

    sections, templates = _parse_outline_response(response)

    assert templates == []


def test_expand_template_names_exact_match_selects_that_document():
    chunks = [
        Chunk(id=0, doc_name="a.docx", title="t", text="x", tokens=frozenset()),
        Chunk(id=1, doc_name="b.docx", title="t", text="x", tokens=frozenset()),
    ]

    assert _expand_template_names(["a.docx"], chunks) == {"a.docx"}


def test_expand_template_names_archive_name_selects_all_its_members_only():
    chunks = [
        Chunk(id=0, doc_name="shablony.zip/a.docx", title="t", text="x", tokens=frozenset()),
        Chunk(id=1, doc_name="shablony.zip/b.docx", title="t", text="x", tokens=frozenset()),
        Chunk(id=2, doc_name="other.docx", title="t", text="x", tokens=frozenset()),
    ]

    resolved = _expand_template_names(["shablony.zip"], chunks)

    assert resolved == {"shablony.zip/a.docx", "shablony.zip/b.docx"}


def test_expand_template_names_drops_unknown_name():
    chunks = [Chunk(id=0, doc_name="a.docx", title="t", text="x", tokens=frozenset())]

    assert _expand_template_names(["призрак.docx"], chunks) == set()


def test_expand_template_names_name_both_real_file_and_archive_prefix_selects_union():
    # A name that is both an exact document and a prefix of other documents
    # (e.g. "papka" uploaded standalone, alongside "papka/inner.docx") selects
    # both — nothing the planner named is silently dropped.
    chunks = [
        Chunk(id=0, doc_name="papka", title="t", text="x", tokens=frozenset()),
        Chunk(id=1, doc_name="papka/inner.docx", title="t", text="x", tokens=frozenset()),
    ]

    resolved = _expand_template_names(["papka"], chunks)

    assert resolved == {"papka", "papka/inner.docx"}


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


def test_section_context_matches_select_then_build_context_block():
    chunks = [
        Chunk(id=0, doc_name="шаблон.docx", title="Гидравлика", text="структура раздела про гидравлику", tokens=frozenset({"гидравлика"}), title_tokens=frozenset({"гидравлика"})),
        Chunk(id=1, doc_name="данные.xlsx", title="Прочее", text="конкретные цифры", tokens=frozenset({"цифры"}), title_tokens=frozenset({"прочее"})),
    ]
    section = Section(id=0, title="Гидравлика", brief="Опиши гидравлику", complexity="simple")

    block = _section_context(section, chunks, {"шаблон.docx"})

    expected = _build_context_block(
        _select_relevant_chunks(section.title, section.brief, chunks), MAX_CHUNK_CHARS_PER_SECTION, {"шаблон.docx"}
    )
    assert block == expected
    assert "Формат по шаблону:" in block


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


def test_document_previews_stays_bounded_with_many_documents_and_every_doc_shown():
    n = 200
    chunks = [
        Chunk(id=i, doc_name=f"архив.zip/f{i}.docx", title="t", text="X" * 2000, tokens=frozenset())
        for i in range(n)
    ]

    previews = _document_previews(chunks)

    # Per-document content is bounded by PLANNER_PREVIEW_BUDGET regardless of
    # file count — headers add bounded overhead on top, not unbounded growth.
    assert len(previews) < PLANNER_PREVIEW_BUDGET + n * 80
    for i in range(n):
        assert f"f{i}.docx" in previews, f"document f{i}.docx missing from previews"
