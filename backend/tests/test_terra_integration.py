import asyncio
from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.config import get_settings
from app.billing.plans import allowed_models, clamp_model, our_tokens, LEGACY_MODEL_ALIASES
from app.billing.costs import model_cost_usd


def test_terra_cost_permissions_and_legacy_alias():
    assert 'gpt-6.1-terra' in allowed_models('pro')
    assert 'gpt-6.1-terra' not in allowed_models('free')
    assert clamp_model('free', 'gpt-6.1-terra') == 'gpt-6-luna'
    assert our_tokens('gpt-6.1-terra', 100, 20) == 1200
    assert model_cost_usd('gpt-6.1-terra', 10000, 1000) == pytest.approx(.015)
    assert model_cost_usd('gpt-6.1-terra', 10000, 1000, cached_input_tokens=10000) == pytest.approx(.0055)
    assert LEGACY_MODEL_ALIASES['gpt-5.6-terra'] == 'gpt-6-sol'


@pytest.mark.parametrize('selected,tier,prompt,expected', [
    ('auto','pro','Что видно на скриншоте?', 'gpt-6.1-terra'),
    ('auto','free','Прочитай фото', 'gpt-6-luna'),
    ('gpt-6-sol','pro','Прочитай фото', 'gpt-6-sol'),
    ('gpt-6-astra','proplus','Прочитай фото', 'gpt-6-astra'),
    ('auto','pro','Чертёж: проверь размеры и допуски', 'gpt-6-sol'),
])
def test_routine_vision_keeps_budget_and_strong_routes(selected,tier,prompt,expected):
    from routing import vision_route
    assert vision_route(selected,tier,prompt)==expected


def test_terra_registry_and_reasoning():
    from config import AVAILABLE_MODELS
    from model_context import max_output_tokens, window_for
    from openai_client import _get_reasoning_config, _api_model_id
    assert 'gpt-6.1-terra' in AVAILABLE_MODELS
    assert max_output_tokens('gpt-6.1-terra') == 128000
    assert window_for('gpt-6.1-terra').context == 1050000
    assert _get_reasoning_config('gpt-6.1-terra') == {'effort':'low'}
    assert _api_model_id('gpt-6.1-terra') == 'gpt-6.1-terra'


@pytest.mark.parametrize('web', [False, True])
def test_local_project_read_is_not_erased_by_web_citation_guard(monkeypatch, web):
    import handlers.core as core
    import director_router
    from app.services.desktop_context import desktop_executor, desktop_cwd
    uid=860_000_000+uuid4().int%10_000_000
    core.conversation_manager.set_subscription_tier(uid,'pro',30,from_today=True)
    monkeypatch.setattr(core.conversation_manager,'conversation_for_turn',lambda _:None)
    reads=[]
    async def executor(name,args):
        reads.append(name)
        return 'index.html: <h1>ENALT — энергетическое оборудование</h1>\ncss/site.css: body {color:#123}'
    answer = ('Это сайт ENALT об энергетическом оборудовании. Главная страница — index.html, стили — css/site.css.'
              if not web else 'Цена указана в карточке: 30 000 ₽. [Карточка](https://example.com/product)')
    async def director(*args,**kwargs):
        await desktop_executor.get()('workspace_read',{'path':'index.html'})
        sources=[{'query':'Источник','summary':'https://example.com/product\nСведения', 'evidence_state':'read' if web else 'retrieved'}]
        return answer,[],'',sources
    async def forbidden(*args,**kwargs):raise AssertionError('No extra verifier/model call expected')
    monkeypatch.setattr(director_router,'get_director_response',director)
    monkeypatch.setattr(core,'get_chat_response',forbidden)
    token=desktop_executor.set(executor);folder=desktop_cwd.set('C:/fixture/enalt')
    try:
        query='Найди актуальную цену в интернете' if web else 'что это за проект'
        result=asyncio.run(core.get_smart_response(uid,query,[{'role':'user','content':query}],None))
        assert answer==result[0] and reads==['workspace_read']
        assert 'Проверенных данных' not in result[0]
    finally:desktop_executor.reset(token);desktop_cwd.reset(folder)
