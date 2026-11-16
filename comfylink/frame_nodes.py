"""Tensor-only exact delivery guard. No colour or alpha conversions."""
from __future__ import annotations


class ZuraComfyLinkMatchFrames:
    CATEGORY = 'Zura/ComfyLink'
    FUNCTION = 'match'
    RETURN_TYPES = ('IMAGE', 'MASK', 'STRING')
    RETURN_NAMES = ('images', 'mask', 'metadata')

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images': ('IMAGE',),
            'frame_count': ('INT', {'default': 1, 'min': 1, 'max': 1000000}),
            'width': ('INT', {'default': 1, 'min': 1, 'max': 65536}),
            'height': ('INT', {'default': 1, 'min': 1, 'max': 65536})},
            'optional': {'mask': ('MASK',), 'metadata': ('STRING', {'default': ''})}}

    def match(self, images, frame_count, width, height, mask=None, metadata=''):
        import torch
        if not isinstance(images, torch.Tensor) or images.ndim != 4 or not images.is_floating_point():
            raise ValueError('Exact AE delivery requires a native IMAGE tensor batch.')
        if type(frame_count) is not int or frame_count < 1:
            raise ValueError('Exact AE delivery needs a positive frame count.')
        if tuple(images.shape[1:3]) != (height, width):
            raise ValueError('Generated dimensions do not match the AE source layer. Use the AE source dimensions for this mode.')
        if len(images) < frame_count:
            raise ValueError(f'The model returned {len(images)} frames; AE requires {frame_count}. Missing frames cannot be repeated or invented.')
        if mask is not None:
            if not isinstance(mask, torch.Tensor) or mask.ndim != 3 or tuple(mask.shape[1:]) != (height, width) or len(mask) < frame_count:
                raise ValueError('The generated alpha/mask batch does not match the AE frame contract.')
            mask = mask[:frame_count]
        return images[:frame_count], mask, metadata


class ZuraComfyLinkRateAudio:
    CATEGORY='Zura/ComfyLink'
    FUNCTION='reinterpret'
    RETURN_TYPES=('AUDIO',)
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'audio':('AUDIO',),'speed':('FLOAT',{'default':1,'min':.01,'max':240})}}
    def reinterpret(self,audio,speed=1):
        import numpy as np
        import torch
        import subprocess,shutil
        from .studio_rate import tempo_filter
        if audio is None or abs(speed-1)<1e-9:return (audio,)
        executable=shutil.which('ffmpeg')
        if not executable:raise ValueError('FFmpeg is required to restore the audio clock.')
        waves=audio['waveform'];rate=audio['sample_rate'];result=[]
        for wave in waves:
            samples=wave.detach().cpu().float().numpy().T.copy()
            command=[executable,'-v','error','-f','f32le','-ar',str(rate),'-ac',str(wave.shape[0]),'-i','pipe:0',
                '-af',tempo_filter(speed),'-f','f32le','-acodec','pcm_f32le','pipe:1']
            changed=subprocess.run(command,input=samples.tobytes(),capture_output=True,timeout=120)
            if changed.returncode:raise ValueError('The source audio clock could not be restored.')
            output=np.frombuffer(changed.stdout,dtype=np.float32).reshape(-1,wave.shape[0]).T.copy()
            result.append(torch.from_numpy(output).to(device=waves.device,dtype=waves.dtype))
        length=min(w.shape[-1] for w in result)
        return ({**audio,'waveform':torch.stack([w[...,:length] for w in result])},)
