import asyncio
import json
import os
from pathlib import Path
import sys

import pytest
from app.config import get_settings  # noqa: F401
from app.services import workspace_fs as fs
from app.services.orchestrator_policy import ValidationState


@pytest.fixture
def workspace(monkeypatch,tmp_path):
    monkeypatch.setenv('WORKSPACES_DIR',str(tmp_path))
    monkeypatch.setenv('WORKSPACE_ALLOW_LOCAL_RUN','1')
    monkeypatch.delenv('SANDBOX_MODE',raising=False)
    monkeypatch.delenv('WORKSPACE_LANDLOCK',raising=False)
    return fs.user_root(123)


def test_real_command_has_correct_cwd_and_no_application_secrets(workspace,monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY','must-not-reach-code')
    monkeypatch.setenv('DATABASE_URL','must-not-reach-code')
    (workspace/'project').mkdir()
    code='import os,json; print(json.dumps({"cwd":os.path.basename(os.getcwd()),"key":os.getenv("OPENROUTER_API_KEY"),"db":os.getenv("DATABASE_URL")}))'
    value=json.loads(fs.run_command(123,['python','-c',code],cwd='project'))
    assert value['exit_code']==0
    assert json.loads(value['output'])=={'cwd':'project','key':None,'db':None}


@pytest.mark.parametrize('argv',[[], 'node x.js', ['sh','-c','true'], ['../node'], ['node','\x00'], ['node',42]])
def test_no_shell_or_unvalidated_argv(workspace,argv):
    with pytest.raises(ValueError):fs.run_command(123,argv)


def test_command_cannot_choose_another_workspace(workspace):
    with pytest.raises(ValueError):fs.run_command(123,['python','-c','print(1)'],cwd='../u456')


def test_focused_repair_cannot_follow_an_alias_outside_its_project(workspace):
    product = '1' * 24
    project = workspace / 'products' / product
    project.mkdir(parents=True)
    outside = workspace / 'outside.py'
    outside.write_text('original')
    try:
        (project / 'alias.py').symlink_to(outside)
    except OSError:
        pytest.skip('Creating symlinks is unavailable')
    args = {'repair_product_id': product, 'path': f'products/{product}/alias.py',
            'old_string': 'original', 'new_string': 'changed'}
    with pytest.raises(ValueError, match='выбранного проекта'):
        fs.dispatch(123, 'edit', args)
    assert outside.read_text() == 'original'


def test_compiled_program_resolves_only_inside_its_project(workspace,monkeypatch):
    from app.services import product_factory
    (workspace/'project').mkdir()
    binary=workspace/'project/app'
    binary.write_bytes(b'placeholder')
    monkeypatch.setattr(fs.os,'access',lambda *args:True)
    calls=[]
    def command(uid,cwd,argv,*args,**kwargs):
        calls.append((cwd,argv));return {'exit_code':0,'passed':True}
    monkeypatch.setattr(product_factory,'_command',command)
    assert json.loads(fs.run_command(123,['./app','4'],cwd='project'))['passed']
    assert calls==[(workspace/'project',[str(binary),'4'])]
    with pytest.raises(ValueError):fs.run_command(123,['./../../u456/app'],cwd='project')


def test_missing_runtime_is_explicit_not_a_fake_success(workspace,monkeypatch):
    monkeypatch.setattr(fs.shutil,'which',lambda *args,**kwargs:None)
    result=json.loads(fs.run_command(123,['go','test','./...']))
    assert result['exit_code']==127 and not result['passed']
    assert result['error']=='runtime_unavailable'


def test_shell_metacharacter_is_only_an_argument(workspace):
    code='import sys,json; print(json.dumps(sys.argv[1:]))'
    result=json.loads(fs.run_command(123,['python','-c',code,'; echo not-a-shell']))
    assert json.loads(result['output'])==['; echo not-a-shell']


def test_compile_failure_stays_failed_until_same_check_passes():
    state=ValidationState()
    state.observe('workspace_run',{'argv':['gcc','-Wall','main.c']},json.dumps({'exit_code':1}))
    state.observe('workspace_run',{'argv':['node','--test']},json.dumps({'exit_code':0}))
    assert state.failed
    state.observe('workspace_run',{'argv':['gcc','-Wall','main.c']},json.dumps({'exit_code':0}))
    assert not state.failed


def test_expected_bad_cli_input_is_not_a_failed_build():
    state=ValidationState()
    state.observe('workspace_run',{'argv':['node','main.mjs','bad.json']},json.dumps({'exit_code':1}))
    assert not state.failed


def test_command_timeout_returns_nonzero(workspace):
    value=json.loads(fs.run_command(123,['python','-c','import time; time.sleep(10)'],timeout=1))
    assert value['exit_code']==124 and not value['passed']


def test_real_command_receipts_do_not_need_web_sources_and_reject_fake_success():
    from app.services.run_protocol import RunRecord
    record=RunRecord()
    record.observe('workspace_run',json.dumps({'command':['/usr/local/bin/node','--test'],'exit_code':0,'passed':True,'output':'unused private dump'}))
    assert record.command_checks==[{'id':'C1','tool':'workspace_run','program':'node','operation':'test','exit_code':0,'passed':True}]
    assert 'unused private dump' not in record.evidence_prompt()
    record.observe('workspace_read',json.dumps({'command':['node','--test'],'exit_code':0,'passed':True}))
    assert len(record.command_checks)==1
    record.observe('workspace_run',json.dumps({'command':['gcc'],'exit_code':1,'passed':True}))
    assert not record.command_checks[-1]['passed']
    assert record.tools[-1]['outcome']=='error'


def test_failed_revision_receipt_cannot_become_success_from_zero_exit():
    from app.services.run_protocol import RunRecord
    record=RunRecord()
    record.observe('product_lifecycle',json.dumps({'last_check':{'command':['python','-m','unittest'],'exit_code':0,'passed':False}}))
    assert record.command_checks[-1]['passed'] is False


def test_successful_research_is_not_forced_to_repeat_a_read_page():
    import director_router as dr
    from app.services.run_protocol import RunRecord,current_run
    record=RunRecord()
    record.observe_page('URL: https://docs.python.org/3.14/library/multiprocessing.html\n'+'forkserver and spawn are documented. '*20)
    token=current_run.set(record)
    try:
        done={'status':'done','new_employees':[]}
        journal=[{'status':'ok','result':'Данные найдены и проверены на странице.',
                  'search':[{'summary':'https://docs.python.org/3.14/library/multiprocessing.html'}]}]
        assert dr._ensure_research_plan(2,done,'Проверь актуальную документацию Python 3.14',journal,False)==done
        journal[0]['result']='Не удалось найти метод запуска.'
        assert dr._ensure_research_plan(2,done,'Проверь актуальную документацию Python 3.14',journal,False)['new_employees']
    finally:current_run.reset(token)


def test_text_written_as_docx_is_a_real_word_package(workspace):
    import zipfile
    result=fs.write(123,'beam.docx','# Проверка балки\nНапряжение 75 МПа.')
    assert 'Записал' in result
    with zipfile.ZipFile(workspace/'beam.docx') as document:
        xml=document.read('word/document.xml').decode()
        assert '75 МПа' in xml
    assert 'двоичный' in fs.edit(123,'beam.docx','75','80')


def test_invalid_docx_is_not_delivered_as_word_document():
    import base64
    from app.services.sandbox_client import _parse_deliverables
    assert _parse_deliverables(json.dumps([{'name':'fake.docx','data_b64':base64.b64encode(b'plain text').decode()}]))==[]


def test_requested_project_archive_is_not_replaced_by_example_csv(workspace):
    import zipfile
    from app.services.run_protocol import RunRecord,current_run
    from app.services.sandbox_client import collect_workspace_files
    from turn_scope import turn_conversation,export_paths
    fs.write(123,'project/example.csv','value\n1\n')
    with zipfile.ZipFile(workspace/'project.zip','w') as archive:archive.writestr('main.py','print(1)')
    token=current_run.set(RunRecord(request_context={'current_request':'Создай проект на Python и приложи ZIP исходников'}))
    try:
        with turn_conversation('synthetic'):
            files=asyncio.run(collect_workspace_files(123,0))
            assert [f['filename'] for f in files]==['project.zip']
            assert export_paths()==['project.zip']
    finally:current_run.reset(token)


def test_targeted_document_read_reaches_a_later_fact_with_small_budget():
    from db_conversations import _relevant_document_excerpt
    text='INTROFACT\n'+'unrelated background. '*500+'\nRARETAILFACT is the requested value.\n'+'ordinary trailing text. '*200
    excerpt=_relevant_document_excerpt(text,'RARETAILFACT',1800)
    assert 'RARETAILFACT is the requested value.' in excerpt
    assert 'INTROFACT' not in excerpt


def test_refining_the_same_page_reuses_fetch_and_read_budget(monkeypatch):
    import computer_tools
    from app.services.search_budget import SearchBudget,current_search_budget,LIMIT_NOTE
    from turn_scope import turn_conversation
    calls=[]
    async def fetch(url):
        calls.append(url)
        return url,'ALPHATOPFACT\n'+'background information. '*500+'\nBETATAILFACT\n'+'trailing content. '*300
    monkeypatch.setattr('web_scraper.fetch_url_content',fetch)
    monkeypatch.setattr(computer_tools,'_assert_public_http_url',lambda url:url)
    async def exercise():
        budget=SearchBudget(reads=1)
        token=current_search_budget.set(budget)
        try:
            with turn_conversation('synthetic'):
                first=await computer_tools.run_computer_tool('browse_page',{'url':'https://example.com/doc','query':'ALPHATOPFACT'},123)
                second=await computer_tools.run_computer_tool('browse_page',{'url':'https://example.com/doc#tail','query':'BETATAILFACT'},123)
                blocked=await computer_tools.run_computer_tool('browse_page',{'url':'https://example.com/other'},123)
            assert 'ALPHATOPFACT' in first and 'BETATAILFACT' in second
            assert len(budget.pages)==1 and blocked==LIMIT_NOTE
            assert calls==['https://example.com/doc']
        finally:current_search_budget.reset(token)
    asyncio.run(exercise())
