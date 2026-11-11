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

RECIPE_VERSION = 'temporal-scene-ltx25-v1'
GEOMETRY_MODES = ('temporal_scene',)
MODELS = {
    'geometry': ('geometry_estimation', 'depth_anything_3_base.safetensors'),
    'model': ('diffusion_models', 'ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors'),
    'crossview': ('loras', 'LTX2.3-22B_IC-LoRA-CrossView-Warp_v2_6000.safetensors'),
    'text': ('text_encoders', 'gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors'),
    'video_vae': ('vae', 'ltx-2.5-video-vae-conv-bf16.safetensors'),
    'audio_vae': ('vae', 'ltx-2.5-audio-vae-bf16.safetensors'),
    'upscaler': ('latent_upscale_models', 'ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors'),
}



def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def geometry_mode(config):
    # Old drafts migrate to the joint solve. Independent frame depth is no
    # longer a camera-mode execution path.
    return 'temporal_scene'


def stabilise_geometry(geometry, texture_images):
    """Hold one reconstructed scene and its still texture across the camera timeline."""
    if not isinstance(geometry, dict):
        raise ValueError('MoGe did not return frame geometry.')
    if len(texture_images.shape) != 4 or texture_images.shape[0] < 1 or texture_images.shape[-1] < 3:
        raise ValueError('Stable scene needs a complete IMAGE sequence.')
    frames, height, width = map(int, texture_images.shape[:3])
    points = geometry.get('points')
    depth = geometry.get('depth')
    if getattr(points, 'shape', None) is None or getattr(depth, 'shape', None) is None:
        raise ValueError('MoGe did not return full frame geometry.')
    if tuple(points.shape[:3]) != (1, height, width) or tuple(depth.shape[:3]) != (1, height, width):
        raise ValueError('The source textures do not match the selected frame geometry.')
    result = {}
    for key, value in geometry.items():
        if not hasattr(value, 'shape') or not hasattr(value, 'expand'):
            continue
        if len(value.shape) == 0 or int(value.shape[0]) != 1:
            raise ValueError('Stable scene needs geometry from exactly one frame.')
        # Expanding keeps one static storage for geometry while Panorama reads
        # the same first-frame mesh at the current source timeline frame.
        base = value.detach().cpu()
        result[key] = base.expand(frames, *base.shape[1:])
    result['image'] = texture_images[:1, ..., :3].detach().cpu().clone().expand(frames, height, width, 3)
    return result


