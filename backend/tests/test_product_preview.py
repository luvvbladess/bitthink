import asyncio
import io
import json
import stat
import zipfile
from types import ModuleType
import sys

import pytest
from app.config import get_settings
from app.services.product_preview import create, preview_html

NAME = 'product-' + 'a' * 24 + '.zip'


def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        for name, data in files.items():
            info = zipfile.ZipInfo('member');info.filename = name
            z.writestr(info, data)
    return output.getvalue()


def test_preview_preserves_local_assets_and_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), 'UPLOAD_DIR', tmp_path)
    result = create('owner@example.invalid', NAME, archive({'index.html': '<html><head></head><body><script defer src="src/app.js"></script></body></html>',
        'src/app.js': 'window.ready = true;', 'fonts/font.woff2': b'font', '.env': 'PRIVATE'}))
    name, data, meta = result
    assert meta['canvas'] and meta['workspace'] == {'kind': 'product', 'id': 'a' * 24}
    assert name.endswith('-preview.html')
    root = tmp_path / meta['url'].removeprefix('/uploads/')
    assert root.read_bytes() == data
    assert (root.parent / 'src/app.js').read_text() == 'window.ready = true;'
    assert (root.parent / 'fonts/font.woff2').read_bytes() == b'font'
    assert not (root.parent / '.env').exists()
    assert data.count(b'<base ') == 1 and b'<script defer src="src/app.js">' in data


def test_html_rewriting_never_changes_inline_script_and_handles_base():
    original = '<html><head><base href="/wrong/"><script>const s = `href="/keep"`;</script></head><body><img src="/assets/x.png"></body></html>'
    page = preview_html(original, '/uploads/previews/demo/')
    assert 'const s = `href="/keep"`;' in page
    assert '<base href="/uploads/previews/demo/">' in page
    assert 'src="/uploads/previews/demo/assets/x.png"' in page
    assert '/wrong/' not in page and page.count('<base') == 1


@pytest.mark.parametrize('path', ['../escape.js', '/escape.js', 'a/../../escape.js', 'a\\escape.js', 'C:/escape.js'])
def test_archive_traversal_is_rejected(tmp_path, monkeypatch, path):
    monkeypatch.setattr(get_settings(), 'UPLOAD_DIR', tmp_path)
    with pytest.raises(ValueError):
        create('owner', NAME, archive({'index.html': '<html></html>', path: 'escape'}))
    assert not list(tmp_path.iterdir())


def test_symlinks_and_zip_bombs_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), 'UPLOAD_DIR', tmp_path)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        link = zipfile.ZipInfo('index.html');link.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(link, '../../secret')
    with pytest.raises(ValueError):create('owner', NAME, output.getvalue())
    with pytest.raises(ValueError):create('owner', NAME, archive({str(i)+'.js': 'x' for i in range(621)}))


def test_non_web_and_source_only_projects_get_no_fake_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), 'UPLOAD_DIR', tmp_path)
    assert create('owner', 'sources.zip', b'not a zip') is None
    assert create('owner', NAME, archive({'main.py': 'print(1)'})) is None
    assert create('owner', NAME, archive({'index.html': '<script type="module" src="/src/main.tsx"></script>'})) is None


def test_preview_assets_allow_opaque_canvas_origin_but_sandbox_direct_navigation(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    monkeypatch.setattr(get_settings(), 'UPLOAD_DIR', tmp_path)
    _, _, meta = create('owner', NAME, archive({'index.html': '<html><head></head></html>', 'app.mjs': 'export const x = 1;'}))
    client = TestClient(create_app())
    for url in [meta['url'], meta['url'].replace('index.html', 'app.mjs')]:
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers['access-control-allow-origin'] == '*'
        assert response.headers['content-security-policy'] == 'sandbox allow-scripts allow-downloads'
        assert response.headers['x-content-type-options'] == 'nosniff'


def test_product_archive_and_preview_are_both_persisted_and_delivered(tmp_path, monkeypatch):
    from app.services import chat_service
    monkeypatch.setattr(get_settings(), 'UPLOAD_DIR', tmp_path)
    data = archive({'index.html': '<html><head></head><body>Simulation</body></html>'})
    async def response(*args, **kwargs):return 'Готово.', [{'filename': NAME, 'bytes': data}], '', []
    handlers = ModuleType('handlers.core');handlers.get_smart_response = response;handlers.sanitize_response_text = lambda s:s
    monkeypatch.setitem(sys.modules, 'handlers.core', handlers)
    saved, delivered = [], []
    async def persist(*args, **kwargs):saved.append(kwargs)
    async def no_files(*args):return []
    async def noop(*args):pass
    async def file(*args):delivered.append(args)
    monkeypatch.setattr(chat_service.repo, 'add_message', persist)
    monkeypatch.setattr(chat_service, 'schedule_memory_refresh', lambda *args:None)
    monkeypatch.setattr('app.services.sandbox_client.collect_workspace_files', no_files)
    asyncio.run(chat_service._generate_and_send(1,'preview@example.invalid','Сделай сайт',[],noop,noop,file,noop,noop))
    files = saved[-1]['attachment']['files']
    assert len(files) == 2 and files[0]['name'] == NAME and files[1]['canvas']
    assert files[1]['url'].startswith('/uploads/previews/')
    assert len(delivered) == 2 and delivered[1][-1] == files[1]['url']


def test_preview_retains_revision_lineage(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), 'UPLOAD_DIR', tmp_path)
    version = {'product_id': 'a' * 24, 'revision': 'b' * 64, 'previous_revision': 'c' * 64}
    _, _, meta = create('owner', NAME, archive({
        'index.html': '<html></html>',
        'BITTHINK_VERSION.json': json.dumps(version),
    }))
    assert meta['workspace'] == {'kind': 'product', 'id': 'a' * 24,
                                 'revision': 'b' * 64, 'previous_revision': 'c' * 64}
