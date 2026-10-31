from types import SimpleNamespace as NS
from app.config import get_settings  # noqa: F401
from app.services.followup_evidence import followup_evidence, previous_source_rows, EVIDENCE_MARKER
from app.services.source_quality import evidence_issues
from app.services.source_quality import resolve_numbered_citations
from model_context import search_hop_messages
from kimi_client import kimi_result_is_grounded
import asyncio
import pytest
from uuid import uuid4


def source(state='read', url='https://example.com/announcement'):
    return dict(query='Official announcement', summary=url+'\nNew Model and New Model Full were released.',
                evidence_state=state, read_at='2026-10-12T12:00:00Z')


def history(*rows):
    return [NS(role='user',content='Что за новая модель?',search=None),
            NS(role='assistant',content='Описание модели',search=list(rows))]


def test_numeric_model_followup_restores_observations_and_requires_web():
    note, fresh = followup_evidence('а скажи именно версии моделей, циферные',history(source()))
    assert fresh and 'New Model Full' in note and '2026-10-12T12:00:00Z' in note
    assert 'Описание модели' not in note
    prior=previous_source_rows(note)
    assert prior[0]['cached'] and prior[0]['origin']=='history'
    assert prior[0]['read_at']=='2026-10-12T12:00:00Z'
    messages=[{'role':'system','content':note},{'role':'user','content':'а версии?'}]
    assert any(EVIDENCE_MARKER in m['content'] for m in search_hop_messages(messages,'а версии?'))


def test_new_topic_greeting_and_formatting_do_not_force_web():
    for query in ['привет','спасибо','Напиши код сортировки на Python','новая тема: а какие у неё версии?']:
        assert followup_evidence(query,history(source()))==('',False)
    note,fresh=followup_evidence('перефразируй это короче',history(source()))
    assert note and not fresh


def test_failed_sources_and_assistant_prose_are_not_evidence():
    assert followup_evidence('а версии моделей?',history(source('failed')))==('',False)
    assert followup_evidence('а версии моделей?',history())==('',False)
    note,_=followup_evidence('а её цена?',history(source('retrieved')))
    assert '"evidence_state": "retrieved"' in note
    assert followup_evidence('а её цена?',history(source(url='https://example.com/?token=secret')))==('',False)


def test_evidence_is_bounded_and_comes_from_immediately_previous_answer():
    rows=[source(url=f'https://example.com/{i}') for i in range(30)]
    for row in rows:row['summary']+='x'*20000
    note,_=followup_evidence('а её точная версия?',history(*rows))
    assert len(note)<8000 and len(previous_source_rows(note))<=4
    turns=history(source())+[NS(role='assistant',content='Другой ответ без источников',search=None)]
    assert followup_evidence('а её версия?',turns)==('',False)
    turns[-1].content='Похоже, предыдущие ответы были выдуманными.'
    note,fresh=followup_evidence('а её версия?',turns)
    assert fresh and 'New Model Full' in note


def test_source_quantity_cannot_replace_citation_provenance():
    rows=[source()]*10
    assert not kimi_result_is_grounded('Уверенное утверждение без ссылок. '*10,rows)
    assert not kimi_result_is_grounded('[Версия](https://invented.example/fake)',rows)
    assert kimi_result_is_grounded('Версия 2. [Источник](https://example.com/announcement)',rows[:1],minimum_sources=4)
    assert not kimi_result_is_grounded('❌ Ошибка API',rows)


def test_version_comparison_requires_coverage_for_each_statement_and_page_read():
    rows=[source()]
    assert 'precise_claim_without_inline_source' in evidence_issues(
        'Model 4.7 is current.\nOther details [source](https://example.com/announcement)',rows)
    assert 'precise_claim_needs_page_read' in evidence_issues(
        'Version 4.7 [source](https://example.com/announcement)',[source('retrieved')])
    assert not evidence_issues('Version 4.7 [source](https://example.com/announcement)',rows)


