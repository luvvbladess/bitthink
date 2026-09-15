from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path

from docgen_router import Chunk, _build_context_block, _extract_source_chunks, _select_relevant_chunks, _parse_outline_response


def _doc_message(name: str, body: str) -> dict:
    return {
        "role": "system",
        "content": f"Пользователь предоставил документ для контекста: {name}\n\nСодержание:\n{body}",
    }


def test_extract_source_chunks_splits_on_page_markers():
    pages = "\n\n".join(f"--- Страница {i} ---\nТекст страницы номер {i}." for i in range(1, 6))
    messages = [_doc_message("spec.pdf", pages), {"role": "user", "content": "Сделай документ"}]

    chunks = _extract_source_chunks(messages)

    assert len(chunks) == 5
    assert all(c.doc_name == "spec.pdf" for c in chunks)
    assert "страницы номер 3" in chunks[2].text.lower()


def test_extract_source_chunks_falls_back_to_fixed_size_without_markers():
    body = "слово " * 2000  # long plain text, no page markers
    messages = [_doc_message("plain.txt", body)]

    chunks = _extract_source_chunks(messages)

    assert len(chunks) > 1
    assert all(chunk.doc_name == "plain.txt" for chunk in chunks)


def test_extract_source_chunks_returns_empty_without_documents():
    messages = [{"role": "user", "content": "Просто вопрос"}]

    assert _extract_source_chunks(messages) == []


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
