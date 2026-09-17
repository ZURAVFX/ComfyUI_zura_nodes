"""VIDEO assembly for Zura nodes.

Uses ComfyUI's native ``VideoFromComponents`` when available so nodes can
return real ``VIDEO`` wires previewable by any ComfyUI video node.  Falls back
to a plain dict component structure in test environments without the ComfyUI
API package.
"""
from __future__ import annotations

from fractions import Fraction
import math


def components_from_frames(images, audio=None, fps=24):
    """Normalise frames (+ optional audio) into VideoComponents-like data."""
    import torch
    if not isinstance(images, torch.Tensor) or images.ndim != 4 or images.shape[-1] != 3:
        raise ValueError("video frames must be an IMAGE tensor [frames,height,width,3]")
    if int(images.shape[0]) < 1:
        raise ValueError("video frames must contain at least one frame")
    fps = float(fps)
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("video frame rate must be a finite positive number")
    if audio is not None:
        if not isinstance(audio, dict) or 'waveform' not in audio or 'sample_rate' not in audio:
            raise ValueError('audio must be a ComfyUI audio dict with waveform and sample_rate')
        if not isinstance(audio['waveform'], torch.Tensor) or audio['waveform'].ndim < 2:
            raise ValueError('audio waveform must be a tensor with a sample dimension')
        if int(audio['sample_rate']) <= 0:
            raise ValueError('audio sample_rate must be positive')
        audio = dict(audio)
        wanted = round(images.shape[0] / float(fps) * int(audio['sample_rate']))
        if audio['waveform'].shape[-1] < wanted:
            audio['waveform'] = torch.nn.functional.pad(audio['waveform'], (0, wanted - audio['waveform'].shape[-1]))
        audio['waveform'] = audio['waveform'][..., :wanted]
    return {'images': images, 'audio': audio, 'frame_rate': Fraction(str(fps))}


def video_output(images, audio=None, fps=24):
    """Return a native ComfyUI VIDEO object, or the component dict as fallback."""
    components = components_from_frames(images, audio, fps)
    try:
        from comfy_api.latest import InputImpl, Types
        return InputImpl.VideoFromComponents(Types.VideoComponents(**components))
    except ImportError:
        return components


def video_components(video):
    """Unpack a ``VIDEO`` wire into ``(frames, audio, fps)``.

    Accepts ComfyUI's native VIDEO (which exposes ``get_components``) and this
    pack's component-dict fallback, so nodes that read a video wire work with or
    without the ComfyUI API package.
    """
    if video is None:
        raise ValueError("no video was provided")
    data = video.get_components() if hasattr(video, "get_components") else video
    if not isinstance(data, dict):
        data = {key: getattr(data, key, None) for key in ("images", "audio", "frame_rate")}
    images = data.get("images")
    if images is None:
        raise ValueError("video has no frames")
    fps = data.get("frame_rate")
    fps = 24 if fps is None else float(fps)
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError(f"video has an unusable frame rate: {fps}")
    return images, data.get("audio"), fps
