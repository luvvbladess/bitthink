from app.services.answer_format import normalize_answer_format


def test_json_only_sentence_is_a_format_request_without_a_return_verb():
    assert normalize_answer_format('```json\n{"amount":"0.32"}\n```', 'Сложи 0.1 и 0.22. Только JSON с amount — строкой.') == '{"amount":"0.32"}'


def test_quoting_json_instruction_does_not_change_the_requested_prose():
    source='```json\n{"a":1}\n```'
    assert normalize_answer_format(source,'Процитируй «Только JSON»') == source
    assert normalize_answer_format(source,'Переведи: верни только JSON') == source


def test_json_normalization_does_not_guess_or_discard_explanations():
    source='```json\n{"a":1}\n```\nВторой вариант: {"a":2}'
    assert normalize_answer_format(source,'Только JSON') == source
    assert normalize_answer_format('```json\n{"a":NaN}\n```','Только JSON').startswith('```')
