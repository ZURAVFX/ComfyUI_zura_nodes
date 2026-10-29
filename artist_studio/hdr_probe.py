"""Read video colour tags before selecting an HDR or SDR processing route."""
from __future__ import annotations


def classify_transfer(value):
    """FFmpeg transfer-characteristic enum; unknown must stay unknown."""
    if value == 16:return 'hdr_pq'
    if value == 18:return 'hdr_hlg'
    if value in (1, 4, 5, 6, 7, 11, 12, 13, 14, 15):return 'sdr'
    return 'unknown'


def inspect_video(path):
    """Return source metadata without decoding or inventing missing tags.

    This detects HDR from transfer metadata only; it doesn't convert primaries,
    transfer or range. Callers must prepare true sRGB frames for the SDR-to-HDR
    guide and reject unknown colour or ask for an explicit source override.
    """
    import av
    with av.open(str(path)) as source:
        if not source.streams.video:raise ValueError('The file has no video stream.')
        stream=source.streams.video[0]
        codec=stream.codec_context
        transfer=int(codec.color_trc or 2)
        primaries=int(codec.color_primaries or 2)
        matrix=int(codec.colorspace or 2)
        return {'transfer':transfer,'primaries':primaries,'matrix':matrix,
                'colour_range':int(codec.color_range or 0),
                'classification':classify_transfer(transfer),
                'width':stream.width,'height':stream.height,
                'fps':float(stream.average_rate) if stream.average_rate else None}
