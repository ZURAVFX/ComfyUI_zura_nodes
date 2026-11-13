"""Read one original native ACEScg EXR ZIP frame without expanding a shot."""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
import os
import re
import stat
import struct
import tempfile
import threading
import zipfile
import zlib
import hashlib
import json

import numpy as np

from ..comfylink import float_io
from ..comfylink import archive_zip
from .hdr_alpha import PROOF_NAME, alpha_hash

MAX_FRAMES = 10000
MAX_PIXELS = 16 * 1024 * 1024
MAX_DIRECTORY = 8 * 1024 * 1024
MAX_HEADER = 1024 * 1024
MAX_FRAME_BYTES = MAX_PIXELS * 32 + 8 * 1024 * 1024
_FRAME = re.compile(r'frame_[0-9]{5}\.exr\Z')
_AP1 = (.713, .293, .165, .830, .128, .044, .32168, .33767)
_indexes = OrderedDict()
_index_lock = threading.RLock()


def _identity(value):
    # Python's Windows path stat and descriptor stat expose different ctime
    # semantics. File identity, byte length and modification time agree.
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


@contextmanager
def locked_archive(path):
    """Pin the selected archive and its parents; Windows denies writer swaps."""
    path = Path(path).absolute()
    with float_io._locked_parents(path.parent):
        before = float_io._safe_stat(path)
        if before.st_size > float_io.MAX_TRANSFER_BYTES: raise ValueError('The native HDR archive exceeds its byte limit.')
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            import msvcrt
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateFileW.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
            kernel.CreateFileW.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.CreateFileW(str(path),0x80000000,1,None,3,0x00200080,None)
            if handle == wintypes.HANDLE(-1).value: raise ValueError('The native HDR archive could not be locked for preview.')
            try: fd = msvcrt.open_osfhandle(handle, os.O_RDONLY|os.O_BINARY)
            except Exception:
                kernel.CloseHandle(handle);raise
        else:
            fd = os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        with os.fdopen(fd,'rb') as source:
            opened = os.fstat(source.fileno())
            if _identity(before) != _identity(opened): raise ValueError('The native HDR archive identity changed.')
            yield source,_identity(opened)
            if (_identity(os.fstat(source.fileno())) != _identity(opened)
                    or _identity(float_io._safe_stat(path)) != _identity(opened)):
                raise ValueError('The original HDR archive changed during preview.')


def _read(source,size):
    value = source.read(size)
    if len(value) != size: raise ValueError('The native HDR archive is truncated.')
    return value


def _directory(source,size):
    """Bound the central directory before zipfile allocates its member index."""
    directory=archive_zip.bounded_directory(source,size,max_entries=MAX_FRAMES+1,max_directory=MAX_DIRECTORY)
    return directory.count,directory.offset


def _member_start(source,entry):
    return archive_zip.member_start(source,entry)


class _Member:
    def __init__(self,source,entry):
        self.source=source;self.left=entry['size'];_member_start(source,entry)
    def read(self,size):
        if size<0 or size>self.left:raise ValueError('The native EXR header exceeds its member.')
        value=_read(self.source,size);self.left-=size;return value


def _cstring(source,limit=255):
    value=bytearray()
    while len(value)<=limit:
        char=source.read(1)
        if char==b'\0':return bytes(value)
        value+=char
    raise ValueError('The native EXR header contains an oversized name.')


