import pytest
from app.services.response_policy import compact_answer_kind
from app.services.orchestrator_policy import bounded_text_revision


HISTORY = [
    {'role':'user','content':'Напиши клиенту сообщение: встреча 12 мая в 15:00. Только сообщение, без обещаний.'},
    {'role':'assistant','content':'Встреча состоится 12 мая в 15:00.'},
]


@pytest.mark.parametrize('task',['Сделай короче','Ещё короче','Теплее','Убери вступление','Сделай вежливее',
                                 'Сделай короче, сохрани день и время.',
                                 'А теперь теплее, без официоза','Оставь только само сообщение, без вступления'])
def test_text_followups_use_the_existing_draft(task):
    assert bounded_text_revision(task,HISTORY)
    assert compact_answer_kind(task,messages=HISTORY)== 'text'
    assert not bounded_text_revision(task,[])


def test_repeated_identical_revision_keeps_its_origin():
    rows=HISTORY+[{'role':'user','content':'Сделай короче'},
                  {'role':'assistant','content':'12 мая, 15:00.'},
                  {'role':'user','content':'Сделай короче'}]
    assert compact_answer_kind('Сделай короче',messages=rows)=='text'
    assert rows[-1]['content']=='Сделай короче'


@pytest.mark.parametrize('task',[
    'Сделай короче и отправь по почте','Сделай короче в DOCX',
    'Сделай короче и сверь источники','Сделай теплее и сохрани результат',
    'Сделай короче и запусти скрипт',
    'Сделай короче и пересчитай сумму',
    'Сделай короче и установи пакет',
    'Сделай короче и открой почту',
    'Оставь только само сообщение и отправь по почте',
])
def test_revision_is_not_permission_to_act(task):
    assert not bounded_text_revision(task,HISTORY)
    assert compact_answer_kind(task,messages=HISTORY)!='text'


@pytest.mark.parametrize('source',[
    'Исправь приложение в проекте','Проанализируй прикреплённый документ',
    'Напиши функцию Python. Только код.',
])
def test_unrelated_previous_task_does_not_become_a_draft(source):
    assert not bounded_text_revision('Сделай короче',[{'role':'user','content':source}])


def test_file_context_and_required_research_keep_normal_routes():
    assert not bounded_text_revision('Сделай короче',HISTORY+[{'role':'user','content':'см. файл','attachment':{'name':'a.docx'}}])
    assert compact_answer_kind('Сделай короче',messages=HISTORY,web_required=True)!='text'
    interrupted=HISTORY+[{'role':'user','content':'Объясни ошибку в проекте'}]
    assert not bounded_text_revision('Сделай короче',interrupted)


def test_revision_guidance_preserves_transcript_and_facts():
    from app.services.response_policy import compact_messages
    rows=HISTORY+[{'role':'user','content':'Сделай короче'}]
    result=compact_messages(rows)
    assert result[:-1]==rows
    assert 'Сохрани факты, даты, суммы, контакты' in result[-1]['content']


def test_fenced_code_is_not_downgraded_to_prose_revision():
    rows=[{'role':'user','content':'Перепиши: def f(): return 1'},
          {'role':'assistant','content':'```python\ndef f(): return 1\n```'}]
    assert not bounded_text_revision('Сделай короче',rows)
