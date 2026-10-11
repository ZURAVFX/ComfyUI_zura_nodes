"""Thin mask-selection adapters; segmentation stays in visible native nodes."""
import json
import math

import torch

CATEGORY = "Zura/Artist Studio"
MAX_POINTS = 32
MAX_POINT_TEXT = 16384


class _PointFormatError(ValueError):
    pass


def _image_shape(images, single=False):
    if (not isinstance(images, torch.Tensor) or images.ndim != 4 or images.shape[-1] != 3 or
            min(images.shape[:3]) < 1 or not images.is_floating_point()):
        raise ValueError("Choose a valid colour image before selecting an area.")
    if single and images.shape[0] != 1:
        raise ValueError("Use one opening frame to place selection points.")
    return tuple(int(size) for size in images.shape[:3])


def _point_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _PointFormatError("Each selection point must have one position and one include setting.")
        result[key] = value
    return result


def _invalid_number(value):
    raise _PointFormatError("Place selection points inside the image using finite positions.")


def clean_points(value, require_positive=False):
    """Validate saved artist clicks without changing their normalized positions."""
    if not isinstance(value, list) or len(value) > MAX_POINTS:
        raise ValueError("Choose up to 32 selection points.")
    cleaned = []
    for point in value:
        if not isinstance(point, dict) or set(point) != {"x", "y", "include"}:
            raise ValueError("Each selection point needs a position and an include setting.")
        x, y = point["x"], point["y"]
        if (type(x) not in (int, float) or type(y) not in (int, float) or
                not 0 <= x <= 1 or not 0 <= y <= 1 or not math.isfinite(x) or not math.isfinite(y)):
            raise ValueError("Place selection points inside the image using finite positions.")
        if type(point["include"]) is not bool:
            raise ValueError("Choose include or exclude for each selection point.")
        cleaned.append({"x": x, "y": y, "include": point["include"]})
    if require_positive and not any(point["include"] for point in cleaned):
        raise ValueError("Add at least one point inside the area you want to change.")
    return cleaned


class ZuraWholeSceneMask:
    """All frames are selected without running a detector or reading pixels."""
    CATEGORY = CATEGORY
    FUNCTION = "select"
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("whole_scene_mask",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",)}}

    def select(self, images):
        shape = _image_shape(images)
        return (torch.ones(shape, dtype=torch.float32, device=images.device),)


class ZuraMaskPoints:
    """Convert image-relative artist clicks to native SAM pixel coordinates."""
    CATEGORY = CATEGORY
    FUNCTION = "coordinates"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("positive_coords", "negative_coords")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",), "points_json": ("STRING", {
            "default": "[]", "multiline": False,
            "tooltip": "Selection points relative to the actual image: x, y and include."})}}

    def coordinates(self, image, points_json):
        _, height, width = _image_shape(image, single=True)
        if not isinstance(points_json, str) or len(points_json) > MAX_POINT_TEXT:
            raise ValueError("Choose between one and 32 selection points.")
        try:
            points = json.loads(points_json, parse_constant=_invalid_number, object_pairs_hook=_point_object)
        except _PointFormatError as error:
            raise ValueError(str(error)) from error
        except (ValueError, RecursionError) as error:
            raise ValueError("The selection points could not be read. Place the points again.") from error
        points = clean_points(points, require_positive=True)
        positive, negative = [], []
        for point in points:
            x, y = point["x"], point["y"]
            pixel = {"x": min(width - 1, math.floor(x * width)),
                     "y": min(height - 1, math.floor(y * height))}
            (positive if point["include"] else negative).append(pixel)
        return json.dumps(positive, separators=(",", ":")), json.dumps(negative, separators=(",", ":"))


NODE_CLASS_MAPPINGS = {node.__name__: node for node in (ZuraWholeSceneMask, ZuraMaskPoints)}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraWholeSceneMask": "Zura · Select Whole Scene",
                            "ZuraMaskPoints": "Zura · Selection Points"}
