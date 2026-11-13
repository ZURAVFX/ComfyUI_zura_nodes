"""Pinned full-precision alpha, read separately from the HDR RGB model pass."""
from fractions import Fraction
import hashlib,json,re
from pathlib import Path

import numpy as np
from ..comfylink import float_io

PROOF_NAME='zura_hdr_delivery.json'
SHA=re.compile(r'^[a-f0-9]{64}$')

def alpha_hash(alpha):return hashlib.sha256(np.ascontiguousarray(alpha,dtype='<f4').tobytes()).hexdigest()

def output_path(root,reference):
    if not isinstance(reference,dict) or reference.get('type')!='output':raise ValueError('Choose an available alpha master.')
    name,folder=reference.get('filename'),reference.get('subfolder','')
    if (not isinstance(name,str) or not name or Path(name).name!=name or any(c in name for c in ('\\',':','\0','/'))
            or not isinstance(folder,str) or any(c in folder for c in ('\\',':','\0'))):raise ValueError('Invalid alpha master reference.')
    root=Path(root).resolve();path=(root/folder/name).resolve()
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('The selected alpha master is unavailable.')
    return path

def _rate(value):
    if not isinstance(value,dict) or any(type(value.get(k)) is not int or value[k]<1 for k in ('numerator','denominator')):raise ValueError('Invalid alpha frame rate.')
    return Fraction(value['numerator'],value['denominator'])

