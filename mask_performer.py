"""Zura nodes · Zura Mask.

Person detection, replacement-area masks, pose/face conditioning and the
user-controlled blockify step.  The mask itself is model agnostic and useful on
its own, so the node takes an ordinary ``VIDEO`` wire (Zura Load Video, or any
decoded clip) and hands back standard wires.

Inputs: ``video``.  Outputs: ``mask_preview`` (red tinted control video),
``masked_footage`` (the prepared payload the Wan 2.2 sampler consumes, which has
to carry pose/face/mask tensors a video wire cannot) and ``mask`` (the
replacement mask itself, as a native MASK).

Replacement areas:
- ``Whole character`` replaces the head-and-body mask.
- ``Whole head`` expands the face landmarks to cover hair, forehead and ears,
  cut at the neck so the torso cannot enter the mask.
- ``Face only`` keeps the tight face-landmark ellipse.

``blockify_mask`` (on by default) quantises the final mask to large square
blocks before conditioning, matching the installed KJNodes ``BlockifyMask``
node; the pack delegates to KJNodes when importable and otherwise reproduces
its behaviour with an internal max-pool/nearest pipeline.
"""
from __future__ import annotations

from typing import Any

import sys

import numpy as np
import torch
import torch.nn.functional as F

from .segmentation import as_frames, check_cancelled, detect
from .video import video_components, video_output


def _resize_mask(mask: torch.Tensor, height: int, width: int) -> torch.Tensor:
    if mask.ndim == 2:
        mask = mask[None]
    if mask.ndim == 4:
        mask = mask[:, 0]
    if mask.ndim != 3:
        raise ValueError("character mask must have shape [frames,height,width]")
    return F.interpolate(mask[:, None].float(), (height, width), mode="bilinear", align_corners=False)[:, 0].clamp(0, 1)


def _dilate(mask: torch.Tensor, pixels: int) -> torch.Tensor:
    pixels = int(pixels)
    if pixels <= 0:
        return mask
    return F.max_pool2d(mask[:, None], 2 * pixels + 1, stride=1, padding=pixels)[:, 0].clamp(0, 1)


def _kjnodes_blockify(mask: torch.Tensor, block_size: int):
    """Delegate to the installed KJNodes BlockifyMask; None when unavailable."""
    try:
        import nodes as comfy_nodes
        cls = comfy_nodes.NODE_CLASS_MAPPINGS.get("BlockifyMask")
        if cls is None:
            return None
        params = cls.INPUT_TYPES()["required"]
        kwargs = {}
        if "block_size" in params:
            kwargs["block_size"] = int(block_size)
        if "device" in params:
            kwargs["device"] = "cpu"
        func = getattr(cls(), getattr(cls, "FUNCTION", "process"), None)
        if func is None:
            return None
        if "masks" in params:
            out = func(masks=mask, **kwargs)
        elif "mask" in params:
            out = func(mask=mask, **kwargs)
        else:
            out = func(mask, **kwargs)
        values = out[0] if isinstance(out, (tuple, list)) else out
        result = values.detach().float().clamp(0, 1)
        if result.ndim == 2:
            result = result[None]
        if tuple(result.shape[-2:]) != tuple(mask.shape[-2:]):
            return None
        return result
    except Exception:
        return None


