"""Combine native SAM text detections with the reviewed replacement mask."""
import math

import torch
import torch.nn.functional as F


def text_regions(mask, limit=12):
    """Compact the text-only union into review-space rectangles.

    Connected components coalesce detections in pixel space instead of comparing
    every detector box with every other box. The final overlap merge is bounded
    to at most twelve rectangles. Many tiny detections share horizontal bands.
    """
    import cv2

    pixels = mask.detach().to(device="cpu", dtype=torch.uint8).numpy()
    count, _, stats, _ = cv2.connectedComponentsWithStats(pixels, connectivity=8)
    rectangles = [tuple(int(v) for v in row[:4]) for row in stats[1:count] if row[4] > 0]
    rectangles.sort(key=lambda r: (r[1] + r[3] / 2, r[0]))

    def bounds(group):
        left = min(r[0] for r in group)
        top = min(r[1] for r in group)
        right = max(r[0] + r[2] for r in group)
        bottom = max(r[1] + r[3] for r in group)
        return left, top, right - left, bottom - top

    if len(rectangles) > limit:
        size = len(rectangles)
        rectangles = [bounds(rectangles[i * size // limit:(i + 1) * size // limit])
                      for i in range(limit)]
    merged = []
    for rectangle in rectangles:
        index = 0
        while index < len(merged):
            other = merged[index]
            if (rectangle[0] <= other[0] + other[2] and other[0] <= rectangle[0] + rectangle[2]
                    and rectangle[1] <= other[1] + other[3] and other[1] <= rectangle[1] + rectangle[3]):
                rectangle = bounds((rectangle, merged.pop(index)))
                index = 0
            else:
                index += 1
        merged.append(rectangle)
    return [{"x": x, "y": y, "width": w, "height": h}
            for x, y, w, h in sorted(merged, key=lambda r: (r[1], r[0]))]


class GenjTextRemovalMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"performer_mask": ("MASK",), "text_mask": ("MASK",),
                             "text_boxes": ("BOUNDING_BOX",), "clip_details": ("GENJ_CLIP",),
                             "padding": ("INT", {"default": 5, "min": 0, "max": 32})},
                "optional": {"hold_regions": ("BOOLEAN", {"default": True,
                    "tooltip": "Keep detected text panels editable throughout this continuous shot. Prepare cuts separately; moving text can create a wider removal area."})}}

    RETURN_TYPES = ("MASK", "GENJ_CLIP")
    FUNCTION = "combine"
    CATEGORY = "Zura/Artist Studio"

    def combine(self, performer_mask, text_mask, text_boxes, clip_details, padding=5, hold_regions=True):
        count, height, width = performer_mask.shape
        if text_mask.ndim != 3 or len(text_mask) != count or len(text_boxes) != count:
            raise ValueError("Text detection and the performer mask must cover the same frames.")
        if count == 0 or min(height, width, *text_mask.shape[1:]) <= 0:
            raise ValueError("Provide non-empty text and performer masks.")
        scale_x, scale_y = width / text_mask.shape[-1], height / text_mask.shape[-2]
        text = F.interpolate(text_mask[:, None].float(), size=(height, width), mode="nearest")[:, 0]
        text = (text > 0.5).to(device=performer_mask.device, dtype=torch.float32)
        detections = 0
        detected_frames = 0
        for frame, boxes in enumerate(text_boxes):
            frame_detected = bool(text[frame].any())
            for box in boxes or ():
                try:
                    x, y, w, h = (float(box[k]) for k in ("x", "y", "width", "height"))
                except (TypeError, ValueError, KeyError):
                    continue
                if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
                    continue
                x, y, w, h = x * scale_x, y * scale_y, w * scale_x, h * scale_y
                if not all(math.isfinite(v) for v in (x, y, w, h, x + w, y + h)):
                    continue
                left, top = max(0, math.floor(x) - padding), max(0, math.floor(y) - padding)
                right, bottom = min(width, math.ceil(x + w) + padding), min(height, math.ceil(y + h) + padding)
                if right > left and bottom > top:
                    # Whole text panels, including their anti-aliased edges, are editable.
                    text[frame, top:bottom, left:right] = 1
                    detections += 1
                    frame_detected = True
            detected_frames += int(frame_detected)
        if padding:
            text = F.max_pool2d(text[:, None], padding * 2 + 1, stride=1, padding=padding)[:, 0]
        union = text.amax(dim=0)
        regions = text_regions(union)
        if hold_regions:
            # Hold text only: the performer's mask must still follow their motion.
            for region in regions:
                x, y, w, h = (region[k] for k in ("x", "y", "width", "height"))
                union[y:y + h, x:x + w] = 1
            text = union[None].expand(count, -1, -1)
        else:
            # Compatibility option: share only nearby detections across seven frames.
            text = F.max_pool3d(text[None, None], (7, 1, 1), stride=1, padding=(3, 0, 0))[0, 0]
        combined = torch.maximum(performer_mask.float(), text)
        details = dict(clip_details, remove_text=True, text_boxes_detected=detections,
                       text_frames_detected=detected_frames, text_mask_pixels=int((text > 0.5).sum()),
                       text_regions=regions, text_regions_size=[width, height],
                       text_regions_held=bool(hold_regions))
        return combined, details


NODE_CLASS_MAPPINGS = {"GenjTextRemovalMask": GenjTextRemovalMask}
NODE_DISPLAY_NAME_MAPPINGS = {"GenjTextRemovalMask": "Include On-screen Text in Removal Mask"}
