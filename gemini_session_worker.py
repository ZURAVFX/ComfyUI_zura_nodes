"""Isolated worker for the published gemini-webapi client. No credential output."""
import asyncio
import contextlib
import io
import hashlib
import importlib
import json
import re
import sys


class SessionError(RuntimeError):
    pass


def safe_failure(exc, stage):
    """Describe recognised failures without exposing upstream payloads or cookies."""
    kind = type(exc).__name__
    text = str(exc)
    if kind == 'AuthError' or isinstance(exc, SessionError) and stage == 'connecting':
        return 'auth', 'Gemini did not accept your browser session. Open Gemini in your selected browser, then reconnect.'
    if kind == 'UsageLimitExceededError':
        return 'quota', 'Gemini reports that this account has reached its usage limit. Wait for the account allowance to reset.'
    if kind == 'TemporarilyBlockedError':
        return 'limited', 'Google temporarily limited this connection. Wait before trying again; signing in again is not required.'
    if 'silently aborted' in text or 'polling timed out' in text:
        return 'aborted', 'Google ended the image request before a completed image could be recovered. Your sign-in was accepted. Check the Gemini conversation before retrying.'
    if kind in ('TimeoutError', 'ReadTimeout'):
        return 'timeout', f'Gemini timed out while {stage}. Check the conversation before retrying; it may still finish on Google’s side.'
    status = re.search(r'(?:Status: |status code )(\d{3})\b', text)
    if status:
        code = status.group(1)
        if code in ('401', '403'):
            return 'access', f'Google rejected the {stage} request (HTTP {code}). Open Gemini in your selected browser to check account access, then reconnect if requested.'
        return 'service', f'Google returned HTTP {code} while {stage}. Check Gemini in your selected browser before retrying.'
    if 'Failed to parse response' in text:
        return 'protocol', 'The Gemini client could not read Google’s response. The website format may have changed. Signing in again may not help.'
    if isinstance(exc, SessionError):
        return 'result', str(exc)
    return 'request', f'Gemini failed while {stage} ({kind}). Check the conversation in your selected browser before retrying. This does not necessarily mean your sign-in expired.'


async def generated_asset(client, request, generated_type, progress):
    """Accept a generated asset as soon as it arrives; recover only this new chat."""
    chat = client.start_chat()
    cid = None
    stream = client.generate_content_stream(request['prompt'], files=request.get('paths') or None,
                                            chat=chat, current_retry=0)
    try:
        async with contextlib.aclosing(stream):
            async for response in stream:
                metadata = getattr(response, 'metadata', None) or []
                cid = (metadata[0] if metadata else None) or getattr(chat, 'cid', None) or cid
                for asset in response.images:
                    if isinstance(asset, generated_type):
                        return asset
    except Exception as exc:
        # Quota/auth failures require an action, not another generation request.
        if type(exc).__name__ not in ('APIError', 'GeminiError', 'TimeoutError') or not cid:
            raise
        progress('recovering the existing image request')
        if not client._running:
            await client.init(timeout=30, watchdog_timeout=30, auto_close=False, auto_refresh=True, verbose=False)
        for attempt in range(3):
            history = await client.read_chat(cid)
            if history:
                for turn in history.turns:
                    output = getattr(turn, 'model_output', None)
                    if turn.role == 'model' and output:
                        for asset in output.images:
                            if isinstance(asset, generated_type):
                                return asset
            if attempt < 2:
                await asyncio.sleep(2)
        raise
    raise SessionError('Gemini returned no generated image. The request may have been refused or the account may have reached its limit.')


def private_cache_names(values):
    """Keep upstream 2.1.1's raw cookie value out of cache filenames."""
    rotation = importlib.import_module('gemini_webapi.utils.rotate_1psidts')
    access = importlib.import_module('gemini_webapi.utils.get_access_token')
    directory = rotation._get_cookie_cache_dir()
    def cache_path(jar, verbose=False):
        value = next((cookie.value for cookie in jar.jar if cookie.name == '__Secure-1PSID'), None)
        if not value:
            return None
        digest = hashlib.sha256(value.encode('utf8')).hexdigest()
        return directory / f'.cached_cookies_{digest}.json'
    # Migrate only the exact, task-owned previous cache for this account.
    legacy = directory / f'.cached_cookies_{values["__Secure-1PSID"]}.json'
    target = directory / f'.cached_cookies_{hashlib.sha256(values["__Secure-1PSID"].encode("utf8")).hexdigest()}.json'
    if legacy.parent.resolve() == directory.resolve() and legacy.is_file() and not target.exists():
        legacy.replace(target)
    rotation._get_cookies_cache_path = cache_path
    access._get_cookies_cache_path = cache_path


async def run(request):
    from gemini_webapi import GeminiClient
    from gemini_webapi.types import GeneratedImage
    from loguru import logger
    logger.remove()
    cookies = request.get('cookies') or {}
    if not cookies.get('__Secure-1PSID'):
        raise SessionError('Connect Gemini using the browser selector before generating.')
    private_cache_names(cookies)
    client = GeminiClient(cookies['__Secure-1PSID'], cookies.get('__Secure-1PSIDTS'))
    def progress(stage):
        request['_stage'] = stage
        if request.get('debug_progress'):
            print(stage, file=sys.__stderr__, flush=True)
    try:
        progress('connecting')
        timeout = request.get('timeout', 300)
        await client.init(timeout=timeout, watchdog_timeout=timeout, auto_close=False, auto_refresh=True, verbose=False)
        # Upstream can fall back to a guest session; that is not a connection.
        source = str(getattr(client, '_cookie_source', ''))
        if source.startswith('Guest'):
            raise SessionError('Google did not accept the saved browser session. Sign in again in your selected browser.')
        if request['action'] == 'connect':
            return {'ok':True}
        progress('generating')
        asset = await generated_asset(client, request, GeneratedImage, progress)
        progress('downloading')
        saved = await asset.save(path=request['output_dir'], filename='generated.png', full_size=True, verbose=False)
        return {'ok':True, 'path':saved}
    finally:
        await client.close()


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            answer = asyncio.run(asyncio.wait_for(run(request), request.get('timeout', 300)))
    except Exception as exc:
        code, message = safe_failure(exc, locals().get('request', {}).get('_stage', 'connecting'))
        answer = {'ok':False, 'code':code, 'error':message}
    print(json.dumps(answer))
