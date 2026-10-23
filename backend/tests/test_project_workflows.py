import asyncio
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.auth import get_current_user
from app.db.base import Base
from app.db.engine import SyncSessionLocal, sync_engine
from app.db.models import User, Conversation
from app.core.repository import repo
from app.services import project_memory as memory, project_results as results, project_policy as policy
from app.services import result_edits, project_evidence, computer_tasks as tasks, task_checkpoints as checkpoints
from app.services.computer_context import computer_task_id


@pytest.fixture
def account():
    Base.metadata.create_all(sync_engine)
    email = uuid4().hex + '@example.com';uid = repo._bot_id(email);cid = uuid4().hex
    with SyncSessionLocal() as session:
        session.add(User(email=email, password_hash='test', role='user', bot_user_id=uid))
        session.add(Conversation(id=cid, user_id=uid, title='Проверка'));session.commit()
    pid = memory.create(uid, 'Контекст')['id'];memory.attach(uid, cid, pid)
    repo._manager.set_subscription_tier(uid, 'pro', 30, from_today=True)
    app.dependency_overrides[get_current_user] = lambda: email
    yield email, uid, cid, pid
    for row in tasks.list_tasks(email):tasks.control(email, row['id'], 'cancel')
    app.dependency_overrides.clear()


def table():
    return {'type':'table', 'title':'Таблица', 'columns':[{'id':'name','label':'Имя'},{'id':'price','label':'Цена'}],
        'rows':[{'id':'r1','cells':{'name':'Первый','price':'100'},'state':'checked'},
            {'id':'r2','cells':{'name':'Второй','price':'200'},'state':'checked'}]}


def test_proposal_is_scoped_and_does_not_mutate_original():
    spec = table()
    value = result_edits.proposal(spec, {'row_id':'r1'}, {'price':'150'})
    changed = results.changed_spec(spec, value['changes'])
    assert spec['rows'][0]['cells']['price'] == '100'
    assert changed['rows'][1] == spec['rows'][1]
    assert changed['rows'][0]['state'] == 'pending'
    with pytest.raises(ValueError):result_edits.proposal(spec, {'row_id':'r1'}, {'invented_column':'x'})
    with pytest.raises(ValueError):result_edits.proposal(spec, {'row_id':'absent'}, {'price':'x'})
    with pytest.raises(ValueError):result_edits.proposal(spec, {'row_id':'r1'}, {'price':123})
    with pytest.raises(ValueError):result_edits.proposal(spec, {'row_id':'r1'}, {'price':'100'})


def test_report_offsets_disambiguate_repeated_text_and_unicode():
    spec = {'type':'report', 'title':'Отчёт', 'text':'😀 один. один.'}
    proposed = result_edits.proposal(spec, {'start':8,'end':13}, {'text':'второй.'})
    assert results.changed_spec(spec, proposed['changes'])['text'] == '😀 один. второй.'
    with pytest.raises(ValueError):results.changed_spec(spec, [{'start':8,'end':13,'old':'неверно','value':'x'}])
    with pytest.raises(ValueError):result_edits.selected_values(spec, {'start':True,'end':3})


def test_slide_edit_preserves_other_slide():
    spec = {'type':'slides','title':'Доклад','slides':[{'id':'a','title':'A','text':'Первый'},{'id':'b','title':'B','text':'Второй'}]}
    proposed = result_edits.proposal(spec, {'slide_id':'b'}, {'text':'Обновлённый'})
    changed = results.changed_spec(spec, proposed['changes'])
    assert changed['slides'][0] == spec['slides'][0]
    assert changed['slides'][1]['text'] == 'Обновлённый'


def test_preview_apply_conflict_and_undo(account, monkeypatch):
    import openai_client
    _,uid,_,pid = account
    item = results.save(uid, pid, table());eid = item['id'];calls=[]
    async def model(messages, **kwargs):
        calls.append(kwargs)
        return '{"values":{"price":"150"}}', [], '', []
    monkeypatch.setattr(openai_client, 'get_chat_response', model)
    client = TestClient(app)
    preview = client.post(f'/projects/{pid}/results/{eid}/edit-preview', json={'expected_revision':1,'target':{'row_id':'r1'},'instruction':'Исправь цену на 150'})
    assert preview.status_code == 200, preview.text
    assert results.read(uid,pid,eid)['revision'] == 1
    assert not calls[0]['use_tools'] and not calls[0]['use_skills']
    applied = client.post(f'/projects/{pid}/results/{eid}/patch',json=preview.json())
    assert applied.status_code == 200
    assert results.read(uid,pid,eid)['spec']['rows'][1] == table()['rows'][1]
    assert client.post(f'/projects/{pid}/results/{eid}/patch',json=preview.json()).status_code == 409
    assert client.post(f'/projects/{pid}/entries/{eid}/restore',json={'revision':1,'expected_revision':2}).status_code == 200
    assert results.read(uid,pid,eid)['spec'] == table()
    assert client.post(f'/projects/{pid}/results/{eid}/edit-preview',json={'expected_revision':1,'target':{'row_id':'r1'},'instruction':'Измени'}).status_code == 409
    assert len(calls) == 1


