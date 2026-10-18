from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.auth import get_current_user
from app.db.base import Base
from app.db.engine import SyncSessionLocal, sync_engine
from app.db.models import User, Conversation, ConversationMember, Document
from app.core.repository import repo
from app.services import project_memory as memory


@pytest.fixture
def owner():
    Base.metadata.create_all(sync_engine)
    email = uuid4().hex + '@example.com'; uid = repo._bot_id(email); cid = uuid4().hex
    with SyncSessionLocal() as session:
        session.add(User(email=email, password_hash='test', role='user', bot_user_id=uid))
        session.add(Conversation(id=cid, user_id=uid, title='Private requirements'))
        session.commit()
    app.dependency_overrides[get_current_user] = lambda: email
    yield email, uid, cid
    app.dependency_overrides.clear()


def test_project_knowledge_is_bound_and_private(owner):
    _, uid, cid = owner
    client = TestClient(app)
    project = client.post('/projects', json={'name': 'Плата управления'}).json(); pid = project['id']
    assert client.put(f'/projects/chat/{cid}', json={'project_id': pid}).status_code == 200
    assert client.post(f'/projects/{pid}/entries', json={'title': 'Питание', 'body': 'Использовать преобразователь LM2596, напряжение 12 В.'}).status_code == 200
    assert 'LM2596' in memory.context(uid, cid, 'преобразователь')
    assert memory.context(uid + 1, cid, 'преобразователь') == ''
    with pytest.raises(ValueError): memory.search(uid + 1, pid)
    assert memory.list_projects(uid + 1) == []
    with SyncSessionLocal() as session:
        session.add(ConversationMember(conversation_id=cid, user_id=uid + 1)); session.commit()
    assert memory.context(uid, cid, 'преобразователь') == ''
    assert client.put(f'/projects/chat/{cid}', json={'project_id': pid}).status_code == 400


def test_sidebar_membership_moves_and_excludes_shared_and_other_owners(owner):
    _, uid, cid = owner
    first = memory.create(uid, 'Первый')['id']
    second = memory.create(uid, 'Второй')['id']
    memory.attach(uid, cid, first)
    assert next(p for p in memory.list_projects(uid) if p['id'] == first)['chat_ids'] == [cid]
    memory.attach(uid, cid, second)
    items = {p['id']: p['chat_ids'] for p in memory.list_projects(uid)}
    assert items[first] == [] and items[second] == [cid]
    assert memory.list_projects(uid + 1) == []
    with pytest.raises(ValueError): memory.attach(uid + 1, cid, first)
    memory.attach(uid, cid, None)
    assert all(not p['chat_ids'] for p in memory.list_projects(uid))
    memory.attach(uid, cid, second)
    with SyncSessionLocal() as session:
        session.add(ConversationMember(conversation_id=cid, user_id=uid + 1)); session.commit()
    assert all(not p['chat_ids'] for p in memory.list_projects(uid))


