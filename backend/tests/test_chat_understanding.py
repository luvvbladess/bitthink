"""Intent pairs exercise dispatch, including nested instructions and existing artifacts."""
import asyncio
from types import SimpleNamespace

import pytest
from app.config import get_settings  # noqa: F401
from app.core.request_context import generation_preferences
from canvas_intent import canvas_request

REPLIES = [
    'Объясни, как создать сайт музея',
    'Как сделать инфографику понятной?',
    'Почему в презентации нельзя смешивать пять шрифтов?',
    'Что такое сайт с авторизацией?',
    'Расскажи, как нарисовать портрет карандашом',
    'Не создавай сайт, просто объясни подход',
    'Не рисуй картинку. Дай описание словами',
    'Не создавай картинку кота',
    'Не нужно рисовать портрет',
    'Не создавай картинку, нужен только короткий текстовый промпт: нарисуй современный город у реки. Не вызывай генерацию.',
    'Не рисуй постер. Нужен лишь краткий промпт: Нарисуй постер города.',
    'Ответь текстом, как нарисовать картинку',
    'Дай разбор картины эпохи Возрождения',
    'Найди картинку замка в интернете',
    'Нужна помощь с созданием сайта',
    'Не нужно собирать презентацию, только предложи структуру',
    'Нужен текст для лендинга мастерской',
    'Хочу понять, как сделать сайт с базой данных',
    'Хочу узнать, как создать инфографику',
    'Создай краткий конспект презентации',
    'Сделай анализ сайта и перечисли недостатки',
    'Напиши промпт: «Нарисуй кота на Марсе»',
    'Составь ТЗ на сайт с авторизацией и базой данных',
    'Придумай пять идей для сайта школы',
    'Напиши описание картинки для незрячего читателя',
    'Переведи на английский: «Создай сайт музея»',
    'Перефразируй: «Нарисуй кота»',
    'Кратко перескажи инструкцию: создай сайт и добавь форму',
    'Создай план презентации по истории России',
    'Напиши подробный промпт для картинки. Нарисуй в нём современный город',
    'Ни сайт, ни картинку создавать не надо. Объясни термин',
    'Я не прошу создавать сайт. Нужна консультация',
    'Сайт делать не нужно, только текст',
    'Объясни, почему надо исправить цвет кнопки',
    'Расскажи, как изменить заголовок, сам ничего не меняй',
    'Что такое картина мира в философии?',
    'Напиши эссе про картину мира эпохи Возрождения',
    'Сделай текст короче и добавь заголовок',
    'Сравни два подхода к созданию сайта',
    'Можно ли создать сайт без сервера? Ответь словами',
    'Write a prompt: "Create a website for a museum"',
    'Do not create an infographic; explain the idea in words',
    'Translate: "Draw a cat"',
    'How can I build a website?',
    'Историки создают картину прошлого. Объясни эту фразу',
    'Почему Наполеон проиграл при Ватерлоо?',
    'Рассчитай напряжение в балке, ответ текстом',
    'Нужна консультация по интерфейсу приложения, без генерации',
]

CREATIONS = [
    'Создай сайт музея с расписанием и контактами',
    'Не рисуй картинку, а создай сайт музея',
    'Собери инфографику по этим трём числам: 1, 2, 3',
    'Подготовь презентацию на 6 слайдов',
    'Составь презентацию по истории Древнего Рима',
    'Разработай лендинг для мастерской',
    'Построй дашборд с демонстрационными данными',
    'Нужен готовый сайт-портфолио на холсте',
    'Можешь собрать сайт по этому брифу?',
    'Сделай сайт по этому промпту: тёмная тема, контакты',
    'Напиши промпт и собери по нему лендинг',
    'Создай инфографику, не описание и не план',
    'Build a website for a museum',
    'Create an infographic about recycling',
    'Создай сайт без авторизации и базы данных, без backend, один HTML',
]

