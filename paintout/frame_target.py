"""Ground a named removal inside the artist's painted search area."""
import base64
import io
import numpy as np
import torch
from PIL import Image
from .paintout import CATEGORY, resize
from .frame_editor import effective_edit_mask, erased_reference


def _resize_mask(mask, height, width):
    return resize(torch.from_numpy(np.asarray(mask, dtype=np.float32))[None, :, :, None], height, width, 'nearest-exact')[0, :, :, 0].numpy()


def _model_mask(mask, patch):
    x, y, width, height = patch['rect']
    rh, rw = patch['resized']
    return _resize_mask(mask[y:y+height, x:x+width], rh, rw)


def refine_target(patch, image, masks, target):
    target = str(target).strip()
    if not target:
        raise ValueError('Name the subject to remove.')
    values = masks.detach().float().cpu().numpy() if isinstance(masks, torch.Tensor) else np.asarray(masks)
    rh, rw = patch['resized']
    if values.ndim != 3 or values.shape[1:] != (rh, rw) or not np.isfinite(values).all():
        raise ValueError('Subject detection returned an invalid mask. Try selecting the subject again.')
    raw = _model_mask(patch['mask'], patch) > .001
    allowed = _model_mask(effective_edit_mask(patch['mask'], patch['grow'], patch['feather'], patch.get('protection')), patch) > .001
    protected = patch.get('model_protection')
    candidates = [value > .5 for value in values if np.any((value > .5) & raw & allowed)]
    if not candidates:
        raise ValueError(f'Could not find {target} inside the painted area. Paint over that subject or use a clearer subject name.')
    if len(candidates) != 1:
        raise ValueError(f'Found more than one {target} inside the painted area. Tighten the painted area to choose one subject.')
    selected = candidates[0] & allowed
    if protected is not None:
        selected &= np.asarray(protected) <= .001
    if not selected.any():
        raise ValueError('The detected subject is outside the editable area or is protected.')
    refined = dict(patch)
    x, y, width, height = patch['rect']
    processing_mask = np.zeros_like(patch['mask'], dtype=np.float32)
    processing_mask[y:y+height, x:x+width] = _resize_mask(selected, height, width)
    processing_mask *= effective_edit_mask(patch['mask'], patch['grow'], patch['feather'], patch.get('protection')) > .001
    refined.update(mask=processing_mask, grow=0, feather=0, target_name=target)
    if patch.get('delivery_mask') is not None:
        dh, dw = patch['delivery_mask'].shape
        delivery = _resize_mask(processing_mask, dh, dw)
        delivery *= effective_edit_mask(patch['delivery_mask'], patch['delivery_grow'], patch['delivery_feather'], patch.get('delivery_protection')) > .001
        refined.update(delivery_mask=delivery, delivery_grow=0, delivery_feather=0)
    else:
        delivery = processing_mask
    if not delivery.any():
        raise ValueError('The detected subject is too small at the current edit resolution. Use a larger crop size.')
    stream = io.BytesIO()
    Image.fromarray((delivery > .001).astype(np.uint8)*255).save(stream, format='PNG')
    refined['target_mask'] = 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode('ascii')
    matte = torch.from_numpy(selected.astype(np.float32))[None]
    return erased_reference(image, matte, protected), refined


class ZuraPaintoutFrameTarget:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'patch': ('ZURA_FRAME_PATCH',), 'image': ('IMAGE',), 'masks': ('MASK',), 'target': ('STRING', {'default': ''})}}
    RETURN_TYPES = ('IMAGE', 'ZURA_FRAME_PATCH')
    RETURN_NAMES = ('erased_reference', 'refined_patch')
    FUNCTION = 'select'
    CATEGORY = CATEGORY

    def select(self, patch, image, masks, target):
        return refine_target(patch, image, masks, target)


NODE_CLASS_MAPPINGS = {'ZuraPaintoutFrameTarget': ZuraPaintoutFrameTarget}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraPaintoutFrameTarget': 'Select Named Frame Removal'}


class ZuraPaintoutTargetConditioning:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'conditioning': ('CONDITIONING',)}}
    RETURN_TYPES = ('CONDITIONING',)
    FUNCTION = 'prepare'
    CATEGORY = CATEGORY

    def prepare(self, conditioning):
        from .editor_store import _sam_subject_conditioning
        return (_sam_subject_conditioning(conditioning),)


NODE_CLASS_MAPPINGS['ZuraPaintoutTargetConditioning'] = ZuraPaintoutTargetConditioning
NODE_DISPLAY_NAME_MAPPINGS['ZuraPaintoutTargetConditioning'] = 'Detect Separate Named Subjects'
