"""Decode ProRes 4:4:4 twelve-bit planes without an integer RGB conversion.

YCbCr coefficients and limited-range code values follow ITU-R BT.601-7,
BT.709-6 and BT.2020-2 (non-constant luminance). This only recovers encoded
RGB samples: gamma, primaries and working-space interpretation remain the
caller's declared source metadata. No viewing transform or RGB clipping occurs.
"""
from __future__ import annotations

import numpy as np

FORMATS = {'yuv444p12le': 3, 'yuva444p12le': 4}
# AVColorSpace values: BT709=1, BT470BG=5, SMPTE170M=6, BT2020_NCL=9.
COEFFICIENTS = {1: (.2126, .0722), 5: (.299, .114), 6: (.299, .114), 9: (.2627, .0593)}
_LOCAL = {'protocol_whitelist': 'file,pipe', 'format_whitelist': 'mov,matroska,webm,avi,mxf'}


_MAX_MOOV = 16*1024*1024
_MAX_BOXES = 4096
_PRORES_TAGS = {b'ap4h', b'ap4x', b'apch', b'apcn', b'apcs', b'apco'}


def _boxes(data):
    """Walk one bounded in-memory MOV container; never search media payloads."""
    import struct
    offset = 0
    for _ in range(_MAX_BOXES):
        if offset == len(data):return
        if len(data)-offset < 8:raise ValueError('The MOV colour metadata has an incomplete box.')
        size, kind = struct.unpack_from('>I4s', data, offset);header = 8
        if size == 1:
            if len(data)-offset < 16:raise ValueError('The MOV colour metadata has an incomplete box.')
            size = struct.unpack_from('>Q', data, offset+8)[0];header = 16
        elif size == 0:size = len(data)-offset
        if size < header or offset+size > len(data):raise ValueError('The MOV colour metadata box size is invalid.')
        yield kind, data[offset+header:offset+size]
        offset += size
    raise ValueError('The MOV colour metadata has too many boxes.')


def _single(data, kind):
    matches = [body for name, body in _boxes(data) if name == kind]
    if len(matches) > 1:raise ValueError('The MOV colour metadata is ambiguous.')
    return matches[0] if matches else None


def _video_colour(moov):
    import struct
    for kind, track in _boxes(moov):
        if kind != b'trak':continue
        media = _single(track, b'mdia')
        if media is None:continue
        handler = _single(media, b'hdlr')
        if handler is None or len(handler) < 12 or handler[8:12] != b'vide':continue
        # AV video stream zero is the first video track, not the first colr box.
        info = _single(media, b'minf')
        table = _single(info, b'stbl') if info is not None else None
        sample = _single(table, b'stsd') if table is not None else None
        if sample is None:return None
        if len(sample) < 8:raise ValueError('The MOV sample descriptions are incomplete.')
        count = struct.unpack_from('>I', sample, 4)[0]
        if not 1 <= count <= 64:raise ValueError('The MOV has an unsupported sample description count.')
        entries = list(_boxes(sample[8:]))
        if len(entries) != count:raise ValueError('The MOV sample description count is invalid.')
        declarations = []
        for codec, body in entries:
            if codec not in _PRORES_TAGS:return None
            if len(body) < 78:raise ValueError('The ProRes sample description is incomplete.')
            colour = _single(body[78:], b'colr')
            # nclc has no full/limited-range flag and is never used to infer one.
            if colour is None or colour[:4] != b'nclx':return None
            if len(colour) < 11 or colour[10] & 0x7f:raise ValueError('The MOV nclx range declaration is invalid.')
            matrix = struct.unpack_from('>H', colour, 8)[0]
            code_range = 2 if colour[10] & 0x80 else 1
            if matrix not in COEFFICIENTS:raise ValueError('The MOV nclx matrix is unsupported for ProRes RGB recovery.')
            declarations.append((matrix, code_range))
        if len(set(declarations)) != 1:raise ValueError('The ProRes MOV sample descriptions have conflicting colour declarations.')
        return declarations[0]
    return None


def mov_colour_declaration(path):
    """Read explicit video-zero ProRes nclx metadata, with bounded local I/O.

    Non-MOV containers have no declaration here. Media data is skipped by seek;
    only one moov box, capped at 16 MiB, is read into memory.
    """
    import struct
    with open(path, 'rb') as stream:
        stream.seek(0, 2);length = stream.tell();stream.seek(0)
        offset = 0;moov = None
        for _ in range(_MAX_BOXES):
            if offset == length:return _video_colour(moov) if moov is not None else None
            if length-offset < 8:raise ValueError('The MOV top-level box is incomplete.')
            stream.seek(offset);head = stream.read(8)
            if len(head) != 8:raise ValueError('The MOV top-level box is incomplete.')
            size, kind = struct.unpack('>I4s', head);header = 8
            if offset == 0 and kind not in {b'ftyp', b'moov', b'mdat', b'wide', b'free', b'skip'}:return None
            if size == 1:
                extended = stream.read(8)
                if len(extended) != 8:raise ValueError('The MOV top-level box is incomplete.')
                size = struct.unpack('>Q', extended)[0];header = 16
            elif size == 0:size = length-offset
            if size < header or offset+size > length:raise ValueError('The MOV top-level box size is invalid.')
            if kind == b'moov':
                if moov is not None:raise ValueError('The MOV has multiple movie metadata boxes.')
                if size > _MAX_MOOV:raise ValueError('The MOV movie metadata exceeds the 16 MiB limit.')
                moov = stream.read(size-header)
                if len(moov) != size-header:raise ValueError('The MOV movie metadata is incomplete.')
            offset += size
        raise ValueError('The MOV has too many top-level boxes.')


