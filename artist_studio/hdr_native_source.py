"""Experimental, bounded native HDR input for the LTX 2.5 HDR workflow.

This loader prepares native sources for Studio's bounded experimental HDR
graph. Its colour transforms and end-to-end visual quality still need
qualification on representative HDR camera footage.
"""
from __future__ import annotations

import math
from fractions import Fraction
import torch
import torch.nn.functional as F

from .hdr_source import MAX_FRAMES, MAX_PIXEL_FRAMES

HDR_VIDEO_SPACES = ('hlg_rec2020', 'pq_rec2020', 'pq_display_p3')
HDR_SEQUENCE_SPACES = ('acescg', 'acescct', 'linear_rec709')


def _resample_video(info, start_seconds, frame_count, output_fps, colour):
    """Use the reviewed clip's FFmpeg timing without its SDR/compressed proxy."""
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path
    import numpy as np
    from ..paintout.paintout import find_media_tool, working

    # Match GenjSelectClip's seek, timestamp reset, fps rounding and held tail.
    # Decode the original encoded HDR values into full-range RGB16; transfer
    # and primaries conversion happens afterwards, without an SDR round-trip.
    vf = f'setpts=PTS-STARTPTS,fps={output_fps}'
    matrix = {'bt2020nc': 'bt2020', 'bt2020c': 'bt2020', 'bt709': 'bt709',
              'smpte170m': 'bt601'}.get(info.get('matrix'))
    if matrix:
        vf += f',scale=in_color_matrix={matrix}:in_range={"pc" if info.get("range") == "pc" else "tv"}:out_range=pc'
    vf += ',tpad=stop_mode=clone:stop=1'
    frame_bytes = info['width'] * info['height'] * 3 * 2
    expected = frame_bytes * frame_count
    with tempfile.TemporaryDirectory(prefix='zura-hdr-timeline-') as directory:
        if shutil.disk_usage(directory).free < expected * 1.2:
            raise ValueError('Free more temporary disk space or choose fewer HDR frames.')
        path = Path(directory) / 'selected.rgb'
        command = [find_media_tool('ffmpeg'), '-v', 'error', '-ss', str(start_seconds),
                   '-i', info['path'], '-vf', vf, '-frames:v', str(frame_count),
                   '-an', '-sn', '-fps_mode', 'passthrough', '-f', 'rawvideo',
                   '-pix_fmt', 'rgb48le', str(path)]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=300)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise ValueError('Could not prepare the selected native HDR timeline.') from error
        if path.stat().st_size != expected:
            raise ValueError('The source ended before the selected frame range.')
        mapped = np.memmap(path, dtype='<u2', mode='r', shape=(frame_count, info['height'], info['width'], 3))
        result = []
        try:
            for pixels in mapped:
                rgb = torch.from_numpy(pixels.astype(np.float32) / 65535.)[None]
                converted = working(rgb, colour, 'HDR (ACEScct)')
                if not torch.isfinite(converted).all():
                    raise ValueError('The HDR colour transform produced non-finite pixels.')
                result.append(converted)
        finally:
            del pixels, mapped
        return torch.cat(result), float(output_fps)


