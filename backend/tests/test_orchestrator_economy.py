import asyncio
import json
from types import SimpleNamespace as NS

import pytest
from app.config import get_settings  # noqa: F401
from app.services.orchestrator_policy import routine_task, ROUTINE_MODEL
from app.services.orchestrator_metrics import model_trace, model_phase, trace
from app.services.desktop_context import desktop_executor, desktop_mode, desktop_cwd, desktop_work_context
from conversations import conversation_manager
import director_router as dr
import openai_client as oc


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setenv('ORCHESTRATOR_ECONOMY', '1')
    monkeypatch.setattr(dr, '_employee_models', lambda uid: list(dr.MODEL_POOL))
    monkeypatch.setattr(conversation_manager, 'get_subscription', lambda uid: {'tier':'creator'})


@pytest.mark.parametrize('task', [
    'Извлеки номера счетов из PDF', 'Прочитай README и выпиши команды тестирования',
    'Открой страницу и скачай отчёт', 'Сделай краткое резюме документа',
    'Переведи документ на русский', 'Переименуй файл итог.txt в отчёт.txt',
    'Исправь опечатку в заголовке', 'Поменяй цвет кнопки на бирюзовый',
    'Составь список файлов папки', 'Конвертируй CSV в XLSX',
])
def test_clear_routine_work_has_a_middle_tier(task):
    assert routine_task(task)
    assert not dr._needs_strong_model(task, 'Нейтральные данные\n' * 80, False, 1)
    assert dr._clamped_planner_model(1, complex_task=False, routine=True) == ROUTINE_MODEL
    plan=dr._clamp_employee_plan({'new_employees':[{'role':'Исполнитель','task':task,'model':'gpt-6-sol'}]},1,task,'данные')
    assert plan['new_employees'][0]['model']==ROUTINE_MODEL


@pytest.mark.parametrize('task', [
    'Прочитай проект и спроектируй архитектуру', 'Прочитай README и создай приложение',
    'Открой проект, а затем реализуй авторизацию OAuth', 'Перепиши сервис и миграцию базы',
    'Проверь договор на юридические риски', 'Извлеки доказательства для расследования',
    'Проверь сложную геометрию SOLIDWORKS', 'Исправь ошибку COM SDK',
    'Разберись с гонкой транзакций', 'Настрой безопасность сервера',
])
def test_high_risk_and_open_ended_requests_are_not_downgraded(task):
    assert not routine_task(task)
    plan=dr._clamp_employee_plan({'new_employees':[{'role':'Эксперт','task':task,'model':'gpt-6-sol'}]},1,task,'исходный документ')
    assert plan['new_employees'][0]['model']=='gpt-6-sol'


def test_ambiguous_files_and_legal_sources_stay_strong():
    assert not routine_task('Проверь', 'документ')
    assert not routine_task('Сделай краткое резюме', 'Договор поставки')
    assert not routine_task('Summarize the document', 'Contract: legal obligations')
    assert dr._needs_strong_model('Извлеки размеры', '', True, 1)
    assert not routine_task('Прочитай ' + 'условие ' * 400)


def test_tier_limits_and_rollback_are_respected(monkeypatch):
    monkeypatch.setattr(dr, '_employee_models', lambda uid: ['gpt-6-luna'])
    monkeypatch.setattr(conversation_manager, 'get_subscription', lambda uid: {'tier':'free'})
    assert dr._clamped_planner_model(1, complex_task=False, routine=True)=='gpt-6-luna'
    monkeypatch.setenv('ORCHESTRATOR_ECONOMY', '0')
    assert not routine_task('Прочитай README')
    assert dr._needs_strong_model('Извлеки поля', 'документ', False, 1)


def test_already_cheap_routine_is_not_upgraded(monkeypatch):
    task='Прочитай source.csv и сохрани result.csv'
    monkeypatch.setattr(dr,'_sandbox_skills',lambda *args:[])
    assert not dr._legacy_needs_strong_model(task,'',False,1)
    for requested in ['gpt-6-sol',ROUTINE_MODEL,'gpt-6-luna']:
        result=dr._clamp_employee_plan({'new_employees':[{'role':'Чтение','task':task,'model':requested}]},1,task)
        assert result['new_employees'][0]['model']=='gpt-6-luna'
    result=dr._clamp_employee_plan({'new_employees':[{'role':'Security audit','task':'Investigate authentication vulnerability','model':ROUTINE_MODEL}]},1,task)
    assert result['new_employees'][0]['model']=='gpt-6-sol'


