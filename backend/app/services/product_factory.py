"""Product lifecycle executed only inside the isolated workspace service.

Receipts live outside user roots. Generated programs cannot edit their own gates.
Stdlib only: this module is also shipped in the sandbox image.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

try:
    import workspace_fs as fs
    from product_strategy import STACKS, select_stack
except ImportError:
    from app.services import workspace_fs as fs
    from app.services.product_strategy import STACKS, select_stack

MAX_FILES = 600
MAX_BYTES = 35 * 1024 * 1024
SKIP = {'.git', '.venv', '.tmp', '__pycache__', 'node_modules', 'dist', 'build', '.next', '.astro', '.pytest_cache', '.cache', 'coverage', 'test-results'}
_ID = re.compile(r'^[0-9a-f]{24}$')


def _control(uid):
    path = fs.workspaces_root() / '.product-control' / f'u{int(uid)}'
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _state_path(uid, pid):
    if not _ID.fullmatch(str(pid)):
        raise ValueError('Неверный product_id.')
    return _control(uid) / (pid + '.json')


def _save(path, value):
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='receipt-')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextlib.contextmanager
def _lock(path):
    # Sandbox is Linux. File locks also fence separate API processes.
    with path.with_suffix('.lock').open('a+b') as stream:
        if os.name == 'posix':
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'posix':
                fcntl.flock(stream, fcntl.LOCK_UN)


def _files(root):
    result, size = [], 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        if any((Path(directory) / name).is_symlink() for name in dirs):
            raise ValueError('Симлинки в продукте запрещены.')
        dirs[:] = sorted(name for name in dirs if name not in SKIP and not name.startswith('.') and not (Path(directory) / name).is_symlink())
        for name in sorted(names):
            path = Path(directory) / name
            if path.relative_to(root).as_posix() in {'qa/desktop.png', 'qa/mobile.png'}:
                continue
            if name.startswith('.') or path.suffix == '.zip':
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('Симлинки в продукте запрещены.')
            size += path.stat().st_size
            if len(result) >= MAX_FILES or size > MAX_BYTES:
                raise ValueError('Продукт превышает лимит исходников (600 файлов / 35 МБ).')
            result.append(path)
    return sorted(result)


def _revision(root):
    digest = hashlib.sha256()
    for path in _files(root):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b'\0')
        digest.update(path.read_bytes())
        digest.update(b'\0')
    return digest.hexdigest()


def _public(state, root):
    revision = _revision(root)
    required = ('build', 'test') if state['stack'] == 'python' else ('build', 'test', 'smoke')
    gates = {name: bool((state.get('checks', {}).get(name) or {}).get('passed') and
                       state['checks'][name].get('revision') == revision) for name in required}
    if state.get('archive') and state.get('packaged_revision') != revision:
        (root.parent.parent / state['archive']).unlink(missing_ok=True)
    return {**state, 'revision': revision, 'gates': gates,
            'ready': all(gates.values()),
            'packaged': state.get('packaged_revision') == revision and bool(state.get('archive')) and (root.parent.parent / state['archive']).is_file()}


def _command(uid, root, argv, timeout=90, process_limit=64):
    if os.environ.get('WORKSPACE_ALLOW_LOCAL_RUN') != '1' and os.environ.get('SANDBOX_MODE') != '1':
        raise ValueError('Сборка запускается только в изолированной песочнице.')
    if os.name != 'posix' and os.environ.get('SANDBOX_MODE') == '1':
        raise ValueError('Для сборки нужна Linux-песочница с изоляцией файлов.')
    home = fs.user_root(uid)
    temporary = home / '.tmp'
    temporary.mkdir(exist_ok=True)
    env = {'HOME': str(home), 'PATH': str(Path(fs._python_bin(home)).parent) + os.pathsep + os.defpath + os.pathsep + '/usr/local/bin',
           'LANG': 'C.UTF-8', 'TMPDIR': str(temporary), 'CI': 'true', 'NO_COLOR': '1',
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
           'npm_config_cache': str(temporary / 'npm-cache'), 'npm_config_update_notifier': 'false',
           'NODE_OPTIONS': '--max-old-space-size=512'}
    env.update(GOMAXPROCS='2', UV_THREADPOOL_SIZE='2', NEXT_TELEMETRY_DISABLED='1')
    # No application secrets, proxy credentials, sandbox token or database URL.
    started = time.monotonic()
    with tempfile.TemporaryFile() as output:
        try:
            child = subprocess.Popen(argv, cwd=root, env=env, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, start_new_session=os.name == 'posix',
                preexec_fn=(lambda: fs._prepare_child(uid, timeout, False, process_limit)) if os.name == 'posix' else None)
            try:
                code = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == 'posix':
                    os.killpg(child.pid, signal.SIGKILL)
                else:
                    child.kill()
                child.wait()
                code = 124
            # Kill leftover watchers and servers after a check completes.
            if os.name == 'posix':
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except OSError as exc:
            code = 127
            output.write(str(exc).encode())
        output.seek(0, 2)
        output.seek(max(0, output.tell() - 8000))
        log = output.read(8000).decode('utf-8', 'replace')
    return {'exit_code': code, 'passed': code == 0, 'seconds': round(time.monotonic() - started, 2),
            'command': argv, 'output': log}


def _static_build(root):
    from html.parser import HTMLParser
    from urllib.parse import unquote, urlsplit
    problems = []

    class Page(HTMLParser):
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            for key in ('src', 'href'):
                value = values.get(key) or ''
                parts = urlsplit(value)
                if not value or value.startswith('#') or parts.scheme or parts.netloc:
                    continue
                target = (self.base / unquote(parts.path).lstrip('/')).resolve() if not value.startswith('/') else (root / unquote(parts.path).lstrip('/')).resolve()
                if not target.is_relative_to(root.resolve()) or not target.exists():
                    problems.append(str(value))

    pages = list(root.rglob('*.html'))
    if not (root / 'index.html').is_file():
        problems.append('index.html отсутствует')
    for path in pages[:100]:
        parser = Page()
        parser.base = path.parent
        parser.feed(path.read_text(encoding='utf-8'))
    return {'exit_code': int(bool(problems)), 'passed': not problems,
            'command': ['static-html-assets-check'], 'output': '\n'.join(problems) or f'HTML и локальные ресурсы: {len(pages)} страниц.'}


def operate(uid, args):
    """No arbitrary argv or cwd from the model; only explicit lifecycle operations."""
    uid = int(uid)
    fs.user_root(uid)  # Validate account before creating control paths.
    if fs._dir_size(fs.user_root(uid)) > fs.QUOTA_BYTES:
        raise ValueError('Квота рабочего пространства исчерпана; удали ненужные файлы.')
    action = str(args.get('action') or 'status')
    if action == 'start':
        brief = str(args.get('brief') or '').strip()[:16000]
        if not brief:
            raise ValueError('Нужно описание продукта.')
        stack = str(args.get('stack') or select_stack(brief))
        if stack not in STACKS:
            raise ValueError('Поддерживаемые стеки: ' + ', '.join(STACKS))
        pid = uuid.uuid4().hex[:24]
        root = fs.resolve_in_jail(uid, 'products/' + pid)
        root.mkdir(parents=True)
        state = {'product_id': pid, 'path': 'products/' + pid, 'stack': stack,
                 'stack_reason': str(args.get('reason') or STACKS[stack])[:1000],
                 'brief': brief, 'created_at': int(time.time()), 'checks': {}, 'attempts': 0}
        _save(_state_path(uid, pid), state)
        return {**_public(state, root), 'next': 'Запиши BRIEF.md с критериями приёмки, REFERENCES.md с наблюдениями и ссылками, README.md с запуском. Затем исходники и тесты. product_lifecycle install/build/test/smoke/package. Для Python smoke заменяется интеграционными тестами.'}
    path = _state_path(uid, args.get('product_id', ''))
    with _lock(path):
        if not path.is_file():
            raise ValueError('Продукт не найден у этого пользователя.')
        state = json.loads(path.read_text(encoding='utf-8'))
        root = fs.resolve_in_jail(uid, state['path'])
        if action == 'status':
            return _public(state, root)
        if action == 'revise':
            brief = str(args.get('brief') or '').strip()[:16000]
            if not brief:
                raise ValueError('Нужно новое описание требований.')
            state.update(brief=brief, checks={})
            state.pop('packaged_revision', None)
            _save(path, state)
            return {**_public(state, root), 'next': 'Обнови BRIEF.md и исходники по новым требованиям; повтори все проверки.'}
        if action not in {'install', 'build', 'test', 'smoke', 'package'}:
            raise ValueError('Неизвестный этап продукта.')
        for name in ('BRIEF.md', 'README.md'):
            if not (root / name).is_file() or (root / name).stat().st_size < 30:
                raise ValueError('Сначала запиши ' + name + ' с требованиями/запуском.')
        before = _revision(root)
        if action == 'package':
            if not _public(state, root)['ready']:
                raise ValueError('Архив готового продукта требует успешной сборки, тестов и браузерной проверки (для веба) текущих исходников.')
            archive = fs.resolve_in_jail(uid, 'product-' + state['product_id'] + '.zip')
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as target:
                for source in _files(root):
                    target.write(source, source.relative_to(root).as_posix())
                for name in ('desktop.png', 'mobile.png'):
                    image = root / 'qa' / name
                    if image.is_file() and not image.is_symlink() and image.stat().st_size <= 2 * 1024 * 1024:
                        target.write(image, 'qa/' + name)
                target.writestr('BITTHINK_CHECKS.json', json.dumps(state['checks'], ensure_ascii=False))
            if _revision(root) != before:
                archive.unlink(missing_ok=True)
                raise ValueError('Исходники изменились во время упаковки. Повтори проверки.')
            if archive.stat().st_size > fs.MAX_FILE_BYTES:
                archive.unlink(missing_ok=True)
                raise ValueError('Архив больше лимита вложения 8 МБ. Убери тяжёлые медиа из исходников и повтори проверки.')
            state.update(archive=archive.name, packaged_revision=before)
            _save(path, state)
            return _public(state, root)
        if state['attempts'] >= 24:
            raise ValueError('Лимит сборок продукта исчерпан. Сохрани исходники и причину остановки.')
        state['attempts'] += 1
        _save(path, state)
        python = fs._python_bin(fs.user_root(uid))
        stack = state['stack']
        if action == 'install':
            if stack == 'python':
                raise ValueError('Для Python используй pip_install с именами нужных пакетов; requirements.txt положи в проект.')
            if stack == 'static':
                return {**_public(state, root), 'note': 'Статическому сайту зависимости не нужны.'}
            if not (root / 'package.json').is_file():
                raise ValueError('Нужен package.json с build и test.')
            argv = ['npm', 'ci' if (root / 'package-lock.json').is_file() else 'install', '--ignore-scripts', '--no-audit', '--no-fund']
        elif action == 'smoke':
            if stack == 'python':
                raise ValueError('Для Python выполни интеграционные тесты через test.')
            if not _public(state, root)['gates']['build']:
                raise ValueError('Перед браузерной проверкой нужна успешная сборка текущих исходников.')
            argv = ['node', '/usr/local/lib/bitthink/product_smoke.cjs', str(root), stack]
        elif action == 'build' and stack == 'static':
            check = _static_build(root)
            argv = None
        elif action == 'build':
            argv = [python, '-m', 'compileall', '-q', '.'] if stack == 'python' else ['npm', 'run', 'build']
        else:
            tests = [source for source in _files(root) if source.name.startswith('test_') or '.test.' in source.name or '.spec.' in source.name]
            if not tests:
                raise ValueError('Нужны реальные тесты ключевого пользовательского сценария (test_*, *.test.*, *.spec.*).')
            argv = [python, '-m', 'unittest', 'discover', '-s', 'tests', '-v'] if stack == 'python' else ['node', '--test'] if stack == 'static' else ['npm', 'run', 'test']
        if argv:
            check = _command(uid, root, argv, 160 if action == 'install' else 90, process_limit=192)
        if action == 'test' and state['stack'] == 'python' and re.search(r'Ran 0 tests', check['output']):
            check.update(passed=False, output=check['output'] + '\nНе выполнено ни одного теста.')
        if action == 'test' and re.search(r'(?m)^# tests 0\s*$', check['output']):
            check.update(passed=False, output=check['output'] + '\nНе выполнено ни одного теста.')
        after = _revision(root)
        # A check that rewrites sources is never evidence for their final revision.
        check.update(revision=before, checked_at=int(time.time()))
        if action != 'install' and after != before:
            check.update(passed=False, output=check['output'] + '\nИсходники изменились во время проверки; повтори её.')
        state['checks'][action] = check
        state.pop('packaged_revision', None)
        _save(path, state)
        return {**_public(state, root), 'last_check': check}


def dispatch(uid, args):
    try:
        return json.dumps(operate(uid, args), ensure_ascii=False)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        return json.dumps({'error': str(exc)[:1000], 'ready': False}, ensure_ascii=False)
