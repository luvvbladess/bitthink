"""Public pages can be rendered for layout questions, not only read as text."""
import asyncio
import base64
import io
import json

from PIL import Image

from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path
from app.services.engineering_io import EngineeringResult
from app.services.page_shot import compose_frames, public_http_url
import computer_tools


def _jpeg(color):
    image = Image.new("RGB", (40, 24), color)
    out = io.BytesIO()
    image.save(out, format="JPEG")
    return out.getvalue()


def _png(color):
    image = Image.new("RGB", (30, 16), color)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_private_targets_are_refused():
    for url in ("http://127.0.0.1/", "http://10.1.1.1/", "http://localhost/x", "file:///etc/passwd", "https://user:pass@example.com/"):
        try:
            public_http_url(url)
        except ValueError as exc:
            assert "недоступен" in str(exc) or "обычный" in str(exc) or "длинный" in str(exc)
        else:
            raise AssertionError(url)


def test_frames_stack_without_covering_the_page():
    jpeg, width, height = compose_frames(_png((200, 10, 10)), _png((10, 10, 200)))
    assert jpeg.startswith(b"\xff\xd8\xff")
    assert width == 30
    assert height == 16 + 16 + 36 * 2


def test_chat_offers_visual_reading():
    assert "browse_visual" in computer_tools.CHAT_TOOL_NAMES
    names = computer_tools.response_tool_names(
        attach_tools=False, chat_only=False, force_web=True, skill_tools=False,
    )
    assert "browse_visual" in names


def test_visual_tool_returns_the_rendered_frame(monkeypatch):
    encoded = base64.b64encode(_jpeg((12, 80, 40))).decode("ascii")

    async def fake_fetch(url, user_id):
        return json.dumps({
            "jpeg_base64": encoded, "width": 40, "height": 24, "desktop": True, "mobile": True,
        })

    async def fake_describe(encoded_image, question, user_id):
        assert question == "заголовки"
        return "Заголовок слева над сеткой карточек."

    monkeypatch.setattr(computer_tools, "_assert_public_http_url", lambda url: url)
    monkeypatch.setattr(computer_tools, "_fetch_page_shot", fake_fetch)
    monkeypatch.setattr(computer_tools, "_describe_layout", fake_describe)
    result = asyncio.run(computer_tools.run_computer_tool(
        "browse_visual", {"url": "https://example.com/school", "question": "заголовки"}, 7,
    ))
    assert isinstance(result, EngineeringResult)
    assert result.image_data_url.startswith("data:image/jpeg;base64,")
    assert "Заголовок слева" in str(result)
    assert "десктоп" in str(result) and "телефон" in str(result)


def test_localhost_never_reaches_the_browser():
    result = asyncio.run(computer_tools.run_computer_tool("browse_visual", {"url": "http://127.0.0.1/admin"}, 1))
    assert "недоступен" in result
    assert not isinstance(result, EngineeringResult)
