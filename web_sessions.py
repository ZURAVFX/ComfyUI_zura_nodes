"""Direct website sessions. No WebDriver, browser profiles or Codex credentials."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser

from .chatgpt_image import _interrupt

_locks = {name: threading.Lock() for name in ('gemini', 'chatgpt')}
_setup_locks = {name: threading.Lock() for name in ('gemini', 'chatgpt')}
_state_lock = threading.Lock()
_states = {}
_urls = {'gemini': 'https://gemini.google.com/app', 'chatgpt': 'https://chatgpt.com/auth/login'}
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


def _state(provider, state, message):
    with _state_lock:
        _states[provider] = {'state': state, 'message': message}


def login_status(provider):
    _provider(provider)
    with _state_lock:
        return dict(_states.get(provider, {'state': 'disconnected', 'message': 'Connect your signed-in Firefox session.'}))


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
                raise RuntimeError(f'{label} timed out. Check the conversation in Firefox before retrying to avoid a duplicate generation.')
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


def _open_default(provider):
    if os.name == 'nt':
        os.startfile(_urls[provider])
    else:
        webbrowser.open(_urls[provider])


def start_login(provider):
    _provider(provider)
    with _state_lock:
        if _states.get(provider, {}).get('state') in ('setting_up', 'signing_in', 'checking'):
            return
        _states[provider] = {'state': 'checking', 'message': 'Checking your existing Firefox session…'}

    def connect():
        label = _labels[provider]
        try:
            _state(provider, 'setting_up', 'Preparing the session client. First connection may take a minute…')
            _runtime(provider)
            opened = False
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                try:
                    with _locks[provider]:
                        _worker(provider, {'action': 'connect', 'timeout': 45})
                    _state(provider, 'connected', f'Your Firefox session was accepted by {label}. Reconnect after changing accounts.')
                    return
                except RuntimeError as exc:
                    if not opened:
                        _open_default(provider)
                        opened = True
                    _state(provider, 'signing_in', f'Sign in to {label} in your normal Firefox. Checking automatically. {exc}')
                    time.sleep(5)
            _state(provider, 'error', f'No usable {label} session found. Sign in in your normal Firefox, then reconnect.')
        except RuntimeError as exc:
            _state(provider, 'error', str(exc))
        except Exception:
            _state(provider, 'error', f'Could not connect the {label} session. Check your connection, then reconnect.')

    threading.Thread(target=connect, name=f'zura-{provider}-connect', daemon=True).start()


def generate_image(provider, prompt, paths, timeout):
    _provider(provider)
    with _locks[provider], tempfile.TemporaryDirectory(prefix=f'zura-{provider}-output-') as directory:
        try:
            result = _worker(provider, {'action': 'generate', 'prompt': prompt, 'paths': paths,
                              'timeout': timeout, 'output_dir': directory}, interrupt=True)
            path = Path(result['path']).resolve()
            if path.parent != Path(directory).resolve() or not path.is_file():
                raise RuntimeError(f'{_labels[provider]} returned an invalid output file.')
            image = path.read_bytes()
            _state(provider, 'connected', 'Generated using your existing Firefox session.')
            return image
        except RuntimeError as exc:
            authenticated = isinstance(exc, ProviderError) and exc.code in ('quota', 'limited', 'aborted', 'timeout', 'protocol', 'result')
            _state(provider, 'connected' if authenticated else 'error', str(exc))
            raise
