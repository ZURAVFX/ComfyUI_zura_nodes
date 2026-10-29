"""Bounded, reversible frame padding for an LTX 2.5 HDR guide."""
from __future__ import annotations

import math
import torch
import torch.nn.functional as F


def pad_sdr_guide(images, frame_limit=121):
    """Pad right/bottom reflectively, hold the final frame to 8n+1.

    Return the padded batch and exact original W, H and frame count. Cropping
    back after inference is mandatory. Refuse long batches instead of silently
    consuming unbounded VRAM or truncating the artist's video.
    """
    if not isinstance(images, torch.Tensor) or images.ndim != 4 or images.shape[-1] != 3:
        raise ValueError('Expected RGB video frames.')
    if not images.is_floating_point() or not bool(torch.isfinite(images).all()):
        raise ValueError('Expected finite floating-point sRGB video frames.')
    count,height,width,_ = images.shape
    if count < 1 or count > frame_limit:
        raise ValueError(f'This HDR test supports 1–{frame_limit} source frames per render.')
    if height < 32 or width < 32 or height > 4096 or width > 4096:
        raise ValueError('Source dimensions must be between 32 and 4096 pixels.')
    if bool((images < 0).any()) or bool((images > 1).any()):
        raise ValueError('SDR-to-HDR input must be normalised sRGB in the range 0–1.')
    # LTX's official workflow reflect-pads edges and repeats the last frame.
    right=(-width)%32; bottom=(-height)%32
    if right or bottom:
        images=F.pad(images.permute(0,3,1,2),(0,right,0,bottom),mode='reflect').permute(0,2,3,1)
    target=max(9,1+8*((max(1,count)-1+7)//8))
    if count < target:
        images=torch.cat((images,images[-1:].expand(target-count,-1,-1,-1)),dim=0)
    return images,width,height,count,width+right,height+bottom,target


class ZuraLTXHDRPrepare:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'images':('IMAGE',)}}
    RETURN_TYPES=('IMAGE','INT','INT','INT','INT','INT','INT')
    RETURN_NAMES=('padded_frames','original_width','original_height','original_frames','padded_width','padded_height','padded_count')
    FUNCTION='prepare'
    CATEGORY='Zura/Artist Studio'
    def prepare(self,images):return pad_sdr_guide(images)


class ZuraHDRTrimAudio:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'audio':('AUDIO',),'frames':('INT',{'min':1}),
                            'fps':('FLOAT',{'default':24.0,'min':1.0,'max':120.0})},
                'optional':{'start_frame':('INT',{'default':0,'min':0})}}
    RETURN_TYPES=('AUDIO',)
    FUNCTION='trim'
    CATEGORY='Zura/Artist Studio'
    def trim(self,audio,frames,fps,start_frame=0):
        if not isinstance(audio,dict) or not isinstance(audio.get('waveform'),torch.Tensor):
            raise ValueError('Audio waveform is unavailable.')
        waveform=audio['waveform'];rate=audio.get('sample_rate')
        if type(frames) is not int or frames<1 or type(start_frame) is not int or start_frame<0 or not isinstance(fps,(int,float)) or not math.isfinite(fps) or fps<=0 or type(rate) is not int or rate<=0:
            raise ValueError('Audio trimming needs a valid frame rate and sample rate.')
        start=round(start_frame/fps*rate);end=round((start_frame+frames)/fps*rate)
        if waveform.ndim<1 or waveform.shape[-1]<end:
            raise ValueError('The source audio is shorter than the selected video.')
        return ({**audio,'waveform':waveform[..., start:end]},)


NODE_CLASS_MAPPINGS={'ZuraLTXHDRPrepare':ZuraLTXHDRPrepare,'ZuraHDRTrimAudio':ZuraHDRTrimAudio}
NODE_DISPLAY_NAME_MAPPINGS={'ZuraLTXHDRPrepare':'Zura · Prepare SDR for LTX HDR','ZuraHDRTrimAudio':'Zura · Trim HDR source audio'}
