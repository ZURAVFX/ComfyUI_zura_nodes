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


if __name__ == '__main__': unittest.main()
