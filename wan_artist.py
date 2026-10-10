"""Data adapters for reviewed character replacement with native Wan inputs.

Pose inference remains in WanAnimatePreprocess nodes. These adapters decode the
approved videos, validate matching tensors and cache their CPU outputs before
the diffusion model is loaded. No post-generation performer composite is used.
"""
from __future__ import annotations

import json
import math
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


class ZuraWanPackPreparation:
    """Connect visible native preprocessing directly to the sampler in graph view."""
    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "pack"
    RETURN_TYPES = ("ZURA_FOOTAGE", "IMAGE", "INT", "INT")
    RETURN_NAMES = ("footage", "character_view", "width", "height")

    @classmethod
    def INPUT_TYPES(cls):
        required = dict(ZuraWanSavePreparation.INPUT_TYPES()["required"])
        required.pop("cache_key")
        return {"required": required}

    def pack(self, frames, mask, pose, face, reference, scope):
        footage = {"frames": frames.detach().cpu(), "character_mask": mask.detach().cpu(),
            "pose_video": pose.detach().cpu(), "face_video": face.detach().cpu(),
            "replacement_area": "Whole head" if scope == "head" else "Whole character",
            "video_info": {"fps": 24}, "keep_audio": False}
        validate_footage(footage)
        return footage, reference, int(frames.shape[2]), int(frames.shape[1])


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


def _detected_face(pose, boxes, width, height, label):
    """Validate native detector evidence before trusting its fallback-prone crop."""
    import numpy as np
    metas = pose.get("pose_metas_original", [])
    if len(metas) != 1 or len(boxes) != 1:
        raise ValueError("Detect one visible " + label + " face in the approved opening frame.")
    meta = metas[0]
    points = np.asarray(meta.get("keypoints_face", []), dtype=float)
    if points.shape == (69, 3):
        points = points[1:]
    if points.shape != (68, 3) or not np.isfinite(points).all():
        raise ValueError("The " + label + " face has no reliable landmarks. Choose a clearer opening frame.")
    confidence = float(points[27:68, 2].mean())
    if confidence < .3:
        raise ValueError("The " + label + " face is not clear enough for speech. Choose a clearer opening frame.")
    detected_w, detected_h = float(meta.get("width", 0)), float(meta.get("height", 0))
    coordinates = np.asarray(boxes[0], dtype=float)
    if min(detected_w, detected_h) <= 0 or coordinates.shape != (4,) or not np.isfinite(coordinates).all():
        raise ValueError("The " + label + " face detection has invalid dimensions.")
    x1, y1, x2, y2 = coordinates * np.array([width / detected_w, height / detected_h] * 2)
    if x2 <= x1 or y2 <= y1 or x1 < 0 or y1 < 0 or x2 > width or y2 > height:
        raise ValueError("The " + label + " face detection lies outside the approved image.")
    # Reject collapsed/empty landmarks even if a detector returns a high score.
    if min(np.ptp(points[:, :2], axis=0)) <= 1e-5:
        raise ValueError("The " + label + " face landmarks are collapsed.")
    return (float(x1), float(y1), float(x2), float(y2)), confidence


