"""Combine native SAM text detections with the reviewed replacement mask."""
import math

import torch
import torch.nn.functional as F


def _component_rectangles(mask):
    """Return the unmerged, frame-local bounds of connected text components."""
    import cv2

    pixels = mask.detach().to(device="cpu", dtype=torch.uint8).numpy()
    count, _, stats, _ = cv2.connectedComponentsWithStats(pixels, connectivity=8)
    return [tuple(int(v) for v in row[:4]) for row in stats[1:count] if row[4] > 0]


def _fill_frame_component_bounds(mask):
    """Fill each frame's own component bounds before temporal holding.

    Review metadata may compact distant detections into broad rectangles. Those
    rectangles must never be used to create editable pixels.
    """
    import cv2

    pixels = mask.detach().to(device="cpu", dtype=torch.uint8).numpy()
    for frame in pixels:
        count, _, stats, _ = cv2.connectedComponentsWithStats(frame, connectivity=8)
        for left, top, width, height, area in stats[1:count]:
            if area > 0:
                frame[top:top + height, left:left + width] = 1
    return torch.from_numpy(pixels).to(device=mask.device, dtype=mask.dtype)


def text_regions(mask, limit=12):
    """Compact the text-only union into review-space rectangles.

    Connected components coalesce detections in pixel space instead of comparing
    every detector box with every other box. The final overlap merge is bounded
    to at most twelve rectangles. Many tiny detections share horizontal bands.
    """
    rectangles = _component_rectangles(mask)
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
                    "tooltip": "Keep detected text panels editable through each tracking segment. Moving text can create a wider removal area."}),
                    "tracking_segments": ("GENJ_TRACK_SEGMENTS",)}}

    RETURN_TYPES = ("MASK", "GENJ_CLIP")
    FUNCTION = "combine"
    CATEGORY = "Zura/Artist Studio"

    def combine(self, performer_mask, text_mask, text_boxes, clip_details, padding=5,
                hold_regions=True, tracking_segments=None):
        count, height, width = performer_mask.shape
        if text_mask.ndim != 3 or len(text_mask) != count or len(text_boxes) != count:
            raise ValueError("Text detection and the performer mask must cover the same frames.")
        if count == 0 or min(height, width, *text_mask.shape[1:]) <= 0:
            raise ValueError("Provide non-empty text and performer masks.")
        segments = None
        if tracking_segments is not None:
            from .cut_tracking import _segments

            segments = _segments(tracking_segments)
            if (tracking_segments["frames"] != count or tracking_segments["height"] != height
                    or tracking_segments["width"] != width):
                raise ValueError("Tracking segment frame count and raster must match the performer mask.")
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
        text = _fill_frame_component_bounds(text)
        union = text.amax(dim=0)
        regions = text_regions(union)
        text_regions_by_shot = None
        if segments is None:
            if hold_regions:
                # Preserve legacy behavior when no tracking segment metadata is connected.
                text = union[None].expand(count, -1, -1)
            else:
                # Compatibility option: share only nearby detections across seven frames.
                text = F.max_pool3d(text[None, None], (7, 1, 1), stride=1, padding=(3, 0, 0))[0, 0]
        else:
            held_text = torch.empty_like(text)
            text_regions_by_shot = []
            for segment in segments:
                start, end = segment["start"], segment["end"]
                shot_union = text[start:end].amax(dim=0)
                text_regions_by_shot.append({"start": start, "end": end,
                                             "regions": text_regions(shot_union)})
                if hold_regions:
                    # Hold detected text only within this continuous shot.
                    held_text[start:end] = shot_union
                else:
                    # The seven-frame window is padded independently per shot.
                    held_text[start:end] = F.max_pool3d(
                        text[start:end][None, None], (7, 1, 1), stride=1,
                        padding=(3, 0, 0))[0, 0]
            text = held_text
        combined = torch.maximum(performer_mask.float(), text)
        details = dict(clip_details, remove_text=True, text_boxes_detected=detections,
                       text_frames_detected=detected_frames, text_mask_pixels=int((text > 0.5).sum()),
                       text_regions=regions, text_regions_size=[width, height],
                       text_regions_held=bool(hold_regions))
        if text_regions_by_shot is not None:
            details["text_regions_by_shot"] = text_regions_by_shot
        return combined, details


