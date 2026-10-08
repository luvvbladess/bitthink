import asyncio
import pytest
from types import SimpleNamespace

from app.config import get_settings  # adds bot_core to sys.path
from app.services.marketplace_relay import home_relay
import marketplace_verification as mv
import director_router as dr
REAL_REPLACEMENT_SEARCH=mv.replacement_search

@pytest.fixture(autouse=True)
def isolated_buyer(monkeypatch):
    async def buyer(*args,**kwargs):return {}
    async def search(*args,**kwargs):return []
    monkeypatch.setattr(mv,"buyer_json",buyer)
    monkeypatch.setattr(mv,"replacement_search",search)


CARD = "https://www.ozon.ru/product/headphones-123/"
LIST = "https://www.ozon.ru/category/headphones/"


def test_answer_only_links_to_live_verified_products():
    journal=[{'live_verification':True,'status':'ok','requested_url':'https://ozon.ru/t/test123',
        'verified_url':CARD,'search':[{'reader':'home','read_status':'ok','query':CARD}]}]
    invented='https://www.ozon.ru/product/imaginary-999/'
    failed={'live_verification':True,'status':'error','search':[{'reader':'home','read_status':'not_found','query':invented}]}
    answer=f'[Товар](https://ozon.ru/t/test123) [Выдуманный]({invented}) [Подборка]({LIST}) {invented} [Производитель](https://example.com/spec)'
    result=mv.guard_answer_links(answer,journal+[failed])
    assert f'[Товар]({CARD})' in result
    assert invented not in result and LIST not in result and 'ozon.ru/t/' not in result
    assert '[Производитель](https://example.com/spec)' in result
    assert 'Непроверенные ссылки исключены' in result
    # Search results are not successful live verification.
    assert CARD not in mv.guard_answer_links(f'[Товар]({CARD})',[{'status':'ok','search':[{'query':CARD}]}])


def test_missing_page_cannot_be_verified_as_a_card(monkeypatch):
    monkeypatch.setattr(type(home_relay),'online',property(lambda _:True))
    async def fetch(url):return {'status':'ok','url':url,'title':'404','text':'Страница не найдена. Посмотрите похожие товары: цена 1000 рублей. '*5}
    monkeypatch.setattr(home_relay,'fetch',fetch)
    result=asyncio.run(mv.verify_marketplace_cards('сравни '+CARD,[]))
    assert result[0]['status']=='error'
    assert result[0]['search'][0]['read_status']=='not_found'
    assert 'похожие товары' not in result[0]['result']
    assert mv.page_failure_reason('Товар временно нет в наличии, ожидается поставка','Наушники') is None
    assert mv.page_failure_reason('Bad gateway','503') == 'unavailable'
    result=mv.guard_answer_links('http://www.ozon.ru/product/headphones-123/',[])
    assert 'http://' not in result


def test_only_exact_public_card_paths_and_requested_stores():
    journal = [{"result": f"{CARD} {CARD}?page=2 {LIST} https://www.ozon.ru/my/orders https://ozon.ru.evil.test/product/123/ https://market.yandex.ru/card/a/12 https://www.wildberries.ru/catalog/123/detail.aspx"}]
    cards, listings = mv.candidates("наушники с озона и вб",journal)
    assert cards == [CARD,"https://www.wildberries.ru/catalog/123/detail.aspx"]
    assert listings == [LIST]
    assert mv.public_shop_url("https://user:pw@www.ozon.ru/product/123/") is None
    assert mv.public_shop_url("https://www.ozon.ru:444/product/123/") is None


def test_wb_review_page_maps_to_same_product_card():
    assert mv.public_shop_url('https://www.wildberries.ru/catalog/123/feedbacks?imtId=456') == ('card','https://www.wildberries.ru/catalog/123/detail.aspx')
    assert mv.public_shop_url('https://www.wildberries.ru/catalog/123/feedbacks/private')[0] == 'listing'


def test_live_cards_are_read_even_when_search_only_agent_has_finished(monkeypatch):
    monkeypatch.setattr(type(home_relay),"online",property(lambda _:True))
    calls=[]
    async def fetch(url):
        calls.append(url)
        return {"status":"ok","url":url,"text":"Цена: 4282 ₽. Продавец: магазин. " + "Описание " * 700 + "Отзывы: 1273. Рейтинг: 4.8. Комплект: приёмник."}
    monkeypatch.setattr(home_relay,"fetch",fetch)
    result=asyncio.run(mv.verify_marketplace_cards("озон",[{"search":[{"query":"Наушники","summary":CARD}]}]))
    assert calls == [CARD]
    assert result[0]["status"] == "ok"
    assert result[0]["search"][0]["read_status"] == "ok"
    assert "Отзывы: 1273" in dr._format_journal_for_prompt(result)


