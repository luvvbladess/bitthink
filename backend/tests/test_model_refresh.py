"""Provider compatibility and unchanged accounting for the current Flash API."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
import deepseek_client
import computer_tools
import runtime_context
import status_feed
from app.billing import call_budget


class Stream:
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def chunk(content=None, reasoning=None, tool_calls=None):
    return NS(choices=[NS(delta=NS(content=content, reasoning_content=reasoning, tool_calls=tool_calls))], usage=None)


def fake_provider(monkeypatch, *, tool_reasoning=None):
    calls = []
    monkeypatch.setattr(deepseek_client, 'DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr(deepseek_client, 'client', object())
    monkeypatch.setattr(runtime_context, 'with_runtime_context', lambda messages, **kwargs: messages)
    monkeypatch.setattr(computer_tools, 'response_tool_names', lambda **kwargs: {'workspace_read'})

    async def tool(*args, **kwargs):
        return '138'

    monkeypatch.setattr(computer_tools, 'run_computer_tool', tool)
    monkeypatch.setattr(status_feed, 'announce_tool', tool)

    async def model_call(client, request, **kwargs):
        calls.append({'request': deepcopy(request), 'billing_model': kwargs['model']})
        if tool_reasoning is not None and len(calls) == 1:
            chunks = [chunk(reasoning=tool_reasoning), chunk(tool_calls=[NS(index=0, id='lookup-1', function=NS(name='workspace_read', arguments='{"path":"sample.txt"}'))])]
        else:
            chunks = [chunk(content='138')]
        usage = NS(prompt_tokens=100, completion_tokens=20, prompt_cache_hit_tokens=30)
        chunks.append(NS(choices=[], usage=usage))
        return await kwargs['consume'](Stream(chunks))

    monkeypatch.setattr(call_budget, 'model_call', model_call)
    return calls


@pytest.mark.parametrize('requested', ['deepseek-v4-flash', 'deepseek-flash'])
def test_flash_uses_current_api_id_with_existing_budget_and_output_cap(monkeypatch, requested):
    calls = fake_provider(monkeypatch)
    result = asyncio.run(deepseek_client.get_deepseek_response(
        [{'role': 'user', 'content': 'Return 138'}], model=requested, use_tools=False, use_skills=False, reasoning_enabled=False,
    ))
    assert result[0] == '138'
    assert calls[0]['request']['model'] == 'deepseek-flash'
    assert calls[0]['billing_model'] == 'deepseek-v4-flash'
    assert calls[0]['request']['max_tokens'] == 64_000
    assert calls[0]['request']['extra_body']['thinking']['type'] == 'disabled'


@pytest.mark.parametrize('reasoning', ['', 'intermediate provider tokens'])
def test_thinking_tool_round_trip_retains_required_reasoning(monkeypatch, reasoning):
    calls = fake_provider(monkeypatch, tool_reasoning=reasoning)
    result = asyncio.run(deepseek_client.get_deepseek_response(
        [{'role': 'user', 'content': 'Read sample.txt and return its amount.'}], model='deepseek-v4-flash', use_tools=True, use_skills=False,
    ))
    assert result[0] == '138'
    assert len(calls) == 2
    assistant = next(message for message in calls[1]['request']['messages'] if message['role'] == 'assistant')
    assert assistant['reasoning_content'] == reasoning
    assert assistant['tool_calls'][0]['id'] == 'lookup-1'
    assert calls[1]['request']['messages'][-1] == {'role': 'tool', 'tool_call_id': 'lookup-1', 'content': '138'}
    assert all(call['billing_model'] == 'deepseek-v4-flash' for call in calls)


def test_pro_stays_on_its_existing_quality_route(monkeypatch):
    calls = fake_provider(monkeypatch)
    result = asyncio.run(deepseek_client.get_deepseek_response(
        [{'role': 'user', 'content': 'Return 138'}], model='deepseek-v4-pro', use_tools=False, use_skills=False,
    ))
    assert result[0] == '138'
    assert calls[0]['request']['model'] == calls[0]['billing_model'] == 'deepseek-v4-pro'
