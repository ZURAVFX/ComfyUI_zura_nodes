"""Local OpenJutsu character replacement. No cloud services or paid anchor call.

Recipe: Comfy-Org/comfy-openjutsu @ 70ec62df0eda7c58697ea3ac2050588513651583
MIT recipe attribution and licence accompany graphs/OpenJutsu_Experimental.json.
Runtime dependency is the author's separately installed GPL-3.0 node pack.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

UPSTREAM = "https://github.com/Comfy-Org/comfy-openjutsu"
REVISION = "70ec62df0eda7c58697ea3ac2050588513651583"
TEMPLATE = Path(__file__).parent / "graphs" / "OpenJutsu_Experimental.json"


def exact_source_clip(start, duration):
    return {"class_type": "GenjSelectClip", "inputs": {
        "video": ["30", 0], "start_seconds": start, "duration_seconds": duration,
        "long_edge": 1920}, "_meta": {"title": "Select exact source range · 24 fps"}}


def build_graph(project, check_asset=lambda asset: None):
    """Adapt the pinned official graph; preserve native masked regeneration."""
    c = project["config"]
    if (c.get("engine") != "h3" or c.get("workflow_mode") != "swap"
            or c.get("scope", "person") != "person" or c.get("performer", -1) != -1
            or c.get("subject_mode", "people") not in ("auto", "people")
            or c.get("mask_method", "auto") != "auto"
            or c.get("finished_frame_position", "first") != "first"
            or any(c.get(k) for k in ("audio_id", "lip_sync", "refine_lips", "remove_text", "preserve_people", "h3_head_swap"))):
        raise ValueError("OpenJutsu test supports one automatically selected full character and original audio. Use the standard route for other tasks.")
    source, character = project.get("source"), project.get("character")
    if not source or not character:
        raise ValueError("Add a source video and one character reference.")
    duration = float(source.get("duration", 0)) if c.get("length_mode") == "original" else float(c.get("duration", 5))
    start = 0.0 if c.get("length_mode") == "original" else float(c.get("start", 0))
    if not math.isfinite(duration) or not 5/24 <= duration <= 5 or not math.isfinite(start) or start < 0:
        raise ValueError("Select up to five seconds for this OpenJutsu test.")
    if source.get("duration"):
        available = float(source["duration"]) - start
        if available <= 0 or math.floor(duration * 24 + 1e-6) > math.floor(available * 24 + 1e-6):
            raise ValueError("The selected range extends past the end of the source video. Choose a shorter range.")
    tier = c.get("openjutsu_resolution", "480")
    if str(tier) not in ("480", "768"):
        raise ValueError("Choose the OpenJutsu 480 or 768 tier.")
    if len(project.get("references", [character])) != 1:
        raise ValueError("OpenJutsu test accepts one character image. A reference sheet counts as one image.")
    check_asset(source)
    check_asset(character)
    graph = json.loads(TEMPLATE.read_text(encoding="utf8"))
    graph["30"]["inputs"]["file"] = source["file"]
    graph["9"]["inputs"]["image"] = character["file"]
    # Video Slice can decode one frame short after a non-frame-aligned seek.
    # Prepare the requested 24 fps range once, with a one-frame tail hold if
    # needed, before both the H3 preparation and the shot's source reference.
    graph["trim"] = exact_source_clip(start, duration)
    graph["31"]["inputs"].update(resolution=int(tier), duration_seconds=duration)
    graph["801"]["inputs"]["seed"] = int(c.get("seed", 42))
    replace_background = c.get("openjutsu_background", "keep") == "replace"
    graph["801"]["inputs"]["prompt"] = (
        "Replace the entire head and body of the selected person in <Video 1> with the character in <Picture 1>. "
        "Match the reference face, headwear, body and complete outfit. Remove the source person's original garments and accessories. "
        + ("<Picture 2> is the approved complete scene. Replace the background to match its setting, colours and lighting throughout. "
           "Do not return to the original background. Preserve the source performance, camera movement and audio timing. "
           if replace_background else "Preserve the source background, other objects, performance and audio timing. ")
        + str(c.get("prompt", "")).strip()).strip()
    # Native SelectCLIPDevice uses 'default' for the active GPU on this Comfy core.
    graph["58"]["inputs"]["device"] = "default"
    opening = None if c.get("openjutsu_direct") and project.get("look_mode") != "ready" and not replace_background else project.get("opening_input")
    if replace_background and not opening:
        raise ValueError("Create or upload a starting frame with the new background first.")
    graph["803"]["inputs"]["use_mask"] = not replace_background
    if replace_background:
        graph["803"]["inputs"].pop("body_mask", None)
        for identity in map(str, range(100, 111)):
            graph.pop(identity, None)
    graph["803"]["inputs"]["use_anchor"] = bool(opening)
    if opening:
        check_asset(opening)
        graph["anchor_image"]["inputs"]["image"] = opening["file"]
    else:
        graph["803"]["inputs"].pop("anchor", None)
        # Upstream calls the input anchor_image; keep neither dangling branch.
        graph["803"]["inputs"].pop("anchor_image", None)
        graph.pop("anchor_image", None)
        graph.pop("anchor_fit", None)
    identity = str(project.get("id", "test"))
    if not identity.isalnum():
        raise ValueError("Invalid test identity.")
    graph["803"]["inputs"]["shot_id"] = identity
    graph["807"]["inputs"]["filename_prefix"] = "zura_openjutsu_" + identity
    graph["809"]["inputs"]["filename_prefix"] = "genj/final/studio_" + identity + "_openjutsu"
    return graph


def readiness(graph, node_info):
    """Validate exact optional dependencies before queuing expensive work."""
    missing = []
    for node in graph.values():
        kind = node["class_type"]
        if kind not in node_info:
            missing.append(kind)
            continue
        required = node_info[kind].get("input", {}).get("required", {})
        for key in ("unet_name", "lora_name", "clip_name", "vae_name", "ckpt_name"):
            value = node["inputs"].get(key)
            schema = required.get(key)
            if isinstance(value, str) and schema and isinstance(schema[0], list) and value not in schema[0]:
                missing.append(value)
    return {"ready": not missing, "missing": sorted(set(missing))}


def installed_readiness(node_mappings):
    """Check optional node pack and exact weights without loading any models."""
    graph = json.loads(TEMPLATE.read_text(encoding="utf8"))
    graph["trim"] = exact_source_clip(0, 5)
    info = {}
    for kind in {node["class_type"] for node in graph.values()}:
        cls = node_mappings.get(kind)
        if cls is not None:
            try:
                info[kind] = {"input": cls.INPUT_TYPES()}
            except Exception:
                pass
    result = readiness(graph, info)
    result['missing_nodes'] = sorted({n['class_type'] for n in graph.values()} - set(info))
    folders = {'unet_name': 'diffusion_models', 'lora_name': 'loras', 'clip_name': 'text_encoders', 'vae_name': 'vae', 'ckpt_name': 'checkpoints'}
    result['model_files'] = [
        {'folder': folders[key], 'filename': value, 'ready': value not in result['missing']}
        for n in graph.values() for key, value in n['inputs'].items() if key in folders]
    return result
