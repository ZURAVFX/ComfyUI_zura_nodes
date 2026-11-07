"""Explicit, provider-scoped browser connections. Never inspect other browser accounts."""
from __future__ import annotations

import asyncio
import configparser
import contextlib
import json
import os
import plistlib
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

LABELS = {'chrome': 'Chrome', 'edge': 'Microsoft Edge', 'safari': 'Safari',
          'firefox': 'Firefox', 'brave': 'Brave', 'vivaldi': 'Vivaldi',
          'chromium': 'Chromium', 'opera': 'Opera'}
URLS = {'chatgpt': 'https://chatgpt.com/auth/login', 'gemini': 'https://gemini.google.com/app'}
_managed = {}
_lock = threading.Lock()


class BrowserSessionError(RuntimeError):
    pass


def browser_executable(browser):
    if browser not in LABELS:
        return None
    apps = {'chrome': ('Google Chrome', 'Google Chrome'), 'edge': ('Microsoft Edge', 'Microsoft Edge'),
            'safari': ('Safari', 'Safari'), 'firefox': ('Firefox', 'firefox'),
            'brave': ('Brave Browser', 'Brave Browser'), 'vivaldi': ('Vivaldi', 'Vivaldi'),
            'chromium': ('Chromium', 'Chromium'), 'opera': ('Opera', 'Opera')}
    if sys.platform == 'darwin':
        app, binary = apps[browser]
        candidates = [base / f'{app}.app/Contents/MacOS/{binary}' for base in (Path('/Applications'), Path.home() / 'Applications')]
    elif sys.platform == 'win32':
        relative = {'chrome': 'Google/Chrome/Application/chrome.exe', 'edge': 'Microsoft/Edge/Application/msedge.exe',
                    'firefox': 'Mozilla Firefox/firefox.exe', 'brave': 'BraveSoftware/Brave-Browser/Application/brave.exe',
                    'vivaldi': 'Vivaldi/Application/vivaldi.exe', 'chromium': 'Chromium/Application/chrome.exe',
                    'opera': 'Programs/Opera/opera.exe'}
        candidates = [Path(os.environ[key]) / relative[browser] for key in ('LOCALAPPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)')
                      if os.environ.get(key) and browser in relative]
    else:
        candidates = []
    commands = {'chrome': ('google-chrome', 'google-chrome-stable'), 'edge': ('microsoft-edge', 'microsoft-edge-stable'),
                'firefox': ('firefox',), 'brave': ('brave-browser', 'brave'), 'vivaldi': ('vivaldi', 'vivaldi-stable'),
                'chromium': ('chromium', 'chromium-browser'), 'opera': ('opera',)}
    for command in commands.get(browser, ()):
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))
    return next((path for path in candidates if path.is_file()), None)


def _browser_id(identifier):
    """Translate OS browser registrations without inspecting browser profiles."""
    identifier = str(identifier).lower()
    prefixes = {
        'firefox': ('firefox', 'org.mozilla.firefox', 'userapp-firefox', 'snap.firefox'),
        'chrome': ('chromehtml', 'google-chrome', 'com.google.chrome', 'chrome.desktop'),
        'edge': ('msedge', 'microsoft-edge', 'com.microsoft.edgemac'),
        'safari': ('com.apple.safari',),
        'brave': ('brave', 'com.brave.browser'),
        'vivaldi': ('vivaldi', 'com.vivaldi.vivaldi'),
        'chromium': ('chromium', 'org.chromium.chromium'),
        'opera': ('opera', 'com.operasoftware.opera'),
    }
    return next((browser for browser, names in prefixes.items() if identifier.startswith(names)), None)


def default_browser():
    """Read the default web handler on the ComfyUI host, without opening it."""
    try:
        if sys.platform == 'win32':
            import winreg
            for scheme in ('https', 'http'):
                try:
                    key = rf'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\{scheme}\UserChoice'
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                        identifier = winreg.QueryValueEx(handle, 'ProgId')[0]
                    # An unsupported HTTPS handler must not be replaced with the HTTP default.
                    return _browser_id(identifier)
                except OSError:
                    continue
        elif sys.platform == 'darwin':
            result = subprocess.run(
                ['/usr/bin/defaults', 'export', 'com.apple.LaunchServices/com.apple.launchservices.secure', '-'],
                capture_output=True, check=True, timeout=2)
            handlers = plistlib.loads(result.stdout).get('LSHandlers', [])
            for scheme in ('https', 'http'):
                for handler in handlers:
                    if handler.get('LSHandlerURLScheme') == scheme and handler.get('LSHandlerRoleAll'):
                        return _browser_id(handler['LSHandlerRoleAll'])
        else:
            result = subprocess.run(['xdg-settings', 'get', 'default-web-browser'],
                                    capture_output=True, text=True, check=True, timeout=2)
            return _browser_id(result.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError, plistlib.InvalidFileException):
        pass
    return None


