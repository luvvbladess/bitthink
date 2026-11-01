"""Opt-in real artifact workflows. Run only in the dedicated evaluation containers.

python -m evals.specialized --execute --env-file /runtime.env --data-dir /tmp/eval \
    --output /results/baseline.json --budget-usd 12 --per-case-usd 1.25

Uses real storage, sandbox and adapters, with new synthetic users per run.
Independent artifact execution checks are in specialized_verify.py.
"""
import argparse
import asyncio
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import secrets
import time
from unittest.mock import patch
import zipfile
import xml.etree.ElementTree as ET

from evals.calibrate import TraceCollector, active_row, assertions, configure


def file_text(path):
    if path.suffix.lower() == '.docx':
        with zipfile.ZipFile(path) as archive:
            xml = ET.fromstring(archive.read('word/document.xml'))
        return '\n'.join(node.text or '' for node in xml.iter() if node.tag.endswith('}t'))
    if path.suffix.lower() in {'.md','.txt','.csv','.json'}:
        return path.read_text(encoding='utf8')
    return ''


def score(case, row):
    errors = assertions(case, row)
    names = [a['filename'] for a in row.get('artifacts', [])]
    for pattern in case.get('required_artifacts', []):
        if not any(re.search(pattern, name, re.I) for name in names):
            errors.append('missing_artifact:' + pattern)
    read = sum(s.get('evidence_state') == 'read' for s in row.get('sources', []))
    if read < case.get('answer', {}).get('min_read', 0):
        errors.append('not_enough_read_sources')
    if row.get('fixture_changes'):
        errors.append('modified_protected_input')
    if case.get('verify') in {'python_csv','javascript_cli','typescript_cli','c_cli','python_service','holdout_python_fix'} and re.search(
            r'не удалось.{0,60}(?:сборк|тест|запуск)|не могу подтвердить.{0,60}готов|сборк\w*.{0,40}не проверен', row.get('answer',''), re.I|re.S):
        errors.append('project_verification_incomplete')
    return errors


