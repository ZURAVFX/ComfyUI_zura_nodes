"""Bounded LTX outpaint graph adapter. Not exposed as a Studio workflow yet.

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


def plan(source, *, start, duration, mode, width, height, left=0, top=0,
         right=0, bottom=0, black_threshold=2 / 255, allow_partial_end=False):
    """Validate a 24-fps short source range and bind its geometry to review."""
    if not isinstance(source, dict) or not source.get('sha') or not source.get('file'):
        raise ValueError('Select a source video first.')
    if isinstance(start, bool) or isinstance(duration, bool):
        raise ValueError('Choose a valid start and duration.')
    start, duration = float(start), float(duration)
    if not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration <= 0:
        raise ValueError('Choose a valid start and duration.')
    frames = math.ceil(duration * FPS - 1e-6)
    # GenjSelectClip requires a duration of at least 0.1 seconds. At 24 fps,
    # three frames are the first valid duration (2 / 24 is too short).
    if not 3 <= frames <= MAX_FRAMES:
        raise ValueError('Choose between 3 frames and five seconds at 24 fps.')
    available = float(source.get('duration', 0))
    if not math.isfinite(available) or available <= 0 or start + duration > available + (1 / FPS if allow_partial_end else 0) + 1e-4:
        raise ValueError('The selection extends past the source video.')
    if mode not in ('expand', 'black'):
        raise ValueError('Choose canvas expansion or black areas.')
    if any(type(x) is not int for x in (width, height, left, top, right, bottom)):
        raise ValueError('Use whole-pixel canvas dimensions and margins.')
    if min(width, height) < 128 or max(width, height) > 1920 or (mode == 'expand' and (width % 64 or height % 64)):
        raise ValueError('Choose dimensions from 128 to 1920; expanded canvases use steps of 64 pixels.')
    padded_width, padded_height = (width + 63) // 64 * 64, (height + 63) // 64 * 64
    if padded_width * padded_height > 2_100_000:
        raise ValueError('This preview supports up to approximately 2 megapixels.')
    if min(left, top, right, bottom) < 0 or left + right >= width or top + bottom >= height:
        raise ValueError('The canvas margins leave no room for the source.')
    if not math.isfinite(float(black_threshold)) or not 0 <= float(black_threshold) <= .1:
        raise ValueError('Black threshold must be between 0 and 0.1.')
    if mode == 'black' and (int(source.get('width', 0)), int(source.get('height', 0))) != (width, height):
        raise ValueError('Use source dimensions for a black-padded clip.')
    if mode == 'black' and (width % 2 or height % 2):
        raise ValueError('MP4 export needs even dimensions. Add a one-pixel border to the source and try again.')
    if mode == 'black' and any((left, top, right, bottom)):
        raise ValueError('Margins apply to canvas expansion, not a black-padded clip.')
    values = {'source_sha': str(source['sha']), 'start': start, 'frames': frames, 'requested_duration': duration,
              'mode': mode, 'width': width, 'height': height,
              'left': left, 'top': top, 'right': right, 'bottom': bottom,
              'black_threshold': float(black_threshold)}
    key = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {**values, 'duration': frames / FPS, 'padded_frames': max(9, 1 + 8 * ((frames + 6) // 8)),
            'padded_width': padded_width, 'padded_height': padded_height, 'review_key': key}


def hold_video_audio(images, audio, expected_frames, fps=FPS):
    """Pad the selected clip only for inference; keep its original count."""
    if not isinstance(images, torch.Tensor) or images.ndim != 4 or images.shape[-1] != 3:
        raise ValueError('Expected selected RGB video frames.')
    count = len(images)
    if type(expected_frames) is not int or count != expected_frames or not 1 <= count <= MAX_FRAMES:
        raise ValueError('The selected video frame count changed. Select the range again.')
    if fps != FPS or not isinstance(audio, dict) or not isinstance(audio.get('waveform'), torch.Tensor):
        raise ValueError('This outpaint preview needs a 24 fps video with audio or silent audio.')
    wave, rate = audio['waveform'], audio.get('sample_rate')
    if type(rate) is not int or rate <= 0 or wave.ndim < 1:
        raise ValueError('The selected soundtrack is invalid.')
    target = max(9, 1 + 8 * ((count + 6) // 8))
    if count < target:
        images = torch.cat((images, images[-1:].expand(target-count, -1, -1, -1)), dim=0)
    samples = round(target / FPS * rate)
    if wave.shape[-1] < samples:
        wave = F.pad(wave, (0, samples - wave.shape[-1]))
    else:
        wave = wave[..., :samples]
    return images, {**audio, 'waveform': wave}, count


class ZuraOutpaintTemporalHold:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images': ('IMAGE',), 'audio': ('AUDIO',),
                'expected_frames': ('INT', {'default': 48, 'min': 1, 'max': MAX_FRAMES})}}
    RETURN_TYPES = ('IMAGE', 'AUDIO', 'INT')
    RETURN_NAMES = ('padded_frames', 'padded_audio', 'original_frames')
    FUNCTION = 'hold'
    CATEGORY = 'Zura/Artist Studio'
    def hold(self, images, audio, expected_frames):
        return hold_video_audio(images, audio, expected_frames)


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
                    black_threshold=selection['black_threshold'], allow_partial_end=True)
    if expected['review_key'] != selection.get('review_key'):
        raise ValueError('The source or canvas changed. Create a fresh selection preview.')
    if not re.fullmatch(r'genj/outpaint/[a-zA-Z0-9_-]{1,96}', str(output_prefix)):
        raise ValueError('Choose a safe preview destination.')
    check_asset(source)
    graph = {
        'source': {'class_type': 'LoadVideo', 'inputs': {'file': source['file']}},
        'source_range': {'class_type': 'GenjSelectClip', 'inputs': {'video': ['source', 0],
            'start_seconds': expected['start'], 'duration_seconds': expected['requested_duration'], 'long_edge': 1920, 'round_up': True}},
        'components': {'class_type': 'GetVideoComponents', 'inputs': {'video': ['source_range', 0]}},
        'canvas': {'class_type': 'ZuraLTXOutpaintCanvas', 'inputs': {'images': ['components', 0],
            **{k: expected[k] for k in ('mode', 'left', 'top', 'right', 'bottom', 'black_threshold')},
            'width': expected['padded_width'], 'height': expected['padded_height']}},
        'overlay': {'class_type': 'ZuraOutpaintReviewOverlay', 'inputs': {'images': ['canvas', 0], 'mask': ['canvas', 1]}},
        'video': {'class_type': 'CreateVideo', 'inputs': {'images': ['overlay', 0], 'fps': FPS,
            'bit_depth': 8, 'color_space': 'sRGB', 'codec': 'none'}},
        'save': {'class_type': 'SaveVideo', 'inputs': {'video': ['video', 0], 'filename_prefix': output_prefix,
            'format': 'mp4', 'format.codec': 'h264'}},
    }
    if expected['mode'] == 'black':
        graph['unpad_review'] = {'class_type': 'ImageCrop', 'inputs': {'image': ['overlay', 0],
            'width': expected['width'], 'height': expected['height'], 'x': 0, 'y': 0}}
        graph['video']['inputs']['images'] = ['unpad_review', 0]
    return graph


def build_studio_graph(source, selection, *, review_key, prompt='', seed=42, output_prefix, check_asset=lambda asset: None, pad_delivery=False):
    """Use the user-approved LTX 2.5 black-guide recipe after mask review."""
    if not isinstance(selection, dict) or review_key != selection.get('review_key') or not re.fullmatch(r'[a-f0-9]{64}', str(review_key)):
        raise ValueError('Review and approve the current outpaint selection first.')
    expected = plan(source, start=selection['start'], duration=selection.get('requested_duration', selection['duration']), mode=selection['mode'],
                    width=selection['width'], height=selection['height'], left=selection['left'],
                    top=selection['top'], right=selection['right'], bottom=selection['bottom'],
                    black_threshold=selection['black_threshold'], allow_partial_end=True)
    if expected['review_key'] != review_key:
        raise ValueError('The source or canvas changed. Review the selection again.')
    if not re.fullmatch(r'genj/outpaint/[a-zA-Z0-9_-]{1,96}', str(output_prefix)):
        raise ValueError('Choose a safe outpaint output destination.')
    check_asset(source)
    if expected['mode'] == 'black':
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
        'conditioning': n('LTXVConditioning', positive=['positive', 0], negative=['negative', 0], frame_rate=FPS),
        'video_vae': n('VAELoader', vae_name='ltx-2.5-video-vae-conv-bf16.safetensors'),
        'audio_vae': n('VAELoader', vae_name='ltx-2.5-audio-vae-bf16.safetensors'),
        'model': n('UNETLoader', unet_name='ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors', weight_dtype='default'),
        'adapter': n('LTXICLoRALoaderModelOnly', model=['model', 0], lora_name='ltx-2.3-22b-ic-lora-outpaint.safetensors', strength_model=1.0),
        'empty': n('EmptyLTXVLatentVideo', width=expected['padded_width'], height=expected['padded_height'], length=expected['padded_frames'], batch_size=1),
        'guide': n('LTXAddVideoICLoRAGuide', positive=['conditioning', 0], negative=['conditioning', 1], vae=['video_vae', 0], latent=['empty', 0], image=['canvas', 0],
                   frame_idx=0, strength=1.0, latent_downscale_factor=['adapter', 1], crop='disabled', use_tiled_encode=False, tile_size=256, tile_overlap=64),
        'audio_empty': n('LTXVEmptyLatentAudio', frames_number=expected['padded_frames'], frame_rate=FPS, batch_size=1, audio_vae=['audio_vae', 0]),
        'av': n('LTXVConcatAVLatent', video_latent=['guide', 2], audio_latent=['audio_empty', 0]),
        'guider': n('CFGGuider', model=['adapter', 0], positive=['guide', 0], negative=['guide', 1], cfg=1.0),
        'noise': n('RandomNoise', noise_seed=int(seed)),
        'sampler': n('KSamplerSelect', sampler_name='euler_ancestral_cfg_pp'),
        'sigmas': n('ManualSigmas', sigmas='1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0'),
        'sample': n('SamplerCustomAdvanced', noise=['noise', 0], guider=['guider', 0], sampler=['sampler', 0], sigmas=['sigmas', 0], latent_image=['av', 0]),
        'split': n('LTXVSeparateAVLatent', av_latent=['sample', 0]),
        'crop_guides': n('LTXVCropGuides', positive=['guide', 0], negative=['guide', 1], latent=['split', 0]),
        'decode': n('VAEDecodeTiled', samples=['crop_guides', 2], vae=['video_vae', 0], tile_size=512, overlap=64, temporal_size=128, temporal_overlap=32),
        'assemble': n('CreateVideo', images=['trim_result', 0], fps=FPS, audio=['components', 1], bit_depth=8, color_space='sRGB', codec='none'),
        'save': n('SaveVideo', video=['assemble', 0], filename_prefix=output_prefix, format='mp4', **{'format.codec':'h264', 'format.codec.encoding':'re-encode', 'format.codec.encoding.crf':16.0}),
    }
    g['source_range'] = {'class_type': 'GenjSelectClip', 'inputs': {
        'video': ['source', 0], 'start_seconds': expected['start'],
        'duration_seconds': expected['requested_duration'], 'long_edge': 1920, 'round_up': True}}
    g['components']['inputs']['video'] = ['source_range', 0]
    g['temporal_hold'] = {'class_type': 'ZuraOutpaintTemporalHold', 'inputs': {
        'images': ['components', 0], 'audio': ['components', 1], 'expected_frames': expected['frames']}}
    g['canvas']['inputs']['images'] = ['temporal_hold', 0]
    g['trim_result'] = {'class_type': 'ImageFromBatch', 'inputs': {
        'image': ['decode', 0], 'batch_index': 0, 'length': expected['frames']}}
    g['assemble']['inputs']['images'] = ['trim_result', 0]
    if expected['mode'] == 'black':
        g['unpad_result'] = {'class_type': 'ImageCrop', 'inputs': {'image': ['trim_result', 0],
            'width': expected['width'], 'height': expected['height'], 'x': 0, 'y': 0}}
        g['assemble']['inputs']['images'] = ['unpad_result', 0]
    return pad_outpaint_delivery(g) if pad_delivery else g


def pad_outpaint_delivery(graph):
    """Hold the final generated image to LTX's next 8n+1 frame count."""
    graph['hold_delivery'] = {'class_type': 'GenjHoldToModelLength', 'inputs': {
        'images': graph['assemble']['inputs']['images'], 'stride': 8}}
    graph['assemble']['inputs'].update(images=['hold_delivery', 0], audio=['temporal_hold', 1])
    return graph


NODE_CLASS_MAPPINGS = {'ZuraOutpaintTemporalHold': ZuraOutpaintTemporalHold,
                       'ZuraOutpaintReviewOverlay': ZuraOutpaintReviewOverlay}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraOutpaintTemporalHold': 'Zura · Hold Outpaint End Frame',
                              'ZuraOutpaintReviewOverlay': 'Zura · Review Outpaint Selection'}
