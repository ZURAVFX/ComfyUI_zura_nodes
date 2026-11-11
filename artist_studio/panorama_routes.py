"""Validated graph preparation; runs use Studio's owned Comfy submissions."""
import asyncio
import sys
import math
from pathlib import Path

from aiohttp import web

from .panorama_camera import RECIPE_VERSION, MODELS, build_graph, camera_state, cache_path, digest, plan


def readiness():
    import folder_paths
    import nodes
    # Derive dependencies from all real stages, including optional look images.
    # An abbreviated node list used to mark fresh installations as ready.
    source = {'sha': '0' * 64, 'duration': 2, 'has_audio': True, 'file': 'setup.mp4'}
    selection = plan(source, {'two_stage': True})
    needed = set()
    for stage in ('geometry', 'warp', 'render'):
        graph = build_graph(source, selection, None, stage, warp='setup.mp4', look='setup.png')
        needed.update(node['class_type'] for node in graph.values())
    missing_nodes = sorted(needed - nodes.NODE_CLASS_MAPPINGS.keys())
    files = []
    for category, name in MODELS.values():
        try:
            ready = bool(folder_paths.get_full_path(category, name))
        except (KeyError, OSError):
            ready = False
        files.append({'folder': category, 'filename': name, 'ready': ready})
    missing = missing_nodes + [file['filename'] for file in files if not file['ready']]
    unavailable = [str(getattr(module, 'FEATURE_3D_UNAVAILABLE')) for name, module in tuple(sys.modules.items())
                   if 'comfyui_pano_suite' in name and name.endswith('.core_adapters') and getattr(module, 'FEATURE_3D_UNAVAILABLE', None)]
    return {'ready': not missing and not unavailable, 'missing': missing, 'errors': unavailable,
            'route': 'panorama', 'files': files, 'missingNodes': missing_nodes,
            'recipe': RECIPE_VERSION, 'source_fps': True, 'max_seconds': 5}


def warp_path(asset, selection, state):
    import folder_paths
    filename = asset.get('filename', '')
    prefix = 'warp_' + digest([selection['key'], state])[:20] + '_'
    if (asset.get('type', 'output') != 'output' or asset.get('subfolder') != 'genj/panorama'
            or '/' in filename or '\\' in filename or not filename.startswith(prefix) or not filename.endswith('.mp4')):
        raise ValueError('Camera changed. Review a new warp preview before rendering.')
    root = (Path(folder_paths.get_output_directory()) / 'genj' / 'panorama').resolve()
    path = (root / filename).resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError('Choose a reviewed Panorama warp.')
    import av
    with av.open(str(path)) as clip:
        stream = clip.streams.video[0]
        count = sum(1 for _ in clip.decode(video=0))
        if count != selection['frames'] or not math.isclose(float(stream.average_rate or 0), selection['fps'], abs_tol=.001):
            raise ValueError('Camera preview has a different timeline. Prepare it again.')
    return f'genj/panorama/{filename} [output]'


def register(studio, routes, response, check_asset):
    @routes.get('/zura/studio/panorama/status')
    @routes.get('/genj/studio/panorama/status')
    @response
    async def status(request):
        return web.json_response(await asyncio.to_thread(readiness))

    @routes.post('/zura/studio/panorama/graph')
    @routes.post('/genj/studio/panorama/graph')
    @response
    async def graph(request):
        data = await request.json()
        source = studio.store.load(data['source_id'])
        if source.get('asset_kind') != 'video':
            raise ValueError('Import a source video.')
        path = await asyncio.to_thread(check_asset, source)
        def source_rate():
            import av
            with av.open(str(path)) as clip:
                stream = clip.streams.video[0]
                return float(stream.average_rate or stream.guessed_rate or 24)
        source = {**source, 'fps': await asyncio.to_thread(source_rate)}
        selection = plan(source, data.get('config', {}))
        state = camera_state(data.get('state'), selection)
        stage = data.get('stage', 'geometry')
        if stage != 'geometry' and not cache_path(selection['key']).is_file():
            raise ValueError('Prepare geometry before editing this camera.')
        warp = None
        if stage == 'render':
            warp = await asyncio.to_thread(warp_path, data.get('warp') or {}, selection, state)
        look = None
        if data.get('look_id'):
            image = studio.store.load(data['look_id'])
            if image.get('asset_kind') != 'image':
                raise ValueError('Choose a finished look image.')
            await asyncio.to_thread(check_asset, image)
            look = image['file']
        graph = build_graph(source, selection, state, stage, warp=warp, look=look,
                            prompt=str(data.get('prompt', ''))[:12000], seed=int(data.get('seed', 1052)))
        return web.json_response({'graph': graph, 'selection': selection, 'state': state,
                                 'warp_key': digest([selection['key'], state])})
