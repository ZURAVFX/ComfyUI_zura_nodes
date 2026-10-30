"""Experimental, bounded native HDR input for the LTX 2.5 HDR workflow.

This loader prepares native sources for Studio's bounded experimental HDR
graph. Its colour transforms and end-to-end visual quality still need
qualification on representative HDR camera footage.
"""
from __future__ import annotations

import math
import torch
import torch.nn.functional as F

from .hdr_source import MAX_FRAMES, MAX_PIXEL_FRAMES

HDR_VIDEO_SPACES = ('hlg_rec2020', 'pq_rec2020')
HDR_SEQUENCE_SPACES = ('acescg', 'acescct', 'linear_rec709')


def load_native_hdr_frames(path, start_frame, frame_count, colour_space='auto', sequence_fps=24, *, max_frames=MAX_FRAMES):
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
    if type(max_frames) is not int or not 1 <= max_frames <= 257:
        raise ValueError('Invalid HDR source frame limit.')
    if type(frame_count) is not int or not 1 <= frame_count <= max_frames:
        raise ValueError(f'Choose between 1 and {max_frames} frames.')
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


class ZuraHDRLoadNativeSource:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'source': ('STRING', {'default': ''}),
            'start_frame': ('INT', {'default': 0, 'min': 0}),
            'frame_count': ('INT', {'default': 25, 'min': 1, 'max': MAX_FRAMES}),
            'colour_space': (['auto', *HDR_VIDEO_SPACES, *HDR_SEQUENCE_SPACES],),
            'sequence_fps': ('FLOAT', {'default': 24., 'min': 1., 'max': 120.})},
            'optional': {'manifest': ('STRING', {'default': ''}), 'manifest_sha': ('STRING', {'default': ''})}}
    RETURN_TYPES = ('IMAGE', 'FLOAT')
    RETURN_NAMES = ('acescct_frames', 'fps')
    FUNCTION = 'load'
    CATEGORY = 'Zura/Artist Studio'
    @classmethod
    def IS_CHANGED(cls, **kwargs): return float('nan')
    def load(self, source, start_frame, frame_count, colour_space, sequence_fps, manifest='', manifest_sha=''):
        if manifest:
            from .hdr_sequence import validate_manifest
            source, _ = validate_manifest(manifest, manifest_sha, start_frame, frame_count)
        return load_native_hdr_frames(source, start_frame, frame_count, colour_space, sequence_fps)


class ZuraHDRNativePrepare:
    @classmethod
    def INPUT_TYPES(cls): return {'required': {'images': ('IMAGE',)}}
    RETURN_TYPES = ('IMAGE', 'INT', 'INT', 'INT', 'INT', 'INT', 'INT')
    RETURN_NAMES = ('frames', 'source_width', 'source_height', 'source_count',
                    'canvas_width', 'canvas_height', 'padded_count')
    FUNCTION = 'prepare'
    CATEGORY = 'Zura/Artist Studio'
    def prepare(self, images):
        return prepare_native_hdr(images, MAX_FRAMES)


def prepare_native_hdr(images, max_frames):
    if not isinstance(images, torch.Tensor) or images.ndim != 4 or images.shape[-1] != 3 or not torch.isfinite(images).all():
        raise ValueError('Expected finite ACEScct RGB frames.')
    count, height, width, _ = images.shape
    if count < 1 or count > max_frames or min(width,height) < 32 or max(width,height) > 2048:
        raise ValueError(f'Choose 1–{max_frames} frames between 32 and 2048 pixels per side.')
    # Pad rather than distort the source; remove the padding after decoding.
    pw=max(512,math.ceil(width/64)*64); ph=max(512,math.ceil(height/64)*64)
    padded=max(9,1+8*((count-1+7)//8))
    if pw*ph*padded>MAX_PIXEL_FRAMES:
        raise ValueError('The padded HDR selection exceeds the memory budget.')
    images=F.pad(images.permute(0,3,1,2),(0,pw-width,0,ph-height),mode='replicate').permute(0,2,3,1)
    if padded>count: images=torch.cat((images,images[-1:].expand(padded-count,-1,-1,-1)),0)
    return images,width,height,count,pw,ph,padded


class ZuraHDRLoadNativeSourceLong(ZuraHDRLoadNativeSource):
    """Internal experimental loader; Studio's public node remains bounded."""
    @classmethod
    def INPUT_TYPES(cls):
        inputs=super().INPUT_TYPES()
        inputs['required']['frame_count']=('INT',{'default':129,'min':1,'max':257})
        return inputs
    def load(self, source, start_frame, frame_count, colour_space, sequence_fps, manifest='', manifest_sha=''):
        if manifest:
            from .hdr_sequence import validate_manifest
            source,_=validate_manifest(manifest,manifest_sha,start_frame,frame_count)
        return load_native_hdr_frames(source,start_frame,frame_count,colour_space,sequence_fps,max_frames=257)


class ZuraHDRNativePrepareLong(ZuraHDRNativePrepare):
    """Internal memory-bounded preparation for temporal fusion experiments."""
    def prepare(self,images):return prepare_native_hdr(images,257)


NODE_CLASS_MAPPINGS={'ZuraHDRLoadNativeSource':ZuraHDRLoadNativeSource,'ZuraHDRNativePrepare':ZuraHDRNativePrepare,
                     'ZuraHDRLoadNativeSourceLong':ZuraHDRLoadNativeSourceLong,'ZuraHDRNativePrepareLong':ZuraHDRNativePrepareLong}
NODE_DISPLAY_NAME_MAPPINGS={'ZuraHDRLoadNativeSource':'Zura · Load Native HDR Source',
                            'ZuraHDRNativePrepare':'Zura · Prepare Native HDR Frames'}
