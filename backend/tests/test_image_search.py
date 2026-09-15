import asyncio

from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path
from computer_tools import run_computer_tool
from director_router import _select_composer_model, wants_photo_research
from image_search import (
    extract_html_hits,
    extract_json_hits,
    format_reverse_results,
    parse_engine_page,
    unwrap_search_href,
)


def test_unwraps_google_and_keeps_real_pages():
    assert unwrap_search_href("/url?q=https://kudago.com/spb/park", "https://www.google.com") == "https://kudago.com/spb/park"
    hits = extract_html_hits(
        '<a href="https://yandex.ru/images/search">служебное</a>'
        '<a href="https://kudago.com/spb/place/park-pobedy">Парк Победы</a>',
        "https://yandex.ru/images/search",
    )
    assert hits == [{"url": "https://kudago.com/spb/place/park-pobedy", "title": "Парк Победы"}]


def test_parses_json_and_html_engine_pages():
    caption, hits = parse_engine_page(
        '{"sites":[{"url":"https://example.com/place","title":"Колесо обозрения"}]}'
    )
    assert "Колесо" in caption
    assert hits[0]["url"] == "https://example.com/place"
    json_hits = extract_json_hits(
        {"cbir": {"items": [{"href": "https://walkspb.ru/gagarin", "name": "Гагарин"}]}}
    )
    assert json_hits[0]["url"] == "https://walkspb.ru/gagarin"


def test_reverse_results_tell_model_to_open_pages():
    text = format_reverse_results(
        "balcony.jpg",
        [("Яндекс.Картинки", "Парк Победы", [{"url": "https://kudago.com/x", "title": "Гагарин"}])],
    )
    assert "balcony.jpg" in text
    assert "kudago.com" in text
    assert "browse_page" in text


def test_photo_research_gate_and_composer():
    query = "найди где в спб было сделано данное фото"
    assert wants_photo_research(query, True)
    assert not wants_photo_research(query, False)
    assert not wants_photo_research("привет", True)
    journal = [
        {"status": "ok", "result": "Яндекс: Парк Победы"},
        {"status": "ok", "result": "Страница подтверждает колесо Гагарин"},
    ]
    assert _select_composer_model(query, journal) == "gpt-5.6-terra"
    assert _select_composer_model("Сравни два тарифа", [{"status": "ok", "result": "коротко"}]) == "gpt-5.6-luna"


def test_pilot_forces_research_rounds_instead_of_instant_answer():
    from director_router import _ensure_research_plan, is_smalltalk, needs_research, packed_has_images

    assert is_smalltalk("привет")
    assert not is_smalltalk("найди где снято это фото")
    assert needs_research("найди где в спб было сделано данное фото", False)
    skipped = {"status": "done", "new_employees": []}
    round1 = _ensure_research_plan(1, skipped, "найди где снято фото", [], True)
    assert round1["status"] == "continue"
    assert round1["new_employees"][0]["role"] == "Поиск по фото"
    round2 = _ensure_research_plan(2, skipped, "найди где снято фото", [{"status": "ok"}], True)
    assert round2["new_employees"][0]["role"] == "Сверка"
    hello = _ensure_research_plan(1, skipped, "привет", [], False)
    assert not hello.get("new_employees")
    assert packed_has_images([{"role": "user", "content": [{"type": "input_image", "image_url": "data:image/jpeg;base64,xx"}]}])


def test_image_search_without_photo_explains_what_is_missing():
    result = asyncio.run(run_computer_tool("image_search", {}, user_id=93951))
    assert "фото" in result.lower()
