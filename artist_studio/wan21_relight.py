"""Wan 2.1 chained reference relighting for Zura Studio.

This recipe is the approved Switch X relight graph, adapted to Studio's
reviewed clip, generated lighting frame, original-audio and output contracts.
It runs the source in overlapping, hardware-sized windows and matches lighting
between sections using pairs that represent the same source frames.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Mapping

import av

from .hardware import snapshot as hardware_snapshot

HERE = Path(__file__).parent
RECIPE = HERE / "graphs" / "07_Wan21_Relight_Recipe.json"
LONG_EDGE = 1280
MAX_WINDOW_FRAMES = 81
WINDOW_NODE = "272:386"
REFERENCE_PIXELS = 1920 * 1088  # 1080p on Wan's 16-pixel grid.
REFERENCE_VRAM_GIB = 23.5  # A nominal 24 GiB card reports slightly less on some hosts.
DEFAULT_VRAM_GIB = 16
MODEL_FPS = 16
STEPS = 4
SAMPLER = "er_sde"
SHIFT = 5.0

MODEL_FILES = {
    "diffusion": ("diffusion_models", "wan_2.1_idv2v_int8_convrot.safetensors"),
    "text_encoder": ("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
    "clip_vision": ("clip_vision", "clip_vision_h.safetensors"),
    "vae": ("vae", "Wan2_1_VAE_bf16.safetensors"),
    "lightx2v": ("loras", "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"),
}

REQUIRED_NODES = {
    "BasicScheduler", "CLIPLoader", "CLIPTextEncode", "CLIPVisionEncode",
    "CLIPVisionLoader", "CreateVideo", "ForLoopClose", "ForLoopOpen",
    "GetImageSizeAndCount", "GetVideoComponents", "GenjLoadReviewedShot", "GenjHoldImages", "GenjHoldToModelLength",
    "GenjRestoreSoundtrack", "GenjJoinRelightSections", "ImageFromBatch",
    "ImageResizeKJv2", "KSamplerSelect", "LoadImage", "LoraLoaderModelOnly",
    "ModelSamplingSD3", "PathchSageAttentionKJ", "SamplerCustom",
    "SimpleMath+", "UNETLoader", "VAEDecode", "VAELoader",
    "WanImageToVideo", "WanVaceToVideo", "easy int",
}


class Wan21RelightError(ValueError):
    """A missing prerequisite or invalid Wan 2.1 relight request."""


class GenjJoinRelightSections:
    """Match the incoming section's colour while keeping one image per frame."""

    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "join"
    RETURN_TYPES = ("IMAGE",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "previous": ("IMAGE",), "incoming": ("IMAGE",),
            "overlap": ("INT", {"min": 0}), "section_start": ("INT", {"min": 0}),
        }}

    def join(self, previous, incoming, overlap, section_start):
        import torch
        import torch.nn.functional as F

        if section_start == 0:
            # Before iteration one, previous is only the uploaded lighting still.
            return (incoming,)
        if (previous.shape[1:] != incoming.shape[1:] or section_start != len(previous) - overlap
                or not 0 < overlap <= min(len(previous), len(incoming))):
            raise Wan21RelightError("The Wan relight sections do not have matching frames at their join.")

        # Compare the same points in time. A coarse correction field lets the
        # window and foreground match independently without blending details.
        samples = min(overlap, 12)
        height, width = incoming.shape[1:3]
        rows = max(1, min(6, height // 16))
        columns = max(1, min(6, width // 16))
        block = 8
        size = (rows * block, columns * block)
        before = F.adaptive_avg_pool2d(previous[section_start:section_start + samples].movedim(-1, 1).float(), size)
        after = F.adaptive_avg_pool2d(incoming[:samples].movedim(-1, 1).float(), size)
        patches = (before - after).unfold(2, block, block).unfold(3, block, block)
        changes = patches.flatten(-2).median(dim=-1).values
        shared = changes.median(dim=0).values
        maps = torch.stack((changes[0], shared)).clamp(-0.15, 0.15)
        boundary, steady = F.interpolate(maps, size=(height, width), mode='bilinear',
                                         align_corners=False).movedim(1, -1).to(incoming)
        ramp = torch.linspace(0, 1, samples, device=incoming.device, dtype=incoming.dtype)
        ramp = ramp.square() * (3 - 2 * ramp)
        corrected = incoming.clone()
        for index, weight in enumerate(ramp):
            corrected[index].add_(torch.lerp(boundary, steady, weight))
        corrected[samples:].add_(steady)
        corrected.clamp_(0, 1)
        return (torch.cat((previous[:-overlap], corrected)),)


def choose_window_frames(width: int, height: int, vram_gib: float | None) -> int:
    """Scale Wan's temporal groups by working pixel area and dedicated VRAM."""
    if vram_gib is None or not math.isfinite(vram_gib) or vram_gib <= 0:
        vram_gib = DEFAULT_VRAM_GIB
    # Use ten four-frame groups at aligned 1080p on a 24 GiB-class card.
    # This is a workload heuristic. Model residency and other apps vary by host.
    groups = int(10 * REFERENCE_PIXELS * vram_gib / (width * height * REFERENCE_VRAM_GIB))
    return max(5, min(MAX_WINDOW_FRAMES, 4 * groups + 1))


def readiness(node_mappings: Mapping[str, Any], get_full_path) -> dict[str, Any]:
    """Report the exact nodes and files the verified recipe needs."""
    files = []
    for identity, (folder, filename) in MODEL_FILES.items():
        try:
            present = bool(get_full_path(folder, filename))
        except (KeyError, FileNotFoundError, OSError):
            present = False
        files.append({"identity": identity, "folder": folder, "filename": filename,
                      "ready": present})
    missing_nodes = sorted(REQUIRED_NODES - set(node_mappings))
    return {
        "ready": not missing_nodes and all(item["ready"] for item in files),
        "model_files": files,
        "missing_nodes": missing_nodes,
        "limits": {"long_edge": LONG_EDGE, "window_frames": MAX_WINDOW_FRAMES, "adaptive_window": True,
                   "preserve_source_timing": True, "steps": STEPS, "sampler": SAMPLER},
        "quality_verified_locally": False,
        "source_workflow_artist_confirmed": True,
        "note": ("Based on the artist-confirmed Switch X relight workflow. The Studio graph "
                 "is checked against installed Comfy nodes and models; review output quality "
                 "and joins on your shot. Section size adapts to the working resolution and GPU memory."),
    }


def _node(graph: dict[str, dict[str, Any]], key: str, class_type: str,
          **inputs: Any) -> list[Any]:
    graph[key] = {"class_type": class_type, "inputs": inputs}
    return [key, 0]


def _source_size(source_path: str | Path) -> tuple[int, int]:
    with av.open(str(source_path)) as container:
        if not container.streams.video:
            raise Wan21RelightError("Upload a video containing a video track.")
        stream = container.streams.video[0]
        source_width, source_height = int(stream.width), int(stream.height)
    if source_width < 1 or source_height < 1:
        raise Wan21RelightError("The source video's dimensions could not be read.")
    return source_width, source_height


def _output_size(source_path: str | Path) -> tuple[int, int]:
    source_width, source_height = _source_size(source_path)
    scale = LONG_EDGE / max(source_width, source_height)
    width = max(64, round(source_width * scale / 16) * 16)
    height = max(64, round(source_height * scale / 16) * 16)
    return width, height


def _relight_prompt(config: Mapping[str, Any]) -> str:
    direction = str(config.get("prompt") or config.get("image_prompt") or "").strip()
    if not direction:
        direction = "Follow the lighting and colour of the supplied lighting image."
    return (
        "Relight the entire shot to match the provided lighting reference. Keep the source "
        "subjects, objects, scene layout, camera path, framing, motion and performance "
        "consistent throughout the video. Apply the requested lighting naturally and "
        "consistently across every frame. Do not return to the original unrelit appearance. "
        + direction
    )


def build_studio_graph(project: Mapping[str, Any], check_asset) -> dict[str, dict[str, Any]]:
    """Build the chained 4-step Wan 2.1 route from an approved Studio project."""
    config = project.get("config") or {}
    if config.get("workflow_mode") != "relight" or config.get("relight_engine", "h3") != "wan21":
        raise Wan21RelightError("Choose Wan 2.1 Relight for this Studio task.")
    unsupported = ("audio_id", "lip_sync", "refine_lips", "preserve_people",
                   "preserve_identity", "remove_text", "h3_head_swap")
    if any(config.get(key) for key in unsupported):
        raise Wan21RelightError(
            "Wan 2.1 Relight keeps the source performance and audio. Text removal and "
            "the H3 identity guide are not available on this route."
        )
    if not project.get("review") or project.get("approval") != project.get("prepared_key"):
        raise Wan21RelightError("Review and approve the source clip before relighting it.")
    if (not project.get("opening_input") or not project.get("opening_key") or
            project.get("opening_approval") != project.get("opening_key")):
        raise Wan21RelightError("Create and approve the lighting frame before generating video.")

    prompt = _relight_prompt(config)
    from .studio import assert_approved
    assert_approved(project)
    source_path = check_asset(project["source"])
    check_asset(project["opening_input"])
    width, height = _output_size(source_path)
    if config.get("relight_width") and config.get("relight_height"):
        width, height = int(config["relight_width"]), int(config["relight_height"])
        if any(v < 256 or v > 4096 or v % 16 for v in (width, height)) or width * height > 8_388_608:
            raise Wan21RelightError("Choose valid Wan 2.1 dimensions on its 16-pixel grid.")

    payload = json.loads(RECIPE.read_text(encoding="utf-8"))
    if payload.get("_zura_recipe") != "wan21-relight-switchx-v1":
        raise Wan21RelightError("The packaged Wan 2.1 Relight recipe is not recognised.")
    graph = copy.deepcopy(payload["graph"])
    window = choose_window_frames(width, height, hardware_snapshot()["hardware"]["vram_gib"])
    graph[WINDOW_NODE]["inputs"]["value"] = window
    graph[WINDOW_NODE]["_meta"]["title"] = f"Inference window: {window} frames"
    graph["wan21_reference"]["inputs"]["image"] = project["opening_input"]["file"]
    graph["wan21_shot"] = {
        "class_type": "GenjLoadReviewedShot",
        # assert_approved checks the preparation hash above. The loader compares
        # shot IDs, not that hash, just like the other Studio animation graphs.
        "inputs": {"shot_id": project["review"], "approved_shot_id": project["review"],
                   "render_long_edge": max(width, height), "output_scale": 1, "preview_seconds": 0,
                   "preserve_aspect": True, "preserve_source_timing": True},
        "_meta": {"title": "Load approved source clip"},
    }
    if config.get('ae_frame_contract') is None:
        graph["wan21_shot"]["inputs"]["model_fps"] = MODEL_FPS
    graph["wan21_source_frames"] = {
        "class_type": "GetVideoComponents", "inputs": {"video": ["wan21_shot", 0]},
        "_meta": {"title": "Source frames and camera motion"},
    }
    for key in ("272:407:89", "272:408:275:190"):
        graph[key]["inputs"].update(width=width, height=height)
    # Wan's control node otherwise fills a short last section with neutral
    # grey. Hold the last source image for the model's sampling window.
    graph["wan21_hold_source"] = {"class_type": "GenjHoldImages", "inputs": {
        "images": ["272:404:395", 0], "length": ["272:403:387", 0]},
        "_meta": {"title": "Hold final source frame for the model"}}
    graph["272:407:89"]["inputs"]["image"] = ["wan21_hold_source", 0]
    # Crop the lighting reference at the same position as source frames.  The
    # supplied recipe used top for the anchor and centre for every other frame.
    graph["272:408:275:190"]["inputs"]["crop_position"] = "center"
    graph["272:408:274:3"]["inputs"]["text"] = prompt
    graph["272:407:277:19"]["inputs"]["noise_seed"] = int(config.get("seed", 42))
    graph["272:405:399"] = {
        "class_type": "GenjJoinRelightSections",
        "inputs": {"previous": ["272:392", 2], "incoming": ["272:407:6", 0],
                   "overlap": ["272:405:398", 0], "section_start": ["272:404:394", 0]},
        "_meta": {"title": "Match lighting across overlapping sections"},
    }
    graph["272:401"]["inputs"]["initial_value1"] = ["272:405:399", 0]
    result_frames = ["272:402", 0]
    if config.get('ae_frame_contract') is not None:
        graph["wan21_hold_result"] = {"class_type": "GenjHoldToModelLength", "inputs": {
            "images": result_frames, "stride": 4},
            "_meta": {"title": "Hold final frame to a supported Wan length"}}
        result_frames = ["wan21_hold_result", 0]
    graph["wan21_video"] = {
        "class_type": "CreateVideo",
        "inputs": {"images": result_frames, "fps": ["wan21_source_frames", 2]},
        "_meta": {"title": "Assemble relit frames"},
    }
    graph["wan21_export"] = {
        "class_type": "GenjRestoreSoundtrack",
        "inputs": {"video": ["wan21_video", 0],
                   "clip_details": ["wan21_shot", 3],
                   "take_name": "studio_" + str(project["id"])[:8] + "_wan21_relight"},
        "_meta": {"title": "Save relight with original soundtrack"},
    }
    if config.get('ae_frame_contract') is not None:
        from ..comfylink.frame_contract import normalise_frame_contract
        contract = normalise_frame_contract(config['ae_frame_contract'])
        source_width, source_height = _source_size(source_path)
        if ((source_width, source_height) != (contract['width'], contract['height'])
                or any(side < 2 or side > 16384 or side % 2 for side in (source_width, source_height))):
            raise Wan21RelightError('Wan Relight requires the exact AE source raster with even output dimensions.')
        # Keep the model's proven working canvas; its native export restores
        # the original source raster and verifies the final AE interval.
        graph['wan21_export']['inputs'].update(output_width=source_width, output_height=source_height)
    elif config.get("relight_return_source_resolution", True):
        source_width, source_height = _source_size(source_path)
        if max(source_width, source_height) > 16384:
            raise Wan21RelightError('Disable Return at source resolution for sources larger than 16384 pixels on either side.')
        graph["wan21_export"]["inputs"].update(output_width=source_width, output_height=source_height)
        for key in ("272:407:89", "272:408:275:190"):
            graph[key]["inputs"]["keep_proportion"] = "stretch"
    else:
        graph["wan21_export"]["inputs"].update(output_width=width, output_height=height)
    return graph
