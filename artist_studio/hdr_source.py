"""Bounded colour-managed source reader for the experimental LTX HDR route."""
from __future__ import annotations

import io
import math
import shutil
import subprocess
import numpy as np
import torch
from .hdr_prepare import MAX_PIXEL_FRAMES

MAX_FRAMES = 121
# Three float32 channels are approximately 480 MB at 40 million pixels.
SDR_SPACES = ('srgb_display', 'rec709_oetf', 'rec709_gamma24')


def load_sdr_frames(path, start_frame, frame_count, colour_space='auto', sequence_fps=24):
    """Read exactly one bounded source range into display-referred sRGB.

    Reuses paintout's frame-exact 16-bit decode and colour transforms. HDR,
    log/unknown metadata, variable FPS and oversized batches are refused rather
    than silently treating their pixels as sRGB. Explicit overrides are for
    artists who know the encoding of an untagged file.
    """
    from ..paintout.paintout import describe, selected_space, frames, _decode_original, _encode_original
    if type(start_frame) is not int or start_frame < 0:
        raise ValueError('Choose a non-negative first frame.')
    if type(frame_count) is not int or not 1 <= frame_count <= MAX_FRAMES:
        raise ValueError(f'Choose between 1 and {MAX_FRAMES} frames for one HDR conversion.')
    if colour_space not in ('auto', *SDR_SPACES):
        raise ValueError('Choose a supported SDR source colour space.')
    info = describe(path)
    if info.get('transfer') in ('arib-std-b67', 'smpte2084'):
        raise ValueError('This source is tagged HDR. Use the native HDR workflow rather than SDR-to-HDR.')
    if start_frame + frame_count > info['count']:
        raise ValueError('The selected frame range extends past the source.')
    if info['width'] * info['height'] * frame_count > MAX_PIXEL_FRAMES:
        raise ValueError('This selection is too large for one HDR conversion. Choose fewer frames or smaller footage.')
    selected = selected_space(info, colour_space)
    if selected not in SDR_SPACES:
        raise ValueError('This conversion accepts SDR footage only. Native HDR input needs the separate HDR workflow.')
    fps = info.get('fps', sequence_fps)
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps) or not 1 <= fps <= 120:
        raise ValueError('Choose a valid frame rate between 1 and 120 fps.')
    output=[]
    for frame in frames(info, start_frame, frame_count):
        if frame.shape != (info['height'], info['width'], 3):
            raise ValueError('The source dimensions change within the selection.')
        encoded=torch.from_numpy(frame.copy()).float()[None]
        # Rec.709 and sRGB share primaries, so only the transfer curve changes.
        converted=_encode_original(_decode_original(encoded,selected),'srgb_display')
        if not torch.isfinite(converted).all():
            raise ValueError('The source contains non-finite pixels.')
        output.append(converted.clamp(0, 1))
    if len(output) != frame_count:
        raise ValueError('The source ended before the selected frame range.')
    return torch.cat(output), float(fps)


class ZuraHDRLoadSDRSource:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'source': ('STRING', {'default': ''}),
                'start_frame': ('INT', {'default': 0, 'min': 0}),
                'frame_count': ('INT', {'default': 25, 'min': 1, 'max': MAX_FRAMES}),
                'colour_space': (['auto', *SDR_SPACES],),
                'sequence_fps': ('FLOAT', {'default': 24.0, 'min': 1.0, 'max': 120.0})}}
    RETURN_TYPES=('IMAGE', 'FLOAT')
    RETURN_NAMES=('srgb_frames', 'fps')
    FUNCTION='load'
    CATEGORY='Zura/Artist Studio'
    @classmethod
    def IS_CHANGED(cls, **kwargs): return float('nan')
    def load(self, source, start_frame, frame_count, colour_space, sequence_fps):
        return load_sdr_frames(source, start_frame, frame_count, colour_space, sequence_fps)


class ZuraHDRLoadAudioRange:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'source':('STRING',{'default':''}), 'start_frame':('INT',{'default':0,'min':0}),
                'frame_count':('INT',{'default':25,'min':1,'max':MAX_FRAMES}),
                'fps':('FLOAT',{'default':24.0,'min':1.0,'max':120.0})}}
    RETURN_TYPES=('AUDIO',)
    FUNCTION='load'
    CATEGORY='Zura/Artist Studio'
    @classmethod
    def IS_CHANGED(cls, **kwargs): return float('nan')
    def load(self, source, start_frame, frame_count, fps):
        return load_hdr_audio_range(source,start_frame,frame_count,fps,MAX_FRAMES)


