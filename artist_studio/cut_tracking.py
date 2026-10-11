"""CPU shot splitting and mask assembly around visible native tracking nodes.

These nodes do not detect people, infer masks, or establish identity across an
edit. Each segment must pass through the workflow's native detection/tracking
nodes, and the complete result still needs artist review.
"""
from __future__ import annotations

import math

import torch
import torch.nn.functional as F

from ..cut_detection import detect_cuts


def _thumbnails(images: torch.Tensor) -> torch.Tensor:
    """Keep cut analysis on CPU without duplicating the full source batch."""
    chunks = []
    for start in range(0, images.shape[0], 32):
        chunk = images[start:start + 32].detach().to(device="cpu", dtype=torch.float32)
        if not torch.isfinite(chunk).all():
            raise ValueError("Tracking frames must contain finite image values.")
        chunks.append(F.interpolate(chunk.permute(0, 3, 1, 2), size=(32, 32),
                                    mode="area").permute(0, 2, 3, 1))
    return torch.cat(chunks, dim=0)


class ZuraSplitTrackingShots:
    """Expose batches and first frames for ComfyUI's native list mapping."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",)}}

    RETURN_TYPES = ("IMAGE", "IMAGE", "GENJ_TRACK_SEGMENTS")
    RETURN_NAMES = ("shot_frames", "shot_first_frames", "tracking_segments")
    OUTPUT_IS_LIST = (True, True, False)
    FUNCTION = "split"
    CATEGORY = "Zura/Studio/Tracking"
    DESCRIPTION = "Split hard cuts before native tracking, then review every shot for the correct person."

    def split(self, images):
        if not isinstance(images, torch.Tensor) or images.ndim != 4:
            raise ValueError("Tracking frames must be an IMAGE batch [frames, height, width, channels].")
        count, height, width, channels = map(int, images.shape)
        if min(count, height, width, channels) < 1 or channels != 3:
            raise ValueError("Tracking requires a non-empty RGB image batch.")
        cuts = detect_cuts(_thumbnails(images), threshold=.2, downsample=32)
        bounds = [0, *cuts, count]
        if bounds != sorted(set(bounds)) or any(not 0 < cut < count for cut in cuts):
            raise ValueError("Cut detection returned invalid frame boundaries.")
        segments = [{"start": start, "end": end, "frames": end - start}
                    for start, end in zip(bounds[:-1], bounds[1:])]
        metadata = {"version": 1, "frames": count, "height": height,
                    "width": width, "cuts": cuts, "segments": segments}
        return ([images[s["start"]:s["end"]] for s in segments],
                [images[s["start"]:s["start"] + 1] for s in segments], metadata)


def _segments(metadata):
    if not isinstance(metadata, dict) or metadata.get("version") != 1:
        raise ValueError("Tracking segments must come from Zura Split Tracking Shots.")
    for key in ("frames", "height", "width"):
        if type(metadata.get(key)) is not int or metadata[key] <= 0:
            raise ValueError("Tracking segment dimensions are invalid.")
    segments = metadata.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("Tracking segments are missing.")
    next_start = 0
    for segment in segments:
        if not isinstance(segment, dict) or any(type(segment.get(key)) is not int
                                               for key in ("start", "end", "frames")):
            raise ValueError("Tracking segment boundaries are invalid.")
        if (segment["start"] != next_start or segment["end"] <= next_start
                or segment["frames"] != segment["end"] - next_start):
            raise ValueError("Tracking segments must cover the source once, in chronological order.")
        next_start = segment["end"]
    if next_start != metadata["frames"]:
        raise ValueError("Tracking segments do not cover all source frames.")
    expected_cuts = [segment["start"] for segment in segments[1:]]
    if metadata.get("cuts") != expected_cuts:
        raise ValueError("Tracking cuts do not match segment boundaries.")
    return segments


def _coverage(mask, start):
    """Describe near-empty spans; only artist review can establish their cause."""
    # Less than 0.1% of the raster is flagged for review, including tiny tracker
    # remnants. This cannot distinguish valid cutaways from failed tracking.
    minimum_pixels = max(1, math.ceil(int(mask.shape[1]) * int(mask.shape[2]) * .001))
    absent = []
    for index in range(0, len(mask), 32):
        chunk = mask[index:index + 32].detach().to(device="cpu")
        if not torch.isfinite(chunk).all() or (chunk < 0).any() or (chunk > 1).any():
            raise ValueError("Tracking masks must contain finite values between zero and one.")
        absent.extend(((chunk > .5).sum(dim=(1, 2)) < minimum_pixels).tolist())
    ranges = []
    run_start = None
    for index, missing in enumerate(absent):
        if missing and run_start is None:
            run_start = index
        if not missing and run_start is not None:
            ranges.append({"start": start + run_start, "end": start + index,
                           "frames": index - run_start})
            run_start = None
    if run_start is not None:
        ranges.append({"start": start + run_start, "end": start + len(absent),
                       "frames": len(absent) - run_start})
    return {"start": start, "frames": len(mask), "near_empty_frames": sum(absent),
            "minimum_foreground_pixels": minimum_pixels, "near_empty_ranges": ranges}


class ZuraJoinTrackingMasks:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"masks": ("MASK",), "tracking_segments": ("GENJ_TRACK_SEGMENTS",)}}

    RETURN_TYPES = ("MASK", "GENJ_TRACK_COVERAGE")
    RETURN_NAMES = ("tracked_mask", "tracking_coverage")
    INPUT_IS_LIST = True
    FUNCTION = "join"
    CATEGORY = "Zura/Studio/Tracking"
    DESCRIPTION = "Join native per-shot masks without filling missing tracking or changing identity."

    def join(self, masks, tracking_segments):
        if not isinstance(tracking_segments, list) or len(tracking_segments) != 1:
            raise ValueError("Provide exactly one tracking segment manifest.")
        metadata = tracking_segments[0]
        segments = _segments(metadata)
        if not isinstance(masks, list) or len(masks) != len(segments):
            raise ValueError("Native tracking must return exactly one mask batch for each shot.")
        first = masks[0]
        if not isinstance(first, torch.Tensor):
            raise ValueError("Native tracking must return MASK tensors.")
        coverage = []
        for mask, segment in zip(masks, segments):
            expected_shape = (segment["frames"], metadata["height"], metadata["width"])
            if not isinstance(mask, torch.Tensor) or tuple(mask.shape) != expected_shape:
                raise ValueError("Tracked mask frame counts and raster must match their source shot.")
            if mask.dtype != first.dtype or mask.device != first.device:
                raise ValueError("All tracked shot masks must use the same dtype and device.")
            if not (mask.dtype.is_floating_point or mask.dtype == torch.bool):
                raise ValueError("Tracked masks must use floating-point or boolean values.")
            coverage.append(_coverage(mask, segment["start"]))
        diagnostics = {"version": 1, "frames": metadata["frames"], "shots": coverage,
                       "near_empty_frames": sum(shot["near_empty_frames"] for shot in coverage),
                       "cut_reselection_requires_review": len(segments) > 1}
        return (torch.cat(masks, dim=0), diagnostics)


NODE_CLASS_MAPPINGS = {"ZuraSplitTrackingShots": ZuraSplitTrackingShots,
                       "ZuraJoinTrackingMasks": ZuraJoinTrackingMasks}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraSplitTrackingShots": "Zura · Reset Tracking at Cuts",
                             "ZuraJoinTrackingMasks": "Zura · Rejoin Tracked Shots"}
