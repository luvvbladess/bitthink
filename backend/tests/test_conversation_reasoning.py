import pytest
from app.services.response_policy import compact_answer_kind


@pytest.mark.parametrize('task', [
    'Все механики умеют читать чертежи. Некоторые читатели чертежей художники. Следует ли вывод о механиках?',
    'Равносильны ли эти два утверждения? Приведи контрпример.',
    'Разбери аргумент: все участники зарегистрированы, этот человек не зарегистрирован.',
    'Какое минимальное общее время работ, если две ветки можно выполнять параллельно?',
    'В корзине два цвета. Как меняется вероятность при выборе без возвращения?',
    'Докажи, что любая антиутопия отвергает прогресс, или объясни ошибку предпосылки.',
    'Сегодня всё раздражает, просто поговори со мной.',
    'Нет, ходить по лестнице я не могу. Предложи другой вариант.',
    'Напиши брату: за обедом не будем обсуждать оценки. Только сообщение.',
    'Предложи один способ высушить одежду из доступного дома.',
    'После извлечения без возвращения доля оставшихся белых стала больше или меньше?',
    'Проверь аргумент: все квадраты не круги, некоторые красные — квадраты.',
    'После удаления зелёной фишки без возвращения доля жёлтых увеличилась или уменьшилась?',
    'Разбери вымышленную строку: «Окно молчало».',
    'В вымышленном рассказе письмо осталось закрытым. Дай две трактовки.',
])
def test_supplied_analysis_and_conversation_need_no_planner(task):
    assert compact_answer_kind(task) == 'text'


@pytest.mark.parametrize('task', [
    'Разбери аргумент из прикреплённого PDF',
    'Следует ли обновить закон? Найди действующую редакцию.',
    'Равносильны ли эти условия договора? Проверь по источникам.',
    'Разбери аргумент и отправь ответ по почте',
    'Просто поговори со мной и удали файл на сервере',
    'Вычисли вероятность и запусти мой скрипт',
    'Разбери аргумент по лечению и дозам лекарства',
    'Напиши брату: готово. Только сообщение. Отправь его по почте.',
    'Напиши только сообщение и сохрани DOCX.',
    'Проверь аргумент из прикреплённого документа',
    'После удаления фишки без возвращения удали файл на сервере',
])
def test_new_answer_routes_keep_research_and_execution(task):
    assert compact_answer_kind(task) == ''


def test_required_web_is_not_disabled_by_inference_vocabulary():
    assert compact_answer_kind('Разбери аргумент о текущей политике', web_required=True) != 'text'


def test_symbolic_probability_comparison_uses_reasoning_within_tier():
    from app.services.response_policy import compact_model
    task = 'Вероятность при выборе без возвращения стала больше или меньше?'
    assert compact_model(task, ['gpt-6-sol', 'gpt-6-luna']) == 'gpt-6-sol'
    assert compact_model(task, ['gpt-6-luna']) == 'gpt-6-luna'
    assert compact_model('Что такое вероятность?', ['gpt-6-sol', 'gpt-6-luna']) == 'gpt-6-luna'


def test_inference_validity_keeps_strong_model_but_simple_definition_does_not():
    from app.services.response_policy import compact_model
    assert compact_model('Разбери аргумент и проверь посылки.', ['gpt-6-sol', 'gpt-6-luna']) == 'gpt-6-sol'
    assert compact_model('Что такое аргумент?', ['gpt-6-sol', 'gpt-6-luna']) == 'gpt-6-luna'


@pytest.mark.parametrize('task', [
    'Подруга не поставила реакцию на моё фото. Как понять, обиделась ли она?',
    'Коллега изменил фотографию. Почему это меня раздражает?',
    'Что означает молчание в ответ на картинку?',
])
def test_picture_mentions_in_conversation_do_not_authorize_generation(task):
    from canvas_intent import artifact_brief
    assert artifact_brief(task) is None


def test_conversational_picture_question_never_calls_image_provider(monkeypatch):
    import asyncio
    import studio_router
    async def unexpected(*a, **kw):
        pytest.fail('A conversation must not invoke image generation')
    monkeypatch.setattr(studio_router, '_run_image_studio', unexpected)
    assert asyncio.run(studio_router.get_image_response([], 'Друг молчит после моего фото. Почему?', 1, None)) is None
