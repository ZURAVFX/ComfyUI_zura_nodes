"""Original HDR video provenance for the opt-in LTX performance experiment.

The reviewed motion proxy still supplies pose/edges and playback. This module
keeps the original HDR video, colour interpretation and selected interval
bound to the review; no tonemapped proxy can stand in for the original source.
"""
from __future__ import annotations

import asyncio
import copy
from fractions import Fraction
import math
import re
import uuid

from .ltx25_hdr_input import enabled, validate_config

_VIDEO_SPACES = {'hlg_rec2020', 'pq_rec2020', 'pq_display_p3'}


def marker(source):
    value = source.get('native_hdr_video') if isinstance(source, dict) else None
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {'asset_id', 'sha', 'colour_space'}
            or not all(isinstance(v, str) for v in value.values())
            or not re.fullmatch(r'[a-f0-9]{32}', value['asset_id'])
            or not re.fullmatch(r'[a-f0-9]{64}', value['sha'])
            or value['colour_space'] not in {'auto', *_VIDEO_SPACES}):
        raise ValueError('The HDR source identity is invalid. Import the video again.')
    return copy.deepcopy(value)


def verify_source(source, store, check_asset, config):
    identity = marker(source)
    if identity is None:
        return None
    validate_config(config)
    original = store.load(identity['asset_id'])
    if (original.get('kind') != 'asset' or original.get('asset_kind') != 'video'
            or original.get('native_hdr_video') is not None or original.get('sha') != identity['sha']
            or source.get('file') != original.get('file') or source.get('sha') != original.get('sha')):
        raise ValueError('The original HDR source no longer matches this shot. Import it again.')
    path = check_asset(original)
    check_asset(source)
    from ..paintout.paintout import describe, selected_space
    info = describe(str(path))
    if info.get('kind') != 'video':
        raise ValueError('Choose an HDR video source.')
    if info.get('transfer') in ('bt709', 'iec61966-2-1'):
        raise ValueError('This video is tagged SDR. Choose an HDR video source.')
    selected = selected_space(info, identity['colour_space'])
    if selected not in _VIDEO_SPACES:
        raise ValueError('This video is not a supported HDR source.')
    try:
        rate = Fraction(info['fps_rational'])
    except (ValueError, ZeroDivisionError, TypeError, KeyError):
        raise ValueError('The HDR source frame rate could not be verified.') from None
    if not 1 <= rate <= 120:
        raise ValueError('Choose an HDR source between 1 and 120 fps.')
    return {'asset_id': identity['asset_id'], 'file': original['file'], 'sha': identity['sha'],
        'path': str(path), 'colour_space': identity['colour_space'], 'resolved_colour_space': selected,
        'source_fps': str(rate), 'source_frames': info['count']}


def source_interval(source, store, check_asset, config, timeline):
    descriptor = verify_source(source, store, check_asset, config)
    if descriptor is None:
        return None
    start, count, fps = timeline.get('start'), timeline.get('frames'), timeline.get('fps')
    if (isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(start) or start < 0
            or type(count) is not int or not 1 <= count <= 120 or fps != 24):
        raise ValueError('The reviewed HDR source interval is invalid.')
    rate = Fraction(descriptor['source_fps'])
    first = math.ceil(Fraction(str(start)) * rate)
    if first >= descriptor['source_frames']:
        raise ValueError('The selected HDR source range is empty.')
    return {**descriptor, 'start_seconds': start, 'frames': count, 'fps': fps,
        'first_source_frame': first, 'selection': 'first-at-or-after-cfr-provisional-v1'}


