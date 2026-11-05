import pytest
from app.security.redact import labeled_secret_spans, redact_text
from app.services.response_policy import compact_answer_kind
from app.services.subject_guidance import subject_for_query, subject_note


@pytest.mark.parametrize('language', ['C++17', 'С++17 Cortex-M0', 'Rust 1.85', 'C# .NET 8', 'Enfusion Enforce Script'])
def test_languages_receive_code_contract(language):
    text = language + ': напиши функцию. Верни только один блок кода. Не создавай вложения.'
    assert subject_for_query(text) == 'code'
    assert compact_answer_kind(text, web_required=True) == 'text'
    assert 'граничные случаи' in subject_note(text)


@pytest.mark.parametrize('suffix', [' Запусти тесты.', ' Сохрани файл.', ' В проекте.',
                                    ' По официальной документации.', ' https://example.com'])
def test_inline_code_never_discards_execution_or_source_requirements(suffix):
    assert compact_answer_kind('Rust: напиши функцию. Только код.' + suffix) != 'text'


def test_code_expressions_are_not_secret_values():
    source = '```csharp\nvar linkedToken = linkedCts.Token;\nvar token = linkedCts.Token;\npassword = get_password();\n```'
    assert labeled_secret_spans(source) == []
    assert redact_text(source, labeled_secret_spans(source)) == source


def test_real_secrets_remain_hidden_even_in_code():
    source = 'var token = "actual-sensitive-value";\nпароль: private-password'
    secrets = labeled_secret_spans(source)
    assert 'actual-sensitive-value' in secrets and 'private-password' in secrets
    cleaned = redact_text(source, secrets)
    assert 'actual-sensitive-value' not in cleaned and 'private-password' not in cleaned
    assert redact_text('var token = connector.Token;', ['connector.Token']) == 'var token = •••;'
    assert 'abc.def.ghi' in labeled_secret_spans('token: abc.def.ghi')


@pytest.mark.parametrize('task', [
    'Коллега сегодня не поздоровался. Я точно его обидел?',
    'Человек не отвечает три часа. Значит, я ему не нужен?',
    'Есть 25 минут, сил мало. Помоги распределить дела.',
    'Предложи ужин из этих продуктов, без покупок.',
    'Сделай сообщение короче — ровно два предложения.',
])
def test_private_everyday_circumstances_do_not_trigger_research(task):
    assert compact_answer_kind(task, web_required=True) == 'text'


@pytest.mark.parametrize('task', [
    'Я устал, болит грудь и трудно дышать. Что делать?',
    'Коллега сегодня не поздоровался. Найди его профиль.',
    'Устал. Открой почту и отправь сообщение.',
    'Предложи ужин по актуальным рекомендациям лечения.',
    'Коллега сегодня не поздоровался. Дай проверенные источники.',
])
def test_everyday_shortcut_keeps_health_sources_and_external_actions(task):
    from app.services.response_policy import everyday_answer
    assert not everyday_answer(task)


def test_missing_torsion_inputs_get_precision_without_fabricated_geometry():
    task = 'Металлический вал длиной метр и момент 50 Н·м. Определи угол закручивания. Других данных нет.'
    assert subject_for_query(task) == 'engineering'
    assert compact_answer_kind(task) == 'text'
    assert 'только для круглого сечения' in subject_note(task)


def test_reforger_reference_is_scoped_to_its_actual_component_class():
    note = subject_note('Enfusion ScriptComponent')
    assert 'protected void OnDelete(IEntity owner)' in note
    assert 'не EOnDelete' in note
    assert 'ScriptComponent.html' in note
    assert 'OnDelete' not in subject_note('Что такое Python?')


def test_cancellation_code_uses_strong_writer_only_within_tier():
    from app.services.response_policy import compact_model
    task='C# .NET 8: напиши async метод с CancellationToken и корректной отменой.'
    assert compact_model(task,['gpt-6-luna','gpt-6.1-terra','gpt-6-sol'])=='gpt-6-sol'
    assert compact_model(task,['gpt-6-luna','gpt-6.1-terra'])=='gpt-6.1-terra'
    assert compact_model(task,['gpt-6-luna'])=='gpt-6-luna'
    assert compact_model('Python: напиши сортировку',['gpt-6-luna','gpt-6.1-terra'])=='gpt-6-luna'


def test_cancellation_sources_are_not_a_request_for_web_sources():
    task='C# .NET 8: напиши async метод с CancellationToken, источники отмены освобождать. Верни только один блок кода.'
    assert compact_answer_kind(task)=='text'
    assert compact_answer_kind(task+' Сверь официальные источники информации.')!='text'


