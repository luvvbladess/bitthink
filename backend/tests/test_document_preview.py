import asyncio

import fitz
import pytest
from fastapi import HTTPException

from app.services import document_preview as service


def pdf_bytes():
    with fitz.open() as doc:
        doc.new_page().insert_text((50, 60), 'First page')
        doc.new_page().insert_text((50, 60), 'Second page')
        return doc.tobytes()


def test_pdf_pages_are_bounded_images_and_invalid_pages_fail():
    data = pdf_bytes()
    assert service.preview(data, 'Report.pdf') == {'pages': 2}
    image = service.preview(data, 'Report.pdf', 2)
    pixmap = fitz.Pixmap(image)
    assert max(pixmap.width, pixmap.height) <= 1600
    assert image.startswith(b'\x89PNG')
    for page in (0, 3):
        with pytest.raises(IndexError):
            service.preview(data, 'Report.pdf', page)


def test_office_conversion_cache_changes_with_content(monkeypatch):
    import document_parser
    service._cache.clear()
    calls = []
    def convert(data, name, ext):
        calls.append((data, name, ext))
        return pdf_bytes()
    monkeypatch.setattr(document_parser, 'convert_office_bytes', convert)
    for name in ('Report.docx', 'Report.xlsx', 'Report.pptx'):
        assert service.preview(b'v1', name)['pages'] == 2
        service.preview(b'v1', name, 1)
    assert len(calls) == 3
    service.preview(b'v2', 'Report.docx')
    assert len(calls) == 4


def test_invalid_protected_and_unsupported_documents(monkeypatch):
    with pytest.raises(ValueError):
        service.preview(b'garbage', 'report.pdf')
    with pytest.raises(ValueError):
        service.preview(b'archive', 'report.zip')
    monkeypatch.setattr(service, 'MAX_BYTES', 2)
    with pytest.raises(ValueError, match='30'):
        service.preview(b'large', 'report.pdf')
    monkeypatch.undo()
    with fitz.open() as doc:
        doc.new_page()
        data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='secret')
    with pytest.raises(ValueError, match='Защищённый'):
        service.preview(data, 'secret.pdf')


def test_endpoint_checks_membership_before_reading_bytes(monkeypatch):
    from app.api import editor, conversations
    reads = []
    async def denied(*args):
        raise HTTPException(status_code=404)
    monkeypatch.setattr(editor, '_conversation_for', denied)
    monkeypatch.setattr(editor, 'file_bytes', lambda *args: reads.append(args))
    with pytest.raises(HTTPException) as error:
        asyncio.run(conversations.preview_conversation_file('other-chat', 'report.pdf', user_id='guest'))
    assert error.value.status_code == 404
    assert reads == []


def test_endpoint_serves_private_pages_and_current_download_link(monkeypatch):
    from app.api import editor, conversations
    async def allowed(*args):
        return 1, object()
    monkeypatch.setattr(editor, '_conversation_for', allowed)
    monkeypatch.setattr(editor, 'file_bytes', lambda *args: pdf_bytes())
    monkeypatch.setattr(editor, 'sign_file_link', lambda *args: 'signed')
    response = asyncio.run(conversations.preview_conversation_file('mine', 'report.pdf', user_id='owner'))
    assert b'"pages":2' in response.body
    assert b'/conversations/mine/files/download?t=signed' in response.body
    image = asyncio.run(conversations.preview_conversation_file('mine', 'report.pdf', page=1, user_id='owner'))
    assert image.media_type == 'image/png'
    assert image.headers['cache-control'] == 'private, no-store'
    assert image.body.startswith(b'\x89PNG')
