import asyncio
import time

import pytest

from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path
import search_engine
import web_scraper as ws


def test_category_urls_are_discovery_not_verified_offers():
    for url in ('https://www.ozon.ru/category/jbl-720bt/', 'https://www.wildberries.ru/catalog/tags/jbl', 'https://market.yandex.ru/search?text=jbl'):
        assert 'НЕ проверенная карточка' in ws._mark_listing_page(url,'Товары и цены')
    for url in ('https://www.ozon.ru/product/jbl-123/', 'https://www.wildberries.ru/catalog/123/detail.aspx', 'https://market.yandex.ru/card/jbl/123'):
        assert ws._mark_listing_page(url,'Карточка')=='Карточка'


def test_listing_html_exposes_real_card_urls_without_private_links():
    html='<main><a href="/product/jbl-123/">JBL продавец 1</a><a href="/product/jbl-456/">JBL продавец 2</a><a href="/my/orderlist">Заказы</a><a href="https://evil.test/product/789">Fake</a></main>'
    content=ws._clean_html(html,'https://www.ozon.ru/category/jbl/')
    assert 'https://www.ozon.ru/product/jbl-123/' in content
    assert 'https://www.ozon.ru/product/jbl-456/' in content
    assert '/my/orderlist' not in content and 'https://evil.test' not in content
from handlers import core

OZON = "https://www.ozon.ru/product/apple-smartfon-iphone-15-128-gb-chernyy-1538860569/?at=abc"
OZON_WALL = "Похоже, нет соединения\nВыключите VPN, перезагрузите роутер или подключитесь к другой сети\nИнцидент: fab_nmk_20"


def test_url_slug_becomes_a_search_query_and_a_sku():
    query, sku = ws._query_from_url(OZON)
    assert query == "ozon apple smartfon iphone 15 128 gb chernyy"
    assert sku == "1538860569"
    query, sku = ws._query_from_url("https://www.ozon.ru/search/?text=iphone+15&from_global=true")
    assert query == "ozon iphone 15" and sku == ""


def test_bot_walls_are_recognised_but_long_pages_are_not():
    assert ws._looks_like_bot_wall(OZON_WALL)
    assert ws._looks_like_bot_wall("Вы не робот?\nПодтвердите, что запросы отправляли вы, а не робот")
    assert not ws._looks_like_bot_wall("Статья про captcha. " * 400)
    assert ws.is_bot_walled_host("https://www.ozon.ru/x") and ws.is_bot_walled_host("https://m.avito.ru/x")
    assert not ws.is_bot_walled_host("https://example.com/ozon.ru")


@pytest.fixture
def blocked(monkeypatch):
    """Ozon answers 403, the RU proxy is not available, search knows the product."""
    async def direct(_session, _url):
        return 403, ""

    async def no_proxy(_session, _url):
        return -1, ""

    async def search(query, max_results=8):
        search.queries.append(query)
        return [
            {"title": "Отзывы - DNS", "url": "https://www.dns-shop.ru/x", "snippet": "другое"},
            {"title": "Смартфон Apple iPhone 15 128 ГБ Черный - OZON", "url": "https://www.ozon.ru/product/apple-smartfon-iphone-15-128-gb-chernyy-1538860569/", "snippet": "45 111 ₽, рейтинг 4,9"},
        ]

    search.queries = []

    async def kimi_must_not_run(_url):
        raise AssertionError("Kimi fetch is blocked too: not worth a call")

    monkeypatch.setattr(ws, "_fetch_direct", direct)
    monkeypatch.setattr(ws, "_fetch_via_ru_proxy", no_proxy)
    monkeypatch.setattr(search_engine, "search_web", search)
    monkeypatch.setattr(ws, "_recover_with_kimi_fetch", kimi_must_not_run)
    return search


def test_a_walled_page_is_answered_from_the_search_index(blocked):
    _, text = asyncio.run(ws.fetch_url_content(OZON))
    assert "закрыт от автоматического чтения" in text
    assert "45 111 ₽" in text and "Смартфон Apple iPhone 15" in text
    assert "Google" not in text  # the old dead cache returned a Google stub as "content"
    assert blocked.queries[0] == "ozon apple smartfon iphone 15 128 gb chernyy"
    assert text.index("ozon.ru/product") < text.index("dns-shop.ru")  # the same site first


def test_a_200_challenge_page_counts_as_blocked(monkeypatch, blocked):
    async def direct(_session, _url):
        return 200, "<html><body><h1>Вы не робот?</h1><p>Подтвердите, что запросы отправляли вы, а не робот</p></body></html>"

    monkeypatch.setattr(ws, "_fetch_direct", direct)
    _, text = asyncio.run(ws.fetch_url_content("https://market.yandex.ru/product/1/2"))
    assert "закрыт от автоматического чтения" in text


def test_nothing_found_says_so_without_the_old_excuse(monkeypatch, blocked):
    async def nothing(query, max_results=8):
        return []

    monkeypatch.setattr(search_engine, "search_web", nothing)
    _, text = asyncio.run(ws.fetch_url_content(OZON))
    assert text.startswith("[Сайт защищён")
    assert "не пиши «нет соединения»" in text