def test_listing_discovers_card_but_never_verifies_listing_price(monkeypatch):
    monkeypatch.setattr(type(home_relay),"online",property(lambda _:True))
    calls=[]
    async def fetch(url):
        calls.append(url)
        if url==LIST:return {"status":"ok","url":url,"text":"Цена из каталога 1 ₽. " + CARD}
        return {"status":"blocked","url":url,"text":""}
    monkeypatch.setattr(home_relay,"fetch",fetch)
    result=asyncio.run(mv.verify_marketplace_cards("озон",[{"result":LIST}]))
    assert calls == [LIST,CARD]
    assert result[0]["status"] == "error"
    assert result[0]["search"][0]["read_status"] == "blocked"
    assert "1 ₽" not in result[0]["result"]


def test_offline_never_claims_attempt_or_confirmation(monkeypatch):
    monkeypatch.setattr(type(home_relay),"online",property(lambda _:False))
    async def forbidden(url):raise AssertionError("offline must not enqueue")
    monkeypatch.setattr(home_relay,"fetch",forbidden)
    result=asyncio.run(mv.verify_marketplace_cards("озон",[{"result":CARD}]))
    assert "НЕ открывались" in result[0]["result"]
    assert result[0]["status"] == "error"


def test_wall_and_wrong_product_are_never_verified(monkeypatch):
    monkeypatch.setattr(type(home_relay),"online",property(lambda _:True))
    async def fetch(url):return {"status":"ok","url":"https://www.ozon.ru/product/other-456/","text":"Описание другой карточки " * 10}
    monkeypatch.setattr(home_relay,"fetch",fetch)
    result=asyncio.run(mv.verify_marketplace_cards("озон",[{"result":CARD}]))
    assert result[0]["search"][0]["read_status"] == "invalid_content"


def test_director_cannot_skip_reader_with_empty_plan(monkeypatch):
    async def plan(*args,**kwargs):return {"status":"done","new_employees":[]}
    async def direct(*args,**kwargs):return "Непроверенные наушники", "", [{"query":"Наушники","summary":CARD}]
    async def status(*args,**kwargs):pass
    async def files(*args,**kwargs):return []
    async def compose(task,journal,*args,**kwargs):
        assert any(e.get("live_verification") for e in journal)
        return f"Ответ после проверки [Товар]({CARD}) [Выдуманная ссылка](https://www.ozon.ru/product/invented-999/)", ""
    async def fetch(url):
        assert url == CARD
        return {"status":"ok","url":url,"text":"Цена 4282 ₽. Продавец магазин. Рейтинг 4.8, 1273 отзыва. Комплект USB-приёмник."}
    monkeypatch.setattr(dr,"_plan_round",plan)
    monkeypatch.setattr(dr,"_answer_directly",direct)
    monkeypatch.setattr(dr,"_update_status",status)
    monkeypatch.setattr(dr,"_new_file_names",files)
    monkeypatch.setattr(dr,"_compose_answer",compose)
    monkeypatch.setattr(dr,"_ensure_research_plan",lambda n,p,*a:p)
    monkeypatch.setattr(dr,"_is_shopping_task",lambda *a:True)
    monkeypatch.setattr(type(home_relay),"online",property(lambda _:True))
    monkeypatch.setattr(home_relay,"fetch",fetch)
    result=asyncio.run(dr._run_director([],"наушники озон",99001,None))
    assert result[0].startswith("Ответ после проверки")
    assert f'[Товар]({CARD})' in result[0]
    assert 'https://www.ozon.ru/product/invented-999/' not in result[0]
    assert any(s.get("reader")=="home" for s in result[3])


def test_keyboard_does_not_consume_headphone_slots(monkeypatch):
    keyboard="https://www.ozon.ru/product/komplekt-klaviatura-i-myshka-ugreen-mk552-123/"
    async def buyer(*a,**k):return {"ranked_ids":[0],"search_queries":[]}
    monkeypatch.setattr(mv,"buyer_json",buyer)
    cards,_,_=asyncio.run(mv.rank_candidates("топ полноразмерных наушников озон",[{"result":keyboard+" "+CARD}]))
    assert cards == [CARD]


