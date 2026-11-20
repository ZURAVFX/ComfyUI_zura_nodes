"""Rasterise the image guidance drawn in the ComfyUI canvas editor."""
from __future__ import annotations

import json
import math
import re

import numpy as np
from PIL import Image, ImageChops, ImageDraw
import torch


def _stroke(draw, stroke, width, height, layer):
    tool = stroke["tool"]
    points = stroke["points"]
    brush = stroke["width"]
    tools = {"brush", "erase", "arrow", "box"} if layer == "markup" else {"brush", "erase"}
    if (
        tool not in tools or type(brush) is not int or not 1 <= brush <= 512
        or not 1 <= len(points) <= 4096
    ):
        raise ValueError("Invalid drawing stroke.")
    if any(len(point) != 2 or any(type(value) not in (int, float) or not 0 <= value <= 1
                                 for value in point) for point in points):
        raise ValueError("Drawing coordinates are outside the frame.")
    path = [(round(x * (width - 1)), round(y * (height - 1))) for x, y in points]
    if layer == "markup":
        colour = stroke.get("colour", "")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
            raise ValueError("Invalid markup colour.")
        fill = tuple(bytes.fromhex(colour[1:])) + (255,) if tool != "erase" else (0, 0, 0, 0)
    elif layer == "alpha":
        fill = 0 if tool == "brush" else 255
    else:
        fill = 0 if tool == "erase" else 255

    if tool == "box":
        first, last = path[0], path[-1]
        bounds = tuple(min(a, b) for a, b in zip(first, last)) + tuple(max(a, b) for a, b in zip(first, last))
        draw.rectangle(bounds, outline=fill, width=brush)
    elif tool == "arrow":
        start, end = path[0], path[-1]
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        length = max(brush * 3, 12)
        draw.line([start, end], fill=fill, width=brush)
        for direction in (angle - math.pi / 6, angle + math.pi / 6):
            tip = (round(end[0] - length * math.cos(direction)), round(end[1] - length * math.sin(direction)))
            draw.line([end, tip], fill=fill, width=brush)
    else:
        draw.line(path, fill=fill, width=brush, joint="curve")
        before, after = (brush - 1) // 2, brush // 2
        for x, y in path:
            draw.ellipse((x - before, y - before, x + after, y + after), fill=fill)


def _render(drawing, width, height):
    try:
        if len(drawing) > 2_000_000:
            raise ValueError("Drawing exceeds the supported size.")
        state = json.loads(drawing) if drawing else {}
        if not isinstance(state, dict) or (state and state["version"] != 1):
            raise ValueError("Unsupported drawing version.")
        if state and (state["width"], state["height"]) != (width, height):
            raise ValueError("The frame dimensions have changed. Reopen Draw guidance and review the drawing.")
        mask = Image.new("L", (width, height))
        markup = Image.new("RGBA", (width, height))
        visibility = Image.new("L", (width, height), 255)
        for layer, image in (("mask", mask), ("markup", markup), ("alpha", visibility)):
            strokes = state.get(layer, [])
            if not isinstance(strokes, list) or len(strokes) > 1024:
                raise ValueError("Too many strokes in a drawing layer.")
            draw = ImageDraw.Draw(image)
            for stroke in strokes:
                _stroke(draw, stroke, width, height, layer)
        alpha = ImageChops.multiply(markup.getchannel("A"), visibility)
        markup.putalpha(alpha)
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("Invalid drawing data. Reopen Draw guidance to edit the layers.") from exc
    return tuple(torch.from_numpy(np.asarray(image, dtype=np.float32) / 255).unsqueeze(0)
                 for image in (mask, markup, ImageChops.invert(alpha)))


class ZuraImageGuidance:
    CATEGORY = "Zura/Image"
    FUNCTION = "draw"
    OUTPUT_NODE = True
    RETURN_TYPES = ("IMAGE", "MASK", "IMAGE", "MASK")
    RETURN_NAMES = ("reference", "edit mask", "markup overlay", "markup alpha")
    DESCRIPTION = "Draw an edit mask, coloured annotations and their transparency on a single reference frame."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "frame": ("IMAGE", {"tooltip": "Connect a frame. For a batch, the editor uses its first image."}),
            },
            "optional": {
                "drawing": ("STRING", {"default": "", "hidden": True}),
                "preview_only": ("BOOLEAN", {"default": False, "hidden": True}),
            },
        }

    def draw(self, frame, drawing="", preview_only=False):
        if not len(frame):
            raise ValueError("Connect an image containing at least one frame.")
        reference = frame[:1]
        if preview_only:
            from nodes import PreviewImage

            preview = PreviewImage().save_images(reference, filename_prefix="zura_guidance/frame")
            return {"ui": {"zura_guidance_frame": preview["ui"]["images"]}}
        height, width = reference.shape[1:3]
        return reference, *_render(drawing, width, height)