def test_planner_chooses_product_spend_inside_a_ceiling(monkeypatch):
    monkeypatch.setattr('config.OPENROUTER_API_KEY', 'present')
    brief = dr._clamp_employee_plan(
        {'new_employees': [{'role': 'Бриф', 'task': 'Сделай сайт', 'model': 'gpt-6-luna', 'product_phase': 'brief'}]},
        1, 'Исправь опечатку', '')
    assert brief['new_employees'][0]['model'] == 'gpt-6-luna'
    page = dr._clamp_employee_plan(
        {'new_employees': [{'role': 'Сборка', 'task': 'Собери страницу', 'model': 'claude-haiku-5.5', 'product_phase': 'build'}]},
        1, 'Сделай сайт', '')
    assert page['new_employees'][0]['model'] == 'claude-haiku-5.5'
    build = dr._clamp_employee_plan(
        {'new_employees': [{'role': 'Сборка', 'task': 'Собери продукт', 'model': 'gpt-6-sol', 'product_phase': 'build'}]},
        1, 'Исправь опечатку', '')
    assert build['new_employees'][0]['model'] == 'gpt-6-sol'
    over = dr._clamp_employee_plan(
        {'new_employees': [{'role': 'Сборка', 'task': 'Собери', 'model': 'claude-opus-5.5', 'product_phase': 'build'}]},
        1, 'Сделай сайт', '')
    assert over['new_employees'][0]['model'] == 'gpt-6-sol'
    pair = dr._clamp_employee_plan(
        {'new_employees': [
            {'role': 'A', 'task': 'a', 'model': 'gpt-6-sol', 'product_phase': 'build'},
            {'role': 'B', 'task': 'b', 'model': 'gpt-6-sol', 'product_phase': 'build'},
        ]},
        1, 'Сделай сайт', '')
    assert [item['model'] for item in pair['new_employees']] == ['gpt-6-sol', 'claude-haiku-5.5']
    cheap = dr._clamp_employee_plan(
        {'new_employees': [{'role': 'Правка', 'task': 'Исправь опечатку', 'model': 'claude-haiku-5.5'}]},
        1, 'Исправь опечатку', 'данные')
    assert cheap['new_employees'][0]['model'] == 'claude-haiku-5.5'
    monkeypatch.setattr('config.OPENROUTER_API_KEY', '')
    no_key = dr._clamp_employee_plan(
        {'new_employees': [{'role': 'Бриф', 'task': 'Сделай сайт', 'model': 'claude-haiku-5.5', 'product_phase': 'brief'}]},
        1, 'Сделай сайт', '')
    assert no_key['new_employees'][0]['model'] == 'gpt-6-luna'


def test_product_phase_uses_the_model_the_planner_hired(monkeypatch):
    from app.services import autonomy
    seen = []

    planned = []

    async def plan(*args, **kwargs):
        planned.append(len(args[1]) if len(args) > 1 else 0)
        return {'status': 'continue', 'new_employees': [
            {'role': 'Разбор', 'model': 'gpt-6-luna', 'task': 'аналоги'},
            {'role': 'Сборка', 'model': 'gpt-6-sol', 'task': 'страница'},
        ]}

    async def employee(item, round_num, journal, uid, *args):
        seen.append((item['product_phase'], item['model']))
        state = autonomy.product_evidence.get()
        if item['product_phase'] == 'brief':
            state.update(product_id='pid', path='products/pid', stack='static', ready=False, packaged=False)
        else:
            state.update(ready=True, packaged=True)
        return {'round': round_num, 'role': item['role'], 'status': 'ok', 'result': 'ok',
                'model': item['model'], 'product_phase': item['product_phase'], 'product_id': 'pid'}

    async def verified(*args, **kwargs):
        done = len(seen) >= 2
        return {'product_id': 'pid', 'path': 'products/pid', 'stack': 'static',
                'ready': done, 'packaged': done, 'archive': 'product-pid.zip'}

    async def no_files(*args):
        return []

    monkeypatch.setattr('config.OPENROUTER_API_KEY', 'present')
    monkeypatch.setattr(dr, '_plan_round', plan)
    monkeypatch.setattr(dr, '_execute_employee', employee)
    monkeypatch.setattr(dr, '_new_file_names', no_files)
    monkeypatch.setattr(dr, '_is_document_package_task', lambda *args: False)
    monkeypatch.setattr(dr, '_is_shopping_task', lambda *args: False)
    monkeypatch.setattr(autonomy, 'verified_product', verified)
    monkeypatch.setattr(autonomy, 'learn', lambda *args: None)
    token = autonomy.product_evidence.set({})
    try:
        answer, _, _, _ = asyncio.run(dr._run_director([], 'Сделай сайт', 92001, None))
    finally:
        autonomy.product_evidence.reset(token)
    # The brief does not inherit the build's Sol, and the build needs no second Sol planner call.
    assert seen == [('brief', 'gpt-6-luna'), ('build', 'gpt-6-sol')]
    assert planned == [0]
    assert 'Сборка и тесты текущей версии пройдены' in answer


