import asyncio

import httpx
from fastapi import FastAPI
import pytest

from app.config import get_settings
from app.api import marketplace_relay as api
from app.services import marketplace_relay as service
import web_scraper as ws

URL = 'https://www.ozon.ru/product/123456789/'
TOKEN = 'test-only-home-reader-token-' + 'x' * 32


@pytest.fixture
def relay(monkeypatch):
    instance = service.HomeRelay()
    monkeypatch.setattr(service, 'home_relay', instance)
    monkeypatch.setattr(api, 'home_relay', instance)
    monkeypatch.setattr(get_settings(), 'HOME_RELAY_TOKEN', TOKEN)
    return instance


def test_offline_or_unrelated_pages_do_not_wait(relay):
    async def run():
        assert await relay.fetch(URL) is None
        relay.heartbeat()
        for url in ('https://example.com/', 'https://ozon.ru.evil.test/', 'http://www.ozon.ru/', 'https://www.ozon.ru:8080/'):
            assert await relay.fetch(url) is None
        assert not relay.jobs and relay.queue.empty()
    asyncio.run(run())


def test_component_store_is_routed_to_home_reader(relay):
    url = 'https://www.chipdip.ru/product/stm32f103c8t6'
    async def run():
        relay.heartbeat()
        task = asyncio.create_task(relay.fetch(url))
        job = await relay.pull(wait=.1)
        assert job['url'] == url
        relay.complete(job['id'], {'status':'ok','url':url,'text':'В наличии 120 шт. Поставка 3 рабочих дня.'})
        assert (await task)['status'] == 'ok'
        assert await relay.fetch('https://chipdip.ru.evil.test/product/x') is None
    asyncio.run(run())


def test_private_protocol_delivers_rendered_content_and_checks_auth(relay):
    async def run():
        app = FastAPI()
        app.include_router(api.router, prefix='/marketplace-relay')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.get('/marketplace-relay/status')).status_code == 401
            assert (await client.post('/marketplace-relay/heartbeat')).status_code == 401
            client.headers['Authorization'] = 'Bearer ' + TOKEN
            assert (await client.post('/marketplace-relay/heartbeat')).status_code == 200
            task = asyncio.create_task(relay.fetch(URL))
            await asyncio.sleep(0)
            response = await client.get('/marketplace-relay/jobs')
            job = response.json()['job']
            assert job['url'] == URL
            data = {'status': 'ok', 'url': URL, 'title': 'Телефон', 'text': 'Цена 45111 рублей. Рейтинг 4,9.' * 5}
            response = await client.post('/marketplace-relay/jobs/' + job['id'], json=data)
            assert response.status_code == 200
            assert await task == data
            assert (await client.post('/marketplace-relay/jobs/' + job['id'], json=data)).status_code == 410
            status = await client.get('/marketplace-relay/status')
            assert status.json() == {'online': True, 'pending': 0}
            assert status.headers['cache-control'] == 'no-store'
            assert TOKEN not in status.text
    asyncio.run(run())