def test_semantic_ranking_cannot_invent_urls_and_respects_rejections(monkeypatch):
    expensive="https://www.ozon.ru/product/hyperx-cloud-123/"
    async def buyer(*a,**k):return {"ranked_ids":[1,999,1],"rejected":[{"id":0,"reason":"Выше бюджета"}]}
    monkeypatch.setattr(mv,"buyer_json",buyer)
    cards,_,_=asyncio.run(mv.rank_candidates("наушники озон до 5000",[{"result":expensive+" "+CARD}]))
    assert cards == [CARD]


def test_candidates_from_both_requested_stores_get_read_slots(monkeypatch):
    wb="https://www.wildberries.ru/catalog/777/detail.aspx"
    other="https://www.ozon.ru/product/second-345/"
    async def buyer(*a,**k):return {"ranked_ids":[0,1,2]}
    monkeypatch.setattr(mv,"buyer_json",buyer)
    cards,_,_=asyncio.run(mv.rank_candidates("озон вб",[{"result":CARD+" "+other+" "+wb}]))
    assert cards[:2]==[CARD,wb]


def test_suitable_label_without_literal_price_and_seller_is_downgraded(monkeypatch):
    async def buyer(*a,**k):return {"offers":[{"id":0,"fit":"suitable","evidence":{"type":"Наушники","price":"1500 ₽","seller":"Хороший магазин"}}]}
    monkeypatch.setattr(mv,"buyer_json",buyer)
    results=[{"status":"ok","result":"Наушники. Цена не загрузилась.","search":[{"query":CARD}]}]
    assert asyncio.run(mv.assess_offers("топ наушников",results))==0
    assert results[0]["offer_fit"]=="unknown"
    assert "price" not in results[0]["offer_evidence"]


def test_quality_top_requires_rating_and_review_count(monkeypatch):
    async def buyer(*a,**k):return {"offers":[{"id":0,"fit":"suitable","evidence":{"type":"Наушники","price":"Цена 1500 ₽","seller":"Продавец Магазин"}}]}
    monkeypatch.setattr(mv,"buyer_json",buyer)
    results=[{"status":"ok","result":"Наушники. Цена 1500 ₽. Продавец Магазин.","search":[{"query":CARD}]}]
    assert asyncio.run(mv.assess_offers("топ наушников",results))==0
    assert results[0]["offer_fit"]=="unknown"


def test_bad_offer_is_replaced_by_new_search_and_real_read(monkeypatch):
    replacement="https://www.ozon.ru/product/good-headphones-456/"
    monkeypatch.setattr(type(home_relay),"online",property(lambda _:True))
    calls=[]
    async def fetch(url):
        calls.append(url)
        return {"status":"ok","url":url,"text":"Наушники. Цена 4500 ₽. Продавец Магазин. Рейтинг 4.8. 1273 отзыва. Комплект USB-приёмник."}
    async def buyer(prompt,*a,**k):
        if "ranked_ids" in prompt:return {"ranked_ids":[0],"search_queries":["наушники до 5000 озон рейтинг отзывы"]}
        return {"offers":[{"id":i,"fit":"reject" if i==0 else "suitable","reason":"Первый кандидат не подходит" if i==0 else "Подходит запросу","evidence":{"type":"Наушники","price":"Цена 4500 ₽","seller":"Продавец Магазин","rating":"Рейтинг 4.8","review_count":"1273 отзыва"}} for i in range(2)]}
    async def search(*a,**k):return [{"search":[{"query":"Хорошие наушники","summary":replacement}]}]
    monkeypatch.setattr(home_relay,"fetch",fetch)
    monkeypatch.setattr(mv,"buyer_json",buyer)
    monkeypatch.setattr(mv,"replacement_search",search)
    results=asyncio.run(mv.verify_marketplace_cards("топ наушников озон до 5000",[{"result":CARD}]))
    assert calls == [CARD,replacement]
    assert results[0]["offer_fit"]=="reject"
    assert results[1]["offer_fit"]=="suitable"


def test_failed_buyer_cannot_qualify_an_offer():
    results=[{"status":"ok","result":"Цена и отзывы неизвестны","search":[{"query":CARD}]}]
    assert asyncio.run(mv.assess_offers("топ наушников",results))==0
    assert results[0]["offer_fit"]=="unknown"


