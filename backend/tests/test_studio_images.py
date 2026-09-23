"""Studio must draw and edit pictures instead of falling back to a landing page."""

from app.config import get_settings  # noqa: F401

import asyncio

import studio_router as sr
from studio.html_canvas import detect_kind_explicit, wants_image_edit


def test_image_requests_are_recognised():
    for text in [
        "нарисуй кота в космосе",
        "сгенерируй мне, пожалуйста, картинку с котом",
        "сделай красивую обложку для альбома",
        "картинку кота в стиле аниме",
        "фото собаки на пляже",
        "хочу аватарку в стиле пиксель-арт",
        "нужен логотип для кофейни",
        "generate an image of a red car",
    ]:
        assert detect_kind_explicit(text) == "image", text


def test_html_requests_stay_html():
    assert detect_kind_explicit("сделай лендинг для кофейни") == "landing"
    assert detect_kind_explicit("презентация про кофе на 8 слайдов") == "slides"
    assert detect_kind_explicit("сделай сайт с фото команды") == "landing"


def test_photo_edit_words():
    for text in ["убери фон", "сделай его рыжим", "поменяй цвет машины", "в стиле Ван Гога"]:
        assert wants_image_edit(text), text


def test_uploaded_photo_is_edited_not_turned_into_a_landing(monkeypatch):
    calls = {}

    async def fake_image_studio(messages, user_text, user_id, status_msg, *, previous_html="", source_images=None):
        calls["images"] = source_images
        calls["text"] = user_text
        return "ok", [], "", []

    async def fail_html(*args, **kwargs):
        raise AssertionError("photo edit must not build a landing page")

    monkeypatch.setattr(sr, "_run_image_studio", fake_image_studio)
    monkeypatch.setattr(sr, "_run_html_studio", fail_html)
    monkeypatch.setattr(sr, "_chat_image_bytes", lambda user_id, current_turn_only: [b"png-bytes"])
    import studio.html_canvas as hc

    monkeypatch.setattr(hc, "load_previous_html", lambda user_id: None)
    asyncio.run(sr._run_studio([], "убери фон", 1, None))
    assert calls["images"] == [b"png-bytes"]


def test_image_clarify_answer_draws_the_original_request(monkeypatch):
    calls = {}

    async def fake_image_studio(messages, user_text, user_id, status_msg, *, previous_html="", source_images=None):
        calls["text"] = user_text
        return "ok", [], "", []

    monkeypatch.setattr(sr, "_run_image_studio", fake_image_studio)
    import studio.html_canvas as hc

    monkeypatch.setattr(hc, "load_previous_html", lambda user_id: None)
    messages = [
        {"role": "user", "content": "кот"},
        {"role": "assistant", "content": "Что сделать?"},
        {"role": "user", "content": "Уточнения по задаче:\n1. Что сделать? – Картинка"},
    ]
    asyncio.run(sr._run_studio(messages, messages[-1]["content"], 1, None))
    assert calls["text"] == "кот"
