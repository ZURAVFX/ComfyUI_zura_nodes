from __future__ import annotations
import json, math, re, subprocess, hashlib, tempfile, uuid, shutil
from pathlib import Path
from fractions import Fraction
import numpy as np
import torch
import torch.nn.functional as F
from functools import wraps
from scipy.ndimage import maximum_filter, distance_transform_edt

CATEGORY = 'Zura/Paintout'
COLOUR_SPACES=['auto','acescg','acescct','hlg_rec2020','pq_rec2020','linear_rec709','srgb_display','rec709_gamma24','rec709_oetf']

def cpu_frames(function):
    @wraps(function)
    def run(*args,**kwargs):
        before=torch.get_num_threads()
        try:
            if before>8:torch.set_num_threads(4)
            return function(*args,**kwargs)
        finally:
            if torch.get_num_threads()!=before:torch.set_num_threads(before)
    return run
def is_hdr(space):return space in ('acescg','acescct','hlg_rec2020','pq_rec2020','linear_rec709')
def string(default='', **kw): return ('STRING', {'default': default, **kw})
def integer(default, lo=0, hi=100000): return ('INT', {'default': default, 'min': lo, 'max': hi})
def floating(default, lo=0., hi=1.): return ('FLOAT', {'default': default, 'min': lo, 'max': hi, 'step': .01})

def frame_progress(total):
    """Use native owned-node progress for CPU preparation and export too."""
    try:
        from comfy.utils import ProgressBar
        return ProgressBar(total).update_absolute
    except ImportError:
        return lambda value: None  # CPU-only tools can also use the frame helpers.
def natural(p): return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', str(p))]
def read_image(path):
    import OpenImageIO as oiio
    path=resolve_input(path)
    inp = oiio.ImageInput.open(str(path))
    if not inp: raise ValueError(f'Cannot read image: {path}')
    try:
        spec = inp.spec(); names = [n.lower() for n in spec.channelnames]
        a = np.asarray(inp.read_image(format=oiio.FLOAT))
        if a.ndim == 2: a = a[...,None]
        ids = [names.index(c) for c in ('r','g','b')] if all(c in names for c in ('r','g','b')) else list(range(min(3,a.shape[-1])))
        a = a[...,ids]
        if a.shape[-1] == 1: a = np.repeat(a,3,-1)
        if a.shape[-1] != 3: raise ValueError('Need RGB or monochrome image')
        if not np.isfinite(a).all(): raise ValueError(f'Non-finite pixels: {path}')
        return a.copy()
    finally: inp.close()

def describe(path):
    p=resolve_input(path)
    if p.is_dir():
        files=sorted([x for x in p.iterdir() if x.suffix.lower() in ('.exr','.png','.tif','.tiff')],key=natural)
        if not files: raise ValueError(f'No EXR/PNG/TIFF frames in {p}')
        shape=read_image(files[0]).shape
        return dict(kind='sequence',files=[str(x) for x in files],width=shape[1],height=shape[0],count=len(files))
    if p.suffix.lower() in ('.exr','.png','.tif','.tiff'):
        shape=read_image(p).shape
        return dict(kind='sequence',files=[str(p)],width=shape[1],height=shape[0],count=1)
    r=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_streams','-of','json',str(p)],capture_output=True,check=True,text=True)
    s=json.loads(r.stdout)['streams'][0]
    fps=float(Fraction(s['avg_frame_rate'])); rate=float(Fraction(s['r_frame_rate']))
    if abs(fps-rate)>.02: raise ValueError('Variable frame rate: conform to constant frame rate first')
    return dict(kind='video',path=str(p),width=int(s['width']),height=int(s['height']),fps=fps,transfer=s.get('color_transfer'),primaries=s.get('color_primaries'),matrix=s.get('color_space'),range=s.get('color_range'),pixel_format=s.get('pix_fmt'),count=int(s.get('nb_frames') or round(float(s.get('duration',0))*fps)))

def resolve_input(path):
    p=Path(path).expanduser()
    if not p.is_absolute():
        import folder_paths
        p=Path(folder_paths.get_input_directory())/p
    if not p.exists():raise ValueError(f'Input does not exist: {p}')
    return p

def frames(d,start,count):
    if d['kind']=='sequence':
        files=d['files']
        if start+count>len(files): raise ValueError('Frame range exceeds sequence')
        for f in files[start:start+count]: yield read_image(f)
        return
    vf=f'trim=start_frame={start}:end_frame={start+count},setpts=PTS-STARTPTS'
    matrix={'bt2020nc':'bt2020','bt2020c':'bt2020','bt709':'bt709','smpte170m':'bt601'}.get(d.get('matrix'))
    if matrix:
        vf+=f',scale=in_color_matrix={matrix}:in_range={"pc" if d.get("range")=="pc" else "tv"}:out_range=pc'
    # Preserve encoded RGB values at 16-bit precision; colour conversion follows decoding.
    # FFmpeg 7 defaults rawvideo to 25 fps after this filter chain. Keep every
    # decoded source frame, including 59.94 fps footage, rather than drop/duplicate.
    cmd=['ffmpeg','-v','error','-i',d['path'],'-vf',vf,'-an','-sn','-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb48le','-']
    # Windows anonymous pipes throttle large RGB streams. Reuse an uncompressed
    # temporary disk cache instead, while retaining 16-bit decoded RGB precision.
    size=d['width']*d['height']*6*count
    cache_dir=Path(tempfile.gettempdir())/'zura_paintout_rgb';cache_dir.mkdir(exist_ok=True)
    key=hashlib.sha256(('frame-exact-v2|'+str(Path(d['path']).resolve())+str(Path(d['path']).stat().st_mtime_ns)+vf+str(count)).encode()).hexdigest()
    cached=cache_dir/(key+'.rgb')
    if size<=8*1024**3 and (cached.exists() or shutil.disk_usage(cache_dir).free>size*1.2):
        if not cached.exists() or cached.stat().st_size!=size:
            part=cache_dir/(key+'_'+uuid.uuid4().hex+'.part')
            try:
                subprocess.run(cmd[:-1]+[str(part)],check=True,capture_output=True)
                if part.stat().st_size!=size:
                    decoded=part.stat().st_size//(d['width']*d['height']*6)
                    raise ValueError(f'Decoded {decoded} of {count} requested source frames starting at {start}. Check the footage and selected range.')
                part.replace(cached)
            finally:
                part.unlink(missing_ok=True)
        mapped=np.memmap(cached,dtype='<u2',mode='r',shape=(count,d['height'],d['width'],3))
        try:
            for a in mapped:yield a.astype(np.float32)/65535.
        finally:del mapped
        return
    p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    n=d['width']*d['height']*6
    try:
        for _ in range(count):
            b=bytearray()
            while len(b)<n:
                part=p.stdout.read(n-len(b))
                if not part: raise ValueError('Video ended before requested frame range')
                b.extend(part)
            yield np.frombuffer(b,dtype='<u2').reshape(d['height'],d['width'],3).astype(np.float32)/65535.
    finally:
        p.stdout.close()
        if p.poll() is None: p.terminate()
        p.wait()