def test_kimi_passes_domain_filter_and_parallel_reads_keep_result_ids(monkeypatch):
    import kimi_client, kimi_web_search
    captured=[]
    async def search(query,**kwargs):
        captured.append(kwargs)
        return []
    monkeypatch.setattr(kimi_web_search,'kimi_search_pro',search)
    asyncio.run(kimi_client._execute_kimi_tool('web_search',{'query':'current models','sites':['official.example']}))
    assert captured[0]['sites']==['official.example']
    active=peak=0
    async def read(name,args,**kwargs):
        nonlocal active,peak
        active+=1;peak=max(peak,active)
        await asyncio.sleep(.01)
        active-=1
        return args['url'],[]
    monkeypatch.setattr(kimi_client,'_execute_kimi_tool',read)
    calls=[NS(id=f'call{i}',function=NS(name='browse_page',arguments='{"url":"https://example.com/%d"}'%i)) for i in range(4)]
    messages=[]
    asyncio.run(kimi_client._append_tool_results(messages,calls))
    assert peak==3
    assert [m['tool_call_id'] for m in messages]==[f'call{i}' for i in range(4)]
    assert [m['content'] for m in messages]==[f'https://example.com/{i}' for i in range(4)]


def test_false_retraction_is_flagged_without_declaring_semantic_truth():
    issues=evidence_issues('Предыдущие ответы были выдуманными. Модель не существует.',[source()],has_previous_evidence=True)
    assert {'missing_inline_evidence','retraction_needs_source_check'}<=set(issues)
    # A link is structurally valid; this helper does not prove the numeric claim.
    assert not evidence_issues('Число 999. [Источник](https://example.com/announcement)',[source()])


def test_numbered_links_resolve_only_with_explicit_observed_url_mapping():
    text='Модель выпущена [7].\n\n[7] Анонс — https://example.com/announcement'
    assert 'выпущена [источник](https://example.com/announcement)' in resolve_numbered_citations(text,[source()])
    assert resolve_numbered_citations('Модель выпущена [1].',[source()])=='Модель выпущена [1].'
    fake='Утверждение [1].\n[1] https://invented.example/fake'
    assert resolve_numbered_citations(fake,[source()])==fake


def _mock_auto_turn(monkeypatch):
    import handlers.core as core
    import kimi_client, studio_router, model_context
    user=820_000_000+uuid4().int%10_000_000
    core.conversation_manager.set_subscription_tier(user,'creator',30,from_today=True)
    monkeypatch.setattr(core.conversation_manager,'get_user_model',lambda uid:'auto')
    monkeypatch.setattr(core.conversation_manager,'conversation_for_turn',lambda uid:NS(messages=history(source())))
    async def passthrough(messages,*args,**kwargs):return messages
    async def no_image(*args,**kwargs):return None
    monkeypatch.setattr(core,'reduce_heavy_context',passthrough)
    monkeypatch.setattr(model_context,'fit_for_mode',passthrough)
    monkeypatch.setattr(studio_router,'get_image_response',no_image)
    return core,kimi_client,user


def test_auto_followup_searches_with_prior_page_not_offline_memory(monkeypatch):
    core,kimi,user=_mock_auto_turn(monkeypatch)
    seen=[]
    async def search(messages,**kwargs):
        seen.extend(messages)
        return 'Версии конкурентов проверены. [Источник](https://example.com/announcement)',[],'',[source()]
    async def forbidden(*args,**kwargs):raise AssertionError('No offline or recovery call expected')
    monkeypatch.setattr(kimi,'get_kimi_chat_response',forbidden)
    monkeypatch.setattr(core,'get_chat_response',search)
    query='а скажи именно версии моделей, циферные'
    result=asyncio.run(core.get_smart_response(user,query,[{'role':'user','content':query}],None))
    assert 'Версии конкурентов' in result[0]
    assert any(EVIDENCE_MARKER in m['content'] for m in seen)
    assert any('New Model Full' in m['content'] for m in seen)


def test_followup_response_does_not_trigger_a_source_verification_round(monkeypatch):
    core,kimi,user=_mock_auto_turn(monkeypatch)
    requests=[]
    async def empty(*args,**kwargs):return '',[],'',[]
    answer_text='Предыдущие сведения требуют уточнения. Вот доступные варианты.'
    async def answer(messages,**kwargs):
        requests.append(kwargs)
        return answer_text,[],'',[]
    monkeypatch.setattr(kimi,'get_kimi_chat_response',empty)
    monkeypatch.setattr(core,'get_chat_response',answer)
    query='а скажи именно версии моделей, циферные'
    result=asyncio.run(core.get_smart_response(user,query,[{'role':'user','content':query}],None))
    assert result[0]==answer_text
    assert len(requests)==1


