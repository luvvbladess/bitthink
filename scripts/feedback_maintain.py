"""Host controller for evidence-driven repairs. Chat text never enters this process."""
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request
import uuid

ALLOWED = {'backend/app/services/product_strategy.py', 'backend/app/services/request_intent.py',
           'backend/app/services/source_quality.py', 'backend/app/bot_core/studio/quality.py'}


def cycle(c, root, apply=False, uid=None):
    root = root.resolve()
    directory = root / 'data/autonomy'
    directory.mkdir(parents=True, exist_ok=True)
    status = {'status': 'reviewing', 'started_at': int(time.time()), 'applied': False}
    issue = None
    images, network, postgres = [], None, None
    def transition(state, detail='', verified=False):
        c.inside('''import json,sys
from app.services.improvement_journal import transition
d=json.load(sys.stdin);transition(d['id'],d['state'],d['detail'],verified=d['verified'])
''', {'id': issue['id'], 'state': state, 'detail': detail, 'verified': verified})
    try:
        if uid is None:
            uid = int(c.inside('''from sqlalchemy import select
from app.db.engine import SyncSessionLocal
from app.db.models import User
with SyncSessionLocal() as db:
 u=db.scalar(select(User).where(User.role=='admin').order_by(User.id))
 if u is None: raise ValueError('Administrator required')
 print(u.bot_user_id)
''').strip().splitlines()[-1])
        review = json.loads(c.inside('''import asyncio,json,sys
from app.services.daily_feedback import review_daily
print(json.dumps(asyncio.run(review_daily(json.load(sys.stdin)['uid'])),ensure_ascii=False))
''', {'uid': uid}, timeout=600))
        status['review'] = review
        issue = json.loads(c.inside('from app.services.improvement_journal import next_issue; import json,sys;print(json.dumps(next_issue(allow_resolve=not json.load(sys.stdin)["backlog"])))', {'backlog': review['backlog']}))
        if not issue:
            status['status'] = 'reviewed'
            return status
        status['issue_id'] = issue['id']
        if issue['target'] not in ALLOWED:
            raise ValueError('Issue target outside repair policy')
        if c.activity():
            status['status'] = 'deferred'
            return status
        path = issue['target']
        source = (root / path).read_text(encoding='utf-8')
        baseline = c.run(['docker', 'inspect', c.CONTAINER, '--format', '{{.Image}}']).stdout.strip()
        actual = c.inside('import pathlib,json,sys; d=json.load(sys.stdin);print(pathlib.Path("/app",d["path"].removeprefix("backend/")).read_text(),end="")', {'path': path})
        if actual != source:
            raise ValueError('Host source differs from active image')
        transition('reproducing', 'Подготовка кандидата и воспроизводящего теста.')
        proposal = json.loads(c.inside('''import asyncio,json,sys
from app.services.feedback_repair import propose
d=json.load(sys.stdin);print(json.dumps(asyncio.run(propose(d['uid'],d['id'],d['source'])),ensure_ascii=False))
''', {'uid': uid, 'id': issue['id'], 'source': source}, timeout=300))
        if proposal.get('cannot_fix'):
            transition('needs_review', proposal['cannot_fix'])
            status['status'] = 'needs_review'
            return status
        c.inside('''import json,sys
from app.services.feedback_repair import validate
d=json.load(sys.stdin);validate(d['source'],d['proposal'])
''', {'source': source, 'proposal': proposal})
        if proposal['path'] != path:
            raise ValueError('Patch target mismatch')
        stamp = uuid.uuid4().hex[:12]
        candidate = directory / ('feedback-' + stamp)
        candidate.mkdir(mode=0o700)
        c.write_json(candidate / 'proposal.json', proposal)
        test_path = 'backend/tests/regressions/test_feedback_' + issue['id'] + '_' + stamp + '.py'
        test_name = Path(test_path).name
        (candidate / 'regression.py').write_text(proposal['test'], encoding='utf-8')
        (candidate / 'module.py').write_text(proposal['source'], encoding='utf-8')
        base_tag = 'bitthink-feedback-base:' + stamp
        c.run(['docker', 'tag', baseline, base_tag])
        baseline_image = 'bitthink-feedback-repro:' + stamp
        candidate_image = 'bitthink-feedback:' + stamp
        images = [baseline_image, candidate_image]
        dockerfile = f'FROM {base_tag}\nRUN mkdir -p /app/tests/regressions && chmod 755 /app/tests/regressions\nCOPY --chmod=644 regression.py /app/tests/regressions/{test_name}\n'
        (candidate / 'Dockerfile').write_text(dockerfile, encoding='utf-8')
        c.run(['docker', 'build', '-t', baseline_image, str(candidate)])
        command = ['python', '-m', 'unittest', 'discover', '-s', 'tests/regressions', '-p', test_name, '-v']
        before = c.candidate_run(baseline_image, command, check=False, timeout=90)
        (candidate / 'before.log').write_text(before.stdout, encoding='utf-8')
        if before.returncode != 1 or 'AssertionError' not in before.stdout or 'FAIL:' not in before.stdout or 'ERROR:' in before.stdout or not re.search(r'Ran [1-9]\d* tests?', before.stdout):
            transition('needs_review', 'Не получено воспроизведение дефекта через AssertionError на старой версии.')
            status['status'] = 'not_reproduced'
            return status
        (candidate / 'Dockerfile').write_text(dockerfile + f'COPY --chmod=644 module.py /app/{path.removeprefix("backend/")}\n', encoding='utf-8')
        c.run(['docker', 'build', '-t', candidate_image, str(candidate)])
        after = c.candidate_run(candidate_image, command)
        (candidate / 'after.log').write_text(after.stdout, encoding='utf-8')
        if not re.search(r'Ran [1-9]\d* tests?', after.stdout) or 'OK' not in after.stdout:
            raise ValueError('Candidate did not pass behavior test')
        network = 'bt-feedback-' + stamp
        postgres = network + '-db'
        c.run(['docker', 'network', 'create', '--internal', network])
        c.run(['docker', 'run', '-d', '--name', postgres, '--network', network, '--network-alias', 'db', '--memory', '256m',
               '-e', 'POSTGRES_USER=feedback', '-e', 'POSTGRES_PASSWORD=isolated-only', '-e', 'POSTGRES_DB=feedback', 'postgres:16-alpine'])
        for attempt in range(30):
            if c.run(['docker', 'exec', postgres, 'pg_isready', '-U', 'feedback'], check=False).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Test database unavailable')
        env = {'DATABASE_URL': 'postgresql+asyncpg://feedback:isolated-only@db:5432/feedback', 'SECRET_KEY': 'isolated-feedback',
            'OPENAI_API_KEY': 'test-key', 'DEEPSEEK_API_KEY': 'test-key', 'KIMI_API_KEY': 'test-key',
            'DATA_DIR': '/tmp/data', 'UPLOAD_DIR': '/app/uploads', 'MPLBACKEND': 'Agg', 'PYTHONDONTWRITEBYTECODE': '1'}
        checks = [['python', '-m', 'alembic', 'upgrade', 'head'], ['python', '-m', 'pytest', 'tests', '-p', 'no:cacheprovider'],
                  ['python', '-m', 'evals.quality', '--report', '/tmp/quality.json'],
                  ['python', '-m', 'evals.product_journeys', '--fixtures', '--report', '/tmp/journeys.json']]
        for number, check in enumerate(checks):
            try:
                result = c.candidate_run(candidate_image, check, network=network, env=env, timeout=900, root=root)
            except RuntimeError as exc:
                (candidate / f'check-{number}.log').write_text(getattr(exc, 'output', str(exc)), encoding='utf-8')
                raise
            (candidate / f'check-{number}.log').write_text(result.stdout, encoding='utf-8')
        transition('verified_candidate', 'Исходная ошибка воспроизведена; кандидат и полный набор проверок прошли.', True)
        if not apply or c.activity():
            status['status'] = 'verified_candidate'
            return status
        if c.run(['docker', 'inspect', c.CONTAINER, '--format', '{{.Image}}']).stdout.strip() != baseline or (root / path).read_text(encoding='utf-8') != source:
            raise ValueError('Release changed during verification')
        if (root / test_path).exists():
            raise ValueError('Existing regression test cannot be overwritten')
        (candidate / 'before.py').write_text(source, encoding='utf-8')
        (candidate / 'base-image.txt').write_text(baseline, encoding='utf-8')
        history = directory / 'code-history'
        history.mkdir(exist_ok=True)
        if not (history / '.git').exists():
            c.run(['git', 'init', str(history)])
            c.run(['git', 'config', 'user.name', 'Bit-Think Kaizen'], cwd=history)
            c.run(['git', 'config', 'user.email', 'kaizen@bit-think.space'], cwd=history)
        for name, content in [(path, proposal['source']), (test_path, proposal['test'])]:
            saved = history / name; saved.parent.mkdir(parents=True, exist_ok=True); saved.write_text(content, encoding='utf-8')
        c.write_json(history / 'feedback-evidence.json', {'issue_id': issue['id'], 'reproduced': True, 'checks_passed': True})
        c.run(['git', 'add', path, test_path, 'feedback-evidence.json'], cwd=history)
        c.run(['git', 'commit', '-m', 'Verified feedback repair ' + issue['id']], cwd=history)
        try:
            (root / path).write_text(proposal['source'], encoding='utf-8')
            (root / test_path).parent.mkdir(parents=True, exist_ok=True)
            (root / test_path).write_text(proposal['test'], encoding='utf-8')
            c.run(['docker', 'tag', candidate_image, c.IMAGE_TAG])
            c.run(['docker', 'compose', 'up', '-d', '--no-deps', '--no-build', '--force-recreate', 'backend', 'worker'], cwd=root)
            for attempt in range(30):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3) as response:
                        if response.status == 200:
                            break
                except Exception:
                    time.sleep(2)
            else:
                raise RuntimeError('Candidate readiness failed')
            expected = c.run(['docker', 'image', 'inspect', candidate_image, '--format', '{{.Id}}']).stdout.strip()
            for service in ('gpt-ultra-web-backend-1', 'gpt-ultra-web-worker-1'):
                if c.run(['docker', 'inspect', service, '--format', '{{.Image}}']).stdout.strip() != expected:
                    raise RuntimeError('Candidate image not active')
        except BaseException:
            (root / path).write_text(source, encoding='utf-8')
            (root / test_path).unlink(missing_ok=True)
            c.run(['docker', 'tag', baseline, c.IMAGE_TAG])
            c.run(['docker', 'compose', 'up', '-d', '--no-deps', '--no-build', '--force-recreate', 'backend', 'worker'], cwd=root)
            raise
        transition('monitoring', 'Исправление применено. Закрытие после суток без повторения проблемы.', True)
        status.update(status='monitoring', applied=True)
        return status
    except BaseException as exc:
        status.update(status='error', error_type=type(exc).__name__)
        try:
            c.inside('''import json,sys
from app.services.improvement_journal import capture_error
capture_error('maintenance.feedback',json.load(sys.stdin)['type'])
''', {'type': type(exc).__name__})
        except Exception:
            pass
        if issue:
            try:
                transition('rejected', 'Проверка/выпуск не пройдены: ' + type(exc).__name__)
            except Exception:
                pass
        if not isinstance(exc, Exception):
            raise
        return status
    finally:
        status['finished_at'] = int(time.time())
        c.write_json(directory / 'feedback-status.json', status)
        if postgres:
            c.run(['docker', 'rm', '-f', '-v', postgres], check=False)
        if network:
            c.run(['docker', 'network', 'rm', network], check=False)
        if not status.get('applied') and status['status'] != 'verified_candidate':
            for image in images:
                c.run(['docker', 'image', 'rm', image], check=False)
