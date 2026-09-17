from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path

import io

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


def test_parse_replacements_lone_number_line_is_not_consent():
    """A digits-only pair matches the document-number shape, but «100000 ->
    120000» is also how a budget or a deadline gets discussed in passing. On
    its own it is not the filled-in table, so it must not read as consent."""
    for prose in (
        "100000 -> 120000",
        "смета:\n100000 -> 120000",
        "бюджет 100000 -> 120000 и сроки",
    ):
        assert dg._parse_replacements(prose) == {}, f"lone number parsed as consent: {prose!r}"

    # The same line inside a real list still parses: one recognisable
    # neighbour is enough to tell the table from the aside.
    assert dg._parse_replacements(
        "100000 -> 120000\nЗаказчик: ООО «Ромашка» → ООО «Вектор»"
    ) == {"100000": "120000", "ООО «Ромашка»": "ООО «Вектор»"}

    # A lone pair with a recognisable shape is a table of one, not an aside.
    assert dg._parse_replacements("АБВГ.123456.789 -> ЖЗИК.987654.321") == {
        "АБВГ.123456.789": "ЖЗИК.987654.321"
    }


def test_requested_sections_reads_the_page_target():
    """Without this the planner sizes the document by feel — a request for
    5000 pages produced a few dozen sections and the user never learned why."""
    assert dg._requested_sections("напиши документацию на 5000 страниц") == 3334
    assert dg._requested_sections("документ на 5 тыс. страниц") == 3334
    assert dg._requested_sections("7к страниц") == 4667
    assert dg._requested_sections("сделай 300 разделов") == 300


def test_requested_sections_takes_the_upper_bound_of_a_range():
    # «5-7 тысяч страниц» — under-delivering on a stated range is the worse
    # error here: the run is confirmed before it starts, so too big is visible.
    assert dg._requested_sections("нужен документ 5-7 тысяч страниц") == 4667


def test_requested_sections_needs_a_unit_word():
    assert dg._requested_sections("пояснительная записка по ГОСТ 19.201-78") is None
    assert dg._requested_sections("сгенерируй документацию по этой базе") is None
    assert dg._requested_sections("страница 5 шаблона важна") is None


def test_requested_sections_clamped_to_max_sections():
    assert dg._requested_sections("нужно 100000 страниц") == dg.MAX_SECTIONS


def test_deepseek_is_what_keeps_the_run_inside_the_hundred_dollar_budget():
    """The mode's stated budget is 5-7 thousand pages under $100. With DeepSeek
    on the escalated sections the worst case fits with room to spare; without
    it, the same worst case does not — which is exactly why the confirmation
    screen warns when the key is missing instead of quoting a number and
    hoping. Both halves are asserted so neither can drift unnoticed.
    """
    outline = [
        dg.Section(id=i, title=f"Раздел {i}", brief="", complexity="complex")
        for i in range(dg._requested_sections("7000 страниц"))
    ]
    original = dg.DEEPSEEK_API_KEY
    try:
        dg.DEEPSEEK_API_KEY = "sk-present"
        with_deepseek = dg._estimate_cost_usd(outline, has_sources=True)
        dg.DEEPSEEK_API_KEY = ""
        without_deepseek = dg._estimate_cost_usd(outline, has_sources=True)
    finally:
        dg.DEEPSEEK_API_KEY = original

    assert with_deepseek < 100, f"budget blown even with DeepSeek: ${with_deepseek:.2f}"
    assert without_deepseek > with_deepseek * 2, "DeepSeek must be the cheap path, not a rounding difference"


def test_estimate_cost_grows_with_escalation_and_size():
    simple = [dg.Section(id=i, title="x", brief="", complexity="simple") for i in range(100)]
    complex_ = [dg.Section(id=i, title="x", brief="", complexity="complex") for i in range(100)]
    assert dg._estimate_cost_usd(complex_, True) > dg._estimate_cost_usd(simple, True)
    assert dg._estimate_cost_usd(simple, True) > dg._estimate_cost_usd(simple, False)
    assert dg._estimate_cost_usd(simple[:50], True) < dg._estimate_cost_usd(simple, True)


def test_chapter_count_never_exceeds_max_sections():
    # MAX_CHAPTERS x SECTIONS_PER_CHAPTER must stay equal to MAX_SECTIONS:
    # a drift here either caps the mode below its promise or blows past the
    # ceiling that keeps a run from lasting days.
    assert dg.MAX_CHAPTERS * dg.SECTIONS_PER_CHAPTER == dg.MAX_SECTIONS