def test_design_product_gets_motion_guidance_once_and_offline_assets():
    from app.services import autonomy
    from computer_skills.loader import preload_skills_block
    ask = 'Напиши красивый лендинг для кофейни в стиле Apple с анимациями «вау»'
    brief = autonomy.product_employee(ask, {}, [])
    assert 'apple.com' in brief['task'] and 'движения с эффектом «вау»' in brief['task']
    assert 'transform и opacity' in brief['task'] and 'assets/' in brief['task']
    assert '"Parallax Scroll"' in brief['task'] or '"Scroll Reveal"' in brief['task']
    build = autonomy.product_employee(ask, {'product_id': 'id', 'path': 'p', 'stack': 'static'}, [])
    block = preload_skills_block(build['task'], user_id=None)
    # The inline guidance is the single copy; only the code playbook is preloaded.
    assert 'impeccable' not in block.lower()[:400] and block.count('Скилы уже подобраны') == 1
    plain = autonomy.product_employee('Сделай сайт для сантехника', {}, [])
    assert 'движения с эффектом «вау»' not in plain['task']


def test_new_product_build_is_sol_and_a_failed_cheap_build_escalates():
    assert dr._strongest_hired_model(
        [{'model': 'gpt-6-luna'}, {'model': 'gpt-6-sol'}], dr._SPEND_RANK[dr.HAIKU_MODEL]) == 'gpt-6-luna'
    assert dr._strongest_hired_model([{'model': 'gpt-6-sol'}], dr._SPEND_RANK[dr.HAIKU_MODEL]) is None
    from app.services import autonomy
    state = {'product_id': 'id', 'path': 'products/id', 'stack': 'static', 'gates': {'build': True, 'smoke': False}}
    journal = [{'product_phase': 'brief'}, {'product_phase': 'build', 'model': 'claude-haiku-5.5'}]
    repair = autonomy.product_employee('Сделай сайт', state, journal)
    assert repair['model'] == 'gpt-6-sol' and 'ПОЧИНКА' in repair['task'] and 'smoke' in repair['task']
    assert 'ПОЧИНКА' not in autonomy.product_employee('Сделай сайт', state, journal[:1])['task']
    # One build and one repair, then an honest report instead of a third paid pass.
    assert autonomy.product_employee('Сделай сайт', state, journal + [{'product_phase': 'build'}]) is None


def test_recovery_keeps_a_strong_planner_and_repair_worker():
    journal=[{'status':'error','model':ROUTINE_MODEL,'result':'AssertionError: тест не прошёл'}]
    assert dr._clamped_planner_model(1, first_round=False, recovery=True)=='gpt-6-sol'
    plan=dr._clamp_employee_plan({'new_employees':[{'role':'Исправление','task':'Исправь результат, проверь тест','model':ROUTINE_MODEL}]},1,'Исправь опечатку','',journal)
    assert plan['new_employees'][0]['model']=='gpt-6-sol'


def test_desktop_environment_is_in_instructions_not_in_task_classification(monkeypatch):
    tokens=[(desktop_executor,desktop_executor.set(lambda *args:None)),(desktop_mode,desktop_mode.set('director')),
            (desktop_cwd,desktop_cwd.set('C:/private-project')), (desktop_work_context,desktop_work_context.set('Правило проекта'))]
    try:
        assert dr._is_light_task('привет', '', False, 1)
        assert not dr._is_light_task('Открой страницу в браузере', '', False, 1)
        instructions=dr._desktop_work_instructions()
        assert 'PowerShell' in instructions and 'C:/private-project' in instructions and 'Правило проекта' in instructions
    finally:
        for var,token in reversed(tokens):var.reset(token)