def mask_frames(d,start,count):
    if d['kind']=='painted_tracking':
        import cv2
        offset=start-d['start']
        for file in d['files'][offset:offset+count]:
            a=cv2.imread(file,cv2.IMREAD_GRAYSCALE)
            if a is None:raise ValueError('Automatic repair cache is missing; queue the workflow again')
            yield cv2.resize(a,(d['width'],d['height']),interpolation=cv2.INTER_NEAREST).astype(np.float32)/255.
        return
    if d['kind']=='rectangle':
        a=np.zeros((d['height'],d['width']),dtype=np.float32)
        x,y,w,h=d['rect'];a[y:y+h,x:x+w]=1
        for _ in range(count):yield a
        return
    # A single still is a deliberately broadcast static mask.
    if d['count']==1:
        a=next(frames(d,0,1))[...,0]
        for _ in range(count): yield a
    else:
        for a in frames(d,start,count): yield a[...,0]

def encode_ct(x):
    # ACES S-2016-001, same working curve as the official LTX 2.5 HDR path.
    return torch.where(x>.0078125,(torch.log2(x.clamp(min=1e-12))+9.72)/17.52,10.5402377416545*x+.0729055341958355).clamp(0,1)
def decode_ct(x):
    x=x.clamp(0,1)
    return torch.where(x>.155251141552511,torch.pow(2.,x*17.52-9.72),(x-.0729055341958355)/10.5402377416545)
def _decode_original(x,space):
    if space=='acescct': return decode_ct(x)
    if space=='srgb_display': return torch.where(x<=.04045,x/12.92,((x+.055)/1.055).clamp(min=0).pow(2.4))
    if space=='rec709_gamma24':return x.sign()*x.abs().pow(2.4)
    if space=='rec709_oetf':return torch.where(x<.081,x/4.5,((x+.099)/1.099).clamp(min=0).pow(1/.45))
    return x
def _encode_original(x,space):
    if space=='acescct': return encode_ct(x)
    if space=='srgb_display': return torch.where(x<=.0031308,12.92*x,1.055*x.clamp(min=.0031308).pow(1/2.4)-.055)
    if space=='rec709_gamma24':return x.sign()*x.abs().pow(1/2.4)
    if space=='rec709_oetf':return torch.where(x<.018,4.5*x,1.099*x.clamp(min=0).pow(.45)-.099)
    return x
def native_colour(x,source,destination):
    from comfy_extras.nodes_images import ImageColorSpace
    return ImageColorSpace.execute(x.float(),source,destination)[0].float().cpu()

def matrix_rgb(x,inverse=False):
    from comfy_extras.nodes_images import _REC709_TO_REC2020, _REC2020_TO_ACESCG
    m=torch.tensor(_REC2020_TO_ACESCG) @ torch.tensor(_REC709_TO_REC2020)
    if inverse:m=torch.linalg.inv(m)
    return x @ m.to(x).T

def to_linear(x,space):
    # Compositing and VAE conditioning share scene-linear ACEScg / AP1.
    if space in ('hlg_rec2020','pq_rec2020'):
        return decode_ct(native_colour(x,'HDR' if space=='hlg_rec2020' else 'HDR PQ','HDR ACEScct'))
    if space in ('acescg','acescct'):return _decode_original(x,space)
    return matrix_rgb(_decode_original(x,space))

def from_linear(x,space):
    if space in ('hlg_rec2020','pq_rec2020'):
        return native_colour(encode_ct(x),'HDR ACEScct','HDR' if space=='hlg_rec2020' else 'HDR PQ')
    if space in ('acescg','acescct'):return _encode_original(x,space)
    return _encode_original(matrix_rgb(x,True),space)

PROCESSING_MODES=['HDR (ACEScct)','SDR (sRGB)']
EXPORT_FORMATS=['EXR + HLG video','EXR sequence','HLG video','EXR + SDR video','SDR video']

def sdr_view(linear,shoulder=False):
    if shoulder:linear=linear.clamp_min(0)/(1+linear.clamp_min(0))
    return _encode_original(matrix_rgb(linear,True),'srgb_display').clamp(0,1)

def working(x,space,processing='HDR (ACEScct)',view_hdr=None):
    if space=='srgb_display' and processing=='SDR (sRGB)':return x.float()
    linear=to_linear(x,space)
    return sdr_view(linear,is_hdr(space) if view_hdr is None else view_hdr) if processing=='SDR (sRGB)' else encode_ct(linear)