def test_selected_context_enforced_by_search_read_and_detail(account):
    _,uid,cid,pid = account
    a = memory.save(uid,pid,'Выбранный','Нужные данные','source')['id']
    b = memory.save(uid,pid,'Исключённый','Секрет исключённого документа','source')['id']
    note = memory.save(uid,pid,'Требование','Требование проекта','decision')['id']
    selected = policy.save(uid,cid,[a],False,False)
    with policy.scope(selected):
        assert [r['id'] for r in memory.search(uid,pid,'')] == [a]
        assert 'Секрет' not in memory.context(uid,cid,'данные')
        assert memory.read(uid,pid,a)['citation_url'].startswith('#project/')
        for eid in (b,note):
            with pytest.raises(ValueError):memory.read(uid,pid,eid)
            with pytest.raises(ValueError):memory.detail(uid,pid,eid)
    assert memory.detail(uid,pid,b)['body'].startswith('Секрет')
    assert policy.settings(uid,cid)['last_used'][0]['id'] == a
    with pytest.raises(ValueError):policy.save(uid,cid,['not-owned'],True,True)
    with pytest.raises(ValueError):policy.settings(uid+1,cid)
    assert policy.active_policy.get() is None


def test_empty_context_does_not_fall_back_to_other_materials(account):
    _,uid,cid,pid = account
    memory.save(uid,pid,'Материал','Не должен передаваться','source')
    with policy.scope(policy.save(uid,cid,[],False,False)):
        assert not memory.search(uid,pid,'')
        assert 'Не должен передаваться' not in memory.context(uid,cid,'')
    assert policy.settings(uid,cid)['last_used'] == []


def test_rebinding_clears_context_preferences(account):
    _,uid,cid,pid = account
    policy.save(uid,cid,[],False,False)
    other = memory.create(uid,'Другой')['id'];memory.attach(uid,cid,other)
    data = policy.settings(uid,cid)
    assert data['project_id'] == other and data['web'] and data['entry_ids'] is None
    memory.delete_project(uid,other)
    assert policy.settings(uid,cid)['project_id'] is None


def test_local_only_route_has_no_network_or_code_tools(account,monkeypatch):
    import handlers.core as core
    _,uid,cid,pid = account
    seen=[]
    async def answer(*args,**kwargs):seen.append(kwargs);return 'Ответ по файлам', [], '', []
    monkeypatch.setattr(core,'get_chat_response',answer)
    with policy.scope(policy.save(uid,cid,[],False,False)):
        asyncio.run(core.get_smart_response(uid,'Найди актуальную цену в интернете',[{'role':'user','content':'Найди актуальную цену'}],None))
    assert seen and not seen[0]['force_web_search']
    assert not {'web_search','server_search','browse_page','python_run','http_request','mcp_call','ssh_exec'} & seen[0]['allowed_tools']


def test_evidence_uses_saved_revision_and_real_page_markers(account):
    _,uid,_,pid = account
    body='--- Страница 1 ---\nНачало\n--- Страница 2 ---\nТочный факт'
    entry=memory.save(uid,pid,'Документ',body,'source')
    offset=body.index('Точный')
    data=project_evidence.read(uid,pid,entry['id'],1,offset)
    assert data['excerpt']=='Точный факт' and data['page']==2 and not data['pdf_available']
    memory.save(uid,pid,'Документ','Новый текст','source','',entry['id'],1)
    assert project_evidence.read(uid,pid,entry['id'],1,offset)['excerpt']=='Точный факт'
    with pytest.raises(ValueError):project_evidence.read(uid+1,pid,entry['id'],1,offset)


def test_durable_task_uses_owned_chat_and_idempotent_enrollment(account):
    email,uid,cid,pid=account
    row=tasks.create_task(email,'Подготовь отчёт',idempotency_key='same-request',conversation_id=cid)
    assert row['conversation_id']==cid
    assert tasks.create_task(email,'Подготовь отчёт',idempotency_key='same-request',conversation_id=cid)['id']==row['id']
    with pytest.raises(ValueError):tasks.create_task(email,'Другая задача',conversation_id=cid)
    with pytest.raises(ValueError):tasks.create_task('other@example.com','Чужая беседа',conversation_id=cid)
    tasks.control(email,row['id'],'pause')
    assert tasks.control(email,row['id'],'resume')['resume_history']