def test_a_dead_proxy_costs_one_timeout_not_one_per_page(monkeypatch):
    calls = []

    class Session:
        def get(self, *_a, **_k):
            calls.append(1)
            raise asyncio.TimeoutError()

    monkeypatch.setattr(ws, "RU_PROXY_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(ws, "_proxy_down_until", 0.0)
    assert asyncio.run(ws._fetch_via_ru_proxy(Session(), OZON)) == (-1, "")
    assert asyncio.run(ws._fetch_via_ru_proxy(Session(), OZON)) == (-1, "")
    assert len(calls) == 1 and ws._proxy_down_until > time.time()
    monkeypatch.setattr(ws, "_proxy_down_until", 0.0)


def test_only_walled_links_are_read_ahead(monkeypatch):
    seen = []

    async def fake_fetch(url, **_k):
        seen.append(url)
        return url, "карточка товара"

    monkeypatch.setattr(ws, "fetch_url_content", fake_fetch)
    assert asyncio.run(ws.walled_links_context("прочитай https://example.com/a и скажи")) == ""
    block = asyncio.run(ws.walled_links_context(f"сколько стоит {OZON} ? и https://example.com/a"))
    assert seen == [OZON] and "карточка товара" in block


def test_link_block_goes_into_the_users_own_message():
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "что это?"}]
    out = core._with_link_context(messages, "БЛОК")
    assert out[-1]["content"] == "что это?\n\nБЛОК"
    assert messages[-1]["content"] == "что это?"  # the stored thread is untouched
    out = core._with_link_context([{"role": "user", "content": [{"type": "text", "text": "x"}]}], "БЛОК")
    assert out[-1] == {"role": "system", "content": "БЛОК"}


def test_ru_marketplace_routing_checks_domain_boundaries():
    assert ws.is_ru_marketplace(OZON)
    assert ws.is_ru_marketplace('https://www.mvideo.ru/products/1')
    assert not ws.is_ru_marketplace('https://ozon.ru.example.com/1')
    assert not ws.is_ru_marketplace('https://example.com/ozon.ru')
    assert not ws.is_ru_marketplace('https://www.ozon.kz/product/1')


@pytest.mark.parametrize('proxy_status', [200, -1, 403])
def test_marketplace_uses_ru_route_first_and_keeps_fallbacks(monkeypatch, proxy_status):
    calls = []
    page = '<html><body><main>' + 'Телефон 128 ГБ. Цена 45111 рублей. ' * 20 + '</main></body></html>'

    async def proxy(_session, _url):
        calls.append('proxy')
        return proxy_status, page if proxy_status == 200 else ''

    async def direct(_session, _url):
        calls.append('direct')
        return 200, page

    async def search(_url):
        calls.append('search')
        return '[Сведения поискового индекса]'

    monkeypatch.setattr(ws, 'RU_PROXY_URL', 'http://user:password@localhost:18128')
    monkeypatch.setattr(ws, '_fetch_via_ru_proxy', proxy)
    monkeypatch.setattr(ws, '_fetch_direct', direct)
    monkeypatch.setattr(ws, '_recover_from_search', search)
    _, text = asyncio.run(ws._fetch_url_content_local(OZON))
    if proxy_status == 200:
        assert calls == ['proxy'] and '45111' in text
    elif proxy_status == -1:
        assert calls == ['proxy', 'direct'] and '45111' in text
    else:
        assert calls == ['proxy', 'search'] and 'поискового индекса' in text


def test_ordinary_page_still_uses_direct_route(monkeypatch):
    calls = []
    async def direct(_session, _url):
        calls.append('direct')
        return 200, '<html><body>' + 'Обычная статья. ' * 40 + '</body></html>'
    async def proxy(_session, _url):
        raise AssertionError('RU proxy should not handle ordinary articles')
    monkeypatch.setattr(ws, 'RU_PROXY_URL', 'http://localhost:18128')
    monkeypatch.setattr(ws, '_fetch_direct', direct)
    monkeypatch.setattr(ws, '_fetch_via_ru_proxy', proxy)
    _, text = asyncio.run(ws._fetch_url_content_local('https://example.com/article'))
    assert calls == ['direct'] and 'Обычная статья' in text


def test_product_json_ld_keeps_price_and_reviews_from_js_pages():
    html = '''<html><body><script type="application/ld+json">
    {"@graph":[{"@type":"Product","name":"Телефон","sku":"123",
    "offers":{"price":"45111","priceCurrency":"RUB","availability":"InStock"},
    "aggregateRating":{"ratingValue":4.9,"reviewCount":125}}]}
    </script><script>var price = 0;</script><p>Магазин</p></body></html>'''
    text = ws._clean_html(html)
    assert '45111' in text and 'RUB' in text and '4.9' in text and '125' in text
    assert 'var price' not in text
    assert 'Данные товара из страницы' in text


def test_invalid_product_json_ld_does_not_break_page_reading():
    assert 'Товар' in ws._clean_html('<script type="application/ld+json">broken</script><p>Товар</p>')
    assert ws._looks_like_bot_wall('Are you not a robot? Please solve this captcha')


def test_marketplace_query_keeps_all_compact_buying_criteria(monkeypatch):
    import computer_tools
    text = "Цена: 4282 ₽\nПродавец: Магазин\n" + ("Описание. " * 850) + "\nОтзывы: 1273, рейтинг 4.8\nКомплект: USB-приёмник"
    async def fetch(url):
        return url, text
    monkeypatch.setattr(ws, "fetch_url_content", fetch)
    monkeypatch.setattr(computer_tools, "_assert_public_http_url", lambda url: url)
    result = asyncio.run(computer_tools._browse_public(OZON, "описание наушников"))
    assert "Цена: 4282" in result and "Продавец: Магазин" in result
    assert "Отзывы: 1273, рейтинг 4.8" in result and "Комплект: USB-приёмник" in result
    assert len(result) <= computer_tools.MAX_TOOL_OUTPUT
