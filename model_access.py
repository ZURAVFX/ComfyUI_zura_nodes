"""Shared Hugging Face access for every Studio model installer.

Credentials stay on the ComfyUI server. Windows remembers them with DPAPI;
other platforms use an owner-only file. Browser cookies are never read.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
import re
import threading
import uuid
import time

# Public OAuth client registered for Zura Studio. This identifier is not a secret.
# It requests profile and approved public gated models, never private repositories.
HF_CLIENT_ID = '949d5cc3-d65d-4529-a0c4-92d61f970044'


def _protect(data, decrypt=False):
    if os.name != 'nt':
        return data
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]
    buffer = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    outgoing = Blob()
    api = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    # CRYPTPROTECT_UI_FORBIDDEN: background requests must never open a prompt.
    if not api(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise OSError('Could not protect the local model credential.')
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.data)


class ModelAccess:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.token = None
        self.name = ''
        self.remembered = False
        self.ignore_cached = False
        self.browser_login = None
        self.expires = None
        try:
            if self.path.stat().st_size > 32768:
                return
            saved = json.loads(_protect(base64.b64decode(self.path.read_bytes()), decrypt=True))
            if isinstance(saved.get('token'), str) and re.fullmatch(r'[A-Za-z0-9._~+/=\-]{6,4096}', saved['token']):
                self.token, self.name, self.remembered = saved['token'], str(saved.get('name', ''))[:128], True
                self.expires = float(saved['expires']) if saved.get('expires') is not None else None
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def credential(self):
        with self.lock:
            if self.expires is not None and time.time() >= self.expires:
                self.token, self.name, self.remembered, self.ignore_cached = None, '', False, True
            if self.token:
                return self.token
            if self.ignore_cached:
                return None
        try:
            from huggingface_hub import get_token
            return get_token()
        except (ImportError, OSError):
            return None

    def status(self):
        with self.lock:
            return dict(connected=bool(self.credential()), name=self.name, browser_signin_available=True,
                        remembered=self.remembered, cached=not self.token and bool(self.credential()))

    def connect(self, token, remember=False):
        import requests
        if not isinstance(token, str) or not re.fullmatch(r'hf_[A-Za-z0-9_\-]{6,500}', token.strip()):
            raise ValueError('Paste a Hugging Face read token. Create one using the link above.')
        if not isinstance(remember, bool):
            raise ValueError('Choose whether to remember this connection.')
        return self._connect(token.strip(), remember)

    def _connect(self, token, remember=False, expires=None):
        import requests
        # Browser OAuth tokens are opaque; verify against HF before trusting or saving.
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9._~+/=\-]{6,4096}', token):
            raise ValueError('Hugging Face returned an invalid connection. Sign in again.')
        try:
            reply = requests.get('https://huggingface.co/api/whoami-v2',
                                 headers={'Authorization': 'Bearer ' + token}, timeout=(10, 20))
            if reply.status_code in (401, 403):
                raise ValueError('Hugging Face did not accept this token. Check it is active and has read access to public gated models.')
            reply.raise_for_status()
            name = reply.json().get('name')
            if not isinstance(name, str) or not name:
                raise ValueError('Could not verify this Hugging Face account. Try connecting again.')
        except (requests.RequestException, json.JSONDecodeError):
            raise ValueError('Could not reach Hugging Face. Check the connection and try again.') from None
        with self.lock:
            if remember:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_name('.hf-access-' + uuid.uuid4().hex)
                try:
                    data = base64.b64encode(_protect(json.dumps(dict(token=token, name=name, expires=expires)).encode('utf-8')))
                    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, 'wb') as file:
                        file.write(data)
                    os.replace(temporary, self.path)
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                self.path.unlink(missing_ok=True)
            self.token, self.name, self.remembered, self.ignore_cached = token, name[:128], remember, False
            self.expires = expires
        return self.status()

    def disconnect(self):
        with self.lock:
            self.browser_login = None
            self.expires = None
            self.path.unlink(missing_ok=True)
            self.token, self.name, self.remembered, self.ignore_cached = None, '', False, True
        return self.status()

    def browser_start(self, remember=False):
        import requests
        if not isinstance(remember, bool):
            raise ValueError('Choose whether to remember this connection.')
        try:
            reply = requests.post('https://huggingface.co/oauth/device', data={
                'client_id': HF_CLIENT_ID, 'scope': 'openid profile gated-repos'}, timeout=(10, 20))
            reply.raise_for_status()
            data = reply.json()
            from urllib.parse import urlparse
            url = data.get('verification_uri_complete') or data['verification_uri']
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.netloc != 'huggingface.co':
                raise ValueError('Unexpected sign-in destination.')
            interval = max(5, int(data.get('interval', 5)))
            session = dict(id=uuid.uuid4().hex, device=data['device_code'],
                           expires=time.monotonic()+min(1800, int(data['expires_in'])),
                           interval=interval, next_poll=0, remember=remember)
            with self.lock:
                self.browser_login = session
            return dict(id=session['id'], url=url, code=data.get('user_code', ''), interval=interval)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            raise ValueError('Could not open Hugging Face sign-in. Try again shortly.') from None

    def browser_poll(self, login_id, cancel=False):
        import requests
        with self.lock:
            session = self.browser_login
            if not session or session['id'] != login_id:
                raise ValueError('This sign-in has ended. Open browser sign-in again.')
            if cancel:
                self.browser_login = None
                return dict(phase='cancelled')
            if time.monotonic() >= session['expires']:
                self.browser_login = None
                raise ValueError('Sign-in expired. Open browser sign-in again.')
            if time.monotonic() < session['next_poll']:
                return dict(phase='waiting', interval=session['interval'])
            session['next_poll'] = time.monotonic()+session['interval']
        try:
            reply = requests.post('https://huggingface.co/oauth/token', data={
                'client_id': HF_CLIENT_ID, 'device_code': session['device'],
                'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'}, timeout=(10, 20))
            data = reply.json()
            error = data.get('error')
            if error in ('authorization_pending', 'slow_down'):
                if error == 'slow_down':
                    session['interval'] += 5
                    session['next_poll'] = time.monotonic()+session['interval']
                return dict(phase='waiting', interval=session['interval'])
            if error:
                with self.lock:
                    if self.browser_login is session:
                        self.browser_login = None
                raise ValueError('Sign-in was declined or expired. Open browser sign-in to try again.')
            reply.raise_for_status()
            with self.lock:
                if self.browser_login is not session:
                    raise ValueError('This sign-in has been cancelled.')
                expires = time.time()+max(0, float(data['expires_in'])-30) if data.get('expires_in') is not None else None
                state = self._connect(data['access_token'], session['remember'], expires)
                self.browser_login = None
            return dict(phase='connected', **state)
        except (requests.RequestException, json.JSONDecodeError, KeyError, TypeError):
            raise ValueError('Could not finish Hugging Face sign-in. Try again.') from None


_access = None
_access_lock = threading.Lock()


def access():
    global _access
    with _access_lock:
        if _access is None:
            import folder_paths
            user = folder_paths.get_user_directory() if hasattr(folder_paths, 'get_user_directory') else Path(folder_paths.models_dir).parent / 'user'
            _access = ModelAccess(Path(user) / 'zura' / 'huggingface-access')
        return _access


def credential():
    return access().credential()


def check_files(requested, catalogs, token=None):
    """Check pinned gated files without downloading bytes or accepting terms."""
    import requests
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import quote
    keys = ('repo', 'revision', 'remote_path')
    allowed = {tuple(file.get(key) for key in keys)
               for catalog in catalogs for recipe in catalog.values() for file in recipe['files']}
    if (not isinstance(requested, list) or not 1 <= len(requested) <= 100
            or any(not isinstance(file, dict) or set(file) != set(keys)
                   or not all(isinstance(file.get(key), str) for key in keys)
                   or tuple(file[key] for key in keys) not in allowed for file in requested)):
        raise ValueError('Choose files from Studio’s model setup list.')
    selected = list(dict.fromkeys(tuple(file[key] for key in keys) for file in requested))
    def check(item):
        repo, revision, path = item
        try:
            # Do not follow CDN redirects or forward credentials to another host.
            reply = requests.head('https://huggingface.co/' + repo + '/resolve/' + revision + '/' + quote(path, safe='/'),
                                  headers={'Authorization': 'Bearer ' + token} if token else {},
                                  allow_redirects=False, timeout=(10, 15))
            try:
                code = reply.status_code
                if code in (200, 206, 302, 303, 307, 308):
                    return {'repo': repo, 'status': 'ready'}
                if code in (401, 403):
                    return {'repo': repo, 'status': 'access_required'}
                return {'repo': repo, 'status': 'unavailable' if code == 404 else 'retry'}
            finally:
                reply.close()
        except requests.RequestException:
            return {'repo': repo, 'status': 'retry'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        checks = list(pool.map(check, selected))
    blocked = list(dict.fromkeys(item['repo'] for item in checks if item['status'] == 'access_required'))
    return {'allowed': all(item['status'] == 'ready' for item in checks), 'checks': checks,
            'auth_required': bool(blocked), 'access_repos': blocked,
            'access_repo': blocked[0] if blocked else '',
            'access_reason': 'terms_or_permissions' if token else 'connect'}


def register(routes, response, catalog=None):
    # Each installer contributes its allowlist without importing other runtimes.
    catalogs = getattr(routes, '_zura_model_catalogs', None)
    if catalogs is None:
        catalogs = []
        routes._zura_model_catalogs = catalogs
    if catalog is not None and all(item is not catalog for item in catalogs):
        catalogs.append(catalog)
    if getattr(routes, '_zura_model_access', False):
        return
    routes._zura_model_access = True
    from aiohttp import web
    from .media_source import require_same_origin

    async def handle(request):
        require_same_origin(request)
        try:
            manager = access()
            if request.method == 'GET':
                result = await asyncio.to_thread(manager.status)
            else:
                data = await request.json()
                if not isinstance(data, dict):
                    raise ValueError('Choose a Hugging Face connection action.')
                if data == {'disconnect': True}:
                    result = await asyncio.to_thread(manager.disconnect)
                elif data.get('action') == 'check_files' and set(data) == {'action', 'files'}:
                    result = await asyncio.to_thread(check_files, data['files'],
                                                     catalogs, manager.credential())
                elif data.get('action') == 'browser_start' and set(data) <= {'action', 'remember'}:
                    result = await asyncio.to_thread(manager.browser_start, data.get('remember', False))
                elif data.get('action') in ('browser_poll', 'browser_cancel') and set(data) == {'action', 'id'}:
                    result = await asyncio.to_thread(manager.browser_poll, data['id'], data['action'] == 'browser_cancel')
                elif set(data) <= {'token', 'remember'} and 'token' in data:
                    result = await asyncio.to_thread(manager.connect, data['token'], data.get('remember', False))
                else:
                    raise ValueError('Choose a Hugging Face connection action.')
            return web.json_response(result, headers={'Cache-Control': 'no-store'})
        except (ValueError, OSError) as error:
            message = str(error) if isinstance(error, ValueError) else 'Could not save the connection. Uncheck Remember and try again.'
            return web.json_response({'error': message}, status=400, headers={'Cache-Control': 'no-store'})

    for prefix in ('/zura/studio', '/genj/studio'):
        routes.get(prefix + '/model-access')(response(handle))
        routes.post(prefix + '/model-access')(response(handle))
