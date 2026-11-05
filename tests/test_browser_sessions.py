"""Browser selection and local CDP protocol tests. Synthetic accounts only."""
import asyncio
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SOURCE))
import browser_sessions as browsers


def session_module():
    package = types.ModuleType('browser_test_package')
    package.__path__ = [str(SOURCE)]
    helper = types.ModuleType('browser_test_package.chatgpt_image')
    helper._interrupt = lambda: None
    with patch.dict(sys.modules, {package.__name__: package, helper.__name__: helper,
                                 'browser_test_package.browser_sessions': browsers}):
        spec = importlib.util.spec_from_file_location('browser_test_package.web_sessions', SOURCE / 'web_sessions.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class BrowserTests(unittest.TestCase):
    def test_filter_never_passes_other_accounts_or_partitioned_cookies(self):
        rows = [dict(domain='.google.com', name='__Secure-1PSID', value='wanted', expires=9999999999),
                dict(domain='accounts.google.com', name='__Secure-1PSID', value='wrong-domain'),
                dict(domain='google.com', name='__Secure-1PSID', value='container', originAttributes='^userContextId=1'),
                dict(domain='google.com', name='__Secure-1PSID', value='partition', partitionKey={'topLevelSite': 'https://other.test'}),
                dict(domain='google.com', name='__Secure-1PSIDTS', value='expired', expires=1),
                dict(domain='example.com', name='__Secure-1PSID', value='unrelated')]
        self.assertEqual(browsers.filter_cookies('gemini', rows), {'__Secure-1PSID': 'wanted'})
        with self.assertRaises(browsers.BrowserSessionError):
            browsers.filter_cookies('chatgpt', rows)

    def test_chunked_chatgpt_session_and_exact_domains(self):
        rows = [dict(domain='.chatgpt.com', name='__Secure-next-auth.session-token.0', value='first'),
                dict(domain='chatgpt.com', name='__Secure-next-auth.session-token.1', value='second'),
                dict(domain='chatgpt.com', name='__Secure-next-auth.session-token-fake', value='no'),
                dict(domain='evilchatgpt.com', name='oai-did', value='no')]
        self.assertEqual(browsers.filter_cookies('chatgpt', rows), {
            '__Secure-next-auth.session-token.0': 'first', '__Secure-next-auth.session-token.1': 'second'})

    def test_firefox_profile_on_each_platform(self):
        for platform, relative in [('win32', 'Mozilla/Firefox'), ('darwin', 'Library/Application Support/Firefox'), ('linux', '.mozilla/firefox')]:
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / relative
                profile = root / 'Profiles/default'
                profile.mkdir(parents=True)
                (profile / 'cookies.sqlite').touch()
                (root / 'profiles.ini').write_text('[Profile0]\nDefault=1\nIsRelative=1\nPath=Profiles/default\n')
                with patch.object(browsers.sys, 'platform', platform), patch.object(Path, 'home', return_value=Path(temp)), patch.dict(os.environ, {'APPDATA': temp}):
                    self.assertEqual(browsers.firefox_profile(), profile.resolve())

    def test_safari_permission_error_is_actionable_and_private(self):
        fake = types.ModuleType('yt_dlp.cookies')
        fake.extract_cookies_from_browser = Mock(side_effect=PermissionError('private-user-path'))
        with patch.dict(sys.modules, {'yt_dlp.cookies': fake}), patch.object(browsers.sys, 'platform', 'darwin'):
            with self.assertRaises(browsers.BrowserSessionError) as caught:
                browsers.safari_cookies('gemini')
        self.assertIn('Full Disk Access', str(caught.exception))
        self.assertIn('choose Chrome', str(caught.exception))
        self.assertNotIn('private-user-path', str(caught.exception))

    def test_safari_uses_only_selected_provider(self):
        fake = types.ModuleType('yt_dlp.cookies')
        fake.extract_cookies_from_browser = Mock(return_value=[
            types.SimpleNamespace(name='__Secure-1PSID', value='gemini', domain='.google.com', expires=None),
            types.SimpleNamespace(name='__Secure-next-auth.session-token', value='chatgpt', domain='.chatgpt.com', expires=None)])
        with patch.dict(sys.modules, {'yt_dlp.cookies': fake}), patch.object(browsers.sys, 'platform', 'darwin'):
            self.assertEqual(browsers.safari_cookies('chatgpt'), {'__Secure-next-auth.session-token': 'chatgpt'})

    def test_managed_profile_launch_does_not_debug_normal_profile(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(browsers, 'browser_executable', return_value=Path('chrome.exe')), patch.object(browsers.subprocess, 'Popen') as launch:
            browsers.open_browser('gemini', 'chrome', Path(temp))
            args = launch.call_args.args[0]
            self.assertIn('--remote-debugging-port=0', args)
            self.assertIn('--remote-debugging-address=127.0.0.1', args)
            self.assertIn(f'--user-data-dir={Path(temp) / "browser-profiles/gemini/chrome"}', args)
            self.assertEqual(args[-1], 'https://gemini.google.com/app')
            self.assertFalse(any('disable' in arg or 'no-sandbox' in arg for arg in args))

    def test_missing_browser_does_not_open_another_browser(self):
        with patch.object(browsers, 'browser_executable', return_value=None), patch.object(browsers.subprocess, 'Popen') as launch:
            with self.assertRaises(browsers.BrowserSessionError):
                browsers.open_browser('chatgpt', 'chrome', Path('unused'))
            launch.assert_not_called()

    def test_status_never_reads_account_data(self):
        module = session_module()
        with patch.object(browsers, 'available_browsers', return_value=[{'id': 'chrome', 'name': 'Chrome'}]), patch.object(browsers, 'read_cookies') as read:
            self.assertEqual(module.login_status('gemini')['browsers'][0]['id'], 'chrome')
            read.assert_not_called()

    def test_cancelled_attempt_cannot_connect_or_overwrite_new_browser(self):
        module = session_module()
        threads = []
        class DeferredThread:
            def __init__(self, target, **kwargs): threads.append(target)
            def start(self): pass
        with patch.object(browsers, 'available_browsers', return_value=[{'id': 'chrome'}, {'id': 'safari'}]), patch.object(module.threading, 'Thread', DeferredThread), patch.object(module, '_runtime') as runtime, patch.object(browsers, 'open_browser') as launch:
            module.start_login('gemini', 'chrome')
            module.cancel_login('gemini')
            module.start_login('gemini', 'safari')
            threads[0]()
            runtime.assert_not_called()
            launch.assert_not_called()
            self.assertEqual(module.login_status('gemini')['browser'], 'safari')
            self.assertEqual(module.login_status('gemini')['state'], 'checking')

    def test_connect_sends_only_chosen_session_and_cancellation_clears_it(self):
        module = session_module()
        threads = []
        class DeferredThread:
            def __init__(self, target, **kwargs): threads.append(target)
            def start(self): pass
        with patch.object(browsers, 'available_browsers', return_value=[{'id': 'chrome'}]), patch.object(module.threading, 'Thread', DeferredThread), patch.object(module, '_runtime'), patch.object(browsers, 'open_browser') as launch, patch.object(browsers, 'read_cookies', return_value={'__Secure-1PSID': 'synthetic'}) as read, patch.object(module, '_worker', return_value={'ok': True}) as worker:
            module.start_login('gemini', 'chrome')
            threads[0]()
            read.assert_called_once_with('gemini', 'chrome')
            self.assertEqual(worker.call_args.args[1]['cookies'], {'__Secure-1PSID': 'synthetic'})
            self.assertEqual(module.login_status('gemini')['state'], 'connected')
            self.assertNotIn('synthetic', json.dumps(module.login_status('gemini')))
            module.cancel_login('gemini')
            self.assertNotIn('gemini', module._cookies)

    def test_invalid_selection_starts_no_thread(self):
        module = session_module()
        with patch.object(browsers, 'available_browsers', return_value=[{'id': 'chrome'}]), patch.object(module.threading, 'Thread') as thread:
            for value in ('safari', '../chrome', ['chrome']):
                with self.assertRaises(ValueError): module.start_login('gemini', value)
            thread.assert_not_called()


class LocalCDPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiohttp import web
        self.requests = []
        self.port = 0
        self.bad_target = False
        self.bad_browser = False
        async def version(request):
            return web.json_response({'webSocketDebuggerUrl': f'ws://127.0.0.1:{self.port}/devtools/browser/' + ('wrong' if self.bad_browser else 'fixture')})
        async def targets(request):
            return web.json_response([{'type': 'page', 'url': 'https://chatgpt.com/', 'webSocketDebuggerUrl':
                'ws://other.example/devtools/page/fixture' if self.bad_target else f'ws://127.0.0.1:{self.port}/devtools/page/fixture'}])
        async def socket(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            data = await ws.receive_json()
            self.requests.append(data)
            await ws.send_json({'id': data['id'], 'result': {'cookies': [
                {'domain': '.chatgpt.com', 'name': '__Secure-next-auth.session-token', 'value': 'fixture'},
                {'domain': '.google.com', 'name': '__Secure-1PSID', 'value': 'not-selected'}]}})
            await ws.close()
            return ws
        app = web.Application()
        app.router.add_get('/json/version', version)
        app.router.add_get('/json/list', targets)
        app.router.add_get('/devtools/page/fixture', socket)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        await self.runner.cleanup()

    async def test_cdp_real_http_and_websocket_scopes_cookie_request(self):
        result = await browsers._chromium_cookies('chatgpt', self.port, '/devtools/browser/fixture')
        self.assertEqual(result, {'__Secure-next-auth.session-token': 'fixture'})
        self.assertEqual(self.requests[0]['method'], 'Network.getCookies')
        self.assertEqual(self.requests[0]['params']['urls'], ['https://chatgpt.com/', 'https://chatgpt.com/api/auth/session'])

    async def test_untrusted_websocket_and_reused_ports_are_rejected(self):
        for flag in ('bad_target', 'bad_browser'):
            setattr(self, flag, True)
            with self.assertRaises(browsers.BrowserSessionError):
                await browsers._chromium_cookies('chatgpt', self.port, '/devtools/browser/fixture')
            setattr(self, flag, False)
        self.assertEqual(self.requests, [])


if __name__ == '__main__':
    unittest.main()