def unworking(x,space,processing='HDR (ACEScct)'):
    if processing!='SDR (sRGB)':return decode_ct(x)
    linear=to_linear(x,'srgb_display')
    # Undo the single viewing shoulder before compositing into an HDR master.
    # SDR delivery applies that shoulder once to both original and repaired pixels.
    return linear/(1-linear).clamp_min(1e-4) if is_hdr(space) else linear

def selected_space(d,space):
    def video_space(value):
        if d.get('matrix') in (None,'unknown','unspecified'):
            d['matrix']='bt2020nc' if value in ('hlg_rec2020','pq_rec2020') else 'bt709'
        return value
    if space!='auto':
        if d['kind']=='video' and space in ('acescg','acescct','linear_rec709'):
            raise ValueError('For MOV/video choose its encoded colour space: Rec.709, HLG or PQ. Camera log footage needs a colour transform first.')
        return video_space(space) if d['kind']=='video' else space
    if d['kind']=='video':
        transfer=d.get('transfer'); primaries=d.get('primaries')
        if transfer in ('arib-std-b67','smpte2084'):
            if primaries!='bt2020':raise ValueError('HDR video must declare BT.2020 primaries, or choose its colour space explicitly.')
            return video_space('hlg_rec2020' if transfer=='arib-std-b67' else 'pq_rec2020')
        if transfer=='bt709' and primaries in ('bt709',None,'unknown'):return video_space('rec709_oetf')
        if transfer=='iec61966-2-1':return video_space('srgb_display')
        raise ValueError('This video has no supported colour tags. Choose its actual colour space. Convert camera log footage before loading.')
    import OpenImageIO as oiio
    inp=oiio.ImageInput.open(d['files'][0])
    try:
        spec=inp.spec();tag=str(spec.getattribute('oiio:ColorSpace') or spec.getattribute('colorSpace') or '').lower()
        chroma=spec.getattribute('chromaticities')
    finally:inp.close()
    if 'acescct' in tag:return 'acescct'
    if 'acescg' in tag or (chroma and abs(chroma[0]-.713)<.002):return 'acescg'
    if Path(d['files'][0]).suffix.lower()!='.exr':return 'srgb_display'
    if chroma and abs(chroma[0]-.64)<.002:return 'linear_rec709'
    raise ValueError('Untagged EXR: choose ACEScg, ACEScct or linear Rec.709 to match the file.')

def resize(x,h,w,mode='bilinear'):
    return F.interpolate(x.permute(0,3,1,2),size=(h,w),mode=mode,**({'align_corners':False,'antialias':True} if mode=='bilinear' else {})).permute(0,2,3,1)
def resize_fullframe(x,h,w,resampler,is_mask=False):
    if is_mask:return resize(x,h,w,'area')
    if resampler=='comfy_lanczos':
        try:
            import comfy.utils
            return comfy.utils.common_upscale(x.permute(0,3,1,2),w,h,'lanczos','disabled').permute(0,2,3,1)
        except ImportError:
            pass
    return F.interpolate(x.permute(0,3,1,2),size=(h,w),mode='bicubic',align_corners=False,antialias=True).permute(0,2,3,1)
def crop_work(a,c,space,is_mask=False):
    x,y,w,h=c['rect']; rh,rw=c['resized']; ph,pw=c['padded']
    t=torch.from_numpy(a[y:y+h,x:x+w].copy()).float()[None]
    if t.ndim==3:t=t[...,None]
    if not is_mask:t=working(t,space,c.get('processing','HDR (ACEScct)'),is_hdr(c['space']))
    else:t=(t>.001).float()
    if c.get('framing_mode')=='Source resolution (pad, no resize)':
        pass  # Keep source pixels exact; only the model-grid padding below is added.
    elif c.get('framing_mode') in ('Full frame (original method)','Full frame (fit, no crop)'):
        t=resize_fullframe(t,rh,rw,c.get('resampler','float32_bicubic_antialias'),is_mask)
    else:t=resize(t,rh,rw,'area' if is_mask else 'bilinear')
    if is_mask:t=(t>0).float()
    t=F.pad(t.permute(0,3,1,2),(0,pw-rw,0,ph-rh),mode='replicate').permute(0,2,3,1)
    return t

