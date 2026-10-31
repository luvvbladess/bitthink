"""Original chat assets, not text substitutes. No format conversion or execution."""
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import shutil
import tempfile

MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024
AUDIO_SUFFIXES = {'.mp3', '.wav', '.ogg', '.oga', '.m4a', '.aac', '.flac', '.opus', '.aiff', '.wma'}
VIDEO_SUFFIXES = {'.mp4', '.webm', '.mov', '.m4v', '.mkv', '.avi', '.mpeg', '.mpg', '.3gp'}


def safe_filename(name):
    name = str(name).replace('\\', '/').rsplit('/', 1)[-1]
    return ''.join(char for char in name if ord(char) >= 32)[:255] or 'attachment'


def file_kind(name, mime=''):
    suffix = Path(name).suffix.lower()
    if suffix in AUDIO_SUFFIXES or mime.startswith('audio/'):
        return 'audio'
    if suffix in VIDEO_SUFFIXES or mime.startswith('video/'):
        return 'video'
    return 'file'


def mime_type(name):
    return mimetypes.guess_type(name)[0] or 'application/octet-stream'


def original_file(user_id, filename):
    from conversations import conversation_manager
    conv = conversation_manager.conversation_for_turn(int(user_id))
    for message in reversed(getattr(conv, 'messages', []) if conv else []):
        attachment = getattr(message, 'attachment', None) or {}
        for item in attachment.get('files') or [attachment]:
            if item.get('name') == filename or item.get('filename') == filename:
                source = {**item, 'url': item.get('original_url') or item.get('url')}
                path = conversation_manager._attachment_disk_path(source)
                if path and path.is_file():
                    if path.stat().st_size > MAX_ATTACHMENT_BYTES:
                        raise ValueError('Файл больше 100 МБ.')
                    return path
    raise ValueError('Оригинал не найден в текущей беседе. Проверь точное имя через list_chat_files.')


def import_attachment(user_id, filename, destination=None):
    from app.services.workspace_fs import resolve_in_jail, _dir_size, user_root, QUOTA_BYTES
    source = original_file(user_id, filename)
    digest = hashlib.sha256()
    with source.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    checksum = digest.hexdigest()
    name = safe_filename(filename)
    relative = str(destination or f'inputs/{checksum[:12]}/{name.lstrip(".") or "attachment"}')
    target = resolve_in_jail(int(user_id), relative)
    if target.exists():
        if not target.is_file():
            raise ValueError('Путь занят каталогом.')
        with target.open('rb') as handle:
            existing = hashlib.file_digest(handle, 'sha256').hexdigest()
        if existing != checksum:
            raise ValueError('Файл назначения уже существует с другим содержимым. Выбери новое имя.')
    else:
        if _dir_size(user_root(int(user_id))) + source.stat().st_size > QUOTA_BYTES:
            raise ValueError('Превышен объём рабочей папки.')
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='asset-', suffix='.part', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as output, source.open('rb') as handle:
                shutil.copyfileobj(handle, output, 1024 * 1024)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return json.dumps({'status': 'ok', 'path': relative, 'filename': name, 'size': target.stat().st_size,
                       'sha256': checksum, 'mime_type': mime_type(name),
                       'note': 'Оригинальные байты файла сохранены. Используй этот путь для копирования в assets проекта; не подменяй вложение заглушкой.'}, ensure_ascii=False)


def export_files(user_id, paths):
    from app.services.workspace_fs import resolve_in_jail
    from turn_scope import request_file_export
    if not isinstance(paths, list) or not paths or len(paths) > 200 or any(not isinstance(path, str) for path in paths):
        raise ValueError('Укажи список от 1 до 200 путей файлов.')
    files, total = [], 0
    for relative in dict.fromkeys(paths):
        if not isinstance(relative, str):
            raise ValueError('Путь должен быть строкой.')
        path = resolve_in_jail(int(user_id), relative)
        if not path.is_file():
            raise ValueError('Файл не найден: ' + relative)
        total += path.stat().st_size
        if path.stat().st_size > MAX_ATTACHMENT_BYTES or total > MAX_ATTACHMENT_BYTES:
            raise ValueError('За один ответ можно выдать до 100 МБ файлов. Раздели выдачу на части.')
        files.append({'path': relative, 'name': path.name, 'size': path.stat().st_size})
    # Register only after the complete selection has been validated.
    for item in files:
        request_file_export(item['path'])
    return json.dumps({'status': 'ok', 'files': files, 'note': 'Файлы выбраны для выдачи в текущем ответе.'}, ensure_ascii=False)
