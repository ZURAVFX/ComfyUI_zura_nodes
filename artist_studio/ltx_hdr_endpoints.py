"""Native HDR first/last conditioning following LTX 2.5's two-stage I2V example.

Studio exposes this builder only through the opt-in native EXR endpoint preview.
The caller resolves uploaded assets; no arbitrary-path HTTP interface lives here.
"""
from __future__ import annotations

import math
import re

from .hdr_delivery import DISTILLED_SIGMAS, ltx_hdr_delivery

MODEL = 'ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors'
TEXT = 'gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors'
VIDEO_VAE = 'ltx-2.5-video-vae-bf16.safetensors'
AUDIO_VAE = 'ltx-2.5-audio-vae-bf16.safetensors'
UPSCALER = 'ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors'
MAX_PIXEL_FRAMES = 40_000_000


def endpoint_source(asset):
    """Describe a caller-verified single EXR endpoint, never an SDR thumbnail."""
    if not isinstance(asset, dict) or not asset.get('manifest') or not re.fullmatch(r'[a-f0-9]{64}', asset.get('sha', '')):
        raise ValueError('Choose a verified EXR endpoint.')
    colour = asset.get('colour_space', 'auto')
    if colour not in ('auto', 'acescg', 'acescct', 'linear_rec709'):
        raise ValueError('Choose the EXR colour space.')
    return {'class_type': 'ZuraHDRLoadNativeSource', 'inputs': {
        'source': '', 'start_frame': 0, 'frame_count': 1, 'sequence_fps': 24.,
        'manifest': str(asset['manifest']), 'manifest_sha': asset['sha'], 'colour_space': colour}}


