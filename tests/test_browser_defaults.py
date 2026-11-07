"""Default browser selection without real launches or account access."""
import contextlib
from pathlib import Path
import plistlib
import sys
import types
import unittest
from unittest.mock import Mock, patch

from test_browser_sessions import browsers, session_module


class DefaultBrowserTests(unittest.TestCase):
    def test_windows_uses_https_user_choice_including_firefox(self):
        registry = types.ModuleType('winreg')
        registry.HKEY_CURRENT_USER = object()
        registry.OpenKey = Mock(side_effect=lambda *args: contextlib.nullcontext('key'))
        registry.QueryValueEx = Mock()
        with patch.dict(sys.modules, {'winreg': registry}), patch.object(browsers.sys, 'platform', 'win32'):
            for identifier, expected in [('FirefoxURL-308046B0AF4A39CB', 'firefox'), ('MSEdgeHTM', 'edge'), ('ChromeHTML', 'chrome')]:
                registry.QueryValueEx.return_value = (identifier, 1)
                self.assertEqual(browsers.default_browser(), expected)
                self.assertIn('https', registry.OpenKey.call_args.args[1])

    def test_windows_falls_back_to_http_only_when_https_is_unregistered(self):
        registry = types.ModuleType('winreg')
        registry.HKEY_CURRENT_USER = object()
        registry.OpenKey = Mock(side_effect=[FileNotFoundError(), contextlib.nullcontext('key')])
        registry.QueryValueEx = Mock(return_value=('FirefoxURL-test', 1))
        with patch.dict(sys.modules, {'winreg': registry}), patch.object(browsers.sys, 'platform', 'win32'):
            self.assertEqual(browsers.default_browser(), 'firefox')
            self.assertIn('http\\UserChoice', registry.OpenKey.call_args.args[1])

    def test_macos_prefers_https_handler(self):
        data = plistlib.dumps({'LSHandlers': [
            {'LSHandlerURLScheme': 'http', 'LSHandlerRoleAll': 'com.apple.Safari'},
            {'LSHandlerURLScheme': 'https', 'LSHandlerRoleAll': 'org.mozilla.firefox'},
        ]})
        with patch.object(browsers.sys, 'platform', 'darwin'), patch.object(browsers.subprocess, 'run', return_value=types.SimpleNamespace(stdout=data)) as run:
            self.assertEqual(browsers.default_browser(), 'firefox')
            self.assertEqual(run.call_args.kwargs['timeout'], 2)

    def test_linux_desktop_defaults_and_missing_desktop_service(self):
        with patch.object(browsers.sys, 'platform', 'linux'), patch.object(browsers.subprocess, 'run') as run:
            for identifier, expected in [('firefox_firefox.desktop\n', 'firefox'), ('org.mozilla.firefox.desktop', 'firefox'), ('google-chrome.desktop', 'chrome'), ('org.chromium.Chromium.desktop', 'chromium'), ('unknown.desktop', None)]:
                run.return_value = types.SimpleNamespace(stdout=identifier)
                self.assertEqual(browsers.default_browser(), expected)
            run.side_effect = FileNotFoundError()
            self.assertIsNone(browsers.default_browser())
            run.side_effect = browsers.subprocess.TimeoutExpired('xdg-settings', 2)
            self.assertIsNone(browsers.default_browser())

    def test_installed_default_comes_first_without_reading_accounts(self):
        with patch.object(browsers.sys, 'platform', 'win32'), patch.object(browsers, 'browser_executable', return_value=Path('installed')), patch.object(browsers, 'default_browser', return_value='firefox'), patch.object(browsers, 'read_cookies') as read:
            choices = browsers.available_browsers()
            self.assertEqual(choices[0]['id'], 'firefox')
            self.assertEqual([item['id'] for item in choices[1:]], [name for name in browsers.LABELS if name != 'firefox'])
            read.assert_not_called()

    def test_unavailable_or_unknown_default_keeps_installed_fallbacks(self):
        with patch.object(browsers.sys, 'platform', 'win32'), patch.object(browsers, 'browser_executable', side_effect=lambda name: Path('installed') if name in ('chrome', 'edge') else None), patch.object(browsers, 'default_browser') as preferred:
            for value in ('firefox', None):
                preferred.return_value = value
                self.assertEqual([item['id'] for item in browsers.available_browsers()], ['chrome', 'edge'])

    def test_both_providers_default_to_firefox_and_respect_explicit_choice(self):
        module = session_module()
        with patch.object(browsers, 'available_browsers', return_value=[{'id': 'firefox'}, {'id': 'chrome'}]), patch.object(module.threading, 'Thread'):
            for provider in ('chatgpt', 'gemini'):
                module.start_login(provider)
                self.assertEqual(module.login_status(provider)['browser'], 'firefox')
                module.start_login(provider, 'chrome')
                module.start_login(provider)
                self.assertEqual(module.login_status(provider)['browser'], 'chrome')


if __name__ == '__main__':
    unittest.main()
