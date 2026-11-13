"""Display-only SDR review of ACEScg masters; never a master conversion."""
from functools import lru_cache

import numpy as np


@lru_cache(maxsize=1)
def _rec709_processor():
    # The existing display service restricts this URI to OCIO's built-in
    # catalogue. Its ACEScg -> Rec.709 transform includes D60 -> D65 adaptation.
    from ..comfylink.display_view import _config, DEFAULT_CONFIG
    config = _config(DEFAULT_CONFIG)
    source = next((config.getColorSpace(name) for name in ('ACEScg', 'lin_ap1', 'ACES - ACEScg') if config.getColorSpace(name)), None)
    target = next((config.getColorSpace(name) for name in ('Linear Rec.709 (sRGB)', 'lin_rec709_srgb', 'Utility - Linear - sRGB') if config.getColorSpace(name)), None)
    if source is None or target is None:
        raise ValueError('The built-in OCIO configuration lacks the HDR review colour spaces')
    return config.getProcessor(source.getName(), target.getName()).getDefaultCPUProcessor()


def acescg_sdr_preview(linear):
    """Return float32 sRGB/Reinhard review pixels without modifying AP1 input."""
    rgb = np.array(linear, dtype=np.float32, order='C', copy=True)
    if rgb.ndim != 3 or rgb.shape[-1] != 3 or not rgb.size or not np.isfinite(rgb).all():
        raise ValueError('HDR review requires finite HWC ACEScg RGB pixels')
    _rec709_processor().applyRGB(rgb)
    if not np.isfinite(rgb).all():
        raise ValueError('The HDR review colour transform returned non-finite pixels')
    # Negative Rec.709 channels are out of gamut for this SDR viewing copy.
    # Clip only after conversion; AP1 values and all saved masters stay intact.
    np.maximum(rgb, 0, out=rgb)
    rgb /= 1 + rgb
    rgb = np.where(rgb <= .0031308, 12.92 * rgb, 1.055 * np.maximum(rgb, .0031308) ** (1 / 2.4) - .055)
    return np.clip(rgb, 0, 1).astype(np.float32, copy=False)


class ZuraHDRSDRPreview:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'image': ('IMAGE',)}, 'optional': {'source_space': (['acescct','acescg'], {'default':'acescct'})}}
    RETURN_TYPES = ('IMAGE',)
    RETURN_NAMES = ('sdr_preview',)
    OUTPUT_NODE = True
    FUNCTION = 'preview'
    CATEGORY = 'Zura/Artist Studio'
    DESCRIPTION = 'SDR review only: ACEScct to ACEScg, OCIO Rec.709 primaries, neutral Reinhard and sRGB encoding. Master pixels remain unchanged.'

    def preview(self, image, source_space='acescct'):
        import torch
        from ..paintout.paintout import decode_ct
        if source_space not in ('acescct','acescg') or not isinstance(image, torch.Tensor) or image.ndim != 4 or image.shape[-1] != 3 or image.numel() == 0:
            raise ValueError('HDR review requires nonempty NHWC ACEScct RGB frames')
        result = torch.empty(image.shape, dtype=torch.float32, device='cpu')
        for index, frame in enumerate(image):
            if not torch.isfinite(frame).all():
                raise ValueError('HDR review requires finite ACEScct pixels')
            linear = (frame.float() if source_space == 'acescg' else decode_ct(frame.float())).detach().cpu().numpy()
            result[index].numpy()[:] = acescg_sdr_preview(linear)
        return (result,)


NODE_CLASS_MAPPINGS = {'ZuraHDRSDRPreview': ZuraHDRSDRPreview}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraHDRSDRPreview': 'Zura · HDR SDR Preview'}
