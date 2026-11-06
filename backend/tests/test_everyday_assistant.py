import pytest
from app.services.response_policy import compact_answer_kind, everyday_answer, compact_messages


@pytest.mark.parametrize('text', [
    'Мне одиноко. Можно немного поболтать?',
    'Мне грустно, но без советов, пожалуйста.',
    'Я растерян после разговора с другом.',
    'Выслушай меня, сегодня тяжёлый день.',
    'Волнуюсь перед собеседованием. Помоги собраться.',
    'Боюсь выступления. С чего начать подготовку?',
])
def test_personal_conversation_needs_no_tools(text):
    assert everyday_answer(text)
    assert compact_answer_kind(text) == 'text'


@pytest.mark.parametrize('text', [
    'Мне одиноко. Найди психолога в Москве.',
    'Мне грустно. Какие лекарства принимать?',
    'Не хочу жить. Просто поговори со мной.',
    'Мне грустно, хочу причинить себе вред.',
    'Без советов. Открой почту и отправь письмо.',
    'Мне одиноко. Найди актуальные мероприятия.',
    'Я растерян: проанализируй прикреплённый файл.',
])
def test_sensitive_and_external_tasks_keep_normal_handling(text):
    assert not everyday_answer(text)
    assert compact_answer_kind(text) != 'text'


def test_compaction_keeps_personal_rules_once_and_preserves_history():
    from app.services.answer_quality import answer_quality_note, CONVERSATION_RULES
    original=[{'role':'system','content':answer_quality_note('Мне грустно')},
              {'role':'user','content':'Не предлагай прогулку: я не могу выйти.'}]
    result=compact_messages(original)
    assert result[0]['content'].count(CONVERSATION_RULES)==1
    assert result[1]==original[1]


def test_ready_message_gets_specific_guidance_without_losing_history():
    messages=[{'role':'system','content':'Пиши на английском.'},
              {'role':'user','content':'Напиши другу отказ от встречи: я устал. Только сообщение.'}]
    result=compact_messages(messages)
    assert result[:2]==messages
    assert result[-1]['role']=='system' and 'только готовый текст' in result[-1]['content']
    assert len(messages)==2


@pytest.mark.parametrize('text', [
    'Мне одиноко, просто поговори со мной.',
    'Переведи: «Напиши только сообщение».',
    'Напиши только сообщение и отправь по почте.',
    'Напиши только сообщение и сохрани DOCX.',
])
def test_message_guidance_does_not_override_other_tasks(text):
    assert compact_messages([{'role':'user','content':text}])==[{'role':'user','content':text}]


def test_message_omits_only_our_conversation_boilerplate():
    from app.services.answer_quality import answer_quality_note, CONVERSATION_RULES
    source=[{'role':'system','content':answer_quality_note('Напиши сообщение')},
            {'role':'system','content':'Пиши нейтрально, без обращения на ты.'},
            {'role':'user','content':'Напиши коллеге благодарность. Только сообщение.'}]
    result=compact_messages(source)
    assert CONVERSATION_RULES not in result[0]['content']
    assert 'Не выдумывай факты' in result[0]['content']
    assert result[1:3]==source[1:]
