"""Experimental sampler masking for native Wan Animate 2.

White edits, black preserves. This supplements WanAnimate2ToVideo rather than
replacing its pose/reference logic or installing a model patch. It can also
test spatial source conditioning, which produced fringes and is off by default.
Spatial replacement is outside the official recipe and needs qualification.
No decoded-frame compositing is performed here.
"""
from __future__ import annotations

import torch
import torch.nn.functional as F


def temporal_mask(mask):
    """Conservative causal 4n+1 reduction: frame zero, then groups of four."""
    if mask.ndim != 3 or (mask.shape[0] - 1) % 4:
        raise ValueError("Mask must be [4n+1, height, width].")
    first = mask[:1]
    if mask.shape[0] == 1:
        return first
    rest = mask[1:].reshape(-1, 4, *mask.shape[1:]).amax(dim=1)
    return torch.cat((first, rest), dim=0)


def prepare_spatial_mask(masks, grow_pixels=16, block_size=0, fill_holes=False,
                         temporal_radius=0):
    """Conservative edit envelope in output pixels, before causal VAE packing.

    Blockification uses max occupancy, never an average that can erase fingers.
    The small temporal union allows brief tracker dropouts without a long hold
    across real occlusions. Filling enclosed holes is explicitly optional.
    """
    if not 0 <= grow_pixels <= 128 or block_size not in (0, 8, 16, 32, 64):
        raise ValueError("Use 0–128 pixels of growth and blocks of 0, 8, 16, 32 or 64 pixels.")
    if not isinstance(temporal_radius, int) or not 0 <= temporal_radius <= 4:
        raise ValueError("Temporal mask margin must be 0–4 frames.")
    masks = masks.clone()
    if fill_holes:
        import numpy as np
        from scipy.ndimage import binary_fill_holes
        array = masks[:, 0].detach().cpu().numpy() >= .5
        masks = torch.from_numpy(np.stack([binary_fill_holes(m) for m in array]))[:, None].to(masks)
    if grow_pixels:
        kernel = grow_pixels * 2 + 1
        masks = F.max_pool2d(masks, (1, kernel), stride=1, padding=(0, grow_pixels))
        masks = F.max_pool2d(masks, (kernel, 1), stride=1, padding=(grow_pixels, 0))
    if block_size:
        h, w = masks.shape[-2:]
        masks = F.max_pool2d(masks, block_size, stride=block_size, ceil_mode=True)
        masks = masks.repeat_interleave(block_size, -2).repeat_interleave(block_size, -1)[..., :h, :w]
    if temporal_radius:
        masks = F.max_pool3d(masks.transpose(0, 1)[None],
                             (temporal_radius * 2 + 1, 1, 1), stride=1,
                             padding=(temporal_radius, 0, 0))[0].transpose(0, 1)
    return masks