def test_runaway_chapter_plan_does_not_fire_an_expansion_call_per_chapter():
    """A planner that answers with far more chapters than it was asked for
    used to cost one expansion call each, and the sections beyond the ceiling
    were then thrown away anyway — money spent on output nobody sees."""
    import asyncio as _asyncio

    expansions = []

    async def fake_plan(user_text, chunks, user_id, extra_instruction="", want_count=None, as_chapters=False):
        assert as_chapters and want_count
        chapters = [
            dg.Section(id=i, title=f"Глава {i}", brief="", complexity="simple")
            for i in range(want_count * 10)  # runaway: ten times what was asked
        ]
        return chapters, set(), False

    async def fake_expand(chapter, user_text, catalog, per_chapter, user_id):
        expansions.append(chapter.title)
        return [dg.Section(id=0, title=f"{chapter.title}.1", brief="", complexity="simple")]

    orig_plan, orig_expand = dg._plan_outline, dg._expand_chapter
    dg._plan_outline, dg._expand_chapter = fake_plan, fake_expand
    try:
        sections, _, failed = _asyncio.run(
            dg._plan_document("документ на 5000 страниц", [], 1)
        )
    finally:
        dg._plan_outline, dg._expand_chapter = orig_plan, orig_expand

    assert not failed
    expected_chapters = -(-dg._requested_sections("5000 страниц") // dg.SECTIONS_PER_CHAPTER)
    assert len(expansions) == expected_chapters, (
        f"expanded {len(expansions)} chapters, asked for {expected_chapters}"
    )


def test_short_chapter_plan_still_reaches_the_requested_size():
    """The planner usually returns fewer chapters than it was asked for. With
    a hard 25-sections-per-chapter ceiling that alone would turn a 3350-section
    order into 750 — so a short chapter list makes each chapter carry more."""
    import asyncio as _asyncio

    asked_per_chapter = []

    async def fake_plan(user_text, chunks, user_id, extra_instruction="", want_count=None, as_chapters=False):
        # A third of what was asked for — a realistic shortfall, not a failure.
        chapters = [
            dg.Section(id=i, title=f"Глава {i}", brief="", complexity="simple")
            for i in range(max(1, want_count // 3))
        ]
        return chapters, set(), False

    async def fake_expand(chapter, user_text, catalog, per_chapter, user_id):
        asked_per_chapter.append(per_chapter)
        return [
            dg.Section(id=0, title=f"{chapter.title}.{i}", brief="", complexity="simple")
            for i in range(per_chapter)
        ]

    orig_plan, orig_expand = dg._plan_outline, dg._expand_chapter
    dg._plan_outline, dg._expand_chapter = fake_plan, fake_expand
    try:
        sections, _, failed = _asyncio.run(dg._plan_document("документ на 5000 страниц", [], 1))
    finally:
        dg._plan_outline, dg._expand_chapter = orig_plan, orig_expand

    target = dg._requested_sections("5000 страниц")
    assert not failed
    assert max(asked_per_chapter) > dg.SECTIONS_PER_CHAPTER, "a short chapter list must widen each chapter"
    assert max(asked_per_chapter) <= dg.MAX_SECTIONS_PER_EXPANSION
    assert len(sections) >= target * 0.9, f"order shortfall: {len(sections)} of {target}"


def test_progress_line_counts_pages_from_real_text_not_from_the_plan():
    """A run lasts hours and the user ordered pages, not sections. The pages
    shown have to come from what was actually written: a model writing shorter
    than planned must be visible straight away, not at the end."""
    # Half the sections done, but each one came out half the expected length.
    written = 50 * (dg.CHUNK_TARGET_CHARS // 2)
    line = dg._progress_line(done=50, total=100, chars_written=written)
    assert "раздел 50 из 100" in line
    assert "50%" in line
    assert f"готово ~{written // dg.CHARS_PER_PAGE} стр." in line
    # The target still reflects the plan, so the shortfall is visible as a gap.
    assert f"из ~{100 * dg.CHUNK_TARGET_CHARS // dg.CHARS_PER_PAGE}" in line


def test_progress_bar_fills_and_never_overflows():
    assert dg._progress_bar(0, 10) == "▱" * 10
    assert dg._progress_bar(10, 10) == "▰" * 10
    assert len(dg._progress_bar(3, 10)) == 10
    # Degenerate inputs must not raise or produce a ragged bar — this runs
    # inside the status update of a multi-hour job.
    assert len(dg._progress_bar(0, 0)) == 10
    assert len(dg._progress_bar(99, 10)) == 10


def test_estimate_cost_covers_the_model_writing_longer_than_planned():
    """Measured on the server: a 6-page order came back 11 pages. The estimate
    says «не больше», so it has to hold when the model overshoots — otherwise
    the budget promise breaks on a successful run, which is the worst time."""
    outline = [dg.Section(id=i, title="x", brief="", complexity="complex") for i in range(100)]
    estimate = dg._estimate_cost_usd(outline, has_sources=True)

    from app.billing.costs import model_cost_usd
    from model_context import estimate_tokens
    # What a run actually costs if every section comes out 1.8x the plan.
    real_input = estimate_tokens("x" * (dg.MAX_CHUNK_CHARS_PER_SECTION + 1200))
    real_output = estimate_tokens("x" * int(dg.CHUNK_TARGET_CHARS * 1.8))
    escalated = "deepseek-v4-pro" if dg.DEEPSEEK_API_KEY else dg.ESCALATED_WRITER_MODEL
    actual = 100 * model_cost_usd(escalated, real_input, real_output)
    assert estimate >= actual, f"estimate ${estimate:.2f} under-promises the real ${actual:.2f}"


def _sections(*pairs):
    return [
        dg.Section(id=i, title=title, brief="", complexity="simple", document=document)
        for i, (title, document) in enumerate(pairs)
    ]


def test_sections_without_a_document_stay_one_file():
    """The old behaviour, and still the common case: nothing asked for several
    documents, so nothing gets split."""
    outline = _sections(("Раздел 1", ""), ("Раздел 2", ""))
    groups = dg._group_by_document(outline, ["текст один", "текст два"])
    assert len(groups) == 1
    assert groups[0][0] == ""
    assert "текст один" in groups[0][1] and "текст два" in groups[0][1]


def test_each_document_becomes_its_own_file():
    outline = _sections(("Общие сведения", "ИТТ на ПЛК"), ("Требования", "ИТТ на ПЛК"),
                        ("Общие сведения", "ИТТ на шкаф"))
    groups = dg._group_by_document(outline, ["а", "б", "в"])
    assert [title for title, _ in groups] == ["ИТТ на ПЛК", "ИТТ на шкаф"]
    assert "а" in groups[0][1] and "б" in groups[0][1]
    assert "в" in groups[1][1] and "а" not in groups[1][1]


def test_interleaved_sections_do_not_split_a_document_in_two():
    """The planner is asked to keep a document's sections together, but it is a
    model. Grouping by position would turn ten documents into twenty files,
    half of them named «… (2)» — worse than useless to the customer."""
    outline = _sections(("Р1", "Документ А"), ("Р1", "Документ Б"), ("Р2", "Документ А"))
    groups = dg._group_by_document(outline, ["а1", "б1", "а2"])
    assert len(groups) == 2, f"interleaving split a document: {[t for t, _ in groups]}"
    assert "а1" in groups[0][1] and "а2" in groups[0][1]


def test_document_filename_is_safe_and_unique():
    used = set()
    assert dg._document_filename("ИТТ на ПЛК", used) == "ИТТ на ПЛК.docx"
    # Path separators in a model-supplied title must not escape into a path.
    assert dg._document_filename("узел/подузел: часть 1", used) == "узел подузел часть 1.docx"
    assert dg._document_filename("ИТТ на ПЛК", used) == "ИТТ на ПЛК (2).docx"
    assert dg._document_filename("", used) == "Документ.docx"


def test_many_documents_are_packed_into_one_archive():
    """Ten separate attachments are ten cards to download one by one; the user
    asked for an archive."""
    import zipfile
    files = [{"filename": f"Док {i}.docx", "bytes": b"PK-fake-%d" % i} for i in range(3)]
    packed = dg._zip_documents(files)
    assert packed["filename"].endswith(".zip")
    with zipfile.ZipFile(io.BytesIO(packed["bytes"])) as archive:
        assert archive.namelist() == ["Док 0.docx", "Док 1.docx", "Док 2.docx"]
        assert archive.read("Док 1.docx") == b"PK-fake-1"


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
