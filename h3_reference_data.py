"""Attach already encoded H3 reference latents without running model inference."""
from __future__ import annotations

from collections.abc import Mapping

import torch


MAX_TENSOR_BYTES = 256 * 1024 * 1024
MAX_DIMENSION = 4096
_REFERENCE_BLOCK_KEYS = frozenset({"minimax_refs", "minimax_keyframes"})


def _checked_samples(value, label, *, audio=False):
    if not isinstance(value, Mapping) or "samples" not in value:
        raise ValueError(f"{label} must be a latent with a samples tensor.")
    if any(key != "samples" for key in value):
        raise ValueError(f"{label} contains latent metadata this adapter cannot preserve.")
    samples = value["samples"]
    if not isinstance(samples, torch.Tensor):
        raise ValueError(f"{label} samples must be a tensor.")
    if samples.layout != torch.strided:
        raise ValueError(f"{label} samples must use strided tensor storage.")
    if not samples.is_floating_point():
        raise ValueError(f"{label} samples must have a floating-point dtype.")
    if samples.ndim != (4 if audio else 5):
        expected = "[1, 32, 2, T]" if audio else "[1, 24, T, H, W]"
        raise ValueError(f"{label} samples must have shape {expected}.")
    shape = tuple(int(size) for size in samples.shape)
    if any(size <= 0 for size in shape):
        raise ValueError(f"{label} dimensions must be positive.")
    if any(size > MAX_DIMENSION for size in shape):
        raise ValueError(f"{label} dimensions cannot exceed {MAX_DIMENSION}.")
    if audio:
        if shape[:3] != (1, 32, 2):
            raise ValueError(f"{label} samples must have shape [1, 32, 2, T].")
    elif shape[:3] != (1, 24, 1):
        raise ValueError(f"{label} samples must have shape [1, 24, 1, H, W].")
    elif shape[-2] % 2 or shape[-1] % 2:
        raise ValueError(f"{label} height and width must be even for MiniMax H3 image references.")
    size_bytes = samples.numel() * samples.element_size()
    if size_bytes > MAX_TENSOR_BYTES:
        raise ValueError(f"{label} samples exceed the 256 MiB safety limit.")
    if not bool(torch.isfinite(samples).all().item()):
        raise ValueError(f"{label} samples must contain only finite values.")
    return samples


def _reference_block(samples, kind):
    if kind == "image":
        return {
            "kind": "image",
            "latent_h": int(samples.shape[-2]),
            "latent_w": int(samples.shape[-1]),
            "latent": samples,
        }
    return {
        "kind": "audio",
        "ref_audio_t": int(samples.shape[-1]),
        "audio_latent": samples,
    }


def _validate_conditioning(positive):
    if not isinstance(positive, (list, tuple)) or not positive:
        raise ValueError("Positive conditioning must be a non-empty list of pairs.")

    for index, item in enumerate(positive):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(f"Positive conditioning item {index} must be an [embedding, metadata] pair.")
        embedding, metadata = item
        if not isinstance(embedding, torch.Tensor):
            raise ValueError(f"Positive conditioning embedding {index} must be a tensor.")
        if embedding.layout != torch.strided or not embedding.is_floating_point():
            raise ValueError(f"Positive conditioning embedding {index} must be a strided floating-point tensor.")
        if embedding.ndim != 3 or embedding.shape[0] != 1 or embedding.shape[2] != 5120 or embedding.shape[1] <= 0:
            raise ValueError(f"Positive conditioning embedding {index} must have shape [1, N, 5120].")
        # H3's native hidden width is fixed at 5120; only the variable token
        # sequence length is subject to this dimension cap.
        if int(embedding.shape[1]) > MAX_DIMENSION:
            raise ValueError(f"Positive conditioning embedding {index} dimensions cannot exceed {MAX_DIMENSION}.")
        if embedding.numel() * embedding.element_size() > MAX_TENSOR_BYTES:
            raise ValueError(f"Positive conditioning embedding {index} exceeds the 256 MiB safety limit.")
        if not bool(torch.isfinite(embedding).all().item()):
            raise ValueError(f"Positive conditioning embedding {index} must contain only finite values.")
        if not isinstance(metadata, Mapping):
            raise ValueError(f"Positive conditioning metadata {index} must be a mapping.")

        if "minimax_refs" in metadata:
            existing_refs = metadata["minimax_refs"]
            if not isinstance(existing_refs, list):
                # Refuse to replace a future or malformed native payload.
                raise ValueError("Positive conditioning has an unsupported minimax_refs value.")
            if existing_refs:
                raise ValueError("Positive conditioning already has MiniMax H3 references attached.")
        for key in metadata:
            normalized = str(key).casefold()
            if "ref" in normalized and key not in _REFERENCE_BLOCK_KEYS:
                raise ValueError(f"Positive conditioning contains unsupported reference metadata: {key}.")


class ZuraH3AttachEncodedReferences:
    """Attach pre-encoded image/audio latents in H3's native reference order."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "opening_latent": ("LATENT",),
                "character_latent": ("LATENT",),
            },
            "optional": {"audio_latent": ("LATENT",)},
        }

    RETURN_TYPES = ("CONDITIONING",)
    RETURN_NAMES = ("positive",)
    FUNCTION = "attach"
    CATEGORY = "Zura/Artist Studio/Data"

    def attach(self, positive, opening_latent, character_latent, audio_latent=None):
        _validate_conditioning(positive)
        opening = _checked_samples(opening_latent, "Opening reference")
        character = _checked_samples(character_latent, "Character reference")
        blocks = [
            _reference_block(opening, "image"),
            _reference_block(character, "image"),
        ]
        if audio_latent is not None:
            audio = _checked_samples(audio_latent, "Audio reference", audio=True)
            blocks.append(_reference_block(audio, "audio"))

        # This is the same native helper and payload contract used by
        # MiniMaxH3ReferenceToVideo.  It shallow-copies metadata per item and
        # leaves embeddings and reference tensors untouched.
        import node_helpers

        return (node_helpers.conditioning_set_values(positive, {"minimax_refs": blocks}),)


NODE_CLASS_MAPPINGS = {
    "ZuraH3AttachEncodedReferences": ZuraH3AttachEncodedReferences,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ZuraH3AttachEncodedReferences": "Zura · Attach H3 Reference Latents",
}