def frame_rgba(frame, *, declared=None, max_pixels=16*1024*1024):
    """Use actual frame fields or explicit MOV nclx, never codec-context guesses."""
    count = FORMATS.get(frame.format.name)
    width, height = frame.width, frame.height
    if (count is None or type(width) is not int or type(height) is not int
            or min(width, height) < 1 or width*height > max_pixels or len(frame.planes) != count):
        raise ValueError('Choose a bounded twelve-bit ProRes 4:4:4 frame.')
    try:
        matrix = int(frame.colorspace) if getattr(frame, 'colorspace', None) is not None else None
        code_range = int(frame.color_range) if getattr(frame, 'color_range', None) is not None else None
    except (TypeError, ValueError):raise ValueError('The ProRes frame matrix and range are missing.') from None
    if declared is not None:
        if (not isinstance(declared, tuple) or len(declared) != 2
                or any(type(value) is not int for value in declared)
                or declared[0] not in COEFFICIENTS or declared[1] not in {1, 2}):
            raise ValueError('The explicit ProRes MOV matrix and range declaration is invalid.')
        if matrix not in {None, 2} and matrix != declared[0]:
            raise ValueError('The ProRes frame matrix conflicts with its explicit MOV declaration.')
        if code_range not in {None, 0} and code_range != declared[1]:
            raise ValueError('The ProRes frame range conflicts with its explicit MOV declaration.')
        if matrix in {None, 2}:matrix = declared[0]
        if code_range in {None, 0}:code_range = declared[1]
    if matrix not in COEFFICIENTS or code_range not in {1, 2}:
        raise ValueError('This ProRes frame needs a declared BT.601, BT.709 or non-constant BT.2020 matrix and limited or full range.')
    values=[]
    for plane in frame.planes:
        stride = plane.line_size
        if (plane.width != width or plane.height != height or type(stride) is not int
                or stride < width*2 or stride % 2 or stride*height > plane.buffer_size):
            raise ValueError('The ProRes plane stride or raster is invalid.')
        buffer = memoryview(plane)
        if buffer.nbytes < stride*height:
            raise ValueError('The ProRes plane buffer is incomplete.')
        samples = np.ndarray((height, width), dtype='<u2', buffer=buffer, strides=(stride, 2))
        if np.any(samples > 4095):
            raise ValueError('The decoded ProRes plane contains invalid twelve-bit samples.')
        values.append(samples.astype(np.float64))
    y, cb, cr = values[:3]
    if code_range == 1:
        y = (y-256)/3504
        cb, cr = (cb-2048)/3584, (cr-2048)/3584
    else:
        y = y/4095
        cb, cr = (cb-2048)/4095, (cr-2048)/4095
    kr, kb = COEFFICIENTS[matrix];kg = 1-kr-kb
    red = y+2*(1-kr)*cr
    blue = y+2*(1-kb)*cb
    green = y-2*kb*(1-kb)/kg*cb-2*kr*(1-kr)/kg*cr
    rgba = np.empty((height, width, 4), dtype=np.float32)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = red, green, blue
    rgba[..., 3] = values[3]/4095 if count == 4 else 1
    return rgba


def selected_frames(info, start, count, check_cancelled, *, max_pixels=16*1024*1024):
    """Return an owned iterator for ProRes 444/12, or None for older paths.

    Select only video stream zero. Normal MOV timecode/XMP data tracks do not
    change pixel decoding. The caller verifies the rational frame clock first.
    """
    import av
    check_cancelled()
    clip = av.open(info['path'], options=_LOCAL)
    try:
        if not clip.streams.video or clip.streams.video[0].codec_context.name != 'prores':
            clip.close();return None
        decoder = iter(clip.decode(video=0))
        first = next(decoder, None)
        if first is None:
            raise ValueError('The original ProRes contains no readable frames.')
        if first.format.name not in FORMATS:
            clip.close();return None
        declared = mov_colour_declaration(info['path'])
    except BaseException:
        clip.close();raise

    def frames():
        selected = 0
        try:
            def decoded():
                yield first
                yield from decoder
            for index, frame in enumerate(decoded()):
                check_cancelled()
                if index < start:continue
                if (frame.width, frame.height) != (info['width'], info['height']):
                    raise ValueError('The ProRes raster changed during original-frame decoding.')
                yield frame_rgba(frame, declared=declared, max_pixels=max_pixels)
                selected += 1
                if selected == count:break
            if selected != count:
                raise ValueError('The original ProRes ended before its selected frame interval.')
        finally:
            clip.close()
    return frames()
