"""Experimental last-frame conditioning for sequential LTX outpaint.

The generated anchor is inserted into the video latent before the independent
source-video IC guide. It does not replace the source guide or reviewed mask.
"""
from __future__ import annotations

import copy
from pathlib import Path


def extract_frame(video_path, output_path, frame_index):
    """Save an exact decoded frame without retaining the complete video."""
    import av
    video_path, output_path = Path(video_path), Path(output_path)
    if type(frame_index) is not int or frame_index < 0:
        raise ValueError('Choose a valid anchor frame index.')
    selected = None
    with av.open(str(video_path)) as container:
        for index, frame in enumerate(container.decode(video=0)):
            if index == frame_index:
                selected = frame
                break
    if selected is None:
        raise ValueError('The previous outpaint window does not contain the anchor frame.')
    with output_path.open('xb') as target:
        selected.to_image().save(target, format='PNG')
    return output_path


def attach_first_frame(graph, relative_image, strength=1.0):
    """Attach an aligned I2V frame to the existing source-guided graph."""
    if not isinstance(relative_image, str) or not relative_image or '\\' in relative_image:
        raise ValueError('Choose a valid generated anchor frame.')
    path = Path(relative_image)
    if path.is_absolute() or any(part in ('', '.', '..') for part in path.parts):
        raise ValueError('Choose a valid generated anchor frame.')
    result = copy.deepcopy(graph)
    if result.get('guide', {}).get('inputs', {}).get('latent') != ['empty', 0]:
        raise ValueError('This outpaint graph cannot accept a first-frame anchor.')
    if result.get('guide', {}).get('class_type') not in ('LTXAddVideoICLoRAGuide', 'LTXAddVideoICLoRAGuideAdvanced'):
        raise ValueError('This outpaint graph does not expose a supported LTX source guide.')
    if any(key in result for key in ('zura_anchor_image', 'zura_anchor_i2v')):
        raise ValueError('An anchor is already attached.')
    result['zura_anchor_image'] = {'class_type':'LoadImage', 'inputs':{'image':relative_image}}
    result['zura_anchor_i2v'] = {'class_type':'LTXVImgToVideoInplace', 'inputs':{
        'vae':['video_vae',0], 'image':['zura_anchor_image',0], 'latent':['empty',0],
        'strength':float(strength), 'bypass':False}}
    result['guide']['inputs']['latent'] = ['zura_anchor_i2v', 0]
    if 'av_high' in result:
        if result['av_high'].get('inputs', {}).get('video_latent') != ['encode_high', 0]:
            raise ValueError('This outpaint refinement graph cannot accept a first-frame anchor.')
        result['zura_anchor_i2v_high'] = {'class_type':'LTXVImgToVideoInplace', 'inputs':{
            'vae':['video_vae',0], 'image':['zura_anchor_image',0], 'latent':['encode_high',0],
            'strength':float(strength), 'bypass':False}}
        result['av_high']['inputs']['video_latent'] = ['zura_anchor_i2v_high', 0]
    return result
