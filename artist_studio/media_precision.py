"""Describe original storage and decoder precision without claiming coded quality.

A ProRes decoder's twelve-bit pixel format is not evidence that its source was
encoded at twelve bits. Original bytes and their colour identity stay separate
from any eight-bit inference view.
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path


def video_precision(stream, frame):
    """Actual decoded component width; never an inferred effective source depth."""
    bits = sorted({component.bits for component in frame.format.components})
    raw = getattr(stream.codec_context, 'bits_per_raw_sample', None)
    declared = raw if type(raw) is int and 1 <= raw <= 64 else None
    return {'storage': 'video', 'decodedBitDepth': max(bits),
            'decodedComponentBits': bits, 'declaredBitDepth': declared,
            'effectiveBitDepth': None, 'pixelFormat': frame.format.name,
            'codec': stream.codec_context.name,
            'hasAlpha': any(component.is_alpha for component in frame.format.components)}


def image_precision(path):
    import OpenImageIO as oiio
    reader = oiio.ImageInput.open(str(path))
    if reader is None:
        raise ValueError('The original image header could not be read.')
    try:
        spec = reader.spec()
        if spec.deep or spec.depth != 1 or spec.width < 1 or spec.height < 1:
            raise ValueError('Choose a flat image with a valid raster.')
        formats = list(spec.channelformats) or [spec.format] * spec.nchannels
        widths = {'half':16,'float':32,'uint8':8,'uint16':16,'uint':32,'uint32':32}
        bits = [widths.get(str(value)) for value in formats]
        if any(value is None for value in bits):
            raise ValueError('This original image uses an unsupported channel storage type.')
        return {'storage': 'image', 'storageBitDepth': max(bits),
                'channelStorage': [str(value) for value in formats],
                'sampleType': 'float' if any(value in (oiio.HALF, oiio.FLOAT) for value in formats) else 'integer',
                'effectiveBitDepth': None, 'width': spec.width, 'height': spec.height,
                'hasAlpha': any(name.lower() in ('a', 'alpha') for name in spec.channelnames)}
    finally:
        reader.close()


def inspect_original(resolved,cancel=None):
    """Inspect an already-authorised original. This function never opens user paths."""
    def check():
        if cancel is not None and cancel.is_set():raise ValueError('Media inspection was cancelled. The original is retained.')
    check();metadata = resolved['metadata']
    if metadata['kind'] == 'video':
        import av
        info = metadata['info']
        with av.open(str(resolved['path'])) as media:
            stream = media.streams.video[0]
            frame = next(media.decode(video=0), None)
            check()
            if frame is None:
                raise ValueError('The original video contains no readable frames.')
            result = video_precision(stream, frame)
        result.update({key: info.get(key) for key in ('transfer', 'primaries', 'matrix', 'range')})
        rate = Fraction(info['fps_rational'])
        result['frameRate'] = {'numerator': rate.numerator, 'denominator': rate.denominator}
        return result
    if metadata['kind'] == 'float_sequence':
        manifest = metadata['manifest']
        return {'storage': 'float_sequence', 'storageBitDepth': manifest['sourceBitDepth'],
                'sampleType': manifest['sampleType'], 'effectiveBitDepth': None,
                'hasAlpha': True}
    files = resolved.get('files') or [resolved['path']]
    descriptions=[]
    for path in files:
        check();descriptions.append(image_precision(path))
    check()
    first = descriptions[0]
    if any(description != first for description in descriptions[1:]):
        raise ValueError('The sequence changes raster, alpha or channel precision between frames.')
    return first
