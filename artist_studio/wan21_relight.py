"""Wan 2.1 chained reference relighting for Zura Studio.

This recipe is the approved Switch X relight graph, adapted to Studio's
reviewed clip, generated lighting frame, original-audio and output contracts.
It runs the source in overlapping 81-frame windows and keeps the last overlap
as a hard cut, matching the supplied artist workflow.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

import av

HERE = Path(__file__).parent
RECIPE = HERE / "graphs" / "07_Wan21_Relight_Recipe.json"
LONG_EDGE = 1280
WINDOW_FRAMES = 81
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
    "GetImageSizeAndCount", "GetVideoComponents", "GenjLoadReviewedShot",
    "GenjRestoreSoundtrack", "ImageBatchExtendWithOverlap", "ImageFromBatch",
    "ImageResizeKJv2", "KSamplerSelect", "LoadImage", "LoraLoaderModelOnly",
    "ModelSamplingSD3", "PathchSageAttentionKJ", "SamplerCustom",
    "SimpleMath+", "UNETLoader", "VAEDecode", "VAELoader",
    "WanImageToVideo", "WanVaceToVideo", "easy int",
}


class Wan21RelightError(ValueError):
    """A missing prerequisite or invalid Wan 2.1 relight request."""


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
        "limits": {"long_edge": LONG_EDGE, "window_frames": WINDOW_FRAMES,
                   "fps": 24, "steps": STEPS, "sampler": SAMPLER},
        "quality_verified_locally": False,
        "source_workflow_artist_confirmed": True,
        "note": ("Based on the artist-confirmed Switch X relight workflow. The Studio graph "
                 "is checked against installed Comfy nodes and models; review output quality "
                 "and joins on your shot. Longer clips use 81-frame sections."),
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
        if any(v < 256 or v > 1920 or v % 16 for v in (width, height)) or width * height > 1920 * 1088:
            raise Wan21RelightError("Choose valid Wan 2.1 dimensions on its 16-pixel grid.")

    payload = json.loads(RECIPE.read_text(encoding="utf-8"))
    if payload.get("_zura_recipe") != "wan21-relight-switchx-v1":
        raise Wan21RelightError("The packaged Wan 2.1 Relight recipe is not recognised.")
    graph = copy.deepcopy(payload["graph"])
    graph["wan21_reference"]["inputs"]["image"] = project["opening_input"]["file"]
    graph["wan21_shot"] = {
        "class_type": "GenjLoadReviewedShot",
        # assert_approved checks the preparation hash above. The loader compares
        # shot IDs, not that hash, just like the other Studio animation graphs.
        "inputs": {"shot_id": project["review"], "approved_shot_id": project["review"],
                   "render_long_edge": max(width, height), "output_scale": 1, "preview_seconds": 0,
                   "preserve_aspect": True},
        "_meta": {"title": "Load approved source clip"},
    }
    graph["wan21_source_frames"] = {
        "class_type": "GetVideoComponents", "inputs": {"video": ["wan21_shot", 0]},
        "_meta": {"title": "Source frames and camera motion"},
    }
    for key in ("272:407:89", "272:408:275:190"):
        graph[key]["inputs"].update(width=width, height=height)
    # Crop the lighting reference at the same position as source frames.  The
    # supplied recipe used top for the anchor and centre for every other frame.
    graph["272:408:275:190"]["inputs"]["crop_position"] = "center"
    graph["272:408:274:3"]["inputs"]["text"] = prompt
    graph["272:407:277:19"]["inputs"]["noise_seed"] = int(config.get("seed", 42))
    graph["wan21_video"] = {
        "class_type": "CreateVideo",
        "inputs": {"images": ["272:402", 0], "fps": 24.0},
        "_meta": {"title": "Assemble relit frames"},
    }
    graph["wan21_export"] = {
        "class_type": "GenjRestoreSoundtrack",
        "inputs": {"video": ["wan21_video", 0],
                   "clip_details": ["wan21_shot", 3],
                   "take_name": "studio_" + str(project["id"])[:8] + "_wan21_relight"},
        "_meta": {"title": "Save relight with original soundtrack"},
    }
    if config.get("relight_shape") == "source_size":
        source_width, source_height = _source_size(source_path)
        # H.264 yuv420p requires even output dimensions.
        graph["wan21_export"]["inputs"].update(output_width=source_width - source_width % 2,
                                                 output_height=source_height - source_height % 2)
    elif config.get("relight_width") and config.get("relight_height"):
        graph["wan21_export"]["inputs"].update(output_width=width, output_height=height)
    return graph
