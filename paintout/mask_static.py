"""Verified source-raster masks without a tracking model."""
import secrets
import numpy as np
from PIL import Image
from .browser import checked_path
from .paintout import describe
from .editor_store import load_project, project_response, source_identity, commit_mask_pass, RevisionConflict

def context(body):
    project=body['project']; document=load_project(project); expected=body.get('expected_revision')
    if type(expected) is not int or expected != document['revision']:
        raise RevisionConflict('This project changed. Reload before saving the mask.')
    source=checked_path(body['source']); draft=document.get('data',{}).get('draft',{})
    if not draft.get('source') or checked_path(draft['source']) != source:
        raise ValueError('Use the mask in its original source project.')
    info=describe(str(source)); width,height=info['width'],info['height']
    if not 1<=width<=16384 or not 1<=height<=16384 or width*height>40_000_000:raise ValueError('The source is too large for an interactive mask.')
    start=body.get('startFrame',draft.get('startFrame',0)); count=body.get('frameCount',draft.get('frameCount',info['count']))
    if type(start) is not int or type(count) is not int or start<0 or count<1 or start+count>info['count']:
        raise ValueError('Choose a mask range inside the source.')
    return project,expected,source,info,start,count,source_identity(str(source),info)

def commit(body,mask,method,mask_source=None,expected_identity=None):
    project,expected,source,info,start,count,identity=context(body)
    if expected_identity is not None and identity!=expected_identity:raise ValueError('The source changed while preparing the mask.')
    if count>10000:raise ValueError('Choose at most 10000 source frames for a static mask.')
    if mask.shape != (info['height'],info['width']) or not np.isfinite(mask).all() or np.any((mask<0)|(mask>1)):
        raise ValueError('The mask must match the original source dimensions exactly. White removes; black keeps.')
    if source_identity(str(source),describe(str(source))) != identity:raise ValueError('The source changed while preparing the mask.')
    committed=commit_mask_pass(project,identity,{frame:mask for frame in range(start,start+count)},'replace',expected,
        metadata={'method':method,'segment_id':secrets.token_hex(12),'tracked':False,'ready':True,'mask_source':mask_source or '', 'frame':start},preserve_protection=True)
    return {**project_response(load_project(project)),'segment_id':committed['segment_id']}

def save_static(body):
    from .editor_routes import _decode_paint
    _,_,_,info,_,_,identity=context(body)
    mask=_decode_paint(body['mask'],info['width'],info['height'])
    return commit(body,mask,'static_paint',expected_identity=identity)

def import_still(body):
    _,_,_,info,_,_,identity=context(body)
    path=checked_path(body['mask'])
    if path.stat().st_size>256*1024*1024:raise ValueError('Choose a mask image smaller than 256 MB.')
    if path.suffix.lower() not in {'.png','.jpg','.jpeg','.tif','.tiff','.webp'}:
        raise ValueError('Choose a grayscale PNG or JPEG mask, or a matching mask video.')
    before=path.stat()
    with Image.open(path) as image:
        if getattr(image,'n_frames',1)!=1 or image.getexif().get(274,1)!=1:
            raise ValueError('Use one mask image with its orientation applied.')
        if image.size!=(info['width'],info['height']):raise ValueError('The mask dimensions must match the original footage exactly, not the model grid.')
        rgba=np.asarray(image.convert('RGBA'));rgb=rgba[...,:3]
        if not np.array_equal(rgb[...,0],rgb[...,1]) or not np.array_equal(rgb[...,1],rgb[...,2]):
            raise ValueError('Use a grayscale mask. White removes; black keeps.')
        mask=rgb[...,0].astype(np.float32)/255
        mask*=rgba[...,3].astype(np.float32)/255
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('The mask changed during import.')
    return commit(body,mask,'import_still',str(path),identity)