def test_reasoning_capabilities_are_explicit():
    assert oc._get_reasoning_config('gpt-6-luna','none')=={'effort':'none'}
    assert oc._get_reasoning_config(ROUTINE_MODEL,'none')=={'effort':'none'}
    assert oc._get_reasoning_config('gpt-6-sol','none')=={'effort':'low'}
    assert oc._get_reasoning_config('gpt-6-sol')=={'effort':'medium'}
    assert oc._get_reasoning_config('gpt-6-astra')=={'effort':'high'}


@pytest.mark.parametrize('desktop', [False,True])
def test_real_planner_retries_invalid_json_once_without_running_tools(monkeypatch, desktop):
    calls=[]
    async def fake(messages,**kwargs):
        calls.append((messages,kwargs))
        assert kwargs['use_tools'] is False
        return ('not JSON' if len(calls)==1 else '{"status":"continue","new_employees":[{"role":"Исполнитель","task":"Извлеки поля","model":"gpt-6-sol"}]}'), [], '', []
    monkeypatch.setattr(oc,'get_chat_response',fake)
    monkeypatch.setattr(dr,'_chat_image_names',lambda uid:[])
    token=desktop_mode.set('director' if desktop else None)
    executor=desktop_executor.set((lambda *args:None) if desktop else None)
    try:
        result=asyncio.run(dr._plan_round('Извлеки поля из документа',[],1,'данные'))
        assert [kwargs['model'] for _,kwargs in calls]==[ROUTINE_MODEL,'gpt-6-sol']
        assert calls[1][1]['reasoning_effort']=='medium'
        assert result['new_employees'][0]['model']==ROUTINE_MODEL
        assert 'python_run' in calls[0][0][1]['content']
        if desktop:assert 'PowerShell' in calls[0][0][1]['content']
    finally:desktop_executor.reset(executor);desktop_mode.reset(token)


def test_trace_records_cost_and_phase_without_prompt_or_account(caplog, monkeypatch):
    from app.billing.call_budget import model_call
    from app.billing import call_budget
    monkeypatch.setattr(call_budget,'wallet_user',lambda uid:False)
    async def create(**kwargs):
        return NS(usage=NS(input_tokens=100,output_tokens=20,input_tokens_details=NS(cached_tokens=10),output_tokens_details=NS(reasoning_tokens=5)))
    async def count(**kwargs):
        return NS(input_tokens=100)
    client=NS(responses=NS(create=create,input_tokens=NS(count=count)))
    @model_phase('planner')
    async def run():
        return await model_call(client,{'model':ROUTINE_MODEL,'input':'PRIVATE_PROMPT','max_output_tokens':100},model=ROUTINE_MODEL,responses=True)
    caplog.set_level('INFO',logger='app.services.orchestrator_metrics')
    with model_trace('desktop') as state:asyncio.run(run())
    assert state['calls']==1 and state['reasoning']==5 and state['estimated_text_usd']>0
    logs='\n'.join(r.message for r in caplog.records)
    assert 'PRIVATE_PROMPT' not in logs and 'user_id' not in logs and 'email' not in logs
    assert '"phase": "planner"' in logs
    assert trace.get() is None


def test_trace_isolates_parallel_turns_and_restores_after_error():
    from app.services.orchestrator_metrics import observe
    async def turn(surface):
        with model_trace(surface) as state:
            await asyncio.sleep(0)
            observe('gpt-6-luna',{'input_tokens':10,'output_tokens':2},.01,True)
            return state
    async def run():return await asyncio.gather(turn('web'),turn('desktop'))
    a,b=asyncio.run(run())
    assert a['run']!=b['run'] and a['calls']==b['calls']==1
    with pytest.raises(RuntimeError):
        with model_trace('web'):raise RuntimeError('private message')
    assert trace.get() is None


