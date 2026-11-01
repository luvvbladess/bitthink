"""Opt-in evaluation of the real orchestrator in an isolated synthetic database.

python -m evals.calibrate --execute --env-file /app/.env --data-dir /tmp/bt-eval \
    --output /tmp/bt-eval/baseline.json --budget-usd 8

Reports retain synthetic prompts/answers and content-free call metadata. They do
not contain credentials, user conversations, tool arguments or tool responses.
Assertions are regression checks, not an automatic semantic quality rating.
"""
import argparse
import asyncio
from contextvars import ContextVar
import json
import logging
import os
from pathlib import Path
import re
import time
from unittest.mock import patch

active_row = ContextVar('calibration_row', default=None)


class TraceCollector(logging.Handler):
    def emit(self, record):
        row = active_row.get()
        if row is None:
            return
        message = record.getMessage()
        for prefix, key in [('orchestrator_call ', 'calls'), ('orchestrator_summary ', 'summaries')]:
            if message.startswith(prefix):
                row[key].append(json.loads(message[len(prefix):]))


def assertions(case, row):
    text = row.get('answer', '')
    errors = []
    for pattern in case.get('answer', {}).get('required', []):
        if not re.search(pattern, text, re.I):
            errors.append('missing:' + pattern)
    for pattern in case.get('answer', {}).get('forbidden', []):
        if re.search(pattern, text, re.I):
            errors.append('forbidden:' + pattern)
    if 'json_expected' in case:
        try:
            if json.loads(text) != case['json_expected']:
                errors.append('json_value')
        except ValueError:
            errors.append('json_format')
    if case.get('max_words') and len(text.split()) > case['max_words']:
        errors.append('word_limit')
    tools = {x['name'] for x in row['tools']}
    if case.get('required_tools_any') and not tools.intersection(case['required_tools_any']):
        errors.append('required_tool_missing')
    if case.get('max_calls') and len(row['calls']) > case['max_calls']:
        errors.append('excess_model_calls')
    if case.get('expect_strong') and not any(c.get('model') in {
            'gpt-6-sol', 'claude-sonnet-5.5', 'claude-opus-5.5', 'gpt-6-astra'} for c in row['calls']):
        errors.append('expert_question_uses_only_small_models')
    if case.get('answer', {}).get('min_citations'):
        from app.services.source_quality import cited_urls
        if len(cited_urls(text)) < case['answer']['min_citations']:
            errors.append('citation_missing')
    if not text.strip():
        errors.append('empty_answer')
    if text.lstrip().startswith('❌'):
        errors.append('provider_error_answer')
    if row.get('exception'):
        errors.append('exception:' + row['exception'])
    return errors


def configure(args):
    from dotenv import load_dotenv
    if args.env_file:
        load_dotenv(args.env_file)
    directory = args.data_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    # Always replace the connection string, even when a production .env is read.
    os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///' + (directory / 'synthetic.sqlite').as_posix()
    os.environ['DATA_DIR'] = str(directory / 'data')
    os.environ['UPLOAD_DIR'] = str(directory / 'uploads')
    os.environ['ORCHESTRATOR_MODEL_BUDGET_USD'] = str(args.per_case_usd)
    if args.direct_model:
        os.environ['ORCHESTRATOR_DIRECT_MODEL'] = args.direct_model
    from app.config import get_settings
    from app.db.base import Base
    from app.db.engine import sync_engine
    import app.db.models
    import app.db.project_models
    Base.metadata.create_all(sync_engine)
    from conversations import conversation_manager
    return conversation_manager