def load_hdr_audio_range(source, start_frame, frame_count, fps, max_frames, *, start_seconds=None, allow_tail_hold=False, source_duration=None):
    from ..paintout.paintout import resolve_input
    import av
    if type(max_frames) is not int or not 1<=max_frames<=257 or type(start_frame) is not int or start_frame<0 or type(frame_count) is not int or not 1<=frame_count<=max_frames or not isinstance(fps,(float,int)) or isinstance(fps,bool) or not math.isfinite(fps) or not 1<=fps<=120:
        raise ValueError('Choose a valid audio frame range and frame rate.')
    path=resolve_input(source)
    executable=shutil.which('ffmpeg')
    if not executable: raise ValueError('FFmpeg is required to restore the source audio.')
    if start_seconds is not None and (isinstance(start_seconds,bool) or not isinstance(start_seconds,(float,int)) or not math.isfinite(start_seconds) or start_seconds < 0):
        raise ValueError('Choose a valid audio start time.')
    duration=frame_count/fps
    if source_duration is not None and (isinstance(source_duration, bool) or not isinstance(source_duration, (int, float))
            or not math.isfinite(source_duration) or source_duration <= 0 or source_duration > duration + 1e-6):
        raise ValueError('Choose a valid selected audio duration.')
    # Decode one extra frame of audio, then trim to the exact video duration.
    # AAC timestamp rounding at fractional frame rates can otherwise leave a
    # valid selection a few samples short even when more audio follows.
    result=subprocess.run([executable,'-hide_banner','-loglevel','error','-i',str(path),
        '-ss',str(start_frame/fps if start_seconds is None else start_seconds),'-t',str(duration+1/fps),'-map','0:a:0','-vn','-ac','2','-ar','48000',
        '-c:a','pcm_f32le','-f','wav','pipe:1'],capture_output=True)
    if result.returncode:
        raise ValueError('Could not read the selected source audio.')
    with av.open(io.BytesIO(result.stdout),format='wav') as container:
        resampler=av.AudioResampler(format='fltp',layout='stereo',rate=48000)
        chunks=[converted.to_ndarray() for frame in container.decode(audio=0) for converted in resampler.resample(frame)]
        chunks.extend(frame.to_ndarray() for frame in resampler.resample(None))
    if not chunks: raise ValueError('No audio was found in the selected range.')
    samples=torch.from_numpy(np.concatenate(chunks,axis=-1).copy()).float()
    expected=round(duration*48000)
    selected=expected if source_duration is None else min(expected, round(source_duration*48000))
    if samples.shape[-1]<selected:
        short=selected-samples.shape[-1]
        permitted = 48 + (math.ceil(48000 / fps) if allow_tail_hold else 0)
        if short>permitted:
            raise ValueError('The source audio is shorter than the selected video range.')
        # A fractional final video frame may require a short silent tail.
        samples=torch.nn.functional.pad(samples,(0,short))
    samples=samples[..., :selected]
    if selected<expected: samples=torch.nn.functional.pad(samples,(0,expected-selected))
    return ({'waveform':samples[None, ..., :expected], 'sample_rate':48000},)

class ZuraHDRLoadAudioRangeLong(ZuraHDRLoadAudioRange):
    """Internal long HDR experiment; not used by the public Studio graph."""
    @classmethod
    def INPUT_TYPES(cls):
        inputs=super().INPUT_TYPES()
        inputs['required']['frame_count']=('INT',{'default':129,'min':1,'max':257})
        return inputs
    def load(self,source,start_frame,frame_count,fps):
        return load_hdr_audio_range(source,start_frame,frame_count,fps,257)


class ZuraHDRLoadTimedAudio:
    """Experimental audio selection matching a time-based video trim."""
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'source': ('STRING', {'default': ''}),
            'start_seconds': ('FLOAT', {'default': 0., 'min': 0.}),
            'frame_count': ('INT', {'default': 48, 'min': 1, 'max': MAX_FRAMES}),
            'fps': ('FLOAT', {'default': 24., 'min': 1., 'max': 120.})},
            'optional': {'allow_tail_hold': ('BOOLEAN', {'default': False}),
                         'source_duration': ('FLOAT', {'default': 0., 'min': 0.})}}
    RETURN_TYPES = ('AUDIO',)
    FUNCTION = 'load'
    CATEGORY = 'Zura/Artist Studio/Experimental'
    @classmethod
    def IS_CHANGED(cls, **kwargs): return float('nan')
    def load(self, source, start_seconds, frame_count, fps, allow_tail_hold=False, source_duration=0.):
        return load_hdr_audio_range(source, 0, frame_count, fps, MAX_FRAMES, start_seconds=start_seconds,
                                    allow_tail_hold=allow_tail_hold, source_duration=source_duration or None)


NODE_CLASS_MAPPINGS={'ZuraHDRLoadSDRSource': ZuraHDRLoadSDRSource,'ZuraHDRLoadAudioRange':ZuraHDRLoadAudioRange,
                     'ZuraHDRLoadAudioRangeLong':ZuraHDRLoadAudioRangeLong, 'ZuraHDRLoadTimedAudio':ZuraHDRLoadTimedAudio}
NODE_DISPLAY_NAME_MAPPINGS={'ZuraHDRLoadSDRSource': 'Zura · Load SDR Source for LTX HDR',
                           'ZuraHDRLoadAudioRange':'Zura · Load HDR Audio Range'}
