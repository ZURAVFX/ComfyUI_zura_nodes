"""Original high-depth ComfyLink nodes. SPDX-License-Identifier: MIT.

See float_io.py for the full MIT permission and warranty notice.
These nodes preserve declared sample semantics. They perform no model-specific
normalisation or colour conversion; downstream IMAGE nodes can still clip data.
"""
from fractions import Fraction
import copy
import uuid

import numpy as np
import torch
import folder_paths

from .float_io import load_transfer, write_transfer, write_exr, canonical_manifest_bytes


class ZuraComfyLinkLoadFloatFrames:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"manifest": ("STRING", {"default": ""}),
                             "alpha_operation": (["preserve", "unpremultiply"], {"default": "preserve"})}}

    RETURN_TYPES = ("IMAGE", "MASK", "COMFYLINK_FRAME_METADATA")
    RETURN_NAMES = ("images", "alpha_mask", "frame_metadata")
    FUNCTION = "load"
    CATEGORY = "ComfyLink/High Depth"
    DESCRIPTION = "Loads finite RGBA float32 or AE uint16 samples without gamma, gamut or range conversion. IMAGE contains the stored RGB; MASK is 1-alpha. Metadata retains original alpha and declared colour semantics."

    @classmethod
    def IS_CHANGED(cls, manifest, alpha_operation="preserve"):
        try:
            import hashlib
            _, wire = load_transfer(folder_paths.get_input_directory(), manifest)
            return hashlib.sha256(canonical_manifest_bytes(wire) + alpha_operation.encode()).hexdigest()
        except (OSError, ValueError):
            return float("nan")

    def load(self, manifest, alpha_operation="preserve"):
        rgba, wire = load_transfer(folder_paths.get_input_directory(), manifest)
        transformations = []
        if alpha_operation not in {"preserve", "unpremultiply"}:
            raise ValueError("Unknown alpha operation")
        if alpha_operation == "unpremultiply":
            if wire["alphaAssociation"] != "premultiplied":
                raise ValueError("Unpremultiply requires declared premultiplied input")
            np.divide(rgba[..., :3], rgba[..., 3:4], out=rgba[..., :3], where=rgba[..., 3:4] != 0)
            if not np.isfinite(rgba).all():
                raise ValueError("Unpremultiply produced nonfinite samples")
            wire = copy.deepcopy(wire)
            wire["alphaAssociation"] = "straight"
            transformations.append({"operation": "unpremultiply", "zeroAlphaPolicy": "preserve_rgb", "explicit": True})
        alpha = torch.from_numpy(rgba[..., 3].copy())
        metadata = {"manifest": wire, "original_alpha": alpha, "transformations": transformations,
                    "sampleSemantics": "declared; float32 dtype alone does not imply linear light or model fidelity"}
        return (torch.from_numpy(rgba[..., :3].copy()), 1.0 - alpha, metadata)


class ZuraComfyLinkSaveFloatFrames:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "frame_metadata": ("COMFYLINK_FRAME_METADATA",),
                             "exr_storage": (["float32", "half"], {"default": "float32"})},
                "optional": {"alpha_mask": ("MASK",), "fps": ("FLOAT", {"default": 25.0, "min": 0.001, "max": 1000.0})}}

    RETURN_TYPES = ("STRING", "COMFYLINK_FRAME_METADATA")
    RETURN_NAMES = ("manifest", "frame_metadata")
    OUTPUT_NODE = True
    FUNCTION = "save"
    CATEGORY = "ComfyLink/High Depth"
    DESCRIPTION = "Saves raw FLOAT RGBA plus FLOAT EXR (HALF only when explicitly selected). Alpha comes from the connected MASK or preserved metadata. No hidden clipping, gamma, gamut or alpha conversion."

    def save(self, images, frame_metadata, exr_storage="float32", alpha_mask=None, fps=None):
        if not isinstance(images, torch.Tensor) or images.dtype != torch.float32 or images.ndim != 4 or images.shape[-1] != 3:
            raise ValueError("Expected float32 NHWC RGB IMAGE batch")
        if not isinstance(frame_metadata, dict) or not isinstance(frame_metadata.get("manifest"), dict):
            raise ValueError("Declared ComfyLink metadata is required")
        wire = frame_metadata["manifest"]
        if exr_storage not in {"float32", "half"}:
            raise ValueError("Unknown EXR storage")
        alpha = 1.0 - alpha_mask if alpha_mask is not None else frame_metadata.get("original_alpha")
        if not isinstance(alpha, torch.Tensor) or alpha.dtype != torch.float32 or tuple(alpha.shape) != tuple(images.shape[:3]):
            raise ValueError("Supply a matching float32 MASK or preserved original alpha")
        rgba = torch.cat((images.detach().cpu(), alpha.detach().cpu().unsqueeze(-1)), dim=-1).numpy()
        if not np.isfinite(rgba).all():
            raise ValueError("Nonfinite output samples")
        rate = copy.deepcopy(wire["frameRate"])
        if fps is not None:
            if isinstance(fps, bool) or not np.isfinite(fps) or not 0.001 <= fps <= 1000:
                raise ValueError("Invalid output FPS")
            rational = Fraction(str(float(fps))).limit_denominator(1000000)
            rate = {"numerator": rational.numerator, "denominator": rational.denominator}
        relative = "ComfyLink/" + uuid.uuid4().hex
        root = folder_paths.get_output_directory()
        manifest, result_wire = write_transfer(root, relative, rgba, colour=wire["colour"], frame_rate=rate,
                                                source_bit_depth=wire["sourceBitDepth"], alpha_association=wire["alphaAssociation"],
                                                source_start=wire.get("sourceStart"), exr_storage=exr_storage)
        # EXR is additional declared media. The raw transfer is always FLOAT and
        # is the lossless authoritative round-trip payload even with HALF EXRs.
        exrs = []
        for i, frame in enumerate(rgba, 1):
            filename = f"{i:06d}.exr"
            exrs.append({"filename": filename, "subfolder": relative, "type": "output", "storage": exr_storage})
        metadata = {"manifest": result_wire, "original_alpha": alpha.detach().cpu().clone(),
                    "transformations": copy.deepcopy(frame_metadata.get("transformations", [])), "exrStorage": exr_storage}
        return {"ui": {"comfylink_float": [{"filename": "manifest.json", "subfolder": relative, "type": "output"}],
                       "comfylink_exr": exrs}, "result": (manifest, metadata)}


NODE_CLASS_MAPPINGS = {"ZuraComfyLinkLoadFloatFrames": ZuraComfyLinkLoadFloatFrames,
                       "ZuraComfyLinkSaveFloatFrames": ZuraComfyLinkSaveFloatFrames}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraComfyLinkLoadFloatFrames": "Zura ComfyLink Load Float Frames",
                              "ZuraComfyLinkSaveFloatFrames": "Zura ComfyLink Save Float Frames"}
