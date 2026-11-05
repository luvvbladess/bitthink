import asyncio
from io import BytesIO
from docx import Document
from app.services import simple_docx

def test_one_call_docx_and_exact_source_revision(monkeypatch):
    import openai_client
    source={'text':None};calls=[]
    monkeypatch.setattr(simple_docx,'previous',lambda uid:source['text'])
    async def write(messages,**kwargs):
        calls.append((messages,kwargs));return 'Здравствуйте! Предложение направим в пятницу.\n\nАнна',[], '',[]
    monkeypatch.setattr(openai_client,'get_chat_response',write)
    for prompt in ['Сохрани в DOCX короткое письмо клиенту, подпись Анна.','Сделай короче и сохрани в DOCX, срок — пятница.']:
        result=asyncio.run(simple_docx.respond([],prompt,1,None));assert result
        doc=Document(BytesIO(result[1][0]['bytes']));assert doc.core_properties.identifier==simple_docx.MARKER
        assert 'Анна' in '\n'.join(p.text for p in doc.paragraphs)
        source['text']='Original source document'
    assert len(calls)==2 and all(not call[1]['use_tools'] for call in calls)
    assert 'Original source document' in calls[1][0][-1]['content']

def test_complex_or_unrelated_work_uses_existing_pipeline():
    for text in ['Сделай договор в DOCX','Объясни историю','Уточни по выделенному фрагменту: письмо в DOCX','Собери таблицу в DOCX','По шаблону сделай письмо в DOCX','Сделай презентацию в PDF']:
        assert not simple_docx.request(text)
