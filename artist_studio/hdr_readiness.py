"""Read-only setup checks derived from the actual bounded HDR graphs."""
from __future__ import annotations

from .hdr_studio import build_hdr_graph
from .hdr_native_graph import build_native_video_graph

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
        return web.json_response(result)