def resample_native_hdr_frames(path, start_seconds, frame_count, output_fps=24,
                               colour_space='auto', sequence_fps=24):
    """Experimental CFR selection in ACEScct, with no SDR proxy round-trip.

    Video uses the same CFR selection as Studio's approved motion proxy.
    EXR sequences select the source frame displayed at each output timestamp.
    Every output sample must fall inside the source; a final output frame may
    straddle its end. Temporal inference padding is performed separately.
    """
    from pathlib import Path
    from ..paintout.paintout import describe, selected_space, frames, working

    if isinstance(start_seconds, bool) or not isinstance(start_seconds, (int, float)) or not math.isfinite(start_seconds) or start_seconds < 0:
        raise ValueError('Choose a valid selection start.')
    if type(frame_count) is not int or not 1 <= frame_count <= MAX_FRAMES:
        raise ValueError(f'Choose between 1 and {MAX_FRAMES} output frames.')
    if isinstance(output_fps, bool) or not isinstance(output_fps, (int, float)) or not math.isfinite(output_fps) or not 1 <= output_fps <= 120:
        raise ValueError('Choose a valid output frame rate.')
    if colour_space not in ('auto', *HDR_VIDEO_SPACES, *HDR_SEQUENCE_SPACES):
        raise ValueError('Choose a supported HDR colour space.')
    info = describe(path)
    if info['width'] * info['height'] * frame_count > MAX_PIXEL_FRAMES:
        raise ValueError('The selection exceeds the HDR memory budget.')
    if info['kind'] == 'video' and info.get('transfer') in ('bt709', 'iec61966-2-1'):
        raise ValueError('This video is tagged SDR. Use the SDR-to-HDR workflow.')
    if colour_space == 'pq_display_p3' and (info.get('transfer') != 'smpte2084' or info.get('primaries') != 'smpte432'):
        raise ValueError('Display-P3 PQ requires matching source transfer and primaries tags.')
    selected = selected_space(info, colour_space)
    if selected not in (HDR_VIDEO_SPACES if info['kind'] == 'video' else HDR_SEQUENCE_SPACES):
        raise ValueError('Choose a supported HDR video or EXR colour space.')
    if isinstance(sequence_fps, bool) or not isinstance(sequence_fps, (int, float)) or not math.isfinite(sequence_fps) or not 1 <= sequence_fps <= 120:
        raise ValueError('Choose a valid sequence frame rate.')
    source_rate = Fraction(info.get('fps_rational', str(sequence_fps)))
    target_rate = Fraction(str(output_fps))
    if not 1 <= source_rate <= 120:
        raise ValueError('Choose a valid source frame rate.')
    start = Fraction(str(start_seconds))
    # A final output sample may begin before the source ends even when its
    # display interval extends slightly beyond it. No sample may begin at or
    # after the source end: that would invent an extra source frame.
    source_end = Fraction(info['count'], 1) / source_rate
    if start + Fraction(frame_count - 1, 1) / target_rate >= source_end:
        raise ValueError('The selected range extends past the source.')
    if info['kind'] == 'video':
        return _resample_video(info, start_seconds, frame_count, output_fps, selected)
    indices = [int((start + Fraction(i, 1) / target_rate) * source_rate) for i in range(frame_count)]
    if indices[-1] >= info['count']:
        raise ValueError('The selected range extends past the source.')
    first, last = indices[0], indices[-1]
    if info['kind'] == 'sequence' and any(Path(name).suffix.lower() != '.exr' for name in info['files'][first:last + 1]):
        raise ValueError('Native HDR image input requires EXR frames.')
    result = []
    next_output = 0
    for index, frame in enumerate(frames(info, first, last - first + 1), first):
        if next_output >= frame_count:
            break
        if index != indices[next_output]:
            continue
        if frame.shape != (info['height'], info['width'], 3):
            raise ValueError('The source dimensions change within the selection.')
        rgb = torch.from_numpy(frame.copy()).float()[None]
        if not torch.isfinite(rgb).all():
            raise ValueError('The source contains non-finite pixels.')
        converted = working(rgb, selected, 'HDR (ACEScct)')
        if not torch.isfinite(converted).all():
            raise ValueError('The HDR colour transform produced non-finite pixels.')
        while next_output < frame_count and indices[next_output] == index:
            result.append(converted)
            next_output += 1
    if next_output != frame_count:
        raise ValueError('The source ended before the selected frame range.')
    return torch.cat(result), float(target_rate)


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
    if colour_space == 'pq_display_p3' and (info.get('transfer') != 'smpte2084' or info.get('primaries') != 'smpte432'):
        raise ValueError('Display-P3 PQ requires matching source transfer and primaries tags.')
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


