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


def frame_rgba(frame, *, max_pixels=16*1024*1024):
    """Read decoded frame metadata, never the codec context's guessed matrix."""
    count = FORMATS.get(frame.format.name)
    width, height = frame.width, frame.height
    if (count is None or type(width) is not int or type(height) is not int
            or min(width, height) < 1 or width*height > max_pixels or len(frame.planes) != count):
        raise ValueError('Choose a bounded twelve-bit ProRes 4:4:4 frame.')
    try:matrix, code_range = int(frame.colorspace), int(frame.color_range)
    except (TypeError,ValueError):raise ValueError('The ProRes frame matrix and range are missing.') from None
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
                yield frame_rgba(frame, max_pixels=max_pixels)
                selected += 1
                if selected == count:break
            if selected != count:
                raise ValueError('The original ProRes ended before its selected frame interval.')
        finally:
            clip.close()
    return frames()
