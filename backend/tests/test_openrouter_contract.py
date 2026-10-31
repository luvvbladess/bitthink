import asyncio
import copy
import json
from types import SimpleNamespace as NS

import pytest
from app.config import get_settings  # noqa: F401
from app.services.engineering_io import EngineeringResult
import openrouter_client as oc


def chunk(*, content=None, details=None, calls=None, finish=None, usage=None):
    return NS(usage=usage, choices=[NS(finish_reason=finish, delta=NS(
        content=content, tool_calls=calls, model_extra={'reasoning_details': details} if details else {}))])


def tool_call(arguments='{}'):
    return NS(index=0, id='read-1', function=NS(name='workspace_read', arguments=arguments))


@pytest.fixture
def provider(monkeypatch):
    import runtime_context
    import computer_tools
    import app.services.autonomy as autonomy
    import app.billing.call_budget as cb
    monkeypatch.setattr(oc, 'OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setattr(oc, '_client', object())
    monkeypatch.setattr(runtime_context, 'with_runtime_context', lambda m, **kw: m)
    monkeypatch.setattr(autonomy, 'attach_company', lambda m: m)
    monkeypatch.setattr(computer_tools, 'response_tool_names', lambda **kw: {'workspace_read'})
    monkeypatch.setattr(computer_tools, 'COMPUTER_TOOLS_CHAT', [
        {'type': 'function', 'function': {'name': 'workspace_read', 'parameters': {'type': 'object'}}}])
    requests, actions = [], []
    turns = []
    tool_results = ['data']

    async def run_tool(name, args, uid):
        actions.append((name, args))
        value = tool_results[min(len(actions)-1, len(tool_results)-1)]
        if isinstance(value, Exception):
            raise value
        return value

    async def model_call(client, request, **kwargs):
        requests.append(copy.deepcopy(request))
        output = turns[len(requests)-1]
        if isinstance(output, Exception):
            raise output
        async def stream():
            for item in output:
                yield item
        return await kwargs['consume'](stream())

    monkeypatch.setattr(computer_tools, 'run_computer_tool', run_tool)
    monkeypatch.setattr(cb, 'model_call', model_call)
    return NS(requests=requests, actions=actions, turns=turns, results=tool_results)


def run(messages=None, **kwargs):
    return asyncio.run(oc.get_openrouter_response(messages or [{'role': 'user', 'content': 'Read sample'}],
        use_skills=False, max_tool_loops=3, **kwargs))


def test_images_and_history_survive_without_mutating_caller(provider):
    provider.turns.append([chunk(content='done')])
    messages = [
        {'role': 'user', 'content': [{'type': 'input_text', 'text': 'Look\x00'},
            {'type': 'input_image', 'image_url': 'data:image/png;base64,IMAGE', 'detail': 'high'}]},
        {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'old', 'type': 'function',
            'function': {'name': 'workspace_read', 'arguments': '{}'}}],
         'reasoning_details': [{'type': 'reasoning.encrypted', 'data': 'OPAQUE', 'index': 0}]},
        {'role': 'tool', 'tool_call_id': 'old', 'content': 'old result'},
    ]
    original = copy.deepcopy(messages)
    assert run(messages)[0] == 'done'
    sent = provider.requests[0]['messages']
    assert sent[0]['content'][1]['image_url']['url'].endswith('IMAGE')
    assert sent[1] == messages[1]
    assert sent[2]['tool_call_id'] == 'old'
    assert messages == original


