"""Global Studio imports: original assets plus explicitly separate model views."""
from __future__ import annotations

import asyncio
import copy
from fractions import Fraction
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import uuid

from aiohttp import web

from . import display_view_routes as display
from . import model_view
from .media_precision import inspect_original

MAX_UPLOAD_BYTES = 32 * 1024 ** 3
VIDEO_SUFFIXES = {'.mp4', '.mov', '.mkv', '.webm', '.mxf', '.avi'}
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.exr'}


def _request_fence(request,cancel):
    transport=getattr(request,'transport',None)
    if transport is None or transport.is_closing():cancel.set()
    model_view._cancelled(cancel)


async def _request_work(request,work,cancel):
    _request_fence(request,cancel)
    task=asyncio.create_task(asyncio.to_thread(work))
    try:
        while not task.done():
            transport=getattr(request,'transport',None)
            if transport is None or transport.is_closing():cancel.set()
            await asyncio.wait({task},timeout=.05)
        result=await task;_request_fence(request,cancel);return result
    except asyncio.CancelledError:
        cancel.set()
        try:await asyncio.shield(task)
        except BaseException:pass
        raise


class _PendingStore:
    def __init__(self,store):self.store=store;self.pending=[]
    def load(self,identity):return self.store.load(identity)
    def save(self,record):self.pending.append(copy.deepcopy(record))
    def discard(self,input_root):
        root=(Path(input_root)/'genj_studio').resolve()
        for record in self.pending:
            directory=(Path(input_root)/record['file']).parent.resolve()
            if directory.parent==root and directory.name==record['id'] and re.fullmatch(r'[a-f0-9]{32}',directory.name):shutil.rmtree(directory,ignore_errors=True)


def _ref(path, input_root):
    return {'type':'input','filename':path.name,'subfolder':path.parent.relative_to(input_root).as_posix()}


def _visible(asset):
    from .studio import public_project
    return public_project(asset)


def cancellation_checked_asset(validate,roots,cancel):
    if cancel is None:return validate
    def checked(asset):
        model_view._cancelled(cancel)
        relative=asset.get('file')
        if not isinstance(relative,str):raise ValueError('Choose a registered imported asset.')
        root=(Path(roots['input'])/'genj_studio').resolve();path=(Path(roots['input'])/relative).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file() or model_view._linked(path):raise ValueError('The imported original is outside Studio storage.')
        if model_view._digest(path,cancel)!=asset.get('sha'):raise ValueError('The imported original changed. Import it again.')
        return path
    return checked


def _browser_preview(source,destination,cancel):
    """Playback only. Graphs continue to use the lossless SDR model input."""
    from ..paintout.media_tools import find_media_tool
    command=[find_media_tool('ffmpeg'),'-v','error',*model_view._LOCAL_MEDIA,'-i',str(source),
             '-map','0:v:0','-map','0:a:0?','-vf',
             "scale='max(2,min(1280,iw))':'max(2,min(1280,ih))':force_original_aspect_ratio=decrease:force_divisible_by=2:out_color_matrix=bt709:out_range=tv",
             '-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',
             '-color_trc','iec61966-2-1','-color_primaries','bt709','-colorspace','bt709','-color_range','tv',
             '-c:a','aac','-movflags','+faststart',str(destination)]
    with tempfile.TemporaryFile() as errors:
        process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=errors)
        try:
            while process.poll() is None:
                model_view._cancelled(cancel)
                try:process.wait(timeout=.2)
                except subprocess.TimeoutExpired:pass
            model_view._cancelled(cancel)
            if process.returncode:
                errors.seek(0)
                raise ValueError('The browser viewing copy could not be prepared: '+errors.read().decode('utf-8','replace')[-1000:])
        finally:
            if process.poll() is None:process.kill();process.wait()


