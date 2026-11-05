"""Direct website clients with explicit, provider-scoped browser connections."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from .chatgpt_image import _interrupt
from . import browser_sessions as browsers

_locks = {name: threading.Lock() for name in ('gemini', 'chatgpt')}
_setup_locks = {name: threading.Lock() for name in ('gemini', 'chatgpt')}
_state_lock = threading.Lock()
_states = {}
_attempts = {}
_cookies = {}
_selected = {}
_labels = {'gemini': 'Gemini', 'chatgpt': 'ChatGPT'}
_requirements = {
    'gemini': ('gemini-webapi-2.1.1', ['gemini-webapi==2.1.1']),
    'chatgpt': ('g4f-91d9c821', [
        'https://github.com/xtekky/gpt4free/archive/91d9c82150b8d5032a0400591872cfc816cfa9af.tar.gz#sha256=9aed0c68acd3673b41cf95014e31510d97710d8694e2646bf0e94c77237bb6d4',
        'curl-cffi==0.17.0', 'pillow==13.0.0', 'platformdirs==4.14.0',
    ]),
}
_root = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.local/share') / 'ZuraNodes'


class ProviderError(RuntimeError):
    def __init__(self, message, code='request'):
        super().__init__(message)
        self.code = code


def _provider(provider):
    if provider not in _locks:
        raise ValueError('Unknown image provider.')


def _state(provider, state, message, attempt=None):
    with _state_lock:
        if attempt is not None and _attempts.get(provider) is not attempt:
            return False
        _states[provider] = {'state': state, 'message': message}
        return True


def login_status(provider):
    _provider(provider)
    with _state_lock:
        result = dict(_states.get(provider, {'state': 'disconnected', 'message': 'Choose a browser, then connect your website account.'}))
        result['browser'] = _selected.get(provider, '')
    result['browsers'] = browsers.available_browsers()
    return result


def _runtime(provider):
    name, requirements = _requirements[provider]
    directory = _root / 'runtimes' / f'{name}-py{sys.version_info.major}{sys.version_info.minor}'
    python = directory / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    ready = directory / '.zura-ready'
    with _setup_locks[provider]:
        if ready.exists() and python.exists():
            return python
        directory.parent.mkdir(parents=True, exist_ok=True)
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        for command in (
            [sys.executable, '-m', 'venv', str(directory)],
            [str(python), '-m', 'pip', 'install', '--disable-pip-version-check', *requirements],
        ):
            try:
                subprocess.run(command, check=True, timeout=300, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=flags)
            except (OSError, subprocess.SubprocessError):
                raise RuntimeError(f'Could not set up the {_labels[provider]} session client. Check your internet connection and reconnect.') from None
        ready.touch()
    return python


def _worker(provider, request, *, interrupt=False):
    python = _runtime(provider)
    label = _labels[provider]
    env = dict(os.environ)
    env['GEMINI_COOKIE_PATH'] = str(_root / 'sessions' / 'gemini')
    env['PYTHONIOENCODING'] = 'utf-8'
    script = Path(__file__).with_name(f'{provider}_session_worker.py')
    deadline = time.monotonic() + request.get('timeout', 60) + 10
    process = subprocess.Popen([str(python), str(script)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, encoding='utf-8', env=env,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    payload = json.dumps(request)
    try:
        while True:
            if interrupt:
                _interrupt()
            if time.monotonic() >= deadline:
                raise RuntimeError(f'{label} timed out. Check the conversation in your selected browser before retrying to avoid a duplicate generation.')
            try:
                output, _ = process.communicate(input=payload, timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                payload = None
        try:
            result = json.loads(output)
        except (ValueError, TypeError):
            raise RuntimeError(f'The {label} session client stopped unexpectedly. Reconnect and try again.') from None
        if process.returncode or not result.get('ok'):
            raise ProviderError(result.get('error') or f'The {label} session client stopped unexpectedly.', result.get('code', 'request'))
        return result
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def start_login(provider, browser=None):
    _provider(provider)
    choices = browsers.available_browsers()
    browser = browser or _selected.get(provider) or (choices[0]['id'] if choices else '')
    if not isinstance(browser, str) or browser not in {item['id'] for item in choices}:
        raise ValueError('Choose a browser installed on the computer running ComfyUI. Safari is available on macOS.')
    attempt = threading.Event()
    with _state_lock:
        old = _attempts.get(provider)
        if old:
            old.set()
        _attempts[provider] = attempt
        _selected[provider] = browser
        _cookies.pop(provider, None)
        _states[provider] = {'state': 'checking', 'message': f'Connecting with {browsers.LABELS[browser]}…'}

    def connect():
        label = _labels[provider]
        try:
            if not _state(provider, 'setting_up', 'Preparing the session client. First connection may take a minute…', attempt):
                return
            _runtime(provider)
            if attempt.is_set():
                return
            browsers.open_browser(provider, browser, _root)
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline and not attempt.is_set():
                try:
                    cookies = browsers.read_cookies(provider, browser)
                    with _locks[provider]:
                        if attempt.is_set():
                            return
                        _worker(provider, {'action': 'connect', 'cookies': cookies, 'timeout': 45})
                    with _state_lock:
                        if _attempts.get(provider) is not attempt or attempt.is_set():
                            return
                        _cookies[provider] = cookies
                        _states[provider] = {'state': 'connected', 'message': f'{label} connected through {browsers.LABELS[browser]}. You can close the sign-in window. Reconnect to change accounts.'}
                    return
                except RuntimeError as exc:
                    _state(provider, 'signing_in', f'{browsers.LABELS[browser]}: {exc} Checking automatically.', attempt)
                    attempt.wait(5)
            _state(provider, 'error', f'No usable {label} session found. Reconnect and sign in using the selected browser.', attempt)
        except RuntimeError as exc:
            _state(provider, 'error', str(exc), attempt)
        except Exception:
            _state(provider, 'error', f'Could not connect the {label} session. Check your connection, then reconnect.', attempt)

    threading.Thread(target=connect, name=f'zura-{provider}-connect', daemon=True).start()


def cancel_login(provider):
    _provider(provider)
    with _state_lock:
        attempt = _attempts.pop(provider, None)
        if attempt:
            attempt.set()
        _cookies.pop(provider, None)
        _states[provider] = {'state': 'disconnected', 'message': 'Connection cancelled. Choose a browser and sign in when ready.'}


def generate_image(provider, prompt, paths, timeout):
    _provider(provider)
    with _locks[provider], tempfile.TemporaryDirectory(prefix=f'zura-{provider}-output-') as directory:
        try:
            with _state_lock:
                cookies = dict(_cookies.get(provider, {}))
                attempt = _attempts.get(provider)
            if not cookies:
                raise ProviderError(f'Connect {_labels[provider]} using the browser selector before generating.', 'auth')
            result = _worker(provider, {'action': 'generate', 'prompt': prompt, 'paths': paths,
                              'cookies': cookies, 'timeout': timeout, 'output_dir': directory}, interrupt=True)
            path = Path(result['path']).resolve()
            if path.parent != Path(directory).resolve() or not path.is_file():
                raise RuntimeError(f'{_labels[provider]} returned an invalid output file.')
            image = path.read_bytes()
            _state(provider, 'connected', f'Generated using your connected {_labels[provider]} account.', attempt)
            return image
        except RuntimeError as exc:
            authenticated = isinstance(exc, ProviderError) and exc.code in ('quota', 'limited', 'aborted', 'timeout', 'protocol', 'result')
            _state(provider, 'connected' if authenticated else 'error', str(exc), attempt)
            raise