class ZuraPaintoutCrop:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{
        'plate_path':string(''), 'mask_path':string(''),
        'colour_space':(COLOUR_SPACES,),
        'start_frame':integer(0),'frame_count':integer(81,1,993),'sequence_fps':floating(25,1,120),
        'context_pixels':integer(128,32,2048),'max_crop_side':integer(768,128,2048),
        'repair_grow':integer(16,0,256),'feather_pixels':integer(24,0,256)},'optional':{'processing_mode':(PROCESSING_MODES,), 'framing_mode':(['Smart crop (experimental)','Full frame (original method)','Full frame (fit, no crop)','Source resolution (pad, no resize)'],), 'render_width':integer(1152,64,4096), 'render_height':integer(640,64,4096)}}
    RETURN_TYPES=('IMAGE','MASK','ZURA_PLATE','INT','INT','INT','FLOAT','STRING')
    RETURN_NAMES=('crop_frames','crop_mask','plate','width','height','padded_frames','fps','crop_report')
    FUNCTION='prepare'; CATEGORY=CATEGORY
    @classmethod
    def IS_CHANGED(cls,**kw):return float('nan')
    @cpu_frames
    def prepare(self,plate_path,mask_path,colour_space,start_frame,frame_count,sequence_fps,context_pixels,max_crop_side,repair_grow,feather_pixels,processing_mode='HDR (ACEScct)',framing_mode='Smart crop (experimental)',render_width=1152,render_height=640):
        if not str(plate_path).strip():raise ValueError('Select the original footage before running the paintout')
        if not isinstance(mask_path,dict) and not str(mask_path).strip():raise ValueError('Select matching removal-mask footage: white = remove, black = keep')
        d=describe(plate_path);m=mask_path if isinstance(mask_path,dict) else describe(mask_path)
        colour_space=selected_space(d,colour_space)
        if (m['width'],m['height'])!=(d['width'],d['height']):raise ValueError('Mask and plate dimensions must match exactly')
        if d['kind']=='video' and m['kind']=='video' and abs(d['fps']-m['fps'])>.001:raise ValueError('Mask/plate fps mismatch')
        if d['count'] and start_frame+frame_count>d['count']:raise ValueError('Requested plate frame range is too long')
        W,H=d['width'],d['height']
        if render_width%64 or render_height%64:raise ValueError('Render width and height must be multiples of 64')
        if framing_mode not in ('Smart crop (experimental)','Full frame (original method)','Full frame (fit, no crop)','Source resolution (pad, no resize)'):raise ValueError('Unknown framing mode')
        if framing_mode=='Source resolution (pad, no resize)':
            render_width,render_height=math.ceil(W/64)*64,math.ceil(H/64)*64
            if max(render_width,render_height)>4096:raise ValueError('Source resolution exceeds 4096 pixels. Choose a smaller processing resolution.')
        if framing_mode!='Smart crop (experimental)':
            if framing_mode=='Full frame (original method)':
                aspect=render_width/render_height
                if W/H>aspect: cw,ch=round(H*aspect),H
                else:cw,ch=W,round(W/aspect)
                x0,y0=(W-cw)//2,(H-ch)//2
            else:x0,y0,cw,ch=0,0,W,H
            if framing_mode=='Source resolution (pad, no resize)':rw,rh=W,H
            elif framing_mode=='Full frame (fit, no crop)':
                scale=min(render_width/W,render_height/H);rw,rh=max(1,round(W*scale)),max(1,round(H*scale))
            else:rw,rh=render_width,render_height
            x1,y1=x0+cw,y0+ch
            has_mask=False
            for a in mask_frames(m,start_frame,frame_count):
                yy,xx=np.where(a>.001)
                if len(xx):
                    has_mask=True
                    if framing_mode=='Full frame (original method)' and (xx.min()<x0 or xx.max()>=x1 or yy.min()<y0 or yy.max()>=y1):raise ValueError('The removal mask extends outside the selected full-frame crop. Use Full frame (fit, no crop), or adjust the mask.')
            if not has_mask:raise ValueError('Mask is empty: white must mark the object to remove')
            w,h=cw,ch;pw,ph=render_width,render_height
        else:
            x0,y0,x1,y1=W,H,0,0
        if framing_mode=='Smart crop (experimental)':
            for a in mask_frames(m,start_frame,frame_count):
                yy,xx=np.where(a>.001)
                if len(xx):x0=min(x0,int(xx.min()));x1=max(x1,int(xx.max())+1);y0=min(y0,int(yy.min()));y1=max(y1,int(yy.max())+1)
            if x1<=x0:raise ValueError('Mask is empty: white must mark the object to remove')
            margin=max(context_pixels,repair_grow+feather_pixels+32)
            x0=max(0,x0-margin);y0=max(0,y0-margin);x1=min(W,x1+margin);y1=min(H,y1+margin)
            w,h=x1-x0,y1-y0;scale=min(1.,max_crop_side/max(w,h));rw=max(1,round(w*scale));rh=max(1,round(h*scale))
            pw=max(64,math.ceil(rw/64)*64);ph=max(64,math.ceil(rh/64)*64)
        else:scale=min(rw/w,rh/h)
        padded=math.ceil((frame_count-1)/8)*8+1
        resampler=('comfy_lanczos' if processing_mode=='SDR (sRGB)' else 'float32_bicubic_antialias') if framing_mode!='Smart crop (experimental)' else 'bilinear'
        c=dict(source=d,mask=m,space=colour_space,processing=processing_mode,start=start_frame,count=frame_count,fps=d.get('fps',sequence_fps),rect=[x0,y0,w,h],resized=[rh,rw],padded=[ph,pw],grow=repair_grow,feather=feather_pixels,framing_mode=framing_mode,resampler=resampler)
        ims=[];ms=[];progress=frame_progress(frame_count)
        for a,b in zip(frames(d,start_frame,frame_count),mask_frames(m,start_frame,frame_count)):
            if a.shape[:2]!=(H,W) or b.shape!=(H,W):raise ValueError('Sequence resolution changes mid-shot')
            ims.append(crop_work(a,c,colour_space));ms.append(crop_work(b,c,colour_space,True)[...,0])
            progress(len(ims))
        image=torch.cat(ims);mask=torch.cat(ms)
        # Grow the conditioning mask at inference scale; final matte is built in original pixels.
        grow=math.ceil(repair_grow*scale)
        if grow:mask=F.max_pool2d(mask[:,None],2*grow+1,1,grow)[:,0]
        if padded>frame_count:
            image=torch.cat([image,image[-1:].expand(padded-frame_count,-1,-1,-1)])
            mask=torch.cat([mask,mask[-1:].expand(padded-frame_count,-1,-1)])
        report=f'{frame_count} delivered / {padded} inference frames, {c["fps"]:g} fps. {framing_mode}: {w}x{h} at ({x0},{y0}) -> {rw}x{rh}, padded to {pw}x{ph}. Resampler: {resampler}.'
        c['_work_images']=image;c['_work_mask']=mask
        return image,mask,c,pw,ph,padded,float(c['fps']),report