class ZuraTextBackgroundRepairMask:
    """Crop reviewed background-only text panels for a native cleanup branch.

    The node never invents editable pixels: the candidate text area is intersected
    with the already-approved combined mask. A panel that touches or approaches
    the genuine performer mask in any frame stays on the normal generation path.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"combined_mask": ("MASK",),
                             "performer_mask": ("MASK",),
                             "clip_details": ("GENJ_CLIP",)},
                "optional": {"context": ("INT", {"default": 32, "min": 0, "max": 128}),
                             "performer_guard": ("MASK", {"tooltip":
                                 "Optional genuine performer union for the complete continuous shot. "
                                 "Keeps cleanup eligibility and crop bounds stable across windows."})}}

    RETURN_TYPES = ("MASK", "MASK", "INT", "INT", "INT", "INT", "BOOLEAN")
    RETURN_NAMES = ("crop_text_mask", "generation_mask", "crop_width", "crop_height",
                    "crop_x", "crop_y", "has_background_text")
    FUNCTION = "adapt"
    CATEGORY = "Zura/Artist Studio"

    def adapt(self, combined_mask, performer_mask, clip_details, context=32, performer_guard=None):
        if not isinstance(combined_mask, torch.Tensor) or not isinstance(performer_mask, torch.Tensor):
            raise ValueError("Combined and performer masks must be tensors.")
        if combined_mask.ndim != 3 or performer_mask.ndim != 3:
            raise ValueError("Combined and performer masks must be three-dimensional frame masks.")
        if tuple(combined_mask.shape) != tuple(performer_mask.shape):
            raise ValueError("Combined and performer masks must have matching frames and spatial dimensions.")
        frames, height, width = combined_mask.shape
        if frames <= 0 or height <= 0 or width <= 0:
            raise ValueError("Combined and performer masks must have positive frame and spatial dimensions.")
        if combined_mask.device != performer_mask.device:
            raise ValueError("Combined and performer masks must be on the same device.")
        if not torch.isfinite(combined_mask).all() or not torch.isfinite(performer_mask).all():
            raise ValueError("Combined and performer masks must contain only finite values.")
        if not isinstance(context, int) or context < 0 or context > 128:
            raise ValueError("Crop context must be an integer from 0 to 128 pixels.")
        if not isinstance(clip_details, dict):
            raise ValueError("Clip details must be a mapping containing reviewed text regions.")

        performer_union = (performer_mask > 0.5).any(dim=0)
        if performer_guard is not None:
            if (not isinstance(performer_guard, torch.Tensor)
                    or tuple(performer_guard.shape) != (1, height, width)
                    or performer_guard.device != performer_mask.device):
                raise ValueError("The shot performer guard must be one mask at the matching raster and device.")
            if (not bool(torch.isfinite(performer_guard).all())
                    or bool((performer_guard < 0).any()) or bool((performer_guard > 1).any())):
                raise ValueError("The shot performer guard must contain finite values from zero to one.")
            guarded_union = performer_guard[0] > 0.5
            if bool((performer_union & ~guarded_union).any()):
                raise ValueError("The shot performer guard must include every genuine performer pixel in this window.")
            performer_union = guarded_union

        regions = clip_details.get("text_regions") or []
        generation_mask = combined_mask
        if not regions:
            crop_height, crop_width = min(8, height), min(8, width)
            return (combined_mask.new_zeros((frames, crop_height, crop_width)), generation_mask,
                    crop_width, crop_height, 0, 0, False)

        try:
            source_width, source_height = (float(value) for value in clip_details["text_regions_size"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Reviewed text regions need their source width and height.") from None
        if (not math.isfinite(source_width) or not math.isfinite(source_height)
                or source_width <= 0 or source_height <= 0):
            raise ValueError("Reviewed text region dimensions must be positive and finite.")

        # A single spatial union protects panels that are close to the performer
        # even when the person moves away from them in other frames.
        performer_yx = torch.nonzero(performer_union, as_tuple=False)
        approved = combined_mask > 0.5
        background_mask = torch.zeros_like(approved)
        eligible_rectangles = []

        for region in regions:
            if not isinstance(region, dict):
                continue
            try:
                x, y, box_width, box_height = (float(region[key]) for key in ("x", "y", "width", "height"))
            except (KeyError, TypeError, ValueError):
                continue
            if (not all(math.isfinite(value) for value in (x, y, box_width, box_height))
                    or box_width <= 0 or box_height <= 0):
                continue
            right_value, bottom_value = x + box_width, y + box_height
            if not math.isfinite(right_value) or not math.isfinite(bottom_value):
                continue
            scaled = (x * width / source_width, y * height / source_height,
                      right_value * width / source_width, bottom_value * height / source_height)
            if not all(math.isfinite(value) for value in scaled):
                continue
            left = max(0, min(width, math.floor(scaled[0])))
            top = max(0, min(height, math.floor(scaled[1])))
            right = max(0, min(width, math.ceil(scaled[2])))
            bottom = max(0, min(height, math.ceil(scaled[3])))
            if right <= left or bottom <= top:
                continue

            if performer_yx.numel():
                py, px = performer_yx.unbind(dim=1)
                # Distance from each performer pixel to the closed rectangle;
                # the 32px guard is spatial and spans every frame in the shot.
                dx = torch.maximum(torch.maximum(left - px, px - (right - 1)), torch.zeros_like(px))
                dy = torch.maximum(torch.maximum(top - py, py - (bottom - 1)), torch.zeros_like(py))
                if torch.any(dx.square() + dy.square() <= 32 * 32):
                    continue

            # Restrict repair to pixels the artist already approved for editing.
            background_mask[:, top:bottom, left:right] |= approved[:, top:bottom, left:right]
            eligible_rectangles.append((left, top, right, bottom))

        if not background_mask.any():
            crop_height, crop_width = min(8, height), min(8, width)
            return (combined_mask.new_zeros((frames, crop_height, crop_width)), generation_mask,
                    crop_width, crop_height, 0, 0, False)

        if performer_guard is not None:
            # Shot-level rectangles keep LaMa's context identical for repeated
            # frames even when other panels are inactive in a particular window.
            min_x = min(rectangle[0] for rectangle in eligible_rectangles)
            min_y = min(rectangle[1] for rectangle in eligible_rectangles)
            max_x = max(rectangle[2] for rectangle in eligible_rectangles) - 1
            max_y = max(rectangle[3] for rectangle in eligible_rectangles) - 1
        else:
            active_yx = torch.nonzero(background_mask.any(dim=0), as_tuple=False)
            min_y, min_x = (int(value) for value in active_yx.amin(dim=0).tolist())
            max_y, max_x = (int(value) for value in active_yx.amax(dim=0).tolist())
        crop_x = max(0, ((min_x - context) // 8) * 8)
        crop_y = max(0, ((min_y - context) // 8) * 8)
        crop_right = min(width, ((max_x + 1 + context + 7) // 8) * 8)
        crop_bottom = min(height, ((max_y + 1 + context + 7) // 8) * 8)
        crop_width, crop_height = crop_right - crop_x, crop_bottom - crop_y
        crop_text_mask = background_mask[:, crop_y:crop_bottom, crop_x:crop_right].to(dtype=combined_mask.dtype)
        generation_mask = combined_mask * (~background_mask).to(dtype=combined_mask.dtype)
        return (crop_text_mask, generation_mask, crop_width, crop_height, crop_x, crop_y, True)


NODE_CLASS_MAPPINGS = {
    "GenjTextRemovalMask": GenjTextRemovalMask,
    "ZuraTextBackgroundRepairMask": ZuraTextBackgroundRepairMask,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "GenjTextRemovalMask": "Include On-screen Text in Removal Mask",
    "ZuraTextBackgroundRepairMask": "Prepare Background Text Cleanup",
}
