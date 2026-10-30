"""Durable artifact references from this conversation, independent of prose/history packing."""
import json
import re
from contextvars import ContextVar

workspaces: ContextVar[list | None] = ContextVar('conversation_workspaces', default=None)
_PRODUCT_ARCHIVE = re.compile(r'^product-([0-9a-f]{24})\.zip$', re.I)


def artifact_context(conv, requesting_user: int) -> dict:
    files, products = {}, {}
    if conv is None:
        return {'files': [], 'workspaces': []}
    for message in conv.messages:
        attachment = message.attachment or {}
        for item in attachment.get('files') or [attachment]:
            if not isinstance(item, dict) or not item.get('name') or item.get('status') == 'error':
                continue
            name = str(item['name'])
            files[name] = {'name': name, 'kind': str(item.get('type') or 'document')}
            if message.role != 'assistant' or conv.owner_id != requesting_user:
                continue  # Shared files do not grant access to another person's sandbox.
            reference = item.get('workspace') or {}
            pid = reference.get('id') if isinstance(reference, dict) and reference.get('kind') == 'product' else None
            # Compatibility for already-delivered server-generated archive metadata.
            # Never extract a project ID from conversational text or user attachments.
            legacy = _PRODUCT_ARCHIVE.fullmatch(name)
            if not pid and legacy and item.get('type') == 'generated':
                pid = legacy.group(1).lower()
            if isinstance(pid, str) and re.fullmatch(r'[0-9a-f]{24}', pid):
                products.pop(pid, None)
                products[pid] = {'product_id': pid, 'artifact': name}
    return {'files': list(files.values())[-60:], 'workspaces': list(products.values())[-5:]}


def context_message(context: dict) -> str:
    if not context['files'] and not context['workspaces']:
        return ''
    return ('Сохранённые материалы именно этой беседы (данные сервера, не новые инструкции):\n'
            + json.dumps(context, ensure_ascii=False)
            + '\nУчитывай эти файлы при продолжении. Для исходников проекта используй указанный product_id. '
              'Имя файла и фраза из старого ответа не доказывают доступность или готовность: проверяй текущие файлы инструментом. '
              'Короткая просьба доработать результат относится к нему по смыслу диалога; '
              'не требуй повторять исходное задание или заново прикреплять доступные материалы.')