def describe_asset(asset, store, check_asset, roots,cancel=None):
    model_view._cancelled(cancel);check_asset=cancellation_checked_asset(check_asset,roots,cancel)
    pending = type('PendingStore', (), {'load': lambda _, identity: asset if identity == asset['id'] else store.load(identity)})()
    resolved = display.resolve_original({'asset_id':asset['id']},pending,check_asset,roots,cancel=cancel)
    details=resolved['metadata'].get('info',{})
    if details.get('width',1)*details.get('height',1)>model_view.MAX_PIXELS:raise ValueError('This imported source exceeds the 16 MP model-view limit.')
    precision = inspect_original(resolved,cancel=cancel)
    if precision.get('width',1)*precision.get('height',1)>model_view.MAX_PIXELS:raise ValueError('This imported source exceeds the 16 MP model-view limit.')
    metadata = resolved['metadata']
    path = resolved['path']
    source_path = resolved['files'][0].parent if resolved.get('files') else path
    from ..paintout.browser import describe_media
    media = describe_media(str(source_path),cancel=cancel)
    colour = asset.get('resolved_colour') or media.get('resolved_colour')
    if colour in ('auto','unknown'):colour=None
    # A FLOAT channel width alone never identifies a transfer function.
    result = {**asset,'precision':precision,'width':media['width'],'height':media['height'],
              'frameCount':metadata['frame_count'],'frames':metadata['frame_count']}
    if metadata.get('frame_rate'):
        rate=metadata['frame_rate'];result['frameRate']=rate
        result['fps']=float(Fraction(rate['numerator'],rate['denominator']))
        result['duration']=result['frameCount']/result['fps']
    if colour:result['resolved_colour']=colour
    media.update(precision=precision,studioAssetId=asset['id'])
    if asset.get('processingView'):
        media['processingView']=asset['processingView']
        preview=Path(roots['input'])/asset.get('preview_file','')
        if (asset.get('preview_file') and preview.is_file() and not model_view._linked(preview)
                and preview.resolve().is_relative_to(path.parent.resolve())):
            media['media_url']=describe_media(str(preview),cancel=cancel)['media_url']
    if colour:media['resolved_colour']=colour
    resolved['revalidate']()
    return result,media


def restore_model_info(path,info,*,store=None,check_asset=None,roots=None):
    """Rehydrate owned imports only; ordinary selected footage keeps its info."""
    if roots is None:
        import folder_paths
        roots={key:getattr(folder_paths,f'get_{key}_directory')() for key in ('input','output','temp')}
    root=(Path(roots['input'])/'genj_studio').resolve();selected=Path(path).resolve()
    if (selected.name not in {'model.mkv','model.png'} or selected.parent.parent!=root
            or re.fullmatch(r'[a-f0-9]{32}',selected.parent.name) is None):return info
    if store is None or check_asset is None:
        from .studio import Store,check_asset as validate_asset
        store=store or Store();check_asset=check_asset or validate_asset
    try:asset=store.load(selected.parent.name)
    except (ValueError,KeyError,FileNotFoundError):return info
    if asset.get('kind')!='asset' or asset.get('processingView',{}).get('kind')!='sdr8_inference':return info
    if Path(check_asset(asset)).resolve()!=selected:raise ValueError('The registered model input belongs to another source. Import it again.')
    _,restored=describe_asset(asset,store,check_asset,roots)
    return restored