def available_browsers():
    order = ['safari', 'chrome', 'edge', 'firefox', 'brave', 'vivaldi', 'chromium', 'opera'] if sys.platform == 'darwin' else LABELS
    choices = [{'id': browser, 'name': LABELS[browser]} for browser in order if browser_executable(browser)]
    preferred = default_browser()
    # Stable sorting preserves the fallback order if the OS handler is unsupported or missing.
    return sorted(choices, key=lambda choice: choice['id'] != preferred)


def filter_cookies(provider, rows):
    """Drop unrelated, expired, container and partitioned cookies before IPC."""
    if provider not in URLS:
        raise ValueError('Unknown image provider.')
    values = {}
    for row in rows:
        if row.get('partitionKey') or row.get('originAttributes'):
            continue
        domain = str(row.get('domain', '')).lstrip('.').lower()
        name = str(row.get('name', ''))
        expiry = row.get('expires', 0) or 0
        if expiry > 0 and expiry <= time.time():
            continue
        allowed = (domain == 'google.com' and name in ('__Secure-1PSID', '__Secure-1PSIDTS')) if provider == 'gemini' else (
            domain == 'chatgpt.com' and (name in ('__Secure-next-auth.session-token', 'cf_clearance', 'oai-did')
            or name.startswith('__Secure-next-auth.session-token.') and name.rsplit('.', 1)[-1].isdigit()))
        if allowed and isinstance(row.get('value'), str) and row['value']:
            values[name] = row['value']
    required = bool(values.get('__Secure-1PSID')) if provider == 'gemini' else any(
        name.startswith('__Secure-next-auth.session-token') for name in values)
    if not required:
        raise BrowserSessionError('Sign in to the selected account in the browser window, then leave it open while Zura connects.')
    return values


def firefox_profile():
    if sys.platform == 'win32':
        roots = [Path(os.environ.get('APPDATA', Path.home())) / 'Mozilla/Firefox']
    elif sys.platform == 'darwin':
        roots = [Path.home() / 'Library/Application Support/Firefox']
    else:
        roots = [Path.home() / location for location in ('.mozilla/firefox', 'snap/firefox/common/.mozilla/firefox',
                                                       '.var/app/org.mozilla.firefox/.mozilla/firefox')]
    for root in roots:
        config = configparser.ConfigParser()
        config.read(root / 'profiles.ini', encoding='utf8')
        for section in config.sections():
            if section.startswith('Install') and config.has_option(section, 'Default'):
                path = root / config[section]['Default']
                if (path / 'cookies.sqlite').is_file():
                    return path.resolve()
        for section in config.sections():
            if section.startswith('Profile') and config[section].get('Default') == '1':
                value = config[section]['Path']
                path = root / value if config[section].get('IsRelative') == '1' else Path(value)
                if (path / 'cookies.sqlite').is_file():
                    return path.resolve()
    raise BrowserSessionError('Open Firefox and sign in using its default profile, outside private windows and containers.')


def firefox_cookies(provider):
    uri = (firefox_profile() / 'cookies.sqlite').as_uri() + '?mode=ro'
    domain = 'google.com' if provider == 'gemini' else 'chatgpt.com'
    with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
        rows = db.execute('SELECT name,value,expiry,host,originAttributes FROM moz_cookies '
                          'WHERE host IN (?,?) AND originAttributes=\'\' ORDER BY lastAccessed', (domain, '.' + domain)).fetchall()
    return filter_cookies(provider, [dict(zip(('name', 'value', 'expires', 'domain', 'originAttributes'), row)) for row in rows])


def safari_cookies(provider):
    if sys.platform != 'darwin':
        raise BrowserSessionError('Safari connections are available on macOS.')
    from yt_dlp.cookies import extract_cookies_from_browser
    class QuietLogger:
        def debug(self, *args, **kwargs): pass
        info = warning = error = debug
    try:
        jar = extract_cookies_from_browser('safari', logger=QuietLogger())
    except PermissionError:
        raise BrowserSessionError('macOS blocked Safari session access. In System Settings > Privacy & Security > Full Disk Access, '
                                  'allow the app that starts ComfyUI (or choose Chrome or another browser here), then restart ComfyUI.') from None
    except Exception:
        raise BrowserSessionError('Safari session is unavailable. Sign in in a normal Safari window, then reconnect. '
                                  'If macOS blocks access, allow Full Disk Access for the app that starts ComfyUI or choose another browser.') from None
    return filter_cookies(provider, [dict(name=c.name, value=c.value, domain=c.domain, expires=c.expires) for c in jar])


