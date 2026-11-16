"""Short, cached OCIO viewing copies. No preview path is a model input."""
from __future__ import annotations

from collections import OrderedDict
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import secrets
import subprocess
import threading
import time

import numpy as np
from PIL import Image

MAX_FRAMES = 1000
MAX_BYTES = 512 * 1024 * 1024
MAX_PIXELS = 16 * 1024 * 1024
MAX_COPIES = 16
_lock = threading.RLock()
_build_lock = threading.Lock()
_copies = OrderedDict()
_tokens = {}


def _digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _settings(body):
    from . import display_view_routes as display
    from ..comfylink import display_view
    if not isinstance(body, dict) or set(body) - {'source', 'colour_space', 'config', 'display', 'view'}:
        raise ValueError('Choose valid display preview settings.')
    if not isinstance(body.get('source'), dict):
        raise ValueError('Choose a registered video source.')
    colour = body.get('colour_space', 'auto')
    if colour != 'auto' and colour not in display._SPACES:
        raise ValueError('Choose the actual source colour space.')
    for name in ('config', 'display', 'view'):
        if not isinstance(body.get(name, ''), str) or len(body.get(name, '')) > 256:
            raise ValueError('Choose a valid OCIO display setting.')
    catalogue = display_view.describe(body.get('config', ''))
    config = display_view._config(catalogue['config'])
    output, view = body.get('display') or catalogue['display'], body.get('view') or catalogue['view']
    if output not in config.getDisplays() or view not in config.getViews(output) or view == 'Raw':
        raise ValueError('Choose an active OCIO display transform.')
    return colour, catalogue['config'], config.getCacheID(), output, view


def _frame_count(path):
    import av
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        frames = sum(1 for _ in container.decode(stream))
        audio = bool(container.streams.audio)
    return frames, audio


def prepare(body, store, check_asset, roots, *, archive_metadata=None):
    """Resolve an owned original, encode a display-only MP4, return an opaque grant."""
    from . import display_view_routes as display
    import av
    colour, config_path, config_id, output, view = _settings(body)
    original = display.resolve_original(body['source'], store, check_asset, roots,
                                        archive_metadata=archive_metadata)
    meta = original['metadata']
    path = Path(original['path'])
    if meta['kind'] != 'video' or original['files'] is not None or path.stat().st_size > MAX_BYTES:
        raise ValueError('This display video needs a selected clip under 512 MB.')
    count = meta['frame_count']
    rate = meta['frame_rate']
    if type(count) is not int or not 1 <= count <= MAX_FRAMES or not isinstance(rate, dict):
        raise ValueError('This display video supports clips of up to 1000 frames.')
    fps = Fraction(rate['numerator'], rate['denominator'])
    info = meta['info']
    if info['width'] * info['height'] > MAX_PIXELS or not 1 <= fps <= 240:
        raise ValueError('This clip exceeds the display preview size or frame-rate limit.')
    from ..paintout.paintout import selected_space
    source_space = selected_space(info, colour if colour != 'auto' else original['detectedColour'])
    if source_space not in display._SPACES:
        raise ValueError('Choose the actual source colour space for playback.')
    source_count, source_audio = _frame_count(path)
    if source_count != count:
        raise ValueError('The source frame count changed during preview preparation.')
    original['revalidate']()
    source_sha = _digest(path)
    original['revalidate']()
    # A grant can assign a different actual interpretation to identical bytes.
    # Key the rendered pixels, not the caller's 'auto' request spelling.
    identity = (source_sha, config_id, output, view, source_space, 'straight')
    key = hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest()
    cache_root = Path(roots['temp']).resolve() / 'zura_display_video'
    cache_root.mkdir(parents=True, exist_ok=True)
    final = cache_root / (key + '.mp4')
    with _build_lock:
        if not final.is_file():
            partial = cache_root / (key + '.' + secrets.token_hex(8) + '.partial.mp4')
            silent = cache_root / (key + '.' + secrets.token_hex(8) + '.silent.mp4')
            try:
                with av.open(str(silent), 'w') as container:
                    stream = container.add_stream('libx264', rate=fps)
                    stream.width = max(2, int(info['width'] * min(1, 1280 / max(info['width'], info['height']))) // 2 * 2)
                    stream.height = max(2, int(info['height'] * min(1, 1280 / max(info['width'], info['height']))) // 2 * 2)
                    stream.pix_fmt = 'yuv420p'
                    stream.options = {'preset': 'ultrafast', 'crf': '20'}
                    from .model_view import _video_frames
                    frames = _video_frames(info, 0, count, None)
                    try:
                        for index, rgba in enumerate(frames):
                            original['revalidate'](False)
                            png = display.render_pixels(rgba, source_space, config_path, output, view)
                            image = Image.open(io.BytesIO(png)).convert('RGB')
                            if image.size != (stream.width, stream.height):
                                image = image.resize((stream.width, stream.height), Image.Resampling.BICUBIC)
                            rgb = np.asarray(image)
                            frame = av.VideoFrame.from_ndarray(rgb, format='rgb24')
                            frame.pts = index
                            frame.time_base = Fraction(fps.denominator, fps.numerator)
                            for packet in stream.encode(frame):
                                container.mux(packet)
                    finally:
                        frames.close()
                    for packet in stream.encode():
                        container.mux(packet)
                if _frame_count(silent)[0] != count:
                    raise ValueError('The display copy did not retain every source frame.')
                # Video is already encoded; copy it while preserving source audio.
                from ..paintout.media_tools import find_media_tool
                executable = find_media_tool('ffmpeg')
                args = [executable, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(silent), '-i', str(path),
                        '-map', '0:v:0', '-map', '1:a:0?', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
                        '-t', str(float(count / fps)), '-movflags', '+faststart', str(partial)]
                result = subprocess.run(args, capture_output=True, text=True)
                if result.returncode:
                    raise ValueError('The display preview audio could not be retained: ' + result.stderr[-500:])
                actual_count, actual_audio = _frame_count(partial)
                if actual_count != count or (source_audio and not actual_audio):
                    raise ValueError('The display preview changed the original frame count or audio.')
                original['revalidate']()
                partial.replace(final)
            finally:
                silent.unlink(missing_ok=True)
                partial.unlink(missing_ok=True)
        token = secrets.token_urlsafe(24)
        now = time.monotonic()
        with _lock:
            _copies[key] = (final, now)
            _copies.move_to_end(key)
            _tokens[token] = (key, now + 2 * 60 * 60)
            while len(_copies) > MAX_COPIES:
                old, (obsolete, _) = _copies.popitem(last=False)
                if old != key:
                    obsolete.unlink(missing_ok=True)
            for stale, (owned, expires) in list(_tokens.items()):
                if expires < now or owned not in _copies:
                    _tokens.pop(stale, None)
    return {'url': '/zura/studio/display/video/' + token, 'frame_count': count,
            'frame_rate': rate, 'source_sha256': source_sha, 'preview_only': True}


def lookup(token):
    if not isinstance(token, str) or len(token) > 128:
        raise ValueError('This display preview has expired.')
    with _lock:
        record = _tokens.get(token)
        if not record or record[1] < time.monotonic():
            raise ValueError('This display preview has expired.')
        owned = _copies.get(record[0])
        if not owned or not owned[0].is_file():
            raise ValueError('This display preview has expired.')
        _copies.move_to_end(record[0])
        return owned[0]
