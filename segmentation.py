"""CPU person detection and segmentation for Zura nodes.

The detector is deliberately CPU-only: the diffusion model owns the GPU and a
small YOLO segmentation pass must not evict it.  Detection helpers are usable
in tests without ultralytics installed; only ``detect`` needs the model.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F


MODEL_NAME = "person_yolov8m-seg.pt"
_MODEL = None


def as_frames(x: torch.Tensor) -> torch.Tensor:
    if not isinstance(x, torch.Tensor):
        raise ValueError("images must be a ComfyUI IMAGE tensor")
    if x.ndim == 3:
        x = x.unsqueeze(0)
    if x.ndim != 4 or x.shape[-1] != 3:
        raise ValueError("images must have shape [frames,height,width,3]")
    return x.float().clamp(0, 1)


def check_cancelled():
    try:
        import comfy.model_management as mm
        mm.throw_exception_if_processing_interrupted()
    except ImportError:
        return


def _model_path() -> Path:
    try:
        import folder_paths
        found = folder_paths.get_full_path("ultralytics", f"segm/{MODEL_NAME}")
        if found:
            return Path(found)
        root = Path(folder_paths.models_dir) / "ultralytics" / "segm" / MODEL_NAME
    except Exception:
        root = Path("models/ultralytics/segm") / MODEL_NAME
    if root.is_file():
        return root
    raise RuntimeError(
        f"Person segmentation model not found: {MODEL_NAME}. "
        "Place it in ComfyUI/models/ultralytics/segm/ "
        f"(expected file: {MODEL_NAME}) and restart ComfyUI."
    )


def _detector():
    global _MODEL
    if _MODEL is None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Zura nodes require the installed ultralytics package") from exc
        _MODEL = YOLO(str(_model_path()))
    return _MODEL


def detect(frame: torch.Tensor, previous_box=None):
    # Ultralytics expects ordinary image bytes.  Keep this path CPU-only so the
    # diffusion model's VRAM remains available.
    array = (frame.detach().cpu().clamp(0, 1).mul(255).byte().numpy()[..., ::-1]).copy()
    result = _detector()(array, device="cpu", verbose=False, imgsz=640, retina_masks=True, classes=[0])[0]
    if result.masks is None or result.boxes is None or len(result.boxes) == 0:
        return None, None
    masks = result.masks.data.detach().cpu().float()
    boxes = result.boxes.xyxy.detach().cpu().float()
    h, w = frame.shape[:2]
    best, best_score = None, -1e9
    for i, box in enumerate(boxes):
        x1, y1, x2, y2 = box.tolist()
        area = max(1.0, (x2 - x1) * (y2 - y1))
        cx, cy = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
        centrality = max(0.0, 1.0 - ((cx - .5) ** 2 + (cy - .5) ** 2) ** .5 / .707)
        score = area * (0.35 + 0.65 * centrality)
        if previous_box is not None:
            px1, py1, px2, py2 = previous_box
            ix1, iy1, ix2, iy2 = max(x1, px1), max(y1, py1), min(x2, px2), min(y2, py2)
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            union = area + max(1, (px2 - px1) * (py2 - py1)) - inter
            score *= 1 + 1.5 * (inter / union)
        if score > best_score:
            best_score, best = score, i
    mask = F.interpolate(masks[best][None, None], (h, w), mode="bilinear", align_corners=False)[0, 0]
    return mask, boxes[best].tolist()
