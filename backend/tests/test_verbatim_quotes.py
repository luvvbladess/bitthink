from app.services.verbatim_quotes import restore_verbatim_quote
from handlers.core import sanitize_response_text


def test_known_literal_survives_unquoted_model_output_and_delivery_cleanup():
    history=[{'role':'user','content':'Запомни реплику «Точно — не значит навсегда».'},
             {'role':'assistant','content':'Хорошо: «Точно – не значит навсегда».'}]
    fixed=restore_verbatim_quote('Точно – не значит навсегда','Повтори дословно эту реплику и ничего не добавляй.',history)
    assert sanitize_response_text(fixed) == '«Точно — не значит навсегда»'


def test_matching_selects_the_literal_without_guessing_its_meaning():
    task='Выпиши дословно только вторую реплику: «Не сейчас». «Потом — не значит никогда».'
    assert restore_verbatim_quote('«Потом – не значит никогда»',task) == '«Потом — не значит никогда»'
    assert restore_verbatim_quote('«Не сейчас»',task) == '«Не сейчас»'  # No pretending to solve selection.


def test_repair_does_not_invent_words_or_discard_explanation():
    task='Повтори дословно: «Я — здесь»'
    for answer in ['Я — там','Я — здесь. Это метафора.','«Я — здесь». Объяснение.']:
        assert restore_verbatim_quote(answer,task) == answer
    assert restore_verbatim_quote('Я – здесь','Объясни слова «Я — здесь»') == 'Я – здесь'
    assert restore_verbatim_quote('Я – здесь','Не повторяй дословно: «Я — здесь»') == 'Я – здесь'


def test_ambiguous_original_typography_is_not_guessed():
    task='Повтори дословно: «Я — здесь» или «Я – здесь»'
    assert restore_verbatim_quote('Я – здесь',task) == 'Я – здесь'


def test_unquoted_delivery_with_terminal_period_is_restored_without_touching_words():
    task='Повтори дословно эту реплику и ничего не добавляй.'
    history=[{'role':'user','content':'Реплика: «Точно — не значит навсегда».'}]
    assert sanitize_response_text(restore_verbatim_quote('Точно – не значит навсегда.',task,history)) == '«Точно — не значит навсегда».'
    assert restore_verbatim_quote('Точно – не значит навсегда.','Повтори дословно без точки.',history) == '«Точно — не значит навсегда»'
    assert restore_verbatim_quote('Точно – не значит навсегда. Другие слова.',task,history) == 'Точно – не значит навсегда. Другие слова.'


def test_only_literal_request_removes_a_label_but_never_trailing_analysis():
    task='Выпиши дословно только вторую реплику: «Не сейчас». «Потом — не значит никогда».'
    assert restore_verbatim_quote('Вторая реплика: «Потом – не значит никогда».',task) == '«Потом — не значит никогда».'
    answer='Вторая реплика: «Потом – не значит никогда». Далее объясню.'
    assert restore_verbatim_quote(answer,task) == answer
    assert restore_verbatim_quote('Реплика: «Я – здесь»','Прокомментируй дословную цитату «Я — здесь»') == 'Реплика: «Я – здесь»'
