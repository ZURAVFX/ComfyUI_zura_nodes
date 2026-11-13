"""Unquantised, one-channel final alpha for colour-managed downstream delivery."""
from fractions import Fraction
import hashlib,json,math,os,shutil,subprocess,uuid
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

MAX_ALPHA_PIXELS=64*1024*1024
MAX_ALPHA_FRAMES=145

def _alpha_component(pixel_format):
    import av
    try:return any(component.is_alpha for component in av.VideoFormat(pixel_format).components)
    except (ValueError,TypeError):return False

def final_alpha_frames(images,info,source,ffmpeg,*,check_cancelled=lambda:None):
    """Resize in FLOAT, then multiply the source's existing alpha if present."""
    count,width,height=info['frame_count'],info['width'],info['height']
    process=None
    if _alpha_component(info.get('pixel_format')):
        trim=f"trim=start_frame={info['start_frame']}:end_frame={info['start_frame']+count},setpts=PTS-STARTPTS,alphaextract,format=grayf32le"
        process=subprocess.Popen([str(ffmpeg),'-v','error','-i',str(source),'-vf',trim,'-an','-sn','-fps_mode','passthrough','-f','rawvideo','-pix_fmt','grayf32le','pipe:1'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    try:
        for index in range(count):
            check_cancelled()
            frame=images[index,:info['content_height'],:info['content_width'],:3].detach().to(device='cpu',dtype=torch.float32)
            if not torch.isfinite(frame).all():raise ValueError('The generated matte contains invalid pixels.')
            matte=frame.mean(dim=-1)[None,None]
            if tuple(matte.shape[-2:])!=(height,width):matte=F.interpolate(matte,size=(height,width),mode='bilinear',align_corners=False)
            alpha=matte[0,0].clamp(0,1).numpy().copy()
            if process is not None:
                expected=width*height*4;parts=bytearray()
                while len(parts)<expected:
                    block=process.stdout.read(expected-len(parts))
                    if not block:raise ValueError('The source alpha ended before the selected range.')
                    parts.extend(block)
                original=np.frombuffer(parts,dtype='<f4').reshape(height,width)
                if not np.isfinite(original).all() or np.any(original<0) or np.any(original>1):raise ValueError('The source alpha is outside its finite 0–1 range.')
                alpha*=original
            yield np.ascontiguousarray(alpha,dtype='<f4')
        if process is not None:
            if process.stdout.read(1):raise ValueError('The source alpha contains extra selected frames.')
            if process.wait(timeout=30):raise ValueError('The source alpha could not be decoded.')
    finally:
        if process is not None:
            if process.poll() is None:process.kill();process.wait()
            process.stdout.close()


class AlphaFloatWriter:
    """Publish one bounded A-only manifest after every selected frame is saved."""
    def __init__(self,output,info):
        self.output=Path(output).resolve();self.info=info
        count,width,height=info['frame_count'],info['width'],info['height']
        if any(type(v) is not int or v<1 for v in (count,width,height)) or count>MAX_ALPHA_FRAMES or width*height>MAX_ALPHA_PIXELS:raise ValueError('Alpha FLOAT output exceeds its bounded source dimensions or frame count.')
        rate=Fraction(info['fps_rational'])
        if not 0<rate<=1000:raise ValueError('Invalid alpha FLOAT frame rate.')
        self.parent=self.output/'genj'/'alpha';assert self.parent.resolve().is_relative_to(self.output);self.parent.mkdir(parents=True,exist_ok=True)
        if shutil.disk_usage(self.parent).free<count*width*height*4+64*1024*1024:raise ValueError('Not enough space to retain the full-precision alpha master.')
        identity=uuid.uuid4().hex;self.directory=self.parent/('.alpha-float-'+identity);self.destination=self.parent/('alpha-float-'+identity)
        assert self.directory.resolve().is_relative_to(self.output) and self.destination.resolve().is_relative_to(self.output)
        self.directory.mkdir(exist_ok=False);self.frames=[];self.published=False
        self.manifest={'schemaVersion':1,'kind':'alpha_float32','sampleType':'float32','layout':'A','byteOrder':'little','width':width,'height':height,
            'frameRate':{'numerator':rate.numerator,'denominator':rate.denominator},
            'sourceStart':{'numerator':info['start_frame']*rate.denominator,'denominator':rate.numerator},'frames':self.frames}
    def write(self,index,alpha):
        if index!=len(self.frames) or index>=self.info['frame_count'] or alpha.shape!=(self.info['height'],self.info['width']):raise ValueError('Alpha FLOAT frames must retain their source order and raster.')
        data=np.ascontiguousarray(alpha,dtype='<f4')
        if not np.isfinite(data).all() or np.any(data<0) or np.any(data>1):raise ValueError('Alpha FLOAT samples must be finite within 0–1.')
        payload=data.tobytes();name=f'{index:06d}.alpha32f'
        with (self.directory/name).open('xb') as stream:stream.write(payload);stream.flush();os.fsync(stream.fileno())
        self.frames.append({'filename':name,'byteLength':len(payload),'sha256':hashlib.sha256(payload).hexdigest()})
    def finish(self):
        if len(self.frames)!=self.info['frame_count']:raise ValueError('The full-precision alpha master is incomplete.')
        payload=json.dumps(self.manifest,sort_keys=True,separators=(',',':')).encode()
        with (self.directory/'alpha_manifest.json').open('xb') as stream:stream.write(payload);stream.flush();os.fsync(stream.fileno())
        assert self.directory.resolve().parent==self.parent.resolve() and self.destination.resolve().parent==self.parent.resolve()
        if self.destination.exists():raise FileExistsError('Alpha FLOAT destination already exists.')
        self.directory.rename(self.destination);self.published=True
        relative=self.destination.relative_to(self.output)
        return {'filename':'alpha_manifest.json','subfolder':relative.as_posix(),'type':'output','role':'alpha_float'}
    def abort(self):
        if self.published:return
        if self.directory.is_symlink() or self.directory.resolve().parent!=self.parent.resolve():raise ValueError('Alpha staging directory changed.')
        for file in self.directory.iterdir():
            if file.is_symlink() or not file.is_file():raise ValueError('Unexpected alpha staging entry.')
            file.unlink()
        self.directory.rmdir()
