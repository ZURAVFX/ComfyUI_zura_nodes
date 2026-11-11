"""Bounded LTX 2.5 outpaint using the artist-approved full-resolution recipe.

The artist reviews a white-to-generate mask for the exact source and settings.
Review identifiers bind the selection to those settings so a change cannot
silently reuse an earlier approval. The output retains the selected duration.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

import torch
import torch.nn.functional as F

FPS = 24
MAX_FRAMES = 120


def source_rate(source):
    """Preserve exact native cadence when known; old cached sources default to 24."""
    from fractions import Fraction
    try:
        rate = Fraction(int(source.get('fps_num', FPS)), int(source.get('fps_den', 1)))
    except (ValueError, TypeError, ZeroDivisionError):
        raise ValueError('The source frame rate is invalid.')
    if not 1 <= rate <= 120:
        raise ValueError('Frame extension supports source rates from 1 to 120 fps.')
    return rate


def needs_bounded_canvas(width, height, duration, fps=FPS):
    if any(type(side) is not int or side < 128 for side in (width, height)):
        return False
    try:
        frames = math.ceil(float(duration) * float(fps) - 1e-6)
    except (TypeError, ValueError, OverflowError):
        return False
    area = ((width + 63) // 64 * 64) * ((height + 63) // 64 * 64)
    padded_frames = max(9, 1 + 8 * ((frames + 6) // 8))
    return area > 2_100_000 and area * padded_frames > 40_000_000


def plan(source, *, start, duration, mode, width, height, left=0, top=0,
         right=0, bottom=0, black_threshold=2 / 255, allow_partial_end=False, ae_frame_contract=None):
    """Validate a short source range and bind its cadence and geometry to review."""
    if not isinstance(source, dict) or not source.get('sha') or not source.get('file'):
        raise ValueError('Select a source video first.')
    if isinstance(start, bool) or isinstance(duration, bool):
        raise ValueError('Choose a valid start and duration.')
    start, duration = float(start), float(duration)
    if not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration <= 0:
        raise ValueError('Choose a valid start and duration.')
    fps = source_rate(source)
    frames = math.ceil(duration * fps - 1e-6)
    # Three frames make a meaningful short sample.
    if not 3 <= frames <= MAX_FRAMES:
        raise ValueError('Choose at least 3 frames and no more than 120 frames per section.')
    available = float(source.get('duration', 0))
    if not math.isfinite(available) or available <= 0 or start + duration > available + (1 / float(fps) if allow_partial_end else 0) + 1e-4:
        raise ValueError('The selection extends past the source video.')
    if mode not in ('expand', 'black'):
        raise ValueError('Choose canvas expansion or black areas.')
    if any(type(x) is not int for x in (width, height, left, top, right, bottom)):
        raise ValueError('Use whole-pixel canvas dimensions and margins.')
    if min(width, height) < 128 or max(width, height) > 1920 or (mode == 'expand' and (width % 64 or height % 64)):
        raise ValueError('Choose dimensions from 128 to 1920; expanded canvases use steps of 64 pixels.')
    padded_width, padded_height = (width + 63) // 64 * 64, (height + 63) // 64 * 64
    if needs_bounded_canvas(width, height, duration, fps):
        raise ValueError('This canvas and frame count need overlapping sections. Use Expand canvas with automatic sections, or select fewer frames.')
    if (max(abs(v) for v in (left, top, right, bottom)) > 32768 or
            left + right >= width or top + bottom >= height or
            left >= width or right >= width or top >= height or bottom >= height):
        raise ValueError('The canvas margins leave no room for the source.')
    if not math.isfinite(float(black_threshold)) or not 0 <= float(black_threshold) <= .1:
        raise ValueError('Black threshold must be between 0 and 0.1.')
    if mode == 'black' and (int(source.get('width', 0)), int(source.get('height', 0))) != (width, height):
        raise ValueError('Use source dimensions for a black-padded clip.')
    if mode == 'black' and (width % 2 or height % 2):
        raise ValueError('MP4 export needs even dimensions. Add a one-pixel border to the source and try again.')
    if mode == 'black' and any((left, top, right, bottom)):
        raise ValueError('Margins apply to canvas expansion, not a black-padded clip.')
    values = {'source_sha': str(source['sha']), 'start': start, 'frames': frames, 'requested_duration': duration, 'fps_num': fps.numerator, 'fps_den': fps.denominator,
              'mode': mode, 'width': width, 'height': height,
              'left': left, 'top': top, 'right': right, 'bottom': bottom,
              'black_threshold': float(black_threshold)}
    if ae_frame_contract is not None:
        from ..comfylink.frame_contract import validate_interval
        values['ae_frame_contract']=validate_interval(ae_frame_contract,frames=frames,fps=fps,width=width,height=height)
    key = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {**values, 'duration': float(frames / fps), 'padded_frames': max(9, 1 + 8 * ((frames + 6) // 8)),
            'padded_width': padded_width, 'padded_height': padded_height, 'review_key': key}


def hold_video_audio(images, audio, expected_frames, fps=FPS):
    """Pad the selected clip only for inference; keep its original count."""
    if not isinstance(images, torch.Tensor) or images.ndim != 4 or images.shape[-1] != 3:
        raise ValueError('Expected selected RGB video frames.')
    count = len(images)
    if type(expected_frames) is not int or count != expected_frames or not 1 <= count <= MAX_FRAMES:
        raise ValueError('The selected video frame count changed. Select the range again.')
    if not 1 <= float(fps) <= 120 or not isinstance(audio, dict) or not isinstance(audio.get('waveform'), torch.Tensor):
        raise ValueError('Frame extension needs a valid source rate and audio or silent audio.')
    wave, rate = audio['waveform'], audio.get('sample_rate')
    if type(rate) is not int or rate <= 0 or wave.ndim < 1:
        raise ValueError('The selected soundtrack is invalid.')
    target = max(9, 1 + 8 * ((count + 6) // 8))
    if count < target:
        images = torch.cat((images, images[-1:].expand(target-count, -1, -1, -1)), dim=0)
    samples = round(target / float(fps) * rate)
    if wave.shape[-1] < samples:
        wave = F.pad(wave, (0, samples - wave.shape[-1]))
    else:
        wave = wave[..., :samples]
    return images, {**audio, 'waveform': wave}, count


class ZuraOutpaintSelectClip:
    """Prepare a bounded source interval at the video's exact rational frame rate."""
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'video': ('VIDEO',), 'start_seconds': ('FLOAT', {'default': 0, 'min': 0, 'max': 86400}),
            'duration_seconds': ('FLOAT', {'default': 1, 'min': .001, 'max': 120}),
            'long_edge': ('INT', {'default': 1920, 'min': 256, 'max': 1920}),
            'fps_num': ('INT', {'default': 24, 'min': 1, 'max': 120000}),
            'fps_den': ('INT', {'default': 1, 'min': 1, 'max': 100000}),
            'expected_frames': ('INT', {'default': 24, 'min': 1, 'max': MAX_FRAMES})}}
    RETURN_TYPES = ('VIDEO',)
    FUNCTION = 'select'
    CATEGORY = 'Zura/Artist Studio'

    def select(self, video, start_seconds, duration_seconds, long_edge, fps_num, fps_den, expected_frames):
        import av
        from fractions import Fraction
        from . import source_path, root, ffmpeg, digest_file
        from comfy_api.latest import InputImpl
        fps = Fraction(fps_num, fps_den)
        if not 1 <= fps <= 120 or not 1 <= expected_frames <= MAX_FRAMES:
            raise ValueError('Choose a valid source rate and frame selection.')
        source = source_path(video)
        with av.open(str(source)) as container:
            stream = container.streams.video[0]
            actual = Fraction(stream.average_rate or stream.base_rate or 0)
            if actual != fps:
                raise ValueError('The source frame rate changed. Review the selection again.')
            width, height = stream.width, stream.height
            has_audio = bool(container.streams.audio)
        scale = min(1., long_edge / max(width, height))
        width, height = (max(2, round(side * scale / 2) * 2) for side in (width, height))
        values = [digest_file(source), start_seconds, duration_seconds, long_edge, fps_num, fps_den, expected_frames, 'native-outpaint-v1']
        identity = hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()[:24]
        folder = root() / 'clips';folder.mkdir(exist_ok=True)
        target = folder / ('outpaint-' + identity + '.mp4')
        if not target.exists():
            second = [] if has_audio else ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
            ffmpeg('-ss', start_seconds, '-i', source, *second, '-t', float(expected_frames / fps),
                '-map', '0:v:0', '-map', '0:a:0' if has_audio else '1:a:0',
                '-vf', f'setpts=PTS-STARTPTS,fps={fps},scale={width}:{height}:flags=lanczos,tpad=stop_mode=clone:stop=2',
                '-frames:v', expected_frames, '-c:v', 'libx264', '-crf', 16, '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '256k', '-af', 'apad', '-movflags', '+faststart', target)
        with av.open(str(target)) as prepared:
            stream = prepared.streams.video[0]
            count = stream.frames or sum(1 for _ in prepared.decode(video=0))
            if count != expected_frames or Fraction(stream.average_rate or 0) != fps:
                target.unlink(missing_ok=True)
                raise ValueError('The prepared clip does not match the source frame rate and selected frame count.')
        return (InputImpl.VideoFromFile(str(target)),)


class ZuraOutpaintExactVideo:
    """Create output VIDEO with the source's exact rational cadence."""
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images': ('IMAGE',),
            'fps_num': ('INT', {'default': 24, 'min': 1, 'max': 120000}),
            'fps_den': ('INT', {'default': 1, 'min': 1, 'max': 100000})},
            'optional': {'audio': ('AUDIO',)}}
    RETURN_TYPES = ('VIDEO',)
    FUNCTION = 'make'
    CATEGORY = 'Zura/Artist Studio'
    def make(self, images, fps_num, fps_den, audio=None):
        from fractions import Fraction
        from comfy_api.latest import InputImpl, Types
        fps = Fraction(fps_num, fps_den)
        if not 1 <= fps <= 120:
            raise ValueError('Choose a valid output frame rate.')
        return (InputImpl.VideoFromComponents(Types.VideoComponents(images=images, audio=audio, frame_rate=fps),
                    bit_depth=8, color_space='sRGB'),)