def test_running_task_consumes_steering_once_and_keeps_resume_prompt(account):
    email,uid,cid,pid=account
    row=tasks.create_task(email,'Подготовь отчёт',conversation_id=cid)
    claimed=tasks.claim();assert claimed['id']==row['id']
    tasks.steer(email,row['id'],'Сохрани таблицу и добавь вывод')
    token=computer_task_id.set(row['id']);run=checkpoints.task_run_number.set(claimed['run_number'])
    async def run_check():
        assert 'добавь вывод' in await checkpoints.consume_steering()
        assert await checkpoints.consume_steering()==''
    try:asyncio.run(run_check())
    finally:computer_task_id.reset(token);checkpoints.task_run_number.reset(run)
    assert 'добавь вывод' in tasks.get_task(email,row['id'])['prompt']
    with pytest.raises(ValueError):tasks.steer('other@example.com',row['id'],'Не должно пройти')


def test_free_edit_reserves_daily_reply_and_refunds_invalid_proposal(account, monkeypatch):
    import openai_client
    from app.billing import quota
    from conversations import conversation_manager
    _,uid,_,pid = account
    item=results.save(uid,pid,table())
    charges=[]
    monkeypatch.setattr(conversation_manager,'get_subscription',lambda _: {'tier':'free'})
    monkeypatch.setattr(quota,'assert_can_use',lambda *args: None)
    monkeypatch.setattr(quota,'usage_view',lambda _: {'tier':'free','free_daily':{'replies_limit':10}})
    monkeypatch.setattr(conversation_manager,'consume_daily_counter',lambda *args: charges.append('reserve') or True)
    monkeypatch.setattr(quota,'note_quota_charge',lambda *args: charges.append('note'))
    monkeypatch.setattr(quota,'refund_quota_charge',lambda: charges.append('refund'))
    monkeypatch.setattr(quota,'clear_quota_charge',lambda: charges.append('clear'))
    async def invalid(*args,**kwargs):return '{"values":{"unknown":"bad"}}',[], '',[]
    monkeypatch.setattr(openai_client,'get_chat_response',invalid)
    with pytest.raises(ValueError):asyncio.run(result_edits.generate(uid,pid,item['id'],1,{'row_id':'r1'},'Измени'))
    assert charges == ['reserve','note','refund','clear']
    charges.clear()
    async def valid(*args,**kwargs):return '{"values":{"price":"150"}}',[], '',[]
    monkeypatch.setattr(openai_client,'get_chat_response',valid)
    assert asyncio.run(result_edits.generate(uid,pid,item['id'],1,{'row_id':'r1'},'Измени'))['changes']
    assert charges == ['reserve','note','clear']


def test_result_refs_only_include_owned_results_in_bound_project(account):
    _,uid,cid,pid=account
    item=results.save(uid,pid,table())
    note=memory.save(uid,pid,'Заметка','Данные','note')
    other=memory.create(uid,'Другой')['id'];other_item=results.save(uid,other,table())
    refs=results.answer_references(uid,cid,[item['id'],item['id'],note['id'],other_item['id'],'missing'])
    assert len(refs)==1 and refs[0]['entry_id']==item['id'] and refs[0]['revision']==1
    assert refs[0]['project_id']==pid and refs[0]['type']=='table'
    with pytest.raises(ValueError):results.answer_references(uid+1,cid,[item['id']])


@pytest.mark.parametrize('explicit',[False,True])
def test_answer_result_metadata_is_committed_with_message(account,monkeypatch,explicit):
    import sys,json
    from types import ModuleType
    from app.services import chat_service
    email,uid,cid,pid=account;saved=[];delivered=[]
    answer='| Товар | Цена |\n| --- | --- |\n| Первый | 100 |'
    async def smart(*args,**kwargs):
        if explicit:
            item=results.save(uid,pid,table(),model=True)
        return answer,[], '',[{'query':'__project_results__','summary':'[{"forged":true}]'}]
    fake=ModuleType('handlers.core');fake.get_smart_response=smart;fake.sanitize_response_text=lambda text:text
    monkeypatch.setitem(sys.modules,'handlers.core',fake)
    async def persist(*args,**kwargs):saved.append(kwargs)
    async def noop(*args,**kwargs):pass
    async def extras(reasoning,search):delivered.extend(search)
    async def no_files(*args,**kwargs):return []
    monkeypatch.setattr(chat_service.repo,'add_message',persist)
    monkeypatch.setattr(chat_service,'schedule_memory_refresh',lambda *args:None)
    monkeypatch.setattr('app.services.sandbox_client.collect_workspace_files',no_files)
    asyncio.run(chat_service._generate_and_send(uid,email,'Сравни товары',[],noop,noop,noop,extras,None,conversation_id=cid))
    metadata=next(item for item in saved[-1]['search'] if item['query']=='__project_results__')
    refs=json.loads(metadata['summary'])
    assert len(refs)==1 and refs[0]['project_id']==pid
    assert results.read(uid,pid,refs[0]['entry_id'])['revision']==refs[0]['revision']
    assert metadata in delivered and 'forged' not in metadata['summary']