def test_reasoning_fragments_tool_images_files_and_cache(provider):
    provider.turns.extend([
        [chunk(details=[{'type': 'reasoning.text', 'index': 0, 'id': 'r', 'text': 'first ', 'signature': None}]),
         chunk(details=[{'index': 0, 'text': 'second', 'signature': 'sig-'}]),
         chunk(details=[{'index': 0, 'signature': 'end'}, {'type': 'reasoning.encrypted', 'index': 1, 'data': 'abc'}]),
         chunk(details=[{'index': 1, 'data': 'def'}], calls=[tool_call()])],
        [chunk(content='done')],
    ])
    provider.results[:] = [EngineeringResult('page', image_data_url='data:image/png;base64,SCREEN',
        files=[{'filename': 'preview.png'}])]
    response = run(reasoning_effort='high')
    assert response[1] == [{'filename': 'preview.png'}]
    second = provider.requests[1]['messages']
    assistant = next(m for m in second if m['role'] == 'assistant')
    assert assistant['reasoning_details'] == [
        {'type': 'reasoning.text', 'index': 0, 'id': 'r', 'text': 'first second', 'signature': 'sig-end'},
        {'type': 'reasoning.encrypted', 'index': 1, 'data': 'abcdef'}]
    assert second[-1]['content'][1]['image_url']['url'].endswith('SCREEN')
    extra = provider.requests[0]['extra_body']
    assert extra['reasoning']['effort'] == 'high'
    assert extra['cache_control'] == {'type': 'ephemeral'}
    assert extra['provider']['require_parameters'] is True
    assert extra['provider']['data_collection'] == 'deny'
    assert extra['session_id'] == provider.requests[1]['extra_body']['session_id']


@pytest.mark.parametrize('arguments', ['{bad', '[]', 'null'])
def test_invalid_arguments_never_execute_an_empty_action(provider, arguments):
    provider.turns.extend([[chunk(calls=[tool_call(arguments)])], [chunk(content='fixed')]])
    assert run()[0] == 'fixed'
    assert provider.actions == []
    tool = provider.requests[1]['messages'][-1]
    assert json.loads(tool['content'])['error'] == 'invalid_arguments'


def test_stop_after_acceptance_does_not_spend_another_model_call(provider):
    provider.turns.append([chunk(calls=[tool_call()])])
    response = run(stop_after_tool=lambda name, value: value == 'data')
    assert not response.error_kind
    assert response.actions_executed == 1
    assert len(provider.requests) == 1


def test_truncated_tool_arguments_are_not_executed(provider):
    provider.turns.append([chunk(calls=[tool_call('{')], finish='length')])
    response = run()
    assert response.error_kind == 'output_limit'
    assert provider.actions == []


def test_provider_failure_after_action_preserves_files_and_replay_guard(provider):
    provider.turns.extend([[chunk(calls=[tool_call()])], TimeoutError('not public')])
    provider.results[:] = [EngineeringResult('saved', files=[{'filename': 'saved.txt'}])]
    response = run()
    assert response.error_kind
    assert response.retryable
    assert response.actions_executed == 1
    assert response[1] == [{'filename': 'saved.txt'}]
    assert 'not public' not in response[0]


def test_tool_exception_is_returned_as_diagnostic_not_replayed(provider):
    provider.turns.extend([[chunk(calls=[tool_call()])], [chunk(content='Need to inspect the saved state')]])
    provider.results[:] = [RuntimeError('private diagnostic')]
    run()
    assert len(provider.actions) == 1
    assert json.loads(provider.requests[1]['messages'][-1]['content'])['error'] == 'tool_failed'


def test_empty_response_is_an_error(provider):
    provider.turns.append([chunk()])
    assert run().error_kind == 'empty_response'


def test_unindexed_text_and_signature_deltas_are_preserved(provider):
    provider.turns.extend([[chunk(details=[{'type': 'reasoning.text', 'text': 'first '}]),
        chunk(details=[{'type': 'reasoning.text', 'text': 'second'}]),
        chunk(details=[{'type': 'reasoning.text', 'signature': 'sig'}], calls=[tool_call()])],
        [chunk(content='done')]])
    run()
    assistant = next(m for m in provider.requests[1]['messages'] if m['role'] == 'assistant')
    assert assistant['reasoning_details'] == [{'type': 'reasoning.text', 'text': 'first second', 'signature': 'sig'}]


def test_unknown_model_is_not_silently_changed(provider):
    assert run(model='unknown').error_kind == 'unsupported_model'
    assert provider.requests == []


def test_invalid_context_is_not_silently_dropped(provider):
    response = run([{'role': 'user', 'content': [{'type': 'unsupported', 'text': 'important'}]}])
    assert response.error_kind == 'invalid_context'
    assert provider.requests == []

