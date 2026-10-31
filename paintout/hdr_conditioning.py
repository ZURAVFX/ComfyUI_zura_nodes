"""Read official LTX HDR scene embeddings without a patched dependency node."""
import hashlib
from pathlib import Path

import safetensors
import torch


def _context(tensor, label):
    if tensor.ndim == 2:
        tensor = tensor.unsqueeze(0)
    if tensor.ndim != 3 or any(size < 1 for size in tensor.shape):
        raise ValueError(f"HDR {label} context must have nonempty [batch, tokens, channels] dimensions.")
    if not tensor.is_floating_point() or not torch.isfinite(tensor).all():
        raise ValueError(f"HDR {label} context must contain finite floating-point values.")
    return tensor


def load_hdr_conditioning(path):
    """Return native AV conditioning, preserving the file's floating precision."""
    with safetensors.safe_open(str(path), framework="pt", device="cpu") as source:
        keys = set(source.keys())
        video_key = next((key for key in ("video_context", "video_prompt_embeds") if key in keys), None)
        if video_key is None:
            raise ValueError("HDR scene embeddings need video_context or video_prompt_embeds.")
        video = _context(source.get_tensor(video_key), "video")
        if video.shape[-1] == 6144:
            result = video
        elif video.shape[-1] == 4096:
            audio_key = next((key for key in ("audio_context", "audio_prompt_embeds") if key in keys), None)
            if audio_key is None:
                raise ValueError("HDR scene embeddings need audio_context or audio_prompt_embeds for LTX audio/video conditioning.")
            audio = _context(source.get_tensor(audio_key), "audio")
            if audio.shape[-1] != 2048 or audio.shape[:-1] != video.shape[:-1]:
                raise ValueError("HDR audio context must match video batch/tokens and have 2048 channels.")
            if audio.dtype != video.dtype:
                raise ValueError("HDR audio and video contexts must use the same floating precision.")
            result = torch.cat((video, audio), dim=-1)
        else:
            raise ValueError("HDR video context needs 4096 channels, or 6144 channels with audio already included.")
    return [[result, {}]]


class ZuraPaintoutHDRConditioning:
    @classmethod
    def INPUT_TYPES(cls):
        import folder_paths
        files = [name for name in folder_paths.get_filename_list("embeddings") if name.lower().endswith(".safetensors")]
        return {"required": {"file_name": (sorted(files) or [""],)}}

    RETURN_TYPES = ("CONDITIONING",)
    RETURN_NAMES = ("conditioning",)
    FUNCTION = "load"
    CATEGORY = "Zura/Paintout"

    @staticmethod
    def _path(file_name):
        import folder_paths
        path = folder_paths.get_full_path("embeddings", file_name)
        if not path or not Path(path).is_file():
            raise FileNotFoundError("HDR scene embeddings were not found in ComfyUI/models/embeddings.")
        if Path(path).suffix.lower() != ".safetensors":
            raise ValueError("HDR scene embeddings must use safetensors format.")
        return path

    @classmethod
    def IS_CHANGED(cls, file_name):
        digest = hashlib.sha256()
        with open(cls._path(file_name), "rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def load(self, file_name):
        return (load_hdr_conditioning(self._path(file_name)),)