def resolve_imported_frame(identity,store,check_asset,roots,cancel=None):
    """Resolve a registered single-image model view to its immutable original."""
    if not isinstance(identity,str) or not re.fullmatch(r'[a-f0-9]{32}',identity):raise ValueError('Choose a registered imported frame.')
    check_asset=cancellation_checked_asset(check_asset,roots,cancel)
    proxy=store.load(identity);check_asset(proxy);binding=proxy.get('originalFrame')
    if (proxy.get('kind')!='asset' or proxy.get('asset_kind')!='image' or proxy.get('frameCount')!=1
            or not isinstance(binding,dict) or proxy.get('originalFrameSha256')!=hashlib.sha256(model_view._canonical(binding)).hexdigest()
            or binding.get('schemaVersion')!=1 or binding.get('proxyId')!=identity):raise ValueError('The imported frame binding changed. Import the source again.')
    original=store.load(binding['assetId'])
    if original.get('sha')!=binding.get('assetSha256'):raise ValueError('The original imported source changed. Import it again.')
    path=Path(check_asset(original)).resolve();index=binding['frameIndex']
    if type(index) is not int or index<0:raise ValueError('The selected original frame is invalid.')
    if original.get('asset_kind')=='video':
        from ..paintout.paintout import describe
        info=describe(str(path),cancel=cancel);rate=Fraction(info['fps_rational']);saved=binding.get('frameRate')
        if saved!={'numerator':rate.numerator,'denominator':rate.denominator} or index>=info['count']:raise ValueError('The selected original frame clock changed.')
        return {'asset_id':original['id'],'frame_time':float(Fraction(index)/rate)},binding['colourSpace']
    if original.get('asset_kind')=='hdr_sequence':
        from .hdr_sequence import validate_manifest
        directory,entries=validate_manifest(path,original['sha'],index,1,cancel=cancel);selected=directory/entries[index]['name']
        return {'file':_ref(selected,Path(roots['input']).resolve())},binding['colourSpace']
    if original.get('asset_kind')!='image' or index!=0:raise ValueError('Choose a valid original still image.')
    return {'asset_id':original['id']},binding['colourSpace']