PICTURES = [
    'Нарисуй кота на Марсе',
    'Создай картинку с лесом',
    'Пожалуйста, нарисуй портрет вымышленного героя',
    'Draw a cat on Mars',
    'Стильный минималистичный логотип кофейни',
    'Современный постер для сайта и презентации. Без текста.',
]


@pytest.fixture
def turn(monkeypatch, tmp_path):
    import conversations
    path = tmp_path/'site.html'
    path.write_text('<!doctype html><html><body><h1>Existing</h1></body></html>')
    messages = []
    monkeypatch.setattr(conversations.conversation_manager, 'conversation_for_turn',
                        lambda uid: SimpleNamespace(messages=messages))
    monkeypatch.setattr(conversations.conversation_manager, '_attachment_disk_path', lambda item: path)
    return messages


@pytest.mark.parametrize('existing', [False, True], ids=['fresh', 'after_canvas'])
@pytest.mark.parametrize('text', REPLIES)
def test_text_requests_do_not_generate_or_modify_artifacts(monkeypatch, turn, text, existing):
    import studio_router as sr
    import openai_client as oc
    if existing:
        turn.append({'role': 'assistant', 'attachment': {'name': 'site.html', 'url': '/uploads/site.html', 'canvas': True}})
    assert canvas_request(7, text) is None
    monkeypatch.setattr(sr, '_chat_image_bytes', lambda *a, **k: [])
    monkeypatch.setattr(sr, '_last_reply_image', lambda *a: b'old-photo' if existing else None)
    async def forbidden(*a, **k):
        pytest.fail('A text request reached an image provider')
    monkeypatch.setattr(oc, 'generate_image', forbidden)
    monkeypatch.setattr(oc, 'edit_image', forbidden)
    assert asyncio.run(sr.get_image_response([], text, 7, None)) is None


@pytest.mark.parametrize('text', CREATIONS)
def test_requested_visual_output_enters_canvas(turn, text):
    assert canvas_request(7, text) == 'create'


@pytest.mark.parametrize('text', PICTURES)
def test_requested_picture_uses_image_adapter_without_canvas(monkeypatch, turn, text):
    import studio_router as sr
    import openai_client as oc
    from app.billing import quota
    assert canvas_request(7, text) is None
    monkeypatch.setattr(sr, '_chat_image_bytes', lambda *a, **k: [])
    monkeypatch.setattr(sr, '_last_reply_image', lambda *a: None)
    monkeypatch.setattr(quota, 'assert_can_generate_image', lambda *a: None)
    monkeypatch.setattr(quota, 'debit_images', lambda *a: None)
    monkeypatch.setattr(quota, 'refund_images', lambda *a: None)
    async def picture(*a, **k): return 'data:image/png;base64,QQ==', None
    monkeypatch.setattr(oc, 'generate_image', picture)
    result = asyncio.run(sr.get_image_response([], text, 7, None))
    assert result is not None and result[1] and result[1][0]['mime_type'] == 'image/png'


@pytest.mark.parametrize('text', [
    'Измени текущий макет: Тёмный фон. Сохрани остальные элементы.',
    'Сделай заголовок крупнее',
    'Увеличь ширину кнопки',
    'Добавь в текущий макет секцию контактов',
    'Проверь читаемость текущего макета и исправь проблемы',
])
def test_edit_requires_bound_existing_result(turn, text):
    assert canvas_request(7, text) is None
    turn.append({'role': 'assistant', 'attachment': {'name': 'site.html', 'url': '/uploads/site.html', 'canvas': True}})
    token = generation_preferences.set({'user_id': 7, 'canvas_target': '/uploads/site.html'})
    try: assert canvas_request(7, text) == 'edit'
    finally: generation_preferences.reset(token)


@pytest.mark.parametrize('text', [
    'Создай сайт с авторизацией и базой данных PostgreSQL',
    'Создай приложение на React и FastAPI с исходным кодом',
])
def test_real_application_uses_project_builder(turn, text):
    assert canvas_request(7, text) == 'project'