class ZuraOutpaintTemporalHold:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images': ('IMAGE',), 'audio': ('AUDIO',),
                'expected_frames': ('INT', {'default': 48, 'min': 1, 'max': MAX_FRAMES})},
                'optional': {'fps': ('FLOAT', {'default': 24.0, 'min': 1.0, 'max': 120.0})}}
    RETURN_TYPES = ('IMAGE', 'AUDIO', 'INT')
    RETURN_NAMES = ('padded_frames', 'padded_audio', 'original_frames')
    FUNCTION = 'hold'
    CATEGORY = 'Zura/Artist Studio'
    def hold(self, images, audio, expected_frames, fps=FPS):
        return hold_video_audio(images, audio, expected_frames, fps)


class ZuraOutpaintReviewOverlay:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images': ('IMAGE',), 'mask': ('MASK',)}}
    RETURN_TYPES = ('IMAGE',)
    FUNCTION = 'make'
    CATEGORY = 'Zura/Artist Studio'
    def make(self, images, mask):
        if images.ndim != 4 or mask.ndim != 3 or images.shape[:3] != mask.shape:
            raise ValueError('The outpaint selection does not match the source frames.')
        amount = mask.clamp(0, 1).unsqueeze(-1) * 0.48
        tint = images.new_tensor((1.0, 0.42, 0.18)).reshape(1, 1, 1, 3)
        return (images * (1 - amount) + tint * amount,)