def _header(source,entry):
    member=_Member(source,entry)
    if member.read(8)!=b'\x76\x2f\x31\x01\x02\x00\x00\x00':
        raise ValueError('Only native scanline EXR frames are supported.')
    attributes={};total=8
    while True:
        name=_cstring(member);total+=len(name)+1
        if not name:break
        kind=_cstring(member);length=struct.unpack('<L',member.read(4))[0];total+=len(kind)+5+length
        if total>MAX_HEADER or name in attributes:raise ValueError('The native EXR header metadata is invalid or too large.')
        attributes[name]=(kind,member.read(length))
    def attribute(name,kind,size=None):
        value=attributes.get(name)
        if value is None or value[0]!=kind or size is not None and len(value[1])!=size:
            raise ValueError('The native EXR is missing required colour or raster metadata.')
        return value[1]
    if attribute(b'compression',b'compression',1)[0]>9 or attribute(b'lineOrder',b'lineOrder',1)[0]>2:
        raise ValueError('The native EXR compression or scanline metadata is invalid.')
    aspect=struct.unpack('<f',attribute(b'pixelAspectRatio',b'float',4))[0]
    if not np.isfinite(aspect) or aspect<=0:raise ValueError('The native EXR pixel aspect metadata is invalid.')
    window=struct.unpack('<4i',attribute(b'dataWindow',b'box2i',16))
    display=struct.unpack('<4i',attribute(b'displayWindow',b'box2i',16))
    width,height=window[2]-window[0]+1,window[3]-window[1]+1
    if (window[:2]!=(0,0) or display!=window or not 1<=width<=16384 or not 1<=height<=16384
            or width*height>MAX_PIXELS):raise ValueError('The native HDR raster exceeds display bounds.')
    chroma=struct.unpack('<8f',attribute(b'chromaticities',b'chromaticities',32))
    if not all(abs(float(a)-b)<.002 for a,b in zip(chroma,_AP1)):
        raise ValueError('The native HDR archive must contain ACEScg/AP1 pixels.')
    tag=attributes.get(b'oiio:ColorSpace') or attributes.get(b'colorSpace')
    if tag:
        if tag[0]!=b'string':raise ValueError('The native HDR colour-space tag is invalid.')
        try:label=tag[1].decode('utf-8').strip().lower()
        except UnicodeDecodeError:raise ValueError('The native HDR colour-space tag is invalid.') from None
        if 'acescct' in label or label not in ('','linear','scene_linear','scene-linear','unknown','lin_ap1_scene') and 'acescg' not in label:
            raise ValueError('The native HDR archive must contain scene-linear ACEScg pixels.')
    channels=attribute(b'channels',b'chlist');position=0;formats={}
    while position<len(channels) and channels[position]!=0:
        end=channels.find(b'\0',position)
        if end<0 or end-position>255 or end+17>len(channels):raise ValueError('The native EXR channel list is invalid.')
        name=channels[position:end];pixel,linear,reserved,x,y=struct.unpack('<iB3sii',channels[end+1:end+17]);position=end+17
        if name in formats or name not in (b'R',b'G',b'B',b'A') or pixel not in (1,2) or linear not in (0,1) or reserved!=b'\0\0\0' or (x,y)!=(1,1):
            raise ValueError('The native EXR channel metadata is invalid.')
        formats[name]=pixel
    names=set(formats)
    if position!=len(channels)-1 or names not in ({b'R',b'G',b'B'},{b'R',b'G',b'B',b'A'}) or len(set(formats.values()))!=1:
        raise ValueError('The native HDR archive requires one RGB or RGBA HALF/FLOAT layer.')
    return {'width':width,'height':height,'exr_storage':'half' if next(iter(formats.values()))==1 else 'float32',
            'colour_space':'acescg','alpha_association':'straight','has_alpha':b'A' in names}


def _sha(value):
    return isinstance(value,str) and re.fullmatch(r'[a-f0-9]{64}',value) is not None


