"""Real normal-chat acceptance in isolated storage; facts and rubrics are external to answers.

Deterministic checks are screening, not an independent quality verdict. Save every
answer for human review. No production accounts, conversations or user data.
"""
import argparse
from contextvars import ContextVar
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import time


def screen(case, answer):
    text = answer.casefold()
    errors = []
    for word in case.get('all', []):
        if word.casefold() not in text:
            errors.append('missing:' + word)
    for group in case.get('any', []):
        if not any(word.casefold() in text for word in group):
            errors.append('missing_any:' + '|'.join(group))
    # Accept decimal commas, grouping spaces and values embedded in explanations.
    raw = re.findall(r'(?<![\w])[-−]?\d+(?:[.,]\d+)?', answer)
    numbers = [float(n.replace(',', '.').replace('−', '-')) for n in raw]
    for expected in case.get('numbers', []):
        if not any(abs(n-expected) <= max(.015, abs(expected)*.01) for n in numbers):
            errors.append('wrong_or_missing_number:' + str(expected))
    if not answer.strip() or answer.startswith('❌'):
        errors.append('empty_or_adapter_error')
    if 'json_expected' in case:
        try:
            if json.loads(answer) != case['json_expected']:
                errors.append('json_value')
        except ValueError:
            errors.append('json_format')
    if case.get('max_words') and len(answer.split()) > case['max_words']:
        errors.append('word_limit')
    return errors