def build_review_graph(source, selection, *, output_prefix, check_asset=lambda asset: None):
    """Render the exact per-frame generation mask before allowing sampling."""
    expected = plan(source, start=selection['start'], duration=selection.get('requested_duration', selection['duration']), mode=selection['mode'],
                    width=selection['width'], height=selection['height'], left=selection['left'],
                    top=selection['top'], right=selection['right'], bottom=selection['bottom'],
                    black_threshold=selection['black_threshold'], allow_partial_end=True, ae_frame_contract=selection.get('ae_frame_contract'))
    if expected['review_key'] != selection.get('review_key'):
        raise ValueError('The source or canvas changed. Create a fresh selection preview.')
    if not re.fullmatch(r'genj/outpaint/[a-zA-Z0-9_-]{1,96}', str(output_prefix)):
        raise ValueError('Choose a safe preview destination.')
    check_asset(source)
    graph = {
        'source': {'class_type': 'LoadVideo', 'inputs': {'file': source['file']}},
        'source_range': {'class_type': 'ZuraOutpaintSelectClip', 'inputs': {'video': ['source', 0],
            'start_seconds': expected['start'], 'duration_seconds': expected['requested_duration'], 'long_edge': 1920, 'fps_num': expected['fps_num'], 'fps_den': expected['fps_den'], 'expected_frames': expected['frames']}},
        'components': {'class_type': 'GetVideoComponents', 'inputs': {'video': ['source_range', 0]}},
        'canvas': {'class_type': 'ZuraLTXOutpaintCanvas', 'inputs': {'images': ['components', 0],
            **{k: expected[k] for k in ('mode', 'left', 'top', 'right', 'bottom', 'black_threshold')},
            'width': expected['padded_width'], 'height': expected['padded_height']}},
        'overlay': {'class_type': 'ZuraOutpaintReviewOverlay', 'inputs': {'images': ['canvas', 0], 'mask': ['canvas', 1]}},
        'video': {'class_type': 'ZuraOutpaintExactVideo', 'inputs': {'images': ['overlay', 0],
            'fps_num': expected['fps_num'], 'fps_den': expected['fps_den']}},
        'save': {'class_type': 'SaveVideo', 'inputs': {'video': ['video', 0], 'filename_prefix': output_prefix,
            'format': 'mp4', 'format.codec': 'h264'}},
    }
    if expected['mode'] == 'black':
        graph['unpad_review'] = {'class_type': 'ImageCrop', 'inputs': {'image': ['overlay', 0],
            'width': expected['width'], 'height': expected['height'], 'x': 0, 'y': 0}}
        graph['video']['inputs']['images'] = ['unpad_review', 0]
    return graph