def _proof(raw):
    """Validate the optional exporter proof without trusting its declarations."""
    try:
        proof=json.loads(raw.decode('utf-8'),object_pairs_hook=float_io._json_pairs,
            parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite HDR proof'))
        )
    except (UnicodeDecodeError,json.JSONDecodeError,ValueError) as error:
        raise ValueError('The native HDR proof is invalid.') from error
    required={'schemaVersion','kind','colour','alphaAssociation','width','height','frameCount','frameRate','alphaSource','frames'}
    if (not isinstance(proof,dict) or not required<=set(proof) or set(proof)-required-{'sourceStart'}
            or type(proof['schemaVersion']) is not int or proof['schemaVersion']!=1
            or proof['kind']!='rgba_hdr'
            or proof['colour']!={'encoding':'acescg','sceneLinear':True}
            or proof['alphaAssociation']!='straight'
            or any(type(proof[key]) is not int or proof[key]<1 for key in ('width','height','frameCount'))
            or not isinstance(proof['frameRate'],dict)):
        raise ValueError('The native HDR proof metadata is invalid.')
    rate=float_io._rational(proof['frameRate'],'HDR proof frame rate',positive=True)
    if not 1<=rate<=240:raise ValueError('The native HDR proof frame rate is invalid.')
    if 'sourceStart' in proof:float_io._rational(proof['sourceStart'],'HDR proof source start',signed=True)
    origin=proof['alphaSource']
    if (not isinstance(origin,dict) or set(origin)!={'kind','sha256'}
            or origin['kind'] not in {'alpha_float32','float_manifest','rgba_image'} or not _sha(origin['sha256'])):
        raise ValueError('The native HDR alpha provenance is invalid.')
    frames=proof['frames']
    if not isinstance(frames,list) or len(frames)!=proof['frameCount']:
        raise ValueError('The native HDR proof count differs.')
    for name,frame in zip((f'frame_{index:05d}.exr' for index in range(proof['frameCount'])),frames):
        if (not isinstance(frame,dict) or set(frame)!={'filename','sha256','alphaSha256'}
                or frame['filename']!=name or not _sha(frame['sha256']) or not _sha(frame['alphaSha256'])):
            raise ValueError('The native HDR frame proof is invalid.')
    return proof


def _build_index(source,size):
    count,directory=_directory(source,size)
    with zipfile.ZipFile(source) as archive:
        infos=archive.infolist()
        if len(infos)!=count:raise ValueError('The HDR archive directory count is inconsistent.')
        archive_zip.validate_infos(source,infos,archive_zip.bounded_directory(source,size,max_entries=MAX_FRAMES+1,max_directory=MAX_DIRECTORY))
        proof_infos=[info for info in infos if info.filename==PROOF_NAME]
        if len(proof_infos)>1:raise ValueError('The HDR archive contains duplicate delivery proofs.')
        proof_info=proof_infos[0] if proof_infos else None
        frame_infos=[info for info in infos if info.filename!=PROOF_NAME]
        frame_count=len(frame_infos)
        if not 1<=frame_count<=MAX_FRAMES:raise ValueError('The HDR archive has an invalid number of frames.')
        expected=[f'frame_{index:05d}.exr' for index in range(frame_count)]
        if sorted(info.filename for info in frame_infos)!=expected:raise ValueError('The HDR archive has missing, duplicate or unexpected frames.')
        ordered=sorted(infos,key=lambda value:value.header_offset);ends={info.header_offset:(ordered[index+1].header_offset if index+1<len(ordered) else directory) for index,info in enumerate(ordered)}
        if len(ends)!=count or ordered[0].header_offset!=0:raise ValueError('The HDR archive member locations are invalid.')
        entries=[];total=0
        for info in sorted(frame_infos,key=lambda value:value.filename):
            kind=(info.external_attr>>16)&0o170000
            if (not _FRAME.fullmatch(info.filename) or info.orig_filename!=info.filename or info.is_dir()
                    or kind not in (0,stat.S_IFREG) or info.flag_bits not in (0,0x800) or info.comment
                    or info.compress_type!=zipfile.ZIP_STORED or info.compress_size!=info.file_size
                    or not 0<info.file_size<=MAX_FRAME_BYTES or not 0<=info.header_offset<directory):
                raise ValueError('The HDR archive contains unsafe or compressed members.')
            total+=info.file_size
            if total>float_io.MAX_TRANSFER_BYTES:raise ValueError('The HDR archive exceeds its aggregate byte bound.')
            entries.append({'name':info.filename,'offset':info.header_offset,'end':ends[info.header_offset], 'size':info.file_size,'crc':info.CRC,'flags':info.flag_bits})
        proof=None
        if proof_info is not None:
            kind=(proof_info.external_attr>>16)&0o170000
            if (proof_info.orig_filename!=PROOF_NAME or proof_info.is_dir() or kind not in (0,stat.S_IFREG)
                    or proof_info.flag_bits not in (0,0x800) or proof_info.comment
                    or proof_info.compress_type!=zipfile.ZIP_STORED or proof_info.compress_size!=proof_info.file_size
                    or not 0<proof_info.file_size<=4*1024*1024):
                raise ValueError('The HDR delivery proof is unsafe or oversized.')
            raw=archive.read(proof_info)
            if len(raw)!=proof_info.file_size:raise ValueError('The HDR delivery proof is truncated.')
            proof=_proof(raw)
            if (proof['frameCount']!=frame_count or proof['width']!=_header(source,entries[0])['width']
                    or proof['height']!=_header(source,entries[0])['height']):
                raise ValueError('The HDR delivery proof differs from its frames.')
    metadata=_header(source,entries[0]);limit=metadata['width']*metadata['height']*32+8*1024*1024
    if any(entry['size']>limit for entry in entries):raise ValueError('The HDR archive member size exceeds the intended raster.')
    if proof is not None and (not metadata['has_alpha'] or metadata['exr_storage']!='float32'):
        raise ValueError('The RGBA HDR proof requires FLOAT RGBA EXR frames.')
    metadata.update(kind='hdr_archive',frame_count=frame_count,frame_rate=proof['frameRate'] if proof else None,
        source_bit_depth=16 if metadata['exr_storage']=='half' else 32)
    return {'entries':entries,'metadata':metadata,'proof':proof}


