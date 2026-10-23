"""Native draw.io generation/export in the isolated Computer sandbox (stdlib only)."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import urllib.parse
import xml.etree.ElementTree as ET

EXPORT_SLOTS = threading.BoundedSemaphore(1)
DIAGRAM_SPEC = (
    'diagram_create',
    'Создать блок-схему/алгоритм/диаграмму diagrams.net (draw.io) и готовые файлы. '
    'Работает на сервере в веб-версии и локально в новом BitClient. '
    'path — НОВЫЙ относительный .drawio. xml — полный НЕСЖАТЫЙ XML mxfile с diagram/mxGraphModel/root, '
    'mxCell id=0 и id=1 parent=0, фигурами vertex=1 parent=1, mxGeometry x/y/width/height as=geometry, '
    'стрелками edge=1 source/target parent=1 и mxGeometry relative=1 as=geometry. '
    'Для ромба style=rhombus;whiteSpace=wrap;html=1; для действия rounded=0;whiteSpace=wrap;html=1; '
    'для начала/конца rounded=1;whiteSpace=wrap;html=1; для стрелки edgeStyle=orthogonalEdgeStyle;endArrow=block;html=1;. '
    'Указывай читаемые размеры/координаты, fontSize=16, короткие подписи, Да/Нет на ветвях, корректно экранируй XML. '
    'Вместо xml можно source_path существующей НЕСЖАТОЙ .drawio/.xml в песочнице для экспорта копии. '
    'formats: pdf,png,svg,drawio, по умолчанию pdf,png; .drawio выдаётся всегда. PDF — все страницы, '
    'PNG/SVG — page_index с 1, по умолчанию первая. '
    'Настоящий движок draw.io, без отправки схем сторонним сервисам. Файлы появятся вложениями в ответе. '
    'Проверь логические связи, отсутствие обрезанного текста и пересечений. При ошибке исправь XML и повтори. '
    'Не подменяй файлы кодовым блоком Mermaid/инструкцией ручного экспорта. Не перезаписывает файлы.',
    {'path': {'type': 'string'}, 'xml': {'type': 'string'}, 'source_path': {'type': 'string'},
     'formats': {'type': 'array', 'items': {'type': 'string', 'enum': ['drawio', 'pdf', 'png', 'svg']}},
     'page_index': {'type': 'integer', 'minimum': 1}},
    ['path'],
)


def validate_xml(xml: str) -> int:
    if not isinstance(xml, str) or not xml.strip() or len(xml.encode('utf-8')) > 5_000_000:
        raise ValueError('Нужен draw.io XML до 5 МБ.')
    if re.search(r'<!DOCTYPE|<!ENTITY', xml, re.I):
        raise ValueError('DTD/entities в схеме запрещены.')
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError('Некорректный XML схемы: ' + str(exc)) from exc
    if root.tag not in {'mxfile', 'mxGraphModel'}:
        raise ValueError('Нужен корневой mxfile или mxGraphModel.')
    pages = list(root.findall('diagram')) if root.tag == 'mxfile' else [root]
    if not 1 <= len(pages) <= 30:
        raise ValueError('Нужно от 1 до 30 страниц.')
    for page in pages:
        model = page.find('mxGraphModel') if page.tag == 'diagram' else page
        if model is None:
            raise ValueError('Нужен несжатый mxGraphModel: пересоздай XML с фигурами и координатами.')
        cells = list(model.iter('mxCell'))
        ids = [cell.get('id') for cell in cells]
        if not ids or None in ids or len(ids) != len(set(ids)) or len(cells) > 2000:
            raise ValueError('Каждой фигуре нужен уникальный id; до 2000 элементов на странице.')
        if not any(cell.get('vertex') == '1' for cell in cells):
            raise ValueError('Страница не содержит фигур.')
        for cell in cells:
            for key in ('source', 'target', 'parent'):
                if cell.get(key) is not None and cell.get(key) not in ids:
                    raise ValueError(f'Неизвестный {key} у элемента {cell.get("id")}.')
        # Chromium does not inherit Python's network guard. Diagrams are self-contained:
        # do not let labels/images cause requests to internal services or local files.
        for item in model.iter():
            for value in item.attrib.values():
                value = html.unescape(urllib.parse.unquote(value))
                if re.search(r'(?:https?|ftp|file|javascript|data):|//|image\s*=|<\s*(?:img|script|iframe|object|embed)|url\s*\(', value, re.I):
                    raise ValueError('Используй самодостаточную схему без внешних изображений/ссылок/скриптов.')
    return len(pages)


def _export(command: list[str], cwd: Path, home: Path) -> None:
    options = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NO_WINDOW}
    env = dict(os.environ)
    if os.name != 'nt':
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'), XDG_CACHE_HOME=str(home / 'cache'))
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log, **options)
        try:
            code = process.wait(timeout=55)
        except subprocess.TimeoutExpired:
            if os.name != 'nt':
                os.killpg(process.pid, signal.SIGKILL)
            else:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            process.wait()
            raise ValueError('draw.io: экспорт не завершён за 55 секунд. Упрости или раздели схему.')
        if code:
            log.seek(0)
            raise ValueError('Ошибка draw.io: ' + log.read(2000).decode('utf-8', 'replace'))


def create_diagram(user_id: int, args: dict) -> str:
    try:
        import workspace_fs as workspace
    except ImportError:
        from app.services import workspace_fs as workspace
    if bool(args.get('xml')) == bool(args.get('source_path')):
        raise ValueError('Укажи xml ИЛИ source_path.')
    root = workspace.user_root(user_id)
    target = workspace.resolve_in_jail(user_id, str(args.get('path') or 'Схема.drawio'))
    if target.suffix.lower() != '.drawio':
        raise ValueError('path должен заканчиваться на .drawio.')
    xml = args.get('xml')
    if args.get('source_path'):
        source = workspace.resolve_in_jail(user_id, str(args['source_path']))
        if source.suffix.lower() not in {'.drawio', '.xml'} or source.stat().st_size > 5_000_000:
            raise ValueError('Исходник должен быть .drawio/.xml до 5 МБ.')
        xml = source.read_text(encoding='utf-8-sig')
    pages = validate_xml(xml)
    formats = args.get('formats', ['pdf', 'png'])
    if not isinstance(formats, list) or len(formats) > 4 or any(f not in {'drawio', 'pdf', 'png', 'svg'} for f in formats):
        raise ValueError('formats: массив pdf,png,svg,drawio.')
    formats = list(dict.fromkeys(['drawio', *formats]))
    page = args.get('page_index', 1)
    if type(page) is not int or not 1 <= page <= pages:
        raise ValueError(f'page_index должен быть от 1 до {pages}.')
    targets = [target.with_suffix('.' + fmt) for fmt in formats]
    if any(p.exists() or p.is_symlink() for p in targets):
        raise ValueError('Файл уже существует. Выбери новое имя .drawio для всего комплекта.')
    exe = os.environ.get('DRAWIO_BINARY') or shutil.which('drawio')
    if len(formats) > 1 and not exe:
        raise ValueError('Движок draw.io не установлен в песочнице; требуется обновить образ sandbox.')
    if workspace._dir_size(root) + 40_000_000 > workspace.QUOTA_BYTES:
        raise ValueError('Недостаточно места в песочнице для экспорта схемы.')
    if not EXPORT_SLOTS.acquire(timeout=5):
        raise ValueError('Экспорт схем занят. Повтори вызов через несколько секунд.')
    published = []
    try:
        with tempfile.TemporaryDirectory(prefix='bt-diagram-') as folder:
            stage = Path(folder)
            source = stage / 'source.drawio'
            source.write_text(xml, encoding='utf-8', newline='\n')
            prepared = [source]
            for fmt in formats[1:]:
                output = stage / ('export.' + fmt)
                command = [str(exe), '--disable-update', '--disable-gpu', '--user-data-dir=' + str(stage / 'profile'),
                           '--export', '--format', fmt, '--output', str(output), '--border', '24', '--embed-diagram']
                if os.name != 'nt':
                    command = ['xvfb-run', '-a', *command, '--no-sandbox', '--disable-dev-shm-usage']
                command += ['--all-pages', '--crop'] if fmt == 'pdf' else ['--page-index', str(page)]
                if fmt == 'png':
                    command += ['--scale', '2']
                _export([*command, str(source)], root, stage)
                if not output.is_file() or not 50 <= output.stat().st_size <= workspace.MAX_FILE_BYTES:
                    raise ValueError(f'Не создан {fmt} или файл превышает лимит 8 МБ. Упрости схему.')
                data = output.read_bytes()
                if ((fmt == 'pdf' and not data.startswith(b'%PDF-')) or
                        (fmt == 'png' and not data.startswith(b'\x89PNG\r\n\x1a\n')) or
                        (fmt == 'svg' and b'<svg' not in data)):
                    raise ValueError('Некорректный файл экспорта ' + fmt)
                prepared.append(output)
            target.parent.mkdir(parents=True, exist_ok=True)
            for ready, destination in zip(prepared, targets):
                with destination.open('xb') as stream:
                    published.append(destination)
                    stream.write(ready.read_bytes())
        return json.dumps({'path': target.relative_to(root).as_posix(),
                           'files': [p.relative_to(root).as_posix() for p in targets], 'pages': pages,
                           'image_page': page, 'editable': True,
                           'hint': 'PDF: все страницы. PNG/SVG: выбранная страница. .drawio: редактируется в diagrams.net.'}, ensure_ascii=False)
    except BaseException:
        for item in published:
            item.unlink(missing_ok=True)
        raise
    finally:
        EXPORT_SLOTS.release()
