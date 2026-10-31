import asyncio
import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from starlette.datastructures import UploadFile, Headers
from starlette.requests import Request
from app.config import get_settings  # noqa: F401
from app.api import documents
from app.services.file_exchange import import_attachment, export_files
from app.services.workspace_fs import collect_deliverables
from app.services.sandbox_client import _parse_deliverables
from conversations import conversation_manager as manager
from turn_scope import turn_conversation, export_paths
import director_router as dr


@pytest.mark.parametrize('name,mime,data', [
    ('music.mp3', 'audio/mpeg', b'ID3-original-audio'),
    ('clip.mp4', 'video/mp4', b'original-video'),
    ('part.blend', 'application/octet-stream', b'BLENDER-original'),
    ('archive.7z', 'application/x-7z-compressed', b'7z-original'),
    ('DATA', 'application/octet-stream', b'opaque'),
    ('empty.custom', 'application/octet-stream', b''),
])
def test_any_upload_preserves_original_and_registers_available_asset(tmp_path, monkeypatch, name, mime, data):
    stored, texts = [], []
    async def model(*args): return 'director'
    async def ensure(*args): return 88001
    async def add_doc(uid, filename, text, **kw): texts.append(text)
    async def add_message(*args, **kwargs):
        stored.append(kwargs['attachment']); return {'attachment': kwargs['attachment']}
    monkeypatch.setattr(documents.repo, 'get_user_model', model)
    monkeypatch.setattr(documents.repo, 'ensure_user', ensure)
    monkeypatch.setattr(documents.repo, 'add_document', add_doc)
    monkeypatch.setattr(documents.repo, 'add_message', add_message)
    monkeypatch.setattr(documents, 'get_settings', lambda: NS(UPLOAD_DIR=tmp_path))
    request = Request({'type': 'http', 'headers': []})
    file = UploadFile(io.BytesIO(data), filename=name, headers=Headers({'content-type': mime}))
    response = asyncio.run(documents.upload_document(request, file, 'chat-1', 'owner'))
    assert response['ok']
    assert (tmp_path / stored[0]['url'].removeprefix('/uploads/')).read_bytes() == data
    assert 'workspace_import_file' in texts[0]
    assert 'не расшифровка' in texts[0]


def test_audio_can_be_imported_into_real_project_assets_without_changing_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKSPACES_DIR', str(tmp_path / 'workspaces'))
    original = tmp_path / 'original.mp3'; original.write_bytes(b'ID3-exact-binary-audio\x00\xff')
    conv = NS(messages=[NS(attachment={'name': 'track.mp3', 'url': '/uploads/source.mp3'})])
    monkeypatch.setattr(manager, 'conversation_for_turn', lambda uid: conv)
    monkeypatch.setattr(manager, '_attachment_disk_path', lambda item: original)
    result = json.loads(import_attachment(88001, 'track.mp3', 'products/site/assets/track.mp3'))
    target = tmp_path / 'workspaces/u88001/products/site/assets/track.mp3'
    assert result['status'] == 'ok' and target.read_bytes() == original.read_bytes()
    assert json.loads(import_attachment(88001, 'track.mp3', result['path']))['sha256'] == result['sha256']
    with pytest.raises(ValueError): import_attachment(88001, 'track.mp3', '../outside.mp3')
    with pytest.raises(ValueError): import_attachment(88001, 'different.mp3')


def test_exports_support_unknown_formats_source_and_empty_files(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKSPACES_DIR', str(tmp_path))
    root = tmp_path / 'u88002'; root.mkdir()
    for name, data in [('model.blend', b'BLEND'), ('track.mp3', b'ID3'), ('requested.py', b'print(1)'), ('EMPTY', b'')]:
        (root / name).write_bytes(data)
    with turn_conversation('chat'):
        export_files(88002, ['model.blend', 'track.mp3', 'requested.py', 'EMPTY'])
        files = _parse_deliverables(collect_deliverables(88002, paths=export_paths()))
    assert {item['filename'] for item in files} == {'model.blend', 'track.mp3', 'requested.py', 'EMPTY'}
    assert next(item['bytes'] for item in files if item['filename'] == 'EMPTY') == b''
    assert export_paths() == []


def test_imported_assets_and_internal_files_are_not_auto_delivered(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKSPACES_DIR', str(tmp_path))
    root = tmp_path / 'u88003'; (root / 'inputs').mkdir(parents=True)
    (root / 'inputs/original.mp3').write_bytes(b'ID3')
    (root / '.env').write_bytes(b'private')
    (root / 'scratch_helper.py').write_bytes(b'print(1)')
    assert json.loads(collect_deliverables(88003)) == []


@pytest.mark.parametrize('kind,expected', [('extract_text','glm-5.3-flash'), ('classify','glm-5.3-flash'), ('file_operation','minimax-m3.1-flash'), ('small_edit','minimax-m3.1-flash')])
def test_semantic_stage_uses_live_economy_workers(monkeypatch, kind, expected):
    monkeypatch.delenv('ORCHESTRATOR_ECONOMY_WORKERS', raising=False)
    monkeypatch.setattr(dr, '_employee_models', lambda uid: list(dr.MODEL_POOL))
    item = {'role': 'Исполнитель', 'task': 'Выполни ограниченный этап', 'model': 'gpt-6-luna', 'work_kind': kind}
    result = dr._clamp_employee_plan({'new_employees': [item]}, 1, 'Обработай входные данные')
    assert result['new_employees'][0]['model'] == expected


def test_glm_is_not_given_visual_or_expert_work(monkeypatch):
    monkeypatch.setattr(dr, '_employee_models', lambda uid: list(dr.MODEL_POOL))
    employee = {'role': 'Чтение', 'task': 'Извлеки поля', 'model': 'gpt-6-luna', 'work_kind': 'extract_text'}
    result = dr._clamp_employee_plan({'new_employees': [employee]}, 1, 'Посмотри фото', has_images=True)
    assert result['new_employees'][0]['model'] != 'glm-5.3-flash'
    employee['model'] = 'gpt-6-sol'
    result = dr._clamp_employee_plan({'new_employees': [employee]}, 1, 'Проверь архитектуру и безопасность сервера')
    assert result['new_employees'][0]['model'] == 'gpt-6-sol'