def test_kimi_keeps_verified_numbered_links_before_cleanup(monkeypatch):
    import kimi_client
    calls=[]
    async def model(client,request,**kwargs):
        calls.append(request)
        if len(calls)==1:
            message=NS(content='',tool_calls=[NS(id='s1',type='function',function=NS(name='web_search',arguments='{"query":"model"}'))])
        else:
            message=NS(content='Version 4.7 is listed [7].\n\n[7] Official — https://example.com/announcement',tool_calls=[])
        return NS(usage=None,choices=[NS(message=message)])
    async def append(messages,tool_calls,**kwargs):
        messages.append(dict(role='tool',tool_call_id='s1',content='Version 4.7'))
        return [source()]
    monkeypatch.setattr(kimi_client,'client',NS())
    monkeypatch.setattr(kimi_client,'model_call',model)
    monkeypatch.setattr(kimi_client,'_append_tool_results',append)
    result=asyncio.run(kimi_client.get_kimi_chat_response([dict(role='user',content='model versions')]))
    assert '[источник](https://example.com/announcement)' in result[0]
    assert '\n[7]' not in result[0]


def test_failed_recovery_cannot_keep_an_unobserved_link_or_unread_number():
    from app.services.source_quality import supported_partial
    answer=('Valid [source](https://example.com/announcement).\n\n'
            'Model 9.9 [invented](https://invented.example/no).')
    partial=supported_partial(answer,[source()])
    assert 'Valid' in partial and 'invented.example' not in partial and '9.9' not in partial
    assert 'выдуман' not in supported_partial('Предыдущие ответы выдуманы.',[source()])


def test_read_page_does_not_require_another_check_for_link_placement():
    from app.services.source_quality import answer_recovery_issues
    answer = ('Бюджет — до 40 000 ₽.\n\n'
              'Рассмотрите Phone A: удобная камера. Сравните состояние б/у экземпляра.')
    assert 'missing_inline_evidence' in evidence_issues(answer, [source()])
    assert not answer_recovery_issues(answer, [source()])
    assert 'missing_inline_evidence' in answer_recovery_issues(answer, [source('retrieved')])


def test_formatting_warning_cannot_hide_a_later_unread_price():
    from app.services.source_quality import answer_recovery_issues
    rows = [source(), source('retrieved', 'https://shop.example/phone')]
    text = 'Бюджет 40 000 ₽.\n\nТелефон стоит 35 000 ₽. [Магазин](https://shop.example/phone)'
    assert 'precise_claim_needs_page_read' in answer_recovery_issues(text, rows)
    assert 'unobserved_citation_url' in answer_recovery_issues(
        'Модель [здесь](https://invented.example/no)', rows)


def test_phone_recommendation_with_read_pages_survives_without_inline_links(monkeypatch):
    core, kimi, user = _mock_auto_turn(monkeypatch)
    monkeypatch.setattr(core.conversation_manager, 'conversation_for_turn', lambda uid: NS(messages=[]))
    answer = ('До 40 000 ₽ я бы сравнил Phone A и Phone B.\n\n'
              'Phone A — мой выбор ради камеры; Phone B — если важнее новый аппарат. '
              'Текущие цены конкретных объявлений не подтверждены.')
    async def search(*args, **kwargs): return answer, [], '', [source()]
    async def forbidden(*args, **kwargs): raise AssertionError('Do not repeat search/model calls for link formatting')
    monkeypatch.setattr(kimi, 'get_kimi_chat_response', forbidden)
    monkeypatch.setattr(core, 'get_chat_response', search)
    query = 'Какой телефон выбрать к покупке с камерой до 40 тысяч рублей?'
    result = asyncio.run(core.get_smart_response(user, query, [{'role': 'user', 'content': query}], None))
    assert result[0] == answer and result[3]