def test_results_cannot_point_to_private_addresses_or_be_unbounded(relay):
    async def run():
        app = FastAPI()
        app.include_router(api.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Authorization': 'Bearer ' + TOKEN}) as client:
            assert (await client.post('/jobs/unknown', json={'status': 'ok', 'url': 'https://127.0.0.1/', 'text': 'x'})).status_code == 422
            assert (await client.post('/jobs/unknown', json={'status': 'ok', 'url': URL, 'text': 'x' * 80_001})).status_code == 422
            assert (await client.post('/jobs/unknown', content=b'x' * 512_001)).status_code == 413
    asyncio.run(run())


def test_private_inspection_and_reader_diagnostics(relay):
    async def run():
        app=FastAPI();app.include_router(api.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.post('/inspect',json={'url':URL})).status_code==401
            client.headers['Authorization']='Bearer '+TOKEN
            assert (await client.post('/inspect',json={'url':'https://www.ozon.ru/my/orders'})).status_code==422
            await client.post('/heartbeat',json={'reader_version':'1.8.0'})
            task=asyncio.create_task(client.post('/inspect',json={'url':URL}));await asyncio.sleep(0)
            job=await relay.pull(wait=.1)
            data={'status':'ok','url':URL,'text':'ТЕКСТЫ ОТЗЫВОВ: покупатель хвалит звук.','reader_version':'1.8.0','review_diagnostics':{'source':'dom','count':1}}
            assert (await client.post('/jobs/'+job['id'],json=data)).status_code==200
            result=(await task).json()
            assert result['reader_version']=='1.8.0' and 'хвалит звук' in result['result']['text']
            info=(await client.get('/diagnostics')).json()
            assert info['recent'][0]['reviews']['count']==1
            assert 'хвалит звук' not in str(info) and TOKEN not in str(info)
    asyncio.run(run())


def test_expired_job_is_cleaned_up_and_cannot_be_completed(relay, monkeypatch):
    async def run():
        monkeypatch.setattr(service, 'JOB_TIMEOUT', .02)
        relay.heartbeat()
        task = asyncio.create_task(relay.fetch(URL))
        await asyncio.sleep(0)
        job = await relay.pull(wait=.01)
        assert await task is None
        assert not relay.jobs
        assert not relay.complete(job['id'], {'status': 'ok'})
    asyncio.run(run())


def test_stopping_home_reader_immediately_releases_waiting_page(relay):
    async def run():
        relay.heartbeat()
        task = asyncio.create_task(relay.fetch(URL))
        await asyncio.sleep(0)
        relay.disconnect()
        assert await task is None
        assert not relay.online and not relay.jobs and relay.queue.empty()
    asyncio.run(run())


def test_scraper_uses_home_page_content_before_server_fallback(relay, monkeypatch):
    async def server_must_not_run(_url):
        raise AssertionError('Home page should be used directly')
    monkeypatch.setattr(ws, '_fetch_url_content_local', server_must_not_run)
    async def run():
        relay.heartbeat()
        task = asyncio.create_task(ws.fetch_url_content(URL))
        await asyncio.sleep(0)
        job = await relay.pull(wait=.1)
        relay.complete(job['id'], {'status': 'ok', 'url': URL, 'text': 'Телефон. Цена 45111 рублей. Рейтинг 4,9. ' * 20})
        url, text = await task
        assert url == URL and '45111' in text
    asyncio.run(run())


def test_home_captcha_does_not_become_product_content(relay, monkeypatch):
    async def server(_url):
        return _url, '[Сведения поискового индекса]'
    monkeypatch.setattr(ws, '_fetch_url_content_local', server)
    async def run():
        relay.heartbeat()
        task = asyncio.create_task(ws.fetch_url_content(URL))
        await asyncio.sleep(0)
        job = await relay.pull(wait=.1)
        relay.complete(job['id'], {'status': 'blocked', 'url': URL, 'text': 'captcha'})
        _, text = await task
        assert text == '[Сведения поискового индекса]'
    asyncio.run(run())


def test_marketplace_skill_browse_tool_reads_home_page(relay, monkeypatch):
    from computer_tools import run_computer_tool

    async def forbidden(_url):
        raise AssertionError('Home result must be used before the server fallback')
    monkeypatch.setattr(ws, '_fetch_url_content_local', forbidden)
    async def run():
        relay.heartbeat()
        task = asyncio.create_task(run_computer_tool('browse_page', {'url': URL}, user_id=1))
        job = await relay.pull(wait=.1)
        assert job['url'] == URL
        relay.complete(job['id'], {'status':'ok','url':URL,'text':
            'Товар. Цена 1520 рублей. Характеристики: высота 10 см. Отзывы: покупатель хвалит детализацию.'})
        result = await task
        assert '1520' in result and 'высота 10 см' in result and 'хвалит детализацию' in result
    asyncio.run(run())


def test_kimi_employee_browse_reads_home_page(relay, monkeypatch):
    import kimi_client
    import kimi_web_search
    async def forbidden(*args, **kwargs):
        raise AssertionError('External fetch must not run before the home reader')
    monkeypatch.setattr(kimi_web_search, 'kimi_fetch', forbidden)
    monkeypatch.setattr(ws, '_fetch_url_content_local', forbidden)
    async def run():
        relay.heartbeat()
        task=asyncio.create_task(kimi_client._execute_kimi_tool('browse_page', {'url':URL}))
        job=await relay.pull(wait=.1)
        assert job['url']==URL
        relay.complete(job['id'], {'status':'ok','url':URL,'text':'Домашний браузер. Наушники. Цена 4253 рубля. В наличии. Доставка завтра.'})
        content,sources=await task
        assert '4253' in content and sources[0]['summary']==URL
    asyncio.run(run())


def test_same_turn_reuses_short_link_and_final_card_without_second_job(relay):
    from turn_scope import turn_conversation
    short='https://ozon.ru/t/l1zlv1V'
    async def run():
        relay.heartbeat()
        with turn_conversation('test-radio-comparison'):
            task=asyncio.create_task(relay.fetch(short))
            job=await relay.pull(wait=.1)
            relay.complete(job['id'],{'status':'ok','url':URL,'text':'Характеристики рации, цена и отзывы.'})
            original=await task
            assert await relay.fetch(short)==original
            assert await relay.fetch(URL)==original
            assert relay.queue.empty()
        with turn_conversation('different-turn'):
            task=asyncio.create_task(relay.fetch(short))
            job=await relay.pull(wait=.1)
            assert job is not None
            relay.complete(job['id'],{'status':'ok','url':URL,'text':'Новая проверка.'})
            assert (await task)['text']=='Новая проверка.'
    asyncio.run(run())
