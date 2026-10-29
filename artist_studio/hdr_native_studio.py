"""Bounded, user-selected HDR video or EXR sequence preflight."""
from __future__ import annotations

import uuid
import math
from pathlib import Path

from .hdr_native_graph import build_native_video_graph


def build_asset_graph(asset, body, check_asset):
    import av
    from ..paintout.paintout import describe, selected_space
    start=body.get('start_frame',0);count=body.get('frame_count')
    if type(start) is not int or start<0 or type(count) is not int or count<1 or count>121:
        raise ValueError('Choose a non-negative first frame and 1–121 frames.')
    sequence=asset.get('asset_kind')=='hdr_sequence'
    if not sequence and asset.get('asset_kind') != 'video':raise ValueError('Choose HDR video or an EXR sequence.')
    manifest=check_asset(asset)
    if sequence:
        from .hdr_sequence import validate_manifest
        path,_=validate_manifest(manifest,asset['sha'],start,count)
    else:path=manifest
    info=describe(str(path))
    if info['kind'] != ('sequence' if sequence else 'video'):raise ValueError('Choose a valid HDR source.')
    if start+count>info['count']:raise ValueError('The selected range extends past the source video.')
    if not sequence and info.get('transfer') in ('bt709','iec61966-2-1'):
        raise ValueError('This source is SDR. Use SDR to HDR instead.')
    colour=body.get('colour_space','auto')
    choices=('auto','acescg','acescct','linear_rec709') if sequence else ('auto','hlg_rec2020','pq_rec2020')
    if colour not in choices:raise ValueError('Choose a supported HDR source colour space.')
    if not sequence and (info.get('transfer')=='smpte2084' and colour=='hlg_rec2020' or info.get('transfer')=='arib-std-b67' and colour=='pq_rec2020'):
        raise ValueError('The selected HDR colour space conflicts with the source transfer tags.')
    accepted=('acescg','acescct','linear_rec709') if sequence else ('hlg_rec2020','pq_rec2020')
    if selected_space(info,colour) not in accepted:raise ValueError('Choose a supported HDR source colour space.')
    if sequence:
        fps=body.get('sequence_fps',24)
        if isinstance(fps,bool) or not isinstance(fps,(int,float)) or not math.isfinite(fps) or not 1<=fps<=120:raise ValueError('Choose an EXR sequence frame rate between 1 and 120 fps.')
        has_audio=False
    else:
        fps=info['fps']
        with av.open(str(path)) as stream:has_audio=bool(stream.streams.audio)
    prefix='native_'+uuid.uuid4().hex
    graph=build_native_video_graph(source=str(path),start_frame=start,frame_count=count,fps=fps,
        width=info['width'],height=info['height'],prefix=prefix,colour_space=colour,has_audio=has_audio,
        output=body.get('output','hlg_and_exr'), sequence_manifest=str(manifest) if sequence else '',
        manifest_sha=asset.get('sha','') if sequence else '')
    return graph,{'prefix':prefix,'width':info['width'],'height':info['height'],'frames':count,
                  'fps':fps,'has_audio':has_audio,'output':body.get('output','hlg_and_exr')}


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
        elif body.get('source_kind','upload') in ('upload','sequence'):
            asset=studio.store.load(body.get('source_id',''))
            if (body.get('source_kind')=='sequence') != (asset.get('asset_kind')=='hdr_sequence'):
                raise ValueError('Choose the requested source type.')
            graph,details=await asyncio.to_thread(build_asset_graph,asset,body,check_asset)
        else:raise ValueError('Choose source footage or the latest LTX result.')
        if details['output'] in ('acescg_exr','hlg_and_exr'):
            from .hdr_package import preflight_archive
            await asyncio.to_thread(preflight_archive,folder_paths.get_output_directory())
        return web.json_response({'graph':graph,'details':details})

    from .hdr_sequence import register as register_sequence
    register_sequence(studio,routes,response)
