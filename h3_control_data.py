"""Visible H3 pixel preparation and native ControlNet attachment, without inference.

The graph must use stock VAEEncode nodes between prepare and pack. Cache identity
must bind the source, mask, target and actual VAE/ControlNet configuration; this
module does not infer provenance from a tensor or silently regenerate a cache.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from functools import lru_cache

import torch
import torch.nn.functional as F

MAX_LATENT_BYTES = 256 * 1024 * 1024
MAX_PIXEL_BYTES = 2 * 1024 * 1024 * 1024
MAX_PREPARED_PIXEL_BYTES = 4 * 1024 * 1024 * 1024
MAX_DIMENSION = 4096
SPATIAL_COMPRESSION = 16  # Installed native H3 VAE contract.
_DTYPES = (torch.float16, torch.bfloat16, torch.float32, torch.float64)


def _tensor(value, label, ndim, limit):
    if (not isinstance(value, torch.Tensor) or value.layout != torch.strided
            or getattr(value, "is_nested", False) or value.device.type == "meta"):
        raise ValueError(f"{label} must be a strided tensor.")
    if value.dtype not in _DTYPES or value.ndim != ndim:
        raise ValueError(f"{label} must be a supported floating-point {ndim}D tensor.")
    if any(size <= 0 or size > MAX_DIMENSION for size in value.shape):
        raise ValueError(f"{label} dimensions must be between 1 and {MAX_DIMENSION}.")
    if value.numel() * value.element_size() > limit:
        raise ValueError(f"{label} exceeds its bounded payload limit.")
    if not bool(torch.isfinite(value).all().item()):
        raise ValueError(f"{label} must contain only finite values.")
    return value


def _samples(value, label, channels, *, target=False):
    allowed = {"samples", "noise_mask"} if target else {"samples"}
    if not isinstance(value, Mapping) or "samples" not in value or set(value) - allowed:
        raise ValueError(f"{label} must be a plain latent with supported metadata.")
    samples = _tensor(value["samples"], label, 5, MAX_LATENT_BYTES)
    shape = tuple(samples.shape)
    if shape[:2] != (1, channels) or shape[2] < 2 or (shape[2] - 2) % 5:
        raise ValueError(f"{label} must have shape [1, {channels}, 2+5n, H, W].")
    if shape[-2] % 2 or shape[-1] % 2:
        raise ValueError(f"{label} spatial dimensions must be even.")
    if target and "noise_mask" in value:
        mask = _tensor(value["noise_mask"], f"{label} noise mask", 5, MAX_LATENT_BYTES)
        if any(a not in (1, b) for a, b in zip(mask.shape, shape)) or bool(((mask < 0) | (mask > 1)).any().item()):
            raise ValueError(f"{label} noise mask must broadcast to samples and lie in [0, 1].")
    return samples


def _patch_model(model_patch):
    actual = getattr(model_patch, "model", None)
    norm = getattr(actual, "inpaint_post_norm", None)
    layers = getattr(actual, "injection_layers", None)
    if type(norm) is not bool or not isinstance(layers, (list, tuple)) or not layers:
        raise ValueError("Use the actual loaded native H3 ControlNet MODEL_PATCH.")
    if any(type(item) is not int or item < 0 for item in layers) or len(set(layers)) != len(layers):
        raise ValueError("H3 ControlNet injection layers are malformed.")
    if not callable(getattr(actual, "init_stream", None)) or not callable(getattr(actual, "step", None)):
        raise ValueError("H3 ControlNet must provide native stream and step methods.")
    return actual


def _frame_count(shape):
    return max((shape[2] - 2) // 5, 0) * 17 + 5


def _fit(frames, count, width, height):
    import comfy.utils
    indices = torch.arange(count, device=frames.device).clamp(max=frames.shape[0] - 1)
    return comfy.utils.common_upscale(frames[indices], width, height, "bilinear", "center")


class ZuraH3PrepareControlPixels:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source_video": ("IMAGE",), "control_video": ("IMAGE",),
                             "mask": ("MASK",), "target_latent": ("LATENT",),
                             "model_patch": ("MODEL_PATCH",)}}

    RETURN_TYPES = ("IMAGE", "IMAGE", "MASK")
    RETURN_NAMES = ("fitted_control", "masked_source", "visibility")
    FUNCTION = "prepare"
    CATEGORY = "Zura/Artist Studio/Data"

    def prepare(self, source_video, control_video, mask, target_latent, model_patch):
        target = _samples(target_latent, "Target video", 24, target=True)
        actual = _patch_model(model_patch)
        source = _tensor(source_video, "Source video", 4, MAX_PIXEL_BYTES)
        control = _tensor(control_video, "Control video", 4, MAX_PIXEL_BYTES)
        for image, label in ((source, "Source"), (control, "Control")):
            if image.shape[-1] not in (3, 4):
                raise ValueError(f"{label} image must have RGB or RGBA channels.")
        if not isinstance(mask, torch.Tensor) or mask.ndim not in (2, 3):
            raise ValueError("Edit mask must have shape [H, W] or [frames, H, W].")
        mask = _tensor(mask, "Edit mask", mask.ndim, MAX_PIXEL_BYTES)
        if bool(((mask < 0) | (mask > 1)).any().item()):
            raise ValueError("Edit mask must lie in [0, 1].")
        count = _frame_count(target.shape)
        height, width = target.shape[-2] * SPATIAL_COMPRESSION, target.shape[-1] * SPATIAL_COMPRESSION
        if max(height, width) > MAX_DIMENSION:
            raise ValueError("Prepared H3 raster exceeds the dimension limit.")
        # Multiplication by float32 visibility promotes half/bfloat16 source
        # pixels to float32 in the native formula.
        prepared_bytes = count * height * width * (3 * max(source.element_size(), 4)
                                                  + 3 * control.element_size() + 4)
        if prepared_bytes > MAX_PREPARED_PIXEL_BYTES or target.numel() // 24 * 49 * 4 > MAX_LATENT_BYTES:
            raise ValueError("Prepared H3 control exceeds its bounded payload limit.")
        depth = _fit(control[..., :3].movedim(-1, 1), count, width, height)
        binary_mask = (mask.reshape(-1, 1, mask.shape[-2], mask.shape[-1]) > 0.5).to(torch.float32)
        visibility = 1.0 - (_fit(binary_mask, count, width, height) > 0.5).to(torch.float32)
        fitted_source = _fit(source[..., :3].movedim(-1, 1), count, width, height)
        visibility = visibility.to(fitted_source.device)
        masked = fitted_source * visibility
        if actual.inpaint_post_norm:
            from comfy.ldm.minimax.vae import IMAGENET_MEAN
            masked += (1.0 - visibility) * torch.tensor(IMAGENET_MEAN, dtype=fitted_source.dtype,
                                                       device=fitted_source.device).view(1, 3, 1, 1)
        return depth.movedim(1, -1), masked.movedim(1, -1), visibility.squeeze(1)


class ZuraH3PackEncodedControl:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"control_latent": ("LATENT",), "masked_source_latent": ("LATENT",),
                             "visibility": ("MASK",), "target_latent": ("LATENT",)}}

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("prepared_control",)
    FUNCTION = "pack"
    CATEGORY = "Zura/Artist Studio/Data"

    def pack(self, control_latent, masked_source_latent, visibility, target_latent):
        target = _samples(target_latent, "Target video", 24, target=True)
        depth = _samples(control_latent, "Encoded control", 24)
        source = _samples(masked_source_latent, "Encoded masked source", 24)
        if depth.shape != target.shape or source.shape != target.shape:
            raise ValueError("Both stock H3 VAE encodes must exactly match the target video shape.")
        visibility = _tensor(visibility, "Prepared visibility", 3, MAX_PIXEL_BYTES)
        expected = (_frame_count(target.shape), target.shape[-2] * SPATIAL_COMPRESSION,
                    target.shape[-1] * SPATIAL_COMPRESSION)
        if tuple(visibility.shape) != expected or bool(((visibility != 0) & (visibility != 1)).any().item()):
            raise ValueError("Visibility must be the fitted binary mask at the exact native pixel raster and length.")
        if target.numel() // 24 * 49 * 4 > MAX_LATENT_BYTES:
            raise ValueError("Prepared H3 control exceeds the 256 MiB payload limit.")
        visible = F.interpolate(visibility.to(torch.float32)[None, None], size=tuple(target.shape[2:]),
                                mode="trilinear", align_corners=False)
        packed = torch.cat([depth.to(torch.float32), visible.to(depth.device),
                            source.to(device=depth.device, dtype=torch.float32)], dim=1)
        _samples({"samples": packed}, "Prepared control", 49)
        return ({"samples": packed},)


@lru_cache(maxsize=1)
def _prepared_patch_class():
    # Keep native imports lazy: importing the data module loads no model or GPU.
    from comfy_extras.nodes_minimax_h3 import MiniMaxH3FunControlPatch

    class PreparedH3ControlPatch(MiniMaxH3FunControlPatch):
        def __init__(self, model_patch, prepared, strength, sigma_start, sigma_end):
            super().__init__(model_patch, None, None, None, None, strength, sigma_start, sigma_end)
            self._canonical_control = prepared.detach().to(device="cpu", dtype=torch.float32).clone()
            self._target_shape = (1, 24, *prepared.shape[2:])
            self._post_norm = model_patch.model.inpaint_post_norm

        def prepare_control_latent(self, target_shape):
            if tuple(target_shape) != self._target_shape:
                raise ValueError("Prepared H3 control does not match this sampler's target video shape; prepare it again.")
            if _patch_model(self.model_patch).inpaint_post_norm != self._post_norm:
                raise ValueError("H3 ControlNet normalisation changed after prepared control was attached.")
            if self.control_latent is None or self.control_latent_shape != self._target_shape:
                # Native cleanup erases its working tensor. Restore an independent
                # copy so native stream code cannot mutate the canonical payload.
                self.control_latent = self._canonical_control.clone()
                self.control_latent_shape = self._target_shape

    return PreparedH3ControlPatch


class ZuraH3ApplyEncodedControl:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",), "model_patch": ("MODEL_PATCH",),
                             "prepared_control": ("LATENT",),
                             "strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.01}),
                             "start_percent": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0}),
                             "end_percent": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0})}}

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "apply"
    CATEGORY = "Zura/Artist Studio/Data"

    def apply(self, model, model_patch, prepared_control, strength=1.0, start_percent=0.0, end_percent=1.0):
        prepared = _samples(prepared_control, "Prepared control", 49)
        if prepared.dtype != torch.float32:
            raise ValueError("Prepared H3 control must use float32, as in the native control path.")
        _patch_model(model_patch)
        values = (strength, start_percent, end_percent)
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
            raise ValueError("Control strength and interval must be finite numbers.")
        if not 0 <= strength <= 10 or not 0 <= start_percent <= end_percent <= 1:
            raise ValueError("Control strength must lie in [0, 10] and start/end must be ordered within [0, 1].")
        if strength == 0:
            return (model,)
        sampling = model.get_model_object("model_sampling")
        sigma_start, sigma_end = float(sampling.percent_to_sigma(start_percent)), float(sampling.percent_to_sigma(end_percent))
        if not all(math.isfinite(value) for value in (sigma_start, sigma_end)):
            raise ValueError("Native model sampling returned non-finite control sigma bounds.")
        patch = _prepared_patch_class()(model_patch, prepared, strength, sigma_start, sigma_end)
        cloned = model.clone()
        patch.register(cloned)
        return (cloned,)


NODE_CLASS_MAPPINGS = {cls.__name__: cls for cls in
                       (ZuraH3PrepareControlPixels, ZuraH3PackEncodedControl, ZuraH3ApplyEncodedControl)}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ZuraH3PrepareControlPixels": "Zura · Prepare H3 Control Pixels",
    "ZuraH3PackEncodedControl": "Zura · Pack H3 Control Latents",
    "ZuraH3ApplyEncodedControl": "Zura · Apply Encoded H3 Control",
}