def test_replacement_search_survives_kimi_outage(monkeypatch):
    import kimi_web_search, search_engine
    calls=[]
    async def failed(*a,**k):return []
    async def fallback(query,limit):
        calls.append(query)
        return [{"title":"Наушники с отзывами","url":CARD,"snippet":"Рейтинг 4.8"},{"title":"Посторонний сайт","url":"https://example.com/product/1","snippet":""}]
    monkeypatch.setattr(kimi_web_search,"kimi_search_pro",failed)
    monkeypatch.setattr(search_engine,"_search_openai_sources",fallback)
    result=asyncio.run(REAL_REPLACEMENT_SEARCH("озон наушники",["наушники до 5000"],[]))
    assert calls==["наушники до 5000 site:ozon.ru"]
    assert len(result[0]["search"])==1
    assert CARD in result[0]["search"][0]["summary"]


def test_comparison_reads_original_short_links_without_replacement_or_guessing(monkeypatch):
    originals=["https://ozon.ru/t/l1zlv1V","https://ozon.ru/t/2zG2KhU","https://ozon.ru/t/tPZtGST"]
    task="\n".join(originals)+"\nСравни все три рации и выбери фаворита"
    monkeypatch.setattr(type(home_relay),"online",property(lambda _:True))
    calls=[]
    async def fetch(url):
        calls.append(url)
        return {"status":"ok","url":"https://www.ozon.ru/product/radio-"+str(originals.index(url))+"/","text":"Название рации, характеристики, продавец, комплект. Цена и отзывы неизвестны."}
    async def forbidden(*args,**kwargs):raise AssertionError("a fixed comparison must not search for replacement")
    monkeypatch.setattr(home_relay,"fetch",fetch)
    monkeypatch.setattr(mv,"replacement_search",forbidden)
    monkeypatch.setattr(mv,"rank_candidates",forbidden)
    result=asyncio.run(mv.verify_marketplace_cards(task,[]))
    assert calls==originals
    assert len(result)==3 and all(r["status"]=="ok" for r in result)
    assert all(originals[i] in r["result"] for i,r in enumerate(result))
    assert all('/product/radio-' in r["search"][0]["query"] for r in result)


def test_comparison_table_in_chat_is_not_a_file_request():
    task="https://ozon.ru/t/l1zlv1V https://ozon.ru/t/2zG2KhU https://ozon.ru/t/tPZtGST Сравни все три рации и сделай сводную таблицу параметров"
    assert not dr._wants_file(task)
    assert dr._wants_file(task+" в Excel")


def test_confirmed_yandex_and_aliexpress_short_formats_and_destination_guards():
    yam='https://market.yandex.ru/cc/9rsgpy'
    ali='https://sl.aliexpress.ru/p?key=2IztsDQ'
    assert mv.public_shop_url(yam)==('short',yam)
    assert mv.public_shop_url(ali)==('short',ali)
    assert mv.candidates('Сравни '+yam+' '+ali,[])[0]==[yam,ali]
    assert mv.short_destination_allowed(yam,'https://market.yandex.ru/card/model/123')
    assert mv.short_destination_allowed(ali,'https://aliexpress.ru/item/100500123.html')
    for bad in ['https://market.yandex.ru/my/cart','https://market.yandex.ru/search?text=a',CARD,'https://market.yandex.ru.evil.test/card/a/123']:
        assert not mv.short_destination_allowed(yam,bad)
    assert not mv.short_destination_allowed(ali,'https://aliexpress.ru/account')
    assert mv.public_shop_url('https://sl.aliexpress.ru/p?key=abc&url=https://evil.test') is None
    assert mv.public_shop_url('https://sl.aliexpress.ru/p?key=a&key=b') is None
    assert mv.public_shop_url('https://market.yandex.ru/cc/a/private') is None
    assert mv.public_shop_url('https://sl.aliexpress.ru.evil.test/p?key=abc') is None


def test_yandex_short_cart_redirect_is_not_verified(monkeypatch):
    monkeypatch.setattr(type(home_relay),'online',property(lambda _:True))
    async def fetch(url):return {'status':'ok','url':'https://market.yandex.ru/my/cart','text':'Чужая корзина с товарами и персональными данными '*5}
    monkeypatch.setattr(home_relay,'fetch',fetch)
    result=asyncio.run(mv.verify_marketplace_cards('Сравни https://market.yandex.ru/cc/abc',[]))
    assert result[0]['status']=='error'
    assert 'персональными' not in result[0]['result']
