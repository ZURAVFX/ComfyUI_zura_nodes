"""Video sourcing for Zura nodes: local files, direct URLs and search.

Trimmed from the original Trend Studio media module to Wan 2.2 Animate only:
topic imagery, the H3/Animate-2 backends and the selection-receipt gating are
gone.  The YouTube picker remains as a UI convenience on Zura Load Video.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
import math
from urllib.parse import urlencode, urlsplit

import numpy as np
import torch
from PIL import Image, ImageOps

UA = {'User-Agent': 'ZuraNodes/1.0 (local ComfyUI video sourcing)'}


def cache_dir():
    import folder_paths
    path = Path(folder_paths.get_temp_directory()) / 'zura_media'
    path.mkdir(parents=True, exist_ok=True)
    return path


def local_path(name):
    if not str(name).strip():
        raise ValueError('Choose a local video or paste a video URL')
    import folder_paths
    supplied = Path(str(name))
    path = (supplied if supplied.is_absolute() else Path(folder_paths.get_annotated_filepath(str(name)))).resolve()
    if not path.is_file():
        raise ValueError('Choose an existing video file: ' + str(name))
    return path


def download_video(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use a public HTTP(S) video URL without embedded credentials')
    import yt_dlp
    key = hashlib.sha256(url.encode()).hexdigest()
    cached = [p for p in cache_dir().glob(key + '.*') if p.suffix in ('.mp4', '.mkv', '.webm', '.mov')]
    if cached:
        return cached[0]

    def cap(progress):
        if progress.get('downloaded_bytes', 0) > 512 * 1024 * 1024:
            raise ValueError('Video download exceeds 512 MB; use a local trimmed clip')

    options = dict(outtmpl=str(cache_dir() / (key + '.%(ext)s')), noplaylist=True, quiet=True,
                   format='bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b', merge_output_format='mp4',
                   max_filesize=512 * 1024 * 1024, socket_timeout=20, retries=1, fragment_retries=1,
                   progress_hooks=[cap], js_runtimes={'node': {'path': shutil.which('node') or 'node'}})
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        path = Path(downloader.prepare_filename(info))
        if not path.is_file() and path.with_suffix('.mp4').is_file():
            path = path.with_suffix('.mp4')
        path.with_suffix('.source.json').write_text(json.dumps(
            {k: info.get(k) for k in ('title', 'webpage_url', 'upload_date', 'view_count', 'channel', 'duration')},
            ensure_ascii=False), encoding='utf-8')
    if not path.is_file():
        raise ValueError('Video could not be downloaded. Use a local file; login/DRM bypass is not supported.')
    return path


def choose_clip_start(path, duration=10):
    """Prefer a visible, moving, relatively continuous window in the first 120s."""
    raw = subprocess.check_output([shutil.which('ffmpeg'), '-v', 'error', '-i', str(path), '-t', '120', '-an',
                                   '-vf', 'fps=1,scale=160:90', '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1'], timeout=90)
    images = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 90, 160).astype(np.float32)
    if len(images) < 10:
        return 0.0
    brightness = images.mean(axis=(1, 2))
    contrast = images.std(axis=(1, 2))
    motion = np.abs(np.diff(images, axis=0)).mean(axis=(1, 2))
    scores = []
    window = max(1, int(np.ceil(float(duration))))
    for start in range(max(1, len(images) - window + 1)):
        movement = motion[start:start + window]
        visible = np.mean((brightness[start:start + window + 1] > 25) & (contrast[start:start + window + 1] > 20))
        score = visible * 10 + min(float(movement.mean()), 12) / 12 - float(np.mean(movement > 35)) * 4
        scores.append(score)
    return float(max(range(len(scores)), key=scores.__getitem__))


def source_max_side(value):
    """Validate the decode bound exposed by the Driving clip node."""
    value = int(value)
    if not 256 <= value <= 1920 or value % 64:
        raise ValueError('source_max_side must be a multiple of 64 between 256 and 1920')
    return value


def decode_clip(path, start, clip_seconds=10, max_side=1280):
    """Decode exactly ``clip_seconds`` seconds at 24 fps for Wan 2.2 Animate.

    Dimensions are multiples of 16 and bounded by ``max_side``.  Audio is
    returned as ComfyUI 32 kHz stereo when the source has any audio stream.
    """
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('FFmpeg and ffprobe must be on PATH for video references')
    start = float(start)
    clip_seconds = float(clip_seconds)
    if not math.isfinite(start) or start < 0:
        raise ValueError('Clip start must be a finite non-negative number')
    if not math.isfinite(clip_seconds) or not 1 <= clip_seconds <= 120:
        raise ValueError('Clip duration must be a finite number between 1 and 120 seconds')
    max_side = source_max_side(max_side)
    probe = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))
    video = next((s for s in probe['streams'] if s['codec_type'] == 'video'), None)
    if not video:
        raise ValueError('The selected file has no video stream')
    duration = float(probe.get('format', {}).get('duration', video.get('duration', 0)))
    if duration - float(start) < clip_seconds - 0.05:
        raise ValueError(f'Choose a start time with at least {clip_seconds:g} seconds remaining in the source video')
    width, height = int(video['width']), int(video['height'])
    scale = min(1, max_side / max(width, height))
    rw = max(16, round(width * scale / 16) * 16)
    rh = max(16, round(height * scale / 16) * 16)
    delivery_frames = round(clip_seconds * 24)
    args = [ffmpeg, '-v', 'error', '-ss', str(start), '-i', str(path), '-t', str(clip_seconds), '-an',
            '-vf', f'fps=24,scale={rw}:{rh}', '-frames:v', str(delivery_frames),
            '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']
    raw = subprocess.check_output(args, timeout=120)
    array = np.frombuffer(raw, dtype=np.uint8).reshape(-1, rh, rw, 3).copy()
    if len(array) < delivery_frames:
        raise ValueError(f'Source did not decode to a complete {clip_seconds:g}-second clip')
    frames = torch.from_numpy(array).float() / 255
    has_audio = any(s['codec_type'] == 'audio' for s in probe['streams'])
    audio = None
    if has_audio:
        raw = subprocess.check_output([ffmpeg, '-v', 'error', '-ss', str(start), '-i', str(path), '-t', str(clip_seconds), '-vn',
                                       '-ar', '32000', '-ac', '2', '-f', 'f32le', 'pipe:1'], timeout=120)
        samples = np.frombuffer(raw, dtype='<f4').reshape(-1, 2).copy()
        target_samples = round(clip_seconds * 32000)
        if len(samples) < target_samples:
            samples = np.pad(samples, ((0, target_samples - len(samples)), (0, 0)))
        samples = samples[:target_samples]
        audio = {'sample_rate': 32000, 'waveform': torch.from_numpy(samples).T.unsqueeze(0)}
    return frames, audio, dict(source_file=Path(path).name, start_seconds=float(start), duration_seconds=clip_seconds,
                               source_width=width, source_height=height, reference_width=rw, reference_height=rh,
                               reference_frames=len(frames), delivery_frames=delivery_frames, fps=24,
                               source_max_side=int(max_side), has_audio=bool(audio), source_audio_exact_length=bool(audio))


def _shorts_search_entries(url, limit=40):
    """Read Shorts lockups from YouTube's filtered search page.

    yt-dlp currently recognises the filtered page but returns an empty playlist;
    the page still contains the authoritative shortsLockupViewModel entries.
    """
    import requests
    response = requests.get(url, headers=UA, timeout=20)
    response.raise_for_status()
    marker = 'var ytInitialData = '
    start = response.text.find(marker)
    if start < 0:
        return []
    start = response.text.find('{', start + len(marker))
    if start < 0:
        return []
    try:
        initial, _ = json.JSONDecoder().raw_decode(response.text[start:])
    except json.JSONDecodeError:
        return []
    found = []

    def walk(value):
        if len(found) >= limit:
            return
        if isinstance(value, dict):
            lockup = value.get('shortsLockupViewModel')
            if isinstance(lockup, dict):
                endpoint = (((lockup.get('onTap') or {}).get('innertubeCommand') or {}).get('reelWatchEndpoint') or {})
                video_id = endpoint.get('videoId')
                if video_id:
                    title = ((lockup.get('overlayMetadata') or {}).get('primaryText') or {}).get('content')
                    if not title:
                        title = (lockup.get('accessibilityText') or '').rsplit(', ', 1)[0]
                    found.append({'id': video_id, 'title': title or '',
                                  'url': f'https://www.youtube.com/watch?v={video_id}'})
                    return
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(initial)
    return found


def discover_video(query, hint='live dance', choice=0, min_views=10000, shorts_only=False):
    """Search YouTube and return (url, receipt) for the highest-view match."""
    import yt_dlp
    if not str(query).strip():
        raise ValueError('Automatic video discovery requires a topic keyword')
    search = f'{str(query)[:160]} {str(hint)[:160]} ' + ('#shorts ' if shorts_only else '') + '-reaction -AI -tribute -cover'
    search_url = ('https://www.youtube.com/results?' + urlencode({'search_query': search, 'sp': 'EgIQCQ%3D%3D'})
                  if shorts_only else 'ytsearch40:' + search)
    if shorts_only:
        entries = _shorts_search_entries(search_url, 40)
        data = {'entries': entries}
    else:
        with yt_dlp.YoutubeDL(dict(quiet=True, extract_flat=True, skip_download=True, socket_timeout=20, retries=1)) as searcher:
            data = searcher.extract_info(search_url, download=False)
    candidates = []
    entries = [item for item in data.get('entries', []) if item]
    extraction_failures = 0
    filtered = dict(relevance=0, duration=0, views=0, not_vertical=0)
    query_tokens = [token.casefold() for token in re.findall(r"[\w']+", str(query)) if len(token) > 2]
    node_path = shutil.which('node') or 'node'
    with yt_dlp.YoutubeDL(dict(quiet=True, extract_flat=False, skip_download=True, socket_timeout=20, retries=1,
                               js_runtimes={'node': {'path': node_path}})) as downloader:
        for item in entries:
            detail_url = item.get('webpage_url') or item.get('url') or f"https://www.youtube.com/watch?v={item.get('id')}"
            if not shorts_only and all(item.get(key) is not None for key in ('title', 'duration', 'view_count')):
                detail = item
            else:
                try:
                    detail = downloader.extract_info(detail_url, download=False)
                except Exception:
                    extraction_failures += 1
                    continue
            title = detail.get('title') or item.get('title', '')
            title_fold = title.casefold()
            if query_tokens and not any(token in title_fold for token in query_tokens):
                filtered['relevance'] += 1
                continue
            duration = float(detail.get('duration') or item.get('duration') or 0)
            if not 10 <= duration <= (180 if shorts_only else 600):
                filtered['duration'] += 1
                continue
            views = int(detail.get('view_count') or item.get('view_count') or 0)
            if views < int(min_views):
                filtered['views'] += 1
                continue
            if shorts_only:
                width, height = detail.get('width'), detail.get('height')
                if not width or not height:
                    formats = detail.get('formats') or []
                    video_formats = [f for f in formats if f.get('vcodec') not in (None, 'none') and f.get('width') and f.get('height')]
                    if video_formats:
                        best = max(video_formats, key=lambda f: (f.get('height', 0), f.get('width', 0)))
                        width, height = best.get('width'), best.get('height')
                if not width or not height or int(height) <= int(width):
                    filtered['not_vertical'] += 1
                    continue
            canonical = detail.get('webpage_url') or item.get('webpage_url') or (f"https://www.youtube.com/watch?v={detail.get('id') or item.get('id')}")
            candidates.append(dict(title=title, url=canonical, duration=duration, view_count=views,
                                   channel=detail.get('channel') or item.get('channel'), vertical_only=bool(shorts_only)))
    candidates.sort(key=lambda c: c['view_count'], reverse=True)
    if not candidates:
        mode = 'Shorts' if shorts_only else 'videos'
        diagnostics = ', '.join(f'{key}={value}' for key, value in filtered.items() if value)
        failure = f'; metadata extraction failed for {extraction_failures}' if extraction_failures else ''
        details = f'; filtered {diagnostics}' if diagnostics else ''
        raise ValueError(f'No matching {mode} passed the filters (searched {len(entries)} results{failure}{details}). '
                         'Try another hint, lower minimum views, disable Shorts-only, or paste a URL.')
    selected = candidates[int(choice) % len(candidates)]
    return selected['url'], dict(source='YouTube public search', query=search,
                                 observed_at=datetime.now(timezone.utc).isoformat(),
                                 selection='Highest total view count among eligible search results; not a live trending chart or proof of growth',
                                 shorts_only=bool(shorts_only), selected=selected, candidates=candidates,
                                 search_diagnostics=dict(searched=len(entries), metadata_extraction_failures=extraction_failures, filtered=filtered))


def preview_clip(url, start=0, automatic=True, shorts_only=False, duration=10, max_side=1280):
    """Download, pick a window and cache a small preview MP4 for the picker UI."""
    duration = float(duration)
    if not 1 <= duration <= 120:
        raise ValueError('Clip duration must be between 1 and 120 seconds')
    max_side = source_max_side(max_side)
    path = download_video(url)
    if shorts_only:
        ffprobe = shutil.which('ffprobe')
        probe = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], timeout=30))
        video = next((s for s in probe.get('streams', []) if s.get('codec_type') == 'video'), None)
        if not video or int(video.get('height', 0)) <= int(video.get('width', 0)):
            raise ValueError('Shorts-only mode rejected this source because it is not vertical')
        if float(probe.get('format', {}).get('duration', 0)) > 180.5:
            raise ValueError('Shorts-only mode rejected this source because it is longer than 180 seconds')
    start = choose_clip_start(path, duration) if automatic else max(0, float(start))
    probe = json.loads(subprocess.check_output([shutil.which('ffprobe'), '-v', 'error', '-show_format', '-of', 'json', str(path)], timeout=30))
    source_duration = float(probe.get('format', {}).get('duration', 0))
    if source_duration - start < duration:
        raise ValueError(f'Choose a start time with at least {duration:g} seconds remaining in the source video')
    key = hashlib.sha256(f'{url}|{start}|{duration}|{max_side}'.encode()).hexdigest()[:24]
    target = cache_dir() / f'preview_{key}.mp4'
    if not target.exists():
        subprocess.run([shutil.which('ffmpeg'), '-y', '-v', 'error', '-ss', str(start), '-i', str(path), '-t', str(duration),
                        '-vf', 'scale=640:-2', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24', '-c:a', 'aac',
                        '-movflags', '+faststart', str(target)], check=True, timeout=120)
    return dict(filename=target.name, subfolder='zura_media', type='temp', start=start, duration=duration,
                source_max_side=int(max_side))
