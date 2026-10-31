import asyncio

import pytest
from app.config import get_settings  # noqa: F401
from studio.html_canvas import detect_kind_explicit, resolve_studio_job, image_canvas_html, requested_image_size


KANEKI_POSTER = '''Стильный современный аниме-постер с Канеки Кеном из «Токийского гуля». Канеки в центре, портрет по пояс, слегка повёрнут к зрителю. Белые растрёпанные волосы, спокойное, но напряжённое выражение лица, чёрная одежда. Одна сторона лица освещена холодным светом, другая скрыта в глубокой тени. За спиной изгибаются алые щупальца-кагуне, добавляя композиции движения, но не закрывая лицо. Глубокий чёрный фон с лёгкой дымкой и редкими красными частицами. Контрастные чёрные, белые и кроваво-красные тона, драматичный боковой свет, выразительные тени, тонкий красный контровой свет, лёгкое плёночное зерно. Асимметричная композиция, чёткий силуэт, высокая детализация, кинематографичная атмосфера, вертикальный формат 2:3. Без текста и логотипов.
Негативный промпт:
Текст, буквы, цифры, подписи, логотипы, водяные знаки, рамка, лишние персонажи, лишние конечности или пальцы, деформированные кисти, неправильная анатомия, размытое лицо, низкая детализация, плоское освещение, блеклые цвета, перегруженный фон, обрезанная голова, лицо закрыто щупальцами, комичная улыбка, детский стиль, фотореализм.'''


@pytest.mark.parametrize('previous', ['', '<html><body>Старый сайт</body></html>', image_canvas_html('data:image/png;base64,QQ==', 'Старое фото')])
def test_pasted_descriptive_poster_starts_a_new_image_even_after_a_site_or_image(previous):
    assert detect_kind_explicit(KANEKI_POSTER) == 'image'
    assert resolve_studio_job(KANEKI_POSTER, previous) == ('image', '', False)
    assert requested_image_size(KANEKI_POSTER) == '1024x1536'


@pytest.mark.parametrize('prompt,kind', [
    ('Стильный минималистичный логотип кофейни', 'image'),
    ('Современный постер для сайта и презентации. Без текста.', 'image'),
    ('Создай сайт с аниме-постером на главной', 'landing'),
    ('Презентация с иллюстрацией аниме', 'slides'),
    ('Расскажи про современные аниме-постеры', None),
    ('Опиши картинку и её композицию', None),
    ('Стильный постер с героем.\nNegative prompt: сайт, приложение, PowerPoint', 'image'),
])
def test_output_kind_follows_the_requested_artifact_not_incidental_or_negative_words(prompt, kind):
    assert detect_kind_explicit(prompt) == kind


@pytest.mark.parametrize('prompt,size', [('Постер, 2:3', '1024x1536'), ('Картинка 3:2', '1536x1024'),
    ('Вертикальный постер', '1024x1536'), ('Квадратный портрет', '1024x1024'),
    ('Постер\nНегативный промпт: горизонтальный формат 16:9', '1024x1024')])
def test_image_dimensions_follow_positive_brief(prompt, size):
    assert requested_image_size(prompt) == size


@pytest.mark.parametrize('prompt', [KANEKI_POSTER, 'Современный постер для PowerPoint. Вертикальный формат 2:3.'])
def test_actual_studio_dispatch_uses_image_provider_preserves_negative_prompt_and_portrait_size(monkeypatch, prompt):
    import studio_router as sr
    import studio.html_canvas as hc
    import openai_client as oc
    from app.billing import quota
    calls = []
    monkeypatch.setattr(hc, 'load_previous_html', lambda uid: '<html><body>Старый сайт</body></html>')
    monkeypatch.setattr(sr, '_chat_image_bytes', lambda *args, **kwargs: [])
    monkeypatch.setattr(sr, '_image_quality', lambda uid: 'low')
    monkeypatch.setattr(quota, 'assert_can_generate_image', lambda uid: None)
    monkeypatch.setattr(quota, 'debit_images', lambda uid, count: None)
    async def forbidden(*args, **kwargs):
        raise AssertionError('A descriptive image prompt must never generate a website or run text composition')
    async def image(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return 'data:image/png;base64,QQ==', None
    monkeypatch.setattr(oc, 'generate_image', image)
    monkeypatch.setattr(sr, '_run_html_studio', forbidden)
    monkeypatch.setattr(sr, '_run_pptx_studio', forbidden)
    monkeypatch.setattr(oc, 'get_chat_response', forbidden)
    result = asyncio.run(sr.get_studio_response([{'role': 'user', 'content': prompt}], prompt, 1, None))
    assert calls[0][0] == prompt and calls[0][1]['size'] == '1024x1536'
    assert len(calls) == 1
    picture = next(item for item in result[1] if str(item.get('mime_type', '')).startswith('image/'))
    page = next(item for item in result[1] if item.get('canvas'))
    assert picture['bytes'] == b'A' and picture['filename'].endswith('.png')
    assert 'data-studio-image' in page['bytes'].decode() and 'createObjectURL' in page['bytes'].decode()
    assert 'подтвердить не удалось' not in result[0]


def test_short_image_and_site_edits_keep_the_existing_artifact():
    site = '<html><body>Сайт</body></html>'
    picture = image_canvas_html('data:image/png;base64,QQ==', 'Фото')
    assert resolve_studio_job('Сделай шапку темнее', site) == ('landing', site, True)
    assert resolve_studio_job('Сделай картинку темнее', picture) == ('image', picture, True)
