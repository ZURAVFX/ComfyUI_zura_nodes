"""Regression checks for session selection, credential scope and worker cleanup."""
import importlib.util
import contextlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parent
if not (SOURCE / 'web_sessions.py').exists():
    SOURCE = SOURCE.parent
sys.path.insert(0, str(SOURCE))

import browser_sessions as browsers
import gemini_session_worker as gemini
import chatgpt_session_worker as chatgpt


class SessionTests(unittest.TestCase):
    def test_generation_abort_is_not_reported_as_expired_login(self):
        APIError = type('APIError', (Exception,), {})
        code, message = gemini.safe_failure(APIError('The original request may have been silently aborted by Google.'), 'generating')
        self.assertEqual(code, 'aborted')
        self.assertNotIn('reconnect', message)
        self.assertIn('sign-in was accepted', message)

    def test_unknown_failure_does_not_leak_upstream_payload(self):
        _, message = gemini.safe_failure(ValueError('cookie=do-not-expose-this'), 'generating')
        self.assertNotIn('do-not-expose-this', message)

    def test_gemini_cache_name_never_contains_the_cookie(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            value = 'test-session-secret'
            legacy = directory / f'.cached_cookies_{value}.json'
            legacy.write_text('{}', encoding='utf8')
            rotation = types.ModuleType('gemini_webapi.utils.rotate_1psidts')
            rotation._get_cookie_cache_dir = lambda: directory
            access = types.ModuleType('gemini_webapi.utils.get_access_token')
            with patch.dict(sys.modules, {rotation.__name__: rotation, access.__name__: access}):
                gemini.private_cache_names({'__Secure-1PSID': value})
            jar = types.SimpleNamespace(jar=[types.SimpleNamespace(name='__Secure-1PSID', value=value)])
            target = rotation._get_cookies_cache_path(jar)
            self.assertNotIn(value, target.name)
            self.assertTrue(target.exists())
            self.assertFalse(legacy.exists())
            self.assertEqual(access._get_cookies_cache_path(jar), target)

    def test_firefox_filters_containers_expired_and_unrelated_cookies(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'Mozilla/Firefox'
            profile = root / 'Profiles/default'
            profile.mkdir(parents=True)
            (root / 'profiles.ini').write_text('[InstallTest]\nDefault=Profiles/default\n', encoding='utf8')
            with contextlib.closing(sqlite3.connect(profile / 'cookies.sqlite')) as db, db:
                db.execute('CREATE TABLE moz_cookies (name TEXT,value TEXT,expiry INTEGER,host TEXT,originAttributes TEXT,lastAccessed INTEGER)')
                db.executemany('INSERT INTO moz_cookies VALUES (?,?,?,?,?,?)', [
                    ('__Secure-1PSID', 'normal', 9999999999, '.google.com', '', 1),
                    ('__Secure-1PSIDTS', 'expired', 1, '.google.com', '', 2),
                    ('__Secure-1PSID', 'container', 9999999999, '.google.com', '^userContextId=1', 3),
                    ('__Secure-1PSID', 'other-site', 9999999999, '.example.com', '', 4),
                    ('password', 'unrelated', 9999999999, '.google.com', '', 5),
                ])
            with patch.dict(os.environ, {'APPDATA': temp}), patch.object(browsers.sys, 'platform', 'win32'):
                self.assertEqual(browsers.firefox_cookies('gemini'), {'__Secure-1PSID': 'normal'})

    def test_download_does_not_forward_auth_to_external_redirect(self):
        calls = []
        def get(url, **kwargs):
            calls.append((url, kwargs))
            if len(calls) == 1:
                return types.SimpleNamespace(status_code=302, headers={'location': 'https://files.oaiusercontent.com/image'}, raise_for_status=lambda: None)
            return types.SimpleNamespace(status_code=200, content=b'image', raise_for_status=lambda: None)
        with patch.dict(sys.modules, {'curl_cffi': types.SimpleNamespace(requests=types.SimpleNamespace(get=get))}):
            self.assertEqual(chatgpt.download('https://chatgpt.com/backend-api/estuary/content?id=test', 'secret', {'session': 'secret'}), b'image')
        self.assertIn('headers', calls[0][1])
        self.assertNotIn('headers', calls[1][1])
        self.assertNotIn('cookies', calls[1][1])

    def test_download_rejects_non_https_before_request(self):
        with self.assertRaises(chatgpt.SessionError):
            chatgpt.download('http://chatgpt.com/image', 'secret', {})

    def test_worker_is_killed_when_comfy_interrupts(self):
        package = types.ModuleType('session_test_package')
        package.__path__ = [str(SOURCE)]
        helper = types.ModuleType('session_test_package.chatgpt_image')
        class Cancelled(Exception):
            pass
        helper._interrupt = lambda: (_ for _ in ()).throw(Cancelled())
        with patch.dict(sys.modules, {package.__name__: package, helper.__name__: helper}):
            spec = importlib.util.spec_from_file_location('session_test_package.web_sessions', SOURCE / 'web_sessions.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        from unittest.mock import MagicMock
        process = MagicMock()
        process.poll.return_value = None
        with patch.object(module, '_runtime', return_value=Path(sys.executable)), patch.object(module.subprocess, 'Popen', return_value=process):
            with self.assertRaises(Cancelled):
                module._worker('gemini', {'action': 'connect'}, interrupt=True)
        process.kill.assert_called_once()
        process.communicate.assert_called_once()


class GeminiStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_image_before_trailing_stream_error(self):
        class Asset:
            pass
        asset = Asset()
        state = {'closed': False, 'tail': False}
        async def stream(*args, **kwargs):
            self.assertEqual(kwargs['current_retry'], 0)
            try:
                yield types.SimpleNamespace(metadata=['c_this_request'], images=[object(), asset])
                state['tail'] = True
                raise RuntimeError('late stream failure')
            finally:
                state['closed'] = True
        client = types.SimpleNamespace(start_chat=lambda: types.SimpleNamespace(cid=''), generate_content_stream=stream)
        result = await gemini.generated_asset(client, {'prompt':'test'}, Asset, lambda _: None)
        self.assertIs(result, asset)
        self.assertTrue(state['closed'])
        self.assertFalse(state['tail'])

    async def test_recovers_only_current_chat_without_resubmitting(self):
        from unittest.mock import AsyncMock
        APIError = type('APIError', (Exception,), {})
        class Asset:
            pass
        asset = Asset()
        submissions = []
        async def stream(*args, **kwargs):
            submissions.append(1)
            yield types.SimpleNamespace(metadata=['c_this_request'], images=[])
            raise APIError('stream interrupted')
        history = types.SimpleNamespace(turns=[types.SimpleNamespace(role='model', model_output=types.SimpleNamespace(images=[asset]))])
        read = AsyncMock(return_value=history)
        client = types.SimpleNamespace(start_chat=lambda: types.SimpleNamespace(cid=''), generate_content_stream=stream,
                                       _running=True, read_chat=read)
        result = await gemini.generated_asset(client, {'prompt':'test'}, Asset, lambda _: None)
        self.assertIs(result, asset)
        self.assertEqual(len(submissions), 1)
        read.assert_awaited_once_with('c_this_request')

    async def test_does_not_resubmit_an_untracked_request(self):
        from unittest.mock import AsyncMock
        APIError = type('APIError', (Exception,), {})
        submissions = []
        async def stream(*args, **kwargs):
            submissions.append(1)
            if False:
                yield None
            raise APIError('The original request may have been silently aborted by Google.')
        read = AsyncMock()
        client = types.SimpleNamespace(start_chat=lambda: types.SimpleNamespace(cid=''), generate_content_stream=stream, read_chat=read)
        with self.assertRaises(APIError):
            await gemini.generated_asset(client, {'prompt':'test'}, object, lambda _: None)
        self.assertEqual(len(submissions), 1)
        read.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
