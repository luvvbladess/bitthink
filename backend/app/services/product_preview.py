"""Bounded static previews; archived code is copied as data and never run on the server."""
import hashlib
import json
import io
import re
import shutil
import stat
import uuid
import zipfile
from pathlib import PurePosixPath
from html.parser import HTMLParser

WEB_SUFFIXES = {'.html', '.htm', '.css', '.js', '.mjs', '.json', '.svg', '.png', '.jpg', '.jpeg',
                '.gif', '.webp', '.avif', '.ico', '.woff', '.woff2', '.ttf', '.otf', '.wasm',
                '.mp4', '.webm', '.mp3', '.wav', '.ogg', '.glsl', '.vert', '.frag', '.txt'}


def preview_html(page, base):
    offsets = [0]
    for line in page.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    edits = []
    class Page(HTMLParser):
        head = False
        def handle_starttag(self, tag, attrs):
            raw = self.get_starttag_text()
            line, column = self.getpos()
            start = offsets[line - 1] + column
            replacement = '' if tag == 'base' else re.sub(
                r'(\b(?:src|href|poster)\s*=\s*)(["\'])(/(?!/)[^"\']*)\2',
                lambda m: m[1] + m[2] + base + m[3].lstrip('/') + m[2], raw, flags=re.I)
            if tag == 'head' and not self.head:
                replacement += f'<base href="{base}">'
                self.head = True
            if replacement != raw:
                edits.append((start, start + len(raw), replacement))
        handle_startendtag = handle_starttag
    parser = Page(convert_charrefs=False)
    parser.feed(page)
    output, cursor = [], 0
    for start, end, replacement in edits:
        output.extend((page[cursor:start], replacement))
        cursor = end
    output.append(page[cursor:])
    return ('' if parser.head else f'<base href="{base}">') + ''.join(output)


def create(web_user_id, filename, data):
    match = re.fullmatch(r'product-([0-9a-f]{24})\.zip', filename)
    if not match:
        return None
    from app.config import get_settings
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > 620 or sum(i.file_size for i in infos) > 35 * 1024 * 1024:
            raise ValueError('Preview archive is too large')
        members = {}
        for info in infos:
            path = PurePosixPath(info.filename)
            if (path.is_absolute() or '\\' in info.orig_filename or '\x00' in info.orig_filename or '..' in path.parts
                    or ':' in info.filename or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError('Unsafe preview member')
            if info.is_dir():
                continue
            if str(path) in members:
                raise ValueError('Duplicate preview member')
            members[str(path)] = info
        entry = next((name for name in ('dist/index.html', 'build/index.html', 'index.html') if name in members), None)
        if not entry:
            return None
        workspace = {'kind': 'product', 'id': match[1]}
        version = members.get('BITTHINK_VERSION.json')
        if version and version.file_size <= 1024:
            try:
                lineage = json.loads(archive.read(version))
                if isinstance(lineage, dict) and lineage.get('product_id') == match[1]:
                    for field in ('revision', 'previous_revision'):
                        digest = lineage.get(field)
                        if isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest):
                            workspace[field] = digest
            except (ValueError, UnicodeError):
                pass
        page = archive.read(members[entry]).decode('utf-8-sig')
        # shortcut: preview built browser files only; a source-only TS/JSX project needs its build output.
        if re.search(r'<script\b[^>]*\bsrc\s*=\s*["\'][^"\']+\.(?:tsx?|jsx)(?:[?"\'])', page, re.I):
            return None
        user_key = hashlib.sha256(web_user_id.encode()).hexdigest()[:16]
        key = uuid.uuid4().hex
        base = f'/uploads/previews/{user_key}/{key}/'
        root = get_settings().UPLOAD_DIR / 'previews' / user_key / key
        prefix = PurePosixPath(entry).parent
        # srcdoc has the chat's base URL; retain the project's own asset directory instead.
        page = preview_html(page, base)
        root.mkdir(parents=True)
        try:
            for name, info in members.items():
                path = PurePosixPath(name)
                if not path.is_relative_to(prefix) or path.suffix.lower() not in WEB_SUFFIXES:
                    continue
                relative = path.relative_to(prefix)
                target = root / str(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(page.encode() if name == entry else archive.read(info))
        except BaseException:
            shutil.rmtree(root)
            raise
    name = f'product-{match[1]}-preview.html'
    return name, page.encode(), {'name': name, 'size': len(page.encode()), 'type': 'generated',
        'status': 'done', 'url': base + 'index.html', 'canvas': True,
        'workspace': workspace}
