"""First-frame/timing adapter only. Ripple inference stays in native LTX nodes."""
import torch


class ZuraRippleGuide:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'plate': ('ZURA_PLATE',), 'anchors': ('ZURA_ANCHORS',)}}

    RETURN_TYPES = ('IMAGE', 'INT')
    RETURN_NAMES = ('guide_frames', 'inference_frames')
    FUNCTION = 'prepare'
    CATEGORY = 'Zura/Object replacement'

    def prepare(self, plate, anchors):
        if plate.get('processing') != 'SDR (sRGB)' or plate.get('space') in ('hlg_rec2020', 'pq_rec2020', 'acescg', 'acescct', 'linear_rec709', 'pq_display_p3'):
            raise ValueError('Ripple object replacement currently supports SDR footage only.')
        if len(anchors) != 1 or anchors[0][0] != 0:
            raise ValueError('Ripple needs exactly one replacement image at the first selected source frame.')
        images = plate['_work_images']
        first = anchors[0][1]
        if images.ndim != 4 or first.shape != images[:1].shape:
            raise ValueError('The replacement image must match the prepared source frame dimensions.')
        if len(images) % 8 != 1 or len(images) < plate['count'] or len(images) > 985:
            raise ValueError('Source frames must be padded upwards to the LTX 8n+1 frame count.')
        # Author's prepend convention, with enough held tail to retain EVERY source
        # frame. The graph removes the first decoded frame before original-fps save.
        guide = torch.cat([first.to(images), images, images[-1:].expand(7, -1, -1, -1)])
        return guide, len(guide)


NODE_CLASS_MAPPINGS = {'ZuraRippleGuide': ZuraRippleGuide}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraRippleGuide': 'Ripple · Prepare First-Frame Guide'}