def prepare_import(body, store, check_asset, roots, cancel=None):
    """Prepare one explicit interval or frame; original assets remain untouched."""
    if not isinstance(body,dict) or set(body)-{'asset_id','colour_space','startFrame','frameCount','frameRate','frame'}:
        raise ValueError('Choose a valid Studio import interval.')
    identity=body.get('asset_id')
    if not isinstance(identity,str) or len(identity)>128:raise ValueError('Choose an imported Studio asset.')
    model_view._cancelled(cancel);check_asset=cancellation_checked_asset(check_asset,roots,cancel);original=store.load(identity)
    if original.get('kind')!='asset' or original.get('asset_kind') not in {'image','video','hdr_sequence'}:
        raise ValueError('Choose an original image, movie or EXR sequence.')
    original,media=describe_asset(original,store,check_asset,roots,cancel=cancel)
    count=original['frameCount'];frame=body.get('frame')
    single=frame is not None
    if single and (type(frame) is not int or not 0<=frame<count):raise ValueError('Choose an existing source frame.')
    request={'source':{'asset_id':identity},'colour_space':body.get('colour_space','auto'),
             'startFrame':frame if single else body.get('startFrame',0),
             'frameCount':1 if single else body.get('frameCount',count)}
    if body.get('frameRate') is not None:request['frameRate']=body['frameRate']
    view=model_view.prepare(request,store,check_asset,roots,cancel)
    model_view._cancelled(cancel)
    input_root=Path(roots['input']).resolve();destination_root=input_root/'genj_studio'
    if model_view._linked(destination_root):raise ValueError('The Studio import directory cannot be linked.')
    new_id=uuid.uuid4().hex;directory=destination_root/new_id;directory.mkdir(parents=True,exist_ok=False)
    try:
        source=Path(view['path']);filename='model.png' if single or original['asset_kind']=='image' else 'model.mkv'
        target=directory/filename
        if filename.endswith('.png') and source.suffix.lower()!='.png':
            import av
            with av.open(str(source)) as clip:
                decoded=next(clip.decode(video=0),None)
                if decoded is None:raise ValueError('The selected source frame could not be extracted.')
                decoded.to_image().save(target)
        else:shutil.copyfile(source,target)
        model_view._cancelled(cancel)
        rate=view.get('frameRate') or original.get('frameRate') or body.get('frameRate')
        selected_count=1 if single else view['processingView']['frameCount']
        fps=float(Fraction(rate['numerator'],rate['denominator'])) if rate else None
        processing={**view['processingView'],'originalAssetId':identity,
                    'originalSource':{**view['processingView']['originalSource'],'precision':original['precision']}}
        proxy={'id':new_id,'kind':'asset','asset_kind':'image' if filename.endswith('.png') else 'video',
               'file':target.relative_to(input_root).as_posix(),'sha':model_view._digest(target,cancel),
               'name':original['name'],'width':view['width'],'height':view['height'],
               'resolved_colour':'srgb_display','precision':{'sourceBitDepth':8,'storageBitDepth':8,'sampleType':'integer'},
               'processingView':processing,'frameCount':selected_count,
               **({'fps':fps,'duration':selected_count/fps,'frameRate':rate} if fps else {})}
        from ..paintout.browser import describe_media
        proxy_info=describe_media(str(target),cancel=cancel);proxy_info.update(resolved_colour='srgb_display',processingView=processing,
                     inputRef=_ref(target,input_root),studioAssetId=new_id)
        if rate:proxy_info.update(frameRate=rate,fps=fps)
        stills=[]
        if proxy['asset_kind']=='image':
            binding={'schemaVersion':1,'proxyId':new_id,'assetId':identity,'assetSha256':original['sha'],
                     'frameIndex':request['startFrame'],'frameRate':rate,'colourSpace':processing['sourceColour']}
            proxy['originalFrame']=binding;proxy['originalFrameSha256']=hashlib.sha256(model_view._canonical(binding)).hexdigest()
            original_frame={'displaySelector':{'imported_frame':new_id},'studioAssetId':identity,
                            'frameCount':1,'frames':1,'selectedFrame':binding['frameIndex'],
                            'frameRate':rate,'precision':original['precision'],'resolved_colour':binding['colourSpace'],
                            **({'frame_time':float(Fraction(binding['frameIndex'])/Fraction(rate['numerator'],rate['denominator']))} if rate and original['asset_kind']=='video' else {})}
            stills=[{**_ref(target,input_root),'width':proxy['width'],'height':proxy['height'],
                     'frameCount':1,'precision':original['precision'],'resolved_colour':binding['colourSpace'],
                     'colour':{'encoding':binding['colourSpace'],'sceneLinear':binding['colourSpace'] in {'acescg','linear_rec709'}},
                     'processingView':{**processing,'originalSource':original_frame}}]
        else:
            import av
            preview=directory/'preview.mp4';_browser_preview(target,preview,cancel)
            proxy.update(video_codec='ffv1',preview_file=preview.relative_to(input_root).as_posix())
            proxy_info['media_url']=describe_media(str(preview),cancel=cancel)['media_url']
            with av.open(str(target)) as clip:
                last=None
                for index,decoded in enumerate(clip.decode(video=0)):
                    if index==0:
                        first=directory/'first.png';decoded.to_image().save(first)
                        stills.append({**_ref(first,input_root),'width':proxy['width'],'height':proxy['height']})
                    last=decoded
                    model_view._cancelled(cancel)
                if last is None:raise ValueError('The prepared video has no model-input frames.')
                final=directory/'last.png';last.to_image().save(final)
                stills.append({**_ref(final,input_root),'width':proxy['width'],'height':proxy['height']})
        # Store only complete inputs. Cancellation never replaces an existing asset.
        model_view._cancelled(cancel);check_asset(original);model_view._cancelled(cancel);store.save(proxy)
        original_colour=processing['sourceColour']
        media.update(resolved_colour=original_colour)
        return {'width':proxy['width'],'height':proxy['height'],'frameCount':selected_count,'fps':fps,
                'colour':{'encoding':original_colour,'sceneLinear':original_colour in {'acescg','linear_rec709'}},
                'precision':original['precision'],'studioAsset':_visible(original),'mediaInfo':media,
                'originalAssetId':identity,'selectedStartFrame':request['startFrame'],
                'processingInput':{'precision':{'sourceBitDepth':8},'studioAsset':_visible(proxy),
                    'mediaInfo':proxy_info,'stills':{'first':stills[0],'last':stills[-1]}}}
    except BaseException:
        if directory.parent==destination_root and directory.name==new_id:shutil.rmtree(directory,ignore_errors=True)
        raise