def _endpoint(directory):
    try:
        lines = (directory / 'DevToolsActivePort').read_text(encoding='utf8').splitlines()
        port = int(lines[0])
        if not 1 <= port <= 65535 or not lines[1].startswith('/devtools/browser/'):
            raise ValueError()
        return port, lines[1]
    except (OSError, ValueError, IndexError):
        raise BrowserSessionError('Waiting for the browser window. If it was closed, cancel and reconnect.') from None


def open_browser(provider, browser, root):
    if provider not in URLS or browser not in LABELS:
        raise ValueError('Choose an installed browser and image provider.')
    executable = browser_executable(browser)
    if not executable:
        raise BrowserSessionError(f'{LABELS[browser]} is not installed on the computer running ComfyUI. Choose another browser.')
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    if browser in ('firefox', 'safari'):
        command = ['open', '-a', str(executable.parents[2]), URLS[provider]] if sys.platform == 'darwin' else [str(executable), URLS[provider]]
        if browser == 'firefox':
            try:
                command = [str(executable), '-profile', str(firefox_profile()), URLS[provider]]
            except BrowserSessionError:
                pass
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        return
    directory = Path(root) / 'browser-profiles' / provider / browser
    directory.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        directory.chmod(0o700)
    with _lock:
        # Never enable debugging on a user's everyday profile. Reuse only our own launch.
        process = subprocess.Popen([str(executable), f'--user-data-dir={directory}', '--remote-debugging-port=0',
                                    '--remote-debugging-address=127.0.0.1', '--no-first-run', '--no-default-browser-check',
                                    '--new-window', URLS[provider]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=flags)
        _managed[(provider, browser)] = (process, directory)


async def _chromium_cookies(provider, port, browser_path):
    import aiohttp
    origin = f'http://127.0.0.1:{port}'
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as client:
        async with client.get(origin + '/json/version', allow_redirects=False) as response:
            response.raise_for_status()
            version = await response.json()
        if version.get('webSocketDebuggerUrl') != f'ws://127.0.0.1:{port}{browser_path}':
            raise BrowserSessionError('The browser connection changed. Close the Zura sign-in window and reconnect.')
        async with client.get(origin + '/json/list', allow_redirects=False) as response:
            response.raise_for_status()
            targets = await response.json()
        host = 'chatgpt.com' if provider == 'chatgpt' else 'gemini.google.com'
        target = next((target for target in targets if target.get('type') == 'page'
                       and urlsplit(target.get('url', '')).hostname == host), None)
        if not target:
            raise BrowserSessionError('Finish signing in, then keep the provider page open in the Zura sign-in window.')
        endpoint = target.get('webSocketDebuggerUrl', '')
        parts = urlsplit(endpoint)
        if parts.scheme != 'ws' or parts.hostname != '127.0.0.1' or parts.port != port or not parts.path.startswith('/devtools/page/'):
            raise BrowserSessionError('The browser returned an invalid local connection. Close the sign-in window and reconnect.')
        urls = ['https://chatgpt.com/', 'https://chatgpt.com/api/auth/session'] if provider == 'chatgpt' else ['https://google.com/', 'https://gemini.google.com/']
        async with client.ws_connect(endpoint, origin=None) as ws:
            await ws.send_json({'id': 1, 'method': 'Network.getCookies', 'params': {'urls': urls}})
            async for message in ws:
                if message.type != aiohttp.WSMsgType.TEXT:
                    break
                result = json.loads(message.data)
                if result.get('id') == 1:
                    return filter_cookies(provider, result.get('result', {}).get('cookies', []))
    raise BrowserSessionError('The browser connection closed. Reconnect using the selected browser.')


def read_cookies(provider, browser):
    try:
        if browser == 'firefox':
            return firefox_cookies(provider)
        if browser == 'safari':
            return safari_cookies(provider)
        with _lock:
            entry = _managed.get((provider, browser))
        if not entry:
            raise BrowserSessionError('The sign-in window is closed. Cancel and reconnect to open it again.')
        async def read():
            return await asyncio.wait_for(_chromium_cookies(provider, *_endpoint(entry[1])), timeout=10)
        return asyncio.run(read())
    except BrowserSessionError:
        raise
    except Exception:
        raise BrowserSessionError(f'Could not read the {LABELS.get(browser, "selected browser")} session. '
                                  'Keep its sign-in window open and finish signing in, or cancel and choose another browser.') from None
