"""Local Windows pickers and colour-managed thumbnails. No footage upload needed."""
import asyncio,base64,io,json,os,secrets,subprocess,time
from pathlib import Path
from collections import OrderedDict
from urllib.parse import urlencode
from aiohttp import web
from server import PromptServer

VIDEO_EXTENSIONS={'.mov','.mp4','.mxf','.mkv','.avi','.webm'}
IMAGE_EXTENSIONS={'.exr','.png','.tif','.tiff'}
_media_grants=OrderedDict()

def checked_path(path):
    """Only probe supported local media, never a manifest or arbitrary file."""
    if not isinstance(path,str) or not path.strip():raise ValueError('Choose a footage file or frame sequence first.')
    p=Path(path).expanduser()
    if not p.is_absolute():raise ValueError('Choose a local file with the file picker.')
    # Reject Windows alternate streams before resolving their filesystem target.
    if any(':' in part for part in p.parts[1:]):raise ValueError('Alternate file streams are not supported.')
    p=p.resolve(strict=True)
    if not p.is_dir() and (not p.is_file() or p.suffix.lower() not in VIDEO_EXTENSIONS|IMAGE_EXTENSIONS):
        raise ValueError('Choose a supported video, PNG, TIFF, EXR or frame sequence.')
    return p

def grant(path):
    """A media URL grants access to one selected file, not a directory."""
    p=checked_path(str(path))
    if not p.is_file():raise ValueError('A frame sequence cannot be played as a single file.')
    now=time.monotonic()
    for key,(_,expires) in list(_media_grants.items()):
        if expires<now:_media_grants.pop(key,None)
    token=secrets.token_urlsafe(24);_media_grants[token]=(p,now+24*60*60)
    while len(_media_grants)>256:_media_grants.popitem(last=False)
    return '/zura/paintout/media?'+urlencode({'token':token})

def describe_media(path):
    from .paintout import describe
    p=checked_path(path);d=describe(str(p));kind='image' if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS else d['kind']
    if kind=='image':
        from .frame_editor import validate_edit_orientation
        validate_edit_orientation(p)
    result=dict(path=str(p),name=p.name,width=d['width'],height=d['height'],frames=d['count'],fps=d.get('fps') or 25,kind=kind,
                thumbnail_url='/zura/paintout/frame-preview?'+urlencode({'file':str(p),'space':'auto','frame':0,'size':1280}))
    if kind=='video':result['media_url']=grant(p)
    return result

async def info(request):
    from ..media_source import require_same_origin
    require_same_origin(request)
    try:return web.json_response(await asyncio.to_thread(describe_media,request.query.get('file','')))
    except Exception as error:return web.json_response({'error':str(error)},status=400)

