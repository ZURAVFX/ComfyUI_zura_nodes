"""Conservative, frame-local cleanup for small enclosed mask holes."""
from __future__ import annotations

import torch


CATEGORY = "Zura/Artist Studio/Mask"
DEFAULT_MAX_HOLE_AREA = 128
# Conservative pixel-area cap. Legitimate gaps can be smaller on other masks;
# inspect the result at its working resolution before generation.
MAX_HOLE_AREA = 256
MAX_FRAMES = 4096
MAX_FRAME_PIXELS = 16_777_216
MAX_BATCH_PIXELS = 134_217_728
MAX_SIDE = 8192
FOREGROUND_THRESHOLD = 0.5


def _validate_masks(masks: torch.Tensor) -> tuple[int, int, int]:
    if not isinstance(masks, torch.Tensor) or masks.ndim != 3:
        raise ValueError("Provide a floating-point MASK batch with shape [frames, height, width].")
    if not masks.is_floating_point():
        raise ValueError("Mask cleanup requires a floating-point MASK batch.")

    frames, height, width = (int(size) for size in masks.shape)
    if (min(frames, height, width) < 1 or frames > MAX_FRAMES
            or height > MAX_SIDE or width > MAX_SIDE
            or height * width > MAX_FRAME_PIXELS
            or frames * height * width > MAX_BATCH_PIXELS):
        raise ValueError("Mask dimensions exceed the bounded frame or batch size for cleanup.")
    return frames, height, width


def _small_enclosed_holes(frame: torch.Tensor, max_hole_area: int):
    """Return a CPU bool raster of fill pixels, using four-connected background."""
    import cv2
    import numpy as np

    # Transfer one frame at a time. Converting the threshold result (rather than
    # the source dtype) also supports bfloat16 masks without changing the cutoff.
    background = (frame.detach().to(device="cpu") < FOREGROUND_THRESHOLD)
    binary = background.to(dtype=torch.uint8).contiguous().numpy()
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=4)

    fill_labels = []
    height, width = binary.shape
    border_labels = set(labels[0, :].tolist())
    border_labels.update(labels[height - 1, :].tolist())
    border_labels.update(labels[:, 0].tolist())
    border_labels.update(labels[:, width - 1].tolist())
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area <= max_hole_area and label not in border_labels:
            fill_labels.append(label)

    if not fill_labels:
        return None
    return np.isin(labels, np.asarray(fill_labels, dtype=labels.dtype))


class ZuraFillSmallMaskHoles:
    """Fill only small, fully enclosed background components in each frame."""

    CATEGORY = CATEGORY
    FUNCTION = "fill"
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("cleaned_mask",)
    DESCRIPTION = (
        "Fill tiny enclosed gaps in each mask frame. Border-connected areas and "
        "larger gaps stay untouched; inspect the mask before generation."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "masks": ("MASK",),
            "max_hole_area": ("INT", {
                "default": DEFAULT_MAX_HOLE_AREA,
                "min": 0,
                "max": MAX_HOLE_AREA,
                "step": 1,
                "tooltip": "Fill enclosed gaps up to this many pixels. Set to 0 to pass the mask through.",
            }),
        }}

    def fill(self, masks, max_hole_area=DEFAULT_MAX_HOLE_AREA):
        frames, _, _ = _validate_masks(masks)
        if type(max_hole_area) is not int or not 0 <= max_hole_area <= MAX_HOLE_AREA:
            raise ValueError(f"Maximum hole area must be an integer from 0 to {MAX_HOLE_AREA}.")

        output = None
        for index in range(frames):
            frame = masks[index]
            if not torch.isfinite(frame).all().item():
                raise ValueError("Mask cleanup requires finite MASK values.")
            if max_hole_area == 0:
                continue

            fill_pixels = _small_enclosed_holes(frame, max_hole_area)
            if fill_pixels is None:
                continue

            if output is None:
                output = masks.clone()
            fill_on_device = torch.from_numpy(fill_pixels).to(device=masks.device)
            output[index][fill_on_device] = 1.0

        return (masks if output is None else output,)


NODE_CLASS_MAPPINGS = {"ZuraFillSmallMaskHoles": ZuraFillSmallMaskHoles}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraFillSmallMaskHoles": "Zura · Fill Small Mask Holes"}