async def execute(args, cases):
    manager = configure(args)
    from app.config import get_settings
    settings = get_settings()
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    from app.services.sandbox_client import run_workspace_tool, collect_workspace_files
    from app.services.workspace_fs import user_root
    from app.services.conversation_context import workspaces
    from turn_scope import turn_conversation, pick_deliverables
    import director_router as dr
    import computer_tools

    logger = logging.getLogger('app.services.orchestrator_metrics')
    collector = TraceCollector()
    logger.addHandler(collector)
    logger.setLevel(logging.INFO)
    real_tool = computer_tools.run_computer_tool
    real_employee = dr._execute_employee
    root = args.output.parent / (args.output.stem + '-artifacts')
    root.mkdir(parents=True, exist_ok=True)
    report = {'kind':'specialized_live', 'synthetic':True, 'uid_base':9_811_000_000 + secrets.randbelow(100_000)*100,
              'budget_usd':args.budget_usd, 'employee_model':args.employee_model, 'results':[]}
    available = args.budget_usd
    semaphore = asyncio.Semaphore(args.concurrency)

    def save():
        report['observed_usd'] = round(sum(r['usd'] for r in report['results']), 8)
        temporary = args.output.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        temporary.replace(args.output)

    async def observed(name, tool_args, *rest, **kwargs):
        row = active_row.get()
        entry = {'name':name}
        if name == 'load_skill': entry['skill'] = tool_args.get('name')
        if name.startswith('workspace_') or name == 'python_run':
            entry['path'] = tool_args.get('path')
        if name == 'workspace_run':
            entry['argv'] = tool_args.get('argv')
        if row is not None: row['tools'].append(entry)
        started = time.monotonic()
        try:
            result = await real_tool(name, tool_args, *rest, **kwargs)
        except Exception as exc:
            entry['exception'] = type(exc).__name__
            raise
        finally:
            entry['seconds'] = round(time.monotonic() - started, 3)
        if name == 'python_run':
            match = re.search(r'^exit\s+(-?\d+)', str(result))
            entry['exit_code'] = int(match.group(1)) if match else None
            if not match or int(match.group(1)):
                entry['diagnostic'] = str(result)[-1200:]
        if name == 'workspace_run':
            try:
                data=json.loads(result)
                entry['exit_code']=data.get('exit_code')
                if data.get('exit_code'):
                    entry['diagnostic']=str(data.get('output') or data.get('error') or '')[-1200:]
            except (ValueError,TypeError):entry['diagnostic']=str(result)[-1200:]
        return result

    async def employee(item, *rest, **kwargs):
        if args.employee_model:
            item = {**item, 'model':args.employee_model}
        return await real_employee(item, *rest, **kwargs)

    async def one(index, case):
        nonlocal available
        async with semaphore:
            if available < args.per_case_usd:
                report['stopped'] = 'budget_reserve'
                return
            available -= args.per_case_usd
            uid = report['uid_base'] + index
            manager.set_subscription_tier(uid, 'creator', duration_days=1)
            conv = manager.create_conversation(uid, 'Synthetic ' + case['id'])
            manager.set_active_conversation(uid, conv.id)
            protected = {}
            for relative, content in case.get('fixtures', {}).items():
                await run_workspace_tool('workspace_write', {'path':relative, 'content':content}, uid)
                if relative.endswith('test_main.py') or relative.startswith('inputs/'):
                    protected[relative] = hashlib.sha256(content.encode()).hexdigest()
            await run_workspace_tool('workspace_ls', {}, uid)
            for filename, content in case.get('documents', {}).items():
                manager.add_document(uid, filename, content, conv_id=conv.id)
                disk = settings.UPLOAD_DIR / str(uid) / filename
                disk.parent.mkdir(parents=True, exist_ok=True)
                disk.write_text(content, encoding='utf8')
                manager.add_message(uid, 'user', 'Прикреплён ' + filename,
                    attachment={'type':'document','name':filename,'url':'/uploads/'+str(uid)+'/'+filename}, conv_id=conv.id)
            row = {'id':case['id'], 'split':case['split'], 'category':case['category'], 'uid':uid,
                   'query':case['query'], 'calls':[], 'summaries':[], 'tools':[], 'artifacts':[]}
            token = active_row.set(row)
            work = workspaces.set([])
            started = time.monotonic()
            try:
                with turn_conversation(conv.id):
                    messages = [{'role':'user','content':case['query']}]
                    answer, files, reasoning, sources = await asyncio.wait_for(
                        dr.get_director_response(messages, case['query'], uid, None), args.timeout)
                    row.update(answer=answer, sources=sources)
                    files = pick_deliverables([*(files or []), *await collect_workspace_files(uid, started)])
                    directory = root / case['id']
                    directory.mkdir(parents=True, exist_ok=True)
                    for artifact in files:
                        name = Path(artifact.get('filename') or artifact.get('name') or 'file').name
                        data = artifact.get('bytes')
                        if not isinstance(data, bytes): continue
                        path = directory / name
                        path.write_bytes(data)
                        row['artifacts'].append({'filename':name, 'path':str(path), 'sha256':hashlib.sha256(data).hexdigest(), 'size':len(data)})
            except Exception as exc:
                row.update(exception=type(exc).__name__, answer=row.get('answer', ''))
            finally:
                active_row.reset(token)
                workspaces.reset(work)
            row['fixture_changes'] = [name for name, digest in protected.items()
                if not (user_root(uid)/name).is_file() or hashlib.sha256((user_root(uid)/name).read_bytes()).hexdigest() != digest]
            row['seconds'] = round(time.monotonic()-started, 3)
            row['usd'] = round(sum(c['estimated_text_usd'] for c in row['calls']), 8)
            charged = max(row['usd'], *(s.get('spent_usd', 0) for s in row['summaries']),
                          args.per_case_usd if row.get('exception') else 0)
            available += max(0, args.per_case_usd-charged)
            row['errors'] = score(case, row)
            row['passed'] = not row['errors']
            report['results'].append(row)
            report['results'].sort(key=lambda r: next(i for i,c in enumerate(cases) if c['id']==r['id']))
            save()
            print(json.dumps({'id':row['id'], 'seconds':row['seconds'], 'usd':row['usd'],
                              'calls':len(row['calls']), 'files':[a['filename'] for a in row['artifacts']], 'errors':row['errors']}, ensure_ascii=False), flush=True)

    try:
        with patch.object(computer_tools, 'run_computer_tool', observed), patch.object(dr, '_execute_employee', employee):
            await asyncio.gather(*(one(i,c) for i,c in enumerate(cases)))
    finally:
        logger.removeHandler(collector)
    save()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--env-file', type=Path)
    p.add_argument('--data-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--budget-usd', type=float, default=12)
    p.add_argument('--per-case-usd', type=float, default=1.25)
    p.add_argument('--timeout', type=float, default=540)
    p.add_argument('--concurrency', type=int, choices=[1,2], default=2)
    p.add_argument('--employee-model', default='')
    p.add_argument('--ids', default='')
    p.add_argument('--split', choices=['all','dev','holdout'], default='all')
    args = p.parse_args()
    args.direct_model = ''
    if not 0 < args.per_case_usd <= args.budget_usd <= 30: p.error('Invalid budget')
    cases = json.loads((Path(__file__).parent/'cases/specialized.json').read_text(encoding='utf8'))['cases']
    cases = [c for c in cases if (args.split=='all' or c['split']==args.split) and (not args.ids or c['id'] in args.ids.split(','))]
    if not args.execute:
        print(json.dumps({'dry_run':True,'cases':[c['id'] for c in cases]}));return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(execute(args,cases))
    print(json.dumps({'completed':len(result['results']), 'observed_usd':result['observed_usd']}))


if __name__=='__main__':main()
