"""Panorama full-video camera guides and the artist-approved H3 CrossView path.

Geometry is an independently cached native MoGe result. Moving a camera never
loads MoGe again. Inference remains in the upstream native nodes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path

RECIPE_VERSION = 'panorama-crossview-v1'
MODELS = {
    'geometry': ('geometry_estimation', 'moge_3_vitg_fp16.safetensors'),
    'h3': ('diffusion_models', 'minimax_h3_ref2va_pruned_int8_convrot.safetensors'),
    'turbo': ('loras', 'minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors'),
    'crossview': ('loras', 'MiniMax-H3_Ref2VA-LoRA-CrossView-Warp_v1_3500.safetensors'),
    'text': ('text_encoders', 'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors'),
    'video_vae': ('vae', 'minimax_h3_video_vae_int8_convrot.safetensors'),
    'audio_vae': ('vae', 'minimax_h3_audio_vae_fp32.safetensors'),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def plan(source, config):
    start, seconds = float(config.get('start', 0)), float(config.get('duration', 2))
    width, height = int(config.get('width', 1920)), int(config.get('height', 1080))
    if not all(math.isfinite(v) for v in (start, seconds)) or start < 0 or seconds <= 0:
        raise ValueError('Choose a valid source interval.')
    if start + seconds > float(source['duration']) + 1e-6:
        raise ValueError('Trim inside the source video.')
    frames = math.ceil(seconds * 24 - 1e-6)
    if not 5 <= frames <= 120:
        raise ValueError('Panorama camera preview supports 0.21 to 5 seconds.')
    if not source.get('has_audio'):
        raise ValueError('The approved camera recipe needs original audio. Silent-source support is not verified yet.')
    if not (256 <= width <= 3840 and 256 <= height <= 3840 and width % 8 == 0 and height % 8 == 0):
        raise ValueError('Use dimensions from 256 to 3840, in multiples of 8.')
    if width * height > 1920 * 1088:
        raise ValueError('This camera preview is verified up to 1080p. Choose a smaller output.')
    geometry = {'recipe': RECIPE_VERSION, 'source': source['sha'], 'start': start,
                'duration': seconds, 'frames': frames, 'fps': 24, 'width': width, 'height': height,
                'model': MODELS['geometry'][1], 'level': 8 if max(width, height) > 1280 else 7,
                'refine': 3, 'batch': 1, 'projection': True, 'mask': True}
    return {**geometry, 'key': digest(geometry), 'padded': 5 + 17 * max(0, math.ceil((frames - 5) / 17)),
            'render_width': math.ceil(width / 32) * 32, 'render_height': math.ceil(height / 32) * 32}


def camera_state(raw, selection):
    state = json.loads(raw) if isinstance(raw, str) else copy.deepcopy(raw)
    if not state:
        state = {'version': 2, 'camera': {'aspect': selection['width'] / selection['height'],
            'position': {'value': [0, 0, 0], 'keyframes': []},
            'rotation': {'value': {'yaw_deg': 0, 'pitch_deg': 0, 'roll_deg': 0}, 'keyframes': []},
            'fov': {'value': 85, 'keyframes': []}}}
    if not isinstance(state, dict) or state.get('version') != 2 or not isinstance(state.get('camera'), dict):
        raise ValueError('Reopen the Panorama camera editor to create a valid camera.')
    # The native editor owns camera interpolation and coordinate conventions.
    # Only camera/timeline state crosses into a camera-reshoot project.
    state = {'version': 2, 'camera': state['camera'],
             'timeline': {'fps': 24, 'length': selection['frames']}, 'stickers': []}
    state['camera']['aspect'] = selection['width'] / selection['height']
    def finite(value):
        if isinstance(value, (float, int)) and not math.isfinite(value):
            raise ValueError('Camera values must be finite.')
        if isinstance(value, dict):
            for v in value.values(): finite(v)
        if isinstance(value, list):
            for v in value: finite(v)
    finite(state)
    text = json.dumps(state, allow_nan=False)
    if len(text) > 256_000:
        raise ValueError('This camera timeline is too large.')
    return text


def build_graph(source, selection, state, stage, *, warp=None, look=None, prompt='', seed=1052):
    if stage not in ('geometry', 'warp', 'render'):
        raise ValueError('Choose geometry, camera preview or render.')
    g = {}
    def n(key, kind, title=None, **inputs):
        g[key] = {'class_type': kind, 'inputs': inputs, '_meta': {'title': title or key.replace('_', ' ').capitalize()}}
        return [key, 0]
    p = selection
    state = camera_state(state, p)
    if stage != 'warp':
        src = n('source', 'LoadVideo', 'Load source footage', file=source['file'])
        src = n('select', 'GenjSelectClip', 'Read selected interval at 24 fps', video=src,
                start_seconds=p['start'], duration_seconds=p['duration'], long_edge=1920,
                use_original_length=False, round_up=True)
        components = n('components', 'GetVideoComponents', 'Read original performance and audio', video=src)
    if stage in ('geometry', 'warp'):
        if stage == 'geometry':
            image = n('geometry_size', 'ImageScale', 'Prepare geometry raster', image=components,
                      width=p['width'], height=p['height'], upscale_method='lanczos', crop='disabled')
            model = n('moge', 'LoadMoGeModel', 'Load MoGe 3 geometry model', model_name=MODELS['geometry'][1])
            world = n('geometry', 'MoGeInference', 'Reconstruct every source frame', moge_model=model,
                      image=image, resolution_level=p['level'], batch_size=1, fov_x_degrees=0,
                      force_projection=True, apply_mask=True, refine_steps=3)
            world = n('cache_geometry', 'ZuraPanoramaSaveGeometry', 'Cache geometry for camera edits', geometry=world, cache_key=p['key'])
        else:
            world = n('cached_geometry', 'ZuraPanoramaLoadGeometry', 'Reuse prepared geometry', cache_key=p['key'])
        n('panorama', 'PanoramaStudio', 'Panorama camera editor', world=world,
          background_color='#ff00ff', background_range='360', megapixels=p['width'] * p['height'] / 1048576,
          multiple=8, state_json=state)
        n('save', 'SaveVideo', 'Save full camera warp preview', video=['panorama', 3],
          filename_prefix='genj/panorama/warp_' + digest([p['key'], state])[:20], format='mp4',
          **{'format.codec': 'h264', 'format.codec.encoding': 'auto'})
        n('opening', 'SaveImage', 'Save new-angle opening', images=['panorama', 1],
          filename_prefix='genj/panorama/opening_' + digest([p['key'], state])[:20])
        if stage == 'geometry':
            original = n('source_opening', 'ImageFromBatch', image=components, batch_index=0, length=1)
            n('source_opening_save', 'SaveImage', 'Save original identity reference', images=original,
              filename_prefix='genj/panorama/source_' + p['key'][:20])
        return g
    if not warp:
        raise ValueError('Review a camera preview before rendering.')
    rw, rh = p['render_width'], p['render_height']
    def size(key, image):
        return n(key, 'ImageScale', image=image, width=rw, height=rh, upscale_method='lanczos', crop='disabled')
    def pad(key, image):
        if p['padded'] == p['frames']: return image
        tail = n(key+'_last', 'ImageFromBatch', image=image, batch_index=p['frames']-1, length=1)
        tail = n(key+'_hold', 'RepeatImageBatch', image=tail, amount=p['padded']-p['frames'])
        return n(key, 'ImageBatch', image1=image, image2=tail)
    performance = size('performance_size', components)
    original = n('identity', 'ImageFromBatch', image=performance, batch_index=0, length=1)
    performance = pad('performance_pad', performance)
    warp_video = n('warp', 'LoadVideo', 'Load full reviewed camera warp', file=warp)
    warped = n('warp_components', 'GetVideoComponents', video=warp_video)
    warped = pad('warp_pad', size('warp_size', warped))
    model = n('model', 'UNETLoader', 'Load H3 INT8', unet_name=MODELS['h3'][1], weight_dtype='default')
    model = n('turbo', 'LoraLoaderModelOnly', 'H3 Turbo · 8 steps', model=model, lora_name=MODELS['turbo'][1], strength_model=1.)
    model = n('shift', 'MiniMaxH3SigmaShift', model=model, shift_video=12., shift_audio=3.)
    model = n('crossview', 'LoraLoaderModelOnly', 'CrossView Warp · 0.8', model=model, lora_name=MODELS['crossview'][1], strength_model=.8)
    model = n('attention', 'ModelAttentionBackend', model=model, attention='comfy kitchen attention')
    clip = n('text', 'CLIPLoader', clip_name=MODELS['text'][1], type='minimax', device='default')
    vae = n('video_vae', 'VAELoader', vae_name=MODELS['video_vae'][1])
    audio_vae = n('audio_vae', 'VAELoader', vae_name=MODELS['audio_vae'][1])
    refs = {'ref_images.ref_image_0': original}
    if look:
        look_image = size('look_size', n('look', 'LoadImage', image=look))
        refs = {'ref_images.ref_image_0': look_image, 'ref_images.ref_image_1': original}
    audio = ['components', 1]
    positive = n('references', 'MiniMaxH3ReferenceToVideo', clip=clip, vae=vae, audio_vae=audio_vae,
        width=rw, height=rh, length=p['padded'], ref_image_size='match',
        prompt='crossview. Reshoot the original performance from the camera view in the warped video guide. '
        'Keep the same person, clothing, setting, gestures and spoken timing. Fill the magenta disocclusions naturally. '
        + str(prompt).strip(), **refs, **{'ref_videos.ref_video_0': performance, 'ref_video_audios.ref_video_audio_0': audio})
    latent = ['references', 1]
    positive = n('warp_guide', 'MiniMaxH3AddGuide', 'Guide every frame with the new camera', positive=positive, latent=latent, vae=vae, image=warped, frame_idx=0)
    if look:
        positive = n('look_guide', 'MiniMaxH3AddGuide', 'Soft opening look guide', positive=positive, latent=latent, vae=vae, image=look_image, frame_idx=0)
    positive = n('audio_guide', 'MiniMaxH3AddGuide', positive=positive, latent=latent, audio_vae=audio_vae, audio=audio, frame_idx=0)
    latent = n('audio_lock', 'ZuraH3LockReferenceAudio', latent=latent, audio_vae=audio_vae, audio=audio)
    guider = n('guider', 'BasicGuider', model=model, conditioning=positive)
    noise = n('noise', 'RandomNoise', noise_seed=int(seed))
    sigmas = n('sigmas', 'BasicScheduler', model=model, scheduler='simple', steps=8, denoise=1.)
    sampler = n('sampler', 'KSamplerSelect', sampler_name='res_multistep')
    sample = n('sample', 'SamplerCustomAdvanced', 'Render new camera · 8 steps', noise=noise, guider=guider, sampler=sampler, sigmas=sigmas, latent_image=latent)
    images = n('decode', 'VAEDecode', 'Decode finished video', samples=sample, vae=vae)
    images = n('trim', 'ImageFromBatch', 'Deliver exact selected frame count', image=images, batch_index=0, length=p['frames'])
    images = n('crop', 'ImageCrop', image=images, width=p['width'], height=p['height'], x=(rw-p['width'])//2, y=(rh-p['height'])//2)
    video = n('video', 'CreateVideo', images=images, audio=audio, fps=24.)
    n('save', 'SaveVideo', 'Save finished camera take', video=video, filename_prefix='genj/panorama/take',
      format='mp4', **{'format.codec': 'h264', 'format.codec.encoding': 'auto'})
    if __package__:
        from .attention import adapt_attention
        return adapt_attention(g)
    return g


def cache_path(key):
    import folder_paths
    if not re.fullmatch('[a-f0-9]{64}', key or ''):
        raise ValueError('Prepare geometry for this source first.')
    directory = Path(folder_paths.get_output_directory()) / 'genj' / 'panorama' / 'geometry'
    directory.mkdir(parents=True, exist_ok=True)
    return directory / (key + '.pt')


class ZuraPanoramaSaveGeometry:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'geometry': ('MOGE_GEOMETRY',), 'cache_key': ('STRING',)}}
    RETURN_TYPES = ('MOGE_GEOMETRY',)
    FUNCTION = 'save'
    CATEGORY = 'Zura/Camera'

    def save(self, geometry, cache_key):
        import torch
        import uuid
        data = {k: v.detach().cpu() for k, v in geometry.items() if isinstance(v, torch.Tensor)}
        if not {'image', 'points', 'depth'} <= data.keys():
            raise ValueError('MoGe did not return full frame geometry.')
        path = cache_path(cache_key)
        temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        try:
            torch.save(data, temporary)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return (geometry,)


class ZuraPanoramaLoadGeometry:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'cache_key': ('STRING',)}}
    RETURN_TYPES = ('MOGE_GEOMETRY',)
    FUNCTION = 'load'
    CATEGORY = 'Zura/Camera'

    @classmethod
    def IS_CHANGED(cls, cache_key):
        p = cache_path(cache_key)
        return p.stat().st_mtime_ns if p.exists() else float('nan')

    def load(self, cache_key):
        import torch
        path = cache_path(cache_key)
        if not path.is_file():
            raise ValueError('Geometry cache is missing. Prepare this source again.')
        return (torch.load(path, map_location='cpu', weights_only=True),)
