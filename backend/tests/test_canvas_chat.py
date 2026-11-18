import asyncio
from types import SimpleNamespace

import pytest
from app.config import get_settings  # noqa: F401
from app.core.request_context import generation_preferences
from canvas_intent import canvas_request, canvas_creation
from studio.html_canvas import load_previous_html


@pytest.fixture
def canvases(monkeypatch, tmp_path):
    import conversations
    messages=[]
    paths={}
    def add(name='site.html',role='assistant',url=None):
        url=url or '/uploads/'+str(len(paths))+'.html'
        path=tmp_path/(str(len(paths))+'.html')
        path.write_text('<!doctype html><html><body><h1>'+name+'</h1></body></html>')
        paths[url]=path
        messages.append(SimpleNamespace(role=role,attachment={'name':name,'url':url,'canvas':True}))
        return url
    monkeypatch.setattr(conversations.conversation_manager,'conversation_for_turn',lambda uid:SimpleNamespace(messages=messages))
    monkeypatch.setattr(conversations.conversation_manager,'_attachment_disk_path',lambda item:paths.get(item.get('url')))
    return add,messages


@pytest.mark.parametrize('text',[
    'Создай сайт кофейни с меню и контактами',
    'Собери инфографику по прикреплённым данным',
    'Подготовь презентацию для инвесторов на 8 слайдов',
    'Нужен лендинг для мастерской',
    'Создай картинку на холсте с подписью',
])
def test_creating_visual_artifacts_is_a_chat_action(canvases,text):
    assert canvas_request(7,text)=='create'


@pytest.mark.parametrize('text',[
    'Создай сайт с авторизацией и базой данных PostgreSQL',
    'Создай приложение на React и FastAPI с исходным кодом',
])
def test_full_app_request_keeps_real_project_builder(canvases,text):
    assert canvas_request(7,text)=='project'


@pytest.mark.parametrize('text',[
    'Как создать сайт кофейни?',
    'Напиши текст для лендинга',
    'Создай план презентации',
    'Проанализируй презентацию и скажи, что поправить',
    'Нарисуй кота',
    'Что сегодня происходит в мире?',
    'Сравни два сайта',
    'Добавь логирование на сервере',
])
def test_ordinary_chat_analysis_and_plain_images_do_not_enter_canvas(canvases,text):
    add,_=canvases
    add()
    assert canvas_request(7,text) is None


@pytest.mark.parametrize('text',[
    'Сделай заголовок крупнее',
    'В текущем макете измени элемент «Кнопка»: сделай текст короче',
    'Проверь читаемость текущего макета и исправь найденные проблемы',
    'Измени визуальный стиль текущего макета. Сохрани содержание.',
    'Измени текущий макет: Тёмный фон. Сохрани остальные элементы и содержание.',
])
def test_visual_edits_use_existing_result(canvases,text):
    add,_=canvases;add()
    assert canvas_request(7,text)=='edit'


@pytest.mark.parametrize('with_canvases', [False, True], ids=['only-images', 'older-canvases'])
@pytest.mark.parametrize('text', [
    'Данный вариант глушителя 3.1 оказался очень неплохим: снижение шума 48–115 дБ. '
    'Давай сделаем обновленную конструкцию, исходя из расчетов нам хватает абсорбционной секции, '
    'а две реактивные секции выглядят избыточными. Лучше сделать одну? И как ее тогда лучше сделать?',
    'Обнови конструкцию глушителя по расчётам: убери одну реактивную секцию. Как изменится шум?',
    'Уменьши ширину реактивной секции. Как проверить результат?',
    'Сделай короче',
])
def test_engineering_followup_stays_in_chat(canvases, with_canvases, text):
    add, messages = canvases
    if with_canvases:
        add('first.html')
        add('second.html')
    messages.extend([
        SimpleNamespace(role='user', attachment={'type': 'image', 'name': 'section.png',
                                                  'url': '/uploads/section.png'}),
        SimpleNamespace(role='user', attachment={'type': 'image', 'name': 'loss.png',
                                                  'url': '/uploads/loss.png'}),
        SimpleNamespace(role='assistant', content='Вариант 3.1 стоит принять за основу.'),
    ])
    assert canvas_request(7, text) is None


