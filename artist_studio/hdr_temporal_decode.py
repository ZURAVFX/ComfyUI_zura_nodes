"""Private temporal VAE cut experiment; not registered in Studio."""
from __future__ import annotations

import torch


class ZuraHDRTemporalDecodeCut:
    """Decode bounded overlapping latent windows, choosing one image per frame.

    Comfy's native tiled VAE averages decoded overlaps, which can double moving
    detail. This experiment chooses a single tile at each overlap midpoint.
    The result may instead show a jump and requires visual/HDR validation.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'samples':('LATENT',),'vae':('VAE',),
            'temporal_size':('INT',{'default':64,'min':16,'max':128,'step':8}),
            'temporal_overlap':('INT',{'default':16,'min':8,'max':64,'step':8}),
            'tile_size':('INT',{'default':512,'min':64,'max':2048,'step':32}),
            'spatial_overlap':('INT',{'default':64,'min':0,'max':512,'step':32})}}
    RETURN_TYPES=('IMAGE',)
    OUTPUT_NODE=False
    FUNCTION='decode'
    CATEGORY='Zura/Experimental HDR'

    def decode(self,samples,vae,temporal_size,temporal_overlap,tile_size,spatial_overlap):
        latent=samples['samples']
        if not isinstance(latent,torch.Tensor) or latent.ndim!=5 or latent.shape[0]!=1:
            raise ValueError('Expected one video latent.')
        compression=vae.temporal_compression_decode()
        if type(compression) is not int or compression<1:
            raise ValueError('This experiment requires a video VAE.')
        if any(type(v) is not int for v in (temporal_size,temporal_overlap,tile_size,spatial_overlap)):
            raise ValueError('Choose whole-number tile sizes.')
        if temporal_size%compression or temporal_overlap%compression or not 0<temporal_overlap<temporal_size:
            raise ValueError('Temporal sizes must be multiples of VAE compression and overlap must be smaller than the tile.')
        window=temporal_size//compression;overlap=temporal_overlap//compression
        count=latent.shape[2]
        starts=list(range(0,max(count-overlap,1),window-overlap))
        chunks=[]
        spatial=vae.spacial_compression_decode()
        if type(spatial) is not int or spatial<1:raise ValueError('Invalid VAE spatial compression.')
        for start in starts:
            video=vae.decode_tiled(latent[:,:,start:min(start+window,count)],tile_x=max(1,tile_size//spatial),
                                   tile_y=max(1,tile_size//spatial),overlap=spatial_overlap//spatial)
            if video.ndim==5:video=video.reshape(-1,video.shape[-3],video.shape[-2],video.shape[-1])
            if video.ndim!=4 or video.shape[-1]!=3:raise ValueError('The VAE returned invalid video frames.')
            chunks.append((start*compression,video.cpu()))
        output=[]
        for i,(start,frames) in enumerate(chunks):
            left=0 if i==0 else (chunks[i-1][0]+len(chunks[i-1][1])-start)//2
            right=len(frames) if i==len(chunks)-1 else (chunks[i+1][0]+len(frames)-start)//2
            if not 0<=left<right<=len(frames):raise ValueError('Invalid VAE tile overlap.')
            output.append(frames[left:right])
        result=torch.cat(output)
        expected=(count-1)*compression+1
        if len(result)!=expected:raise ValueError(f'VAE tiles returned {len(result)} frames, expected {expected}.')
        return (result,)


NODE_CLASS_MAPPINGS={'ZuraHDRTemporalDecodeCut':ZuraHDRTemporalDecodeCut}
NODE_DISPLAY_NAME_MAPPINGS={'ZuraHDRTemporalDecodeCut':'Zura · HDR Temporal Decode Cut (Experimental)'}
