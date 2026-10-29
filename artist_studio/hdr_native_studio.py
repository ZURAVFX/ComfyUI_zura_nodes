"""Bounded, user-selected HDR video preflight for LTX 2.5 native HDR."""
from __future__ import annotations

import uuid
from pathlib import Path

from .hdr_native_graph import build_native_video_graph


def build_asset_graph(asset, body, check_asset):
    import av
    from ..paintout.paintout import describe, selected_space
    if asset.get('asset_kind') != 'video': raise ValueError('Choose HDR source video.')
    path=check_asset(asset);info=describe(str(path))
    if info['kind']!='video':raise ValueError('Choose HDR video footage.')
    start=body.get('start_frame',0);count=body.get('frame_count')
    if type(start) is not int or start<0 or type(count) is not int or count<1 or count>121:
        raise ValueError('Choose a non-negative first frame and 1–121 frames.')
    if start+count>info['count']:raise ValueError('The selected range extends past the source video.')
    if info.get('transfer') in ('bt709','iec61966-2-1'):
        raise ValueError('This source is SDR. Use SDR to HDR instead.')
    if info.get('transfer') == 'smpte2084':
        raise ValueError('PQ HDR input is not supported in this preview yet. Use HLG video.')
    colour=body.get('colour_space','auto')
    if colour not in ('auto','hlg_rec2020'):raise ValueError('This preview currently accepts HLG video only.')
    if selected_space(info,colour) != 'hlg_rec2020':raise ValueError('Choose HLG source video; PQ and EXR input are not supported here yet.')
    with av.open(str(path)) as stream:has_audio=bool(stream.streams.audio)
    prefix='native_'+uuid.uuid4().hex
    graph=build_native_video_graph(source=str(path),start_frame=start,frame_count=count,fps=info['fps'],
        width=info['width'],height=info['height'],prefix=prefix,colour_space=colour,has_audio=has_audio,
        output=body.get('output','hlg_and_exr'))
    return graph,{'prefix':prefix,'width':info['width'],'height':info['height'],'frames':count,
                  'fps':info['fps'],'has_audio':has_audio,'output':body.get('output','hlg_and_exr')}


def register(studio,routes,response,check_asset):
    import asyncio
    from aiohttp import web
    @routes.post('/zura/studio/hdr/native-graph')
    @routes.post('/genj/studio/hdr/native-graph')
    @response
    async def prepare(request):
        body=await request.json()
        import folder_paths
        from .hdr_native_graph import REFINER
        required=(('diffusion_models','ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors'),
                  ('vae','ltx-2.5-video-vae-bf16.safetensors'),
                  ('text_encoders','gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors'),
                  ('latent_upscale_models','ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors'),
                  ('loras',REFINER))
        missing=[name for folder,name in required if not folder_paths.get_full_path(folder,name)]
        if missing:raise ValueError('Native HDR needs these installed files: '+', '.join(missing))
        if body.get('source_kind','upload')=='result':
            project=studio.store.load(body.get('project_id',''))
            if project.get('config',{}).get('engine')!='local' or not project.get('results'):
                raise ValueError('Generate an LTX video before choosing its result.')
            ref=project['results'][-1].get('asset') or {};root=Path(folder_paths.get_output_directory()).resolve()
            path=(root/ref.get('subfolder','')/ref.get('filename','')).resolve()
            if ref.get('type')!='output' or not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in ('.mp4','.mov','.mkv','.webm'):
                raise ValueError('The saved LTX result is unavailable.')
            graph,details=await asyncio.to_thread(build_asset_graph,{'asset_kind':'video'},body,lambda _:path)
        elif body.get('source_kind','upload')=='upload':
            asset=studio.store.load(body.get('source_id',''))
            graph,details=await asyncio.to_thread(build_asset_graph,asset,body,check_asset)
        else:raise ValueError('Choose source footage or the latest LTX result.')
        if details['output'] in ('acescg_exr','hlg_and_exr'):
            from .hdr_package import preflight_archive
            await asyncio.to_thread(preflight_archive,folder_paths.get_output_directory())
        return web.json_response({'graph':graph,'details':details})
