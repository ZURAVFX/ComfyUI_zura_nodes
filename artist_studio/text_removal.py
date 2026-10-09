"""Combine native SAM text detections with the reviewed replacement mask."""
import math

import torch
import torch.nn.functional as F


class GenjTextRemovalMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"performer_mask": ("MASK",), "text_mask": ("MASK",),
                             "text_boxes": ("BOUNDING_BOX",), "clip_details": ("GENJ_CLIP",),
                             "padding": ("INT", {"default": 5, "min": 0, "max": 32})}}

    RETURN_TYPES = ("MASK", "GENJ_CLIP")
    FUNCTION = "combine"
    CATEGORY = "Zura/Artist Studio"

    def combine(self, performer_mask, text_mask, text_boxes, clip_details, padding=5):
        count, height, width = performer_mask.shape
        if len(text_mask) != count or len(text_boxes) != count:
            raise ValueError("Text detection and the performer mask must cover the same frames.")
        text = F.interpolate(text_mask[:, None].float(), size=(height, width), mode="nearest")[:, 0]
        text = (text > 0.5).to(device=performer_mask.device, dtype=torch.float32)
        detections = 0
        detected_frames = 0
        for frame, boxes in enumerate(text_boxes):
            if boxes:
                detected_frames += 1
            for box in boxes:
                x, y, w, h = (float(box[k]) for k in ("x", "y", "width", "height"))
                if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
                    continue
                left, top = max(0, math.floor(x) - padding), max(0, math.floor(y) - padding)
                right, bottom = min(width, math.ceil(x + w) + padding), min(height, math.ceil(y + h) + padding)
                if right > left and bottom > top:
                    # Whole text panels, including their anti-aliased edges, are editable.
                    text[frame, top:bottom, left:right] = 1
                    detections += 1
        if padding:
            text = F.max_pool2d(text[:, None], padding * 2 + 1, stride=1, padding=padding)[:, 0]
        # Share nearby detections to cover short subtitle changes and detector flicker.
        text = F.max_pool3d(text[None, None], (7, 1, 1), stride=1, padding=(3, 0, 0))[0, 0]
        combined = torch.maximum(performer_mask.float(), text)
        details = dict(clip_details, remove_text=True, text_boxes_detected=detections,
                       text_frames_detected=detected_frames, text_mask_pixels=int((text > 0.5).sum()))
        return combined, details


NODE_CLASS_MAPPINGS = {"GenjTextRemovalMask": GenjTextRemovalMask}
NODE_DISPLAY_NAME_MAPPINGS = {"GenjTextRemovalMask": "Include On-screen Text in Removal Mask"}
