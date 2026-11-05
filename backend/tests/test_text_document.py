import asyncio
from io import BytesIO
import pytest
from app.services import text_document as td

TASK='напиши мне доклад про алгоритм дейкстры и его реализацию на c++ в формате docx. после положи его на гугл диск'
BODY='# Алгоритм Дейкстры\n\nАлгоритм находит кратчайшие пути при неотрицательных весах. '+('Описание алгоритма и его ограничений. '*8)+'\n\n```cpp\n#include <vector>\nint main() { int **p = nullptr; std::vector<int> a{1}; return a[0] - 1; }\n```\n\n## Вывод\nПример реализации.'

def test_bounded_report_eligibility_and_upload_authorization():
    assert td.eligible(TASK) and td.drive_requested(TASK)
    assert td.eligible('Подготовь обзор сортировок в Word')
    assert not td.drive_requested('Напиши доклад про Google Диск в DOCX')
    assert not td.drive_requested('Напиши доклад в DOCX, не загрузи на Google Диск')
    assert not td.eligible('Напиши два доклада в DOCX')
    assert not td.eligible('Создай 2 документа DOCX: доклад и конспект')
    assert not td.eligible('Напиши доклад в DOCX и опубликуй его на сайте')
    for task in ['Напиши доклад в DOCX по прикреплённому файлу','Сделай доклад в DOCX по шаблону','Напиши доклад в DOCX с источниками','Напиши доклад в DOCX на 20 страниц','Напиши доклад в DOCX на 3000 слов','Напиши договор в DOCX','Напиши доклад в DOCX, сохрани в папке на Google Диск']:
        assert not td.eligible(task),task


def setup(monkeypatch, body=BODY, upload='Сохранено на Google Диск: Доклад.docx — https://drive.google.com/file/d/test/view (id test)'):
    import openai_client,computer_tools,google_tools
    from conversations import conversation_manager
    from docx_generator import convert_markdown_to_docx
    model_calls=[];tools=[];stored={}
    monkeypatch.setattr(conversation_manager,'get_subscription',lambda uid:{'tier':'creator'})
    async def writer(messages,**kwargs):
        model_calls.append(kwargs);return body,[], '',[]
    async def tool(name,args,uid):
        tools.append((name,args))
        if name=='workspace_write':
            stored[args['path']]=convert_markdown_to_docx(args['content']);return 'Записал '+args['path']
        assert name=='google_drive_upload'
        if isinstance(upload,Exception):raise upload
        return upload
    monkeypatch.setattr(openai_client,'get_chat_response',writer)
    monkeypatch.setattr(computer_tools,'run_computer_tool',tool)
    monkeypatch.setattr(google_tools,'_load_file',lambda uid,path:('Доклад.docx',stored[path]))
    return model_calls,tools


def run(task=TASK):
    from turn_scope import turn_conversation
    async def call():
        with turn_conversation('synthetic-document-test'):
            return await td.respond([{'role':'user','content':task}],task,123)
    return asyncio.run(call())


def test_one_writer_native_document_one_upload_preserves_cpp(monkeypatch):
    calls,tools=setup(monkeypatch)
    answer,files,_,_=run()
    assert len(calls)==1 and not calls[0]['use_tools'] and not calls[0]['use_skills']
    assert calls[0]['output_token_limit']==6000
    assert [name for name,args in tools]==['workspace_write','google_drive_upload']
    assert len(files)==1 and files[0]['filename']=='Доклад.docx'
    assert 'drive.google.com' in answer
    assert 'std::vector<int> a{1}' in td.validate(files[0]['bytes'],BODY)


@pytest.mark.parametrize('failure',['Google не подключён.',RuntimeError('network disconnect')])
def test_failed_upload_keeps_document_and_does_not_retry(monkeypatch,failure):
    calls,tools=setup(monkeypatch,upload=failure)
    answer,files,_,_=run()
    assert len(files)==1 and len(calls)==1
    assert 'не подтверждена' in answer and 'Сохранено на Google' not in answer
    assert sum(name=='google_drive_upload' for name,args in tools)==1


def test_local_doc_never_uploads_and_incomplete_generation_never_writes(monkeypatch):
    calls,tools=setup(monkeypatch)
    assert run('Напиши доклад про графы в DOCX')[1]
    assert [name for name,args in tools]==['workspace_write']
    calls,tools=setup(monkeypatch,body=BODY+'\n```cpp\nunfinished')
    assert not run()[1] and not tools


def test_serialization_corruption_is_not_uploaded(monkeypatch):
    calls,tools=setup(monkeypatch)
    monkeypatch.setattr(td,'validate',lambda *args:(_ for _ in ()).throw(ValueError('lost code')))
    answer,files,_,_=run()
    assert not files and 'не прошёл проверку' in answer
    assert [name for name,args in tools]==['workspace_write']


def test_resumed_draft_is_bounded_but_external_receipt_prevents_restart(monkeypatch):
    from app.services.task_checkpoints import resumed_journal
    calls,tools=setup(monkeypatch)
    token=resumed_journal.set([{'status':'ok','result':'old draft'}])
    try:
        monkeypatch.setattr(td,'_has_external_action',lambda:True)
        assert run() is None and not calls and not tools
        monkeypatch.setattr(td,'_has_external_action',lambda:False)
        assert run()[1] and len(calls)==1
    finally:resumed_journal.reset(token)
