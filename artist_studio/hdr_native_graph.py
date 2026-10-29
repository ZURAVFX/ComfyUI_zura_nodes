"""Experimental native EXR-to-HDR tiled-fusion recipe. Not yet a Studio route.

Based on Lightricks' 2.5 V2V_TiledFusion_HDR_to_HDR example. Unlike the example
(which repeats one still), this accepts an 8n+1 sequence using the official EXR
loader. The official Refine Details adapter is a candidate replacement for the
example's locally named general-refine adapter; equivalent quality is unproven.
"""
from __future__ import annotations

import math
from .hdr_delivery import ltx_hdr_delivery

REFINER = 'ltx-2.5-22b-ic-lora-refine-details-1.0.safetensors'
STAGE1 = '1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0'
STAGE2 = '0.909375, 0.725, 0.421875, 0.0'


def build_native_exr_graph(*, source, frame_count, fps, width, height, prefix,
                           prompt='The same scene, preserve the motion and HDR lighting.',
                           stage2_prompt='Natural lighting, fine detail, clean edges.',
                           source_colour='acescg', seed=42, output='hlg_and_exr',
                           model='ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors',
                           video_vae='ltx-2.5-video-vae-bf16.safetensors',
                           text_encoder='gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors',
                           upscaler='ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors'):
    if not isinstance(source,str) or not source.strip(): raise ValueError('Choose an EXR sequence.')
    if type(frame_count) is not int or not 9 <= frame_count <= 121 or (frame_count-1)%8:
        raise ValueError('Experimental native HDR input requires 9–121 frames in 8n+1 increments.')
    if any(type(v) is not int or v < 512 or v > 2048 or v % 64 for v in (width,height)):
        raise ValueError('Choose output dimensions between 512 and 2048 pixels, multiples of 64.')
    if not isinstance(fps,(int,float)) or isinstance(fps,bool) or not math.isfinite(fps) or not 1<=fps<=120:
        raise ValueError('Choose a valid frame rate.')
    if source_colour not in ('acescg','acescct','srgb_linear'):
        raise ValueError('Choose the EXR source colour space.')
    def n(kind, **inputs): return {'class_type':kind,'inputs':inputs}
    g={
        'source':n('LTXVLoadEXRSequence',path=source,color_space=source_colour,frame_rate=float(fps),frame_start=0,frame_cap=frame_count,trim_to_8k1=True),
        'model':n('UNETLoader',unet_name=model,weight_dtype='default'),
        'lora':n('LTXICLoRALoaderModelOnly',model=['model',0],lora_name=REFINER,strength_model=1.),
        'vae_load':n('VAELoader',vae_name=video_vae),
        'vae':n('LTXVVAEForceFloat32',vae=['vae_load',0]),
        'text':n('CLIPLoader',clip_name=text_encoder,type='ltxv',device='default'),
        'positive':n('CLIPTextEncode',clip=['text',0],text=prompt),
        'negative':n('CLIPTextEncode',clip=['text',0],text=''),
        'positive2':n('CLIPTextEncode',clip=['text',0],text=stage2_prompt),
        'condition':n('LTXVConditioning',positive=['positive',0],negative=['negative',0],frame_rate=float(fps)),
        'condition2':n('LTXVConditioning',positive=['positive2',0],negative=['negative',0],frame_rate=float(fps)),
        'resize1':n('ImageScale',image=['source',0],upscale_method='bilinear',width=width//2,height=height//2,crop='disabled'),
        'empty':n('EmptyLTXVLatentVideo',width=width//2,height=height//2,length=frame_count,batch_size=1),
        'guide1':n('LTXAddVideoICLoRAGuide',positive=['condition',0],negative=['condition',1],vae=['vae',0],latent=['empty',0],image=['resize1',0],frame_idx=0,strength=1.,latent_downscale_factor=['lora',1],crop='disabled',use_tiled_encode=False,tile_size=256,tile_overlap=64,use_streaming=True,tile_frames=frame_count),
        'sampler':n('KSamplerSelect',sampler_name='euler'),
        'sigmas1':n('ManualSigmas',sigmas=STAGE1),
        'sigmas2':n('ManualSigmas',sigmas=STAGE2),
        'sample1':n('LTXVTiledFusionSampler',model=['lora',0],positive=['guide1',0],negative=['guide1',1],latents=['guide1',2],sigmas=['sigmas1',0],sampler=['sampler',0],vae=['vae',0],seed=seed,cfg=1.,tile_width=1024,tile_height=576,overlap_frac=.5,blend_var=.05,grid_cycle=1,tile_frames=frame_count,canvas_device='auto'),
        'upscale_model':n('LatentUpscaleModelLoader',model_name=upscaler),
        'upsample':n('LTXVLatentUpsampler',samples=['sample1',0],upscale_model=['upscale_model',0],vae=['vae',0]),
        'resize2':n('ImageScale',image=['source',0],upscale_method='bilinear',width=width,height=height,crop='disabled'),
        'guide2':n('LTXAddVideoICLoRAGuide',positive=['condition2',0],negative=['condition2',1],vae=['vae',0],latent=['upsample',0],image=['resize2',0],frame_idx=0,strength=1.,latent_downscale_factor=['lora',1],crop='disabled',use_tiled_encode=False,tile_size=256,tile_overlap=64,use_streaming=True,tile_frames=frame_count),
        'sample2':n('LTXVTiledFusionSampler',model=['lora',0],positive=['guide2',0],negative=['guide2',1],latents=['guide2',2],sigmas=['sigmas2',0],sampler=['sampler',0],vae=['vae',0],seed=seed,cfg=1.,tile_width=1024,tile_height=576,overlap_frac=.5,blend_var=.05,grid_cycle=1,tile_frames=frame_count,canvas_device='auto'),
        'decode':n('VAEDecodeTiled',samples=['sample2',0],vae=['vae',0],tile_size=512,overlap=64,temporal_size=128,temporal_overlap=32),
    }
    g.update(ltx_hdr_delivery(['decode',0],fps,output=output,prefix=prefix,working_space='ltx25_acescct_qualified'))
    return g
