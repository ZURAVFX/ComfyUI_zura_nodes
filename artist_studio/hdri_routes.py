"""Environment editing uses CPU floats; Panorama supplies its native composer."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import uuid

from aiohttp import web
import numpy as np
import torch

from . import hdri


def reference_path(reference):
    import folder_paths
    kind = reference.get('type', 'input')
    if kind not in ('input', 'output'): raise ValueError('Choose a Studio image.')
    root = Path(folder_paths.get_input_directory() if kind == 'input' else folder_paths.get_output_directory()).resolve()
    name = reference.get('file') or str(Path(reference.get('subfolder', '')) / reference.get('filename', ''))
    path = (root / name).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file(): raise ValueError('Choose an image inside Studio inputs or outputs.')
    return path


def output_path(name):
    import folder_paths
    folder = Path(folder_paths.get_output_directory()) / 'ZURA STUDIO' / 'hdri'
    folder.mkdir(parents=True, exist_ok=True)
    return folder/name, {'filename': name, 'subfolder': 'ZURA STUDIO/hdri', 'type': 'output'}


def preview_file(image, key):
    from PIL import Image
    path, reference = output_path(key+'.png')
    rgb = (np.clip(image,0,1)*255).round().astype(np.uint8)
    picture = Image.fromarray(rgb);picture.thumbnail((2048,2048))
    picture.save(path)
    return {**reference,'width':picture.width,'height':picture.height}


def params(body):
    from ..paintout.paintout import to_linear
    result = {key: body.get(key, default) for key, default in [('yaw',0),('exposure',0),('lights',[])]}
    result['lights'] = [{**light,'color':to_linear(torch.tensor(light.get('color',[1,1,1]),dtype=torch.float32),'srgb_display').tolist()}
                        for light in result['lights']]
    return result


def register(studio, routes, response, check_asset):
    operation_lock = asyncio.Lock()
    def source(body):
        if body.get('source_id'):
            asset = studio.store.load(body['source_id']);check_asset(asset)
            return reference_path({'file':asset['file']}), body.get('color_space',asset.get('color_space','auto'))
        return reference_path(body.get('file') or {}), body.get('color_space','srgb_display')

    def rendered(body):
        path, space = source(body)
        linear, used = hdri.read_environment(path,space)
        if linear.shape[0]*linear.shape[1]>8192*4096:raise ValueError('Use an environment up to 8K × 4K.')
        result = hdri.build_environment(linear,**params(body))
        return result, {'source_hdr':path.suffix.lower() in ('.exr','.hdr'), 'color_space':used, **hdri.summary(result)}

    @routes.post('/zura/studio/hdri/import')
    @response
    async def import_environment(request):
        import folder_paths
        reader=await request.multipart();part=await reader.next()
        if not part or not part.filename:raise ValueError('Choose a panorama or HDRI.')
        suffix=Path(part.filename).suffix.lower()
        if suffix not in ('.png','.jpg','.jpeg','.webp','.exr','.hdr','.tif','.tiff'):raise ValueError('Choose an image, EXR or Radiance HDR file.')
        identity=uuid.uuid4().hex;relative=Path('zura_hdri')/identity/('source'+suffix)
        path=Path(folder_paths.get_input_directory())/relative;path.parent.mkdir(parents=True,exist_ok=True)
        size=0;digest=hashlib.sha256()
        try:
            with path.open('wb') as stream:
                while chunk:=await part.read_chunk():
                    size+=len(chunk)
                    if size>500*1024*1024:raise ValueError('Use an environment smaller than 500 MB.')
                    stream.write(chunk);digest.update(chunk)
            # Colour selection is explicit for untagged EXRs; retain the file if
            # Auto cannot identify it so the artist can choose its actual space.
            colour=request.query.get('color_space','auto')
            linear,used=await asyncio.to_thread(hdri.read_environment,path,colour)
            asset={'id':identity,'kind':'asset','asset_kind':'image','file':relative.as_posix(),
                   'sha':digest.hexdigest(),'name':Path(part.filename).name,'color_space':used,
                   'width':int(linear.shape[1]),'height':int(linear.shape[0])}
            studio.store.save(asset)
            proxy=await asyncio.to_thread(preview_file,hdri.preview_environment(linear),identity+'_import')
            return web.json_response({'source_id':identity,'file':proxy,'name':asset['name'],
                                      'source_hdr':suffix in ('.exr','.hdr'),**hdri.summary(linear)})
        except BaseException:
            path.unlink(missing_ok=True);raise

    @routes.post('/zura/studio/hdri/preview')
    @response
    async def preview(request):
        body=await request.json()
        def work():
            image,meta=rendered(body)
            key=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()[:24]
            proxy=preview_file(hdri.preview_environment(image,body.get('view_exposure',0)),key)
            return {'file':proxy,**meta}
        async with operation_lock:
            return web.json_response(await asyncio.to_thread(work))

    @routes.post('/zura/studio/hdri/export')
    @response
    async def export(request):
        body=await request.json()
        def work():
            image,meta=rendered(body);path,reference=output_path('environment_'+uuid.uuid4().hex[:12]+'.exr')
            hdri.write_environment(path,image,body.get('export_space','linear_rec709'))
            return {'file':reference,**meta}
        async with operation_lock:
            return web.json_response(await asyncio.to_thread(work))

    @routes.post('/zura/studio/hdri/scene')
    @response
    async def scene(request):
        body=await request.json()
        def work():
            import nodes
            if 'PanoramaStudio' not in nodes.NODE_CLASS_MAPPINGS:raise ValueError('Install Panorama Stickers through the model setup panel, then restart ComfyUI.')
            if body.get('file') or body.get('source_id'):
                path,space=source(body);linear,_=hdri.read_environment(path,space)
            else:
                linear=np.zeros((128,256,3),np.float32);linear[...,1]=1.0
            proxy=hdri.preview_environment(linear)
            if max(proxy.shape[:2])>2048:
                from PIL import Image
                image=Image.fromarray((proxy*255).round().astype(np.uint8));image.thumbnail((2048,2048));proxy=np.asarray(image,np.float32)/255
            state=body.get('state')
            state=json.loads(state) if isinstance(state,str) else state or {'version':2,'camera':{},'stickers':[]}
            state['timeline']={'fps':24,'length':1}
            state['camera'].update({'projection':'erp','erp_range':'360','curve':{'value':0,'keyframes':[]},
                                    'fov':{'value':360,'keyframes':[]},'rotation':{'value':{'yaw_deg':0,'pitch_deg':0,'roll_deg':0},'keyframes':[]}})
            erp=linear.shape[1]==2*linear.shape[0]
            tensor=torch.from_numpy(np.ascontiguousarray(proxy))[None]
            result=nodes.NODE_CLASS_MAPPINGS['PanoramaStudio'].execute(background_color='#00ff00',background_range='360',
                megapixels=max(.125,min(8.,float(body.get('width',2048))*float(body.get('height',1024))/1_000_000)),multiple=16,state_json=json.dumps(state),**({'background':tensor} if erp else {'sticker':tensor}))
            image=result.result[1][0].detach().cpu().numpy()
            identity=uuid.uuid4().hex[:12]
            file=preview_file(image,'composition_'+identity)
            # Keep the full native composition for export. The browser proxy is
            # bounded and must never become the artist's final-resolution master.
            from ..paintout.paintout import to_linear
            full_path,full_reference=output_path('composition_'+identity+'.exr')
            linear=to_linear(torch.from_numpy(np.ascontiguousarray(image)),'srgb_display').numpy()
            hdri.write_environment(full_path,linear,'acescg')
            return {'file':file,'composition_file':full_reference,'ui':result.ui,'state':json.dumps(state),'port': 'background' if erp else 'sticker',
                    'source_file':preview_file(proxy,'source_'+uuid.uuid4().hex[:12]),'width':int(image.shape[1]),'height':int(image.shape[0])}
        async with operation_lock:
            return web.json_response(await asyncio.to_thread(work))