def _index(path,source,identity):
    key=(str(path),identity)
    with _index_lock:
        value=_indexes.get(key)
        if value is not None:_indexes.move_to_end(key);return value
    value=_build_index(source,identity[2])
    with _index_lock:
        _indexes[key]=value
        while len(_indexes)>8 or sum(len(item['entries']) for item in _indexes.values())>20000:_indexes.popitem(last=False)
    return value


def _metadata(index,expected):
    result=dict(index['metadata'])
    if expected is None:return result
    if not isinstance(expected,dict):raise ValueError('Native HDR delivery metadata is invalid.')
    for field in ('width','height','frame_count','exr_storage'):
        if field in expected and (type(expected[field]) is not type(result[field]) or expected[field]!=result[field]):
            raise ValueError('The HDR archive differs from its native delivery metadata.')
    rate=expected.get('frame_rate')
    if rate is not None:
        if (not isinstance(rate,dict) or set(rate)!={'numerator','denominator'}
                or any(type(rate.get(key)) is not int or not 1<=rate[key]<=1000000000 for key in rate)
                or not 1<=rate['numerator']/rate['denominator']<=240):raise ValueError('Native HDR delivery cadence is invalid.')
        result['frame_rate']=dict(rate)
    return result


def describe_archive(path,expected=None):
    path=Path(path).absolute()
    try:
        with locked_archive(path) as (source,identity):return _metadata(_index(path,source,identity),expected)
    except (OSError,zipfile.BadZipFile,zipfile.LargeZipFile,struct.error,OverflowError) as error:
        raise ValueError('The native HDR EXR archive is invalid or changed.') from error


def _copy_member(source,entry,destination,expected_sha=None):
    _member_start(source,entry);left=entry['size'];crc=0
    digest=hashlib.sha256()
    with destination.open('xb') as output:
        while left:
            block=_read(source,min(1024*1024,left));left-=len(block);crc=zlib.crc32(block,crc);digest.update(block);output.write(block)
    if crc&0xffffffff!=entry['crc']:raise ValueError('The selected HDR frame failed its ZIP checksum.')
    actual=digest.hexdigest()
    if expected_sha is not None and actual!=expected_sha:raise ValueError('The selected HDR frame differs from its delivery proof.')
    return actual


