import asyncio
import base64
import io
import os
import zipfile
from types import SimpleNamespace

from PIL import Image

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from app.api import documents
from app.bot_core.document_parser import extract_text_from_file
import config as bot_config

bot_config.OPENAI_API_KEY = "test-key"

from app.bot_core.openai_client import _build_responses_input


def test_pdf_reads_only_capped_pages(monkeypatch):
    import fitz
    from app.bot_core import document_parser as parser

    monkeypatch.setattr(parser, "MAX_PDF_PAGES", 2)
    monkeypatch.setattr(parser, "MAX_PDF_TABLE_PAGES", 0)
    doc = fitz.open()
    for index in range(5):
        page = doc.new_page()
        page.insert_text((72, 72), f"MARKER_PAGE_{index + 1}")
    data = doc.tobytes()
    doc.close()
    text = asyncio.run(parser.extract_text_from_pdf(data))
    assert "MARKER_PAGE_1" in text
    assert "MARKER_PAGE_2" in text
    assert "MARKER_PAGE_5" not in text
    assert "5 страниц" in text


def test_common_text_and_presentation_formats_are_extracted():
    markdown = asyncio.run(extract_text_from_file("Привет, документ".encode(), "notes.md"))
    assert markdown == "Привет, документ"

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            "ppt/slides/slide1.xml",
            '<p:sld xmlns:p="p" xmlns:a="a"><a:t>Квартальный отчёт</a:t><a:t>42%</a:t></p:sld>',
        )
    presentation = asyncio.run(extract_text_from_file(stream.getvalue(), "report.pptx"))
    assert "Квартальный отчёт" in presentation
    assert "42%" in presentation


def test_image_model_is_gpt_image_2():
    assert bot_config.IMAGE_MODEL == "gpt-image-2"


def test_gpt_image_2_omits_auto_size_and_input_fidelity():
    from app.bot_core.openai_client import _image_generate_kwargs, edit_image
    import inspect

    kwargs = _image_generate_kwargs("кот", size="auto", quality="auto")
    assert kwargs["model"] == "gpt-image-2"
    assert "size" not in kwargs
    assert "quality" not in kwargs
    assert "input_fidelity" not in inspect.getsource(edit_image)


def test_image_job_helpers_keep_prompt_before_generation():
    from app.api import media
    import inspect

    source = inspect.getsource(media)
    assert "_begin_image_job" in source
    assert "persist_user" in source
    assert "Рисую изображение" in source


def test_image_edit_validates_files_before_saving_prompt():
    import inspect
    from app.api import media

    source = inspect.getsource(media.edit_image_endpoint)
    assert source.index("if not sources") < source.index("_begin_image_job")


def test_chat_image_paths_stay_inside_upload_dir(tmp_path, monkeypatch):
    from app.api import media
    monkeypatch.setattr(media, "get_settings", lambda: SimpleNamespace(UPLOAD_DIR=tmp_path))
    stored = tmp_path / "generated" / "abc"
    stored.mkdir(parents=True)
    target = stored / "pic.png"
    target.write_bytes(b"png")
    resolved = media._resolve_upload_path("/uploads/generated/abc/pic.png")
    assert resolved == target.resolve()
    try:
        media._resolve_upload_path("/uploads/../pic.png")
        raise AssertionError("escaped upload dir")
    except (ValueError, FileNotFoundError):
        pass


def test_uploaded_image_is_resized_and_saved_as_vision_safe_format(tmp_path, monkeypatch):
    source = io.BytesIO()
    Image.new("RGB", (3000, 1200), (15, 110, 180)).save(source, format="PNG")
    monkeypatch.setattr(documents, "get_settings", lambda: SimpleNamespace(UPLOAD_DIR=tmp_path))

    url, mime_type, size = asyncio.run(documents._save_chat_image(source.getvalue(), "clipboard.png", "user-1"))

    assert url.startswith("/uploads/chat/")
    assert mime_type == "image/jpeg"
    stored = tmp_path / url.removeprefix("/uploads/")
    assert stored.is_file()
    assert size == stored.stat().st_size
    with Image.open(stored) as image:
        assert max(image.size) == 2048


def test_responses_input_keeps_multiple_attached_images():
    encoded = base64.b64encode(b"image").decode()
    _, items = _build_responses_input([
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Сравни изображения"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ],
        }
    ])

    assert sum(part["type"] == "input_image" for part in items[0]["content"]) == 2


