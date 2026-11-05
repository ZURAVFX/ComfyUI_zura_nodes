"""Generate images using the explicitly connected Gemini session, without a browser driver."""
from __future__ import annotations

import asyncio
import io
import tempfile

import numpy as np
from PIL import Image, ImageOps
import torch

from .chatgpt_image import _prompt, _save_references, _sizes

class ZuraGeminiImage:
    CATEGORY = "Zura/Image"
    FUNCTION = "generate"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "actual_size")
    DESCRIPTION = "Generate in the Gemini website using your Google account. Dimensions are requests, not guaranteed output sizes."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": "", "tooltip": "Describe the image or edit you want."}),
                "size": (list(_sizes), {"default": "Auto", "tooltip": "Requested in the prompt. Gemini decides the actual output size."}),
                "custom_width": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 64}),
                "custom_height": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 64}),
                "timeout_seconds": ("INT", {"default": 300, "min": 60, "max": 1800, "step": 30}),
            },
            "optional": {f"reference_{i}": ("IMAGE", {"tooltip": "Optional image or image batch. Gemini account upload limits apply."}) for i in range(1, 9)},
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    async def generate(self, prompt, size, custom_width, custom_height, timeout_seconds, **references):
        return await asyncio.to_thread(self._generate_sync, prompt, size, custom_width, custom_height, timeout_seconds, **references)

    def _generate_sync(self, prompt, size, custom_width, custom_height, timeout_seconds, **references):
        text = _prompt(prompt, size, custom_width, custom_height)
        with tempfile.TemporaryDirectory(prefix="zura-gemini-") as temp:
            paths = _save_references([references.get(f"reference_{i}") for i in range(1, 9)], temp)
            from .web_sessions import generate_image
            image_bytes = generate_image("gemini", text, paths, timeout_seconds)
        with Image.open(io.BytesIO(image_bytes)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            width, height = im.size
            result = torch.from_numpy(np.array(im, dtype=np.float32) / 255.0).unsqueeze(0)
        return (result, f"{width} × {height}")


NODE_CLASS_MAPPINGS = {"ZuraGeminiImage": ZuraGeminiImage}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraGeminiImage": "Zura · Gemini Image"}
