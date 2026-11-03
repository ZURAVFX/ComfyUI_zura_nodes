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
        try:
            if self.path.stat().st_size > 32768:
                return
            saved = json.loads(_protect(base64.b64decode(self.path.read_bytes()), decrypt=True))
            if re.fullmatch(r'hf_[A-Za-z0-9_\-]+', saved['token']):
                self.token, self.name, self.remembered = saved['token'], str(saved.get('name', ''))[:128], True
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def credential(self):
        with self.lock:
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
            return dict(connected=bool(self.credential()), name=self.name,
                        remembered=self.remembered, cached=not self.token and bool(self.credential()))

    def connect(self, token, remember=False):
        import requests
        if not isinstance(token, str) or not re.fullmatch(r'hf_[A-Za-z0-9_\-]{6,500}', token.strip()):
            raise ValueError('Paste a Hugging Face read token. Create one using the link above.')
        if not isinstance(remember, bool):
            raise ValueError('Choose whether to remember this connection.')
        token = token.strip()
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
                    data = base64.b64encode(_protect(json.dumps(dict(token=token, name=name)).encode('utf-8')))
                    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, 'wb') as file:
                        file.write(data)
                    os.replace(temporary, self.path)
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                self.path.unlink(missing_ok=True)
            self.token, self.name, self.remembered, self.ignore_cached = token, name[:128], remember, False
        return self.status()

    def disconnect(self):
        with self.lock:
            self.path.unlink(missing_ok=True)
            self.token, self.name, self.remembered, self.ignore_cached = None, '', False, True
        return self.status()


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


def register(routes, response):
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