def build_native_endpoint_graph(*, first, last=None, width, height, frames, prompt,
                                seed=42, output='hlg_and_exr', prefix, audio_file=None,
                                audio_start=0.):
    if any(type(v) is not int or not 512 <= v <= 2048 or v % 64 for v in (width, height)):
        raise ValueError('Native HDR endpoints need 512–2048 pixels per side on a 64-pixel grid.')
    if type(frames) is not int or not 9 <= frames <= 361 or (frames-1) % 8:
        raise ValueError('Native HDR endpoints need 8n+1 frames, from 9 to 361.')
    if width * height * frames > MAX_PIXEL_FRAMES:
        raise ValueError('This native HDR selection exceeds the software memory budget. Reduce resolution or length.')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
        raise ValueError('Describe the video to generate.')
    if type(seed) is not int or not 0 <= seed <= 2**53-1:
        raise ValueError('Choose a valid seed.')
    if isinstance(audio_start, bool) or not isinstance(audio_start, (int, float)) or not math.isfinite(audio_start) or audio_start < 0:
        raise ValueError('Choose a non-negative audio start.')
    if audio_file is not None and (not isinstance(audio_file, str) or not audio_file.strip()):
        raise ValueError('Choose a valid audio reference.')
    def n(kind, **inputs): return {'class_type': kind, 'inputs': inputs}
    g = {
        'first': endpoint_source(first),
        'model': n('UNETLoader', unet_name=MODEL, weight_dtype='default'),
        'attention': n('ModelAttentionBackend', model=['model', 0], attention='comfy kitchen attention'),
        'text': n('CLIPLoader', clip_name=TEXT, type='ltxv', device='default'),
        'positive': n('CLIPTextEncode', clip=['text', 0], text=prompt),
        'negative': n('CLIPTextEncode', clip=['text', 0], text=''),
        'condition': n('LTXVConditioning', positive=['positive', 0], negative=['negative', 0], frame_rate=24.),
        'vae_load': n('VAELoader', vae_name=VIDEO_VAE),
        'vae': n('LTXVVAEForceFloat32', vae=['vae_load', 0]),
        'audio_vae': n('VAELoader', vae_name=AUDIO_VAE),
        'empty_video': n('EmptyLTXVLatentVideo', width=width//2, height=height//2, length=frames, batch_size=1),
        'sampler': n('KSamplerSelect', sampler_name='euler_ancestral'),
        'sigmas1': n('ManualSigmas', sigmas=DISTILLED_SIGMAS),
        'sigmas2': n('ManualSigmas', sigmas='0.909375,0.725,0.421875,0.0'),
        'noise': n('RandomNoise', noise_seed=seed),
        'upscale_model': n('LatentUpscaleModelLoader', model_name=UPSCALER),
    }
    if last is not None: g['last'] = endpoint_source(last)
    if audio_file:
        g['audio_ref'] = n('LoadAudio', audio=audio_file)
        g['audio_window'] = n('TrimAudioDuration', audio=['audio_ref', 0], start_index=float(audio_start), duration=frames/24.)
        g['audio_silence'] = n('EmptyAudio', duration=frames/24., sample_rate=48000, channels=2)
        g['audio_padded'] = n('AudioConcat', audio1=['audio_window', 0], audio2=['audio_silence', 0], direction='after')
        g['trim_audio'] = n('TrimAudioDuration', audio=['audio_padded', 0], start_index=0., duration=frames/24.)
        g['encode_audio'] = n('LTXVAudioVAEEncode', audio=['trim_audio', 0], audio_vae=['audio_vae', 0])
        g['audio_mask'] = n('SolidMask', value=0., width=1024, height=1024)
        g['frozen_audio'] = n('SetLatentNoiseMask', samples=['encode_audio', 0], mask=['audio_mask', 0])
        audio = ['frozen_audio', 0]
    else:
        g['empty_audio'] = n('LTXVEmptyLatentAudio', audio_vae=['audio_vae', 0], frames_number=frames, frame_rate=24., batch_size=1)
        audio = ['empty_audio', 0]
    latent = ['empty_video', 0]
    for stage, w, h in ((1, width//2, height//2), (2, width, height)):
        suffix = str(stage)
        positive, negative = ['condition', 0], ['condition', 1]
        g['fit_first'+suffix] = n('ImageScale', image=['first', 0], upscale_method='bilinear', width=w, height=h, crop='center')
        g['anchor_first'+suffix] = n('LTXVImgToVideoInplace', vae=['vae', 0], image=['fit_first'+suffix, 0], latent=latent, strength=1., bypass=False)
        latent = ['anchor_first'+suffix, 0]
        if last is not None:
            g['fit_last'+suffix] = n('ImageScale', image=['last', 0], upscale_method='bilinear', width=w, height=h, crop='center')
            g['anchor_last'+suffix] = n('LTXVAddGuide', positive=positive, negative=negative, vae=['vae', 0], latent=latent,
                image=['fit_last'+suffix, 0], frame_idx=frames-1, strength=1.)
            positive, negative, latent = ['anchor_last'+suffix, 0], ['anchor_last'+suffix, 1], ['anchor_last'+suffix, 2]
        g['av'+suffix] = n('LTXVConcatAVLatent', video_latent=latent, audio_latent=audio)
        g['guider'+suffix] = n('CFGGuider', model=['attention', 0], positive=positive, negative=negative, cfg=1.)
        g['sample'+suffix] = n('SamplerCustomAdvanced', noise=['noise', 0], guider=['guider'+suffix, 0], sampler=['sampler', 0], sigmas=['sigmas'+suffix, 0], latent_image=['av'+suffix, 0])
        g['separate'+suffix] = n('LTXVSeparateAVLatent', av_latent=['sample'+suffix, 0])
        g['crop'+suffix] = n('LTXVCropGuides', positive=positive, negative=negative, latent=['separate'+suffix, 0])
        if stage == 1:
            g['upsample'] = n('LTXVLatentUpsampler', samples=['crop1', 2], upscale_model=['upscale_model', 0], vae=['vae', 0])
            latent = ['upsample', 0]
            if not audio_file: audio = ['separate1', 1]
    g['decode'] = n('VAEDecodeTiled', samples=['crop2', 2], vae=['vae', 0], tile_size=512, overlap=64, temporal_size=64, temporal_overlap=8)
    if audio_file: delivered_audio = ['trim_audio', 0]
    else:
        g['decode_audio'] = n('LTXVAudioVAEDecode', samples=['separate2', 1], audio_vae=['audio_vae', 0])
        # The audio latent's native duration can be a few samples shorter than
        # the video. Preserve its contents and pad only that tail with silence.
        g['audio_duration'] = n('GenjPadAudioToFrames', audio=['decode_audio', 0], frames=frames, fps=24.)
        delivered_audio = ['audio_duration', 0]
    g.update(ltx_hdr_delivery(['decode', 0], 24., output=output, prefix=prefix,
        working_space='ltx25_acescct_qualified', audio=delivered_audio))
    if output in ('acescg_exr', 'hlg_and_exr'):
        g['zura_hdr_archive'] = n('ZuraHDRPackageACEScct', images=['decode', 0], prefix=prefix)
        preview = ['zura_hdr_exr', 0]
    else:
        g['tonemap'] = n('LTXVHDRDecodePostprocess', image=['decode', 0], transfer='acescct', save_exr=False,
            exr_color_space='acescg', output_dir='genj/hdr/'+prefix, filename_prefix='frame', half_precision=True)
        preview = ['tonemap', 0]
    g['preview_video'] = n('CreateVideo', images=preview, audio=delivered_audio, fps=24.)
    g['save_preview'] = n('ZuraHDRSaveExactRate', video=['preview_video', 0], filename_prefix='genj/hdr/'+prefix+'_preview', fps=24.)
    titles = {'first': 'Read HDR first frame', 'last': 'Read HDR last frame',
              'model': 'Load LTX 2.5 INT8', 'text': 'Load Gemma4 INT8',
              'vae_load': 'Load full HDR video VAE', 'vae': 'Prepare float32 HDR VAE',
              'sample1': 'Generate HDR video: pass 1 of 2',
              'upsample': 'Upscale HDR latent', 'sample2': 'Refine HDR video: pass 2 of 2',
              'decode': 'Decode HDR video', 'decode_audio': 'Decode soundtrack',
              'audio_duration': 'Align soundtrack length',
              'zura_hdr_save_video': 'Save 10-bit HLG video',
              'zura_hdr_archive': 'Package ACEScg EXR frames', 'save_preview': 'Save SDR viewing preview'}
    for key, title in titles.items():
        if key in g: g[key]['_meta'] = {'title': title}
    return g
