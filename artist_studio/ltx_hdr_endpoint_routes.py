"""Opt-in native HDR endpoint preparation using Studio-owned EXR assets."""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from .ltx_hdr_endpoints import build_native_endpoint_graph, MAX_PIXEL_FRAMES


def enabled():
    return os.environ.get('ZURA_LTX_HDR_ENDPOINTS', '0').strip() == '1'


def readiness(get_path, node_mappings, output='hlg_and_exr'):
    """Derive setup from both optional soundtrack paths, without loading models."""
    from .hdr_readiness import _MODEL_FIELDS
    asset = {'manifest': 'readiness', 'sha': '0'*64}
    graphs = [build_native_endpoint_graph(first=asset, last=asset, width=512, height=512,
        frames=9, prompt='Setup check', output=output, prefix='setup', audio_file=audio)
        for audio in (None, 'setup.wav')]
    files = {}
    for graph in graphs:
        for node in graph.values():
            field = _MODEL_FIELDS.get(node['class_type'])
            if not field: continue
            folder, key = field
            name = node['inputs'][key]
            try: present = bool(get_path(folder, name))
            except (KeyError, FileNotFoundError, OSError): present = False
            files[folder, name] = {'folder': folder, 'filename': name, 'ready': present}
    missing = sorted({n['class_type'] for g in graphs for n in g.values()} - set(node_mappings))
    return {'route': 'ltx_hdr_endpoints', 'enabled': enabled(), 'files': list(files.values()),
            'missingNodes': missing, 'ready': all(f['ready'] for f in files.values()) and not missing,
            'limits': {'minDimension': 512, 'maxDimension': 2048, 'dimensionStep': 64,
                       'maxFrames': 361, 'maxPixelFrames': MAX_PIXEL_FRAMES}}


def resolve_endpoint(store, check_asset, identity, colour='auto'):
    from .hdr_sequence import validate_manifest
    from ..paintout.paintout import describe, selected_space
    if colour not in ('auto', 'acescg', 'acescct', 'linear_rec709'):
        raise ValueError('Choose the EXR colour space.')
    asset = store.load(identity)
    if asset.get('asset_kind') != 'hdr_sequence' or asset.get('count') != 1:
        raise ValueError('Choose one uploaded EXR image for each endpoint.')
    manifest = check_asset(asset)
    directory, entries = validate_manifest(manifest, asset.get('sha', ''), 0, 1)
    if len(entries) != 1:
        raise ValueError('An endpoint must contain exactly one EXR frame.')
    info = describe(str(directory))
    if info['count'] != 1 or selected_space(info, colour) not in ('acescg', 'acescct', 'linear_rec709'):
        raise ValueError('Choose a supported EXR source colour space.')
    return {'manifest': str(manifest), 'sha': asset['sha'], 'colour_space': colour}, info


def endpoint_preview(store, check_asset, identity, colour='auto'):
    """Create only an SDR viewing proxy; generation still reads the EXR."""
    import numpy as np
    from PIL import Image
    from .hdr_sequence import validate_manifest
    from .hdr_native_source import load_native_hdr_frames
    from ..paintout.paintout import decode_ct, sdr_view
    asset, info = resolve_endpoint(store, check_asset, identity, colour)
    directory, _ = validate_manifest(asset['manifest'], asset['sha'], 0, 1)
    pixels, _ = load_native_hdr_frames(directory, 0, 1, colour, 24.)
    display = sdr_view(decode_ct(pixels), True)[0].clamp(0, 1).numpy()
    preview = Path(asset['manifest']).parent / ('endpoint_'+colour+'.png')
    height, width = display.shape[:2]
    image = Image.fromarray((display*255).round().astype(np.uint8))
    image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    image.save(preview)
    import folder_paths
    relative = preview.relative_to(Path(folder_paths.get_input_directory()).resolve())
    return {'id': identity, 'asset_kind': 'hdr_endpoint', 'colour_space': colour,
            'name': Path(info['files'][0]).name, 'width': width, 'height': height,
            'preview': {'filename': relative.name, 'subfolder': relative.parent.as_posix(), 'type': 'input'}}


