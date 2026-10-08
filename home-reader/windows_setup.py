"""Per-user EXE installation; no admin, shell scripts or global Python changes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import winreg

NAME = 'BitThinkHomeReader'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def launch(directory):
    flag = directory / 'stop.flag'
    if flag.exists():
        flag.unlink()
    subprocess.Popen(
        [str(directory / (NAME + '.exe')), '--worker', '--config', str(directory / 'config.json')],
        cwd=str(directory), creationflags=subprocess.CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'},
    )


def setup_main():
    directory = Path(os.environ['LOCALAPPDATA']) / NAME
    action = next((arg for arg in sys.argv[1:] if arg in ('--start', '--stop', '--status', '--uninstall', '--install-browser')), '--install')
    try:
        if action == '--install-browser':
            from playwright.__main__ import main
            sys.argv = ['playwright', 'install', 'chromium']
            main()
            return
        if action in ('--stop', '--uninstall'):
            if directory.exists():
                (directory / 'stop.flag').write_text('stop')
            if action == '--uninstall':
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                    try:
                        winreg.DeleteValue(key, NAME)
                    except FileNotFoundError:
                        pass
            print('Читатель остановлен.' if action == '--stop' else 'Автозапуск отключён. Профиль и журнал сохранены.')
            return
        if action == '--start':
            launch(directory)
            print('Читатель запущен. Через несколько секунд проверь STATUS.bat.')
            return
        if action == '--status':
            config = json.loads((directory / 'config.json').read_text(encoding='utf-8-sig'))
            try:
                request = urllib.request.Request(config['server_url'] + '/api/marketplace-relay/status', headers={'Authorization': 'Bearer ' + config['token']})
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=15) as response:
                    status = json.load(response)
                print('HOME READER ONLINE' if status['online'] else 'HOME READER OFFLINE')
                print('Страниц в очереди:', status['pending'])
            except Exception as exc:
                print('Не удалось проверить подключение:', type(exc).__name__)
            log = directory / 'agent.log'
            if log.exists():
                print('\n'.join(log.read_text(encoding='utf-8').splitlines()[-15:]))
            return
        source = Path(sys.executable).resolve()
        source_config = source.with_name('config.json')
        config = json.loads(source_config.read_text(encoding='utf-8-sig'))
        if config.get('server_url') != 'https://bit-think.space' or len(config.get('token', '')) < 32:
            raise ValueError('Invalid installation config')
        directory.mkdir(parents=True, exist_ok=True)
        # Protect the dedicated profile, token and logs with per-user ACLs.
        sid = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'], encoding='utf-8', errors='replace').strip().split(',')[-1].strip('"')
        subprocess.run(['icacls', str(directory), '/inheritance:r', '/grant:r', f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F', '/Q'], check=True, capture_output=True)
        (directory / 'stop.flag').write_text('stop')
        target = directory / (NAME + '.exe')
        if target.exists():
            time.sleep(5)
        if source != target.resolve():
            shutil.copy2(source, target)
        if source_config.resolve() != (directory / 'config.json').resolve():
            shutil.copy2(source_config, directory / 'config.json')
        from agent import browser_channel
        if not browser_channel():
            print('Chrome/Edge не найден. Загружаю отдельный Chromium...')
            subprocess.run([str(target), '--install-browser'], check=True)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, f'"{target}" --start')
        launch(directory)
        print('Установлено. Читатель будет запускаться после входа в Windows.')
        print('Через 10–20 секунд запусти STATUS.bat: ожидается HOME READER ONLINE.')
        print('Маркетплейсы должны открываться через Smart Telecom напрямую.')
        print('Если площадка попросит капчу, открой отдельное окно браузера на панели задач.')
        print('Папка программы:', directory)
    except Exception as exc:
        print('Операция не выполнена:', type(exc).__name__)
        print('Убедись, что ZIP полностью распакован и config.json находится рядом с INSTALL.exe.')
        raise SystemExit(1)
    finally:
        if action == '--install' and sys.stdin and sys.stdin.isatty():
            input('Нажми Enter, чтобы закрыть установщик...')