class ZuraPaintoutAnchors:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'plate':('ZURA_PLATE',),'anchors':string('[]',multiline=True)}}
    RETURN_TYPES=('ZURA_ANCHORS','STRING');RETURN_NAMES=('anchors','anchor_report');FUNCTION='load';CATEGORY=CATEGORY
    @classmethod
    def IS_CHANGED(cls,**kw):return float('nan')
    @cpu_frames
    def load(self,plate,anchors):
        rows=json.loads(anchors)
        if not isinstance(rows,list):raise ValueError('Anchors must be a JSON list of {frame,file,strength,enabled}')
        out=[];seen=set();report=[]
        for row in rows:
            if not row.get('enabled',True):continue
            f=int(row['frame']);f=plate['start']+plate['count']-1 if f==-1 else f
            i=f-plate['start']
            if not 0<=i<plate['count']:raise ValueError(f'Anchor frame {f} is outside selected source range')
            if i in seen:raise ValueError(f'Duplicate anchor frame {f}')
            seen.add(i);path=row['file'];a=read_image(path)
            if a.shape[:2]!=(plate['source']['height'],plate['source']['width']):raise ValueError(f'Anchor {f} must be a full-resolution painted plate, without cropping or resizing')
            if is_hdr(plate['space']) and plate.get('processing')!='SDR (sRGB)' and Path(path).suffix.lower() not in ('.exr','.tif','.tiff'):raise ValueError('HDR anchors must be EXR or high bit depth TIFF. Export paint frames using this pack first.')
            strength=float(row.get('strength',.75))
            if not 0<strength<=1:raise ValueError('Anchor strength must be >0 and <=1')
            anchor_space=row.get('colour_space') or ('acescg' if plate['space'] in ('hlg_rec2020','pq_rec2020') else plate['space'])
            out.append((i,crop_work(a,plate,anchor_space),strength));report.append(f'Source {f} -> local {i}: {Path(path).name} ({strength:g})')
        if not out:raise ValueError('Add at least one enabled manually painted clean anchor')
        return sorted(out,key=lambda x:x[0]),'\n'.join(report)

class ZuraPaintoutAnchorFiles:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'anchors':string('[]',multiline=True)}}
    RETURN_TYPES=('ZURA_ANCHOR_FILES',);RETURN_NAMES=('painted_files',);FUNCTION='select';CATEGORY=CATEGORY
    @classmethod
    def IS_CHANGED(cls,**kw):return float('nan')
    def select(self,anchors):
        rows=json.loads(anchors)
        if not isinstance(rows,list):raise ValueError('Painted frames must be a list')
        rows=[r for r in rows if r.get('enabled',True)]
        if not rows:raise ValueError('Browse to at least one manually painted clean frame')
        return (rows,)

def painted_bounds(d,rows,space,start,count,processing):
    """Infer one conservative repair rectangle from aligned painted originals.

    Coherent edited regions become seeds for optical-flow tracking. Additional
    anchors still help when subjects are occluded or leave the visible frame.
    """
    W,H=d['width'],d['height'];x0,y0,x1,y1=W,H,0,0;seen=set();seeds={}
    for row in rows:
        f=int(row['frame']);f=start+count-1 if f==-1 else f
        if not start<=f<start+count:raise ValueError(f'Painted frame {f} is outside the selected source range')
        if f in seen:raise ValueError(f'Duplicate painted frame {f}')
        seen.add(f)
        painted=read_image(row['file'])
        if painted.shape!=(H,W,3):raise ValueError('Painted frames must keep the original full-frame dimensions and alignment')
        original=next(frames(d,f,1))
        anchor_space=row.get('colour_space') or ('acescg' if space in ('hlg_rec2020','pq_rec2020') else space)
        source_work=working(torch.from_numpy(original),space,processing,is_hdr(space))
        paint_work=working(torch.from_numpy(painted),anchor_space,processing,is_hdr(space))
        changed=(source_work-paint_work).abs().amax(-1).numpy()>.025
        # Suppress codec/rounding texture before finding coherent painted edits.
        import cv2
        kernel=max(3,int(round(min(W,H)/150))|1)
        changed=cv2.medianBlur(changed.astype(np.uint8),kernel)
        components,labels,stats,_=cv2.connectedComponentsWithStats(changed,connectivity=8)
        eligible=np.where(stats[1:,cv2.CC_STAT_AREA]>=max(16,round(W*H/4000)))[0]+1
        if not len(eligible):continue
        seeds[f-start]=np.isin(labels,eligible).astype(np.uint8)*255
        for i in eligible:
            x,y,w,h,_=stats[i];x0=min(x0,int(x));y0=min(y0,int(y));x1=max(x1,int(x+w));y1=max(y1,int(y+h))
    if x1<=x0:raise ValueError('No painted changes detected. Use edited clean frames aligned with the original, with the correct colour space.')
    return track_painted_regions(d,seeds,space,start,count)