def test_real_validation_cannot_be_overwritten_by_unrelated_success():
    from app.services.orchestrator_policy import ValidationState, needs_recovery
    state=ValidationState()
    state.observe('desktop_run_command',{'command':'npm test'},'failure\nКод завершения: 1')
    assert state.failed
    state.observe('desktop_run_command',{'command':'npm run build'},'done\nКод завершения: 0')
    assert state.failed
    failure={'status':'error','validation_failed':True,'validation_checks':dict(state.checks)}
    assert needs_recovery([failure])
    state.observe('desktop_run_command',{'command':'npm test'},'all tests passed\nКод завершения: 0')
    assert not state.failed
    assert not needs_recovery([failure,{'status':'ok','validation_checks':dict(state.checks)}])
    assert all(len(key)==64 for key in state.checks)


@pytest.mark.parametrize('repaired',[False,True])
def test_actual_worker_observes_test_exit_code_without_replaying_a_write(monkeypatch,repaired):
    import computer_tools
    from app.services.orchestrator_policy import validation
    calls=[]
    async def execute(name,args,uid):
        calls.append(name)
        return 'Код завершения: ' + ('0' if repaired and len(calls)==2 else '1')
    async def chat(*args,**kwargs):
        await computer_tools.run_computer_tool('desktop_run_command',{'command':'npm test'},None)
        if repaired:await computer_tools.run_computer_tool('desktop_run_command',{'command':'npm test'},None)
        return 'Готово', [], '', []
    monkeypatch.setattr(computer_tools,'_run_computer_tool',execute)
    monkeypatch.setattr(oc,'get_chat_response',chat)
    result=asyncio.run(dr._execute_employee({'role':'Исполнитель','task':'Исправь опечатку','model':ROUTINE_MODEL},1,[],1))
    assert result['status']==('ok' if repaired else 'error')
    assert result.get('validation_failed',False)==(not repaired)
    assert calls==['desktop_run_command']*(2 if repaired else 1)
    assert validation.get() is None


def test_desktop_websocket_uses_the_shared_economy_policy(monkeypatch):
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import desktop
    from app.auth import create_access_token_for_user
    from app.db.engine import SyncSessionLocal
    from app.db.models import User
    from app.core.repository import repo
    from app.services.sandbox_client import run_workspace_tool
    email='economy-'+uuid4().hex+'@example.invalid'
    with SyncSessionLocal() as db:
        db.add(User(email=email,password_hash='test-only',role='user',bot_user_id=repo._bot_id(email)));db.commit()
    choices=[]
    async def chat(messages,**kwargs):
        choices.append(kwargs['model'])
        return '{"status":"continue","new_employees":[{"role":"Чтение","task":"Прочитай README","model":"gpt-6-sol"}]}', [], '', []
    async def routed(user,content,cid,status,chunk,file,**kwargs):
        assert desktop_mode.get()=='director'
        plan=await dr._plan_round(content,[],repo._bot_id(user))
        assert plan['new_employees'][0]['model']=='gpt-6-luna'
        result=await run_workspace_tool('workspace_read',{'path':'README.md'},repo._bot_id(user))
        await chunk(result)
    monkeypatch.setattr(oc,'get_chat_response',chat)
    monkeypatch.setattr(dr,'_chat_image_names',lambda uid:[])
    monkeypatch.setattr(desktop,'run_local_chat',routed)
    with TestClient(app).websocket_connect('/desktop/ws') as ws:
        ws.send_json({'type':'auth','payload':{'token':create_access_token_for_user(email,'user')}})
        assert ws.receive_json()['type']=='ready'
        ws.send_json({'type':'run','payload':{'mode':'director','content':'Прочитай README и выпиши команды тестирования','cwd':'C:/fixture'}})
        message=ws.receive_json()
        assert message['type']=='tool_call' and message['payload']['name']=='workspace_read'
        ws.send_json({'type':'tool_result','payload':{'id':message['payload']['id'],'ok':True,'output':'npm test'}})
        assert ws.receive_json()['payload']['text']=='npm test'
        assert ws.receive_json()['type']=='done'
    assert choices==['gpt-6-luna']


def test_catalog_exposes_terra_but_explicit_chat_models_stay_unchanged():
    from routing import vision_route
    assert ROUTINE_MODEL in dr._pool_description(1,'Прочитай README')
    assert vision_route('gpt-6-astra','creator','Посмотри скриншот')=='gpt-6-astra'
    assert vision_route('gpt-6-sol','creator','Посмотри скриншот')=='gpt-6-sol'
