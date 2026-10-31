"""Bounded, opt-in live contract check. Only synthetic data and a pure sum tool.

python -m scripts.selfcheck_openrouter --execute --budget-usd .30 --output /tmp/router-check.json
This checks integration, not general model quality. Never enables a model.
"""
import argparse
import asyncio
import io
import json
import time
from pathlib import Path
from unittest.mock import patch
import base64

from app.config import get_settings  # noqa: F401
from app.services.orchestrator_budget import RunBudget, current_budget
from app.services.orchestrator_metrics import model_trace
from app.services.model_registry import openrouter_models


def image_fixture():
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (320, 160), 'blue')
    ImageDraw.Draw(image).rectangle((160, 0, 320, 160), fill='red')
    data = io.BytesIO()
    image.save(data, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(data.getvalue()).decode()


async def check_model(model, budget):
    import openrouter_client
    import runtime_context
    import computer_tools
    import app.services.autonomy as autonomy
    import status_feed

    calls = []
    tool = {'type': 'function', 'function': {'name': 'workspace_read',
        'description': 'Read the synthetic fixture. No real files are accessible.',
        'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}},
                       'required': ['path'], 'additionalProperties': False}}}
    async def execute(name, args, uid):
        calls.append(name)
        if name != 'workspace_read' or args.get('path') != 'fixture.txt':
            raise ValueError('Only the synthetic fixture tool is permitted')
        return json.dumps({'total': 138, 'verified': True})
    async def announce(*args):
        pass
    cases = [
        ('tool', [{'role': 'user', 'content': 'Read fixture.txt using workspace_read. Then return only JSON {"total": number, "verified": boolean} from the tool result.'}]),
        ('image', [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'Look at the attached image. Return only JSON {"left":"color","right":"color"} using English color names.'},
            {'type': 'image_url', 'image_url': {'url': image_fixture()}}]}]),
    ]
    output = []
    with patch.object(runtime_context, 'with_runtime_context', lambda messages, **kw: messages), \
         patch.object(autonomy, 'attach_company', lambda messages: messages), \
         patch.object(computer_tools, 'response_tool_names', lambda **kw: {'workspace_read'} if kw['skill_tools'] else set()), \
         patch.object(computer_tools, 'COMPUTER_TOOLS_CHAT', [tool]), \
         patch.object(computer_tools, 'SKILL_TOOL_NAMES', {'workspace_read'}), \
         patch.object(computer_tools, 'run_computer_tool', execute), \
         patch.object(status_feed, 'announce_tool', announce):
        for kind, messages in cases:
            if kind == 'image' and model == 'glm-5.3-flash':
                output.append({'case': kind, 'ok': True, 'skipped': True, 'reason': 'text_only_worker'})
                continue
            calls.clear()
            started = time.monotonic()
            with model_trace('evaluation') as metrics:
                token = current_budget.set(budget)
                try:
                    result = await openrouter_client.get_openrouter_response(messages, model=model,
                        use_tools=False, use_skills=kind == 'tool', max_tool_loops=4,
                        output_token_limit=2048, reasoning_effort='low')
                except Exception as exc:
                    output.append({'case': kind, 'ok': False, 'error_kind': type(exc).__name__})
                    continue
                finally:
                    current_budget.reset(token)
            try:
                text = result[0].strip()
                if text.startswith('```'):
                    text = text.split('\n', 1)[1].rsplit('```', 1)[0]
                value = json.loads(text)
                ok = value == {'total': 138, 'verified': True} and calls == ['workspace_read'] if kind == 'tool' else value == {'left': 'blue', 'right': 'red'}
            except (ValueError, TypeError):
                ok = False
            output.append({'case': kind, 'ok': bool(ok) and not result.error_kind,
                'error_kind': result.error_kind, 'calls': metrics['calls'],
                'usd': round(metrics['estimated_text_usd'], 8), 'ms': round((time.monotonic()-started)*1000)})
    return {'model': model, 'cases': output}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', default='claude-haiku-5.5,claude-sonnet-5.5,glm-5.3-flash,minimax-m3.1-flash')
    parser.add_argument('--budget-usd', type=float, default=.30)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output')
    args = parser.parse_args()
    models = args.models.split(',')
    if any(name not in openrouter_models(include_experimental=True) for name in models):
        parser.error('Unknown model')
    if not 0 < args.budget_usd <= 2:
        parser.error('Live self-check budget must be between 0 and 2 USD')
    if not args.execute:
        print(json.dumps({'dry_run': True, 'models': models, 'cases_per_model': 2, 'budget_usd': args.budget_usd}))
        return
    async def execute():
        budget = RunBudget(args.budget_usd)
        results = []
        for model in models:
            results.append(await check_model(model, budget))
        return {'integration_only': True, 'budget': budget.summary(), 'results': results}
    result = asyncio.run(execute())
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered, encoding='utf-8')
    print(rendered)
    raise SystemExit(0 if all(case['ok'] for row in result['results'] for case in row['cases']) else 1)


if __name__ == '__main__':
    main()