def track_painted_regions(d,seeds,space,start,count):
    """CPU optical-flow propagation between actual painted edits, with anchor resets."""
    import cv2
    W,H=d['width'],d['height'];scale=min(1.,576/max(W,H));w=max(16,round(W*scale));h=max(16,round(H*scale))
    seeds={i:cv2.resize(m,(w,h),interpolation=cv2.INTER_AREA) for i,m in seeds.items()}
    seeds={i:((m>32).astype(np.uint8)*255) for i,m in seeds.items()}
    grey=[]
    if d['kind']=='video':
        cap=cv2.VideoCapture(d['path']);cap.set(cv2.CAP_PROP_POS_FRAMES,start)
        try:
            for _ in range(count):
                ok,a=cap.read()
                if not ok:raise ValueError('Video ended during automatic paint tracking')
                grey.append(cv2.cvtColor(cv2.resize(a,(w,h)),cv2.COLOR_BGR2GRAY))
        finally:cap.release()
    else:
        for a in frames(d,start,count):
            small=torch.from_numpy(cv2.resize(a,(w,h)))
            view=working(small,space,'HDR (ACEScct)').numpy()
            grey.append(cv2.cvtColor((view.clip(0,1)*255).astype(np.uint8),cv2.COLOR_RGB2GRAY))
    dis=cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST);dis.setFinestScale(1)
    yy,xx=np.mgrid[:h,:w].astype(np.float32)
    def warp(mask,dest,source):
        flow=dis.calc(dest,source,None)
        return cv2.remap(mask,xx+flow[...,0],yy+flow[...,1],cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT)
    forward=[];mask=None
    for i in range(count):
        if i in seeds:mask=seeds[i].copy()
        elif mask is not None:mask=warp(mask,grey[i],grey[i-1])
        forward.append(mask.copy() if mask is not None else None)
    folder=Path(tempfile.gettempdir())/'zura_paintout_tracking'/uuid.uuid4().hex;folder.mkdir(parents=True)
    files=[None]*count;mask=None
    for i in range(count-1,-1,-1):
        if i in seeds:mask=seeds[i].copy()
        elif mask is not None:mask=warp(mask,grey[i],grey[i+1])
        combined=forward[i] if mask is None else mask if forward[i] is None else np.maximum(mask,forward[i])
        if i in seeds:combined=seeds[i]
        if combined is None:raise ValueError('Automatic tracking has no painted reference')
        combined=cv2.morphologyEx(combined,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        file=folder/f'{i:06d}.png';cv2.imwrite(str(file),combined);files[i]=str(file)
    return dict(kind='painted_tracking',width=W,height=H,count=count,start=start,files=files)

class ZuraPaintoutFromAnchors(ZuraPaintoutCrop):
    @classmethod
    def INPUT_TYPES(cls):
        schema=ZuraPaintoutCrop.INPUT_TYPES();del schema['required']['mask_path']
        schema['required']={'anchor_files':('ZURA_ANCHOR_FILES',),**schema['required']}
        return schema
    RETURN_TYPES=ZuraPaintoutCrop.RETURN_TYPES+('ZURA_ANCHORS',)
    RETURN_NAMES=ZuraPaintoutCrop.RETURN_NAMES+('painted_guides',)
    @cpu_frames
    def prepare(self,anchor_files,plate_path,colour_space,start_frame,frame_count,sequence_fps,context_pixels,max_crop_side,repair_grow,feather_pixels,processing_mode='HDR (ACEScct)',framing_mode='Smart crop (experimental)',render_width=1152,render_height=640):
        d=describe(plate_path);space=selected_space(d,colour_space)
        matte=painted_bounds(d,anchor_files,space,start_frame,frame_count,processing_mode)
        result=super().prepare(plate_path,matte,colour_space,start_frame,frame_count,sequence_fps,context_pixels,max_crop_side,repair_grow,feather_pixels,processing_mode,framing_mode,render_width,render_height)
        guides,_=ZuraPaintoutAnchors().load(result[2],json.dumps(anchor_files))
        result[2]['repair_method']='Painted differences propagated with CPU optical flow and reset at clean anchors'
        return (*result,guides)

class ZuraPaintoutFullFrame(ZuraPaintoutCrop):
    @classmethod
    def INPUT_TYPES(cls):
        schema=ZuraPaintoutCrop.INPUT_TYPES();del schema['required']['mask_path'];return schema
    def prepare(self,plate_path,colour_space,start_frame,frame_count,sequence_fps,context_pixels,max_crop_side,repair_grow,feather_pixels,processing_mode='SDR (sRGB)',framing_mode='Full frame (fit, no crop)',render_width=1152,render_height=640):
        d=describe(plate_path);matte=dict(kind='rectangle',width=d['width'],height=d['height'],count=d['count'],rect=[0,0,d['width'],d['height']])
        return super().prepare(plate_path,matte,colour_space,start_frame,frame_count,sequence_fps,context_pixels,max_crop_side,0,0,processing_mode,framing_mode,render_width,render_height)

class ZuraPaintoutApplyAnchors:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'positive':('CONDITIONING',),'negative':('CONDITIONING',),'vae':('VAE',),'latent':('LATENT',),'anchors':('ZURA_ANCHORS',)}}
    RETURN_TYPES=('CONDITIONING','CONDITIONING','LATENT');FUNCTION='apply';CATEGORY=CATEGORY
    def apply(self,positive,negative,vae,latent,anchors):
        import nodes
        cls=nodes.NODE_CLASS_MAPPINGS['LTXAddVideoICLoRAGuide']
        for index,image,strength in anchors:
            result=cls.execute(positive=positive,negative=negative,vae=vae,latent=latent,image=image,frame_idx=index,strength=strength,latent_downscale_factor=1.,crop='disabled',use_tiled_encode=False,tile_size=256,tile_overlap=64)
            positive,negative,latent=result[0],result[1],result[2]
        return positive,negative,latent

class ZuraPaintoutVAE:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'vae':('VAE',)}}
    RETURN_TYPES=('VAE',);FUNCTION='patch';CATEGORY=CATEGORY
    def patch(self,vae):
        vae.vae_dtype=torch.float32
        vae.first_stage_model.to(dtype=torch.float32)
        return (vae,)

