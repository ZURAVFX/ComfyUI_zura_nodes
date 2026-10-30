"""Experimental native HDR tiled-fusion recipes used by Studio's preview.

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


def build_native_video_graph(*, source, start_frame, frame_count, fps, width, height,
                             prefix, colour_space='auto', has_audio=False, output='hlg_and_exr',
                             sequence_manifest='', manifest_sha='', temporal_window=0):
    """Bounded HDR-video post-pass, padded for LTX then cropped to source raster.

    This preserves frame count and source soundtrack; the model may alter scene
    appearance and movement. The caller must validate real HDR colour metadata.
    """
    if type(temporal_window) is not int or (temporal_window and (not 9 <= temporal_window <= 121 or (temporal_window-1)%8)):
        raise ValueError('The experimental HDR temporal window must be 8n+1 and at most 121 frames.')
    limit=257 if temporal_window else 121
    if type(start_frame) is not int or start_frame < 0 or type(frame_count) is not int or not 1 <= frame_count <= limit:
        raise ValueError(f'Choose a valid range of up to {limit} frames.')
    if temporal_window and (has_audio or output != 'hlg_video'):
        raise ValueError('Long temporal HDR is experimental and currently supports silent HLG video only.')
    if any(type(v) is not int or v < 32 or v > 2048 or v % 2 for v in (width,height)):
        raise ValueError('Choose an even-sized HDR source between 32 and 2048 pixels per side.')
    if width*height*frame_count > 40_000_000:
        raise ValueError('This range is too large; choose fewer frames.')
    choices = ('auto','acescg','acescct','linear_rec709') if sequence_manifest else ('auto','hlg_rec2020','pq_rec2020')
    if colour_space not in choices:
        raise ValueError('Choose a supported source colour space.')
    if sequence_manifest and (not manifest_sha or has_audio):
        raise ValueError('The EXR sequence must have a verified manifest and no source audio.')
    pw=max(512,math.ceil(width/64)*64);ph=max(512,math.ceil(height/64)*64)
    padded=max(9,1+8*((frame_count-1+7)//8))
    if pw*ph*padded > 40_000_000:
        raise ValueError('This padded range is too large; choose fewer frames.')
    # Keep the public graph's validation unchanged. The internal temporal test
    # constructs a valid short graph then expands its *single* latent canvas.
    g=build_native_exr_graph(source=source,frame_count=min(padded,121),fps=fps,width=pw,height=ph,prefix=prefix,output=output)
    if temporal_window:
        g['empty']['inputs']['length']=padded
        for name in ('guide1','guide2','sample1','sample2'):
            g[name]['inputs']['tile_frames']=temporal_window
        for name in ('sample1','sample2'):
            g[name]['inputs']['canvas_device']='cpu'
    def n(kind, **inputs):return {'class_type':kind,'inputs':inputs}
    g['source']=n('ZuraHDRLoadNativeSourceLong' if temporal_window else 'ZuraHDRLoadNativeSource',source=source,start_frame=start_frame,frame_count=frame_count,
                  colour_space=colour_space,sequence_fps=float(fps))
    if sequence_manifest:
        g['source']['inputs'].update(manifest=sequence_manifest,manifest_sha=manifest_sha)
    g['native_pad']=n('ZuraHDRNativePrepareLong' if temporal_window else 'ZuraHDRNativePrepare',images=['source',0])
    g['resize1']['inputs']['image']=['native_pad',0]
    g['resize2']['inputs']['image']=['native_pad',0]
    g['trim_frames']=n('ImageFromBatch',image=['decode',0],batch_index=0,length=frame_count)
    g['trim_raster']=n('ImageCrop',image=['trim_frames',0],width=width,height=height,x=0,y=0)
    # Rebuild delivery against cropped ACEScct, never the padded canvas.
    for key in list(g):
        if key.startswith('zura_hdr_'):del g[key]
    audio=None
    if has_audio:
        g['native_audio']=n('ZuraHDRLoadAudioRange',source=source,start_frame=start_frame,frame_count=frame_count,fps=float(fps))
        audio=['native_audio',0]
    g.update(ltx_hdr_delivery(['trim_raster',0],fps,output=output,prefix=prefix,
                              working_space='ltx25_acescct_qualified',audio=audio))
    if output in ('acescg_exr','hlg_and_exr'):
        g['zura_hdr_archive']=n('ZuraHDRPackageACEScct',images=['trim_raster',0],prefix=prefix)
        preview=['zura_hdr_exr',0]
    else:
        g['zura_hdr_preview_tonemap']=n('LTXVHDRDecodePostprocess',image=['trim_raster',0],transfer='acescct',save_exr=False,
            exr_color_space='acescg',output_dir='genj/hdr/'+prefix,filename_prefix='frame',half_precision=True)
        preview=['zura_hdr_preview_tonemap',0]
    video={'images':preview,'fps':float(fps)}
    if audio:video['audio']=audio
    g['zura_hdr_preview_video']=n('CreateVideo',**video)
    g['zura_hdr_save_preview']=n('ZuraHDRSaveExactRate',video=['zura_hdr_preview_video',0],filename_prefix='genj/hdr/'+prefix+'_preview',fps=float(fps))
    return g