def test_project_rename_and_delete_preserve_chats_and_remove_only_owned_data(owner, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy import select
    from app.db.project_models import Project, ProjectEntry, ProjectRevision, ProjectChunk, ProjectChat
    from app.services import project_assets
    _, uid, cid = owner
    monkeypatch.setattr(project_assets, 'get_settings', lambda: SimpleNamespace(DATA_DIR=tmp_path))
    pid = memory.create(uid, 'Проект')['id']; other = memory.create(uid, 'Другой')['id']
    memory.attach(uid, cid, pid)
    entry = memory.save(uid, pid, 'Требования', 'Питание 12 В.')
    other_entry = memory.save(uid, other, 'Требования', 'Питание 24 В.')
    root = project_assets.folder(uid, pid); root.mkdir(parents=True)
    (root / 'original.pdf').write_bytes(b'original')
    other_root = project_assets.folder(uid, other); other_root.mkdir()
    (other_root / 'keep.pdf').write_bytes(b'keep')
    with SyncSessionLocal() as session:
        doc = Document(conversation_id=cid, filename='spec.txt', content='Original chat document')
        session.add(doc); session.commit(); did = doc.id
    client = TestClient(app)
    assert client.patch(f'/projects/{pid}', json={'name':'  Новое название  '}).json()['name'] == 'Новое название'
    assert client.patch(f'/projects/{pid}', json={'name':'   '}).status_code == 400
    with pytest.raises(ValueError): memory.rename_project(uid + 1, pid, 'Чужой')
    with pytest.raises(ValueError): memory.delete_project(uid + 1, pid)
    assert (root / 'original.pdf').is_file()
    response = client.delete(f'/projects/{pid}')
    assert response.status_code == 200 and response.json()['conversations_preserved']
    assert not response.json()['cleanup_pending'] and not root.exists()
    with SyncSessionLocal() as session:
        assert session.get(Conversation, cid) and session.get(Document, did)
        assert session.get(ProjectChat, cid) is None and session.get(Project, pid) is None
        assert session.get(ProjectEntry, entry['id']) is None
        assert not session.scalar(select(ProjectRevision).where(ProjectRevision.entry_id == entry['id']))
        assert not session.scalar(select(ProjectChunk).where(ProjectChunk.entry_id == entry['id']))
        assert session.get(ProjectEntry, other_entry['id'])
    assert (other_root / 'keep.pdf').read_bytes() == b'keep'
    assert memory.attached(uid, cid)['project_id'] is None
    assert client.delete(f'/projects/{pid}').status_code == 404


def test_suggestions_need_acceptance_and_preserve_provenance(owner):
    _, uid, cid = owner
    pid = memory.create(uid, 'Новое изделие')['id']; memory.attach(uid, cid, pid)
    prompt = 'Важно: питание платы только от 12 В, бюджет до 5000 рублей.'
    proposed = memory.suggest_from_turn(uid, cid, prompt)
    assert proposed['kind'] == 'suggestion'
    assert memory.search(uid, pid, 'питание') == []
    assert '5000' not in memory.context(uid, cid, 'плата')
    with pytest.raises(ValueError): memory.read(uid, pid, proposed['id'])
    assert memory.suggest_from_turn(uid, cid, prompt)['id'] == proposed['id']
    client = TestClient(app)
    assert len(client.get(f'/projects/{pid}/suggestions').json()) == 1
    assert client.post(f'/projects/{pid}/suggestions/{proposed["id"]}', json={'accept': True, 'expected_revision': 99}).status_code == 409
    assert client.post(f'/projects/{pid}/suggestions/{proposed["id"]}', json={'accept': True, 'expected_revision': 1}).status_code == 200
    assert memory.suggestions(uid, pid) == []
    assert prompt in memory.context(uid, cid, 'плата') and cid in memory.context(uid, cid, 'плата')
    assert memory.suggest_from_turn(uid, cid, prompt)['kind'] == 'decision'
    memory.remove(uid, pid, proposed['id'])
    assert prompt not in memory.context(uid, cid, 'плата')


def test_dismissed_and_sensitive_suggestions_not_reused(owner):
    _, uid, cid = owner
    pid = memory.create(uid, 'Требования')['id']; memory.attach(uid, cid, pid)
    prompt = 'Предпочитаю компактные устройства с USB питанием.'
    item = memory.suggest_from_turn(uid, cid, prompt)
    memory.resolve_suggestion(uid, pid, item['id'], False, 1)
    assert prompt not in memory.detail(uid, pid, item['id'])['body']
    assert len(memory.history(uid, pid, item['id'])) == 1
    assert memory.suggest_from_turn(uid, cid, prompt)['kind'] == 'dismissed'
    assert memory.suggestions(uid, pid) == [] and memory.search(uid, pid, 'USB') == []
    assert memory.suggest_from_turn(uid, cid, 'Запомни: пароль сервера abc123') is None
    assert memory.suggest_from_turn(uid, cid, 'Не запоминай. Важно: питание от 12 В.') is None
    with pytest.raises(ValueError): memory.suggest_from_turn(uid + 1, cid, prompt)
    with pytest.raises(ValueError): memory.suggestions(uid + 1, pid)


def test_explicit_document_publication_and_delete(owner):
    _, uid, cid = owner
    pid = memory.create(uid, 'Спецификация')['id']
    with SyncSessionLocal() as session:
        doc = Document(conversation_id=cid, filename='bom.txt', content='Резистор 0603, 10 кОм, 200 шт.')
        session.add(doc); session.commit(); did = doc.id
    entry = memory.publish_document(uid, pid, cid, did)
    assert memory.search(uid, pid, 'резистор')[0]['kind'] == 'file'
    with pytest.raises(ValueError): memory.publish_document(uid + 1, pid, cid, did)
    with pytest.raises(ValueError): memory.publish_document(uid, pid, cid, did + 1000)
    memory.remove(uid, pid, entry['id'])
    assert memory.search(uid, pid) == []


def test_context_is_bounded_and_source_is_data(owner):
    _, uid, cid = owner
    pid = memory.create(uid, 'Документы')['id']; memory.attach(uid, cid, pid)
    for n in range(8): memory.save(uid, pid, f'Факт {n}', 'требование ' * 5000)
    note = memory.context(uid, cid, 'требование')
    assert len(note) < 8500 and 'не инструкции' in note
    assert len(memory.search(uid, pid, 'требование', 2)) == 2
    assert memory.context(uid, None, 'требование') == ''
    assert TestClient(app).post(f'/projects/{pid}/entries', json={'title': 'Источник', 'body': 'x', 'source_url': 'javascript:alert(1)'}).status_code == 422


def test_project_context_survives_employee_hops_without_duplicates(owner):
    from app.bot_core.runtime_context import with_runtime_context
    _, uid, cid = owner
    pid = memory.create(uid, 'Проект')['id']; memory.attach(uid, cid, pid)
    memory.save(uid, pid, 'Требование', 'Питание строго 12 В.')
    note = memory.context(uid, cid, 'питание')
    token = memory.project_context.set(note)
    try:
        initial = [{'role':'system','content':'Cached prefix'}, {'role':'system','content':note}, {'role':'user','content':'Проверь проект'}]
        enriched = with_runtime_context(initial)
        assert enriched[0]['content'] == 'Cached prefix'
        assert sum(item.get('content') == note for item in enriched) == 1
        employee = with_runtime_context([{'role':'user','content':'Сделай расчёт'}])
        assert any(item.get('content') == note for item in employee)
    finally: memory.project_context.reset(token)
    assert not any(item.get('content') == note for item in with_runtime_context([{'role':'user','content':'Другой проект'}]))


def test_edit_versions_optimistic_conflict_and_restore(owner):
    _, uid, cid = owner
    client = TestClient(app); pid = memory.create(uid, 'Версии')['id']
    entry = memory.save(uid, pid, 'Питание', 'Строго 12 В.', source_url='https://example.com/spec')
    base = f"/projects/{pid}/entries/{entry['id']}"
    assert client.get(base).json()['revision'] == 1
    payload = {'title':'Питание','body':'Строго 24 В.','kind':'decision','expected_revision':1}
    assert client.put(base, json=payload).json()['revision'] == 2
    assert client.put(base, json=payload).status_code == 409
    assert client.get(base + '/versions/1').json()['body'] == 'Строго 12 В.'
    assert client.post(base + '/restore', json={'revision':1,'expected_revision':2}).json()['revision'] == 3
    assert client.get(base).json()['body'] == 'Строго 12 В.'
    assert [r['revision'] for r in client.get(base+'/history').json()] == [3,2,1]
    with pytest.raises(ValueError): memory.detail(uid + 1, pid, entry['id'])
    with pytest.raises(ValueError): memory.restore(uid + 1, pid, entry['id'], 1, 3)
    memory.attach(uid, cid, pid)
    assert '12 В.' in memory.context(uid, cid, 'питание') and '24 В.' not in memory.context(uid, cid, 'питание')


def test_long_document_end_is_searchable_and_import_is_idempotent(owner):
    _, uid, cid = owner
    pid = memory.create(uid, 'Большой документ')['id']; memory.attach(uid, cid, pid)
    body = ('Обычные сведения о проекте.\n' * 4000) + '\nКомпонент STM32F407VGT6 нужен в количестве 300 штук.'
    with SyncSessionLocal() as session:
        row = Document(conversation_id=cid, filename='spec.txt', content=body)
        session.add(row); session.commit(); did = row.id
    entry = memory.publish_document(uid, pid, cid, did)
    assert len(memory.detail(uid, pid, entry['id'])['body']) > 60000
    assert memory.publish_document(uid, pid, cid, did)['id'] == entry['id']
    assert len(memory.search(uid, pid)) == 1
    result = memory.search(uid, pid, 'STM32F407VGT6')[0]
    assert result['passage'] > 1 and '300 штук' in result['body']
    assert '300 штук' in memory.context(uid, cid, 'STM32F407VGT6')
    assert '300 штук' in memory.read(uid, pid, entry['id'], result['offset'])['body']
    with pytest.raises(ValueError): memory.read(uid + 1, pid, entry['id'])
    with SyncSessionLocal() as session:
        row = Document(conversation_id=cid, filename='updated.txt', content='STM32F407VGT6 нужно 200 штук.')
        session.add(row); session.commit(); updated = row.id
    assert memory.publish_document(uid, pid, cid, updated, entry['id'], 1)['revision'] == 2
    assert '200 штук' in memory.context(uid, cid, 'STM32F407VGT6')
    assert '300 штук' not in memory.context(uid, cid, 'STM32F407VGT6')


def test_search_does_not_drop_relevant_older_notes_after_eighty_entries(owner):
    _, uid, _ = owner
    pid = memory.create(uid, 'Поиск')['id']
    old = memory.save(uid, pid, 'Требования', 'Использовать ADS1115 с питанием 3,3 В.')
    for n in range(85): memory.save(uid, pid, f'Поздняя запись {n}', 'Другие сведения')
    assert memory.search(uid, pid, 'ADS1115')[0]['id'] == old['id']


def test_version_history_is_bounded_and_deletion_cleans_index(owner):
    from app.db.project_models import ProjectRevision, ProjectChunk
    from sqlalchemy import select, func
    _, uid, _ = owner
    pid = memory.create(uid, 'История')['id']; entry = memory.save(uid, pid, 'Запись', 'Версия 0')
    for n in range(1,23): memory.save(uid, pid, 'Запись', f'Версия {n}', entry_id=entry['id'])
    assert len(memory.history(uid, pid, entry['id'])) == 20
    assert memory.detail(uid, pid, entry['id'])['revision'] == 23
    memory.remove(uid, pid, entry['id'])
    assert not memory.search(uid, pid, 'версия')
    with SyncSessionLocal() as session:
        for model in (ProjectRevision, ProjectChunk):
            assert session.scalar(select(func.count()).select_from(model).where(model.entry_id == entry['id'])) == 0


def test_migration_backfills_legacy_entries_idempotently(owner, monkeypatch):
    import importlib.util
    from pathlib import Path
    from app.db.project_models import ProjectEntry, ProjectRevision, ProjectChunk
    from sqlalchemy import select, func
    _, uid, _ = owner; pid = memory.create(uid, 'Старый проект')['id']; eid = uuid4().hex
    with SyncSessionLocal() as session:
        session.add(ProjectEntry(id=eid, project_id=pid, title='Старая спецификация', body='Регулятор TPS5430 нужен для питания.', kind='note', source_url='', updated_at=1)); session.commit()
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/020_project_knowledge.py'
    spec = importlib.util.spec_from_file_location('knowledge_migration', path); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    with sync_engine.begin() as connection:
        monkeypatch.setattr(module.op, 'get_bind', lambda: connection)
        module.upgrade(); module.upgrade()
    assert memory.search(uid, pid, 'TPS5430')[0]['id'] == eid
    with SyncSessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(ProjectRevision).where(ProjectRevision.entry_id == eid)) == 1
        assert session.scalar(select(func.count()).select_from(ProjectChunk).where(ProjectChunk.entry_id == eid)) == 1


def test_project_read_tool_stays_within_bound_private_project(owner):
    import asyncio, json
    from computer_tools import _run_computer_tool, CHAT_TOOL_NAMES
    from turn_scope import turn_conversation
    _, uid, cid = owner
    pid = memory.create(uid, 'Доступ')['id']; memory.attach(uid, cid, pid)
    entry = memory.save(uid, pid, 'Инструкция', 'Информация пользователя ' * 1000)
    async def run():
        with turn_conversation(cid):
            result = json.loads(await _run_computer_tool('project_read', {'entry_id':entry['id'],'offset':6000}, uid))
            assert len(result['body']) == 6000 and result['next_offset'] == 12000
            forbidden = await _run_computer_tool('project_read', {'entry_id':entry['id']}, uid + 1)
            assert 'только в вашей личной' in forbidden
    asyncio.run(run())
    assert {'project_read','project_search'} <= CHAT_TOOL_NAMES