def spatial_condition(positive, negative, latent, vae, source_video, edit_mask,
                      trim_latent, length, video_frame_offset=0,
                      grow_pixels=16, lock_background=True, block_size=0,
                      fill_holes=False, temporal_radius=0,
                      condition_background=True):
    """Condition known background AND optionally constrain it every sample step."""
    import comfy.utils

    if isinstance(length, bool) or length < 1 or (length - 1) % 4:
        raise ValueError("Animate 2 requires a positive 4n+1 frame count.")
    samples = latent.get("samples")
    if not isinstance(samples, torch.Tensor) or samples.ndim != 5 or samples.shape[1] != 16:
        raise ValueError("Connect the native Wan Animate 2 latent (16 channels).")
    if trim_latent != 1 or samples.shape[2] != 1 + (length - 1) // 4 + 1:
        raise ValueError("Expected one native reference latent followed by the selected video.")
    if not positive or not negative:
        raise ValueError("Connect both native Animate 2 conditioning outputs.")
    if not lock_background and not condition_background:
        raise ValueError("Enable background locking or experimental background conditioning.")
    if (source_video.ndim != 4 or source_video.shape[-1] < 3
            or not source_video.is_floating_point() or not torch.isfinite(source_video).all()):
        raise ValueError("Source must be a finite RGB image batch.")
    if (edit_mask.ndim != 3 or edit_mask.shape[1:3] != source_video.shape[1:3]
            or edit_mask.shape[0] not in (1, source_video.shape[0])
            or not torch.isfinite(edit_mask).all()):
        raise ValueError("Mask must match the source image dimensions and frame count, or be one static mask.")
    if video_frame_offset < 0 or video_frame_offset >= source_video.shape[0]:
        raise ValueError("Source frame offset is outside the video.")
    # The official node subtracts one continuation frame from this offset.
    # Pass its actual selected offset when using continuation; do not reuse a
    # later offset emitted for the next chunk.
    frames = source_video[video_frame_offset:video_frame_offset + length, ..., :3]
    masks = (edit_mask.expand(source_video.shape[0], -1, -1) if edit_mask.shape[0] == 1 else edit_mask)
    masks = masks[video_frame_offset:video_frame_offset + length].float().clamp(0, 1)
    if frames.shape[0] < length:
        missing = length - frames.shape[0]
        frames = torch.cat((frames, frames[-1:].expand(missing, -1, -1, -1)))
        masks = torch.cat((masks, masks[-1:].expand(missing, -1, -1)))
    height, width = samples.shape[-2] * 8, samples.shape[-1] * 8
    frames = comfy.utils.common_upscale(frames.movedim(-1, 1), width, height, "area", "center").movedim(1, -1)
    masks = comfy.utils.common_upscale(masks[:, None], width, height, "nearest-exact", "center")
    masks = prepare_spatial_mask(masks, grow_pixels, block_size, fill_holes, temporal_radius)
    # Max pooling preserves thin moving features rather than averaging them away.
    small = F.adaptive_max_pool2d(masks, samples.shape[-2:])[:, 0]
    reduced = temporal_mask(small)[None, None]
    known = None
    if condition_background:
        pixel_mask = masks.movedim(1, -1)
        known = vae.encode(frames * (1 - pixel_mask) + 0.5 * pixel_mask)
    full = vae.encode(frames) if lock_background else None
    expected = (1, 16, (length - 1) // 4 + 1, *samples.shape[-2:])
    if ((known is not None and known.shape != expected)
            or full is not None and full.shape != expected):
        raise ValueError("VAE output does not match Wan 2.1/Animate 2 compression.")

    def update(conditioning):
        result = []
        for embedding, metadata in conditioning:
            old = metadata.get("concat_latent_image")
            old_mask = metadata.get("concat_mask")
            if (not isinstance(old, torch.Tensor) or old.shape[1:] != samples.shape[1:]
                    or not isinstance(old_mask, torch.Tensor)
                    or old_mask.shape != (1, 1, samples.shape[2], *samples.shape[-2:])):
                raise ValueError("Connect native WanAnimate2ToVideo conditioning, not another Wan model.")
            if not condition_background:
                # Keep the official full-frame conditioning. Only the sampler
                # sees the spatial mask, avoiding out-of-distribution mask edges
                # in a model with no demonstrated spatial replacement training.
                result.append([embedding, dict(metadata)])
                continue
            # Keep the reference and any known continuation cells untouched.
            editable = old_mask[:, :, trim_latent:].to(reduced) * reduced
            background = known.to(old)
            original_tail = old[:, :, trim_latent:]
            original_mask = old_mask[:, :, trim_latent:]
            background = torch.where(original_mask.to(old) > 0, background, original_tail)
            copy = dict(metadata)
            copy["concat_latent_image"] = torch.cat((old[:, :, :trim_latent], background), dim=2)
            copy["concat_mask"] = torch.cat((old_mask[:, :, :trim_latent], editable.to(old_mask)), dim=2)
            result.append([embedding, copy])
        return result

    pos, neg = update(positive), update(negative)
    out = dict(latent)
    if lock_background:
        prefix = positive[0][1]["concat_latent_image"][:, :, :trim_latent].to(samples)
        original_mask = positive[0][1]["concat_mask"][:, :, trim_latent:].to(reduced)
        video = torch.where(original_mask.to(samples) > 0, full.to(samples),
                            positive[0][1]["concat_latent_image"][:, :, trim_latent:].to(samples))
        out["samples"] = torch.cat((prefix, video), dim=2).expand(samples.shape[0], -1, -1, -1, -1).clone()
        noise_mask = torch.cat((torch.zeros_like(reduced[:, :, :trim_latent]), original_mask * reduced), dim=2)
        if "noise_mask" in latent:
            existing = latent["noise_mask"]
            if existing.shape != noise_mask.shape:
                raise ValueError("Existing latent mask has incompatible shape.")
            noise_mask = noise_mask * existing.to(noise_mask)
        out["noise_mask"] = noise_mask
    return pos, neg, out


class ZuraWanAnimate2SpatialMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "positive": ("CONDITIONING",), "negative": ("CONDITIONING",),
            "latent": ("LATENT",), "vae": ("VAE",),
            "source_video": ("IMAGE",), "edit_mask": ("MASK",),
            "trim_latent": ("INT", {"default": 1, "min": 1, "max": 1}),
            "length": ("INT", {"default": 49, "min": 1, "max": 81, "step": 4}),
            "video_frame_offset": ("INT", {"default": 0, "min": 0}),
            "grow_pixels": ("INT", {"default": 32, "min": 0, "max": 128}),
            "lock_background": ("BOOLEAN", {"default": True}),
        }, "optional": {
            "block_size": ([0, 8, 16, 32, 64], {"default": 32}),
            "fill_holes": ("BOOLEAN", {"default": True}),
            "temporal_radius": ("INT", {"default": 1, "min": 0, "max": 4}),
            "condition_background": ("BOOLEAN", {"default": False}),
        }}

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    FUNCTION = "apply"
    CATEGORY = "Zura/Experimental/Wan Animate 2"
    DESCRIPTION = ("Experimental Animate 2 sampler mask. White edits; black locks source latents. "
                   "Default: expanded, solid 32-pixel blocks and native conditioning. No final RGB composite. "
                   "Background conditioning is an experimental ablation that produced coloured fringes in tests.")

    def apply(self, **kwargs):
        kwargs.setdefault("block_size", 32)
        kwargs.setdefault("fill_holes", True)
        kwargs.setdefault("temporal_radius", 1)
        kwargs.setdefault("condition_background", False)
        return spatial_condition(**kwargs)


NODE_CLASS_MAPPINGS = {"ZuraWanAnimate2SpatialMask": ZuraWanAnimate2SpatialMask}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraWanAnimate2SpatialMask": "Wan Animate 2 · Spatial mask (experimental)"}