def test_followup_question_retains_attached_image_context(tmp_path, monkeypatch):
    from app.bot_core.db_conversations import DatabaseConversationManager, MessageData, ConversationData

    manager = DatabaseConversationManager()
    monkeypatch.setattr("app.bot_core.db_conversations.get_settings", lambda: SimpleNamespace(UPLOAD_DIR=tmp_path))

    # Create dummy image file in upload directory
    chat_dir = tmp_path / "chat" / "testuser"
    chat_dir.mkdir(parents=True, exist_ok=True)
    img_file = chat_dir / "sample.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32)

    conv = ConversationData(
        id="conv_test_1",
        title="Тест",
        messages=[
            MessageData(
                role="user",
                content="sample.jpg",
                attachment={
                    "type": "image",
                    "name": "sample.jpg",
                    "url": "/uploads/chat/testuser/sample.jpg",
                    "mime_type": "image/jpeg",
                },
            ),
            MessageData(role="user", content="что это"),
            MessageData(role="assistant", content="Это синий квадрат"),
            MessageData(role="user", content="какой у него оттенок?"),  # Note: no "фото" keyword!
        ],
    )
    monkeypatch.setattr(manager, "get_active_conversation", lambda uid: conv)

    api_messages = manager.get_messages_for_api(123, "Ты — полезный ассистент")
    user_images = [
        m for m in api_messages
        if m.get("role") == "user" and isinstance(m.get("content"), list)
        and any(p.get("type") == "image_url" for p in m.get("content", []))
    ]
    assert len(user_images) == 1
    last_user = next(m for m in reversed(api_messages) if m.get("role") == "user")
    assert last_user is user_images[0]
    assert last_user["content"][0]["text"] == "какой у него оттенок?"
    assert any(p.get("type") == "image_url" for p in last_user["content"])


def test_responses_input_keeps_static_prompt_in_instructions():
    instructions, items = _build_responses_input([
        {"role": "system", "content": "Ты Bit-Think"},
        {"role": "system", "content": "Пользователь предоставил документ для контекста: act.pdf\n\nСодержание:\nтекст"},
        {"role": "user", "content": "привет"},
    ])
    assert instructions == "Ты Bit-Think"
    assert items[0]["role"] == "system"
    assert "act.pdf" in items[0]["content"]
    assert items[-1]["role"] == "user"


def test_runtime_context_keeps_static_prompt_and_injects_date():
    from openai_client import _build_responses_input
    from runtime_context import current_date_note, with_runtime_context

    msgs = with_runtime_context(
        [
            {"role": "system", "content": "Ты Bit-Think"},
            {"role": "user", "content": "привет"},
        ],
        use_skills=False,
    )
    instructions, items = _build_responses_input(msgs)
    assert instructions == "Ты Bit-Think"
    assert items[0]["role"] == "system"
    assert current_date_note()[:10] in items[0]["content"]
    skill_msgs = with_runtime_context(
        [
            {"role": "system", "content": "Ты Bit-Think"},
            {"role": "user", "content": "найди где снято фото"},
        ],
        use_skills=True,
    )
    _, skill_items = _build_responses_input(skill_msgs)
    bodies = " ".join(item["content"] for item in skill_items if item.get("role") == "system")
    assert "Скилы уже подобраны" in bodies
    already = with_runtime_context(
        [
            {"role": "system", "content": "Ты Bit-Think"},
            {"role": "user", "content": "Скилы уже подобраны под этот ход\n# images"},
        ],
        use_skills=True,
    )
    assert sum(1 for m in already if "Скилы уже подобраны" in str(m.get("content"))) == 1


