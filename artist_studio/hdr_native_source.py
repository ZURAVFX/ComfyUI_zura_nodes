"""Experimental, bounded native HDR input for the LTX 2.5 HDR workflow.

This module prepares images for an eventual native HDR generation graph. It
does not implement the official TiledFusion sampler, and is deliberately not
registered or exposed in Studio until the full path is validated.
"""
from __future__ import annotations

import math
import torch

from .hdr_source import MAX_FRAMES, MAX_PIXEL_FRAMES

HDR_VIDEO_SPACES = ('hlg_rec2020', 'pq_rec2020')
HDR_SEQUENCE_SPACES = ('acescg', 'acescct', 'linear_rec709')


def load_native_hdr_frames(path, start_frame, frame_count, colour_space='auto', sequence_fps=24):
    """Read HLG/PQ video or linear/log EXR into LTX's ACEScct working space.

    Input remains bounded, reads the exact range and preserves scene-linear
    values above 1 before applying the model's bounded ACEScct encoding.
    An untagged source needs an explicit correct colour selection; JPEG, PNG,
    SDR video and ambiguous automatic interpretation are rejected here.
    """
    from pathlib import Path
    from ..paintout.paintout import describe, selected_space, frames, working

    if type(start_frame) is not int or start_frame < 0:
        raise ValueError('Choose a non-negative first frame.')
    if type(frame_count) is not int or not 1 <= frame_count <= MAX_FRAMES:
        raise ValueError(f'Choose between 1 and {MAX_FRAMES} frames.')
    if colour_space not in ('auto', *HDR_VIDEO_SPACES, *HDR_SEQUENCE_SPACES):
        raise ValueError('Choose HLG, PQ or an appropriate EXR colour space.')
    info = describe(path)
    if start_frame + frame_count > info['count']:
        raise ValueError('The selected frame range extends past the source.')
    if info['width'] * info['height'] * frame_count > MAX_PIXEL_FRAMES:
        raise ValueError('The selection is too large. Choose fewer frames or smaller footage.')
    if info['kind'] == 'sequence' and any(Path(name).suffix.lower() != '.exr' for name in info['files'][start_frame:start_frame + frame_count]):
        raise ValueError('Native HDR image input requires EXR frames.')
    if info['kind'] == 'video' and info.get('transfer') in ('bt709', 'iec61966-2-1'):
        raise ValueError('This video is tagged SDR. Use the SDR-to-HDR workflow.')
    selected = selected_space(info, colour_space)
    supported = HDR_VIDEO_SPACES if info['kind'] == 'video' else HDR_SEQUENCE_SPACES
    if selected not in supported:
        raise ValueError('Choose a supported HDR video or EXR colour space.')
    fps = info.get('fps', sequence_fps)
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps) or not 1 <= fps <= 120:
        raise ValueError('Choose a valid frame rate between 1 and 120 fps.')
    result = []
    for frame in frames(info, start_frame, frame_count):
        if frame.shape != (info['height'], info['width'], 3):
            raise ValueError('The source dimensions change within the selection.')
        rgb = torch.from_numpy(frame.copy()).float()[None]
        if not torch.isfinite(rgb).all():
            raise ValueError('The source contains non-finite pixels.')
        converted = working(rgb, selected, 'HDR (ACEScct)')
        if not torch.isfinite(converted).all():
            raise ValueError('The HDR colour transform produced non-finite pixels.')
        result.append(converted)
    if len(result) != frame_count:
        raise ValueError('The source ended before the selected frame range.')
    return torch.cat(result), float(fps)