async def run(args, cases):
    manager = configure(args)
    import director_router as dr
    import computer_tools
    from computer_skills.loader import match_skills
    collector = TraceCollector()
    logger = logging.getLogger('app.services.orchestrator_metrics')
    logger.addHandler(collector)
    logger.setLevel(logging.INFO)
    original_tool = computer_tools.run_computer_tool

    async def observed_tool(name, tool_args, *rest, **kwargs):
        row = active_row.get()
        if row is not None:
            entry = {'name': name}
            if name == 'load_skill':
                entry['skill'] = tool_args.get('name')
            row['tools'].append(entry)
        return await original_tool(name, tool_args, *rest, **kwargs)

    report = {'kind': 'live_orchestrator', 'synthetic': True, 'semantic_review_required': True,
              'budget_usd': args.budget_usd, 'per_case_usd': args.per_case_usd, 'direct_model': args.direct_model,
              'results': []}
    charged = 0.0
    try:
        with patch.object(computer_tools, 'run_computer_tool', observed_tool):
            for index, case in enumerate(cases):
                if charged + args.per_case_usd > args.budget_usd:
                    report['stopped'] = 'budget_reserve'
                    break
                uid = 987_611_010 + index
                manager.set_subscription_tier(uid, 'creator', duration_days=1)
                row = {'id': case['id'], 'split': case['split'], 'category': case['category'],
                       'query': case['query'], 'calls': [], 'summaries': [], 'tools': []}
                token = active_row.set(row)
                started = time.monotonic()
                try:
                    messages = [*case.get('history', []), {'role':'user', 'content':case['query']}]
                    row['route'] = {'light': dr._is_light_task(case['query'], '', False, uid),
                                    'strong': dr._needs_strong_model(case['query'], '', False, uid),
                                    'skills': match_skills(case['query'], user_id=uid, sandbox=True)}
                    answer, files, reasoning, sources = await asyncio.wait_for(
                        dr.get_director_response(messages, case['query'], uid, None), timeout=args.timeout)
                    row.update(answer=answer, files=[f.get('name', '') for f in files or []], sources=sources)
                except Exception as exc:
                    row['exception'] = type(exc).__name__
                    row.setdefault('answer', '')
                finally:
                    active_row.reset(token)
                row['seconds'] = round(time.monotonic() - started, 3)
                row['usd'] = round(sum(c['estimated_text_usd'] for c in row['calls']), 8)
                # Unknown usage after a timeout consumes the whole case reservation.
                charged += max(row['usd'], *(s.get('spent_usd', 0) for s in row['summaries']),
                               args.per_case_usd if row.get('exception') else 0)
                row['errors'] = assertions(case, row)
                row['passed'] = not row['errors']
                report['results'].append(row)
                report.update(charged_usd=round(charged, 8), observed_usd=round(sum(r['usd'] for r in report['results']), 8))
                args.output.parent.mkdir(parents=True, exist_ok=True)
                temporary = args.output.with_suffix('.json.tmp')
                temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
                temporary.replace(args.output)
                print(json.dumps({'id':row['id'], 'seconds':row['seconds'], 'usd':row['usd'],
                                  'calls':len(row['calls']), 'errors':row['errors']}, ensure_ascii=False), flush=True)
    finally:
        logger.removeHandler(collector)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--budget-usd', type=float, default=8)
    parser.add_argument('--per-case-usd', type=float, default=.5)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--ids', default='')
    parser.add_argument('--direct-model', default='')
    parser.add_argument('--split', choices=['all','dev','holdout'], default='all')
    args = parser.parse_args()
    if not 0 < args.per_case_usd <= args.budget_usd <= 30:
        parser.error('Require 0 < per-case budget <= total budget <= 30 USD')
    cases = json.loads((Path(__file__).parent / 'cases/calibration.json').read_text(encoding='utf8'))['cases']
    cases = [c for c in cases if (args.split == 'all' or c['split'] == args.split)
             and (not args.ids or c['id'] in args.ids.split(','))]
    if not cases:
        parser.error('No selected cases')
    if not args.execute:
        print(json.dumps({'dry_run':True, 'cases':[c['id'] for c in cases], 'budget_usd':args.budget_usd}))
        return
    report = asyncio.run(run(args, cases))
    print(json.dumps({'completed':len(report['results']), 'observed_usd':report['observed_usd']}))


if __name__ == '__main__':
    main()
