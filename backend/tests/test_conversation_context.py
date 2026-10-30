import asyncio
import sys
from types import ModuleType, SimpleNamespace as NS

from app.services import chat_service
from app.services.conversation_context import workspaces


def test_parallel_generations_keep_their_own_artifacts_and_reset_context(monkeypatch):
    ids = {'first': 'a' * 24, 'second': 'b' * 24}
    observed = []
    def view(uid, cid):
        return NS(owner_id=uid, messages=[NS(role='assistant', attachment={
            'name': f'product-{ids[cid]}.zip', 'type': 'generated', 'status': 'done',
            'workspace': {'kind': 'product', 'id': ids[cid]}})])
    async def response(uid, prompt, messages, *args, **kwargs):
        expected = ids[prompt]
        assert workspaces.get()[0]['product_id'] == expected
        context = '\n'.join(item['content'] for item in messages if item['role'] == 'system')
        assert expected in context
        assert ids['second' if prompt == 'first' else 'first'] not in context
        await asyncio.sleep(.01)
        assert workspaces.get()[0]['product_id'] == expected
        observed.append(prompt)
        return 'Ответ', [], '', []
    async def noop(*args, **kwargs):
        return []
    handlers = ModuleType('handlers.core')
    handlers.get_smart_response = response
    handlers.sanitize_response_text = lambda text: text
    monkeypatch.setitem(sys.modules, 'handlers.core', handlers)
    monkeypatch.setattr(chat_service.repo.conversations, 'view', view)
    monkeypatch.setattr(chat_service.repo, 'add_message', noop)
    monkeypatch.setattr(chat_service, 'schedule_memory_refresh', lambda *args: None)
    monkeypatch.setattr('app.services.project_policy.settings', lambda *args: None)
    monkeypatch.setattr('app.services.project_memory.context', lambda *args: '')
    monkeypatch.setattr('app.services.sandbox_client.collect_workspace_files', noop)
    async def run():
        assert not workspaces.get()
        await asyncio.gather(*[
            chat_service._generate_and_send(uid, f'{name}@example.com', name, [], noop, noop, noop, noop, noop, conversation_id=name)
            for uid, name in [(9911, 'first'), (9912, 'second')]
        ])
        assert not workspaces.get()
    asyncio.run(run())
    assert sorted(observed) == ['first', 'second']


def test_generated_product_metadata_is_persisted(monkeypatch, tmp_path):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), 'UPLOAD_DIR', tmp_path)
    item = asyncio.run(chat_service._persist_generated_file('context@example.com', 'product-' + 'c' * 24 + '.zip', b'archive'))
    assert item['workspace'] == {'kind': 'product', 'id': 'c' * 24}
    assert item['url'].startswith('/uploads/generated/')
