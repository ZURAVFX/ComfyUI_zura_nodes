"""ChatGPT web-session worker. Explicit provider only; no Codex or browser fallback."""
import asyncio
import contextlib
import io
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urljoin

from gemini_session_worker import firefox_profile


class SessionError(RuntimeError):
    pass


def session():
    from curl_cffi import requests
    with contextlib.closing(sqlite3.connect((firefox_profile() / 'cookies.sqlite').as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
        rows = db.execute("SELECT name,value,expiry FROM moz_cookies WHERE host IN ('.chatgpt.com','chatgpt.com') AND originAttributes='' AND (name LIKE '__Secure-next-auth.session-token%' OR name IN ('cf_clearance','oai-did')) ORDER BY lastAccessed").fetchall()
    cookies = {name: value for name, value, expiry in rows if not expiry or expiry > time.time()}
    if not any(name.startswith('__Secure-next-auth.session-token') for name in cookies):
        raise SessionError('Sign in to ChatGPT in your normal Firefox, then reconnect.')
    response = requests.get('https://chatgpt.com/api/auth/session', cookies=cookies, impersonate='chrome', timeout=30)
    if response.status_code != 200:
        raise SessionError('ChatGPT did not accept the Firefox session. Open ChatGPT normally, then reconnect.')
    token = response.json().get('accessToken')
    if not token:
        raise SessionError('No signed-in ChatGPT session found. Sign in in your normal Firefox, then reconnect.')
    return token, cookies


def download(url, token, cookies):
    for _ in range(5):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.username or parts.password:
            raise SessionError('ChatGPT returned an invalid download address.')
        from curl_cffi import requests
        auth = {'headers': {'authorization': f'Bearer {token}'}, 'cookies': cookies} if parts.netloc == 'chatgpt.com' else {}
        response = requests.get(url, **auth, impersonate='chrome', timeout=45, allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, response.headers['location'])
            continue
        response.raise_for_status()
        return response.content
    raise SessionError('ChatGPT image download redirected too many times.')


async def run(request):
    token, cookies = await asyncio.to_thread(session)
    if request['action'] == 'connect':
        return {'ok': True}
    import g4f
    from g4f.Provider.needs_auth.OpenaiChat import OpenaiChat
    from g4f.providers.response import ImageResponse, ImagePreview
    g4f.debug.logging = False
    g4f.debug.version_check = False
    media = [(Path(path).read_bytes(), Path(path).name) for path in request.get('paths', [])]
    timeout = request.get('timeout', 300)
    stream = OpenaiChat.create_async_generator(
        model='gpt-image', messages=[{'role': 'user', 'content': request['prompt']}],
        api_key=token, cookies=cookies, timeout=timeout, image_timeout=timeout,
        media=media or None,
    )
    async with contextlib.aclosing(stream):
        async for chunk in stream:
            if isinstance(chunk, ImageResponse) and not isinstance(chunk, ImagePreview):
                urls = chunk.get_list()
                if not urls:
                    continue
                data = await asyncio.to_thread(download, urls[0], token, cookies)
                path = Path(request['output_dir']) / 'generated.png'
                path.write_bytes(data)
                return {'ok': True, 'path': str(path)}
    raise SessionError('ChatGPT completed the request without a generated image. Check your account limits or try a different prompt.')


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        logging.disable(logging.CRITICAL)
        # Upstream errors/debug messages can include request headers. Keep them local.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            answer = asyncio.run(asyncio.wait_for(run(request), request.get('timeout', 300)))
    except SessionError as exc:
        answer = {'ok': False, 'error': str(exc)}
    except Exception as exc:
        answer = {'ok': False, 'error': f'ChatGPT request failed ({type(exc).__name__}). Open ChatGPT in Firefox and check your session or account limits, then reconnect.'}
    print(json.dumps(answer))
