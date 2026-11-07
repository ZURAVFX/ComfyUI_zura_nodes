"""Small input adapters for Studio's native smart crop-and-stitch graph.

The model, crop and stitch remain native ComfyUI nodes. This module validates
an artist-painted image mask and makes a source-space, inward-only blend mask.
"""

import math
import numpy as np
import torch
import torch.nn.functional as F
from scipy import ndimage


class ZuraImageEditMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "painted_mask": ("IMAGE",),
            "feather_pixels": ("INT", {"default": 16, "min": 0, "max": 256}),
        }}

    RETURN_TYPES = ("MASK", "MASK")
    RETURN_NAMES = ("selection", "inward_blend")
    FUNCTION = "prepare"
    CATEGORY = "Zura Studio/image"

    def prepare(self, image, painted_mask, feather_pixels):
        if image.ndim != 4 or painted_mask.ndim != 4 or not image.shape[0] or not painted_mask.shape[0]:
            raise ValueError("Could not read the main image and edit-area mask.")
        height, width = image.shape[1:3]
        mask_height, mask_width = painted_mask.shape[1:3]
        if min(height, width, mask_height, mask_width) < 1 or not painted_mask.shape[-1]:
            raise ValueError("The edit-area mask has no pixels.")
        if abs((mask_width / mask_height) / (width / height) - 1) > 0.01:
            raise ValueError("The edit-area mask does not match the main image. Paint the area again.")
        if not torch.isfinite(painted_mask).all():
            raise ValueError("The edit-area mask contains invalid pixels. Paint the area again.")

        # Brush images are opaque greyscale PNGs: LoadImage's alpha-derived
        # MASK is empty, so read the red image channel instead.
        mask = painted_mask[:1, :, :, 0].detach().float().cpu().clamp(0, 1)
        raw = F.interpolate(mask.unsqueeze(1), size=(height, width), mode="nearest").squeeze(1)
        if not torch.any(raw > 0):
            raise ValueError("Paint an edit area, or switch back to the whole image.")
        feather = max(0, min(256, int(feather_pixels)))
        if feather == 0:
            return (raw, raw.clone())

        # Distance transforms are bounded to a 2048-pixel longest edge to
        # avoid allocating several full-size float64 arrays for large plates.
        ratio = min(1.0, 2048 / max(mask_height, mask_width))
        small_h = max(1, round(mask_height * ratio))
        small_w = max(1, round(mask_width * ratio))
        small = F.interpolate(mask.unsqueeze(1), size=(small_h, small_w), mode="nearest")[0, 0].numpy() > 0
        if not small.any():
            raise ValueError("The painted area is too small. Paint a slightly larger selection.")
        # Padding treats the image edge as outside the mask, including when
        # the user paints to the edge of the source plate.
        distance = ndimage.distance_transform_edt(
            np.pad(small, 1, constant_values=False),
            sampling=(height / small_h, width / small_w),
        )[1:-1, 1:-1].astype(np.float32)
        weight = np.clip(distance / feather, 0, 1)
        weight = weight * weight * (3 - 2 * weight)
        weight = torch.from_numpy(weight).unsqueeze(0).unsqueeze(0)
        weight = F.interpolate(weight, size=(height, width), mode="bilinear", align_corners=False).squeeze(1)
        # Multiplying by the original mask guarantees exactly zero outside the
        # painted contour, even after interpolation of the feather weights.
        return (raw, (raw * weight).clamp_(0, 1))


class ZuraImageEditCropResult:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",), "reference": ("IMAGE",)}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "validate"
    CATEGORY = "Zura Studio/image"

    def validate(self, image, reference):
        if image.ndim != 4 or reference.ndim != 4 or not image.shape[0] or not reference.shape[0]:
            raise ValueError("The image model did not return a usable edited crop.")
        if image.shape[-1] < 3 or reference.shape[-1] < 3:
            raise ValueError("The image model returned an unsupported crop format.")
        h, w = image.shape[1:3]
        ref_h, ref_w = reference.shape[1:3]
        if min(h, w, ref_h, ref_w) < 1 or abs((w / h) / (ref_w / ref_h) - 1) > 0.08:
            raise ValueError("The image model returned a different crop shape. Try again or use another image model.")
        if not torch.isfinite(image).all():
            raise ValueError("The image model returned invalid crop pixels.")
        # Some decoders return RGBA; older Hallett stitchers require RGB.
        return (image[..., :3],)


class ZuraImageEditResolution:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "megapixels": ("FLOAT", {"default": 1.0, "min": 0.01, "max": 16.0}),
            "resolution_steps": ("INT", {"default": 16, "min": 8, "max": 256}),
        }}

    RETURN_TYPES = ("FLOAT",)
    RETURN_NAMES = ("megapixels",)
    FUNCTION = "clamp"
    CATEGORY = "Zura Studio/image"

    def clamp(self, image, megapixels, resolution_steps):
        if image.ndim != 4 or min(image.shape[1:3]) < 1:
            raise ValueError("The edit crop has no image pixels.")
        if not math.isfinite(megapixels) or not 0.01 <= megapixels <= 16:
            raise ValueError("Choose an edit processing size between 0.01 and 16 MP.")
        h, w = image.shape[1:3]
        aspect = max(w / h, h / w)
        # Keep both axes inside model limits. The smart-crop node has already
        # snapped its crop aspect to a supported range; ImageScaleToTotalPixels
        # will round the resulting dimensions to the model's requested grid.
        min_pixels = 256 * 256 * aspect
        max_pixels = 8192 * 8192 / aspect
        if min_pixels > max_pixels:
            raise ValueError("The selected area is too narrow for this image model. Paint a wider area.")
        pixels = min(max(megapixels * 1024 * 1024, min_pixels), max_pixels, 16 * 1024 * 1024)
        return (pixels / (1024 * 1024),)


NODE_CLASS_MAPPINGS = {
    "ZuraImageEditMask": ZuraImageEditMask,
    "ZuraImageEditCropResult": ZuraImageEditCropResult,
    "ZuraImageEditResolution": ZuraImageEditResolution,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ZuraImageEditMask": "Zura Image Edit Mask",
    "ZuraImageEditCropResult": "Zura Image Edit Crop Result",
    "ZuraImageEditResolution": "Zura Image Edit Resolution",
}
