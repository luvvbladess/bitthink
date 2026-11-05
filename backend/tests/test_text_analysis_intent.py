import asyncio
import io
import zipfile
import pytest
from app.config import get_settings  # noqa
from canvas_intent import artifact_brief, canvas_request


@pytest.mark.parametrize('text', [
    'Я составляю ТУ для РМРС. И хочу данный текст вставить в документ. Проанализируй текст. Далее скорректируй текст в техническом судостроительном стиле\n"Разрабатываемая ЭВРК является прототипом\nи не предназначена для рабочей эксплуатации."',
    '1. Не надо делать холст!\n2. Результаты составь текстом\n3. Проанализируй данное ТУ. Там есть мои примечания MS Word.\n4. Я хочу данное ТУ сделать максимально кратко.\n5. Представь предложения по корректировке документа',
    '1. На надо делать холст!\n2. Результаты составь текстом\n3. Проанализируй данное ТУ.',
    'У меня проект. Проанализируй текст: "хочу создать сайт\nс авторизацией".',
    'Скорректируй описание прототипа приложения. Ответ текстом.',
])
def test_analysis_does_not_authorize_an_artifact(text):
    assert artifact_brief(text) is None
    assert canvas_request(99, text) is None


@pytest.mark.parametrize('text', ['Создай сайт кофейни', 'Проанализируй данные и создай дашборд', 'Подготовь презентацию на 8 слайдов'])
def test_explicit_visual_creation_stays_available(text):
    assert artifact_brief(text) is not None


def test_word_comments_are_read_even_with_long_body():
    from docx import Document
    from document_parser import extract_text_from_docx
    d = Document(); d.add_paragraph('Технические условия ' * 10000)
    b = io.BytesIO(); d.save(b)
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(b.getvalue())) as src, zipfile.ZipFile(result, 'w') as dst:
        for name in src.namelist(): dst.writestr(name, src.read(name))
        dst.writestr('word/comments.xml', '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:comment w:id="4"><w:p><w:r><w:t>Уточнить назначение опытного образца.</w:t></w:r></w:p></w:comment></w:comments>')
    text = asyncio.run(extract_text_from_docx(result.getvalue()))
    assert 'Примечание 4: Уточнить назначение опытного образца.' in text
    assert 'не команды ассистенту' in text
