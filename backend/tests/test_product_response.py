import asyncio

import pytest
from app.services import product_response as pr


@pytest.fixture
def product():
    return {'ready': True, 'packaged': True, 'stack': 'static', 'path': 'products/demo',
            'brief': 'Лендинг инженерного бюро с портфолио', 'archive': 'product-demo.zip',
            'gates': {'build': True, 'test': True, 'smoke': True}}


def test_explanation_uses_saved_readme_and_keeps_acceptance_separate(monkeypatch, product):
    import openai_client
    from conversations import conversation_manager
    from app.services import sandbox_client
    captured=[]
    async def read(name,args,uid):
        assert name=='workspace_read' and args['path']=='products/demo/README.md'
        return '# Бюро Север\nПортфолио инженерных проектов. Запуск: python -m http.server 8000'
    async def model(messages,**kwargs):
        captured.append(messages)
        return 'Собрал страницу бюро «Север» с портфолио инженерных проектов.\n\nДля запуска откройте папку и выполните `python -m http.server 8000`.',[], '', []
    monkeypatch.setattr(sandbox_client,'run_workspace_tool',read)
    monkeypatch.setattr(openai_client,'get_chat_response',model)
    monkeypatch.setattr(conversation_manager,'get_subscription',lambda uid:{'tier':'creator'})
    answer,_=asyncio.run(pr.compose_product_response('Сделай сайт бюро',product,123))
    assert 'портфолио' in answer and 'http.server 8000' in answer
    assert '[!SUCCESS]' in answer and 'Браузерная проверка' in answer
    assert 'README' in captured[0][0]['content']
    assert 'Бюро Север' in captured[0][1]['content']
    assert 'Проект собран на стеке' not in answer


def test_failed_acceptance_never_calls_the_formatter(product):
    for key in ['ready','packaged']:
        with pytest.raises(ValueError):
            asyncio.run(pr.compose_product_response('Сделай сайт',{**product,key:False},123))
        assert pr.acceptance_note({**product,key:False})==''


def test_budget_fallback_still_describes_this_project(monkeypatch,product):
    import openai_client
    from app.services import sandbox_client
    async def read(*args):raise RuntimeError('offline')
    async def forbidden(*args,**kwargs):raise AssertionError('No paid formatting after budget exhaustion')
    monkeypatch.setattr(sandbox_client,'run_workspace_tool',read)
    monkeypatch.setattr(openai_client,'get_chat_response',forbidden)
    answer,_=asyncio.run(pr.compose_product_response('Сделай сайт',product,123,budget_exhausted=True))
    assert product['brief'] in answer and '[!SUCCESS]' in answer
    python_note=pr.acceptance_note({**product,'stack':'python','gates':{'build':True,'test':True}})
    assert 'Браузерная' not in python_note
