"""ComfyLink AE batch input. MIT. Uses only ComfyUI's existing dependencies."""
from pathlib import Path
import hashlib
import re
import numpy as np
import torch
from PIL import Image, ImageOps
import folder_paths


def frame_paths(folder):
    if not re.fullmatch(r"ComfyLink/[a-f0-9]{32}", folder.replace("\\", "/")):
        raise ValueError("ComfyLink expects its uploaded job folder, not an arbitrary disk path")
    base = Path(folder_paths.get_input_directory()).resolve()
    target = (base / folder).resolve()
    if base not in target.parents:
        raise ValueError("Input folder is outside ComfyUI/input")
    files = sorted(p for p in target.glob("*.png") if re.fullmatch(r"\d{6}\.png", p.name))
    if not files:
        raise ValueError("No ComfyLink input frames were uploaded")
    if len(files) > 10000:
        raise ValueError("Frame limit exceeded")
    for i, path in enumerate(files, 1):
        if path.name != f"{i:06d}.png" or path.is_symlink() or base not in path.resolve().parents:
            raise ValueError("Input sequence is incomplete or contains an unsafe file")
    return files


class ComfyLinkLoadFrames:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"folder": ("STRING", {"default": ""}),
                             "fps": ("FLOAT", {"default": 25.0, "min": 1.0, "max": 240.0})}}

    RETURN_TYPES = ("IMAGE", "MASK", "FLOAT", "INT")
    RETURN_NAMES = ("images", "alpha_mask", "fps", "frame_count")
    FUNCTION = "load"
    CATEGORY = "ComfyLink"
    DESCRIPTION = "Loads the AE source frames as one batch. The mask is 1 minus source alpha, following LoadImage."

    @classmethod
    def IS_CHANGED(cls, folder, fps):
        try:
            state = "|".join(f"{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}" for p in frame_paths(folder))
            return hashlib.sha256((str(fps) + state).encode()).hexdigest()
        except (OSError, ValueError):
            return float("nan")

    def load(self, folder, fps):
        images, masks, size = [], [], None
        for path in frame_paths(folder):
            with Image.open(path) as source:
                rgba = ImageOps.exif_transpose(source).convert("RGBA")
                if size is None:
                    size = rgba.size
                if rgba.size != size:
                    raise ValueError("All AE frames must have the same dimensions")
                data = np.array(rgba, dtype=np.float32) / 255.0
                images.append(torch.from_numpy(data[:, :, :3].copy()))
                masks.append(torch.from_numpy(1.0 - data[:, :, 3]))
        return (torch.stack(images), torch.stack(masks), float(fps), len(images))


NODE_CLASS_MAPPINGS = {"ComfyLinkLoadFrames": ComfyLinkLoadFrames}
NODE_DISPLAY_NAME_MAPPINGS = {"ComfyLinkLoadFrames": "ComfyLink Load Frames (AE_INPUT)"}
