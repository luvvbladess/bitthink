import importlib.util
from contextlib import nullcontext
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS

import pytest


def controller():
    path = Path(__file__).resolve().parents[2] / 'scripts/feedback_maintain.py'
    if not path.exists():
        path = Path('/scripts/feedback_maintain.py')
    spec = importlib.util.spec_from_file_location('feedback_controller', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('reproduced,apply,healthy', [(False, True, False), (True, False, False),
                                                   (True, True, False), (True, True, True)])
def test_repair_requires_reproduction_and_rolls_back_failed_release(tmp_path, monkeypatch, reproduced, apply, healthy):
    module = controller()
    source = 'def select_stack(text):\n    return "static"\n'
    path = 'backend/app/services/product_strategy.py'
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_text(source, encoding='utf-8')
    for name in ('tests', 'evals'):
        (tmp_path / 'backend' / name).mkdir()
    (tmp_path / 'backend/pytest.ini').write_text('[pytest]\n', encoding='utf-8')
    (tmp_path / 'scripts').mkdir()
    issue = {'id': 'e' * 32, 'target': path}
    proposal = {'path': path, 'source': source + '# refined\n', 'test': 'synthetic test body'}
    commands, states, checks = [], [], []
    def inside(code, data=None, **kwargs):
        if 'review_daily' in code:
            return json.dumps({'backlog': False, 'messages_reviewed': 5})
        if 'next_issue' in code:
            return json.dumps(issue)
        if 'import propose' in code:
            return json.dumps(proposal)
        if 'import transition' in code:
            states.append(data['state']); return ''
        if 'removeprefix' in code:
            return source
        return ''
    def run(argv, **kwargs):
        commands.append(argv)
        return NS(returncode=0, stdout='sha256:baseline\n')
    def candidate(image, command, **kwargs):
        checks.append(command)
        if kwargs.get('check') is False:
            return NS(returncode=1 if reproduced else 0, stdout='FAIL: behavior\nAssertionError\nRan 1 test\n' if reproduced else 'Ran 1 test\nOK')
        return NS(returncode=0, stdout='Ran 1 test\nOK')
    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
    c = NS(inside=inside, run=run, candidate_run=candidate, activity=lambda: 0,
           write_json=write_json, CONTAINER='isolated', IMAGE_TAG='isolated-candidate')
    monkeypatch.setattr(module.time, 'sleep', lambda delay: None)
    def failed(*args, **kwargs):
        if healthy:
            return nullcontext(NS(status=200))
        raise OSError('readiness failed')
    monkeypatch.setattr(module.urllib.request, 'urlopen', failed)
    status = module.cycle(c, tmp_path, apply, uid=1)
    if not reproduced:
        assert status['status'] == 'not_reproduced' and states[-1] == 'needs_review'
        assert not any(cmd[:2] == ['docker', 'compose'] for cmd in commands)
    elif not apply:
        assert status['status'] == 'verified_candidate' and states[-1] == 'verified_candidate'
    elif not healthy:
        assert status['status'] == 'error' and states[-1] == 'rejected'
        assert len([cmd for cmd in commands if cmd[:2] == ['docker', 'compose']]) == 2
        assert not list((tmp_path / 'backend/tests/regressions').glob('*.py'))
    else:
        assert status['status'] == 'monitoring' and status['applied']
        assert states[-1] == 'monitoring'
        assert len([cmd for cmd in commands if cmd[:2] == ['docker', 'compose']]) == 1
    assert target.read_text(encoding='utf-8') == (proposal['source'] if apply and healthy else source)


def test_verification_snapshot_uses_current_tests_and_never_host_app(tmp_path):
    module = controller()
    for name in ('tests', 'evals'):
        directory = tmp_path / 'backend' / name
        directory.mkdir(parents=True)
        (directory / 'current.py').write_text('CURRENT = True\n')
    (tmp_path / 'backend/pytest.ini').write_text('[pytest]\n')
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'backend/app').mkdir()
    (tmp_path / 'backend/app/unsafe.py').write_text('HOST = True\n')
    candidate = tmp_path / 'candidate'
    candidate.mkdir()
    previous = os.umask(0o077)
    try:
        dockerfile = module.verification_files(tmp_path, candidate)
    finally:
        os.umask(previous)
    assert (candidate / 'verification/backend/tests/current.py').exists()
    assert (candidate / 'verification/backend/evals/current.py').exists()
    assert not (candidate / 'verification/backend/app').exists()
    assert 'cp -a /app/app' in dockerfile
    if os.name != 'nt':
        for path in (candidate / 'verification').rglob('*'):
            assert path.stat().st_mode & (0o555 if path.is_dir() else 0o444) == (0o555 if path.is_dir() else 0o444)


def test_reviewer_failure_does_not_block_existing_queue(tmp_path):
    module = controller()
    calls = []
    def inside(code, data=None, **kwargs):
        calls.append((code, data))
        if 'review_daily' in code:
            raise RuntimeError('review unavailable')
        if 'next_issue' in code:
            assert data['backlog'] is True
            return json.dumps({'id': 'queued', 'target': 'backend/app/services/request_intent.py'})
        raise AssertionError('No model or release while users are active')
    def write_json(path, value):
        path.write_text(json.dumps(value))
    c = NS(inside=inside, activity=lambda: 1, write_json=write_json)
    status = module.cycle(c, tmp_path, apply=True, uid=1)
    assert status['status'] == 'deferred'
    assert status['review_error'] == 'RuntimeError'
    assert status['issue_id'] == 'queued' and not status['applied']