def test_linear_algorithms_with_explicit_memory_bound_get_midrange_model():
    from app.services.response_policy import compact_model
    task='C++17: напиши алгоритм, время O(n), память O(k). Только код.'
    assert compact_model(task,['gpt-6-luna','gpt-6.1-terra'])=='gpt-6.1-terra'
    assert compact_model(task,['gpt-6-luna'])=='gpt-6-luna'
    assert 'до вычисления разности' in subject_note(task)
    assert subject_for_query('C++17: std::size_t')=='code'


def test_explicit_teaching_calculation_uses_only_readonly_math(monkeypatch):
    import asyncio
    import openai_client
    from app.services.answer_tools import computation_query,maybe_tool_answer
    task='Стационарная учебная тепловая модель: мощность 8 Вт, тепловые сопротивления 1.5 и 3 K/Вт, среда 25 °C. Только JSON. Не добавляй оценку безопасности.'
    assert computation_query(task)
    async def response(messages,**kwargs):
        assert kwargs['model']=='gpt-6-sol'
        assert kwargs['allowed_tools']==frozenset({'calculate'})
        assert kwargs['required_first_tool']=='calculate'
        assert not kwargs['use_skills']
        assert any('единиц' in row['content'] for row in messages if row['role']=='system')
        return '{"junction_c":61}',[], '',[]
    monkeypatch.setattr(openai_client,'get_chat_response',response)
    result=asyncio.run(maybe_tool_answer([{'role':'user','content':task}],task,1,{'gpt-6-luna','gpt-6-sol'}))
    assert result[0]=='{"junction_c":61}'


@pytest.mark.parametrize('suffix', [' Сохрани файл.', ' Других данных нет.',
 ' Проверь безопасность реального изделия.', ' По официальной документации.',
 ' Открой проект.', ' Недостаточно данных.', ' Создай DOCX.', ' Собери PDF.'])
def test_teaching_math_does_not_hide_missing_inputs_or_external_work(suffix):
    from app.services.answer_tools import teaching_calculation
    assert not teaching_calculation('Учебный расчёт балки: сила 10 Н, длина 2 м. Только JSON.'+suffix)


@pytest.mark.parametrize('task',[
 'Источник 3.3 В, делитель: резисторы 47 кОм и 10 кОм, вход АЦП 10 кОм. Только JSON с vout_v.',
 'RC ФНЧ: резистор 1000 Ом, конденсатор 1 мкФ. Только JSON с cutoff_hz.',
])
def test_numeric_circuit_answers_also_use_arithmetic_verification(task):
    from app.services.answer_tools import teaching_calculation
    assert teaching_calculation(task)


@pytest.mark.parametrize('bound,resuming', [(False,False),(True,False),(False,True)])
def test_persistent_teaching_task_keeps_workspace_and_resume_guards(monkeypatch,bound,resuming):
    import asyncio
    import director_router as dr
    from app.services import answer_tools,text_document
    from app.services.conversation_context import workspaces
    from app.services.task_checkpoints import resumed_journal
    from app.services.computer_context import computer_task_id
    task='Учебная цепь: резисторы 300 Ом и 600 Ом параллельно, источник 12 В. Только JSON.'
    async def no_doc(*args):return None
    async def calculated(messages,text,uid,available,**kwargs):
        assert not bound and not resuming
        assert computer_task_id.get()=='isolated-cloud-task'
        assert kwargs['pool']=='computer'
        return '{"resistance_ohm":200,"total_current_ma":60}',[],'',[]
    class ExistingPath(Exception):pass
    async def ordinary(*args,**kwargs):raise ExistingPath()
    monkeypatch.setattr(text_document,'respond',no_doc)
    monkeypatch.setattr(answer_tools,'maybe_tool_answer',calculated)
    monkeypatch.setattr(dr,'_route_turn',ordinary)
    monkeypatch.setattr(dr,'_employee_models',lambda uid:['gpt-6-sol','gpt-6-luna'])
    monkeypatch.setattr(dr,'_turn_has_images',lambda uid:False)
    tokens=(workspaces.set([{'product_id':'p'}] if bound else []),
            resumed_journal.set([{'status':'ok'}] if resuming else []),
            computer_task_id.set('isolated-cloud-task'))
    try:
        if bound or resuming:
            with pytest.raises(ExistingPath):asyncio.run(dr._run_director([{'role':'user','content':task}],task,993110,None))
        else:
            assert asyncio.run(dr._run_director([{'role':'user','content':task}],task,993110,None))[0].startswith('{')
    finally:
        workspaces.reset(tokens[0]);resumed_journal.reset(tokens[1]);computer_task_id.reset(tokens[2])