def build_studio_graph(source, selection, *, review_key, prompt='', seed=42, output_prefix, check_asset=lambda asset: None, pad_delivery=False, masked_black=False):
    """Use the user-approved LTX 2.5 black-guide recipe after mask review."""
    if not isinstance(selection, dict) or review_key != selection.get('review_key') or not re.fullmatch(r'[a-f0-9]{64}', str(review_key)):
        raise ValueError('Review and approve the current outpaint selection first.')
    expected = plan(source, start=selection['start'], duration=selection.get('requested_duration', selection['duration']), mode=selection['mode'],
                    width=selection['width'], height=selection['height'], left=selection['left'],
                    top=selection['top'], right=selection['right'], bottom=selection['bottom'],
                    black_threshold=selection['black_threshold'], allow_partial_end=True, ae_frame_contract=selection.get('ae_frame_contract'))
    if expected['review_key'] != review_key:
        raise ValueError('The source or canvas changed. Review the selection again.')
    if expected.get('ae_frame_contract') is not None:
        pad_delivery=False
    if not re.fullmatch(r'genj/outpaint/[a-zA-Z0-9_-]{1,96}', str(output_prefix)):
        raise ValueError('Choose a safe outpaint output destination.')
    check_asset(source)
    if masked_black and expected['mode'] == 'black':
        if expected.get('ae_frame_contract') is not None and source_rate(source)!=24:
            raise ValueError('This masked black-area recipe requires 24 fps. Use the source-cadence outpaint recipe for this AE clip.')
        # A black guide on its own can be interpreted as a permanent letterbox.
        # For explicitly selected black areas, use the separately tested native
        # in/outpainting guide so the reviewed mask reaches the sampler.
        from .ltx_outpaint import build_test_graph
        g = build_test_graph(source['file'], output_prefix, expected['padded_frames'], FPS,
            expected['padded_width'], expected['padded_height'], mode='black',
            prompt=prompt, seed=seed, black_threshold=expected['black_threshold'])
        g['source_range'] = {'class_type': 'GenjSelectClip', 'inputs': {
            'video': ['source', 0], 'start_seconds': expected['start'],
            'duration_seconds': expected['requested_duration'], 'long_edge': 1920, 'round_up': True}}
        g['components']['inputs']['video'] = ['source_range', 0]
        g['temporal_hold'] = {'class_type': 'ZuraOutpaintTemporalHold', 'inputs': {
            'images': ['components', 0], 'audio': ['components', 1], 'expected_frames': expected['frames']}}
        g['canvas']['inputs']['images'] = ['temporal_hold', 0]
        g['audio_encoded']['inputs']['audio'] = ['temporal_hold', 1]
        g['trim_result'] = {'class_type': 'ImageFromBatch', 'inputs': {
            'image': ['blend_high', 0], 'batch_index': 0, 'length': expected['frames']}}
        g['unpad_result'] = {'class_type': 'ImageCrop', 'inputs': {'image': ['trim_result', 0],
            'width': expected['width'], 'height': expected['height'], 'x': 0, 'y': 0}}
        g['assemble']['inputs'].update(images=['unpad_result', 0], audio=['components', 1])
        if expected.get('ae_frame_contract') is not None:
            from ..comfylink.frame_contract import prepare_frame_contract_graph
            return prepare_frame_contract_graph(g,expected['ae_frame_contract'],'outpaint')
        return pad_outpaint_delivery(g) if pad_delivery else g
    def n(kind, **inputs): return {'class_type': kind, 'inputs': inputs}
    g = {
        'source': n('LoadVideo', file=source['file']),
        'components': n('GetVideoComponents', video=['source_range', 0]),
        'canvas': n('ZuraLTXOutpaintCanvas', images=['temporal_hold', 0], mode=expected['mode'],
                    width=expected['padded_width'], height=expected['padded_height'],
                    left=expected['left'], top=expected['top'], right=expected['right'], bottom=expected['bottom'],
                    black_threshold=expected['black_threshold']),
        'encoder': n('CLIPLoader', clip_name='gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors', type='ltxv', device='default'),
        'positive': n('CLIPTextEncode', clip=['encoder', 0], text=str(prompt)),
        'negative': n('CLIPTextEncode', clip=['encoder', 0], text='pc game, console game, video game, cartoon, childish, ugly'),
        'conditioning': n('LTXVConditioning', positive=['positive', 0], negative=['negative', 0], frame_rate=float(source_rate(source))),
        'video_vae': n('VAELoader', vae_name='ltx-2.5-video-vae-conv-bf16.safetensors'),
        'audio_vae': n('VAELoader', vae_name='ltx-2.5-audio-vae-bf16.safetensors'),
        'model': n('UNETLoader', unet_name='ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors', weight_dtype='default'),
        'adapter': n('LTXICLoRALoaderModelOnly', model=['model', 0], lora_name='ltx-2.3-22b-ic-lora-outpaint.safetensors', strength_model=1.0),
        'empty': n('EmptyLTXVLatentVideo', width=expected['padded_width'], height=expected['padded_height'], length=expected['padded_frames'], batch_size=1),
        'guide': n('LTXAddVideoICLoRAGuide', positive=['conditioning', 0], negative=['conditioning', 1], vae=['video_vae', 0], latent=['empty', 0], image=['canvas', 0],
                   frame_idx=0, strength=1.0, latent_downscale_factor=['adapter', 1], crop='disabled', use_tiled_encode=False, tile_size=256, tile_overlap=64),
        'audio_empty': n('LTXVEmptyLatentAudio', frames_number=expected['padded_frames'], frame_rate=float(source_rate(source)), batch_size=1, audio_vae=['audio_vae', 0]),
        'av': n('LTXVConcatAVLatent', video_latent=['guide', 2], audio_latent=['audio_empty', 0]),
        'guider': n('CFGGuider', model=['adapter', 0], positive=['guide', 0], negative=['guide', 1], cfg=1.0),
        'noise': n('RandomNoise', noise_seed=int(seed)),
        'sampler': n('KSamplerSelect', sampler_name='euler_ancestral_cfg_pp'),
        'sigmas': n('ManualSigmas', sigmas='1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0'),
        'sample': n('SamplerCustomAdvanced', noise=['noise', 0], guider=['guider', 0], sampler=['sampler', 0], sigmas=['sigmas', 0], latent_image=['av', 0]),
        'split': n('LTXVSeparateAVLatent', av_latent=['sample', 0]),
        'crop_guides': n('LTXVCropGuides', positive=['guide', 0], negative=['guide', 1], latent=['split', 0]),
        'decode': n('VAEDecodeTiled', samples=['crop_guides', 2], vae=['video_vae', 0], tile_size=512, overlap=64, temporal_size=128, temporal_overlap=32),
        'assemble': n('ZuraOutpaintExactVideo', images=['trim_result', 0], fps_num=expected['fps_num'], fps_den=expected['fps_den'], audio=['components', 1]),
        'save': n('SaveVideo', video=['assemble', 0], filename_prefix=output_prefix, format='mp4', **{'format.codec':'h264', 'format.codec.encoding':'re-encode', 'format.codec.encoding.crf':16.0}),
    }
    g['source_range'] = {'class_type': 'ZuraOutpaintSelectClip', 'inputs': {
        'video': ['source', 0], 'start_seconds': expected['start'],
        'duration_seconds': expected['requested_duration'], 'long_edge': 1920, 'fps_num': expected['fps_num'], 'fps_den': expected['fps_den'], 'expected_frames': expected['frames']}}
    g['components']['inputs']['video'] = ['source_range', 0]
    g['temporal_hold'] = {'class_type': 'ZuraOutpaintTemporalHold', 'inputs': {
        'images': ['components', 0], 'audio': ['components', 1], 'expected_frames': expected['frames'], 'fps': float(source_rate(source))}}
    g['canvas']['inputs']['images'] = ['temporal_hold', 0]
    g['trim_result'] = {'class_type': 'ImageFromBatch', 'inputs': {
        'image': ['decode', 0], 'batch_index': 0, 'length': expected['frames']}}
    g['assemble']['inputs']['images'] = ['trim_result', 0]
    if source.get('has_audio') is False:
        g['assemble']['inputs'].pop('audio', None)
    if expected['mode'] == 'black':
        g['unpad_result'] = {'class_type': 'ImageCrop', 'inputs': {'image': ['trim_result', 0],
            'width': expected['width'], 'height': expected['height'], 'x': 0, 'y': 0}}
        g['assemble']['inputs']['images'] = ['unpad_result', 0]
    if expected.get('ae_frame_contract') is not None:
        from ..comfylink.frame_contract import prepare_frame_contract_graph
        return prepare_frame_contract_graph(g,expected['ae_frame_contract'],'outpaint')
    return pad_outpaint_delivery(g) if pad_delivery else g


def pad_outpaint_delivery(graph):
    """Hold the final generated image to LTX's next 8n+1 frame count."""
    graph['hold_delivery'] = {'class_type': 'GenjHoldToModelLength', 'inputs': {
        'images': graph['assemble']['inputs']['images'], 'stride': 8}}
    graph['assemble']['inputs']['images'] = ['hold_delivery', 0]
    if 'audio' in graph['assemble']['inputs']:
        graph['assemble']['inputs']['audio'] = ['temporal_hold', 1]
    return graph


NODE_CLASS_MAPPINGS = {'ZuraOutpaintExactVideo': ZuraOutpaintExactVideo, 'ZuraOutpaintSelectClip': ZuraOutpaintSelectClip, 'ZuraOutpaintTemporalHold': ZuraOutpaintTemporalHold,
                       'ZuraOutpaintReviewOverlay': ZuraOutpaintReviewOverlay}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraOutpaintExactVideo': 'Zura · Outpaint Video at Source Rate', 'ZuraOutpaintSelectClip': 'Zura · Select Outpaint Source', 'ZuraOutpaintTemporalHold': 'Zura · Hold Outpaint End Frame',
                              'ZuraOutpaintReviewOverlay': 'Zura · Review Outpaint Selection'}
