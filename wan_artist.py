"""Data adapters for reviewed character replacement with native Wan inputs.

Pose inference remains in WanAnimatePreprocess nodes. These adapters decode the
approved videos, validate matching tensors and cache their CPU outputs before
the diffusion model is loaded. No post-generation performer composite is used.
"""
from __future__ import annotations

import re
from pathlib import Path

import torch
import torch.nn.functional as F

from .video import video_components


def cache_path(key):
    import folder_paths
    if not re.fullmatch(r"[a-f0-9]{64}", key):
        raise ValueError("Invalid Wan preparation cache key.")
    directory = Path(folder_paths.get_output_directory()) / "genj" / "wan_conditioning"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / (key + ".pt")


def validate_footage(footage):
    frames = footage["frames"]
    mask = footage["character_mask"]
    if frames.ndim != 4 or frames.shape[-1] != 3 or frames.shape[0] < 1:
        raise ValueError("Wan source must contain RGB frames.")
    if mask.shape != frames.shape[:3]:
        raise ValueError("Wan mask must match the source frame count and size.")
    for name in ("pose_video", "face_video"):
        value = footage[name]
        if value.ndim != 4 or value.shape[0] != frames.shape[0] or value.shape[-1] != 3:
            raise ValueError(f"Wan {name} must cover every selected source frame.")
    for name in ("frames", "character_mask", "pose_video", "face_video"):
        if not torch.isfinite(footage[name]).all():
            raise ValueError(f"Wan {name} contains invalid pixels.")
    if mask.min() < 0 or mask.max() > 1 or not (mask > .5).any():
        raise ValueError("Wan requires a non-empty approved mask in [0,1].")


class ZuraWanReviewedFrames:
    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "unpack"
    RETURN_TYPES = ("IMAGE", "MASK", "INT", "INT")
    RETURN_NAMES = ("source_frames", "approved_mask", "width", "height")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source": ("VIDEO",), "mask_video": ("VIDEO",)}}

    def unpack(self, source, mask_video):
        frames, _, fps = video_components(source)
        masks, _, mask_fps = video_components(mask_video)
        if abs(fps - 24) > .01 or abs(mask_fps - 24) > .01:
            raise ValueError("Wan review videos must be prepared at 24 fps.")
        if len(masks) != len(frames):
            raise ValueError("The approved mask does not cover the selected clip.")
        mask = masks.float().mean(dim=-1)
        mask = F.interpolate(mask[:, None], frames.shape[1:3], mode="nearest")[:, 0]
        # The saved review is a monochrome video. Restore its binary coverage.
        return frames.float(), (mask > .5).float(), int(frames.shape[2]), int(frames.shape[1])


class ZuraWanSavePreparation:
    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "save"
    RETURN_TYPES = ("STRING",)
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"frames": ("IMAGE",), "mask": ("MASK",),
            "pose": ("IMAGE",), "face": ("IMAGE",), "reference": ("IMAGE",),
            "cache_key": ("STRING", {"default": ""}),
            "scope": (["person", "head"],)}}

    def save(self, frames, mask, pose, face, reference, cache_key, scope):
        footage = {"frames": frames.detach().cpu(), "character_mask": mask.detach().cpu(),
            "pose_video": pose.detach().cpu(), "face_video": face.detach().cpu(),
            "replacement_area": "Whole head" if scope == "head" else "Whole character",
            "video_info": {"fps": 24}, "keep_audio": False}
        validate_footage(footage)
        if reference.ndim != 4 or reference.shape[0] != 1 or reference.shape[-1] != 3:
            raise ValueError("Wan requires one isolated character view.")
        path = cache_path(cache_key)
        temporary = path.with_suffix(".tmp")
        torch.save({"version": 1, "footage": footage, "reference": reference.detach().cpu()}, temporary)
        temporary.replace(path)
        return {"ui": {"text": ["Wan motion, face and approved mask ready."]}, "result": (cache_key,)}


class ZuraWanLoadPreparation:
    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "load"
    RETURN_TYPES = ("ZURA_FOOTAGE", "IMAGE", "INT", "INT")
    RETURN_NAMES = ("footage", "character_view", "width", "height")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cache_key": ("STRING", {"default": ""})}}

    @classmethod
    def IS_CHANGED(cls, cache_key):
        stamp = cache_path(cache_key).stat()
        return stamp.st_mtime_ns, stamp.st_size

    def load(self, cache_key):
        data = torch.load(cache_path(cache_key), map_location="cpu", weights_only=True)
        if data.get("version") != 1:
            raise ValueError("Prepare this Wan shot again.")
        validate_footage(data["footage"])
        frames = data["footage"]["frames"]
        return data["footage"], data["reference"], int(frames.shape[2]), int(frames.shape[1])


NODE_CLASS_MAPPINGS = {c.__name__: c for c in (ZuraWanReviewedFrames, ZuraWanSavePreparation, ZuraWanLoadPreparation)}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraWanReviewedFrames": "Zura · Read Approved Frames and Mask",
    "ZuraWanSavePreparation": "Zura · Cache Wan Motion and Character",
    "ZuraWanLoadPreparation": "Zura · Load Wan Motion and Character"}
