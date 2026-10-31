"""Opt-in HDR appearance inputs for staged LTX performance generation.

The PNG asset is a viewing proxy. Only a verified, separately stored EXR
manifest supplies the generation image; its identity travels with approval.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import uuid


def enabled():
    return os.environ.get('ZURA_LTX_HDR_PERFORMANCE', '0').strip() == '1'


def validate_config(config):
    if not enabled():
        raise ValueError('Native HDR performance is an opt-in development preview.')
    if (config.get('engine') != 'local' or config.get('workflow_mode', 'motion') != 'motion'
            or config.get('edit_area') != 'scene' or config.get('viewport_render')):
        raise ValueError('Use the LTX whole-scene performance workflow for this HDR image.')
    if config.get('ltx_output') not in ('hlg_video', 'hlg_and_exr', 'acescg_exr'):
        raise ValueError('Choose an HDR output for the native HDR opening.')


def opening_identity(proxy_sha, marker):
    if marker is None:
        return proxy_sha
    exr = (isinstance(marker, dict) and set(marker) == {'asset_id', 'manifest_sha', 'colour_space'}
           and all(isinstance(v, str) for v in marker.values())
           and re.fullmatch(r'[a-f0-9]{32}', marker.get('asset_id', ''))
           and re.fullmatch(r'[a-f0-9]{64}', marker.get('manifest_sha', ''))
           and marker.get('colour_space') in ('auto', 'acescg', 'acescct', 'linear_rec709'))
    video = (isinstance(marker, dict) and set(marker) == {'source_id', 'source_sha', 'colour_space', 'start_seconds'}
             and isinstance(marker.get('source_id'), str) and re.fullmatch(r'[a-f0-9]{32}', marker['source_id'])
             and isinstance(marker.get('source_sha'), str) and re.fullmatch(r'[a-f0-9]{64}', marker['source_sha'])
             and marker.get('colour_space') in ('auto', 'hlg_rec2020', 'pq_rec2020', 'pq_display_p3')
             and type(marker.get('start_seconds')) in (int,float) and math.isfinite(marker['start_seconds'])
             and marker['start_seconds'] >= 0)
    if not (exr or video):
        raise ValueError('The HDR image identity is invalid. Import the EXR again.')
    value = json.dumps({'proxy_sha': proxy_sha, 'native_hdr': marker}, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(value.encode()).hexdigest()


def resolve_asset(asset, config, store, check_asset):
    marker = asset.get('native_hdr')
    if marker is None:
        return None
    validate_config(config)
    opening_identity(asset.get('sha'), marker)
    if store is None:
        from .studio import Store
        store = Store()
    if 'source_id' in marker:
        from .ltx_hdr_performance import source_interval
        source = store.load(marker['source_id'])
        descriptor = source_interval(source, store, check_asset, config,
            {'start': marker['start_seconds'], 'frames': 1, 'fps': 24})
        if not descriptor or descriptor['sha'] != marker['source_sha'] or descriptor['colour_space'] != marker['colour_space']:
            raise ValueError('The original HDR video changed. Review the source again.')
        return {'kind': 'video', 'source_id': marker['source_id'], 'source_sha': descriptor['sha'],
            'path': descriptor['path'], 'start_seconds': marker['start_seconds'], 'colour_space': marker['colour_space']}
    from .ltx_hdr_endpoint_routes import resolve_endpoint
    endpoint, _ = resolve_endpoint(store, check_asset, marker['asset_id'], marker['colour_space'])
    if endpoint['sha'] != marker['manifest_sha']:
        raise ValueError('The original HDR image changed. Import and review it again.')
    return endpoint


def resolve_opening(project, store, check_asset):
    opening = project.get('opening_input') or {}
    endpoint = resolve_asset(opening, project.get('config', {}), store, check_asset)
    if endpoint is None:
        return None
    if project.get('opening_key') != opening_identity(opening.get('sha'), opening['native_hdr']):
        raise ValueError('Review the matching HDR opening image before generation.')
    return {**endpoint, 'opening_key': project['opening_key']}


def make_opening_asset(store, check_asset, identity, colour='auto'):
    if not enabled():
        raise ValueError('Native HDR performance is an opt-in development preview.')
    from .ltx_hdr_endpoint_routes import endpoint_preview, resolve_endpoint
    import folder_paths
    endpoint, _ = resolve_endpoint(store, check_asset, identity, colour)
    proxy = endpoint_preview(store, check_asset, identity, colour)
    root = Path(folder_paths.get_input_directory()).resolve()
    relative = Path(proxy['preview']['subfolder']) / proxy['preview']['filename']
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to((root / 'genj_studio').resolve()):
        raise ValueError('The HDR viewing image is outside Studio storage.')
    marker = {'asset_id': identity, 'manifest_sha': endpoint['sha'], 'colour_space': colour}
    asset = {'id': uuid.uuid4().hex, 'kind': 'asset', 'asset_kind': 'image',
        'file': relative.as_posix(), 'sha': hashlib.sha256(path.read_bytes()).hexdigest(),
        'name': proxy['name'], 'width': proxy['width'], 'height': proxy['height'],
        'native_hdr': marker}
    opening_identity(asset['sha'], marker)
    check_asset(asset)
    store.save(asset)
    return copy.deepcopy(asset)


def inspect_readiness(get_path, node_mappings, output='hlg_and_exr', detector_paths=None):
    """Inspect actual phase dependencies without loading any model weights."""
    from .ltx25 import QUALIFIED_MODELS
    from .ltx25_hdr_plan import build_native_hdr_plan
    from .ltx_hdr_endpoints import VIDEO_VAE, MAX_PIXEL_FRAMES
    from .hdr_readiness import _MODEL_FIELDS
    asset = {'file': 'setup.png', 'sha': 'a' * 64}
    project = {'source': {**asset, 'file': 'setup.mp4'}, 'character': asset,
        'opening_input': asset, 'opening_key': 'setup-look', 'opening_approval': 'setup-look',
        'approval': 'setup-selection', 'review': 'setup-review',
        'audio': {**asset, 'file': 'setup.wav'}, 'ltx25_run': {'namespace': 'a' * 32},
        'config': {'edit_area': 'scene', 'resolution': 512, 'seed': 42}}
    models = {**QUALIFIED_MODELS, 'video_vae': VIDEO_VAE}
    kwargs = {'timeline': {'frames': 9, 'fps': 24, 'width': 512, 'height': 512, 'has_audio': True},
        'models': models, 'model_pins': {name: {'sha': 'b' * 64} for name in (*models, 'text_encoder')},
        'text_encoder_inputs': {'clip_name': 'gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors', 'type': 'ltxv', 'device': 'default'},
        'approval_key': 'setup-selection', 'original_audio_sha': 'c' * 64, 'union_downscale_factor': 2,
        'hdr_endpoint': {'manifest': 'setup.json', 'sha': 'd' * 64, 'opening_key': 'setup-look'}}
    plans = [build_native_hdr_plan(project, output=output, scenario=scenario, **kwargs)
             for scenario in ('original', 'replacement', 'silent')]
    video_project = copy.deepcopy(project)
    video_project['source']['native_hdr_video'] = {'asset_id':'e'*32, 'sha':'a'*64, 'colour_space':'auto'}
    video_source = {'asset_id':'e'*32, 'file':'setup.mp4', 'sha':'a'*64, 'path':'setup.mp4',
        'colour_space':'auto', 'start_seconds':0, 'frames':9, 'fps':24}
    video_endpoint = {'kind':'video', 'path':'setup.mp4', 'source_sha':'a'*64, 'colour_space':'auto',
        'start_seconds':0, 'opening_key':'setup-look'}
    video_kwargs = {**kwargs, 'hdr_endpoint':video_endpoint, 'hdr_source':video_source,
                    'timeline':{**kwargs['timeline'], 'start':0}}
    plans.append(build_native_hdr_plan(video_project, output=output, scenario='original', **video_kwargs))
    nodes = [node for plan in plans for graph in plan['phases'].values() for node in graph.values()]
    files = {}
    for node in nodes:
        field = _MODEL_FIELDS.get(node['class_type'])
        if not field:
            continue
        folder, key = field
        name = node['inputs'][key]
        try:
            present = bool(get_path(folder, name))
        except (KeyError, OSError):
            present = False
        files[folder, name] = {'folder': folder, 'filename': name, 'ready': present}
    for key in ('bbox_detector', 'pose_estimator'):
        name = models[key]
        files['controlnet_aux', name] = {'folder': 'controlnet_aux', 'filename': name,
            'ready': bool((detector_paths or {}).get(key))}
    missing = sorted({node['class_type'] for node in nodes} - set(node_mappings))
    return {'enabled': enabled(), 'experimental': True, 'route': 'ltx_hdr_performance',
        'files': list(files.values()), 'missingNodes': missing,
        'ready': not missing and all(f['ready'] for f in files.values()),
        'limits': {'maxSeconds': 5, 'maxPixelFrames': MAX_PIXEL_FRAMES}}


def register(studio, routes, response, check_asset):
    from aiohttp import web

    @routes.get('/zura/studio/ltx/hdr-performance/readiness')
    @routes.get('/genj/studio/ltx/hdr-performance/readiness')
    @response
    async def readiness(request):
        if not enabled():
            return web.json_response({'enabled': False, 'ready': False})
        import folder_paths
        import nodes
        from .studio import ltx25_detector_paths
        result = await asyncio.to_thread(inspect_readiness, folder_paths.get_full_path,
            nodes.NODE_CLASS_MAPPINGS, request.query.get('output', 'hlg_and_exr'), ltx25_detector_paths())
        return web.json_response(result)

    if not enabled():
        return

    @routes.post('/zura/studio/ltx/hdr-performance/opening')
    @routes.post('/genj/studio/ltx/hdr-performance/opening')
    @response
    async def opening(request):
        from .studio import media_url
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('Choose an uploaded EXR appearance image.')
        asset = await asyncio.to_thread(make_opening_asset, studio.store, check_asset,
            body.get('asset_id'), body.get('colour_space', 'auto'))
        path = Path(asset['file'])
        return web.json_response({**asset, 'url': media_url({'filename': path.name,
            'subfolder': path.parent.as_posix(), 'type': 'input'})})
