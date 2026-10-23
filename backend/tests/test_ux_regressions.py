from types import SimpleNamespace

from app.services import workspace_fs


def test_requested_isolation_never_silently_runs_without_posix(monkeypatch):
    monkeypatch.setattr(workspace_fs, "os", SimpleNamespace(
        name="nt", environ={"WORKSPACE_ALLOW_LOCAL_RUN": "1", "WORKSPACE_LANDLOCK": "1"},
    ))

    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("Unconfined process must not start")

    monkeypatch.setattr(workspace_fs.subprocess, "run", unexpected_run)
    result = workspace_fs._run_cmd(42, ["python", "untrusted.py"], 1)
    assert result.startswith("Запуск остановлен:")
