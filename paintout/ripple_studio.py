"""Frame-preserving input adapter for the native WepeNerd H3 Ripple node.

Only prepares metadata and held-tail source frames. Model loading, VAE
encoding, conditioning and sampling remain in the publisher's native nodes.
"""
from __future__ import annotations

import math

import torch


def h3_working_frames(count):
    """H3's 17n+5 grid, rounded up so no requested source frame is lost."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError('A Ripple clip needs at least one source frame.')
    return 5 + 17 * math.ceil(max(0, count - 5) / 17)


def ripple_working_size(width, height, scale=1, model='h3'):
    """Round the requested processing scale up on the selected model grid."""
    if (isinstance(width, bool) or isinstance(height, bool)
            or not isinstance(width, int) or not isinstance(height, int)
            or width < 1 or height < 1):
        raise ValueError('Source width and height must be positive whole pixels.')
    if scale not in (1, .75, .5, .25):
        raise ValueError('Choose full, 75%, 50% or 25% processing size.')
    if model not in ('h3', 'ltx'):
        raise ValueError('Choose the H3 or LTX Ripple model.')
    grid = 32 if model == 'h3' else 64
    snap = lambda value: max(64, math.ceil(value * scale / grid) * grid)
    result = (snap(width), snap(height))
    if max(result) > 4096:
        raise ValueError('Processing dimensions exceed 4096 pixels. Choose a smaller processing size.')
    return result


class ZuraRippleH3Guide:
    """Bridge Zura's full-rate source/anchor data into WN_RippleApply."""

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'plate': ('ZURA_PLATE',), 'anchors': ('ZURA_ANCHORS',)}}

    RETURN_TYPES = ('WN_RIPPLE', 'IMAGE', 'INT')
    RETURN_NAMES = ('ripple', 'edited_images', 'inference_frames')
    FUNCTION = 'prepare'
    CATEGORY = 'Zura/Ripple'

    def prepare(self, plate, anchors):
        if plate.get('processing') != 'SDR (sRGB)' or plate.get('space') in (
                'hlg_rec2020', 'pq_rec2020', 'acescg', 'acescct', 'linear_rec709', 'pq_display_p3'):
            raise ValueError('H3 Ripple currently supports SDR footage only.')
        if plate.get('framing_mode') != 'Full frame (stretch to working size)':
            raise ValueError('H3 Ripple needs the full source frame stretched to the working dimensions.')
        images = plate.get('_work_images')
        if not isinstance(images, torch.Tensor) or images.ndim != 4 or images.shape[-1] != 3:
            raise ValueError('The prepared source must contain RGB video frames.')
        count = plate.get('count')
        working_count = h3_working_frames(count)
        if len(images) < count:
            raise ValueError('The source did not decode every frame in the selected range.')
        height, width = images.shape[1:3]
        if width < 64 or height < 64 or width % 32 or height % 32:
            raise ValueError('H3 Ripple processing dimensions must be multiples of 32 pixels.')
        if not isinstance(anchors, (tuple, list)) or not 1 <= len(anchors) <= 16:
            raise ValueError('Add between 1 and 16 edited keyframes.')
        if any(not isinstance(anchor, (tuple, list)) or len(anchor) != 3 for anchor in anchors):
            raise ValueError('An edited keyframe is invalid.')
        ordered = sorted(anchors, key=lambda anchor: anchor[0])
        markers, edited, seen = [], [], set()
        for identity, anchor in enumerate(ordered, 1):
            frame, image, strength = anchor
            if isinstance(frame, bool) or not isinstance(frame, int) or not 0 <= frame < count:
                raise ValueError('An edited keyframe is outside the selected source range.')
            if frame in seen:
                raise ValueError('Choose a different frame for each edited keyframe.')
            if not isinstance(image, torch.Tensor) or image.shape != (1, height, width, 3):
                raise ValueError('Each edited keyframe must match the prepared source dimensions.')
            try:
                strength = float(strength)
            except (TypeError, ValueError):
                raise ValueError('H3 Ripple keyframes currently use full strength.') from None
            if strength != 1:
                raise ValueError('H3 Ripple keyframes currently use full strength.')
            seen.add(frame)
            markers.append({'id': identity, 'frame': frame, 'edited': '', 'edited_at': None})
            edited.append(image.to(device=images.device, dtype=images.dtype))
        # Ignore any 8n+1 padding inserted for the LTX path. Hold the actual
        # final source frame to H3's own grid, keeping every frame one-to-one.
        window = images[:count]
        if working_count > count:
            window = torch.cat((window, window[-1:].expand(working_count - count, -1, -1, -1)))
        geometry = {'crop': [0., 0., 1., 1.], 'source_rect': [0, 0, width, height],
                    'width': width, 'height': height, 'content_rect': [0, 0, width, height],
                    'resize_method': 'lanczos'}
        context = {'window': window, 'markers': markers, 'length': working_count,
                   'width': width, 'height': height, 'geometry': geometry,
                   'fps': float(plate['fps']), 'window_start': int(plate.get('start', 0)),
                   'source': str(plate.get('source', {}).get('path', ''))}
        # Deliberately omit window_key: it prevents WepeNerd's VAE cache from
        # reusing another source's latent after a source or range change.
        return context, torch.cat(edited), working_count


NODE_CLASS_MAPPINGS = {'ZuraRippleH3Guide': ZuraRippleH3Guide}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraRippleH3Guide': 'Ripple · Preserve Source Timing'}