class HDRAlphaSource:
    def __init__(self,root,reference,*,width,height,count,frame_rate,image=False):
        self.root=Path(root).resolve();self.path=output_path(root,reference);self.reference=dict(reference)
        self.width,self.height,self.count,self.rate=width,height,count,Fraction(frame_rate)
        if any(type(v) is not int or v<1 for v in (width,height,count)) or width*height>64*1024*1024 or count>10000 or not 0<self.rate<=1000:raise ValueError('Alpha delivery dimensions or timing exceed supported bounds.')
        self.source_start=None;self.image=image;self.manifest=None
        if image:
            self.kind='rgba_image';self.digest=hashlib.sha256(float_io._read_private(self.path,512*1024*1024)).hexdigest()
        elif self.path.name=='alpha_manifest.json':
            self.kind='alpha_float32';raw=float_io._read_private(self.path,2*1024*1024);self.digest=hashlib.sha256(raw).hexdigest();self.manifest=json.loads(raw)
            m=self.manifest
            if (set(m)!={'schemaVersion','kind','sampleType','layout','byteOrder','width','height','frameRate','sourceStart','frames'}
                    or type(m.get('schemaVersion')) is not int or m['schemaVersion']!=1 or m.get('kind')!='alpha_float32'
                    or m.get('sampleType')!='float32' or m.get('layout')!='A' or m.get('byteOrder')!='little'
                    or type(m.get('width')) is not int or type(m.get('height')) is not int or m.get('width')!=width or m.get('height')!=height or _rate(m.get('frameRate'))!=self.rate
                    or not isinstance(m.get('frames'),list) or len(m['frames'])!=count):raise ValueError('The FLOAT alpha master does not match the HDR source.')
            self.source_start=m['sourceStart'];_rate_nonnegative(self.source_start)
            for index,entry in enumerate(m['frames']):
                if (not isinstance(entry,dict) or set(entry)!={'filename','byteLength','sha256'} or entry['filename']!=f'{index:06d}.alpha32f'
                        or type(entry['byteLength']) is not int or entry['byteLength']!=width*height*4 or not isinstance(entry['sha256'],str) or not SHA.fullmatch(entry['sha256'])):raise ValueError('Invalid FLOAT alpha frame descriptor.')
        elif self.path.name=='manifest.json':
            self.kind='float_manifest';self.relative=self.path.relative_to(self.root).as_posix();self.manifest=float_io.read_manifest(self.root,self.relative)
            m=self.manifest;self.digest=hashlib.sha256(float_io.canonical_manifest_bytes(m)).hexdigest()
            if (m['sampleType']!='float32' or m['sourceBitDepth']!=32 or m['alphaAssociation']!='straight'
                    or m['width']!=width or m['height']!=height or len(m['frames'])!=count or _rate(m['frameRate'])!=self.rate):raise ValueError('The RGBA FLOAT alpha source does not match the HDR source.')
            self.source_start=m.get('sourceStart')
        else:raise ValueError('Use the retained FLOAT alpha master rather than a video preview.')
        self.alpha_hashes=[alpha_hash(alpha) for alpha in self._frames()]
        if len(self.alpha_hashes)!=count:raise ValueError('The alpha master has the wrong number of frames.')

    def verify(self):
        if self.kind=='float_manifest':
            current=float_io.read_manifest(self.root,self.relative);digest=hashlib.sha256(float_io.canonical_manifest_bytes(current)).hexdigest()
        else:digest=hashlib.sha256(float_io._read_private(self.path,512*1024*1024 if self.image else 2*1024*1024)).hexdigest()
        if digest!=self.digest:raise ValueError('The retained alpha source changed during HDR conversion.')

    def _image_alpha(self):
        import OpenImageIO as oiio
        config=oiio.ImageSpec();config.attribute('oiio:UnassociatedAlpha',1)
        inp=oiio.ImageInput.open(str(self.path),config)
        if inp is None:raise ValueError('The image alpha could not be read.')
        try:
            spec=inp.spec();names=[name.lower() for name in spec.channelnames]
            if (spec.width,spec.height)!=(self.width,self.height) or self.count!=1:raise ValueError('Image alpha dimensions do not match HDR delivery.')
            alpha_index=spec.alpha_channel if 0<=spec.alpha_channel<len(names) else next((index for index,name in enumerate(names) if name in ('a','alpha')),-1)
            if alpha_index<0:raise ValueError('The selected image has no alpha channel.')
            pixels=np.asarray(inp.read_image(format=oiio.FLOAT));return np.ascontiguousarray(pixels[...,alpha_index],dtype='<f4')
        finally:inp.close()

    def _frames(self):
        self.verify()
        if self.image:yield self._checked(self._image_alpha());return
        if self.kind=='float_manifest':
            for rgba in float_io.iter_transfer(self.root,self.relative):yield self._checked(rgba[...,3])
            return
        for entry in self.manifest['frames']:
            path=self.path.parent/entry['filename'];data=float_io._read_private(path,entry['byteLength'])
            if len(data)!=entry['byteLength'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('A retained FLOAT alpha frame changed.')
            yield self._checked(np.frombuffer(data,dtype='<f4').reshape(self.height,self.width))

    def _checked(self,alpha):
        alpha=np.ascontiguousarray(alpha,dtype='<f4')
        if alpha.shape!=(self.height,self.width) or not np.isfinite(alpha).all() or np.any(alpha<0) or np.any(alpha>1):raise ValueError('Alpha samples must be finite within 0–1.')
        return alpha

    def frames(self,check_cancelled=lambda:None):
        index=0
        for index,alpha in enumerate(self._frames()):
            check_cancelled()
            if index>=self.count or alpha_hash(alpha)!=self.alpha_hashes[index]:raise ValueError('Alpha changed while reading HDR delivery.')
            yield alpha
        if index+1!=self.count:raise ValueError('The alpha master ended before the HDR result.')
        self.verify()

    def proof(self):
        return {'kind':self.kind,'sha256':self.digest}

def _rate_nonnegative(value):
    if not isinstance(value,dict) or type(value.get('numerator')) is not int or value['numerator']<0 or type(value.get('denominator')) is not int or value['denominator']<1:raise ValueError('Invalid alpha source offset.')
    return Fraction(value['numerator'],value['denominator'])

def image_has_alpha(path):
    import OpenImageIO as oiio
    inp=oiio.ImageInput.open(str(path))
    if inp is None:raise ValueError('The image master could not be inspected.')
    try:return inp.spec().alpha_channel>=0 or any(name.lower() in ('a','alpha') for name in inp.spec().channelnames)
    finally:inp.close()

def read_straight_rgb(path):
    """OIIO otherwise associates PNG RGB before a caller can separate alpha."""
    import OpenImageIO as oiio
    config=oiio.ImageSpec();config.attribute('oiio:UnassociatedAlpha',1)
    inp=oiio.ImageInput.open(str(path),config)
    if inp is None:raise ValueError('The SDR image master could not be read.')
    try:
        names=[name.lower() for name in inp.spec().channelnames];pixels=np.asarray(inp.read_image(format=oiio.FLOAT))
        if pixels.ndim==2:pixels=pixels[...,None]
        if all(name in names for name in ('r','g','b')):rgb=pixels[...,[names.index(name) for name in ('r','g','b')]]
        else:
            indices=[index for index,name in enumerate(names) if index!=inp.spec().alpha_channel and name not in ('a','alpha')][:3];rgb=pixels[...,indices]
            if rgb.shape[-1]==1:rgb=np.repeat(rgb,3,axis=-1)
        if rgb.shape[-1]!=3 or not np.isfinite(rgb).all():raise ValueError('The SDR image has invalid RGB pixels.')
        return np.ascontiguousarray(rgb,dtype=np.float32)
    finally:inp.close()
