"""Strict decode contract for the Studio 10-bit limited-range sRGB master.

Output is FLOAT32 RGB with 16-bit swscale precision, never an 8-bit grid.
The caller retains and hashes the original and verifies framing independently.
"""
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
import av
import numpy as np


def _metadata(value, inherited=None):
    fmt = getattr(value, 'format', None)
    if fmt is None or fmt.name != 'yuv420p10le' or len(fmt.components) != 3 or any(c.bits != 10 or c.is_alpha for c in fmt.components):
        raise ValueError('Video is not supported 10-bit YUV420')
    expected = (13, 1, 1, 1)
    values = tuple(getattr(value, k, None) for k in ('color_trc', 'color_primaries', 'colorspace', 'color_range'))
    normal = tuple((inherited[i] if inherited and v in (None, 2 if i < 3 else 0) else v) for i,v in enumerate(values))
    if normal != expected: raise ValueError('Video is not declared limited-range sRGB / BT.709 SDR')
    sides = getattr(value, 'side_data', ())
    for entry in sides:
        side = entry
        if getattr(side, 'type', None) is None:
            try: side = sides[entry]
            except (KeyError, IndexError, TypeError, AttributeError): raise ValueError('Video side metadata is unavailable') from None
        kind = getattr(getattr(side, 'type', None), 'name', '')
        if kind != 'SEI_UNREGISTERED' or not bytes(side)[16:].startswith(b'x264 - core '):
            raise ValueError('Unsupported video side metadata')
    return expected


def _container(path):
    forbidden=(b'colrprof',b'colrrICC',b'ICC_PROFILE',b'http://ns.adobe.com/xap/1.0/')
    hdr=(b'mdcv',b'clli',b'dvcC',b'dvvC',b'dvwC');overlap=max(map(len,forbidden))+4;previous=b''
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):
            data=previous+chunk
            if any(marker in data for marker in forbidden): raise ValueError('Unsupported embedded profile')
            for marker in hdr:
                offset=data.find(marker)
                while offset >= 0:
                    if offset >= 4 and 8 <= int.from_bytes(data[offset-4:offset], 'big') <= 4096: raise ValueError('Unsupported HDR metadata')
                    offset=data.find(marker,offset+1)
            previous=data[-overlap:]


@contextmanager
def decode_sdr10(path):
    path=Path(path)
    if path.suffix.lower() not in ('.mp4','.mov'): raise ValueError('Unsupported 10-bit video container')
    _container(path)
    with av.open(str(path)) as media:
        if 'mov' not in media.format.name or len(media.streams.video)!=1 or any(s.type not in {'video','audio'} for s in media.streams):
            raise ValueError('Unsupported video streams')
        # Only routine title/encoder/brand metadata; colour or embedded profiles are not accepted.
        for mapping in (media.metadata,media.streams.video[0].metadata):
            if any(any(term in str(k).lower() for term in ('icc','color','colour','hdr','mastering','display','profile')) for k in mapping):
                raise ValueError('Unsupported video colour metadata')
        stream=media.streams.video[0];context=stream.codec_context;_metadata(context)
        if getattr(stream,'side_data',()): raise ValueError('Unsupported video stream side data')
        rate=stream.average_rate
        if not isinstance(rate,Fraction) or rate<=0: raise ValueError('Unsupported video frame rate')
        width,height=context.width,context.height
        if not 1<=width<=16384 or not 1<=height<=16384 or width*height>16*1024*1024: raise ValueError('Video raster exceeds bounds')
        def frames():
            first = None
            for index, frame in enumerate(media.decode(video=0)):
                _metadata(context);_metadata(frame,(13,1,1,1))
                pts, time_base = frame.pts, frame.time_base
                if type(pts) is not int or not isinstance(time_base, Fraction) or time_base <= 0:
                    raise ValueError('Video frame timestamp is missing or invalid')
                instant = pts * time_base
                if first is None: first = instant
                if instant != first + Fraction(index, 1) / rate:
                    raise ValueError('Video frame timestamps are not the declared constant cadence')
                if (frame.width,frame.height)!=(width,height): raise ValueError('Video frame raster changed')
                rgb=frame.reformat(format='rgb48le',src_colorspace='ITU709',dst_colorspace='ITU709',
                                   src_color_range='MPEG',dst_color_range='JPEG').to_ndarray()
                if rgb.shape!=(height,width,3) or rgb.dtype!=np.uint16: raise ValueError('Unexpected video decode')
                rgba=np.empty((height,width,4),dtype=np.float32)
                rgba[:,:,:3]=rgb.astype(np.float32)/np.float32(65535);rgba[:,:,3]=1
                yield rgba
        yield rate,frames()