def test_new_screenshot_is_attached_to_latest_question_not_preamble(tmp_path, monkeypatch):
    from app.bot_core.db_conversations import DatabaseConversationManager, MessageData, ConversationData

    manager = DatabaseConversationManager()
    monkeypatch.setattr("app.bot_core.db_conversations.get_settings", lambda: SimpleNamespace(UPLOAD_DIR=tmp_path))

    chat_dir = tmp_path / "chat" / "testuser"
    chat_dir.mkdir(parents=True, exist_ok=True)
    (chat_dir / "old.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32)
    (chat_dir / "new.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x01" * 32)

    conv = ConversationData(
        id="conv_test_2",
        title="Тест",
        messages=[
            MessageData(
                role="user",
                content="old.jpg",
                attachment={
                    "type": "image",
                    "name": "image.png",
                    "url": "/uploads/chat/testuser/old.jpg",
                    "mime_type": "image/jpeg",
                },
            ),
            MessageData(role="user", content="что на скрине?"),
            MessageData(role="assistant", content="Я не вижу нового скриншота в сообщении."),
            MessageData(
                role="user",
                content="image.png",
                attachment={
                    "name": "image.png",
                    "url": "/uploads/chat/testuser/new.jpg",
                    "mime_type": "image/jpeg",
                },
            ),
            MessageData(role="user", content="А здесь что выбрать?"),
        ],
    )
    monkeypatch.setattr(manager, "get_active_conversation", lambda uid: conv)

    api_messages = manager.get_messages_for_api(123, "Ты — полезный ассистент")
    last_user = next(m for m in reversed(api_messages) if m.get("role") == "user")
    assert last_user["content"][0]["text"] == "А здесь что выбрать?"
    image_urls = [
        part["image_url"]["url"]
        for part in last_user["content"]
        if part.get("type") == "image_url"
    ]
    assert len(image_urls) == 1
    decoded = base64.b64decode(image_urls[0].split(",", 1)[1])
    assert decoded.endswith(b"\x01" * 32)
    assert not any(
        isinstance(m.get("content"), list) and m is not last_user
        for m in api_messages
    )


def test_unrelated_followup_does_not_reattach_old_image(tmp_path, monkeypatch):
    from app.bot_core.db_conversations import DatabaseConversationManager, MessageData, ConversationData

    manager = DatabaseConversationManager()
    monkeypatch.setattr("app.bot_core.db_conversations.get_settings", lambda: SimpleNamespace(UPLOAD_DIR=tmp_path))
    chat_dir = tmp_path / "chat" / "testuser"
    chat_dir.mkdir(parents=True, exist_ok=True)
    (chat_dir / "sample.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32)

    conv = ConversationData(
        id="conv_test_3",
        title="Тест",
        messages=[
            MessageData(
                role="user",
                content="sample.jpg",
                attachment={
                    "type": "image",
                    "name": "sample.jpg",
                    "url": "/uploads/chat/testuser/sample.jpg",
                    "mime_type": "image/jpeg",
                },
            ),
            MessageData(role="user", content="что это"),
            MessageData(role="assistant", content="Это синий квадрат"),
            MessageData(role="user", content="какой сейчас курс доллара"),
        ],
    )
    monkeypatch.setattr(manager, "get_active_conversation", lambda uid: conv)

    api_messages = manager.get_messages_for_api(123, "Ты — полезный ассистент")
    assert not any(
        isinstance(m.get("content"), list)
        and any(p.get("type") == "image_url" for p in m.get("content", []) if isinstance(p, dict))
        for m in api_messages
    )
    catalog = "\n".join(str(m.get("content") or "") for m in api_messages if m.get("role") == "system")
    assert "sample.jpg" in catalog


def test_read_chat_document_opens_file_on_demand(monkeypatch):
    import asyncio
    from computer_tools import run_computer_tool

    monkeypatch.setattr(
        "conversations.conversation_manager.get_documents",
        lambda _uid: [{"filename": "report.pdf", "content": "пункт 7. Договор действует до 2030 года. " * 40}],
    )
    text = asyncio.run(run_computer_tool("read_chat_document", {"filename": "report.pdf", "query": "договор"}, user_id=1))
    assert "Договор действует" in text
    missing = asyncio.run(run_computer_tool("read_chat_document", {"filename": "nope.txt"}, user_id=1))
    assert "не найден" in missing.lower()


def test_pdf_text_layer_garbage_is_not_usable():
    from app.bot_core.document_parser import _image_is_blank_or_black, _pdf_text_is_usable

    assert _pdf_text_is_usable("Генеральный директор\nБухгалтер\nВодитель-экспедитор")
    assert not _pdf_text_is_usable("")
    assert not _pdf_text_is_usable("IIIIIIIIIII IIIII I ERS-BITSHIP\n" * 8)
    black = io.BytesIO()
    Image.new("RGB", (200, 120), (0, 0, 0)).save(black, format="JPEG", quality=80)
    assert _image_is_blank_or_black(black.getvalue())


def test_image_only_pdf_ocrs_page_render_not_embedded_jpeg(monkeypatch):
    import fitz
    from app.bot_core import document_parser as parser

    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(40, 40, 280, 90))
    shape.finish(color=(0, 0, 0), fill=(0.15, 0.15, 0.15))
    shape.commit()
    data = doc.tobytes()
    doc.close()

    async def fake_ocr(image_bytes, user_id=None):
        assert image_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        return "ШТАТНОЕ РАСПИСАНИЕ Битшип"

    monkeypatch.setattr(parser, "_ocr_image_via_openai", fake_ocr)
    text = asyncio.run(parser.extract_text_from_pdf(data))
    assert "ШТАТНОЕ РАСПИСАНИЕ" in text