def test_search_answer_is_not_rewritten_by_source_contract(monkeypatch):
    core, kimi, user = _mock_auto_turn(monkeypatch)
    monkeypatch.setattr(core.conversation_manager, 'conversation_for_turn', lambda uid: NS(messages=[]))
    answer = 'Phone A — кандидат по камере. [Подробнее](https://shop.example/phone)'
    async def search(*args, **kwargs): return answer, [], '', [source('retrieved')]
    async def forbidden(*args, **kwargs): raise AssertionError('No source verification model call')
    monkeypatch.setattr(kimi, 'get_kimi_chat_response', forbidden)
    monkeypatch.setattr(core, 'get_chat_response', search)
    query = 'Какой телефон выбрать к покупке с камерой до 40 тысяч рублей?'
    result = asyncio.run(core.get_smart_response(user, query, [{'role': 'user', 'content': query}], None))
    assert 'Phone A' in result[0] and 'Подробнее' in result[0]
    assert result[3][0]['evidence_state']=='retrieved'


def test_usable_search_answer_does_not_depend_on_sources():
    from kimi_client import kimi_result_is_usable
    for text in ['Совет без ссылок.', 'Version 4.7 [страница](https://example.com)', 'Цены уточняются.']:
        assert kimi_result_is_usable(text)
    for text in ['', '  ', '❌ Ошибка API', '<tool>web_search</tool>']:
        assert not kimi_result_is_usable(text)


def test_search_answer_without_sources_is_delivered_once(monkeypatch):
    core, kimi, user = _mock_auto_turn(monkeypatch)
    monkeypatch.setattr(core.conversation_manager, 'conversation_for_turn', lambda uid: NS(messages=[]))
    answer = 'Рассмотрите Phone A для камеры и Phone B для автономности. Цена зависит от продавца.'
    async def search(*args, **kwargs): return answer, [], '', []
    async def forbidden(*args, **kwargs): raise AssertionError('No duplicate search or source recovery')
    monkeypatch.setattr(kimi, 'get_kimi_chat_response', forbidden)
    monkeypatch.setattr(core, 'get_chat_response', search)
    query = 'Какой телефон выбрать к покупке с камерой до 40 тысяч рублей?'
    result = asyncio.run(core.get_smart_response(user, query, [{'role':'user','content':query}], None))
    assert result[0] == answer and result[3] == []


def test_search_tool_markup_is_not_treated_as_a_finished_recommendation(monkeypatch):
    core, kimi, user = _mock_auto_turn(monkeypatch)
    monkeypatch.setattr(core.conversation_manager, 'conversation_for_turn', lambda uid: NS(messages=[]))
    async def search(*args, **kwargs):
        return '<tool>web_search</tool><query>phone</query>', [], '', [source()]
    async def fallback(*args, **kwargs):
        return 'Phone A — кандидат по камере. Цены объявлений не проверены.', [], '', [source()]
    monkeypatch.setattr(kimi, 'get_kimi_chat_response', search)
    monkeypatch.setattr(core, 'get_chat_response', fallback)
    query = 'Какой телефон выбрать к покупке с камерой до 40 тысяч рублей?'
    result = asyncio.run(core.get_smart_response(user, query, [{'role': 'user', 'content': query}], None))
    assert 'Phone A' in result[0] and '<tool>' not in result[0]


def test_verified_catalog_entrypoints_are_selective_and_do_not_embed_versions(monkeypatch):
    from app.services.authoritative_catalogs import catalog_urls,read_catalogs,CATALOG_MARKER
    assert len(catalog_urls('а версии моделей?','Claude, GPT и Gemini'))==3
    assert catalog_urls('как работает список Python','Claude GPT Gemini')==[]
    assert len(catalog_urls('актуальные модели GPT',''))==1
    import computer_tools
    seen=[]
    async def read(name,args,user_id):
        seen.append((name,args['url']))
        return 'URL: '+args['url']+'\n\nCurrent release from the actual page'
    monkeypatch.setattr(computer_tools,'run_computer_tool',read)
    note,rows=asyncio.run(read_catalogs('версии моделей','Claude GPT Gemini',1))
    assert note.startswith(CATALOG_MARKER) and len(rows)==3
    assert all(name=='browse_page' for name,url in seen)
    assert all('evidence_state' not in row for row in rows) # ledger supplies real status


