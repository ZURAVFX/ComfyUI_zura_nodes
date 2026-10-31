"""ChatGPT website image generation for Zura Nodes.

Uses the user's existing Firefox website session through an isolated direct-request client.
No Codex, paid developer API or browser automation. The website may change at any time.
"""
from __future__ import annotations

import asyncio
import io
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
import torch

_sizes = {
    "Auto": None,
    "Square (1024 × 1024)": (1024, 1024),
    "Portrait (1024 × 1536)": (1024, 1536),
    "Landscape (1536 × 1024)": (1536, 1024),
    "Portrait 9:16 (1080 × 1920)": (1080, 1920),
    "Landscape 16:9 (1920 × 1080)": (1920, 1080),
    "Custom": "custom",
}


def _prompt(prompt, size, width, height):
    text = prompt.strip()
    if not text:
        raise ValueError("Enter an image prompt before queuing.")
    text = "Create an image based on these instructions:\n\n" + text
    dims = _sizes.get(size)
    if dims == "custom":
        dims = (width, height)
    if dims:
        w, h = dims
        text += f"\n\nPlease create the image with a {w}:{h} aspect ratio, targeting {w} x {h} pixels if possible."
    return text


def _save_references(images, directory):
    paths = []
    for tensor in images:
        if tensor is None:
            continue
        for frame in tensor:
            array = (frame.detach().cpu().numpy().clip(0, 1) * 255).round().astype(np.uint8)
            if array.shape[-1] == 1:
                array = array[:, :, 0]
            path = Path(directory) / f"reference_{len(paths)+1:03d}.png"
            Image.fromarray(array).save(path)
            paths.append(str(path))
    return paths


def _interrupt():
    from comfy.model_management import throw_exception_if_processing_interrupted
    throw_exception_if_processing_interrupted()


class ZuraChatGPTImage:
    CATEGORY = "Zura/Image"
    FUNCTION = "generate"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "actual_size")
    DESCRIPTION = "Generate in the ChatGPT website using your own signed-in account. Dimensions are requests, not guaranteed output sizes."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": "", "tooltip": "Describe the image or edit you want."}),
                "size": (list(_sizes), {"default": "Auto", "tooltip": "Requested in the prompt. ChatGPT decides the actual output size."}),
                "custom_width": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 64}),
                "custom_height": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 64}),
                "timeout_seconds": ("INT", {"default": 300, "min": 60, "max": 1800, "step": 30}),
            },
            "optional": {f"reference_{i}": ("IMAGE", {"tooltip": "Optional image or image batch. ChatGPT account upload limits apply."}) for i in range(1, 9)},
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    async def generate(self, prompt, size, custom_width, custom_height, timeout_seconds, **references):
        return await asyncio.to_thread(self._generate_sync, prompt, size, custom_width, custom_height, timeout_seconds, **references)

    def _generate_sync(self, prompt, size, custom_width, custom_height, timeout_seconds, **references):
        text = _prompt(prompt, size, custom_width, custom_height)
        with tempfile.TemporaryDirectory(prefix="zura-chatgpt-") as temp:
            paths = _save_references([references.get(f"reference_{i}") for i in range(1, 9)], temp)
            from .web_sessions import generate_image
            image_bytes = generate_image("chatgpt", text, paths, timeout_seconds)
        with Image.open(io.BytesIO(image_bytes)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            width, height = im.size
            result = torch.from_numpy(np.array(im, dtype=np.float32) / 255.0).unsqueeze(0)
        return (result, f"{width} × {height}")


NODE_CLASS_MAPPINGS = {"ZuraChatGPTImage": ZuraChatGPTImage}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraChatGPTImage": "Zura · ChatGPT Image"}
