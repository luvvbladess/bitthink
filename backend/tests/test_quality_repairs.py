import pytest
from app.services.run_protocol import RunRecord
from app.services.page_excerpt import page_excerpt
from app.services.subject_guidance import subject_note
from evals.quality import score_answer
from docgen_router import handles_document_turn

@pytest.mark.parametrize('text', [
 'У взрослого перекосило лицо и стала невнятной речь. Что делать?',
 'Сколько будет 8000 + 20%?',
 'Найди актуальную ключевую ставку',
 'Напиши письмо поставщику о задержке',
 'Составь план изучения Python на 4 недели. Цель — читать CSV и строить отчёт.',
])
def test_documents_mode_routes_questions_to_chat(text):
 assert not handles_document_turn(text, [{'role':'user','content':text}])

@pytest.mark.parametrize('text', ['Создай документ на 5 страниц', 'Подготовь отчёт о продажах', 'Напиши договор поставки'])
def test_real_document_requests_keep_confirmation(text):
 assert handles_document_turn(text, [{'role':'user','content':text}])

def test_document_followup_and_urgent_override():
 messages=[{'role':'assistant','content':'Разделов: 3, примерно 4 стр.'}, {'role':'user','content':'Замени шаблон'}]
 assert handles_document_turn('Замени шаблон', messages)
 assert not handles_document_turn('Перекосило лицо, что делать?', messages)

def test_read_failures_share_url_but_keep_query_parameters():
 r=RunRecord()
 assert r.read_key('browse_page', {'url':'https://example.com/a#one','query':'first'}) == r.read_key('browse_page', {'url':'https://example.com/a#two','query':'second'})
 assert r.read_key('browse_page', {'url':'https://example.com/a?v=1'}) != r.read_key('browse_page', {'url':'https://example.com/a?v=2'})

def test_full_article_is_selected_after_toc():
 body='Статья 142. Оглавление\n' + 'Навигация\n'*1500 + 'Статья 142. Ответственность\nРаботник вправе приостановить работу после письменного уведомления.\n' + 'Другие сведения\n'*1500
 result=page_excerpt(body, 'Проверь статью 142 ТК РФ', budget=1200)
 assert 'Работник вправе приостановить' in result

def test_finance_note_preserves_comparison_constraints():
 note=subject_note('Сравни долг 100000 под 40% и вклад под 15%')
 for term in ['основного долга','резерв','льготный период','Налог']:
  assert term in note

def test_expected_abstention_is_not_incomplete_but_empty_still_fails():
 case={'id':'uncertainty','expect':{'web':False},'expected_abstention':True}
 answer='Не могу назвать число: нет доступа к аналитике. Нужен отчёт о посетителях и визитах.'
 assert score_answer(case,answer,[])['passed']
 assert not score_answer(case,'',[])['passed']

def test_local_calculation_does_not_need_inline_web_citation():
 sources=[{'summary':'https://example.com\nUnrelated','evidence_state':'read'}]
 assert score_answer({'id':'math','expect':{'web':False}},'Цена 7680 рублей, снижение 4%.',sources)['passed']
 assert not score_answer({'id':'current','expect':{'web':True}},'Цена 7680 рублей, снижение 4%.',sources)['passed']

@pytest.mark.parametrize('kind', ['text', 'scanned', 'invalid', 'oversized'])
def test_pdf_reader_is_bounded_and_does_not_invent_text(kind):
 import asyncio
 from types import SimpleNamespace
 import fitz
 from web_scraper import _read_pdf_response
 if kind in {'text','scanned'}:
  with fitz.open() as doc:
   page=doc.new_page()
   if kind=='text':page.insert_text((72,72), 'Trial: 61 companies, 2900 workers. Revenue increased 1.4%.')
   data=doc.tobytes()
 else:data=b'not a pdf'
 class Body:
  async def iter_chunked(self, size):
   if kind=='oversized':
    for _ in range(161):yield b'x'*65536
   else:yield data
 status, html=asyncio.run(_read_pdf_response(SimpleNamespace(content=Body())))
 if kind=='text':
  assert status==200 and '61 companies' in html and '1.4%' in html
 else:
  assert status==-1 and html.startswith('[PDF')

def test_comparison_budget_can_read_three_offers_after_failed_candidates(monkeypatch):
 import asyncio
 from app.services.search_budget import SearchBudget, current_search_budget, configure_request_budget, LIMIT_NOTE
 from app.services.request_intent import classify_request
 import computer_tools
 seen=[]
 async def read(name,args,uid):
  seen.append(args['url'])
  return 'observed'
 monkeypatch.setattr(computer_tools, '_run_budgeted_computer_tool', read)
 async def run():
  token=current_search_budget.set(SearchBudget())
  try:
   query='Сравни три ноутбука до 80000 рублей, проверь цены и наличие'
   configure_request_budget(classify_request(query), query)
   for i in range(6):
    assert await computer_tools.run_computer_tool('browse_page',{'url':f'https://example.com/{i}'},1)=='observed'
   assert await computer_tools.run_computer_tool('browse_page',{'url':'https://example.com/extra'},1)==LIMIT_NOTE
  finally:current_search_budget.reset(token)
 asyncio.run(run())
 assert len(seen)==6

@pytest.mark.parametrize('reader_name', ['_fetch_direct','_fetch_via_ru_proxy'])
def test_public_pdf_enters_both_http_readers(monkeypatch, reader_name):
 import asyncio
 import fitz
 import web_scraper as reader
 monkeypatch.setattr(reader, 'RU_PROXY_URL', 'http://proxy.example')
 monkeypatch.setattr(reader, '_proxy_down_until', 0)
 with fitz.open() as doc:
  page=doc.new_page();page.insert_text((72,72),'Study sample: 61 companies.')
  data=doc.tobytes()
 class Response:
  status=200
  headers={'Content-Type':'application/pdf'}
  @property
  def content(self):return self
  async def iter_chunked(self,size):yield data
  async def __aenter__(self):return self
  async def __aexit__(self,*args):pass
 class Session:
  def get(self,*args,**kwargs):return Response()
 status,html=asyncio.run(getattr(reader,reader_name)(Session(),'https://example.com/report.pdf'))
 assert status==200 and '61 companies' in html
