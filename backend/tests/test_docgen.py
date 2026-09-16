from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path

import docgen_router as dg
from docgen_router import (
    MAX_CHUNK_CHARS_PER_SECTION,
    MAX_SOURCE_CHARS_TOTAL,
    PLANNER_PREVIEW_BUDGET,
    PLANNER_PREVIEW_GROUPS,
    Chunk,
    Section,
    _build_context_block,
    _classify_documents_hint,
    _document_previews,
    _expand_template_names,
    _folder_of,
    _group_by_folder,
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


def test_expand_template_names_folder_inside_archive_selects_only_that_folder():
    # arhiv.zip holds two folders — shablony (templates) and baza
    # (knowledge) — plus a sub-subfolder inside shablony. Naming just
    # "arhiv.zip/shablony" must select every file under it, however deep,
    # and nothing from "arhiv.zip/baza".
    chunks = [
        Chunk(id=0, doc_name="arhiv.zip/shablony/forma1.docx", title="t", text="x", tokens=frozenset()),
        Chunk(id=1, doc_name="arhiv.zip/shablony/formy/forma2.docx", title="t", text="x", tokens=frozenset()),
        Chunk(id=2, doc_name="arhiv.zip/baza/otchet1.docx", title="t", text="x", tokens=frozenset()),
    ]

    resolved = _expand_template_names(["arhiv.zip/shablony"], chunks)

    assert resolved == {"arhiv.zip/shablony/forma1.docx", "arhiv.zip/shablony/formy/forma2.docx"}


def test_folder_of_bare_name_has_no_slash():
    assert _folder_of("report.docx") == "report.docx"


def test_folder_of_flat_archive_member_groups_by_the_archive():
    assert _folder_of("arhiv.zip/forma1.docx") == "arhiv.zip"


def test_folder_of_nested_archive_member_groups_by_its_own_folder():
    assert _folder_of("arhiv.zip/shablony/formy/forma1.docx") == "arhiv.zip/shablony/formy"


def test_group_by_folder_nested_paths_group_separately_bare_names_group_alone():
    names = [
        "arhiv.zip/shablony/forma1.docx",
        "arhiv.zip/shablony/forma2.docx",
        "arhiv.zip/baza/otchet1.docx",
        "bare.docx",
    ]

    groups = _group_by_folder(names)

    assert groups["arhiv.zip/shablony"] == ["arhiv.zip/shablony/forma1.docx", "arhiv.zip/shablony/forma2.docx"]
    assert groups["arhiv.zip/baza"] == ["arhiv.zip/baza/otchet1.docx"]
    assert groups["bare.docx"] == ["bare.docx"]


def test_extract_source_chunks_stops_at_corpus_ceiling_and_reports_skipped(monkeypatch):
    """Change B: raising the per-file caps removed the only thing that kept
    the total corpus bounded by accident. A document that would push the
    running total over MAX_SOURCE_CHARS_TOTAL must not be loaded, but must be
    named — and a smaller document later in the list still gets its chance."""
    from conversations import conversation_manager

    big = "x" * (MAX_SOURCE_CHARS_TOTAL // 2 + 1)
    docs = [
        {"filename": "a.pdf", "content": big},
        {"filename": "b.pdf", "content": big},
        {"filename": "c.pdf", "content": "small enough to still fit"},
    ]
    monkeypatch.setattr(conversation_manager, "get_documents", lambda uid: docs)

    chunks, truncated, skipped = dg._extract_source_chunks(1)

    loaded = {c.doc_name for c in chunks}
    assert "a.pdf" in loaded, "the first document under the ceiling must load"
    assert "b.pdf" not in loaded, "the document that would exceed the ceiling must not load"
    assert "b.pdf" in skipped, "a document dropped by the ceiling must be named as skipped"
    assert "c.pdf" in loaded, "a smaller document after a skip must still be checked and fit"
    assert not truncated


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


def _previews_for(archives: int, per_archive: int) -> str:
    chunks = [
        Chunk(
            id=a * per_archive + i,
            doc_name=f"архив{a}.zip/f{i}.docx",
            title="t",
            text="X" * 2000,
            tokens=frozenset(),
        )
        for a in range(archives)
        for i in range(per_archive)
    ]
    return _document_previews(chunks)


def test_document_previews_size_stops_growing_with_file_count():
    """The previous per-file budget had a 300-char floor, so past ~200 files it
    grew linearly again — 346k chars at 1000 files, worse than the blowup it was
    meant to fix. Previews are per archive now, so the block must plateau."""
    small = _previews_for(archives=10, per_archive=5)      # 50 files
    large = _previews_for(archives=10, per_archive=500)    # 5000 files, same archives

    # 100x the files may only move the block by the width of the counts printed
    # in each archive header — nothing proportional to the file count.
    assert len(large) < len(small) * 1.2, (
        "preview size must depend on archive count, not file count: "
        f"{len(small)} chars for 50 files vs {len(large)} for 5000"
    )


def test_document_previews_ceiling_holds_at_any_scale():
    huge = _previews_for(archives=200, per_archive=25)  # 5000 files across 200 archives

    # A fixed ceiling, not one that grows with the input: preview bodies are
    # capped by PLANNER_PREVIEW_BUDGET and only PLANNER_PREVIEW_GROUPS archives
    # get one, so headers and name lists add bounded overhead on top.
    assert len(huge) < PLANNER_PREVIEW_BUDGET * 2


def test_document_previews_names_every_archive_even_without_a_preview():
    previews = _previews_for(archives=PLANNER_PREVIEW_GROUPS + 5, per_archive=2)

    for a in range(PLANNER_PREVIEW_GROUPS + 5):
        assert f"архив{a}.zip" in previews, f"архив{a}.zip missing from previews entirely"


# Task 15 — «было → стало»: find repeating requisites, parse a filled reply,
# apply it deterministically.

def test_parse_replacements_accepts_arrow_separator():
    assert dg._parse_replacements("АБВГ.123456.789 → АБВГ.999999.001") == {
        "АБВГ.123456.789": "АБВГ.999999.001"
    }


def test_parse_replacements_accepts_ascii_arrow_separator():
    assert dg._parse_replacements("Иванов И.И. -> Петров П.П.") == {"Иванов И.И.": "Петров П.П."}


def test_parse_replacements_accepts_coloneq_separator():
    # ::= is what app/api/documents.py's /edit-docx norm-control endpoint
    # already parses — same idea, same syntax.
    assert dg._parse_replacements("ООО «Ромашка» ::= ООО «Новый заказчик»") == {
        "ООО «Ромашка»": "ООО «Новый заказчик»"
    }


def test_parse_replacements_strips_label_prefix():
    assert dg._parse_replacements("Заказчик: ООО «Ромашка» → ООО «Новый заказчик»") == {
        "ООО «Ромашка»": "ООО «Новый заказчик»"
    }


def test_parse_replacements_empty_right_side_means_placeholder():
    assert dg._parse_replacements("Заказчик: ООО «Ромашка» → ") == {"ООО «Ромашка»": ""}


def test_parse_replacements_kak_est_drops_the_pair():
    assert dg._parse_replacements("Заказчик: ООО «Ромашка» → как есть") == {}


def test_parse_replacements_no_separator_returns_empty_dict():
    # Not mistaken for a confirmation: Task 12's fail-safe gate relies on
    # this returning falsy for an ordinary message.
    assert dg._parse_replacements("Просто обычное сообщение без разделителей.") == {}


def test_parse_replacements_ignores_prose_that_merely_contains_an_arrow():
    """A non-empty mapping is taken as consent to start generating, so prose
    with a stray arrow must not produce one — otherwise an ordinary chat
    message costs thousands of model calls. The left side has to look like a
    requisite, the same shapes the table offered in the first place."""
    for prose in (
        "я думаю -> надо переделать раздел",
        "давай так: сначала план -> потом текст",
        "сроки сдвинулись ::= перенеси на май",
    ):
        assert dg._parse_replacements(prose) == {}, f"prose parsed as a replacement list: {prose!r}"


def test_apply_replacements_longest_first_prevents_partial_overlap():
    mapping = {
        "АБВГ.123456.789": "СТАЛО.000000.001",
        "123456": "999999",
    }
    text = "Документ АБВГ.123456.789, отдельно упомянут номер 123456."

    result = dg._apply_replacements(text, mapping)

    assert "СТАЛО.000000.001" in result
    assert "999999" in result
    assert "123456" not in result, f"old value survived a partial overlap: {result!r}"


def test_apply_replacements_empty_value_becomes_placeholder():
    mapping = {"ООО «Ромашка»": ""}
    text = "Заказчик: ООО «Ромашка»."

    result = dg._apply_replacements(text, mapping)

    assert "ООО «Ромашка»" not in result
    assert "[УКАЗАТЬ: Организация]" in result


def test_find_replacement_candidates_needs_two_documents():
    chunks = [
        Chunk(id=0, doc_name="a.docx", title="t", text="Изделие АБВГ.123456.789 испытано.", tokens=frozenset()),
        Chunk(id=1, doc_name="b.docx", title="t", text="См. АБВГ.123456.789 в приложении.", tokens=frozenset()),
        Chunk(id=2, doc_name="a.docx", title="t", text="Разовый номер АБВГ.999999.999 только здесь.", tokens=frozenset()),
    ]

    candidates = dg._find_replacement_candidates(chunks)
    values = [v for v, _ in candidates]

    assert "АБВГ.123456.789" in values, "a designation in two documents must be proposed"
    assert "АБВГ.999999.999" not in values, "a designation in a single document must not be proposed"


def test_find_replacement_candidates_never_proposes_gost_reference():
    chunks = [
        Chunk(id=0, doc_name="a.docx", title="t", text="Материал по ГОСТ 123456-99 применяется.", tokens=frozenset()),
        Chunk(id=1, doc_name="b.docx", title="t", text="Материал по ГОСТ 123456-99 применяется здесь же.", tokens=frozenset()),
    ]

    candidates = dg._find_replacement_candidates(chunks)
    values = [v for v, _ in candidates]

    assert not any("123456" in v for v in values), f"a ГОСТ reference leaked into candidates: {values!r}"
