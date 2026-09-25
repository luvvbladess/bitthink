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


def test_chat_draws_and_edits_pictures_instead_of_refusing(monkeypatch):
    """Auto used to answer «у меня нет такого инструмента» to «добавь очки» on an attached photo."""
    import openai_client
    from app.billing import quota

    calls = []

    async def fake_edit(images, prompt, size="auto", quality="auto"):
        calls.append(("edit", prompt, len(images)))
        return "data:image/png;base64,iVBORw0KGgo=", None

    async def fake_generate(prompt, size="auto", quality="auto"):
        calls.append(("generate", prompt, 0))
        return "data:image/png;base64,iVBORw0KGgo=", None

    monkeypatch.setattr(openai_client, "edit_image", fake_edit)
    monkeypatch.setattr(openai_client, "generate_image", fake_generate)
    monkeypatch.setattr(quota, "assert_can_generate_image", lambda _uid: None)
    monkeypatch.setattr(quota, "debit_images", lambda _uid, _count=1: None)
    turn = {"images": [b"photo"]}
    monkeypatch.setattr(sr, "_chat_image_bytes", lambda _uid, current_turn_only: turn["images"])
    monkeypatch.setattr(sr, "_last_reply_image", lambda _uid: None)

    def ask(text):
        return asyncio.run(sr.get_image_response([], text, 1, None))

    # Questions about a photo and work on its content stay with the text model.
    assert ask("что на фото?") is None
    assert ask("какой тут стиль одежды?") is None
    assert ask("добавь это в таблицу") is None
    # A command on the attached photo edits it and comes back as a picture.
    answer, files, _, _ = ask("Добавь ребёнку круглые очки для чтения")
    assert calls[-1][0] == "edit" and files[0]["mime_type"] == "image/png" and files[0]["bytes"]
    # No photo: «нарисуй» draws; a plain question is not a picture job.
    turn["images"] = []
    ask("нарисуй кота в очках")
    assert calls[-1][0] == "generate"
    assert ask("добавь очки") is None
    # Right after a picture, a follow-up command edits that picture.
    monkeypatch.setattr(sr, "_last_reply_image", lambda _uid: b"previous")
    ask("а теперь убери фон")
    assert calls[-1][0] == "edit"