def _blockify_internal(mask: torch.Tensor, block_size: int) -> torch.Tensor:
    # Adapted from kijai/ComfyUI-KJNodes (GPL-3.0); modified for Zura Nodes,
    # 2026-09-17. See THIRD_PARTY_NOTICES.md and licenses/KJNodes-GPL-3.0.txt.
    """KJNodes BlockifyMask algorithm: a bounding-box block grid.

    Each frame's mask bounding box is divided into blocks of roughly
    ``block_size`` pixels; a block fills in when any part of the mask touches
    it.  This is a faithful CPU port of the installed KJNodes node (preferred
    when available), so results are identical with or without it.  Blocks only
    ever fill inside the mask's bounding box and never erase mask pixels.
    """
    b = int(block_size)
    if b <= 0:
        raise ValueError("block_size must be a positive integer")
    if b <= 1:
        return mask.float().clamp(0, 1)
    result = torch.zeros_like(mask, dtype=torch.float32)
    for index in range(int(mask.shape[0])):
        frame = mask[index]
        mask_bool = frame > 0
        if not bool(mask_bool.any()):
            continue
        y_indices = torch.nonzero(mask_bool.any(dim=1), as_tuple=True)[0]
        x_indices = torch.nonzero(mask_bool.any(dim=0), as_tuple=True)[0]
        y_min, y_max = int(y_indices[0]), int(y_indices[-1])
        x_min, x_max = int(x_indices[0]), int(x_indices[-1])
        bbox_width, bbox_height = x_max - x_min + 1, y_max - y_min + 1
        w_divisions = max(1, bbox_width // b)
        h_divisions = max(1, bbox_height // b)
        w_slice, h_slice = max(1, bbox_width // w_divisions), max(1, bbox_height // h_divisions)
        y_coords = torch.arange(y_min, y_max + 1, device=frame.device).view(-1, 1)
        x_coords = torch.arange(x_min, x_max + 1, device=frame.device).view(1, -1)
        w_blocks = ((x_coords - x_min) // w_slice).clamp(0, w_divisions - 1)
        h_blocks = ((y_coords - y_min) // h_slice).clamp(0, h_divisions - 1)
        block_ids = h_blocks * w_divisions + w_blocks
        region = frame[y_min:y_max + 1, x_min:x_max + 1].float()
        block_content = torch.zeros(h_divisions * w_divisions, device=frame.device)
        block_content.scatter_add_(0, block_ids.flatten(), region.flatten())
        result[index, y_min:y_max + 1, x_min:x_max + 1] = (block_content > 0)[block_ids].float()
    return result.clamp(0, 1)


def _blockify(mask: torch.Tensor, block_size: int) -> torch.Tensor:
    """Quantise a mask to ``block_size`` squares: KJNodes first, then internal."""
    if mask.ndim == 2:
        mask = mask[None]
    if mask.ndim != 3:
        raise ValueError("mask must have shape [frames,height,width]")
    delegated = _kjnodes_blockify(mask, int(block_size))
    if delegated is not None:
        return delegated
    return _blockify_internal(mask, int(block_size))


class _SelectedYolo:
    """Detector shim preserving the already selected largest central person."""

    def __init__(self, boxes):
        self.boxes = boxes
        self.index = 0

    def __call__(self, image, shape):
        if not self.boxes:
            return [[{"bbox": None}]]
        box = self.boxes[min(self.index, len(self.boxes) - 1)]
        self.index += 1
        import numpy as np
        return [[{"bbox": np.asarray([*box, 1.0], dtype=np.float32)}]]

    def reinit(self):
        self.index = 0

    def cleanup(self):
        pass


def _run_pose_face(media: dict[str, Any], boxes):
    """Run the installed OnnxDetectionModelLoader + pose/face nodes exactly."""
    try:
        import nodes as comfy_nodes
        loader_cls = comfy_nodes.NODE_CLASS_MAPPINGS["OnnxDetectionModelLoader"]
        pose_cls = comfy_nodes.NODE_CLASS_MAPPINGS["PoseAndFaceDetection"]
        draw_cls = comfy_nodes.NODE_CLASS_MAPPINGS["DrawViTPose"]
    except (ImportError, KeyError) as exc:
        raise RuntimeError("WanAnimate preprocessing nodes are unavailable: expected "
                           "OnnxDetectionModelLoader, PoseAndFaceDetection and DrawViTPose") from exc
    model = loader_cls().loadmodel("vitpose-l-wholebody.onnx", "yolov10m.onnx", "CPUExecutionProvider")[0]
    model["yolo"] = _SelectedYolo(boxes)
    # WanAnimatePreprocess converts every face landmark directly to integers.
    # A missed/occluded face is represented by NaNs and crashes at that
    # conversion.  Keep the native detector, but make its bbox adapter finite.
    import numpy as np
    # PoseAndFaceDetection resolves get_face_bboxes in its own module, not in
    # ComfyUI's root ``nodes`` module. Patch that actual lookup site for this
    # call and always restore it, otherwise an occluded face can still produce
    # an empty crop or NaN conversion.
    pose_module = sys.modules.get(pose_cls.__module__)
    original_bbox = getattr(pose_module, "get_face_bboxes", None)
    if pose_module is not None and original_bbox is not None:
        def safe_face_bboxes(keypoints, scale=1.3, image_shape=None):
            points = np.asarray(keypoints, dtype=np.float32)
            finite = points[np.isfinite(points).all(axis=1)] if points.ndim == 2 else np.empty((0, 2), dtype=np.float32)
            if finite.shape[0] >= 2:
                return original_bbox(finite, scale=scale, image_shape=image_shape)
            h, w = [int(v) for v in image_shape]
            size = max(8, int(min(h, w) * 0.22))
            cx, cy = w // 2, int(h * 0.28)
            return [max(0, cx - size), min(w, cx + size), max(0, cy - size), min(h, cy + size)]
        pose_module.get_face_bboxes = safe_face_bboxes
    try:
        pose_data, face_images, *_ = pose_cls().process(model, media["frames"], int(media["frames"].shape[2]),
                                                        int(media["frames"].shape[1]), retarget_image=None, face_padding=0)
    finally:
        if pose_module is not None and original_bbox is not None:
            pose_module.get_face_bboxes = original_bbox
    pose_video = draw_cls().process(pose_data, int(media["frames"].shape[2]), int(media["frames"].shape[1]),
                                    body_stick_width=-1, hand_stick_width=-1, draw_head=True, retarget_padding=0)[0]
    return {"pose_video": pose_video, "face_video": face_images, "pose_data": pose_data}


def _head_mask_from_pose(pose_data: dict[str, Any], person_masks: torch.Tensor, margin: int = 0,
                         area: str = "Whole head") -> torch.Tensor:
    """Build a head-only foreground mask from WanAnimate's face landmarks.

    ``area`` selects the profile:

    - ``Whole head``: covers hair, forehead and ears.  The face-landmark bounds
      are expanded upward and sideways, the ellipse's top is lifted well above
      the brow line, and the bottom stays near the jaw/neck so the torso never
      enters the mask.
    - ``Face only``: the original tight ellipse around the visible face points.

    Both variants intersect with the person mask and fail loudly when no
    reliable landmarks exist for a frame.
    """
    whole_head = area != "Face only"
    metas = pose_data.get("pose_metas_original") if isinstance(pose_data, dict) else None
    if not metas or len(metas) != int(person_masks.shape[0]):
        raise RuntimeError("Head replacement requires face landmarks for every driving frame")
    h, w = person_masks.shape[-2:]
    result = torch.zeros_like(person_masks, dtype=torch.float32)
    yy, xx = torch.meshgrid(torch.arange(h, device=person_masks.device),
                            torch.arange(w, device=person_masks.device), indexing="ij")
    for index, meta in enumerate(metas):
        points = np.asarray(meta.get("keypoints_face")) if isinstance(meta, dict) and meta.get("keypoints_face") is not None else np.empty((0, 3))
        if points.ndim == 2 and points.shape[1] >= 3:
            valid = np.isfinite(points[:, :3]).all(axis=1) & (points[:, 2] >= 0.5)
            points = points[valid, :2]
        else:
            points = np.empty((0, 2))
        # ViTPose wholebody's body head points (nose and ears, indices 0, 14-17)
        # remain useful for profile/back-facing subjects where face confidence
        # is low.
        if len(points) < 3 and isinstance(meta, dict) and meta.get("keypoints_body") is not None:
            body = np.asarray(meta["keypoints_body"])
            indices = [0, 14, 15, 16, 17]
            if body.ndim == 2 and body.shape[1] >= 3:
                head = body[[i for i in indices if i < len(body)]]
                valid = np.isfinite(head[:, :3]).all(axis=1) & (head[:, 2] >= 0.5)
                points = head[valid, :2]
        if len(points) < 2:
            raise RuntimeError(f"Head replacement could not find reliable face/head landmarks in driving frame {index}")
        x1, y1 = points.min(axis=0) * (w, h)
        x2, y2 = points.max(axis=0) * (w, h)
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        face_w = max(2.0, x2 - x1)
        face_h = max(2.0, y2 - y1)
        if whole_head:
            # Hair and forehead sit above the landmark bounds; ears sit at the
            # landmark sides.  Widen generously and lift the ellipse's centre.
            rx = max(2.0, face_w * 0.85 + float(margin))
            ry = max(2.0, face_h * 1.35 + float(margin))
            cy -= ry * 0.22
        else:
            # Keep the lower edge close to the jaw so the torso cannot enter.
            rx = max(2.0, face_w * 0.68 + float(margin))
            ry = max(2.0, face_h * 0.82 + float(margin))
            cy -= ry * 0.08
        # Profile/back-facing detections can reduce to two ears at almost the
        # same height.  Derive a real head height from their width and lift the
        # ellipse so it includes hair rather than becoming a horizontal sliver.
        if face_h < face_w * 0.25:
            ry = max(ry, rx * 0.95)
            cy -= ry * 0.18
        ellipse = (((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1).to(torch.float32)
        # If the body detector supplied a neck, keep the lower edge near it so
        # the enlarged hair margin cannot spread into the torso.
        body = np.asarray(meta.get("keypoints_body")) if isinstance(meta, dict) and meta.get("keypoints_body") is not None else np.empty((0, 3))
        if body.ndim == 2 and body.shape[1] >= 3 and len(body) > 1:
            neck = body[1]
            if np.isfinite(neck[:3]).all() and neck[2] >= 0.5:
                ellipse = ellipse * (yy <= float(neck[1] * h + margin)).to(torch.float32)
        result[index] = ellipse * person_masks[index].float().clamp(0, 1)
    return result


def _mask_preview_video(frames: torch.Tensor, mask: torch.Tensor, fps: int):
    """Tint the replaced area red over the driving frames: the control video."""
    alpha = (mask[..., None] * 0.55).to(frames.dtype)
    red = torch.tensor([1.0, 0.0, 0.0], device=frames.device, dtype=frames.dtype)
    preview = (frames * (1 - alpha) + red * alpha).clamp(0, 1)
    return video_output(preview, None, fps)


class ZuraMask:
    CATEGORY = "Zura"
    FUNCTION = "prepare"
    RETURN_TYPES = ("VIDEO", "ZURA_FOOTAGE", "MASK")
    RETURN_NAMES = ("mask_preview", "masked_footage", "mask")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video": ("VIDEO", {"tooltip": "Any video wire: Zura Load Video, or a decoded clip from another pack."}),
            "replacement_area": (["Whole character", "Whole head", "Face only"],
                                 {"default": "Whole character",
                                  "tooltip": "Whole character: replace head and body. Whole head: replace the "
                                             "entire head including hair and ears. Face only: replace just the face."}),
            "mask_expansion": ("INT", {"default": 12, "min": 0, "max": 128,
                                       "tooltip": "Grow the replacement mask by this many pixels before blockifying."}),
            "blockify_mask": ("BOOLEAN", {"default": True, "label_on": "Blockify on", "label_off": "Blockify off",
                                          "tooltip": "Quantise the mask to square blocks, as Wan expects."}),
            "block_size": ("INT", {"default": 32, "min": 8, "max": 512, "step": 1,
                                   "tooltip": "Size of blocks in pixels (smaller = smaller blocks) — full "
                                              "control, matching KJNodes BlockifyMask."}),
        }}

    def prepare(self, video, replacement_area="Whole character",
                mask_expansion=12, blockify_mask=True, block_size=32):
        block_size = int(block_size)
        if not 8 <= block_size <= 512:
            raise ValueError(f"block_size must be between 8 and 512 pixels (KJNodes BlockifyMask range), got {block_size}")
        # Any video wire: frames, frame rate and the original audio all come out
        # of the components, so the source can be any loader (or another pack's
        # decode).  ``footage`` below is the payload this node hands downstream.
        images, audio, fps = video_components(video)
        frames = as_frames(images)
        footage = {"frames": frames, "audio": audio, "keep_audio": audio is not None,
                   "video_info": {"fps": fps}}
        masks, boxes = [], []
        previous = None
        for frame_index, frame in enumerate(frames):
            check_cancelled()
            mask, box = detect(frame, previous)
            if mask is None or box is None:
                raise RuntimeError(f"CPU YOLO person mask failed on driving frame {frame_index}; refusing to continue without a character mask")
            masks.append(mask)
            boxes.append(box)
            previous = box
        mask_video = _dilate(torch.stack(masks), int(mask_expansion))
        conditioned = _run_pose_face(footage, boxes)
        if replacement_area in ("Whole head", "Face only"):
            pose_data = conditioned.get("pose_data")
            if pose_data is None:
                raise RuntimeError("Head replacement requires native pose face landmarks")
            mask_video = _head_mask_from_pose(pose_data, mask_video, margin=int(mask_expansion),
                                              area=replacement_area)
        elif replacement_area != "Whole character":
            raise ValueError(f"Unknown replacement area: {replacement_area}")
        if blockify_mask:
            mask_video = _blockify(mask_video, block_size)
        conditioned["character_mask"] = mask_video
        updated = dict(footage)
        # Native Animate receives the performer-removed driving video.  Masks
        # are foreground=1, therefore background_video is source*(1-mask).
        background_video = frames * (1 - mask_video[..., None])
        updated.update({"pose_video": conditioned["pose_video"], "face_video": conditioned["face_video"],
                        "character_mask": mask_video, "background_video": background_video,
                        "mask_expansion": int(mask_expansion), "blockify_mask": bool(blockify_mask),
                        "block_size": int(block_size), "replacement_area": replacement_area,
                        "wan22_prepared": True, "wan22_conditioning": conditioned})
        preview = _mask_preview_video(frames, mask_video, fps)
        return preview, updated, mask_video.detach().clamp(0, 1)


# Class IDs are the workflow contract: these keys are kept from the pack's
# previous name so graphs saved before the Zura rename still load.
NODE_CLASS_MAPPINGS = {"TrendStudioV2MaskPerformer": ZuraMask}
NODE_DISPLAY_NAME_MAPPINGS = {"TrendStudioV2MaskPerformer": "Zura Mask"}