def plan(source, config):
    contract=config.get('ae_frame_contract')
    if contract is not None:
        from ..comfylink.frame_contract import normalise_frame_contract, contract_rate
        contract=normalise_frame_contract(contract)
        if contract_rate(contract)!=24:
            raise ValueError('The native camera recipe requires 24 fps and cannot preserve this AE source cadence.')
        config={**config,'start':0,'duration':contract['frameCount']/24}
    start, seconds = float(config.get('start', 0)), float(config.get('duration', 2))
    width, height = int(config.get('width', 1920)), int(config.get('height', 1080))
    fps = float(source.get('fps') or 24)
    if not all(math.isfinite(v) for v in (start, seconds, fps)) or start < 0 or seconds <= 0 or not 1 <= fps <= 120:
        raise ValueError('Choose a valid source interval and frame rate.')
    if start + seconds > float(source['duration']) + 1e-6:
        raise ValueError('Trim inside the source video.')
    start_frame = round(start * fps)
    frames = math.ceil(seconds * fps - 1e-6)
    if not 2 <= frames <= 361 or seconds > 5:
        raise ValueError('Choose a continuous camera shot of up to 5 seconds and 361 source frames.')
    if not (256 <= width <= 4096 and 256 <= height <= 4096 and width % 8 == 0 and height % 8 == 0):
        raise ValueError('Use dimensions from 256 to 4096, in multiples of 8.')
    two_stage = bool(config.get('two_stage', False))
    grid = 128 if two_stage else 64
    rw, rh = math.ceil(width / grid) * grid, math.ceil(height / grid) * grid
    if rw * rh > 8_388_608:
        raise ValueError('Choose a camera canvas up to 8.39 MP, including model padding.')
    geometry = {'recipe': RECIPE_VERSION, 'source': source['sha'], 'start': start_frame/fps,
                'start_frame': start_frame, 'duration': frames/fps, 'frames': frames, 'fps': fps,
                'width': width, 'height': height, 'model': MODELS['geometry'][1],
                'solve_resolution': 504, 'window': 12, 'overlap': 3, 'geometry_mode': 'temporal_scene'}
    if contract is not None:
        from ..comfylink.frame_contract import validate_interval
        geometry['ae_frame_contract']=validate_interval(contract,frames=frames,fps=fps,width=width,height=height)
    return {**geometry, 'key': digest(geometry), 'padded': 8 * max(1, math.ceil((frames-1)/8)) + 1,
            'render_width': rw, 'render_height': rh, 'two_stage': two_stage}


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
             'timeline': {'fps': selection['fps'], 'length': selection['frames']}, 'stickers': []}
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
        raise ValueError('Choose scene preparation, camera preview or render.')
    g = {}
    def n(key, kind, title=None, **inputs):
        g[key] = {'class_type': kind, 'inputs': inputs, '_meta': {'title': title or key.replace('_', ' ').capitalize()}}
        return [key, 0]
    p = selection
    state = camera_state(state, p)
    def load(key, file, width=0, height=0, start=0):
        return n(key, 'VHS_LoadVideo', video=file, force_rate=0, custom_width=width, custom_height=height,
                 frame_load_cap=p['frames'], skip_first_frames=start, select_every_nth=1, format='AnimateDiff')
    def pad(key, image):
        return n(key, 'ZuraCameraPadFrames', image=image, frames=p['padded'], required_source_frames=p['frames'])
    if stage in ('geometry', 'warp'):
        if stage == 'geometry':
            images = load('source', source['file'], width=640, start=p['start_frame'])
            images = n('source_frames','ZuraCameraPadFrames',image=images,frames=p['frames'],required_source_frames=p['frames'])
            images = n('solve_raster', 'ZuraCameraPrepareViews', 'Prepare calibrated DA3 patch raster', image=images, resolution=504)
            model = n('da3', 'LoadDA3Model', 'Load shared-view scene model', model_name=MODELS['geometry'][1], weight_dtype='fp32')
            previous, start, index = None, 0, 0
            while start < p['frames']:
                end = min(p['frames'], start + p['window'])
                chunk = n('views_'+str(index), 'ImageFromBatch', image=images, batch_index=start, length=end-start)
                solved = n('solve_'+str(index), 'DA3Inference', 'Joint scene views '+str(index+1), da3_model=model, image=chunk,
                           resolution=504, resize_method='upper_bound_resize', mode='multiview',
                           **{'mode.ref_view_strategy': 'first', 'mode.pose_method': 'cam_dec'})
                inputs = {'geometry': solved, 'start_frame': start, 'lock_camera': ['solve_raster',1]}
                if previous is not None: inputs['previous'] = previous
                previous = n('align_'+str(index), 'ZuraCameraAlignViews', 'Register overlapping source cameras', **inputs)
                if end == p['frames']: break
                start = end - p['overlap']; index += 1
            world = n('scene', 'ZuraCameraBuildScene', 'Fuse persistent scenery and moving surfaces', capture=previous, cache_key=p['key'], state_json=state)
            render_state = ['scene', 1]
        else:
            world = n('cached_scene', 'ZuraCameraLoadScene', 'Reuse the shared scene', cache_key=p['key'])
            render_state = state
        n('panorama', 'PanoramaStudio', 'Camera view', world=world, background_color='#ff00ff', background_range='360',
          megapixels=p['width']*p['height']/1048576, multiple=8, state_json=render_state)
        n('save', 'SaveVideo', 'Save reviewed camera guide', video=['panorama', 3],
          filename_prefix='genj/panorama/warp_'+digest([p['key'], state])[:20], format='mp4',
          **{'format.codec':'h264','format.codec.encoding':'auto'})
        n('opening', 'SaveImage', 'New camera opening', images=['panorama',1], filename_prefix='genj/panorama/opening_'+p['key'][:20])
        if stage == 'geometry':
            original = n('source_opening', 'ImageFromBatch', image=images, batch_index=0, length=1)
            n('source_opening_save','SaveImage',images=original,filename_prefix='genj/panorama/source_'+p['key'][:20])
        return g
    if not warp:
        raise ValueError('Review a camera preview before rendering.')
    rw, rh = p['render_width'], p['render_height']
    base_w, base_h = (rw//2, rh//2) if p['two_stage'] else (rw, rh)
    source_images = load('source', source['file'], width=rw, start=p['start_frame'])
    source_images = pad('source_pad', source_images)
    warped = pad('warp_pad', load('warp', warp))
    model = n('model','UNETLoader','LTX 2.5 distilled',unet_name=MODELS['model'][1],weight_dtype='default')
    model = n('crossview','LoraLoaderModelOnly','Dual-reference camera adapter',model=model,lora_name=MODELS['crossview'][1],strength_model=1.)
    model = n('attention','ModelAttentionBackend',model=model,attention='comfy kitchen attention')
    text = n('text','CLIPLoader',clip_name=MODELS['text'][1],type='ltxv',device='default')
    vae = n('video_vae','VAELoader',vae_name=MODELS['video_vae'][1])
    audio_vae = n('audio_vae','VAELoader',vae_name=MODELS['audio_vae'][1])
    positive = n('positive','CLIPTextEncode',clip=text,text='crossview'+('. '+str(prompt).strip() if str(prompt).strip() else ''))
    negative = n('negative','CLIPTextEncode',clip=text,text='')
    n('conditioning','LTXVConditioning',positive=positive,negative=negative,frame_rate=p['fps'])
    positive, negative = ['conditioning',0], ['conditioning',1]
    latent = n('empty_video','EmptyLTXVLatentVideo',width=base_w,height=base_h,length=p['padded'],batch_size=1)
    def guide(key, pos, neg, lat, image, frame_idx=0):
        n(key,'LTXAddVideoICLoRAGuide',positive=pos,negative=neg,vae=vae,latent=lat,image=image,
          frame_idx=frame_idx,strength=1.,latent_downscale_factor=1.,crop='disabled',use_tiled_encode=True,tile_size=256,tile_overlap=64)
        return [key,0],[key,1],[key,2]
    # Training contract: warped view first, unwarped original second. Never
    # substitute the rendered proxy for the source's appearance/performance.
    positive, negative, latent = guide('warp_guide',positive,negative,latent,warped)
    positive, negative, latent = guide('source_guide',positive,negative,latent,source_images)
    if look:
        image=n('look','LoadImage',image=look)
        positive,negative,latent=guide('look_guide',positive,negative,latent,image,-1)
    audio=n('empty_audio','LTXVEmptyLatentAudio',frames_number=p['padded'],frame_rate=p['fps'],batch_size=1,audio_vae=audio_vae)
    def sample(key, pos, neg, lat, sound, sigmas):
        av=n(key+'_av','LTXVConcatAVLatent',video_latent=lat,audio_latent=sound)
        guider=n(key+'_guider','CFGGuider',model=model,positive=pos,negative=neg,cfg=1.)
        n(key,'SamplerCustomAdvanced',noise=n(key+'_noise','RandomNoise',noise_seed=int(seed)),guider=guider,
          sampler=n(key+'_sampler','KSamplerSelect',sampler_name='euler_ancestral'),
          sigmas=n(key+'_sigmas','ManualSigmas',sigmas=sigmas),latent_image=av)
        n(key+'_separate','LTXVSeparateAVLatent',av_latent=[key,0])
        n(key+'_crop','LTXVCropGuides',positive=pos,negative=neg,latent=[key+'_separate',0])
        return [key+'_crop',2],[key+'_separate',1]
    latent,audio=sample('sample',positive,negative,latent,audio,'1.0,0.99375,0.9875,0.98125,0.975,0.909375,0.725,0.421875,0.0')
    if p['two_stage']:
        latent=n('upscale','LTXVLatentUpsampler',samples=latent,vae=vae,
                 upscale_model=n('upscale_model','LatentUpscaleModelLoader',model_name=MODELS['upscaler'][1]))
        positive,negative,latent=guide('refine_source', ['sample_crop',0], ['sample_crop',1],latent,source_images)
        latent,audio=sample('refine',positive,negative,latent,audio,'0.909375,0.725,0.421875,0.0')
    decoded=n('decode','VAEDecodeTiled',samples=latent,vae=vae,tile_size=512,overlap=64,temporal_size=64,temporal_overlap=8)
    decoded=n('trim','ImageFromBatch',image=decoded,batch_index=0,length=p['frames'])
    decoded=n('restore_output','ImageScale',image=decoded,width=p['width'],height=p['height'],upscale_method='lanczos',crop='disabled')
    inputs={'images':decoded,'fps':p['fps']}
    if source.get('has_audio'):inputs['audio']=['source',2]
    video=n('video','CreateVideo',**inputs)
    n('save','SaveVideo',video=video,filename_prefix='ZURA STUDIO/camera/take',format='mp4',**{'format.codec':'h264','format.codec.encoding':'auto'})
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
        return {'required': {'geometry': ('MOGE_GEOMETRY',), 'cache_key': ('STRING',)},
                'optional': {'texture_images': ('IMAGE',)}}
    RETURN_TYPES = ('MOGE_GEOMETRY',)
    FUNCTION = 'save'
    CATEGORY = 'Zura/Camera'

    def save(self, geometry, cache_key, texture_images=None):
        import torch
        import uuid
        if texture_images is not None:
            geometry = stabilise_geometry(geometry, texture_images)
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
