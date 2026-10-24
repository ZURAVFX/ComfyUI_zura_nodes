"""Original-frame conditioning for repeatable, localised opening edits.

Only constructs native graph nodes. A generated opening is never an edit input.
"""
import re


def replacement_target(config):
    if config.get('workflow_mode') not in ('swap', 'motion') or config.get('preserve_people'):
        return None
    direction = config.get('image_prompt') or config.get('prompt') or ''
    match = re.match(r'\s*(?:replace|swap)\s+(?:the\s+)?([^\n.!?;]{1,100}?)\s+(?:with|for)\s+\S', direction, re.I)
    return match.group(1).strip() if match else None


def target_position(target):
    match = re.fullmatch(r'(centre|center|middle|left|leftmost|right|rightmost)(?:\s+(?:character|person|performer|man|woman|guy))', target or '', re.I)
    if not match:
        return 'auto'
    value = match.group(1).lower()
    return 'centre' if value in ('centre', 'center', 'middle') else 'left' if value.startswith('left') else 'right'


def bind_original_frame(graph, project):
    """Decode a short slice of the original, not a low-resolution review proxy."""
    graph['zura_original_video'] = {'class_type': 'LoadVideo', 'inputs': {'file': project['source']['file']}}
    graph['zura_original_slice'] = {'class_type': 'Video Slice', 'inputs': {
        'video': ['zura_original_video', 0], 'start_time': project['config']['start'],
        'duration': 0.1, 'strict_duration': False}}
    graph['124']['inputs']['video'] = ['zura_original_slice', 0]
    graph['zura_original_size'] = {'class_type': 'GetImageSize', 'inputs': {'image': ['125', 0]}}


def add_target_mask(graph, project):
    """A spatial single-person instruction gets a single-frame native selection.

    This is independent of the video model's full-frame conditioning interface.
    Existing manually reviewed masks continue to take precedence.
    """
    c = project['config']
    target = replacement_target(c)
    position = target_position(target)
    if (c.get('workflow_mode') != 'motion' or c.get('mask_method') != 'auto'
            or c.get('preserve_people') or not target or position == 'auto'):
        return None
    graph['zura_opening_sam'] = {'class_type': 'CheckpointLoaderSimple', 'inputs': {
        'ckpt_name': 'sam3.1_multiplex_fp16.safetensors'}}
    graph['zura_opening_person'] = {'class_type': 'CLIPTextEncode', 'inputs': {
        'text': 'person:20', 'clip': ['zura_opening_sam', 1]}}
    graph['zura_opening_detect'] = {'class_type': 'SAM3_Detect', 'inputs': {
        'model': ['zura_opening_sam', 0], 'image': ['92:111', 0],
        'conditioning': ['zura_opening_person', 0], 'threshold': 0.5,
        'refine_iterations': 2, 'individual_masks': True}}
    graph['zura_opening_choose'] = {'class_type': 'GenjChoosePerformer', 'inputs': {
        'masks': ['zura_opening_detect', 0], 'performer': -1, 'position': position}}
    graph['zura_opening_margin'] = {'class_type': 'GrowMask', 'inputs': {
        'mask': ['zura_opening_choose', 0], 'expand': c.get('margin', 20), 'tapered_corners': True}}
    return ['zura_opening_margin', 0]


def constrain_sampling(graph, mask):
    """Protect unselected pixels during diffusion, not just after generation."""
    graph['zura_opening_latent_mask'] = {'class_type': 'SetLatentNoiseMask', 'inputs': {
        'samples': ['92:127', 0], 'mask': mask}}
    graph['92:104']['inputs']['latent_image'] = ['zura_opening_latent_mask', 0]


def restore_source_size(graph):
    generated = graph['122']['inputs']['images']
    graph['zura_opening_original_resolution'] = {'class_type': 'ImageScale', 'inputs': {
        'image': generated, 'upscale_method': 'lanczos', 'crop': 'center',
        'width': ['zura_original_size', 0], 'height': ['zura_original_size', 1]}}
    graph['122']['inputs']['images'] = ['zura_opening_original_resolution', 0]
    if 'zura_opening_latent_mask' in graph:
        graph['zura_opening_preserve_source'] = {'class_type': 'ImageCompositeMasked', 'inputs': {
            'destination': ['125', 0], 'source': ['zura_opening_original_resolution', 0],
            'mask': ['zura_look_inside_mask', 0], 'x': 0, 'y': 0, 'resize_source': False}}
        graph['122']['inputs']['images'] = ['zura_opening_preserve_source', 0]