def composite_crop(original,generated,mask,grow,feather,match,fit_override=None):
    binary=mask>.001
    if not binary.any():return original.copy(),dict(gain=[1,1,1],offset=[0,0,0])
    expanded=maximum_filter(binary,size=2*grow+1) if grow else binary
    # Outward feather, completely opaque over the original object.
    distance=distance_transform_edt(~expanded)
    alpha=(np.clip(1-distance/max(feather,1),0,1) if feather else expanded.astype(np.float32))
    alpha[expanded]=1
    gain=np.ones(3,dtype=np.float32);offset=np.zeros(3,dtype=np.float32)
    if match:
        # Only unchanged context outside the transition is eligible for colour fitting.
        ring=(distance>feather+2)&(distance<=feather+48)
        valid=ring & np.isfinite(generated).all(-1) & np.isfinite(original).all(-1)
        if valid.sum()>=64:
            a=generated[valid];b=original[valid]
            # Robust diagonal affine fit, bounded to avoid unstable relighting.
            aq=np.percentile(a,[20,50,80],axis=0);bq=np.percentile(b,[20,50,80],axis=0)
            spread=aq[2]-aq[0];gain=np.where(spread>1e-5,(bq[2]-bq[0])/np.maximum(spread,1e-5),1).clip(.8,1.25).astype(np.float32)
            offset=(bq[1]-gain*aq[1]).astype(np.float32)
    if fit_override is not None:
        gain=np.asarray(fit_override['gain'],dtype=np.float32);offset=np.asarray(fit_override['offset'],dtype=np.float32)
    adjusted=generated*gain+offset
    result=original.copy();active=alpha>0
    # Assignment only inside support guarantees identical untouched RGB pixels.
    result[active]=original[active]*(1-alpha[active,None])+adjusted[active]*alpha[active,None]
    return result,dict(gain=gain.tolist(),offset=offset.tolist())

def save_exr(path,a,space,half):
    # Delegate to the installed LTX EXR writer without its VAE-decode clamping.
    # The unclamped writer preserves negative plate values outside the repair.
    import sys
    registered=getattr(sys.modules.get('nodes'),'NODE_CLASS_MAPPINGS',{})
    writer=registered.get('LTXVHDRDecodePostprocess')
    if writer and space in ('acescg','acescct','linear_rec709'):
        import importlib
        primaries=importlib.import_module(writer.__module__.rsplit('.',1)[0]+'.hdr_color').Primaries
        writer._save_exr_frames_tagged(torch.from_numpy(np.ascontiguousarray(a))[None],str(Path(path).parent),Path(path).stem,half,primaries=primaries.REC709 if space=='linear_rec709' else primaries.ACESCG,color_space_tag={'acescg':'ACEScg','acescct':'ACEScct','linear_rec709':'sRGB'}[space])
        # Native sequence writer appends its own index, even for one frame.
        Path(path).with_name(Path(path).stem+'_00000.exr').replace(path)
        return
    import OpenImageIO as oiio
    spec=oiio.ImageSpec(a.shape[1],a.shape[0],3,oiio.HALF if half else oiio.FLOAT)
    spec.channelnames=('R','G','B');spec.attribute('oiio:ColorSpace',{'acescg':'ACEScg','acescct':'ACEScct','linear_rec709':'Linear Rec709','srgb_display':'sRGB','rec709_gamma24':'Rec709 Gamma 2.4','rec709_oetf':'Rec709 OETF'}[space]);spec.attribute('compression','zip')
    if space in ('acescg','acescct'):spec.attribute('chromaticities',oiio.TypeDesc('float[8]'),(.713,.293,.165,.830,.128,.044,.32168,.33767))
    else:spec.attribute('chromaticities',oiio.TypeDesc('float[8]'),(.64,.33,.30,.60,.15,.06,.3127,.3290))
    out=oiio.ImageOutput.create(str(path))
    if not out or not out.open(str(path),spec):raise RuntimeError(f'Cannot create EXR: {path}')
    try:
        if not out.write_image(a.astype(np.float32)):raise RuntimeError(out.geterror())
    finally:out.close()

