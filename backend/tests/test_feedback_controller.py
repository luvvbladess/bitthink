import importlib.util
import json
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


@pytest.mark.parametrize('reproduced,apply', [(False, True), (True, False), (True, True)])
def test_repair_requires_reproduction_and_rolls_back_failed_release(tmp_path, monkeypatch, reproduced, apply):
    module = controller()
    source = 'def select_stack(text):\n    return "static"\n'
    path = 'backend/app/services/product_strategy.py'
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_text(source, encoding='utf-8')
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
        raise OSError('readiness failed')
    monkeypatch.setattr(module.urllib.request, 'urlopen', failed)
    status = module.cycle(c, tmp_path, apply, uid=1)
    if not reproduced:
        assert status['status'] == 'not_reproduced' and states[-1] == 'needs_review'
        assert not any(cmd[:2] == ['docker', 'compose'] for cmd in commands)
    elif not apply:
        assert status['status'] == 'verified_candidate' and states[-1] == 'verified_candidate'
    else:
        assert status['status'] == 'error' and states[-1] == 'rejected'
        assert len([cmd for cmd in commands if cmd[:2] == ['docker', 'compose']]) == 2
        assert not list((tmp_path / 'backend/tests/regressions').glob('*.py'))
    assert target.read_text(encoding='utf-8') == source