class ZuraWanSpeechReferenceCrop:
    """CPU crop using visible native pose evidence and the approved performer mask."""
    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "crop"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("speech_portrait", "crop_provenance")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"opening": ("IMAGE",), "source_images": ("IMAGE",),
            "approved_mask": ("MASK",), "source_pose": ("POSEDATA",), "source_boxes": ("BBOX,",),
            "opening_pose": ("POSEDATA",), "opening_boxes": ("BBOX,",),
            "guide_key": ("STRING", {"default": ""})}}

    def crop(self, opening, source_images, approved_mask, source_pose, source_boxes,
             opening_pose, opening_boxes, guide_key):
        from .artist_studio.wan_speech import CROP_RECIPE, canonical, _validate_crop
        for label, image in (("approved opening", opening), ("source opening", source_images)):
            if image.ndim != 4 or image.shape[0] != 1 or image.shape[-1] != 3 or min(image.shape[1:3]) < 4:
                raise ValueError("Use one RGB " + label + " frame for the speech reference.")
            if not torch.isfinite(image).all():
                raise ValueError("The " + label + " contains invalid pixels.")
        h, w = map(int, opening.shape[1:3])
        source_h, source_w = map(int, source_images.shape[1:3])
        if approved_mask.shape != (1, source_h, source_w) or not torch.isfinite(approved_mask).all():
            raise ValueError("The approved performer mask must match the source opening frame.")
        mask = approved_mask.detach().cpu()[0]
        if mask.min() < 0 or mask.max() > 1:
            raise ValueError("The approved performer mask must lie in [0,1].")
        source, source_confidence = _detected_face(source_pose, source_boxes, source_w, source_h, "source")
        face, opening_confidence = _detected_face(opening_pose, opening_boxes, w, h, "character")
        sx1, sy1, sx2, sy2 = source
        source_coverage = mask[math.floor(sy1):math.ceil(sy2), math.floor(sx1):math.ceil(sx2)]
        overlap = float((source_coverage > .5).float().mean())
        if overlap < .5:
            raise ValueError("The detected source face is outside the approved performer mask. Choose a single visible performer.")
        # The approved opening retains source framing. Verify the detected new
        # face still belongs to that performer, including multi-person scenes.
        x1, y1, x2, y2 = face
        projected = mask[math.floor(y1 * source_h / h):math.ceil(y2 * source_h / h),
                         math.floor(x1 * source_w / w):math.ceil(x2 * source_w / w)]
        opening_overlap = float((projected > .5).float().mean()) if projected.numel() else 0
        centre_gap = max(abs((x1 + x2) / (2 * w) - (sx1 + sx2) / (2 * source_w)),
                         abs((y1 + y2) / (2 * h) - (sy1 + sy2) / (2 * source_h)))
        allowed_gap = max((sx2 - sx1) / source_w, (sy2 - sy1) / source_h) * 1.5
        if opening_overlap < .5 or centre_gap > allowed_gap:
            raise ValueError("The character face does not match the approved performer position. Review the opening frame again.")
        # Expand to a 3:4 portrait around the actual head. Native resizing keeps
        # this aspect ratio; no private coordinates or stretched square crop.
        face_w, face_h = x2 - x1, y2 - y1
        units = min(w // 3, h // 4, math.ceil(max(2 * face_w / 3, 2 * face_h / 4)))
        crop_w, crop_h = units * 3, units * 4
        if crop_w < face_w or crop_h < face_h:
            raise ValueError("The face cannot fit a portrait crop without cutting it. Choose a wider opening frame.")
        left = min(max(round((x1 + x2) / 2 - crop_w / 2), 0), w - crop_w)
        top = min(max(round((y1 + y2) / 2 + .25 * face_h - crop_h / 2), 0), h - crop_h)
        if left > x1 or top > y1 or left + crop_w < x2 or top + crop_h < y2:
            # Clamp the shifted framing to include the whole detected face.
            left = min(max(left, math.ceil(x2 - crop_w)), math.floor(x1))
            top = min(max(top, math.ceil(y2 - crop_h)), math.floor(y1))
        metadata = {"recipe": CROP_RECIPE, "guide_key": guide_key,
            "opening_size": [w, h], "source_size": [source_w, source_h],
            "source_face_xyxy": list(source), "opening_face_xyxy": list(face),
            "crop_xywh": [left, top, crop_w, crop_h], "source_mask_overlap": overlap,
            "opening_mask_overlap": opening_overlap, "source_confidence": source_confidence,
            "opening_confidence": opening_confidence}
        _validate_crop(metadata, guide_key)
        encoded = canonical(metadata)
        return {"ui": {"text": [encoded]}, "result": (opening[:, top:top + crop_h, left:left + crop_w, :].detach().cpu(), encoded)}


class ZuraWanSpeechSaveGuide:
    """Record native VHS output; successful-history verification promotes it later."""
    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "save"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("pending_guide_key",)
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # A requeued native graph must record the currently owning prompt even
        # when Comfy reuses its already rendered images or video output.
        return float("nan")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"filenames": ("VHS_FILENAMES",), "crop_metadata": ("STRING",),
            "selected_audio": ("AUDIO",), "guide_key": ("STRING", {"default": ""}),
            "recipe_json": ("STRING", {"default": ""})},
            "hidden": {"prompt": "PROMPT", "unique_id": "UNIQUE_ID"}}

    def save(self, filenames, crop_metadata, selected_audio, guide_key, recipe_json, prompt, unique_id):
        from .artist_studio.wan_speech import save_pending
        return save_pending(filenames, crop_metadata, selected_audio, guide_key, recipe_json, prompt, unique_id)


NODE_CLASS_MAPPINGS = {c.__name__: c for c in (ZuraWanReviewedFrames, ZuraWanSavePreparation, ZuraWanLoadPreparation,
    ZuraWanPackPreparation, ZuraWanSpeechReferenceCrop, ZuraWanSpeechSaveGuide)}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraWanReviewedFrames": "Zura · Read Approved Frames and Mask",
    "ZuraWanSavePreparation": "Zura · Cache Wan Motion and Character",
    "ZuraWanLoadPreparation": "Zura · Load Wan Motion and Character",
    "ZuraWanPackPreparation": "Zura · Connect Wan Motion and Character",
    "ZuraWanSpeechReferenceCrop": "Zura · Crop Approved Speech Portrait",
    "ZuraWanSpeechSaveGuide": "Zura · Save Native Wan Speech Guide"}
