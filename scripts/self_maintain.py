"""Host-side kaizen controller. Run daily via the supplied systemd timer.

One model proposal per cycle, only after a measurable regression. Untrusted code
runs in disposable containers; the production process never imports a candidate.
The mutable algorithm cannot edit this controller, its benchmark, or its tests.
"""
import argparse
import datetime
import difflib
import json
from pathlib import Path
import signal
import subprocess
import time
import urllib.request
import uuid

ALLOWED = 'backend/app/services/product_strategy.py'
CONTAINER = 'gpt-ultra-web-backend-1'
DB_CONTAINER = 'gpt-ultra-web-db-1'
IMAGE_TAG = 'gpt-ultra-web-backend'


def run(argv, *, cwd=None, input=None, timeout=180, check=True):
    result = subprocess.run(argv, cwd=cwd, input=input, text=True, encoding='utf-8',
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if check and result.returncode:
        error = RuntimeError(f'{argv[:4]} failed ({result.returncode}): {result.stdout[-3000:]}')
        error.output = result.stdout
        raise error
    return result


def inside(code, data=None, timeout=180):
    # Program and payload use separate channels; data is never shell code.
    argv = ['docker', 'exec', '-i', CONTAINER, 'python', '-c', code]
    return run(argv, input=json.dumps(data) if data is not None else '', timeout=timeout).stdout


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.next')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def activity():
    result = inside('''from sqlalchemy import select, func
from app.db.engine import SyncSessionLocal
from app.db.models import ComputerTask
from app.db.generation_models import Generation
with SyncSessionLocal() as db:
 print(db.scalar(select(func.count()).select_from(ComputerTask).where(ComputerTask.status=='running')) + db.scalar(select(func.count()).select_from(Generation).where(Generation.status.in_(['queued','running','external']))))
''')
    return int(result.strip().splitlines()[-1])


def candidate_run(image, command, *, network='none', env=None, timeout=180, root=None, check=True):
    name = 'bt-kaizen-check-' + uuid.uuid4().hex[:12]
    argv = ['docker', 'run', '--rm', '--name', name, '--network', network, '--memory', '1536m', '--cpus', '1.5',
            '--pids-limit', '256', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '--tmpfs', '/tmp:rw,size=256m']
    if root is not None:
        # Offline fixtures still exercise the URL guard against public addresses.
        # These entries do not grant internet access to the internal network.
        for host in ('example.com', 'www.ozon.ru', 'www.wildberries.ru', 'www.chipdip.ru'):
            argv += ['--add-host', host + ':93.184.216.34']
        argv += ['-v', str(root / 'backend') + ':/backend:ro', '-v', str(root / 'sandbox') + ':/sandbox:ro', '-v', str(root / 'scripts') + ':/scripts:ro']
    else:
        argv += ['--read-only']
    for key, value in (env or {}).items():
        argv += ['-e', key + '=' + value]
    try:
        return run([*argv, image, *command], timeout=timeout, check=check)
    finally:
        run(['docker', 'rm', '-f', name], check=False)


def cycle(root, apply=False, uid=None, repair=True):
    root = root.resolve()
    directory = root / 'data/autonomy'
    directory.mkdir(parents=True, exist_ok=True)
    status_path = directory / 'maintenance-status.json'
    state = {'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'status': 'checking', 'mutable_paths': [ALLOWED], 'automatic_apply': apply,
             'model_calls': 0}
    write_json(status_path, state)
    database = None
    test_network = None
    test_postgres = None
    candidate_image = None
    try:
        health = json.load(urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=15))
        state['health'] = health
        baseline_image = run(['docker', 'inspect', CONTAINER, '--format', '{{.Image}}']).stdout.strip()
        baseline = json.loads(inside('from app.services.product_benchmark import evaluate; import json; print(json.dumps(evaluate()))'))
        state['benchmark_before'] = baseline['passed']
        state['benchmark_total'] = baseline['total']
        if baseline['passed'] == baseline['total']:
            state.update(status='healthy', reason='Все контрольные сценарии пройдены; изменение кода без измеримой пользы не выполнялось.')
            return state
        if not repair:
            state.update(status='deferred', reason='Сегодня уже обрабатывалось исправление по журналу.')
            return state
        if activity():
            state.update(status='deferred', reason='Есть активные пользовательские задачи.')
            return state
        if uid is None:
            uid = int(inside('''from sqlalchemy import select
from app.db.engine import SyncSessionLocal
from app.db.models import User
with SyncSessionLocal() as db:
 owner=db.scalar(select(User).where(User.role=='admin').order_by(User.id))
 if owner is None: raise ValueError('Administrator required')
 print(owner.bot_user_id)
''').strip().splitlines()[-1])
        source = (root / ALLOWED).read_text(encoding='utf-8')
        live_source = inside('from pathlib import Path; print(Path("/app/app/services/product_strategy.py").read_text(), end="")')
        if source != live_source:
            raise ValueError('Исходники на хосте отличаются от активного образа; сначала согласуйте версии.')
        proposal_text = inside('''import asyncio, json, sys
from app.services.self_improvement import propose
data=json.load(sys.stdin)
print(json.dumps(asyncio.run(propose(data['uid'], data['source'], data['observations'])), ensure_ascii=False))
''', {'uid': uid, 'source': source, 'observations': [item for item in baseline['cases'] if not item['passed']]}, timeout=240)
        proposal = json.loads(proposal_text)
        # Revalidate within trusted production code without importing the candidate.
        inside('''import json,sys
from app.services.self_improvement import validate_proposal
data=json.load(sys.stdin); validate_proposal(data['source'], data['proposal']); print('VALID')
''', {'source': source, 'proposal': proposal})
        state['model_calls'] = 1
        stamp = uuid.uuid4().hex[:16]
        candidate = directory / ('candidate-' + stamp)
        candidate.mkdir(mode=0o700)
        state['candidate_id'] = stamp
        write_json(candidate / 'proposal.json', proposal)
        (candidate / 'change.patch').write_text(''.join(difflib.unified_diff(source.splitlines(True), proposal['source'].splitlines(True),
            fromfile=ALLOWED, tofile=ALLOWED)), encoding='utf-8')
        (candidate / 'product_strategy.py').write_text(proposal['source'], encoding='utf-8')
        baseline_tag = 'bitthink-kaizen-base:' + stamp
        run(['docker', 'tag', baseline_image, baseline_tag])
        (candidate / 'Dockerfile').write_text(f'FROM {baseline_tag}\nCOPY product_strategy.py /app/app/services/product_strategy.py\n', encoding='utf-8')
        candidate_image = 'bitthink-kaizen:' + stamp
        run(['docker', 'build', '-t', candidate_image, str(candidate)], timeout=180)
        measured = candidate_run(candidate_image, ['python', '-m', 'app.services.product_benchmark'])
        after = json.loads(measured.stdout)
        write_json(candidate / 'benchmark.json', after)
        state['benchmark_after'] = after['passed']
        # Strict gain; no previously passing example may regress.
        if after['passed'] <= baseline['passed'] or any(old['passed'] and not new['passed'] for old, new in zip(baseline['cases'], after['cases'])):
            state.update(status='rejected', reason='Нет измеримого улучшения без регрессий.')
            return state
        database = 'kaizen'
        test_network = 'bt-kaizen-' + stamp
        test_postgres = test_network + '-db'
        run(['docker', 'network', 'create', '--internal', test_network])
        run(['docker', 'run', '-d', '--name', test_postgres, '--network', test_network, '--network-alias', 'db',
             '--memory', '256m', '-e', 'POSTGRES_USER=kaizen', '-e', 'POSTGRES_PASSWORD=isolated-only',
             '-e', 'POSTGRES_DB=kaizen', 'postgres:16-alpine'])
        for attempt in range(30):
            if run(['docker', 'exec', test_postgres, 'pg_isready', '-U', 'kaizen'], check=False).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Изолированная тестовая база не запустилась.')
        env = {'DATABASE_URL': 'postgresql+asyncpg://kaizen:isolated-only@db:5432/kaizen',
               'SECRET_KEY': 'isolated-kaizen-checks', 'OPENAI_API_KEY': 'test-key',
               'DEEPSEEK_API_KEY': 'test-key', 'KIMI_API_KEY': 'test-key', 'MPLBACKEND': 'Agg',
               'PYTHONDONTWRITEBYTECODE': '1', 'DATA_DIR': '/tmp/data', 'UPLOAD_DIR': '/app/uploads'}
        checks = [
            ['python', '-m', 'alembic', 'upgrade', 'head'],
            ['python', '-m', 'pytest', 'tests', '-p', 'no:cacheprovider'],
            ['python', '-m', 'evals.quality', '--report', '/tmp/quality.json'],
            ['python', '-m', 'evals.product_journeys', '--fixtures', '--report', '/tmp/journeys.json'],
        ]
        for index, command in enumerate(checks):
            try:
                result = candidate_run(candidate_image, command, network=test_network, env=env, timeout=900, root=root)
            except RuntimeError as exc:
                (candidate / f'check-{index}.log').write_text(getattr(exc, 'output', str(exc)), encoding='utf-8')
                raise
            (candidate / f'check-{index}.log').write_text(result.stdout, encoding='utf-8')
        state['checks_passed'] = True
        if not apply:
            state.update(status='verified_candidate', reason='Кандидат проверен; автоматическое применение выключено.')
            return state
        if activity():
            state.update(status='verified_candidate', reason='Применение отложено: появились активные задачи.')
            return state
        if run(['docker', 'inspect', CONTAINER, '--format', '{{.Image}}']).stdout.strip() != baseline_image or (root / ALLOWED).read_text(encoding='utf-8') != source:
            raise ValueError('Базовая версия изменилась во время проверки; автоматическое применение отменено.')
        (candidate / 'before.py').write_text(source, encoding='utf-8')
        (candidate / 'base-image.txt').write_text(baseline_image, encoding='utf-8')
        # A local Git ledger works even for installations delivered without .git.
        history = directory / 'code-history'
        history.mkdir(exist_ok=True)
        if not (history / '.git').exists():
            run(['git', 'init', str(history)])
            run(['git', 'config', 'user.name', 'Bit-Think Kaizen'], cwd=history)
            run(['git', 'config', 'user.email', 'kaizen@bit-think.space'], cwd=history)
        (history / 'product_strategy.py').write_text(proposal['source'], encoding='utf-8')
        write_json(history / 'evidence.json', {key: value for key, value in state.items() if key != 'health'})
        run(['git', 'add', 'product_strategy.py', 'evidence.json'], cwd=history)
        run(['git', 'commit', '-m', f'Kaizen {stamp}: benchmark {baseline["passed"]} -> {after["passed"]}'], cwd=history)
        state['revision'] = run(['git', 'rev-parse', 'HEAD'], cwd=history).stdout.strip()
        try:
            (root / ALLOWED).write_text(proposal['source'], encoding='utf-8')
            run(['docker', 'tag', candidate_image, IMAGE_TAG])
            run(['docker', 'compose', 'up', '-d', '--no-deps', '--no-build', '--force-recreate', 'backend', 'worker'], cwd=root)
            for attempt in range(30):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3) as response:
                        if response.status == 200:
                            break
                except Exception:
                    time.sleep(2)
            else:
                raise RuntimeError('Новая версия не прошла проверку готовности.')
            expected_image = run(['docker', 'image', 'inspect', candidate_image, '--format', '{{.Id}}']).stdout.strip()
            for service in ('gpt-ultra-web-backend-1', 'gpt-ultra-web-worker-1'):
                if run(['docker', 'inspect', service, '--format', '{{.Image}}']).stdout.strip() != expected_image:
                    raise RuntimeError('API и worker не переключились на проверенный образ.')
        except BaseException:
            (root / ALLOWED).write_text(source, encoding='utf-8')
            run(['docker', 'tag', baseline_image, IMAGE_TAG])
            run(['docker', 'compose', 'up', '-d', '--no-deps', '--no-build', '--force-recreate', 'backend', 'worker'], cwd=root)
            state['rolled_back'] = True
            raise
        state.update(status='applied', reason='Измеримое улучшение прошло неизменённые проверки и опубликовано.')
        return state
    except BaseException as exc:
        # No prompts, model source or secrets in the public status.
        state.update(status='error', error_type=type(exc).__name__)
        raise
    finally:
        state['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        write_json(status_path, state)
        if test_postgres:
            run(['docker', 'rm', '-f', '-v', test_postgres], check=False)
        if test_network:
            run(['docker', 'network', 'rm', test_network], check=False)
        # Keep applied candidate image for rollback/history; discard rejected images.
        if candidate_image and state['status'] not in {'applied', 'verified_candidate'}:
            run(['docker', 'image', 'rm', candidate_image], check=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--user-id', type=int)
    parser.add_argument('--skip-feedback', action='store_true', help='Run infrastructure/stack checks only')
    args = parser.parse_args()
    def terminate(signum, frame):
        raise KeyboardInterrupt('Maintenance stopped')
    signal.signal(signal.SIGTERM, terminate)
    import fcntl
    directory = args.root.resolve() / 'data/autonomy'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'maintenance.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        import sys
        feedback = None
        if not args.skip_feedback:
            from feedback_maintain import cycle as feedback_cycle
            feedback = feedback_cycle(sys.modules[__name__], args.root, args.apply, args.user_id)
        result = cycle(args.root, args.apply, args.user_id, repair=not bool(feedback and feedback.get('issue_id')))
        if feedback is not None:
            result['feedback'] = feedback
            if feedback.get('status') == 'error':
                result['status'] = 'attention'
            write_json(directory / 'maintenance-status.json', result)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
