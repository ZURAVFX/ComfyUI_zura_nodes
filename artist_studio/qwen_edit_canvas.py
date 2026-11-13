"""Reuse Qwen's native reference raster for the sampling canvas.

The native Edit Plus encoder scales its VAE references to roughly one megapixel.
Sampling an independently sized latent changes the framing of the edit.
"""
import torch


class ZuraQwenEditLatent:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'conditioning': ('CONDITIONING',)}}

    RETURN_TYPES = ('LATENT',)
    FUNCTION = 'canvas'
    CATEGORY = 'Zura/Studio'

    def canvas(self, conditioning):
        reference = None
        if not isinstance(conditioning, (list, tuple)) or not 1 <= len(conditioning) <= 128:
            raise ValueError('Qwen editing needs its encoded reference image.')
        for entry in conditioning:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2 or not isinstance(entry[1], dict):
                raise ValueError('Qwen reference conditioning is invalid.')
            refs = entry[1].get('reference_latents')
            if refs is None:
                continue
            if not isinstance(refs, (list, tuple)) or not refs:
                raise ValueError('Qwen reference latents are missing.')
            first = refs[0]
            if (not isinstance(first, torch.Tensor) or first.ndim not in (4, 5)
                    or first.shape[0] != 1 or not first.is_floating_point()
                    or first.numel() > 64 * 1024 * 1024
                    or any(d <= 0 for d in first.shape)):
                raise ValueError('Qwen reference raster is invalid or too large.')
            if reference is not None and reference.shape != first.shape:
                raise ValueError('Qwen conditioning changed the reference raster.')
            if reference is None:
                reference = first
        if reference is None:
            raise ValueError('Qwen editing needs a VAE-encoded reference image.')
        # The sampler may transform its input. Keep the conditioning tensor
        # independent, and preserve the native encoder's dtype and exact shape.
        return ({'samples': reference.detach().clone()},)
