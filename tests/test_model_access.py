"""Credential validation/storage tests use fake accounts, never real HF tokens."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import requests

spec = importlib.util.spec_from_file_location('shared_model_access', Path(__file__).resolve().parents[1] / 'model_access.py')
access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)
TOKEN = 'hf_FixtureOnlyNotARealCredential'


class Reply:
    status_code = 200
    def raise_for_status(self): pass
    def json(self): return {'name': 'fixture-account'}


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'zura' / 'huggingface-access'
        self.manager = access.ModelAccess(self.path)

    def test_connect_is_shared_without_exposing_token_and_remembers_only_if_chosen(self):
        with patch('requests.get', return_value=Reply()) as get:
            state = self.manager.connect(TOKEN, True)
        self.assertTrue(state['connected'])
        self.assertTrue(state['remembered'])
        self.assertEqual(state['name'], 'fixture-account')
        self.assertNotIn(TOKEN, json.dumps(state))
        self.assertNotIn(TOKEN.encode(), self.path.read_bytes())
        if os.name != 'nt': self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(access.ModelAccess(self.path).credential(), TOKEN)
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer ' + TOKEN)
        self.manager.disconnect()
        self.assertFalse(self.path.exists())
        self.assertFalse(self.manager.status()['connected'])

    def test_session_connection_does_not_write_credential(self):
        with patch('requests.get', return_value=Reply()):
            self.manager.connect(TOKEN)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.manager.credential(), TOKEN)

    def test_bad_token_or_network_failure_never_replace_good_connection_or_leak_secrets(self):
        with patch('requests.get', return_value=Reply()):
            self.manager.connect(TOKEN)
        bad = Reply();bad.status_code = 401
        with patch('requests.get', return_value=bad), self.assertRaisesRegex(ValueError, 'did not accept'):
            self.manager.connect('hf_InvalidFixture')
        with patch('requests.get', side_effect=requests.ConnectionError(TOKEN)), self.assertRaisesRegex(ValueError, 'Could not reach') as error:
            self.manager.connect('hf_AnotherFixture')
        self.assertNotIn(TOKEN, str(error.exception))
        self.assertEqual(self.manager.credential(), TOKEN)
        with patch('requests.get') as get:
            for value in (None, {}, 'not a token', 'hf_bad\nheader'):
                with self.assertRaises(ValueError):self.manager.connect(value)
            get.assert_not_called()

    def test_existing_hf_login_is_reused_without_overwriting_it(self):
        with patch('huggingface_hub.get_token', return_value=TOKEN):
            self.assertEqual(self.manager.credential(), TOKEN)
            self.assertTrue(self.manager.status()['cached'])
            self.manager.disconnect()
            self.assertIsNone(self.manager.credential())


    def device_reply(self, payload):
        reply = Reply()
        reply.json = lambda: payload
        return reply

    def start_device(self):
        payload = dict(device_code='server-only-device', user_code='ABCD-EFGH',
                       verification_uri='https://huggingface.co/oauth/device', expires_in=300)
        with patch('requests.post', return_value=self.device_reply(payload)) as post:
            login = self.manager.browser_start(True)
        self.assertEqual(post.call_args.kwargs['data']['scope'], 'openid profile gated-repos')
        self.assertNotIn('device_code', login)
        self.assertEqual(login['code'], 'ABCD-EFGH')
        return login

    def test_browser_pending_slowdown_success_and_expiry(self):
        login = self.start_device()
        with patch('requests.post', return_value=self.device_reply({'error':'authorization_pending'})) as post:
            self.assertEqual(self.manager.browser_poll(login['id'])['phase'], 'waiting')
            self.manager.browser_poll(login['id'])
            self.assertEqual(post.call_count, 1, 'Server enforces polling interval')
        self.manager.browser_login['next_poll'] = 0
        with patch('requests.post', return_value=self.device_reply({'error':'slow_down'})):
            self.assertEqual(self.manager.browser_poll(login['id'])['interval'], 10)
        self.manager.browser_login['next_poll'] = 0
        with patch('requests.post', return_value=self.device_reply({'access_token':'opaque.oauth.fixture', 'expires_in':3600})), patch('requests.get', return_value=Reply()):
            state = self.manager.browser_poll(login['id'])
        self.assertEqual(state['phase'], 'connected')
        self.assertNotIn('opaque.oauth.fixture', json.dumps(state))
        restored = access.ModelAccess(self.path)
        self.assertEqual(restored.credential(), 'opaque.oauth.fixture')
        with patch.object(access.time, 'time', return_value=restored.expires+1):
            self.assertFalse(restored.status()['connected'], 'Expired OAuth tokens ask for sign-in again')

    def test_device_cancel_denial_and_untrusted_destination(self):
        login = self.start_device()
        with self.assertRaisesRegex(ValueError, 'ended'):
            self.manager.browser_poll('wrong-session')
        self.assertEqual(self.manager.browser_poll(login['id'], True)['phase'], 'cancelled')
        with patch('requests.post') as post, self.assertRaisesRegex(ValueError, 'ended'):
            self.manager.browser_poll(login['id'])
        post.assert_not_called()
        login = self.start_device()
        with patch('requests.post', return_value=self.device_reply({'error':'access_denied'})), self.assertRaisesRegex(ValueError, 'declined'):
            self.manager.browser_poll(login['id'])
        self.assertIsNone(self.manager.browser_login)
        with patch('requests.post', return_value=self.device_reply(dict(device_code='secret',user_code='code',verification_uri='https://evil.example',expires_in=300))), self.assertRaisesRegex(ValueError, 'Could not open'):
            self.manager.browser_start()

    def test_cancel_while_token_request_is_in_flight_cannot_connect(self):
        login = self.start_device()
        def respond(*args, **kwargs):
            self.manager.browser_poll(login['id'], True)
            return self.device_reply({'access_token':TOKEN})
        with patch('requests.post', side_effect=respond), patch('requests.get') as get, self.assertRaisesRegex(ValueError, 'cancelled'):
            self.manager.browser_poll(login['id'])
        get.assert_not_called()


if __name__ == '__main__': unittest.main()