def make_source_asset(store, check_asset, identity, colour='auto'):
    if not enabled():
        raise ValueError('Native HDR performance is an opt-in development preview.')
    if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{32}', identity):
        raise ValueError('Choose an uploaded HDR video.')
    original = store.load(identity)
    if (original.get('kind') != 'asset' or original.get('asset_kind') != 'video'
            or original.get('native_hdr_video') is not None):
        raise ValueError('Choose an original uploaded video.')
    source = {**copy.deepcopy(original), 'id': uuid.uuid4().hex,
        'native_hdr_video': {'asset_id': identity, 'sha': original['sha'], 'colour_space': colour}}
    verify_source(source, store, check_asset, {'engine': 'local', 'workflow_mode': 'motion',
        'edit_area': 'scene', 'ltx_output': 'hlg_and_exr'})
    store.save(source)
    return source


def make_source_opening(project, store, check_asset, verify_review, assert_approved, input_root):
    """Create an SDR viewing image while retaining the selected native HDR frame."""
    from pathlib import Path
    from PIL import Image
    import numpy as np
    from .hdr_native_source import resample_native_hdr_frames
    from ..paintout.paintout import decode_ct, sdr_view
    assert_approved(project)
    _, review = verify_review(project['review'])
    clip = review['clip']
    descriptor = source_interval(project['source'], store, check_asset, project['config'],
        {'start': clip['start'], 'frames': clip['frames'], 'fps': clip['fps']})
    if not descriptor or clip.get('source_hash') != descriptor['sha']:
        raise ValueError('Review this HDR source again before using its first frame.')
    native, _ = resample_native_hdr_frames(descriptor['path'], descriptor['start_seconds'], 1, 24,
        descriptor['colour_space'])
    preview = sdr_view(decode_ct(native), True)[0].clamp(0,1).cpu().numpy()
    root = Path(input_root).resolve()
    identity = uuid.uuid4().hex
    relative = Path('genj_studio') / identity / 'hdr_source_opening.png'
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=False)
    image = Image.fromarray((preview*255).round().astype(np.uint8))
    image.thumbnail((1024,1024), Image.Resampling.LANCZOS)
    image.save(path)
    from .studio import sha
    asset = {'id': identity, 'kind': 'asset', 'asset_kind': 'image', 'file': relative.as_posix(),
        'sha': sha(path), 'name': 'HDR source frame', 'width': preview.shape[1], 'height': preview.shape[0],
        'native_hdr': {'source_id': project['source']['id'], 'source_sha': descriptor['sha'],
            'colour_space': descriptor['colour_space'], 'start_seconds': descriptor['start_seconds']}}
    from .ltx25_hdr_input import resolve_asset
    resolve_asset(asset, project['config'], store, check_asset)
    store.save(asset)
    return asset


def register(studio, routes, response, check_asset):
    from aiohttp import web
    if not enabled():
        return

    @routes.post('/zura/studio/ltx/hdr-performance/source')
    @routes.post('/genj/studio/ltx/hdr-performance/source')
    @response
    async def prepare(request):
        from .studio import public_project
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('Choose an uploaded HDR video.')
        asset = await asyncio.to_thread(make_source_asset, studio.store, check_asset,
            body.get('asset_id'), body.get('colour_space', 'auto'))
        return web.json_response(public_project(asset))

    @routes.post('/zura/studio/projects/{identity}/hdr-source-opening')
    @routes.post('/genj/studio/projects/{identity}/hdr-source-opening')
    @response
    async def source_opening(request):
        import folder_paths
        from . import verify_review
        from .opening import bind_uploaded_opening
        from .studio import assert_approved, media_url, public_project
        async with studio.lock:
            project = studio.store.load(request.match_info['identity'])
            asset = await asyncio.to_thread(make_source_opening, project, studio.store, check_asset,
                verify_review, assert_approved, folder_paths.get_input_directory())
            project["config"].update(finished_frame_position="first", finished_frame_number=1)
            bind_uploaded_opening(project, asset, folder_paths.get_input_directory(),
                assert_approved=assert_approved, check_asset=check_asset, media_url=media_url, store=studio.store)
            project.update(look_mode='ready', starting_asset=asset)
            if not project.get('references'):
                project['character'] = copy.deepcopy(asset)
            studio.store.save(project)
            return web.json_response(public_project(project))
