"""Reattach original HDR beauty to an SDR-view-generated Alpha Gen matte."""
from fractions import Fraction
import json
from pathlib import Path
import shutil
import threading
import types
import uuid

import numpy as np
import torch

from . import display_view_routes as display
from . import model_view

HDR_SPACES={'acescg','acescct','linear_rec709','hlg_rec2020','pq_rec2020','pq_display_p3'}


def bind_original(value,info,store,check_asset,roots):
    if not value:return None
    if not isinstance(value,str) or len(value.encode('utf-8'))>8192:raise ValueError('The original alpha source binding is invalid.')
    request=json.loads(value)
    if not isinstance(request,dict) or set(request)!={'asset_id','proxy_id'}:raise ValueError('Choose a registered original alpha source.')
    proxy=store.load(request['proxy_id']);original=store.load(request['asset_id'])
    proxy_path=check_asset(proxy).resolve()
    if proxy_path!=Path(info['source_path']).resolve():raise ValueError('The alpha model view belongs to a different original.')
    processing=proxy.get('processingView',{})
    if processing.get('kind')!='sdr8_inference' or processing.get('originalAssetId')!=original['id']:raise ValueError('The original alpha source is not bound to this model view.')
    space=processing.get('sourceColour')
    if space not in HDR_SPACES:return None
    resolved=display.resolve_original({'asset_id':original['id']},store,check_asset,roots)
    start=processing.get('originalStartFrame')
    if type(start) is not int or start<0:raise ValueError('The original alpha source interval is invalid.')
    start+=info['start_frame'];count=info['frame_count'];rate=Fraction(info['fps_rational'])
    body={'startFrame':start,'frameCount':count,'frameRate':{'numerator':rate.numerator,'denominator':rate.denominator}}
    model_view._range(body,resolved['metadata'])
    original['sha']  # Source validation is performed by the guarded resolver.
    source_hash,scope=model_view._source_hash(resolved,start,count,None)
    resolved['revalidate']()
    return {'schemaVersion':1,'asset_id':original['id'],'proxy_id':proxy['id'],'assetSha':original['sha'],
            'proxySha':proxy['sha'],'sourceHash':source_hash,'hashScope':scope,'colour_space':space,
            'startFrame':start,'frameCount':count,'frameRate':body['frameRate']}


def _processor(space):
    from ..comfylink import display_view
    description=display_view.describe();config=display_view._config(description['config'])
    def name(key):return next((config.getColorSpace(value).getName() for value in display._SPACES[key] if config.getColorSpace(value)),None)
    source,target=name(space),name('acescg')
    if not source or not target:raise ValueError('The installed colour configuration cannot preserve this original HDR beauty.')
    return None if source==target else config.getProcessor(source,target).getDefaultCPUProcessor()


def write_original_alpha(binding,images,info,store,check_asset,roots,output,*,check_cancelled=lambda:None):
    """Publish native HDR and final FLOAT A; previews remain separate SDR files."""
    from .alpha_matte import AlphaFloatWriter,final_alpha_frames
    from .hdr_alpha import HDRAlphaSource
    from .hdr_chunk_exr import export_rgba_exr_zip
    request=json.dumps({'asset_id':binding['asset_id'],'proxy_id':binding['proxy_id']})
    current=bind_original(request,info,store,check_asset,roots)
    if current!=binding:raise ValueError('The original HDR source changed after alpha preparation.')
    original=display.resolve_original({'asset_id':binding['asset_id']},store,check_asset,roots)
    start,count,space=binding['startFrame'],binding['frameCount'],binding['colour_space']
    rate=Fraction(info['fps_rational']);processor=_processor(space)
    if info['width']*info['height']>model_view.MAX_PIXELS:raise ValueError('Original HDR alpha export supports at most 16 MP per frame; the original is retained.')
    if shutil.disk_usage(output).free<count*info['width']*info['height']*20+64*1024*1024:raise ValueError('There is insufficient space for original HDR beauty and its FLOAT matte.')
    writer=AlphaFloatWriter(output,{**info,'start_frame':start})
    archive=None
    original_alpha_info={**info,'pixel_format':None}
    def frames():return model_view._frames(original,{'asset_id':binding['asset_id']},start,count,space,store,check_asset,roots)
    try:
        reader=frames();actual=0
        try:
            masks=final_alpha_frames(images,original_alpha_info,info['source_path'],'',check_cancelled=check_cancelled)
            for index,((rgba,actual_space),matte) in enumerate(zip(reader,masks)):
                check_cancelled()
                if actual_space!=space or rgba.shape!=(info['height'],info['width'],4):raise ValueError('The original beauty no longer matches its alpha matte.')
                if not np.isfinite(rgba).all() or np.any(rgba[...,3]<0) or np.any(rgba[...,3]>1):raise ValueError('The original HDR beauty contains invalid samples or alpha.')
                writer.write(index,np.ascontiguousarray(rgba[...,3]*matte,dtype='<f4'));actual+=1
            if actual!=count:raise ValueError('The original beauty ended before its alpha matte.')
        finally:reader.close()
        original['revalidate']();alpha=writer.finish()
        alpha_source=HDRAlphaSource(output,alpha,width=info['width'],height=info['height'],count=count,frame_rate=rate)
        def stitched():
            reader=frames();actual=0
            try:
                for rgba,actual_space in reader:
                    check_cancelled()
                    if actual_space!=space or rgba.shape!=(info['height'],info['width'],4):raise ValueError('The original HDR beauty changed during export.')
                    rgb=np.array(rgba[...,:3],dtype=np.float32,order='C')
                    if processor:processor.applyRGB(rgb)
                    if not np.isfinite(rgb).all():raise ValueError('The original HDR colour transform produced invalid RGB.')
                    yield torch.from_numpy(rgb)[None];actual+=1
                if actual!=count:raise ValueError('The original HDR beauty has the wrong frame count.')
                original['revalidate']()
            finally:reader.close()
        staged=types.SimpleNamespace(width=info['width'],height=info['height'],cancelled=threading.Event(),
            plan=[types.SimpleNamespace(start=0,count=count)],stitched=stitched)
        archive=export_rgba_exr_zip(staged,output,'alpha_native_'+uuid.uuid4().hex,alpha_source=alpha_source,frame_rate=rate,linear_rgb=True)
        check_cancelled()
        if bind_original(request,info,store,check_asset,roots)!=binding:raise ValueError('The original HDR source changed while exporting its alpha.')
        relative=archive.relative_to(Path(output).resolve())
        return alpha,{'filename':relative.name,'subfolder':relative.parent.as_posix(),'type':'output','role':'native_hdr',
                     'colour':{'encoding':'acescg','sceneLinear':True},'alpha':'straight'}
    except BaseException:
        writer.abort()
        if archive is not None:archive.unlink(missing_ok=True)
        if writer.published:
            # This writer owns a fresh UUID; never remove another output.
            if writer.destination.resolve().parent!=writer.parent.resolve() or writer.destination.is_symlink():raise ValueError('The alpha output directory changed.')
            for path in writer.destination.iterdir():
                if path.is_symlink() or not path.is_file():raise ValueError('Unexpected alpha output entry.')
                path.unlink()
            writer.destination.rmdir()
        raise