async def media(request):
    from ..media_source import require_same_origin
    require_same_origin(request)
    item=_media_grants.get(request.query.get('token',''))
    if not item or item[1]<time.monotonic():raise web.HTTPNotFound(text='Choose this file again to refresh its preview.')
    path=item[0]
    try:valid=checked_path(str(path))==path and path.is_file()
    except (ValueError,OSError):valid=False
    if not valid:raise web.HTTPNotFound(text='The selected file is no longer available.')
    response=web.FileResponse(path,headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        # Exported EXRs are downloads, not browser-decoded colour previews.
        response.headers['Content-Disposition']='attachment; filename="'+path.name.replace('"','')+'"'
    return response

def pick(kind):
    if os.name!='nt':raise ValueError('Windows file browsing requires a local Windows ComfyUI server.')
    # All dialog text is fixed; no request text is interpolated into shell code.
    filters={
        'footage':'Footage (*.mov;*.mp4;*.mxf;*.mkv;*.avi)|*.mov;*.mp4;*.mxf;*.mkv;*.avi|Images (*.exr;*.tif;*.tiff;*.png)|*.exr;*.tif;*.tiff;*.png',
        'anchor':'Painted frames (*.exr;*.tif;*.tiff;*.png)|*.exr;*.tif;*.tiff;*.png',
        'mask':'Mask (*.mov;*.mp4;*.mkv;*.exr;*.png;*.tif;*.tiff)|*.mov;*.mp4;*.mkv;*.exr;*.png;*.tif;*.tiff'}
    if kind=='sequence':
        dialog="$d=New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description='Select the frame sequence folder'; if($d.ShowDialog($owner) -eq 'OK') { ConvertTo-Json -InputObject @($d.SelectedPath) -Compress }"
    else:
        if kind not in filters:raise ValueError('Unknown file picker')
        dialog="$d=New-Object System.Windows.Forms.OpenFileDialog; $d.Filter='"+filters[kind]+"'; $d.Multiselect="+('$true' if kind=='anchor' else '$false')+"; $d.Title='Select paintout files'; if($d.ShowDialog($owner) -eq 'OK') { ConvertTo-Json -InputObject @($d.FileNames) -Compress }"
    script="[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Add-Type -AssemblyName System.Windows.Forms; $owner=New-Object System.Windows.Forms.Form; $owner.TopMost=$true; "+dialog+"; $owner.Dispose()"
    encoded=base64.b64encode(script.encode('utf-16-le')).decode()
    result=subprocess.run(['powershell.exe','-NoProfile','-STA','-EncodedCommand',encoded],capture_output=True,timeout=600,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise ValueError('Windows could not open the file selection window.')
    text=result.stdout.decode('utf-8-sig').strip()
    paths=json.loads(text) if text else []
    return paths if isinstance(paths,list) else [paths]

async def browse(request):
    from ..media_source import require_same_origin
    require_same_origin(request)
    try:
        data=await request.json();paths=await asyncio.to_thread(pick,data.get('kind'))
        return web.json_response({'paths':paths})
    except Exception as error:return web.json_response({'error':str(error)},status=400)

def thumbnail(path,space,frame=0,size=240):
    from PIL import Image
    import torch
    from .paintout import describe,frames,resize,working,selected_space
    p=checked_path(path);d=describe(str(p));frame=int(frame);size=int(size)
    if frame<0 or frame>=d['count']:raise ValueError('The preview frame is outside the source range.')
    if not 32<=size<=1280:raise ValueError('Preview size must be between 32 and 1280 pixels.')
    x=torch.from_numpy(next(frames(d,frame,1)))[None]
    h,w=x.shape[1:3];scale=min(1,size/max(h,w));x=resize(x,max(1,round(h*scale)),max(1,round(w*scale)))
    if space=='auto':space=selected_space(d,space)
    x=working(x,space,'SDR (sRGB)')[0].clamp(0,1)
    image=Image.fromarray((x.numpy()*255).round().astype('uint8'));buf=io.BytesIO();image.save(buf,format='PNG');return buf.getvalue()

async def preview(request):
    from ..media_source import require_same_origin
    require_same_origin(request)
    try:
        result=await asyncio.to_thread(thumbnail,request.query['file'],request.query.get('space','acescg'),request.query.get('frame',0),request.query.get('size',240))
        return web.Response(body=result,content_type='image/png',headers={'Cache-Control':'no-store'})
    except Exception as error:return web.json_response({'error':str(error)},status=400)


def export_source_frame(path,frame,colour_space,project=None):
    """Use the native frame exporter without running a Comfy prompt or model."""
    from .paintout import ZuraPaintoutExportFrames,describe,selected_space,is_hdr,frames,working
    p=checked_path(path)
    if isinstance(frame,bool) or not isinstance(frame,int) or frame<0:raise ValueError('Enter a whole source frame number starting at 0.')
    d=describe(str(p));space=selected_space(d,colour_space)
    document=None
    if project:
        from .editor_store import load_project
        document=load_project(project)
        if checked_path(document.get('data',{}).get('draft',{}).get('source'))!=p:
            raise ValueError('Export the frame from its original shot project.')
    def with_reference(result):
        from .editor_store import source_identity
        clock=d.get('fps_rational') or (document or {}).get('data',{}).get('draft',{}).get('sequenceFps')
        download_name=f'{project or p.stem}_frame_{frame:06d}'+Path(result['path']).suffix
        reference=dict(schema='zura-paintout.frame-reference/v1',project=project,source=source_identity(str(p),d),source_frame=frame,width=d['width'],height=d['height'],fps_rational=str(clock) if clock is not None else None,source_colour_space=space,edit_colour_space=result['colour_space'],image_file=download_name)
        sidecar=Path(result['path']).with_suffix('.reference.json');sidecar.write_text(json.dumps(reference,indent=2),encoding='utf-8')
        return {**result,'reference':reference,'reference_path':str(sidecar),'download_name':download_name}
    if frame>=d['count']:raise ValueError('Requested paint frame is outside the source range.')
    if not is_hdr(space):
        import folder_paths
        import numpy as np
        import torch
        import OpenImageIO as oiio
        target=Path(folder_paths.get_output_directory())/'paintout'/('paint_frames_'+secrets.token_hex(6))
        target.mkdir(parents=True)
        output=target/f'paint_{frame:06d}.png'
        a=torch.from_numpy(next(frames(d,frame,1)))[None]
        # A 16-bit sRGB PNG is easy to paint without silently quantising the plate to 8 bits.
        image=working(a,space,'SDR (sRGB)')[0].clamp(0,1).numpy()
        pixels=np.ascontiguousarray((image*65535).round().astype(np.uint16))
        spec=oiio.ImageSpec(pixels.shape[1],pixels.shape[0],3,oiio.UINT16);spec.attribute('oiio:ColorSpace','sRGB')
        writer=oiio.ImageOutput.create(str(output))
        if not writer:raise ValueError('Could not create the paint frame PNG.')
        try:
            if not writer.open(str(output),spec) or not writer.write_image(pixels):raise ValueError('Could not save the paint frame PNG.')
        finally:writer.close()
        return with_reference(dict(path=str(output),url=grant(output),frame=frame,colour_space='srgb_display'))
    result=ZuraPaintoutExportFrames().export(str(p),colour_space,str(frame),'paintout/paint_frames')
    row=json.loads(result['result'][0])[0]
    return with_reference(dict(path=row['file'],url=grant(row['file']),frame=row['frame'],colour_space=row['colour_space']))

async def export_frame(request):
    from ..media_source import require_same_origin
    require_same_origin(request)
    try:
        data=await request.json()
        result=await asyncio.to_thread(export_source_frame,data.get('file',''),data.get('frame'),data.get('colour_space','auto'),data.get('project'))
        return web.json_response(result)
    except Exception as error:return web.json_response({'error':str(error)},status=400)


def register_routes():
    server=getattr(PromptServer,'instance',None)
    if server is None:return
    existing={(route.method,route.path) for route in server.routes}
    if ('POST','/zura/paintout/pick') not in existing:
        server.routes.post('/zura/paintout/pick')(browse)
    if ('GET','/zura/paintout/thumbnail') not in existing:
        server.routes.get('/zura/paintout/thumbnail')(preview)
    if ('GET','/zura/paintout/info') not in existing:
        server.routes.get('/zura/paintout/info')(info)
    if ('GET','/zura/paintout/media') not in existing:
        server.routes.get('/zura/paintout/media')(media)
    if ('POST','/zura/paintout/export-frame') not in existing:
        server.routes.post('/zura/paintout/export-frame')(export_frame)
    if ('GET','/zura/paintout/frame-preview') not in existing:
        server.routes.get('/zura/paintout/frame-preview')(preview)


register_routes()
