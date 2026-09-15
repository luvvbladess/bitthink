"""Regression tests for conversation / Computer history packing."""

from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path

from model_context import format_chat_history_for_prompt, _history_digest


def test_format_history_pins_early_user_asks():
    messages = []
    messages.append({"role": "user", "content": "CONSTRAINT_ALPHA: always use Python 3.11 and never email X"})
    messages.append({"role": "assistant", "content": "Understood, Python 3.11."})
    for i in range(30):
        messages.append({"role": "user", "content": f"follow-up question number {i}"})
        messages.append({"role": "assistant", "content": f"answer {i}"})
    messages.append({"role": "user", "content": "сделай то же для второго файла"})

    text = format_chat_history_for_prompt(messages, tail_messages=20)
    assert "CONSTRAINT_ALPHA" in text
    assert "сделай то же для второго файла" in text
    # Early pin must survive even when tail is only 20 lines
    assert text.index("CONSTRAINT_ALPHA") < text.index("сделай то же")


def test_format_history_extracts_multimodal_text():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "PHOTO_ASK: what is on the slide"},
                {"type": "input_image", "image_url": "https://example.com/a.png"},
            ],
        },
        {"role": "assistant", "content": "A dark closing slide."},
    ]
    text = format_chat_history_for_prompt(messages)
    assert "PHOTO_ASK" in text
    assert "input_image" not in text


def test_history_digest_prefers_user_length():
    messages = [
        {"role": "user", "content": "A" * 800},
        {"role": "assistant", "content": "B" * 800},
    ]
    digest = _history_digest(messages, budget_chars=2_000)
    assert "Пользователь" in digest
    user_line = [line for line in digest.splitlines() if line.startswith("- Пользователь")][0]
    # User clip is longer than the old 180–220 default
    assert len(user_line) > 400
