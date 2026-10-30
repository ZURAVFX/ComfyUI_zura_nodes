"""Bounded SDR-to-HDR graph for a future Studio integration.

Source paths must be resolved from Studio's approved assets by the caller;
this module does not expose an arbitrary-path HTTP endpoint.
"""
from __future__ import annotations

import math
import re
import uuid

from .hdr_delivery import ltx25_sdr_to_hdr_dynamic_graph
from .hdr_source import MAX_FRAMES, SDR_SPACES


def build_hdr_graph(*, source, start_frame, frame_count, fps, colour_space='auto',
                    output='hlg_and_exr', prefix, has_audio=False, seed=42,
                    model='ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors',
                    video_vae='ltx-2.5-video-vae-bf16.safetensors',
                    audio_vae='ltx-2.5-audio-vae-bf16.safetensors'):
    if not isinstance(source,str) or not source.strip():raise ValueError('Choose source footage.')
    if type(start_frame) is not int or start_frame<0 or type(frame_count) is not int or not 1<=frame_count<=MAX_FRAMES:
        raise ValueError(f'Choose an existing range of 1–{MAX_FRAMES} frames.')
    if not isinstance(fps,(float,int)) or isinstance(fps,bool) or not math.isfinite(fps) or not 1<=fps<=120:
        raise ValueError('Choose a valid source frame rate.')
    if colour_space not in ('auto', *SDR_SPACES):raise ValueError('Choose the source SDR colour space.')
    if type(has_audio) is not bool:raise ValueError('Invalid source audio state.')
    if not isinstance(prefix,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',prefix):raise ValueError('Invalid output name.')
    def node(kind, **inputs):return {'class_type':kind,'inputs':inputs}
    graph={'zura_hdr_source':node('ZuraHDRLoadSDRSource',source=source,start_frame=start_frame,
        frame_count=frame_count,colour_space=colour_space,sequence_fps=float(fps))}
    if has_audio:
        graph['zura_hdr_audio_source']=node('ZuraHDRLoadAudioRange',source=source,start_frame=start_frame,
            frame_count=frame_count,fps=float(fps))
    graph.update(ltx25_sdr_to_hdr_dynamic_graph(['zura_hdr_source',0],fps=float(fps),model=model,
        video_vae=video_vae,audio_vae=audio_vae,output=output,prefix=prefix,seed=seed,
        audio=['zura_hdr_audio_source',0] if has_audio else None))
    if output in ('acescg_exr','hlg_and_exr'):
        graph['zura_hdr_archive']=node('ZuraHDRPackageACEScct',images=['hdr_unpad_raster',0],prefix=prefix)
    # Native LTX tonemap produces a viewable SDR proxy; EXR/video retain HDR.
    if 'zura_hdr_exr' in graph:
        preview=['zura_hdr_exr',0]
    else:
        graph['zura_hdr_preview_tonemap']=node('LTXVHDRDecodePostprocess',image=['hdr_unpad_raster',0],
            transfer='acescct',save_exr=False,exr_color_space='acescg',output_dir='genj/hdr/'+prefix,
            filename_prefix='frame',half_precision=True)
        preview=['zura_hdr_preview_tonemap',0]
    video={'images':preview,'fps':float(fps)}
    if has_audio:video['audio']=['zura_hdr_trim_audio',0]
    graph['zura_hdr_preview_video']=node('CreateVideo',**video)
    graph['zura_hdr_save_preview']=node('ZuraHDRSaveExactRate',video=['zura_hdr_preview_video',0],
        filename_prefix='genj/hdr/'+prefix+'_preview',fps=float(fps))
    return graph


def build_asset_graph(asset, body, check_asset):
    """Preflight an existing Studio asset before preparing an editable graph."""
    from ..paintout.paintout import describe, selected_space
    import av
    if asset.get('asset_kind')!='video':raise ValueError('Choose an uploaded source video.')
    path=check_asset(asset)
    info=describe(str(path))
    if info['kind']!='video':raise ValueError('Choose video footage.')
    if info['width']%2 or info['height']%2:
        raise ValueError('HDR video and its preview currently require even source dimensions. Pad the source by one pixel and retry.')
    start=body.get('start_frame',0); count=body.get('frame_count')
    if type(start) is not int or start<0 or type(count) is not int or not 1<=count<=MAX_FRAMES:
        raise ValueError(f'Choose 1–{MAX_FRAMES} frames and a non-negative start frame.')
    if start+count>info['count']:raise ValueError('The selected range extends past the source video.')
    from .hdr_source import MAX_PIXEL_FRAMES
    if info['width']*info['height']*count>MAX_PIXEL_FRAMES:
        raise ValueError('This selection is too large for one HDR conversion. Choose fewer frames or smaller footage.')
    if info.get('transfer') in ('arib-std-b67','smpte2084'):
        raise ValueError('This source is HDR. The SDR-to-HDR route requires SDR footage.')
    colour=body.get('colour_space','auto')
    if colour not in ('auto',*SDR_SPACES):raise ValueError('Choose the source SDR colour space.')
    if selected_space(info,colour) not in SDR_SPACES:raise ValueError('Choose a supported SDR source colour space.')
    fps=info['fps']
    with av.open(str(path)) as input_video:has_audio=bool(input_video.streams.audio)
    name='shot_'+uuid.uuid4().hex
    graph=build_hdr_graph(source=str(path),start_frame=start,frame_count=count,fps=fps,
                          colour_space=colour,output=body.get('output','hlg_and_exr'),
                          prefix=name,has_audio=has_audio,seed=body.get('seed',42))
    return graph, {'prefix':name,'width':info['width'],'height':info['height'],
                   'frames':count,'fps':fps,'has_audio':has_audio,'output':body.get('output','hlg_and_exr')}


def register(studio, routes, response, check_asset):
    """Expose preflight only: graph is still queued through standard Comfy."""
    import asyncio
    from aiohttp import web
    @routes.post('/zura/studio/hdr/graph')
    @routes.post('/genj/studio/hdr/graph')
    @response
    async def prepare(request):
        data=await request.json()
        if data.get('source_kind','upload')=='result':
            import folder_paths
            from pathlib import Path
            project=studio.store.load(data.get('project_id',''))
            if project.get('config',{}).get('engine')!='local' or not project.get('results'):
                raise ValueError('Generate an LTX video before converting the latest result.')
            result=project['results'][-1]; ref=result.get('asset') or {}
            base=Path(folder_paths.get_output_directory()).resolve()
            path=(base/ref.get('subfolder','')/ref.get('filename','')).resolve()
            if ref.get('type')!='output' or not path.is_relative_to(base) or not path.is_file() or path.suffix.lower() not in ('.mp4','.mov','.mkv','.webm'):
                raise ValueError('The saved LTX result is unavailable.')
            graph,details=await asyncio.to_thread(build_asset_graph,{'asset_kind':'video'},data,lambda _:path)
        elif data.get('source_kind','upload')=='upload':
            asset=studio.store.load(data.get('source_id',''))
            graph,details=await asyncio.to_thread(build_asset_graph,asset,data,check_asset)
        else:raise ValueError('Choose source footage or the latest LTX result.')
        from .custom_loras import apply_installed_ltx_loras
        graph = await asyncio.to_thread(apply_installed_ltx_loras, graph, data.get('custom_loras', []))
        if details['output'] in ('acescg_exr','hlg_and_exr'):
            import folder_paths
            from .hdr_package import preflight_archive
            await asyncio.to_thread(preflight_archive, folder_paths.get_output_directory())
        return web.json_response({'graph':graph,'details':details})