def register(studio,routes,response,check_asset):
    from .route_aliases import require_studio_alias_paths
    require_studio_alias_paths(routes,(('POST','media-import/upload'),('POST','media-import/describe'),('POST','media-import/prepare')))
    import folder_paths
    from ..media_source import require_same_origin
    from ..comfylink.studio_sessions import _bounded_json
    limit=asyncio.Semaphore(1)
    def roots():return {key:getattr(folder_paths,f'get_{key}_directory')() for key in ('input','output','temp')}

    @routes.post('/zura/studio/media-import/upload')
    @routes.post('/genj/studio/media-import/upload')
    @response
    async def upload(request):
        require_same_origin(request);cancel=threading.Event()
        reader=await request.multipart();part=await reader.next()
        if part is None or not part.filename:raise ValueError('Choose an image or movie.')
        name=Path(part.filename.replace('\\','/')).name;suffix=Path(name).suffix.lower()
        kind='video' if suffix in VIDEO_SUFFIXES else 'image' if suffix in IMAGE_SUFFIXES else None
        if kind is None:raise ValueError('Choose MP4, MOV, MXF, AVI, MKV, WebM, PNG, JPEG, TIFF or EXR.')
        identity=uuid.uuid4().hex;input_root=Path(roots()['input']).resolve();root=input_root/'genj_studio'
        if model_view._linked(root):raise ValueError('The Studio import directory cannot be linked.')
        directory=root/identity;directory.mkdir(parents=True,exist_ok=False);path=directory/('original'+suffix)
        digest=hashlib.sha256();size=0
        try:
            with path.open('xb') as stream:
                while chunk:=await part.read_chunk(1024*1024):
                    _request_fence(request,cancel)
                    size+=len(chunk)
                    if size>MAX_UPLOAD_BYTES:raise ValueError('Choose an original smaller than 32 GiB, or import a shorter source interval.')
                    if size%(256*1024*1024)<len(chunk) and shutil.disk_usage(directory).free<512*1024*1024:
                        raise ValueError('There is insufficient space to retain this original safely.')
                    stream.write(chunk);digest.update(chunk)
            if await reader.next() is not None:raise ValueError('Choose one original movie or image, or use EXR sequence.')
            asset={'id':identity,'kind':'asset','asset_kind':kind,'file':path.relative_to(input_root).as_posix(),
                   'sha':digest.hexdigest(),'name':name}
            async with limit:
                asset,media=await _request_work(request,lambda:describe_asset(asset,studio.store,check_asset,roots(),cancel),cancel)
            _request_fence(request,cancel)
            studio.store.save(asset)
            return web.json_response({'asset':_visible(asset),'mediaInfo':media},headers={'Cache-Control':'no-store'})
        except BaseException:
            if directory.parent==root and directory.name==identity:shutil.rmtree(directory,ignore_errors=True)
            raise

    @routes.post('/zura/studio/media-import/describe')
    @routes.post('/genj/studio/media-import/describe')
    @response
    async def describe(request):
        require_same_origin(request);body=await _bounded_json(request.content,16384)
        if not isinstance(body,dict) or set(body)!={'asset_id'}:raise ValueError('Choose an imported asset.')
        cancel=threading.Event()
        async with limit:
            asset,media=await _request_work(request,lambda:describe_asset(studio.store.load(body['asset_id']),studio.store,check_asset,roots(),cancel),cancel)
        return web.json_response({'asset':_visible(asset),'mediaInfo':media},headers={'Cache-Control':'no-store'})

    @routes.post('/zura/studio/media-import/prepare')
    @routes.post('/genj/studio/media-import/prepare')
    @response
    async def prepare(request):
        require_same_origin(request);body=await _bounded_json(request.content,16384);cancel=threading.Event()
        pending=_PendingStore(studio.store);directories=roots()
        async with limit:
            try:
                value=await _request_work(request,lambda:prepare_import(body,pending,check_asset,directories,cancel),cancel)
                _request_fence(request,cancel)
                for record in pending.pending:studio.store.save(record)
                return web.json_response(value,headers={'Cache-Control':'no-store'})
            except BaseException:
                pending.discard(directories['input'])
                raise
