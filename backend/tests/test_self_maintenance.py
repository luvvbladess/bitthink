import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def controller():
    path = Path(__file__).resolve().parents[2] / 'scripts/self_maintain.py'
    if not path.exists():
        path = Path('/scripts/self_maintain.py')
    spec = importlib.util.spec_from_file_location('self_maintain_controller', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_healthy_cycle_never_calls_model_or_restarts_containers(tmp_path, monkeypatch):
    script = controller()
    calls = []
    def command(argv, **kwargs):
        calls.append(argv)
        assert argv[:3] == ['docker', 'inspect', script.CONTAINER]
        return SimpleNamespace(stdout='sha256:baseline\n', returncode=0)
    monkeypatch.setattr(script, 'run', command)
    monkeypatch.setattr(script, 'inside', lambda code, *args, **kwargs: json.dumps({'passed': 28, 'total': 28}))
    monkeypatch.setattr(script.urllib.request, 'urlopen', lambda *args, **kwargs: SimpleNamespace(read=lambda: b'{"status":"ok"}'))
    status = script.cycle(tmp_path, apply=True)
    assert status['status'] == 'healthy' and status['model_calls'] == 0
    saved = json.loads((tmp_path / 'data/autonomy/maintenance-status.json').read_text(encoding='utf-8'))
    assert saved['status'] == 'healthy' and len(calls) == 1


def test_failed_readiness_never_triggers_blind_restart(tmp_path, monkeypatch):
    script = controller()
    commands = Mock()
    monkeypatch.setattr(script, 'run', commands)
    def unavailable(*args, **kwargs):
        raise OSError('offline')
    monkeypatch.setattr(script.urllib.request, 'urlopen', unavailable)
    with pytest.raises(OSError):
        script.cycle(tmp_path, apply=True)
    commands.assert_not_called()
    status = json.loads((tmp_path / 'data/autonomy/maintenance-status.json').read_text(encoding='utf-8'))
    assert status['status'] == 'error' and status['error_type'] == 'OSError'


def test_candidate_container_is_removed_after_timeout(monkeypatch):
    script = controller()
    calls = []
    def execute(argv, **kwargs):
        calls.append(argv)
        if argv[1] == 'run':
            raise TimeoutError('test process exceeded its budget')
        return SimpleNamespace(stdout='', returncode=0)
    monkeypatch.setattr(script, 'run', execute)
    with pytest.raises(TimeoutError):
        script.candidate_run('candidate', ['python', '-m', 'pytest'])
    assert calls[-1][:4] == ['docker', 'rm', '-f', calls[0][calls[0].index('--name') + 1]]


@pytest.mark.parametrize('gain', [False, True])
def test_no_gain_cannot_deploy_and_failed_deployment_restores_code(tmp_path, monkeypatch, gain):
    script = controller()
    source = 'def select_stack(text):\n    return "static"\n'
    target = tmp_path / script.ALLOWED
    target.parent.mkdir(parents=True)
    target.write_text(source, encoding='utf-8')
    before = {'passed': 1, 'total': 2, 'cases': [{'passed': True}, {'passed': False}]}
    after = {'passed': 2 if gain else 1, 'total': 2, 'cases': [{'passed': True}, {'passed': gain}]}
    proposal = {'path': script.ALLOWED, 'source': source + '# candidate\n'}
    def inside(code, data=None, **kwargs):
        if 'product_benchmark' in code:
            return json.dumps(before)
        if 'validate_proposal' in code:
            return 'VALID'
        if 'self_improvement import propose' in code:
            return json.dumps(proposal)
        return source
    commands = []
    def run(argv, **kwargs):
        commands.append(argv)
        output = 'sha256:baseline\n' if argv[:2] == ['docker', 'inspect'] else 'audit-commit\n'
        return SimpleNamespace(stdout=output, returncode=0)
    def candidate(image, command, **kwargs):
        return SimpleNamespace(stdout=json.dumps(after) if 'app.services.product_benchmark' in command else 'checks passed', returncode=0)
    health_calls = []
    def health(*args, **kwargs):
        health_calls.append(True)
        if len(health_calls) > 1:
            raise OSError('candidate readiness failed')
        return SimpleNamespace(read=lambda: b'{"status":"ok"}')
    monkeypatch.setattr(script, 'inside', inside)
    monkeypatch.setattr(script, 'run', run)
    monkeypatch.setattr(script, 'candidate_run', candidate)
    monkeypatch.setattr(script, 'activity', lambda: 0)
    monkeypatch.setattr(script.urllib.request, 'urlopen', health)
    monkeypatch.setattr(script.time, 'sleep', lambda seconds: None)
    if gain:
        with pytest.raises(RuntimeError, match='готовности'):
            script.cycle(tmp_path, apply=True, uid=1)
        assert target.read_text(encoding='utf-8') == source
        assert len([cmd for cmd in commands if cmd[:2] == ['docker', 'compose']]) == 2
        status = json.loads((tmp_path / 'data/autonomy/maintenance-status.json').read_text(encoding='utf-8'))
        assert status['rolled_back'] and status['status'] == 'error'
    else:
        assert script.cycle(tmp_path, apply=True, uid=1)['status'] == 'rejected'
        assert not any(cmd[:2] == ['docker', 'compose'] for cmd in commands)