def test_general_ai_ranking_gets_benchmarks_without_needing_vendor_names():
    from app.services.authoritative_catalogs import catalog_urls,is_ai_overview,MODEL_BENCHMARK
    from search_engine import query_requires_web
    for query in ['какие щас лучшие модели нейронок в мире?', 'топ нейросетей',
                  'Какая сейчас самая сильная языковая модель?', 'best AI models']:
        assert is_ai_overview(query) and query_requires_web(query)
        urls=catalog_urls(query,'')
        assert len(urls)==4 and urls[0]==MODEL_BENCHMARK
    for query in ['как устроена нейросеть','лучшая модель линейной регрессии','лучшие автомобили','лучшая модель нейронов мозга']:
        assert not is_ai_overview(query)
    assert not query_requires_web('без поиска какие лучшие нейросети?')
    assert catalog_urls('без поиска какие лучшие нейросети?','')==[]


def test_empty_search_refusal_is_a_failure_even_with_no_sources():
    assert 'incomplete_answer_needs_recovery' in evidence_issues(
        'Я не могу надёжно назвать мировой топ: поиск не вернул свежих рейтингов.',[])
    assert not evidence_issues('Общий принцип работы нейросетей — обучение на примерах.',[])


def test_cited_table_caption_covers_table_and_survives_partial_filter():
    from app.services.source_quality import supported_partial
    table='| Модель | Балл |\n|---|---|\n| Model 5.5 | 58 |\n| Model 4.1 | 56 |'
    answer=table+'\n\n[Таблица рейтинга](https://example.com/announcement) — источник баллов.'
    assert not evidence_issues(answer,[source()])
    assert '| Model 5.5 |' in supported_partial(answer,[source()])
    assert 'precise_claim_without_inline_source' in evidence_issues(table+'\n\nПосторонний текст.',[source()])
    assert 'precise_claim_without_inline_source' in evidence_issues(answer,[source('retrieved')])


def test_one_list_item_citation_does_not_cover_other_items():
    text='- Model 4.7 [source](https://example.com/announcement)\n\n- Model 9.9'
    assert 'precise_claim_without_inline_source' in evidence_issues(text,[source()])


@pytest.mark.parametrize('mode', ['auto', 'kimi-k2.6', 'gpt-6-sol', 'gpt-6-luna', 'gpt-6-astra', 'director', 'studio'])
@pytest.mark.parametrize('state', ['read', 'retrieved', 'failed', None])
def test_all_modes_preserve_answer_without_source_validation(monkeypatch, mode, state):
    core, kimi, user = _mock_auto_turn(monkeypatch)
    monkeypatch.setattr(core.conversation_manager, 'get_user_model', lambda uid: mode)
    monkeypatch.setattr(core.conversation_manager, 'conversation_for_turn', lambda uid: NS(messages=[]))
    answer = 'Phone A: камера 50 МП, ориентир 35 000 ₽. Условия зависят от продавца.'
    rows = [source(state)] if state else []
    calls = []
    async def generate(*args, **kwargs):
        assert 'allowed_tools' not in kwargs, 'A source recovery pass must not run'
        calls.append(kwargs)
        return answer, [], '', rows
    def forbidden(*args, **kwargs):
        raise AssertionError('Source checks must not gate any mode')
    import app.services.source_quality as quality
    monkeypatch.setattr(quality, 'answer_recovery_issues', forbidden)
    monkeypatch.setattr(quality, 'supported_partial', forbidden)
    monkeypatch.setattr(kimi, 'get_kimi_chat_response', generate)
    monkeypatch.setattr(core, 'get_chat_response', generate)
    import director_router, studio_router
    monkeypatch.setattr(director_router, 'get_director_response', generate)
    monkeypatch.setattr(studio_router, 'get_studio_response', generate)
    query = 'Какой телефон выбрать к покупке с камерой до 40 тысяч рублей?'
    result = asyncio.run(core.get_smart_response(user, query, [{'role': 'user', 'content': query}], None))
    assert result[0] == answer
    assert len(calls) == 1