class ZuraPaintoutUncrop:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'decoded_crop':('IMAGE',),'plate':('ZURA_PLATE',),'output_name':string('paintout/take'),'precision':(['float32','float16'],),'match_context':('BOOLEAN',{'default':True})},'optional':{'export_format':(EXPORT_FORMATS,), 'motion_preview':('BOOLEAN',{'default':True})}}
    RETURN_TYPES=('STRING',);RETURN_NAMES=('saved_sequence',);OUTPUT_NODE=True;FUNCTION='save';CATEGORY=CATEGORY
    @cpu_frames
    def save(self,decoded_crop,plate,output_name,precision,match_context,export_format='EXR sequence',motion_preview=False):
        import folder_paths
        if len(decoded_crop)<plate['count']:raise ValueError('Decoded sequence is shorter than source range')
        ph,pw=plate['padded'];rh,rw=plate['resized'];x,y,w,h=plate['rect']
        if tuple(decoded_crop.shape[1:3])!=(ph,pw):raise ValueError('Decoded crop size differs from crop metadata')
        base=Path(folder_paths.get_output_directory());relative=Path(output_name)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Output name must be relative to ComfyUI output')
        root=base/relative;root.parent.mkdir(parents=True,exist_ok=True)
        for i in range(1,100000):
            target=root.parent/f'{root.name}_{i:04d}'
            try:target.mkdir();break
            except FileExistsError:continue
        else:raise RuntimeError('No free output folder')
        from .media import Delivery
        delivery=Delivery(target,plate,export_format,motion_preview)
        metrics=[]; shared_fit=None
        if match_context:
            # One robust correction for the whole selected shot, avoiding framewise grade pumping.
            fits=[]
            fit_frames=set(np.linspace(0,plate['count']-1,min(12,plate['count']),dtype=int).tolist())
            for i,(a,m) in enumerate(zip(frames(plate['source'],plate['start'],plate['count']),mask_frames(plate['mask'],plate['start'],plate['count']))):
                if i not in fit_frames:continue
                raw=decoded_crop[i:i+1,:rh,:rw,:3].detach().float().cpu()
                generated=resize(unworking(raw,plate['space'],plate.get('processing','HDR (ACEScct)')),h,w)[0].numpy()
                src=to_linear(torch.from_numpy(a[y:y+h,x:x+w].copy()),plate['space']).numpy()
                _,fit=composite_crop(src,generated,m[y:y+h,x:x+w],plate['grow'],plate['feather'],True)
                fits.append(fit)
            shared_fit={key:np.median([f[key] for f in fits],axis=0).tolist() for key in ('gain','offset')}
        progress=frame_progress(plate['count'])
        for i,(a,m) in enumerate(zip(frames(plate['source'],plate['start'],plate['count']),mask_frames(plate['mask'],plate['start'],plate['count']))):
            raw=decoded_crop[i:i+1,:rh,:rw,:3].detach().float().cpu()
            generated=resize(unworking(raw,plate['space'],plate.get('processing','HDR (ACEScct)')),h,w)[0].numpy()
            src=to_linear(torch.from_numpy(a[y:y+h,x:x+w].copy()),plate['space']).numpy()
            result,fit=composite_crop(src,generated,m[y:y+h,x:x+w],plate['grow'],plate['feather'],False,shared_fit)
            encoded=from_linear(torch.from_numpy(result),plate['space']).numpy()
            # Keep original encoded values outside the matte, including negatives and HDR highlights.
            matte=maximum_filter(m[y:y+h,x:x+w]>.001,size=2*plate['grow']+1)
            support=distance_transform_edt(~matte)<plate['feather'] if plate['feather'] else matte
            support|=matte
            if not matte.any():support[:]=False
            region=a[y:y+h,x:x+w].copy();region[support]=encoded[support]
            a[y:y+h,x:x+w]=region
            linear=to_linear(torch.from_numpy(a),plate['space'])
            if export_format not in ('HLG video','SDR video'):
                # Preserve original ACEScg EXR pixels exactly. Other sources are delivered in ACEScg.
                master=a if plate['space']=='acescg' else linear.numpy()
                save_exr(target/f'frame_{plate["start"]+i:06d}.exr',master,'acescg',precision=='float16')
            delivery.append(linear)
            metrics.append(fit)
            progress(i+1)
        metadata=dict(plate={k:v for k,v in plate.items() if not k.startswith('_')},precision=precision,match_context=match_context,colour_fits=metrics,notes='RGB only. Source alpha/AOV/header metadata are not copied. Video exports copy source audio when present, trimmed to the selected range. Sequence fps is authoritative.')
        (target/'paintout.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
        previews=delivery.finish()
        return {'ui':{'text':[f'Saved {plate["count"]} frames: {target}'],**previews},'result':(str(target),)}

class ZuraPaintoutExportFrames:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'plate_path':string(''),'colour_space':(COLOUR_SPACES,),'frame_numbers':string('0, 40, 80'),'output_name':string('paintout/paint_frames')}}
    RETURN_TYPES=('STRING',);RETURN_NAMES=('anchor_manifest',);OUTPUT_NODE=True;FUNCTION='export';CATEGORY=CATEGORY
    @classmethod
    def IS_CHANGED(cls,**kw):return float('nan')
    def export(self,plate_path,colour_space,frame_numbers,output_name):
        import folder_paths
        d=describe(plate_path)
        colour_space=selected_space(d,colour_space)
        indices=[int(t.strip()) for t in frame_numbers.split(',') if t.strip()]
        if not indices or len(set(indices))!=len(indices):raise ValueError('Enter distinct zero-based frame numbers separated by commas')
        if any(i<0 or (d['count'] and i>=d['count']) for i in indices):raise ValueError('Requested paint frame is outside the plate range')
        relative=Path(output_name)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Use a relative output folder')
        base=Path(folder_paths.get_output_directory())/relative;base.parent.mkdir(parents=True,exist_ok=True)
        for i in range(1,100000):
            target=base.parent/f'{base.name}_{i:04d}'
            try:target.mkdir();break
            except FileExistsError:continue
        else:raise RuntimeError('No free output folder')
        rows=[]
        for f in sorted(indices):
            path=target/f'paint_{f:06d}.exr';a=next(frames(d,f,1));save_exr(path,to_linear(torch.from_numpy(a),colour_space).numpy(),'acescg',False)
            rows.append(dict(frame=f,file=str(path),strength=.75,enabled=True,colour_space='acescg'))
        manifest=json.dumps(rows,indent=2);(target/'anchors.json').write_text(manifest,encoding='utf-8')
        return {'ui':{'text':[f'Paint the exported full-frame EXRs, preserving colour space and dimensions. Anchor list: {target / "anchors.json"}',manifest]},'result':(manifest,)}

class ZuraPaintoutTake:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'plate':('ZURA_PLATE',)}}
    RETURN_TYPES=('IMAGE','MASK','INT','INT','INT','FLOAT');RETURN_NAMES=('images','mask','width','height','frames','fps');FUNCTION='unpack';CATEGORY=CATEGORY
    def unpack(self,plate):
        im=plate['_work_images'];return im,plate['_work_mask'],im.shape[2],im.shape[1],im.shape[0],float(plate['fps'])

NODE_CLASS_MAPPINGS={c.__name__:c for c in (ZuraPaintoutCrop,ZuraPaintoutAnchors,ZuraPaintoutAnchorFiles,ZuraPaintoutFromAnchors,ZuraPaintoutFullFrame,ZuraPaintoutApplyAnchors,ZuraPaintoutVAE,ZuraPaintoutUncrop,ZuraPaintoutExportFrames,ZuraPaintoutTake)}
NODE_DISPLAY_NAME_MAPPINGS=dict(ZuraPaintoutCrop='Load High Bit Depth Footage',ZuraPaintoutAnchors='Painted Clean Frames',ZuraPaintoutApplyAnchors='Apply Painted Anchors',ZuraPaintoutVAE='HDR VAE Float32',ZuraPaintoutUncrop='Blend + Export EXR / HLG',ZuraPaintoutExportFrames='Export Frames for Manual Paint')
NODE_DISPLAY_NAME_MAPPINGS.update(ZuraPaintoutAnchorFiles='Painted Clean Frames',ZuraPaintoutFromAnchors='Load High Bit Depth Footage')