async def evaluate(args):
    from app.core.repository import repo
    from app.core.request_context import generation_preferences
    from app.services import chat_service
    from app.services.orchestrator_metrics import model_trace
    chat_service.schedule_memory_refresh = lambda *a, **k: None
    cases = json.loads(args.cases.read_text(encoding='utf8'))
    if args.ids:
        cases = [c for c in cases if c['id'] in args.ids.split(',')]
    calls = []
    active_calls = ContextVar("evaluation_case_calls", default=None)

    class Collector(logging.Handler):
        def emit(self, record):
            value = record.getMessage()
            if value.startswith('orchestrator_call '):
                entry = json.loads(value.split(' ', 1)[1])
                calls.append(entry)
                current = active_calls.get()
                if current is not None:
                    current.append(entry)

    metrics_logger = logging.getLogger('app.services.orchestrator_metrics')
    metrics_logger.addHandler(Collector())
    metrics_logger.setLevel(logging.INFO)
    report = {'synthetic': True, 'mode': args.model, 'cases': [], 'limitations': [
        'Small acceptance suite, not a general knowledge benchmark.',
        'Automatic checks are lexical/numeric screening; full answers require review.',
        'Costs are adapter estimates; no production customer quota is charged.']}
    lock = asyncio.Semaphore(2)

    async def one(case, repeat):
        async with lock:
            spent = sum(c.get('metrics', {}).get('spent_usd', 0) for c in report['cases'])
            if spent >= args.budget_usd:
                report['cases'].append({'id': case['id'], 'repeat': repeat, 'errors': ['suite_budget']})
                return
            email = f'understanding-{case["id"]}-{repeat}@example.invalid'
            uid = await repo.ensure_user(email)
            await repo.set_subscription_tier(email, 'creator', 30)
            await repo.set_user_model(email, args.model)
            conv = await repo.create_conversation(email, 'Synthetic understanding acceptance')
            cid = conv['id']
            for message in case.get('history', []):
                if message.get('role') not in {'user', 'assistant'} or not isinstance(message.get('content'), str):
                    raise ValueError('Invalid synthetic history message')
                await repo.add_message(email, message['role'], message['content'], conv_id=cid)
            before_attachment = None
            original_canvas = b'<!doctype html><html><body><h1>Existing canvas</h1></body></html>'
            if case.get('context_canvas'):
                # A real bound, stored assistant artifact; it must remain immutable.
                before_attachment = await chat_service._persist_generated_file(email, 'existing.html',
                    original_canvas)
                before_attachment.update({'canvas': True, 'mime_type': 'text/html'})
                await repo.add_message(email, 'user', 'Создай сайт кофейни', conv_id=cid)
                await repo.add_message(email, 'assistant', 'Готово', conv_id=cid, attachment=before_attachment)
            row = {'id': case['id'], 'domain': case['domain'], 'repeat': repeat, 'prompt': case['prompt'],
                   'rubric': case['rubric'], 'errors': []}
            started = time.monotonic()
            statuses = []

            async def noop(*a, **k): pass
            async def status(text): statuses.append(text)

            token = generation_preferences.set({'user_id': uid, 'selected_model': args.model,
                'reasoning_effort': 'none', 'image_quality': 'medium',
                'canvas_target': before_attachment['url'] if before_attachment else None})
            metrics = None
            case_calls = []
            calls_token = active_calls.set(case_calls)
            try:
                with model_trace('chat-understanding') as metrics:
                    await asyncio.wait_for(chat_service.run_chat(email, case['prompt'], cid,
                        status, noop, noop, noop, noop, noop), timeout=180)
                history = await repo.get_messages(email, cid)
                answer = next(m for m in reversed(history) if m['role'] == 'assistant')
                row.update({'answer': answer['content'], 'attachment': answer.get('attachment'),
                    'sources': answer.get('search'), 'metrics': metrics,
                    'calls': list(case_calls)})
                row['errors'] += screen(case, answer['content'])
                if answer.get('attachment'):
                    row['errors'].append('unexpected_artifact')
                if await repo.get_user_model(email) != args.model:
                    row['errors'].append('persisted_mode_changed')
                if before_attachment:
                    path = repo._manager._attachment_disk_path(before_attachment)
                    if path.read_bytes() != original_canvas:
                        row['errors'].append('previous_artifact_changed')
            except Exception as exc:
                row['errors'].append(type(exc).__name__ + ': ' + str(exc)[:250])
            finally:
                active_calls.reset(calls_token)
                generation_preferences.reset(token)
                if metrics is not None:
                    row['metrics'] = metrics
                    row['calls'] = list(case_calls)
                    # Director opens a nested trace. Attribute calls by execution
                    # context rather than losing them when its run id differs.
                    row['metrics'] = dict(metrics, spent_usd=sum(
                        c.get('estimated_text_usd', 0) for c in case_calls))
            row['seconds'] = round(time.monotonic()-started, 2)
            row['statuses'] = statuses
            report['cases'].append(row)
            (args.output/(case['id'] + '-' + str(repeat) + '.txt')).write_text(row.get('answer', ''), encoding='utf8')
            (args.output/'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
            print(json.dumps({'id': case['id'], 'repeat': repeat, 'errors': row['errors'],
                              'seconds': row['seconds']}, ensure_ascii=False), flush=True)

    await asyncio.gather(*(one(c, repeat) for repeat in range(args.repeats) for c in cases))
    report['summary'] = {'count': len(report['cases']), 'screen_passed': sum(not c['errors'] for c in report['cases']),
        'estimated_text_usd': sum(c.get('metrics', {}).get('spent_usd', 0) for c in report['cases'])}
    (args.output/'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report['summary']), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--model', default='auto')
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--ids', default='')
    parser.add_argument('--budget-usd', type=float, default=4.)
    args = parser.parse_args()
    args.output = args.output.resolve(); args.output.mkdir(parents=True, exist_ok=True)
    assert not (args.output/'fixture.sqlite').exists(), 'Use a fresh isolated output directory'
    os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///' + (args.output/'fixture.sqlite').as_posix()
    os.environ['UPLOAD_DIR'] = str(args.output/'uploads')
    os.environ['DATA_DIR'] = str(args.output/'data')
    os.environ['PROJECT_EMBEDDINGS_ENABLED'] = 'false'
    os.environ['ORCHESTRATOR_MODEL_BUDGET_USD'] = '.6'
    from app.config import get_settings
    from app.db.base import Base
    import app.db.models, app.db.project_models, app.db.generation_models, app.db.experience_models
    from app.db.engine import sync_engine
    Base.metadata.create_all(sync_engine)
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(evaluate(args))


if __name__ == '__main__':
    main()