def prepare_graph(store, check_asset, body):
    if not isinstance(body, dict): raise ValueError('Choose native HDR generation settings.')
    first, _ = resolve_endpoint(store, check_asset, body.get('first_id'), body.get('first_colour', 'auto'))
    last = None
    if body.get('last_id'):
        last, _ = resolve_endpoint(store, check_asset, body['last_id'], body.get('last_colour', 'auto'))
    audio = None
    if body.get('audio_enabled'):
        # The normal first/last uploader stores an input-relative audio path.
        # Resolve it here rather than accepting an arbitrary file path.
        import folder_paths
        reference = body.get('audio_file')
        if not isinstance(reference, str) or not reference:
            raise ValueError('Choose an audio reference or turn Audio reference off.')
        root = Path(folder_paths.get_input_directory()).resolve()
        path = (root/reference).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in ('.wav','.mp3','.m4a','.flac','.ogg','.aac','.mp4','.mov','.webm'):
            raise ValueError('Choose an uploaded audio reference.')
        audio = path.relative_to(root).as_posix()
    graph = build_native_endpoint_graph(first=first, last=last,
        width=body.get('width'), height=body.get('height'), frames=body.get('frames'),
        prompt=body.get('prompt'), seed=body.get('seed', 42), output=body.get('output', 'hlg_and_exr'),
        prefix='endpoint_'+uuid.uuid4().hex, audio_file=audio, audio_start=body.get('audio_start', 0.))
    from .custom_loras import apply_installed_ltx_loras
    return apply_installed_ltx_loras(graph, body.get('custom_loras', []))


def register(studio, routes, response, check_asset):
    from aiohttp import web

    @routes.get('/zura/studio/ltx/hdr-endpoints/readiness')
    @routes.get('/genj/studio/ltx/hdr-endpoints/readiness')
    @response
    async def inspect(request):
        if not enabled(): return web.json_response({'enabled': False, 'ready': False})
        import folder_paths
        import nodes
        result = await asyncio.to_thread(readiness, folder_paths.get_full_path,
            nodes.NODE_CLASS_MAPPINGS, request.query.get('output', 'hlg_and_exr'))
        return web.json_response(result)

    if not enabled(): return

    @routes.post('/zura/studio/ltx/hdr-endpoints/preview')
    @routes.post('/genj/studio/ltx/hdr-endpoints/preview')
    @response
    async def preview(request):
        body = await request.json()
        if not isinstance(body, dict): raise ValueError('Choose an uploaded EXR endpoint.')
        result = await asyncio.to_thread(endpoint_preview, studio.store, check_asset,
            body.get('asset_id'), body.get('colour_space', 'auto'))
        return web.json_response(result)

    @routes.post('/zura/studio/ltx/hdr-endpoints/graph')
    @routes.post('/genj/studio/ltx/hdr-endpoints/graph')
    @response
    async def graph(request):
        body = await request.json()
        prepared = await asyncio.to_thread(prepare_graph, studio.store, check_asset, body)
        import folder_paths
        import nodes
        fields = {'UNETLoader':('diffusion_models','unet_name'), 'CLIPLoader':('text_encoders','clip_name'),
                  'VAELoader':('vae','vae_name'), 'LatentUpscaleModelLoader':('latent_upscale_models','model_name')}
        missing = set(prepared_node['class_type'] for prepared_node in prepared.values()) - set(nodes.NODE_CLASS_MAPPINGS)
        for node in prepared.values():
            if node['class_type'] in fields:
                folder, key = fields[node['class_type']]
                name = node['inputs'][key]
                if not folder_paths.get_full_path(folder, name): missing.add(name)
        if missing: raise ValueError('Native HDR setup is incomplete: '+', '.join(sorted(missing)))
        if body.get('output', 'hlg_and_exr') in ('acescg_exr','hlg_and_exr'):
            from .hdr_package import preflight_archive
            await asyncio.to_thread(preflight_archive, folder_paths.get_output_directory())
        return web.json_response({'graph': prepared, 'native_hdr': True})