def test_generated_image_card_is_not_an_editable_html_canvas(canvases):
    add, messages = canvases
    add()
    messages[-1].attachment.update(type='image', name='diagram.png')
    assert canvas_request(7, 'Сделай заголовок крупнее') is None


def test_versions_require_exact_selection_and_cannot_open_foreign_url(canvases):
    add,_=canvases
    first=add('first.html');add('second.html')
    assert canvas_request(7,'Сделай заголовок крупнее')=='edit'
    assert canvas_request(7,'Сделай заголовок крупнее в текущем макете')=='ambiguous'
    token=generation_preferences.set({'user_id':7,'canvas_target':first})
    try:
        assert canvas_request(7,'Сделай заголовок крупнее')=='edit'
        assert 'first.html' in load_previous_html(7)
        assert 'second.html' in load_previous_html(8)
    finally:generation_preferences.reset(token)
    token=generation_preferences.set({'user_id':7,'canvas_target':'https://foreign.example/private.html'})
    try:
        assert canvas_request(7,'Сделай заголовок крупнее')=='missing'
        assert load_previous_html(7) is None
    finally:generation_preferences.reset(token)


@pytest.mark.parametrize('text', [
    'Мне нужно понять, как сделать сайт для музея.',
    'Стоит ли сделать сайт для записи на консультацию?',
    'Хочу обновить отчёт: добавь туда график ключевых метрик.',
    'Сделай таблицу с результатами презентации.',
    'Предложи три варианта и скажи, как сделать сайт лучше.',
    'Можно убрать кнопку с главной без потери заявок?',
    'Напиши, что произойдёт, если удалить слайд.',
    'Уменьши высоту камеры. В презентации мы указали другое значение.',
    'Не меняй цвет кнопки.',
])
def test_mentions_and_advice_do_not_dispatch_to_canvas(canvases, text):
    add, _ = canvases
    target = add()
    token = generation_preferences.set({'user_id': 7, 'canvas_target': target})
    try:
        assert canvas_request(7, text) is None
    finally:
        generation_preferences.reset(token)


def test_implicit_edit_uses_recent_result_instead_of_all_historical_canvases(canvases):
    add, messages = canvases
    add('old.html')
    add('latest.html')
    assert canvas_request(7, 'Убери кнопку') == 'edit'
    messages.append(SimpleNamespace(role='assistant', content='Текст отчёта.', attachment=None))
    assert canvas_request(7, 'Убери кнопку') is None
    assert canvas_request(7, 'Убери кнопку в текущем макете') == 'ambiguous'


@pytest.mark.parametrize('text', [
    'Подготовьте презентацию, а ниже добавьте комментарии.',
    'Хочу собрать адаптивный сайт для мастерской.',
    'Сделай понятную инфографику по бухгалтерскому отчёту.',
    'Собери страницу товара из этого описания.',
])
def test_requested_artifact_is_identified_at_the_action(canvases, text):
    assert canvas_request(7, text) == 'create'


@pytest.mark.parametrize('text, expected', [
    ('Можно ли уместить контакты на одном экране? Затем собери лендинг для мастерской.', 'create'),
    ('Объясни, что такое инфографика. Затем создай инфографику по этим цифрам.', 'create'),
    ('На сайте можно поменять цвет кнопки? И как убрать меню?', None),
    ('Посоветуй, как убрать кнопку, чтобы сохранить заявки.', None),
    ('Сделай картинку для презентации, а не презентацию.', None),
    ('Обнови давление до 5 кПа. Холст оставь для следующего шага.', None),
    ('Нужен сайт, который показывает результаты измерений.', 'create'),
])
def test_dispatch_uses_the_independent_action_and_its_target(canvases, text, expected):
    add, _ = canvases
    add()
    assert canvas_request(7, text) == expected


def test_uploaded_html_is_not_a_generated_canvas(canvases):
    add,_=canvases;add(role='user')
    assert load_previous_html(7) is None
    assert canvas_request(7,'Сделай заголовок крупнее') is None


