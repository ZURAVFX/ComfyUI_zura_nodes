"""Read-only setup checks derived from the actual bounded HDR graphs."""
from __future__ import annotations

from .hdr_studio import build_hdr_graph
from .hdr_native_graph import build_native_video_graph
from .hdr_prepare import MAX_PIXEL_FRAMES, sdr_frame_limit
import math

_MODEL_FIELDS = {
    'UNETLoader': ('diffusion_models', 'unet_name'),
    'VAELoader': ('vae', 'vae_name'),
    'CLIPLoader': ('text_encoders', 'clip_name'),
    'LTXICLoRALoaderModelOnly': ('loras', 'lora_name'),
    'LTXVLoadConditioning': ('embeddings', 'file_name'),
    'LatentUpscaleModelLoader': ('latent_upscale_models', 'model_name'),
}


def readiness(mode, output, get_path, node_mappings):
    if mode not in ('sdr', 'native'):raise ValueError('Choose SDR-to-HDR or HDR-to-HDR.')
    if output not in ('hlg_video','acescg_exr','hlg_and_exr'):raise ValueError('Choose an available HDR delivery.')
    if mode == 'sdr':
        graph=build_hdr_graph(source='readiness.mp4',start_frame=0,frame_count=9,fps=24,output=output,prefix='setup')
    else:
        graph=build_native_video_graph(source='readiness.mp4',start_frame=0,frame_count=9,fps=24,
            width=512,height=512,output=output,prefix='setup')
    seen=set();files=[]
    for node in graph.values():
        kind=node.get('class_type');field=_MODEL_FIELDS.get(kind)
        if not field:continue
        folder,key=field;name=node.get('inputs',{}).get(key)
        if not isinstance(name,str) or not name or (folder,name) in seen:continue
        seen.add((folder,name))
        try:present=bool(get_path(folder,name))
        except (KeyError,FileNotFoundError,OSError):present=False
        files.append({'folder':folder,'filename':name,'ready':present})
    missing_nodes=sorted({node['class_type'] for node in graph.values()}-set(node_mappings))
    return {'route':'hdr_sdr' if mode=='sdr' else 'hdr_native','files':files,'missingNodes':missing_nodes,
            'ready':all(item['ready'] for item in files) and not missing_nodes}


def frame_limit(mode, width, height):
    """The software padding budget, not a hardware capacity guarantee."""
    if mode not in ('sdr','native') or any(type(v) is not int or v < 32 or v % 2 for v in (width,height)):
        return None
    if mode == 'sdr':
        return sdr_frame_limit(width,height) if max(width,height)<=4096 else None
    if max(width,height)>2048:return None
    pw=max(512,math.ceil(width/64)*64);ph=max(512,math.ceil(height/64)*64)
    budget=min(121,MAX_PIXEL_FRAMES//(pw*ph))
    return 1+8*((budget-1)//8) if budget>=9 else 0


def register(routes,response):
    import asyncio
    from aiohttp import web
    @routes.get('/zura/studio/hdr/readiness')
    @routes.get('/genj/studio/hdr/readiness')
    @response
    async def inspect(request):
        import folder_paths
        import nodes
        result=await asyncio.to_thread(readiness,request.query.get('mode','sdr'),
            request.query.get('output','hlg_and_exr'),folder_paths.get_full_path,nodes.NODE_CLASS_MAPPINGS)
        try:
            width=int(request.query['width']);height=int(request.query['height'])
        except (KeyError,TypeError,ValueError):
            pass
        else:
            limit=frame_limit(request.query.get('mode','sdr'),width,height)
            if limit is not None:result['frameLimit']={'width':width,'height':height,'maxFrames':limit}
        return web.json_response(result)
