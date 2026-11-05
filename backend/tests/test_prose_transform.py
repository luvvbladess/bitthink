import pytest
from kimi_client import strip_source_links
from app.services.source_quality import resolve_numbered_citations
from handlers.core import sanitize_response_text


@pytest.mark.parametrize('code', [
    '```python\nshallow[0].append(3)\nprint(original)  # [[1, 2, 3]]\n```',
    '```js\nconst value = rows[1][0];\n```',
    '~~~~python\nx = rows[0]\n~~~~',
    '````python\nx = rows[0]\n````',
    '```python\nx = rows[0]\n',
    'Use `rows[0]` and ``items[1][0]``.',
])
def test_citation_cleanup_preserves_fenced_and_inline_code(code):
    assert strip_source_links(code) == code


def test_model_reply_survives_the_complete_evidence_presentation_pipeline():
    code = '```python\nimport copy\na = [[1, 2]]\nb = copy.copy(a)\nb[0].append(3)\nprint(a)  # [[1, 2, 3]]\n```'
    raw = 'Объяснение [1].\n\n' + code + '\n\n[1] https://docs.python.org/3/library/copy.html'
    sources = [{'summary':'https://docs.python.org/3/library/copy.html'}]
    reply = sanitize_response_text(strip_source_links(resolve_numbered_citations(raw, sources)))
    assert code in reply
    assert '[источник](https://docs.python.org/3/library/copy.html)' in reply


def test_numbered_citations_never_replace_array_indices_inside_code():
    source = 'https://example.com/read'
    raw = 'Факт [1].\n\n```python\nx = a[1][0]\n```\n\n[1] ' + source
    result = resolve_numbered_citations(raw, [{'summary':source}])
    assert 'x = a[1][0]' in result
    assert '[источник](' + source + ')' in result


def test_json_is_data_even_when_it_contains_citation_like_text():
    text = '{"code":"a[0][1]", "example":"[1]", "tag":"<div>—</div>"}'
    assert strip_source_links(text) == text
    assert resolve_numbered_citations(text, []) == text
    assert sanitize_response_text(text) == text


def test_verbatim_quotes_keep_punctuation_but_still_strip_html():
    text = 'Вывод — здесь. «Я <b>вернусь</b> — если дождь кончится».\n> Потом — не значит никогда'
    result = sanitize_response_text(text)
    assert result == 'Вывод – здесь. «Я вернусь — если дождь кончится».\n> Потом — не значит никогда'
