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


def fit_opening_edit_canvas(graph, width, height):
    """Put every source-preserving opening-edit input on one working raster.

    The image model sees a grid-aligned source image.  Its reference images,
    mask used during sampling, and mask used for the preview composite must
    use that exact same raster.  Keep the original mask chain intact for the
    final inverse registration: it is the authoritative source-coordinate
    selection after the decoded image has been stretched back to the source.
    """
    def fit(image):
        return {'class_type': 'ImageScale', 'inputs': {'image': image,
            'upscale_method': 'lanczos', 'width': width, 'height': height,
            'crop': 'disabled'}}

    graph['92:111'] = fit(['125', 0])
    if 'zura_look_source' in graph:
        graph['zura_look_source']['inputs']['image'] = ['92:111', 0]

    fitted_masks = {}
    def working_mask(mask, name):
        key = tuple(mask) if isinstance(mask, list) else mask
        if key in fitted_masks:
            return fitted_masks[key]
        image = f'zura_opening_{name}_mask_image'
        scaled = f'zura_opening_{name}_mask_working_image'
        result = f'zura_opening_{name}_mask_working'
        graph[image] = {'class_type': 'MaskToImage', 'inputs': {'mask': mask}}
        graph[scaled] = fit([image, 0])
        graph[result] = {'class_type': 'ImageToMask', 'inputs': {
            'image': [scaled, 0], 'channel': 'red'}}
        fitted_masks[key] = [result, 0]
        return fitted_masks[key]

    # Final working-canvas composite and the sampling latent can originate
    # from different reviewed masks.  Register both explicitly, without
    # altering either original-coordinate source node.
    composite = graph.get('zura_masked_look', {}).get('inputs')
    if composite and composite.get('mask'):
        composite['mask'] = working_mask(composite['mask'], 'inside')
    latent = graph.get('zura_opening_latent_mask', {}).get('inputs')
    if latent and latent.get('mask'):
        latent['mask'] = working_mask(latent['mask'], 'sampling')


# Kept as a narrow compatibility alias for third-party graphs that imported
# the original helper while it was Qwen-only.  New Studio graphs use the
# model-neutral function above.
def fit_qwen_edit_canvas(graph, width, height):
    return fit_opening_edit_canvas(graph, width, height)


def restore_source_size(graph):
    generated = graph['122']['inputs']['images']
    graph['zura_opening_original_resolution'] = {'class_type': 'ImageScale', 'inputs': {
        'image': generated, 'upscale_method': 'lanczos', 'crop': 'disabled',
        'width': ['zura_original_size', 0], 'height': ['zura_original_size', 1]}}
    graph['122']['inputs']['images'] = ['zura_opening_original_resolution', 0]
    # Preserve the actual source pixels outside a reviewed mask even when the
    # selected image model uses a latent format that cannot be noise-masked.
    if 'zura_masked_look' in graph and 'zura_look_inside_mask' in graph:
        mask = ['zura_look_inside_mask',0]
        if graph.get('92:111',{}).get('class_type') == 'ImageScale':
            # Apply the identical inverse raster to the mask before
            # compositing onto the untouched original.
            graph['zura_opening_original_mask_image_source'] = {'class_type':'MaskToImage','inputs':{'mask':mask}}
            graph['zura_opening_original_mask_image'] = {'class_type':'ImageScale','inputs':{
                'image':['zura_opening_original_mask_image_source',0],'upscale_method':'lanczos','crop':'disabled',
                'width':['zura_original_size',0],'height':['zura_original_size',1]}}
            graph['zura_opening_original_mask'] = {'class_type':'ImageToMask','inputs':{
                'image':['zura_opening_original_mask_image',0],'channel':'red'}}
            mask = ['zura_opening_original_mask',0]
        graph['zura_opening_preserve_source'] = {'class_type': 'ImageCompositeMasked', 'inputs': {
            'destination': ['125', 0], 'source': ['zura_opening_original_resolution', 0],
            'mask': mask, 'x': 0, 'y': 0, 'resize_source': False}}
        graph['122']['inputs']['images'] = ['zura_opening_preserve_source', 0]