@pytest.mark.parametrize('model',['auto','gpt-6-luna','gpt-6-sol','gpt-6.1-terra','studio'])
@pytest.mark.parametrize('surface',['web','desktop'])
def test_chat_dispatches_artifact_without_persisting_mode(monkeypatch,canvases,model,surface):
    from handlers import core
    import model_context,studio_router
    from app.billing import quota
    from app.services import authoritative_catalogs
    calls=[]
    monkeypatch.setattr(core.conversation_manager,'get_user_model',lambda uid:model)
    monkeypatch.setattr(core.conversation_manager,'get_user_reasoning_effort',lambda uid:'none')
    monkeypatch.setattr(core.conversation_manager,'get_subscription',lambda uid:{'tier':'creator'})
    monkeypatch.setattr(core.conversation_manager,'set_user_model',lambda *a:pytest.fail('Must not persist a mode switch'))
    monkeypatch.setattr(quota,'assert_can_use',lambda uid,pool,model:calls.append((pool,model)))
    async def context(messages,*args,**kwargs):return messages
    async def catalogs(*args,**kwargs):return '',[]
    async def generated(*args,**kwargs):
        assert canvas_creation.get()
        return 'Макет готов',[{'filename':'site.html','bytes':b'<html>ok</html>','canvas':True}],'',[]
    monkeypatch.setattr(core,'reduce_heavy_context',context)
    monkeypatch.setattr(model_context,'fit_for_mode',context)
    monkeypatch.setattr(authoritative_catalogs,'read_catalogs',catalogs)
    monkeypatch.setattr(studio_router,'get_studio_response',generated)
    from app.services.desktop_context import desktop_mode, desktop_chat_model
    mode_token=desktop_mode.set('chat' if surface=='desktop' else None)
    model_token=desktop_chat_model.set(model)
    try: result=asyncio.run(core.get_smart_response(7,'Создай сайт кофейни',[],None))
    finally:
        desktop_mode.reset(mode_token);desktop_chat_model.reset(model_token)
    assert result[1][0]['canvas']
    assert calls==[('computer','studio')]
    assert not canvas_creation.get()


def test_canvas_plan_gate_runs_before_model_call(monkeypatch,canvases):
    from handlers import core
    from app.billing.quota import QuotaError
    monkeypatch.setattr(core.conversation_manager,'get_user_model',lambda uid:'auto')
    monkeypatch.setattr(core.conversation_manager,'get_user_reasoning_effort',lambda uid:'none')
    monkeypatch.setattr(core.conversation_manager,'get_subscription',lambda uid:{'tier':'free'})
    with pytest.raises(QuotaError,match='Pro'):
        asyncio.run(core.get_smart_response(7,'Создай сайт кофейни',[],None))


def test_legacy_model_selection_is_migrated_without_exposing_studio(monkeypatch):
    from app.api import models_router as models
    from app.models.schemas import ModelSelect
    saved=[]
    async def selected(user):return 'studio'
    async def subscription(user):return {'tier':'pro'}
    async def effort(user):return 'none'
    async def quality(user):return 'high'
    async def save(user,value):saved.append(value)
    monkeypatch.setattr(models.repo,'get_user_model',selected)
    monkeypatch.setattr(models.repo,'get_subscription',subscription)
    monkeypatch.setattr(models.repo,'get_user_reasoning_effort',effort)
    monkeypatch.setattr(models.repo,'get_user_image_quality',quality)
    monkeypatch.setattr(models.repo,'set_user_model',save)
    result=asyncio.run(models.list_models('canvas@example.com'))
    assert result['selected']=='auto' and result['canvasAvailable']
    assert 'studio' not in {row['id'] for row in result['models']}
    assert saved==['auto']
    assert asyncio.run(models.select_model(ModelSelect(model='studio'),'canvas@example.com'))['model']=='auto'


def test_new_work_does_not_reuse_previous_canvas(monkeypatch):
    import studio_router
    from studio import html_canvas
    monkeypatch.setattr(html_canvas,'load_previous_html',lambda uid:pytest.fail('New work must not open a previous artifact'))
    async def build(messages,text,uid,status,*,previous_html=''):
        assert not previous_html
        return 'Новая работа',[],'',[]
    monkeypatch.setattr(studio_router,'_run_html_studio',build)
    token=canvas_creation.set(True)
    try:assert asyncio.run(studio_router._run_studio([], 'Создай сайт кофейни',7,None))[0]=='Новая работа'
    finally:canvas_creation.reset(token)