def _decode_frame(path,metadata):
    import OpenImageIO as oiio
    from ..paintout.paintout import _exr_auto_space
    config=oiio.ImageSpec();config.attribute('oiio:UnassociatedAlpha',1)
    reader=oiio.ImageInput.open(str(path),config)
    if reader is None:raise ValueError('The selected HDR frame is unreadable.')
    try:
        spec=reader.spec();storage=oiio.HALF if metadata['exr_storage']=='half' else oiio.FLOAT
        channels=4 if metadata['has_alpha'] else 3
        names={'R','G','B','A'} if metadata['has_alpha'] else {'R','G','B'}
        if (spec.width!=metadata['width'] or spec.height!=metadata['height'] or spec.depth!=1 or spec.deep
                or spec.nchannels!=channels or set(spec.channelnames)!=names or spec.format!=storage
                or any(value!=storage for value in spec.channelformats)):
            raise ValueError('The selected HDR frame differs from its intended raster or precision.')
        if metadata['has_alpha'] and (storage!=oiio.FLOAT
                or spec.get_string_attribute('comfylink:alphaAssociation')!='straight'
                or spec.get_string_attribute('comfylink:colour')!='{"encoding":"acescg","sceneLinear":true}'):
            raise ValueError('The selected RGBA frame is not an unmanaged FLOAT straight-alpha ACEScg master.')
        chroma=spec.getattribute('chromaticities')
        if chroma is None or len(chroma)!=8 or not all(abs(float(a)-b)<.002 for a,b in zip(chroma,_AP1)) or _exr_auto_space(str(path))!='acescg':
            raise ValueError('The selected HDR frame is not scene-linear ACEScg/AP1.')
        data=reader.read_image(format=oiio.FLOAT)
        if data is None or data.shape!=(metadata['height'],metadata['width'],channels) or not np.isfinite(data).all():raise ValueError('The selected HDR frame has invalid pixels.')
        rgba=np.ones((metadata['height'],metadata['width'],4),dtype=np.float32)
        rgba[...,:3]=data[...,[list(spec.channelnames).index(name) for name in 'RGB']]
        if metadata['has_alpha']:
            rgba[...,3]=data[...,list(spec.channelnames).index('A')]
            if np.any(rgba[...,3]<0) or np.any(rgba[...,3]>1):raise ValueError('The selected HDR frame has invalid alpha.')
        return rgba
    finally:reader.close()


def read_archive_frame(path,frame,expected=None):
    if type(frame) is not int or not 0<=frame<MAX_FRAMES:raise ValueError('Choose a valid native HDR frame.')
    path=Path(path).absolute()
    try:
        with locked_archive(path) as (source,identity):
            index=_index(path,source,identity);metadata=_metadata(index,expected)
            if frame>=metadata['frame_count']:raise ValueError('The preview frame is outside the HDR archive.')
            entry=index['entries'][frame]
            if _header(source,entry)!={key:metadata[key] for key in ('width','height','exr_storage','colour_space','alpha_association','has_alpha')}:
                raise ValueError('The selected HDR frame has inconsistent metadata.')
            proof_frame=index['proof']['frames'][frame] if index['proof'] else None
            parent=Path(tempfile.gettempdir())/'zura-display-original';parent.mkdir(exist_ok=True)
            with float_io._locked_parents(parent):
                temporary=tempfile.TemporaryDirectory(prefix='hdr-frame-',dir=parent)
                directory=Path(temporary.name).resolve()
                try:
                    if directory.parent!=parent.resolve() or not directory.name.startswith('hdr-frame-'):raise ValueError('The private HDR preview directory is invalid.')
                    with float_io._locked_parents(directory):
                        selected=directory/'frame.exr';_copy_member(source,entry,selected,
                            proof_frame['sha256'] if proof_frame else None)
                        with locked_archive(selected):
                            rgba=_decode_frame(selected,metadata)
                            if proof_frame and alpha_hash(rgba[...,3])!=proof_frame['alphaSha256']:
                                raise ValueError('The selected HDR frame alpha differs from its delivery proof.')
                            return rgba,metadata
                finally:
                    float_io._safe_stat(directory,True)
                    if directory.resolve()!=directory or directory.parent!=parent.resolve() or not directory.name.startswith('hdr-frame-'):raise ValueError('The private HDR preview cleanup target changed.')
                    temporary.cleanup()
    except (OSError,zipfile.BadZipFile,zipfile.LargeZipFile,struct.error,OverflowError) as error:
        raise ValueError('The native HDR EXR archive is invalid or changed.') from error