class ZuraHDRSelectNativeTimeline:
    """Internal experimental timeline selection; not yet a Studio route."""
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'source': ('STRING', {'default': ''}),
            'start_seconds': ('FLOAT', {'default': 0., 'min': 0.}),
            'frame_count': ('INT', {'default': 48, 'min': 1, 'max': MAX_FRAMES}),
            'output_fps': ('FLOAT', {'default': 24., 'min': 1., 'max': 120.}),
            'colour_space': (['auto', *HDR_VIDEO_SPACES, *HDR_SEQUENCE_SPACES],),
            'sequence_fps': ('FLOAT', {'default': 24., 'min': 1., 'max': 120.})},
            'optional': {'manifest': ('STRING', {'default': ''}), 'manifest_sha': ('STRING', {'default': ''})}}
    RETURN_TYPES = ('IMAGE', 'FLOAT')
    FUNCTION = 'load'
    CATEGORY = 'Zura/Artist Studio/Experimental'
    @classmethod
    def IS_CHANGED(cls, **kwargs): return float('nan')
    def load(self, source, start_seconds, frame_count, output_fps, colour_space, sequence_fps, manifest='', manifest_sha=''):
        if manifest:
            from .hdr_sequence import validate_manifest
            if (isinstance(start_seconds, bool) or not isinstance(start_seconds, (int, float)) or not math.isfinite(start_seconds) or start_seconds < 0
                    or type(frame_count) is not int or not 1 <= frame_count <= MAX_FRAMES
                    or isinstance(output_fps, bool) or not isinstance(output_fps, (int, float)) or not math.isfinite(output_fps) or not 1 <= output_fps <= 120
                    or isinstance(sequence_fps, bool) or not isinstance(sequence_fps, (int, float)) or not math.isfinite(sequence_fps) or not 1 <= sequence_fps <= 120):
                raise ValueError('Choose a valid EXR timeline selection.')
            first = int(Fraction(str(start_seconds)) * Fraction(str(sequence_fps)))
            last = int((Fraction(str(start_seconds)) + Fraction(frame_count - 1, 1) / Fraction(str(output_fps))) * Fraction(str(sequence_fps)))
            source, entries = validate_manifest(manifest, manifest_sha, first, last - first + 1)
            # describe() reads frame zero for dimensions, and auto colour
            # detection inspects every frame's tags. Validate every file those
            # operations rely on, including outside the selected range.
            if colour_space == 'auto':
                validate_manifest(manifest, manifest_sha, 0, len(entries))
            elif first > 0:
                validate_manifest(manifest, manifest_sha, 0, 1)
        return resample_native_hdr_frames(source, start_seconds, frame_count, output_fps, colour_space, sequence_fps)


class ZuraHDRTemporalHold:
    @classmethod
    def INPUT_TYPES(cls): return {'required': {'images': ('IMAGE',)}}
    RETURN_TYPES = ('IMAGE',)
    FUNCTION = 'hold'
    CATEGORY = 'Zura/Artist Studio/Experimental'
    def hold(self, images):
        if not isinstance(images, torch.Tensor) or images.ndim != 4 or images.shape[-1] != 3 or not 1 <= len(images) <= MAX_FRAMES:
            raise ValueError('Expected a bounded HDR frame selection.')
        count = len(images)
        padded = max(9, 1 + 8 * ((count + 6) // 8))
        return (torch.cat((images, images[-1:].expand(padded - count, -1, -1, -1)), 0) if padded > count else images,)


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
                     'ZuraHDRSelectNativeTimeline':ZuraHDRSelectNativeTimeline,'ZuraHDRTemporalHold':ZuraHDRTemporalHold,
                     'ZuraHDRLoadNativeSourceLong':ZuraHDRLoadNativeSourceLong,'ZuraHDRNativePrepareLong':ZuraHDRNativePrepareLong}
NODE_DISPLAY_NAME_MAPPINGS={'ZuraHDRLoadNativeSource':'Zura · Load Native HDR Source',
                            'ZuraHDRNativePrepare':'Zura · Prepare Native HDR Frames'}
