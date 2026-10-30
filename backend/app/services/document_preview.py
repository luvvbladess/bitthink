"""Private, bounded previews. Office files become PDF; only one page is rasterized."""
import hashlib
import threading
from collections import OrderedDict
from pathlib import Path

import fitz

SUPPORTED = {'.pdf', '.doc', '.docx', '.odt', '.rtf', '.xls', '.xlsx', '.ods', '.ppt', '.pptx', '.odp'}
MAX_BYTES = 30 * 1024 * 1024
_cache: OrderedDict[str, bytes] = OrderedDict()
_lock = threading.Lock()


def preview_pdf(data: bytes, filename: str) -> bytes:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError('Предпросмотр этого формата пока недоступен. Файл можно скачать.')
    if len(data) > MAX_BYTES:
        raise ValueError('Для предпросмотра поддерживаются файлы до 30 МБ. Скачайте этот файл.')
    key = hashlib.sha256(suffix.encode() + data).hexdigest()
    # Serialize conversions and bound the private in-memory cache to 60 MB.
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        if suffix == '.pdf':
            result = data
        else:
            from document_parser import convert_office_bytes
            result = convert_office_bytes(data, f'source{suffix}', 'pdf')
        if not result or len(result) > MAX_BYTES:
            raise ValueError('Не удалось подготовить предпросмотр. Попробуйте ещё раз или скачайте файл.')
        try:
            with fitz.open(stream=result, filetype='pdf') as doc:
                if doc.needs_pass or not doc.page_count:
                    raise ValueError('Защищённый или пустой документ нельзя просмотреть.')
        except (RuntimeError, fitz.FileDataError) as exc:
            raise ValueError('Не удалось прочитать документ. Файл можно скачать.') from exc
        while _cache and (len(_cache) >= 4 or sum(map(len, _cache.values())) + len(result) > 2 * MAX_BYTES):
            _cache.popitem(last=False)
        _cache[key] = result
        return result


def preview(data: bytes, filename: str, page: int | None = None):
    pdf = preview_pdf(data, filename)
    with fitz.open(stream=pdf, filetype='pdf') as doc:
        if page is None:
            return {'pages': doc.page_count}
        if page < 1 or page > doc.page_count:
            raise IndexError('Страница не найдена')
        sheet = doc[page - 1]
        scale = min(2.0, 1600 / max(sheet.rect.width, sheet.rect.height, 1))
        return sheet.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes('png')
