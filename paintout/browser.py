"""Local Windows pickers and colour-managed thumbnails. No footage upload needed."""
import asyncio,base64,io,json,os,subprocess
from pathlib import Path
from aiohttp import web
from server import PromptServer

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

def thumbnail(path,space):
    from PIL import Image
    import torch
    from .paintout import describe,frames,resize,to_linear,encode_ct,native_colour,selected_space
    d=describe(path);x=torch.from_numpy(next(frames(d,0,1)))[None]
    h,w=x.shape[1:3];scale=min(1,240/max(h,w));x=resize(x,max(1,round(h*scale)),max(1,round(w*scale)))
    if space=='auto':space=selected_space(d,space)
    linear=to_linear(x,space).clamp_min(0);linear=linear/(1+linear)
    x=native_colour(encode_ct(linear),'HDR ACEScct','sRGB')[0].clamp(0,1)
    image=Image.fromarray((x.numpy()*255).round().astype('uint8'));buf=io.BytesIO();image.save(buf,format='PNG');return buf.getvalue()

async def preview(request):
    from ..media_source import require_same_origin
    require_same_origin(request)
    try:
        result=await asyncio.to_thread(thumbnail,request.query['file'],request.query.get('space','acescg'))
        return web.Response(body=result,content_type='image/png',headers={'Cache-Control':'no-store'})
    except Exception as error:return web.json_response({'error':str(error)},status=400)


def register_routes():
    server=getattr(PromptServer,'instance',None)
    if server is None:return
    existing={(route.method,route.path) for route in server.routes}
    if ('POST','/zura/paintout/pick') not in existing:
        server.routes.post('/zura/paintout/pick')(browse)
    if ('GET','/zura/paintout/thumbnail') not in existing:
        server.routes.get('/zura/paintout/thumbnail')(preview)


register_routes()
