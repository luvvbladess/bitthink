import asyncio
import pytest
from app.config import get_settings
from computer_skills.loader import match_skills
import director_router as director
import marketplace_verification as verification


@pytest.mark.parametrize('task',[
    'сколько стоит ваще наушники лоджитек г435 в магазе ДНС',
    'сколько стоят наушники Logitech G435 в DNS',
    'цена Logitech G435 dns-shop.ru',
])
def test_dns_price_queries_use_marketplace_reader(task):
    assert 'marketplaces' in match_skills(task,sandbox=False)
    assert director._is_shopping_task(task,None)
    assert verification.single_store_price_lookup(task)


@pytest.mark.parametrize('task',['настрой DNS сервер', 'цена DNS сервера', 'измени DNS запись CNAME', 'топ наушников озон', 'Сравни цены DNS и Ozon', 'сколько стоят наушники в DNS и Ozon'])
def test_dns_protocol_and_comparisons_are_not_single_price_lookup(task):
    assert not verification.single_store_price_lookup(task)
    if 'сервер' in task or 'CNAME' in task:
        assert 'marketplaces' not in match_skills(task,sandbox=False)


def test_direct_answer_with_tools_does_not_announce_writing_before_search(monkeypatch):
    events=[]
    async def plan(*a,**k):return {'status':'done','new_employees':[]}
    async def direct(*a,**k):
        assert not any(text.startswith('Собираю итоговый ответ') for text in events)
        events.extend(['search','browse'])
        return 'Готово','',[]
    async def status(_,text,kind='work'):events.append(text)
    monkeypatch.setattr(director,'_plan_round',plan)
    monkeypatch.setattr(director,'_answer_directly',direct)
    monkeypatch.setattr(director,'_update_status',status)
    monkeypatch.setattr(director,'_is_light_task',lambda *a:False)
    monkeypatch.setattr(director,'_is_shopping_task',lambda *a:False)
    monkeypatch.setattr(director,'_ensure_research_plan',lambda n,p,*a:p)
    result=asyncio.run(director._run_director([],'Поясни вопрос',99001,None))
    assert result[0]=='Готово' and events[-1]=='browse'


def test_single_dns_price_uses_one_search_employee_then_live_card(monkeypatch):
    events=[]
    async def planner(*a,**k): raise AssertionError('Unnecessary planning round for one store price')
    async def employee(*a,**k): events.append('search'); return {'round':1,'role':'Поиск','status':'ok','model':'test','result':'Кандидат','search':[{'query':'Logitech G435 DNS','summary':'https://www.dns-shop.ru/product/abc/'}]}
    async def read(*a,**k):events.append('reader');return [{'round':0,'status':'ok','role':'Карточка','model':'reader','result':'Цена 4499 ₽','search':[]}]
    async def compose(*a,**k):events.append('compose');return '4499 ₽',''
    async def files(*a):return []
    async def status(*a):pass
    monkeypatch.setattr(director,'_plan_round',planner)
    monkeypatch.setattr(director,'_execute_employee',employee)
    monkeypatch.setattr(director,'_is_light_task',lambda *a:False)
    monkeypatch.setattr(director,'needs_research',lambda *a:True)
    monkeypatch.setattr(director,'_compose_answer',compose)
    monkeypatch.setattr(director,'_new_file_names',files)
    monkeypatch.setattr(director,'_update_status',status)
    monkeypatch.setattr(verification,'verify_marketplace_cards',read)
    assert asyncio.run(director._run_director([], 'сколько стоят Logitech G435 в DNS', None, None))[0] == '4499 ₽'
    assert events == ['search','reader','compose']
