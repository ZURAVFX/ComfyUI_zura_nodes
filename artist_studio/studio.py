"""Persistent artist projects and orchestration of the native ComfyUI graphs."""
import asyncio
import copy
import hashlib
import json
import logging
import math
import re
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlparse

import av
from aiohttp import web
from PIL import Image

import folder_paths

from .availability import require_verified_setup, head_swap_setup, camera_setup

HERE = Path(__file__).parent
STAGES = {
    "prepare": "01_Prepare_and_Review",
    "design": "01B_Design_Opening_Frame",
    "background": "02_LTX_Keep_Background",
    "restyle": "03_LTX_Depth_Restyle",
    "draft": "04_Seedance_Draft",
    "final": "05_Seedance_Accepted_Final",
    "h3": "06_H3_Character_Reference",
    "h3_enhance": "08_H3_Enhanced_1080p",
    "wan": "07_Wan_Character_Replacement",
    "wan2": "Wan_Animate_2_Full_Frame",
    "wan21_relight": "07_Wan21_Relight_Recipe",
    "wan_prepare": "07A_Wan_Motion_Preparation",
    "wan_merge": "07D_Wan_Finish_Motion",
    "wan_speech": "07B_Wan_Speech_Performance",
    "wan_cleanup": "07C_Wan_Memory_HandOff",
}
STAGES.update({"ltx25_" + phase: "LTX 2.5 " + phase for phase in
               ("text", "motion", "stage1", "upscale", "refine", "decode", "cleanup")})
DEFAULTS = {"engine": "local", "background": "keep", "scope": "person", "prompt": "", "image_prompt": "",
            "custom_loras": [],
            "h3_character_method": "control", "openjutsu_resolution": "480",
            "openjutsu_background": "keep", "openjutsu_direct": False,
            "opening_model": "klein9b",
            "opening_width": 0, "opening_height": 0, "opening_shape": "source", "opening_megapixels": 1.0,
            "relight_width": 0, "relight_height": 0, "relight_shape": "source", "relight_megapixels": 0.9,
            "camera_shape": "source", "camera_megapixels": 0.35,
            "start": 0.0, "duration": 2.0, "size": 512, "performer": -1,
            "margin": 20, "pitch": False, "seed": 42, "render_size": 0, "h3_preset": "preview_quality", "h3_steps": 0, "h3_attention": "native", "remove_text": False,
            "resolution": 1280, "delivery_mode": "native", "quality": "fast", "audio_id": "", "audio_start": 0.0, "length_mode": "custom", "lip_sync": False, "refine_lips": False,
            "finished_frame_position": "first", "finished_frame_number": 1, "h3_viewport_direct": False, "h3_head_swap": False,
            "camera_preset": "Left three-quarter", "camera_prompt": "", "camera_width": 768, "camera_height": 448,
            "subject_mode": "auto", "preserve_people": False, "preserve_identity": False,
            "relight_engine": "wan21",
            "workflow_mode": "swap", "edit_area": "mask", "mask_method": "auto", "mask_prompt": "person", "mask_points": []}
PREP_KEYS = ("start", "duration", "size", "scope", "performer", "margin", "pitch")


def sha(path):
    from .file_cache import file_digest
    return file_digest(path)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def h3_attention_capabilities(node_mappings):
    """Optional sampling patches never determine baseline H3 readiness."""
    return {"native": True,
            "kitchen": "ModelAttentionBackend" in node_mappings,
            "sage_sol": all(name in node_mappings for name in
                            ("PathchSageAttentionKJ", "SolAttnPatch"))}


def design_readiness(node_mappings, get_full_path, model="klein9b"):
    """Check the actual Klein opening-frame graph, independently of video models."""
    if model != "klein9b":
        from .opening_models import readiness
        return readiness(node_mappings, get_full_path)[model]
    graph = json.loads((HERE / "graphs" / (STAGES["design"] + ".json")).read_text(encoding="utf-8"))
    loaders = {"UNETLoader": ("diffusion_models", "unet_name"),
               "CLIPLoader": ("text_encoders", "clip_name"),
               "VAELoader": ("vae", "vae_name")}
    files = []
    for node in graph.values():
        if node["class_type"] not in loaders:
            continue
        folder, field = loaders[node["class_type"]]
        filename = node["inputs"][field]
        files.append({"folder": folder, "filename": filename,
                      "ready": bool(get_full_path(folder, filename))})
    missing = sorted({node["class_type"] for node in graph.values()} - set(node_mappings))
    return {"ready": bool(files) and all(item["ready"] for item in files) and not missing,
            "model_files": files, "missing_nodes": missing}


def clean_config(value):
    c = {**DEFAULTS, **{k: v for k, v in value.items() if k in DEFAULTS}}
    # Copy list-valued preferences: one shot must never mutate another shot's adapters.
    adapters = c.get("custom_loras")
    if not isinstance(adapters, list) or len(adapters) > 4:
        raise ValueError("Choose up to four custom LoRAs.")
    c["custom_loras"] = copy.deepcopy(adapters)
    for adapter in c["custom_loras"]:
        if not isinstance(adapter, dict) or not isinstance(adapter.get("name"), str) or not adapter["name"]:
            raise ValueError("Choose an installed custom LoRA.")
    # Preserve the former two-way edit selector on older saved shots. The
    # viewport route is opt-in and never inferred from a legacy scene edit.
    if "workflow_mode" not in value:
        if value.get("edit_area") == "scene" or (
                "edit_area" not in value and value.get("background") == "restyle"):
            c["workflow_mode"] = "motion"
        elif value.get("edit_area") == "mask":
            c["workflow_mode"] = "swap"
    # Older saved projects retain their selected render size. New artist
    # controls keep mask preparation at 512 and specify output size separately.
    if "resolution" not in value:
        c["resolution"] = int(value.get("render_size") or value.get("size", DEFAULTS["resolution"]))
    if "quality" in value or "resolution" in value:
        c["h3_preset"] = "take_fast" if c["quality"] == "fast" else "take_quality"
    from .h3 import H3_PRESETS
    from .opening_models import MODELS as OPENING_MODELS
    if c['opening_model'] not in OPENING_MODELS:
        raise ValueError("Choose an available starting-image model.")
    for key, options in [("engine", ("local", "h3", "wan", "wan2", "seedance")), ("background", ("keep", "restyle")),
                         ("quality", ("fast", "detailed")),
                         ("length_mode", ("custom", "original")),
                         ("workflow_mode", ("motion", "swap", "viewport", "relight", "camera")),
                         ("subject_mode", ("auto", "people", "objects")),
                         ("finished_frame_position", ("first", "last", "frame")),
                         ("relight_engine", ("h3", "wan21")),
                         ("mask_method", ("auto", "text", "points")),
                         ("h3_preset", H3_PRESETS),
                         ("h3_attention", ("native", "kitchen", "sage_sol")),
                         ("scope", ("person", "head"))]:
        if c[key] not in options:
            raise ValueError(f"Choose a valid {key} option.")
    if c["h3_character_method"] not in ("control", "openjutsu") or str(c["openjutsu_resolution"]) not in ("480", "768") or c["openjutsu_background"] not in ("keep", "replace"):
        raise ValueError("Choose an available H3 character method and OpenJutsu tier.")
    c["openjutsu_resolution"] = str(c["openjutsu_resolution"])
    if c["engine"] != "h3" or c["workflow_mode"] != "swap":
        c["h3_character_method"] = "control"
    raw_frame = c["finished_frame_number"]
    if isinstance(raw_frame, bool):
        raise ValueError("Choose a whole frame number starting at 1.")
    try:
        c["finished_frame_number"] = int(raw_frame)
        valid_frame = math.isfinite(float(raw_frame)) and float(raw_frame) == c["finished_frame_number"] and 1 <= c["finished_frame_number"] <= 1000000
    except (ValueError, TypeError, OverflowError):
        valid_frame = False
    if not valid_frame:
        raise ValueError("Choose a whole frame number starting at 1.")
    if c["engine"] not in ("local", "h3") and c["finished_frame_position"] != "first":
        raise ValueError("Timed finished-frame references are supported by LTX and H3. Select First frame or switch models.")
    if c["workflow_mode"] == "relight" and c["engine"] != "h3":
        raise ValueError("Relight currently supports MiniMax H3. Choose H3 for this task.")
    if c["workflow_mode"] != "relight":
        c["relight_engine"] = "h3"
    else:
        # Migrate saved H3 choices when editing/exporting a shot. Running jobs
        # keep their queued graph and are never automatically resubmitted.
        c["relight_engine"] = "wan21"
    c["preserve_people"] = bool(c["preserve_people"])
    c["preserve_identity"] = bool(c["preserve_identity"]) and c["workflow_mode"] == "relight"
    if c["preserve_people"] and (c["engine"] != "h3" or c["workflow_mode"] != "motion"):
        raise ValueError("Keep original people currently supports H3 scene transformation only.")
    c["viewport_render"] = c["workflow_mode"] == "viewport"
    c["h3_viewport_direct"] = bool(c["h3_viewport_direct"])
    c["openjutsu_direct"] = bool(c["openjutsu_direct"])
    c["h3_head_swap"] = bool(c["h3_head_swap"])
    c["edit_area"] = "mask" if c["workflow_mode"] == "swap" or c["preserve_people"] else "scene"
    if c["h3_character_method"] == "openjutsu" and c["openjutsu_background"] == "replace":
        c["edit_area"] = "scene"
        c["openjutsu_direct"] = False
    if c["engine"] == "local" and c["edit_area"] == "mask" and c["finished_frame_position"] != "first":
        raise ValueError("Timed LTX finished frames currently require a whole-scene task. Masked edits use the first frame.")
    # The visible task choice is the sole source of scene/mask routing.
    c["background"] = "restyle" if c["engine"] in ("local", "seedance") and c["edit_area"] == "scene" else "keep"
    for key in ("start", "duration", "audio_start"):
        c[key] = float(c[key])
        if not math.isfinite(c[key]):
            raise ValueError("Clip times must be finite numbers.")
    if not 0 <= c["start"] <= 86400 or not 0.1 <= c["duration"] <= 30:
        raise ValueError("Choose a start time and a duration between 0.1 and 30 seconds.")
    if not 0 <= c["audio_start"] <= 86400:
        raise ValueError("Choose an audio start between 0 and 86400 seconds.")
    c["audio_id"] = str(c["audio_id"] or "")
    if c["audio_id"] and not re.fullmatch(r"[a-f0-9]{32}", c["audio_id"]):
        raise ValueError("Choose an uploaded reference audio track.")
    c["lip_sync"] = bool(c["lip_sync"]) and bool(c["audio_id"])
    c["refine_lips"] = bool(c["refine_lips"]) and c["lip_sync"]
    if c["preserve_people"] and c["lip_sync"]:
        raise ValueError("Keep original people preserves their facial performance. Turn it off to inject replacement speech.")
    if c["length_mode"] == "original":
        c["start"] = 0.0
    for key, low, high in [("size", 256, 960), ("performer", -1, 63), ("margin", 0, 128), ("seed", 0, 2**53 - 1)]:
        c[key] = int(c[key])
        if not low <= c[key] <= high:
            raise ValueError(f"{key.title()} is outside its supported range.")
    raw_steps = c["h3_steps"]
    if isinstance(raw_steps, bool):
        raise ValueError("Choose an integer H3 step count from 4 to 80.")
    c["h3_steps"] = int(raw_steps)
    if float(raw_steps) != c["h3_steps"] or c["h3_steps"] != 0 and not 4 <= c["h3_steps"] <= 80:
        raise ValueError("Choose an integer H3 step count from 4 to 80.")
    c["pitch"] = bool(c["pitch"])
    c["remove_text"] = bool(c["remove_text"])
    c["render_size"] = int(c["render_size"])
    if c["render_size"] not in (0, 1920):
        raise ValueError("This saved output setting is invalid. Choose an output resolution.")
    c["prompt"] = str(c["prompt"]).strip()[:5000]
    c["image_prompt"] = str(c["image_prompt"]).strip()[:5000]
    c["camera_prompt"] = str(c["camera_prompt"]).strip()[:5000]
    from .h3_camera import PRESETS as CAMERA_PRESETS
    if c["camera_preset"] not in CAMERA_PRESETS:
        raise ValueError("Choose a valid camera angle.")
    for key in ("camera_width", "camera_height"):
        raw = c[key]
        c[key] = int(raw)
        if isinstance(raw, bool) or float(raw) != c[key] or not 128 <= c[key] <= 1280 or c[key] % 32:
            raise ValueError("Choose camera dimensions from 128 to 1280, in multiples of 32.")
    c["mask_prompt"] = str(c["mask_prompt"]).strip()[:500]
    from .mask_selection import clean_points
    c["mask_points"] = clean_points(c["mask_points"], require_positive=False)
    for prefix, step, maximum, pixels in (("opening", 32 if c["opening_model"] == "qwen21" else 16, 2048, 2_000_000), ("relight", 16, 1920, 1920 * 1088)):
        pair = []
        for side in ("width", "height"):
            raw = c[prefix + "_" + side]
            number = int(raw)
            if isinstance(raw, bool) or float(raw) != number or number and (number < 256 or number > maximum or number % step):
                raise ValueError(f"Choose {prefix} dimensions from 256 to {maximum}, in multiples of {step}.")
            pair.append(number)
            c[prefix + "_" + side] = number
        if bool(pair[0]) != bool(pair[1]) or pair[0] * pair[1] > pixels:
            raise ValueError(f"Choose both {prefix} dimensions within the model's pixel limit.")
    c["resolution"] = 832 if c["engine"] == "wan2" else int(c["resolution"])
    if c["workflow_mode"] == "relight" and c["relight_engine"] == "wan21":
        c["resolution"] = 1280
        c["delivery_mode"] = "native"
        c["preserve_identity"] = False
        c["remove_text"] = False
    if c["resolution"] not in ((1024,) if head_swap_setup(c) else (832,) if c["engine"] == "wan2" else (256, 512, 768, 960, 1280, 1920)):
        if head_swap_setup(c):
            c["resolution"] = 1024
        else:
            raise ValueError("Choose a supported output resolution.")
    if c["delivery_mode"] not in ("native", "enhanced1080"):
        raise ValueError("Choose a supported H3 delivery mode.")
    # Older projects only stored an integer resolution. Preserve their 1920
    # setting as native H3; enhancement is opt-in through the explicit mode.
    if c["engine"] != "h3" or c["resolution"] != 1920:
        c["delivery_mode"] = "native"
    if c["engine"] == "h3" and not head_swap_setup(c) and c["resolution"] not in (1280, 1920):
        # H3 exposes one 720p generation option and two explicit 1080p
        # delivery options. Migrate old small-test selections to the supported
        # 720p base instead of keeping a hidden fourth choice in saved shots.
        c["resolution"] = 1280
    if c["h3_character_method"] == "openjutsu":
        c.update(quality="fast", h3_steps=8, h3_attention="kitchen", delivery_mode="native")
    return c


def require_relight_direction(config, *, supplied_image=False):
    """Allow an empty draft UI state, but never submit an undirected relight."""
    if config.get("workflow_mode") == "relight" and not supplied_image and not (config.get("image_prompt") or config.get("prompt")):
        raise ValueError("Describe the lighting you want for this shot.")


def h3_viewport_direct(project):
    """Use reviewed source motion and appearance images without inventing an opening."""
    c = project.get("config") or {}
    if (c.get("engine") == "h3" and c.get("workflow_mode") == "swap"
            and c.get("h3_character_method") == "openjutsu" and c.get("openjutsu_direct")
            and c.get("openjutsu_background", "keep") == "keep" and project.get("look_mode") != "ready"):
        return True
    return (c.get("workflow_mode") == "viewport" and c.get("engine") == "h3"
            and bool(c.get("h3_viewport_direct")) and project.get("look_mode") != "ready")


def _viewport_project(project):
    """Expose the single shared viewport flag and ordered reference roles to model builders."""
    result = copy.copy(project)
    config = dict(project.get("config") or {})
    viewport = config.get("workflow_mode") == "viewport" or bool(config.get("viewport_render"))
    config["viewport_render"] = viewport
    if viewport:
        config["edit_area"] = "scene"
        config["background"] = "restyle"
    result["config"] = config
    result["viewport_render"] = viewport
    references = list(project.get("references", []))
    # Generated looks become a native first-frame guide only in this graph
    # snapshot. Preserve the artist's saved Build from references choice.
    if (viewport and config.get("engine") == "h3" and not h3_viewport_direct(project) and project.get("look_mode") != "ready"
            and project.get("opening_input") and project.get("opening_key")
            and project.get("opening_approval") == project.get("opening_key")):
        result["look_mode"] = "ready"
        result["starting_asset"] = copy.copy(project["opening_input"])
        config.update(finished_frame_position="first", finished_frame_number=1)
    if (viewport and config.get("engine") == "h3" and result.get("look_mode") == "ready" and
            result.get("starting_asset")):
        if len(references) >= 9:
            raise ValueError("H3 can use a finished scene image plus up to eight extra look references.")
        references.insert(0, {**result["starting_asset"], "role": "environment",
                              "viewport_role": "starting_frame"})
    if viewport and not references and project.get("character"):
        references = [project["character"]]
    result["viewport_references"] = [
        {**reference, "role": reference.get("role", "auto")}
        for reference in references
    ]
    return result


def h3_generation_resolution(config):
    """H3 Enhanced 1080p always samples at the tested 720p base raster."""
    if config.get("engine") == "h3" and config.get("delivery_mode") == "enhanced1080":
        return 1280
    return int(config.get("resolution", config.get("size", 512)))


def h3_render_rasters(project, long_edge, *, delivery=False):
    """Mirror the selected route's actual model canvas and encoded raster."""
    import av
    source = check_asset(project["source"])
    with av.open(str(source)) as container:
        stream = container.streams.video[0]
        width, height = int(stream.width), int(stream.height)
    from .enhancement import h3_dimensions, target_dimensions
    c = project.get("config") or {}
    if c.get("workflow_mode") == "viewport" or project.get("viewport_render"):
        if delivery:
            output = target_dimensions(width, height, long_edge)
            return {"width": output[0], "height": output[1]}, {"width": output[0], "height": output[1]}
        # GenjSelectClip preserves undersized sources; the viewport adapter
        # replicates borders to a 32-pixel canvas and crops them after decode.
        scale = min(1.0, long_edge / max(width, height))
        w, h = max(2, round(width * scale / 2) * 2), max(2, round(height * scale / 2) * 2)
        return {"width": ((w + 31) // 32) * 32, "height": ((h + 31) // 32) * 32}, {"width": w, "height": h}
    model, output = h3_dimensions(width, height, long_edge)
    return {"width": model[0], "height": model[1]}, {"width": output[0], "height": output[1]}


class Store:
    def __init__(self, root=None):
        self.root = Path(root or Path(folder_paths.get_output_directory()) / "genj" / "studio")
        self.root.mkdir(parents=True, exist_ok=True)
        self._records = {}

    def _read(self, path):
        stat = path.stat()
        stamp = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        cached = self._records.get(path)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        value = json.loads(path.read_text(encoding="utf8"))
        self._records[path] = (stamp, value)
        # Keep polling bounded even in a workspace with years of saved shots.
        while len(self._records) > 128 or sum(record[0][0] for record in self._records.values()) > 16 * 1024**2:
            self._records.pop(next(iter(self._records)))
        return value

    def save(self, project):
        project["updated"] = time.time()
        path = self.root / (project["id"] + ".json")
        temporary = path.with_suffix(".tmp")
        saved = copy.deepcopy(project)
        # Runtime progress is refreshed from Comfy's in-memory registry and is
        # deliberately never persisted with a project record.
        saved.pop("progress", None)
        temporary.write_text(json.dumps(saved, indent=2), encoding="utf8")
        temporary.replace(path)

    def load(self, identity):
        if not re.fullmatch(r"[a-f0-9]{32}", identity or ""):
            raise ValueError("Choose a saved shot or create a new one.")
        return copy.deepcopy(self._read(self.root / (identity + ".json")))

    def list(self, active_only=False):
        result = []
        for path in self.root.glob("*.json"):
            try:
                p = self._read(path)
                if p.get("kind") == "project" and (not active_only or p.get("phase") == "working"):
                    result.append(copy.deepcopy(p))
            except (ValueError, OSError):
                logging.warning("Zura Studio: could not read a saved project record")
        return sorted(result, key=lambda p: p["updated"], reverse=True)


def check_asset(asset):
    path = Path(folder_paths.get_input_directory()) / asset["file"]
    root = (Path(folder_paths.get_input_directory()) / "genj_studio").resolve()
    if not path.resolve().is_relative_to(root) or sha(path) != asset["sha"]:
        raise ValueError("An uploaded reference has changed. Upload it again before continuing.")
    return path


def validate_selection(project):
    """Reject unsupported timelines before mask tracking or reference encoding."""
    c = project["config"]
    if c.get("h3_character_method") == "openjutsu":
        from .openjutsu import build_graph as openjutsu_graph
        # Validate this narrower experiment before tracking or generating a look.
        probe = copy.deepcopy(project)
        if c.get("openjutsu_background") == "replace" and not probe.get("opening_input"):
            probe["config"]["openjutsu_background"] = "keep"
        openjutsu_graph(probe, check_asset)
    if camera_setup(c):
        from .h3_camera import selected_frame_count
        selected_frame_count(project, check_asset)
        return
    wan2 = c["engine"] == "wan2"
    h3 = c["engine"] == "h3"
    ltx_scene = c["engine"] == "local" and c.get("edit_area") == "scene"
    wan_speech = c["engine"] == "wan" and bool(project.get("audio")) and c.get("lip_sync")
    if not (h3 or ltx_scene or wan_speech or wan2):
        return
    path = check_asset(project["source"])
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        source_has_audio = bool(container.streams.audio)
        available = (float(stream.duration * stream.time_base) if stream.duration is not None
                     else float((container.duration or 0) / av.time_base))
    if not math.isfinite(available) or available <= 0:
        raise ValueError("The source video has no valid duration. Upload it again.")
    start = 0 if c.get("length_mode") == "original" else c["start"]
    seconds = available if c.get("length_mode") == "original" else min(c["duration"], available - start)
    if seconds <= 0:
        raise ValueError("The start time is beyond the end of this video.")
    frames = max(1, int(seconds * 24 + 1e-6))
    if h3 and not 5 <= frames <= 120:
        raise ValueError("H3 currently supports 0.21 to 5 seconds. Choose a shorter custom clip, or use Wan for a longer take.")
    if head_swap_setup(c):
        if frames > 48:
            raise ValueError("Head & face is approved for up to two seconds. Choose a shorter custom clip.")
        if not source_has_audio:
            raise ValueError("Head & face currently requires a video with original audio. Use Full character for silent footage or new dialogue.")
    if ltx_scene and frames > (360 if c.get("workflow_mode") == "viewport" else 120):
        limit = "15 seconds" if c.get("workflow_mode") == "viewport" else "5 seconds"
        raise ValueError(f"LTX whole-scene generation currently supports up to {limit}. Choose a shorter custom clip.")
    if wan2 and (frames < 5 or frames > 81):
        raise ValueError("Wan Animate 2 currently supports 0.21 to 3.375 seconds. Choose a shorter clip.")
    if wan_speech and frames > 720:
        raise ValueError("Wan replacement speech currently supports up to 30 seconds. Choose a shorter custom clip.")


def prep_key(project):
    from .opening_subject import directed_source_subject
    from .opening_edit import replacement_target, target_position
    settings = {"source": project["source"]["sha"], **{k: project["config"][k] for k in PREP_KEYS}}
    if project["config"].get("remove_text"):
        settings["remove_text"] = 6
    if project["config"].get("length_mode") == "original":
        settings["length_mode"] = "original"
    c = project["config"]
    directed_subject = directed_source_subject(c)
    if directed_subject:
        settings["directed_source_subject"] = directed_subject
    if c.get("workflow_mode") == "swap" and c.get("mask_method") == "auto":
        position = target_position(replacement_target(c))
        if position != 'auto':
            settings['opening_person_position'] = position
    if c.get("remove_text") and c.get("engine") == "h3" and c.get("edit_area") == "scene":
        settings["h3_scene_text_regions"] = 1
    if c.get("workflow_mode") == "relight" and not c.get("remove_text"):
        settings["relight_text_protection"] = 1
    # Bind new reviews to the cut-aware native tracking recipe. Remembered
    # inactive click/text controls still cannot alter a scene selection.
    if c.get("preserve_people"):
        # Inactive performer/click controls do not change the all-person protection mask.
        settings.update(preserve_people=True, tracking_recipe=2, person_boundary_recipe=1)
        for key in ("scope", "performer", "margin"):
            settings.pop(key)
    if c.get("edit_area", "mask") != "scene" and (c.get("preserve_people") or c.get("mask_method", "auto") in ("auto", "text")):
        settings["tracking_recipe"] = 2
    if c.get("edit_area", "mask") == "scene":
        settings["edit_area"] = "scene"
        for key in ("scope", "performer", "margin"):
            settings.pop(key)
    elif not c.get("preserve_people") and c.get("mask_method", "auto") == "text":
        settings.update(mask_method="text", mask_prompt=c.get("mask_prompt", ""))
        for key in ("scope", "performer"):
            settings.pop(key)
    elif not c.get("preserve_people") and c.get("mask_method", "auto") == "points":
        settings.update(mask_method="points", mask_points=c.get("mask_points", []))
        for key in ("scope", "performer"):
            settings.pop(key)
    if project.get("audio"):
        settings.update(audio=project["audio"]["sha"], audio_start=project["config"].get("audio_start", 0))
    return hashlib.sha256(canonical(settings).encode()).hexdigest()


def assert_approved(project):
    from . import verify_review
    if not project.get("review") or project.get("approval") != prep_key(project):
        if project.get("config", {}).get("workflow_mode") == "relight":
            raise ValueError("The source clip changed. Create and review a new lighting frame before relighting.")
        raise ValueError("Check the mask preview and choose Use this mask first.")
    check_asset(project["source"])
    if project.get("audio"):
        check_asset(project["audio"])
    verify_review(project["review"])


def text_cache_info(graph, stage):
    key = "5404" if stage == "background" else "5508"
    negative = "9008" if stage == "background" else "5509"
    prefix = "5407" if stage == "background" else "5004"
    encoder = graph[prefix + ":5606"]["inputs"]
    model = folder_paths.get_full_path("text_encoders", encoder["clip_name"])
    stamp = (Path(model).stat().st_size, Path(model).stat().st_mtime_ns) if model else None
    info = {"positive": graph[key]["inputs"]["value"], "negative": graph[negative]["inputs"]["value"],
            "encoder": encoder, "stamp": stamp, "format": 1}
    return hashlib.sha256(canonical(info).encode()).hexdigest(), info


def text_graph(info, cache_key):
    return {
        "encoder": {"class_type": "CLIPLoader", "inputs": info["encoder"]},
        "positive": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["encoder", 0], "text": info["positive"]}},
        "negative": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["encoder", 0], "text": info["negative"]}},
        "save": {"class_type": "GenjSaveTextConditioning", "inputs": {"positive": ["positive", 0],
                  "negative": ["negative", 0], "cache_key": cache_key}},
    }


def ltx25_scene_route(project, stage):
    """Keep masked inpainting on its existing independent native route."""
    return (stage in ("background", "restyle") and
            project["config"].get("engine") == "local" and
            project["config"].get("edit_area") == "scene")


LTX25_DETECTORS = {
    "bbox_detector": Path("comfyui_controlnet_aux/ckpts/yzd-v/DWPose/yolox_l.onnx"),
    "pose_estimator": Path("comfyui_controlnet_aux/ckpts/hr16/DWPose-TorchScript-BatchSize5/dw-ll_ucoco_384_bs5.torchscript.pt"),
}


def ltx25_detector_paths():
    roots = folder_paths.get_folder_paths("custom_nodes")
    return {name: next((Path(root) / relative for root in roots if (Path(root) / relative).is_file()), None)
            for name, relative in LTX25_DETECTORS.items()}


def ltx25_viewport_readiness(node_mappings):
    """Check the raw-layout graph, independently of the human-pose route."""
    from .ltx25 import VIEWPORT_MODELS
    categories = {"model": "diffusion_models", "video_vae": "vae", "audio_vae": "vae",
                  "union": "loras", "upscaler": "latent_upscale_models"}
    files = [{"folder": categories[key], "filename": name,
              "ready": bool(folder_paths.get_full_path(categories[key], name))}
             for key, name in VIEWPORT_MODELS.items()]
    text = "gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors"
    files.append({"folder": "text_encoders", "filename": text,
                  "ready": bool(folder_paths.get_full_path("text_encoders", text))})
    required_nodes = (
        "CLIPLoader", "CLIPTextEncode", "GenjSaveTextConditioning", "GenjLoadTextConditioning",
        "GenjLoadReviewedShot", "GenjLTXFramePad", "GetVideoComponents", "ImageFromBatch",
        "ImageScale", "SaveImage", "VHS_LoadImagesPath", "ZuraSaveVideoLatentData",
        "ZuraLoadVideoLatentData", "LTXVConditioning", "VAELoader", "UNETLoader",
        "LTXICLoRALoaderModelOnly", "EmptyLTXVLatentVideo", "LoadImage", "LTXAddVideoICLoRAGuide",
        "LTXVEmptyLatentAudio", "LTXVConcatAVLatent", "CFGGuider", "RandomNoise",
        "KSamplerSelect", "ManualSigmas", "SamplerCustomAdvanced", "LTXVSeparateAVLatent",
        "LTXVCropGuides", "LatentUpscaleModelLoader", "LTXVLatentUpsampler", "VAEDecodeTiled",
        "TrimAudioDuration", "CreateVideo", "SaveVideo")
    missing = [name for name in required_nodes if name not in node_mappings]
    return {"ready": all(item["ready"] for item in files) and not missing,
            "model_files": files, "missing_nodes": missing}


def _ltx25_model_pin(path):
    """Bounded file identity; model payloads are never loaded by Studio."""
    path = Path(path).resolve(strict=True)
    before = path.stat()
    with path.open("rb") as stream:
        prefix = stream.read(65536)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("An LTX model changed while preparing this render.")
    return {"path": str(path), "size": before.st_size, "mtime_ns": str(before.st_mtime_ns),
            "prefix_sha256": hashlib.sha256(prefix).hexdigest()}


def ltx25_native_plan(project):
    """Resolve the current reviewed interval and model files without inference."""
    from . import verify_review
    from .ltx25 import QUALIFIED_MODELS, VIEWPORT_MODELS, build_plan
    assert_approved(project)
    source = check_asset(project["source"])
    check_asset(project["character"])
    check_asset(project["opening_input"])
    directory, manifest = verify_review(project["review"])
    clip = manifest["clip"]
    reviewed_source = Path(directory) / "source.mp4"
    with av.open(str(source)) as container:
        stream = container.streams.video[0]
        width, height = int(stream.width), int(stream.height)
        source_has_audio = bool(getattr(container.streams, "audio", []))
    # A reviewed silent source contains a valid silence stream for decoding;
    # its metadata retains whether the source/selected track actually exists.
    scenario = ("replacement" if project.get("audio") and project["config"].get("lip_sync") else
                "original" if project.get("audio") or source_has_audio else "silent")
    timeline = {"frames": clip["frames"], "fps": clip["fps"], "width": width, "height": height,
                "has_audio": bool(clip.get("has_audio")), "source_has_audio": source_has_audio, "start": clip["start"],
                "review_source_sha256": sha(reviewed_source)}
    viewport = bool(project.get("config", {}).get("viewport_render"))
    objects = project.get("config", {}).get("subject_mode") == "objects"
    model_set = VIEWPORT_MODELS if viewport else {k: v for k, v in QUALIFIED_MODELS.items()
        if not objects or k not in ("bbox_detector", "pose_estimator")}
    categories = {"model": "diffusion_models", "video_vae": "vae", "audio_vae": "vae",
                  "union": "loras", "upscaler": "latent_upscale_models"}
    paths = {}
    for name, category in categories.items():
        value = folder_paths.get_full_path(category, model_set[name])
        if not value:
            raise ValueError("An LTX 2.5 component is missing: " + model_set[name])
        paths[name] = Path(value)
    if not viewport and not objects:
        for name, path in ltx25_detector_paths().items():
            if path is None:
                raise ValueError("The local LTX body-motion detector is missing: " + QUALIFIED_MODELS[name])
            paths[name] = path
    encoder = {"clip_name": "gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors", "type": "ltxv", "device": "default"}
    encoder_path = folder_paths.get_full_path("text_encoders", encoder["clip_name"])
    if not encoder_path:
        raise ValueError("The LTX 2.5 text encoder is missing: " + encoder["clip_name"])
    paths["text_encoder"] = Path(encoder_path)
    # Read only the Union safetensors header to verify its native grid factor.
    with paths["union"].open("rb") as stream:
        length = int.from_bytes(stream.read(8), "little")
        if not 0 < length <= 16 * 1024 * 1024:
            raise ValueError("The LTX Union adapter has an invalid metadata header.")
        header = json.loads(stream.read(length))
    factor = 1 if viewport else 2
    metadata_factor = (header.get("__metadata__") or {}).get("reference_downscale_factor")
    if factor == 2 and str(metadata_factor) != "2":
        raise ValueError("The selected LTX adapter does not declare the required guide downscale factor.")
    pins = {name: _ltx25_model_pin(path) for name, path in paths.items()}
    # Bind adapter identities to the same plan used for every cache receipt.
    # The regular model-only validator checks family metadata, special adapter
    # types and explicit confirmation before we read file identity.
    selected = project.get("config", {}).get("custom_loras") or []
    loras = []
    if selected:
        from .custom_loras import apply_to_graph
        paths_by_name = {item.get("name"): folder_paths.get_full_path("loras", item.get("name")) for item in selected}
        if any(not path for path in paths_by_name.values()):
            raise ValueError("The selected LTX LoRA is no longer installed.")
        adapter_pins = {name: _ltx25_model_pin(path) for name, path in paths_by_name.items()}
        sentinel = {"model": {"class_type": "UNETLoader", "inputs": {"unet_name": model_set["model"]}}}
        validated = apply_to_graph(sentinel, "ltx25", selected,
                                   folder_paths.get_filename_list("loras"),
                                   lambda folder, name: paths_by_name.get(name) if folder == "loras" else None)
        for index, item in enumerate(selected):
            node = validated["zura_custom_lora_0_" + str(index)]["inputs"]
            pin = _ltx25_model_pin(paths_by_name[item["name"]])
            if pin != adapter_pins[item["name"]]:
                raise ValueError("The LTX LoRA changed while preparing the render. Try again.")
            loras.append({"name": node["lora_name"], "strength": node["strength_model"],
                          "pin": pin})
    return build_plan(_viewport_project(project), scenario=scenario, timeline=timeline,
        models=dict(model_set), text_encoder_inputs=encoder, model_pins=pins,
        approval_key=prep_key(project), original_audio_sha=project["source"]["sha"],
        union_downscale_factor=factor, custom_loras=loras)


def ltx25_phase_graph(project, phase):
    """Recheck current assets and bind only this run's completed native data."""
    from .ltx25 import bind_phase
    run = project.get("ltx25_run") or {}
    plan = ltx25_native_plan(project)
    if not run or run.get("plan", {}).get("key") != plan["key"]:
        raise ValueError("The LTX source, audio or render settings changed. Start a new animation.")
    return bind_phase(plan, phase, run.get("receipts", {}),
                      output_directory=folder_paths.get_output_directory(),
                      input_directory=folder_paths.get_input_directory())


def custom_lora_family(config):
    """Only advertise video routes whose native model path can be patched."""
    if config.get("workflow_mode") == "relight" and config.get("relight_engine") == "wan21":
        return "wan21"
    if config.get("engine") == "h3":
        if config.get("delivery_mode") == "enhanced1080":
            return None  # Enhancement is a separate unqualified model pass.
        return "h3"
    if config.get("engine") == "wan" and config.get("lip_sync"):
        return None  # MultiTalk is a separate Wan sampler with its own loader.
    if config.get("engine") == "local" and config.get("edit_area") == "scene":
        return "ltx25"  # Both LTX sampling phases use the pinned plan.
    return {"wan": "wan22", "wan2": "wan_animate2"}.get(config.get("engine"))


def apply_video_loras(project, stage, graph):
    """Patch every actual video sampler, leaving preparation and stills untouched."""
    selected = project.get("config", {}).get("custom_loras") or []
    if not selected or stage not in ("h3", "wan", "wan2", "wan21_relight"):
        return graph
    # The first Wan graph can be a motion-preparation job, not a sampler.
    if stage == "wan" and "wan_save" in graph:
        return graph
    family = custom_lora_family(project["config"])
    if family is None:
        raise ValueError("Custom LoRAs aren't supported on this video route yet. Remove them or select a supported model.")
    from .custom_loras import apply_to_graph
    return apply_to_graph(graph, family, selected, folder_paths.get_filename_list("loras"), folder_paths.get_full_path)


def build_graph(project, stage, use_cache=True, run_id=None):
    from .opening_subject import directed_source_subject
    from .opening_edit import replacement_target, target_position
    if (project.get("config", {}).get("custom_loras") and
            (stage in ("draft", "final", "h3_enhance", "wan_speech") or
             stage in ("background", "restyle") and not ltx25_scene_route(project, stage) or
             stage.startswith("ltx25_") and stage != "ltx25_cleanup" and custom_lora_family(project["config"]) != "ltx25")):
        raise ValueError("Custom LoRAs aren't available on this video graph yet. Remove them or select a supported model.")
    if camera_setup(project["config"]):
        from .h3_camera import build_studio_graph, build_studio_still_graph
        if stage == "design":
            return build_studio_still_graph(project, check_asset)
        if stage == "h3":
            return apply_video_loras(project, stage, build_studio_graph(project, check_asset))
        raise ValueError("Create the camera frame before generating video.")
    if stage == "wan21_relight":
        from .wan21_relight import build_studio_graph
        return apply_video_loras(project, stage, build_studio_graph(project, check_asset))
    """Fill known native node inputs; no new subgraph interfaces are fabricated."""
    require_relight_direction(project.get("config", {}), supplied_image=project.get("look_mode") == "ready" and bool(project.get("starting_asset")))
    if project.get("config", {}).get("workflow_mode") == "relight" and project["config"].get("engine") != "h3":
        raise ValueError("Relight currently supports MiniMax H3. Choose H3 for this task.")
    if stage.startswith("ltx25_") and stage != "ltx25_cleanup":
        return ltx25_phase_graph(project, stage.removeprefix("ltx25_"))
    if stage == "ltx25_cleanup":
        return {"ack": {"class_type": "PreviewAny", "inputs": {
            "source": "Zura LTX memory hand-off " + project["id"]}}}
    if stage == "wan2":
        assert_approved(project)
        from .wan_animate2 import build_studio_graph
        return apply_video_loras(project, stage, build_studio_graph(project, check_asset))
    if stage == "wan_speech":
        from .wan_speech import build_graph as speech_graph
        return speech_graph(project)
    if stage == "wan_cleanup":
        previous = project.get("actions", [])[-1] if project.get("actions") else {}
        is_h3_handoff = previous.get("stage") == "h3" and previous.get("delivery_mode") == "enhanced1080"
        label = "H3 enhancement" if is_h3_handoff else "Wan"
        return {"ack": {"class_type": "PreviewAny", "inputs": {
            "source": f"Zura {label} memory hand-off " + project["id"]}}}
    if stage == "h3":
        if project["config"].get("h3_character_method") == "openjutsu":
            assert_approved(project)
            if not h3_viewport_direct(project) and (project.get("opening_approval") != project.get("opening_key") or not project.get("opening_input")):
                raise ValueError("Review your starting frame before the OpenJutsu test.")
            from .openjutsu import build_graph as openjutsu_graph
            return apply_video_loras(project, stage, openjutsu_graph(project, check_asset))
        if head_swap_setup(project.get("config", {})):
            from .h3_head_swap import build_studio_graph
            return apply_video_loras(project, stage, build_studio_graph(project, check_asset))
        from .h3 import build_h3_graph
        return apply_video_loras(project, stage, build_h3_graph(_viewport_project(project), use_cache=use_cache))
    if stage == "design" and h3_viewport_direct(project):
        raise ValueError("Choose Build starting frame to generate an opening, or generate video using references directly.")
    if stage == "h3_enhance":
        from .enhancement import build_graph as enhancement_graph
        return enhancement_graph(project, project.get("h3_enhancement_base"), run_id=run_id)
    if stage == "wan":
        from .wan import build_wan_graph
        return apply_video_loras(project, stage, build_wan_graph(_viewport_project(project), use_cache=use_cache))
    if stage == "design" and project.get("look_mode") == "ready":
        if project.get("config", {}).get("preserve_people"):
            raise ValueError("Keep original people currently requires Build from references so the opening can be registered to the protected source.")
        assert_approved(project)
        asset = project.get("starting_asset")
        if not asset:
            raise ValueError("Upload your finished starting frame first.")
        check_asset(asset)
        return {"starting_frame": {"class_type": "LoadImage", "inputs": {"image": asset["file"]},
                                   "_meta": {"title": "Finished starting frame · no generation"}},
                "preview": {"class_type": "PreviewImage", "inputs": {"images": ["starting_frame", 0]},
                            "_meta": {"title": "Review the starting frame"}}}
    graph = json.loads((HERE / "graphs" / (STAGES[stage] + ".json")).read_text(encoding="utf8"))
    c = project["config"]
    if stage != "prepare":
        assert_approved(project)
        if project.get("character"):
            check_asset(project["character"])
        elif c.get("workflow_mode") != "relight":
            raise ValueError("Add an appearance reference image.")
    for node in graph.values():
        typ, inputs = node["class_type"], node["inputs"]
        if typ == "GenjLoadReviewedShot":
            inputs.update(shot_id=project["review"], approved_shot_id=project["review"])
            node["_meta"] = {"title": "Reviewed shot · automatic"}
        elif typ == "RandomNoise":
            inputs["noise_seed"] = c["seed"]
        elif typ == "GenjRestoreSoundtrack":
            inputs["take_name"] = "studio_" + project["id"][:8] + "_" + stage
    if stage == "prepare":
        check_asset(project["source"])
        graph["2"]["inputs"]["file"] = project["source"]["file"]
        graph["3"]["inputs"].update(start_seconds=c["start"], duration_seconds=c["duration"], long_edge=c["size"],
                                     use_original_length=c["length_mode"] == "original")
        if project.get("audio"):
            check_asset(project["audio"])
            graph["zura_reference_audio"] = {"class_type": "LoadAudio", "inputs": {"audio": project["audio"]["file"]},
                "_meta": {"title": "Reference audio · optional"}}
            graph["3"]["inputs"].update(audio=["zura_reference_audio", 0], audio_start_seconds=c["audio_start"])
        graph["7"]["inputs"]["text"] = c["scope"]
        graph["8"]["inputs"].pop("bboxes", None)  # Text detection over the entire source, at any aspect ratio.
        graph["9"]["inputs"]["performer"] = c["performer"]
        graph["12"]["inputs"]["expand"] = c["margin"]
        graph["18"]["inputs"]["pitch_vocals"] = c["pitch"]
        if c.get("preserve_people"):
            # Detect all visible people as a joint protection track, not just the largest performer.
            # Native SAM defaults to one detection per category. Explicitly
            # request all visible people before forming the protection union.
            graph["7"]["inputs"]["text"] = "person:20"
            graph["8"]["inputs"]["individual_masks"] = False
            graph["9"]["inputs"]["performer"] = -1
        elif c["edit_area"] == "scene":
            # One full-frame mask is generated for every real source frame.
            # Whole-scene edits skip subject tracking. Relight additionally
            # protects detected lettering unless its removal was requested.
            relight_text = (c.get("workflow_mode") == "relight" and c.get("relight_engine") != "wan21"
                            and not c.get("remove_text"))
            if relight_text:
                graph["zura_relight_sam"] = graph.pop("6")
                graph["zura_relight_sam"]["_meta"] = {"title": "Detect source lettering to keep"}
            keep_text_detector = c.get("remove_text") and c.get("engine") == "h3"
            for key in ("6", "7", "8", "9", "10", "11"):
                if key == "6" and keep_text_detector:
                    continue
                graph.pop(key, None)
            graph["12"] = {"class_type": "ZuraWholeSceneMask", "inputs": {"images": ["4", 0]},
                           "_meta": {"title": "Whole scene · no selection mask"}}
            if relight_text:
                graph["zura_relight_text_prompt"] = {"class_type": "CLIPTextEncode", "inputs": {
                    "clip": ["zura_relight_sam", 1], "text": "text:20"}}
                graph["zura_relight_text_detect"] = {"class_type": "SAM3_Detect", "inputs": {
                    "model": ["zura_relight_sam", 0], "image": ["4", 0],
                    "conditioning": ["zura_relight_text_prompt", 0], "threshold": 0.5,
                    "refine_iterations": 0, "individual_masks": False},
                    "_meta": {"title": "Find lettering in every source frame"}}
                graph["zura_relight_text_margin"] = {"class_type": "GrowMask", "inputs": {
                    "mask": ["zura_relight_text_detect", 0], "expand": 5, "tapered_corners": True}}
                graph["zura_relight_edit_mask"] = {"class_type": "InvertMask", "inputs": {
                    "mask": ["zura_relight_text_margin", 0]},
                    "_meta": {"title": "Relight scene · protect source lettering"}}
                for target in ("17", "20"):
                    graph[target]["inputs"]["mask"] = ["zura_relight_edit_mask", 0]
        elif (c["mask_method"] == "auto" and c.get("workflow_mode") == "swap"
              and target_position(replacement_target(c)) != 'auto'):
            graph["7"]["inputs"]["text"] = "person:20"
            graph["8"]["inputs"]["individual_masks"] = True
            graph["9"]["inputs"].update(performer=-1, position=target_position(replacement_target(c)))
        elif c["mask_method"] == "text" or directed_source_subject(c):
            if not c["mask_prompt"] and not directed_source_subject(c):
                raise ValueError("Describe the area to change before preparing the mask.")
            graph["7"]["inputs"]["text"] = (directed_source_subject(c) or c["mask_prompt"])
            graph["8"]["inputs"]["individual_masks"] = False
            graph["9"]["inputs"]["performer"] = -1
        elif c["mask_method"] == "points":
            from .mask_selection import clean_points
            points = clean_points(c["mask_points"], require_positive=True)
            # Native SAM treats text and point results as separate masks. A
            # point correction must use only its included/excluded clicks.
            graph.pop("7")
            graph["8"]["inputs"].pop("conditioning")
            graph["zura_mask_points"] = {"class_type": "ZuraMaskPoints", "inputs": {
                "image": ["5", 0], "points_json": json.dumps(points)},
                "_meta": {"title": "Clicks · include and exclude"}}
            graph["8"]["inputs"].update(positive_coords=["zura_mask_points", 0],
                                            negative_coords=["zura_mask_points", 1], individual_masks=False)
            graph["9"]["inputs"]["performer"] = -1
        if c["edit_area"] != "scene" and (c.get("preserve_people") or c["mask_method"] in ("auto", "text")):
            # ComfyUI pairs each segment and its first frame through the visible
            # native detector/tracker. The join restores the original timeline.
            graph["zura_split_tracking_shots"] = {"class_type": "ZuraSplitTrackingShots",
                "inputs": {"images": ["4", 0]},
                "_meta": {"title": "Reset tracking at camera cuts"}}
            graph["8"]["inputs"]["image"] = ["zura_split_tracking_shots", 1]
            graph["10"]["inputs"]["images"] = ["zura_split_tracking_shots", 0]
            graph["zura_join_tracking_masks"] = {"class_type": "ZuraJoinTrackingMasks",
                "inputs": {"masks": ["11", 0], "tracking_segments": ["zura_split_tracking_shots", 2]},
                "_meta": {"title": "Rejoin tracked shots · keep every source frame"}}
            graph["12"]["inputs"]["mask"] = ["zura_join_tracking_masks", 0]
            graph["20"]["inputs"]["tracking_coverage"] = ["zura_join_tracking_masks", 1]
        if c.get("preserve_people"):
            # Keep the complete tracked silhouette, including soft edge pixels,
            # without carrying a band of the old surroundings into the new look.
            # Replacement margin expands an editable subject; it must not expand
            # protected people when the editable region is their surroundings.
            graph["12"]["inputs"]["expand"] = 0
            graph["12"]["_meta"] = {"title": "Original people · exact tracked silhouette"}
            graph["zura_edit_surroundings"] = {"class_type": "InvertMask", "inputs": {"mask": ["12", 0]},
                "_meta": {"title": "Change surroundings · protect original people"}}
            graph["17"]["inputs"]["mask"] = ["zura_edit_surroundings", 0]
            graph["20"]["inputs"]["mask"] = ["zura_edit_surroundings", 0]
        if c.get("remove_text") and (c["edit_area"] != "scene" or c["engine"] == "h3") and not c.get("preserve_people"):
            graph["text_prompt"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["6", 1], "text": "text:20"}}
            graph["text_detect"] = {"class_type": "SAM3_Detect", "inputs": {
                "model": ["6", 0], "image": ["4", 0], "conditioning": ["text_prompt", 0],
                "threshold": 0.5, "refine_iterations": 0, "individual_masks": False}}
            graph["text_removal"] = {"class_type": "GenjTextRemovalMask", "inputs": {
                "performer_mask": ["12", 0], "text_mask": ["text_detect", 0],
                "text_boxes": ["text_detect", 1], "clip_details": ["3", 1], "padding": 5}}
            graph["17"]["inputs"]["mask"] = ["text_removal", 0]
            graph["20"]["inputs"].update(mask=["text_removal", 0], clip_details=["text_removal", 1])
            if c["edit_area"] != "scene":
                graph["20"]["inputs"]["performer_mask"] = (["zura_join_tracking_masks", 0]
                    if "zura_join_tracking_masks" in graph else ["11", 0])
            if "zura_split_tracking_shots" in graph:
                graph["text_removal"]["inputs"]["tracking_segments"] = ["zura_split_tracking_shots", 2]
        # Only Seedance consumes the coloured-depth review video. Local video
        # engines build their own guidance after the artist approves the look;
        # loading Depth Anything in this preliminary review graph did duplicate
        # inference and delayed the first useful mask/footage preview.
        if c.get("engine") != "seedance":
            graph["20"]["inputs"]["guide_frames"] = ["4", 0]
            for identity in ("13", "15", "16", "17"):
                graph.pop(identity, None)
    elif stage == "design":
        from .opening_edit import (bind_original_frame, replacement_target, add_target_mask,
                                   constrain_sampling, restore_source_size)
        check_asset(project["source"])
        bind_original_frame(graph, project)
        if project.get("character"):
            graph["121"]["inputs"]["image"] = project["character"]["file"]
        for key in ("92:111", "92:85"):
            graph[key]["inputs"]["resolution_steps"] = 16
        if c["edit_area"] == "scene":
            graph["127"]["inputs"]["value"] = (
                "If the second image shows a character, replace the visible performer in the first image "
                "with that character. For a character sheet, select one coherent identity and outfit. "
                "Match the second image's face identity, hairstyle, hat or headwear, clothing and accessories; "
                "in this character replacement, do not retain the first performer's face or clothing. "
                "If the second image shows only an environment, apply its scene appearance without inventing "
                "a reference character or changing the performer's identity and outfit. Keep one performer in the first image's "
                "same body pose, head angle and position. Finish the whole scene using any environment shown "
                "in the second image as the intended scene appearance, adapted to the first image's geometry. "
                "Preserve the first image's camera framing, lens perspective, ground plane, object positions "
                "and foot contact. Return one complete scene with the same composition and aspect ratio, "
                "without a reference sheet or duplicate character. Do not add text or extra people.")
            graph["127"]["inputs"]["value"] += (
                " If the appearance reference shows an object or product, replace the matching object "
                "using its shape, materials and details. Keep its scene position, scale and perspective. "
                "Do not turn an object reference into a person.")
            if c.get("workflow_mode") == "viewport":
                graph["127"]["inputs"]["value"] = (
                    "Turn the grey 3D viewport/blockout into one finished, coherent scene. Treat the first image as "
                    "the exact composition, camera perspective, subject placement, geometry and ground contact to preserve. "
                    "Use the appearance references only for the elements they depict. Replace the grey viewport shading "
                    "throughout the full frame, keep the existing subjects and objects in place, and do not add or remove "
                    "scene elements. Return one finished frame with the same composition and aspect ratio. Do not add text.")
        elif c["mask_method"] != "auto":
            region = ("the area described as " + c["mask_prompt"] if c["mask_method"] == "text"
                      else "the selected performer or object")
            graph["127"]["inputs"]["value"] = (
                "In the first image, change only " + region + " using the second image as the appearance reference. "
                "Keep the original camera framing, pose, ground contact, background and unselected objects. "
                "Return one complete scene with the same composition. Do not add text or extra people.")
        elif c["scope"] == "head":
            graph["127"]["inputs"]["value"] = (
                "In the first image, replace only the performer's head with the identity from the second image. "
                "Match the face and hairstyle. Keep the original body, clothing, pose, head angle, expression, "
                "camera framing, background, objects and lighting unchanged. Return one complete scene. "
                "Do not add text or extra people.")
        elif c.get("workflow_mode") == "swap":
            from .opening_subject import replacement_direction
            graph["127"]["inputs"]["value"] = replacement_direction(directed_source_subject(c))
        if c.get("workflow_mode") == "motion" and replacement_target(c):
            from .opening_subject import replacement_direction
            graph["127"]["inputs"]["value"] = replacement_direction(replacement_target(c)) + (
                " Preserve every other person exactly: their count, face, clothes, pose and position. "
                "Do not use the reference background or copy multiple people from a character sheet.")
        if c.get("preserve_people"):
            graph["127"]["inputs"]["value"] = (
                "Change only the surroundings outside the reviewed protected people, using the references for scene appearance. "
                "Keep every original person's identity, face, apparent age, expression, hair, clothing, body, pose and position unchanged. "
                "Do not use a person in an appearance reference as a replacement. Preserve the source camera framing, "
                "perspective, scene layout and ground contact. Return one complete scene with no extra people.")
        if c.get("workflow_mode") == "relight":
            graph["127"]["inputs"]["value"] = (
                "Relight the first image only. Keep every person\'s identity, apparent age, face, expression, "
                "clothes, materials, object shapes, scene layout, camera framing and perspective unchanged. "
                "Change only illumination: light direction, intensity, colour, shadows, highlights and exposure. "
                "Additional images, if provided, describe lighting only, never replacement characters or objects. "
                "Return the same scene under the requested lighting, with no new or removed elements.")
        image_direction = c.get("image_prompt") or c["prompt"]
        if image_direction:
            graph["127"]["inputs"]["value"] += " Additional appearance direction: " + image_direction
        if c.get("remove_text"):
            graph["127"]["inputs"]["value"] += " Remove all on-screen captions, subtitles, title banners and lettering. Fill their former areas naturally with the scene or clothing."
        from .appearance import add_design_references
        references = project.get("references") or ([project["character"]] if project.get("character") else [])
        if c.get("workflow_mode") == "relight" and not references:
            # Source composition is already the first ReferenceLatent. Do not
            # load the video filename through an image loader for the absent second image.
            graph["92:103"]["inputs"].update(positive=["92:128", 0], negative=["92:126", 0])
        elif c.get("opening_model", "klein9b") == "klein9b":
            if len(references) > 3:
                raise ValueError("FLUX Klein 9B accepts three appearance references. Remove extras or choose Qwen Image 2.1.")
            add_design_references(graph, references, check_asset, lighting_only=c.get("workflow_mode") == "relight")
        for asset in references:
            check_asset(asset)
        if c.get("workflow_mode") == "viewport":
            role_names = {"auto": "visual reference", "environment": "environment", "character": "character",
                          "object": "object", "detail": "detail", "style": "style"}
            refs = project.get("references") or [project["character"]]
            role_text = " ".join(
                f"Reference {index + 1} is for the {role_names.get(asset.get('role', 'auto'), 'visual')} ."
                for index, asset in enumerate(refs[:3]))
            graph["127"]["inputs"]["value"] += (
                " Map each image to the scene element it depicts: " + role_text +
                " Preserve distinct characters as distinct designs; do not copy a character sheet into the frame.")
        from .opening_subject import missing_opening_selection
        missing_subject = missing_opening_selection(project)
        opening_mask = add_target_mask(graph, project)
        # A named non-person replacement can need a new silhouette. Its
        # opening edit uses source/reference conditioning, rather than being
        # pasted back through the old object's shape. Video masks stay intact.
        if (opening_mask or (c["edit_area"] == "mask" and not missing_subject and not directed_source_subject(c))
                or (c.get("workflow_mode") == "relight" and c.get("relight_engine") != "wan21" and not c.get("remove_text"))):
            # Register the approved opening look to the real source before
            # video inference. Only the selected region may change; this is
            # never a post-generation paste of the original performer.
            graph["zura_look_source"] = {"class_type": "ImageScale", "inputs": {
                "image": ["125", 0], "upscale_method": "lanczos", "crop": "disabled",
                "width": ["92:114", 0], "height": ["92:114", 1]}}
            graph["zura_look_mask_video"] = {"class_type": "GetVideoComponents", "inputs": {"video": ["123", 1]}}
            graph["zura_look_mask_frame"] = {"class_type": "ImageFromBatch", "inputs": {
                "image": ["zura_look_mask_video", 0], "batch_index": 0, "length": 1}}
            graph["zura_look_mask"] = {"class_type": "ImageToMask", "inputs": {
                "image": ["zura_look_mask_frame", 0], "channel": "red"}}
            if opening_mask:
                # The video engine may regenerate the whole frame. Its
                # starting-image edit still targets exactly one performer.
                for identity in ("zura_look_mask", "zura_look_mask_frame", "zura_look_mask_video"):
                    graph.pop(identity, None)
            # Review masks are videos: remove codec noise, then soften the
            # opening boundary inside the reviewed area. Neither operation
            # increases that area or changes a saved review.
            graph["zura_look_boundary"] = {"class_type": "ThresholdMask", "inputs": {
                "mask": opening_mask or ["zura_look_mask", 0], "value": 0.5}}
            graph["zura_look_boundary_image"] = {"class_type": "MaskToImage", "inputs": {
                "mask": ["zura_look_boundary", 0]}}
            graph["zura_look_boundary_blur"] = {"class_type": "ImageBlur", "inputs": {
                "image": ["zura_look_boundary_image", 0], "blur_radius": 3, "sigma": 1.0}}
            graph["zura_look_soft_mask"] = {"class_type": "ImageToMask", "inputs": {
                "image": ["zura_look_boundary_blur", 0], "channel": "red"}}
            graph["zura_look_inside_mask"] = {"class_type": "MaskComposite", "inputs": {
                "destination": ["zura_look_boundary", 0], "source": ["zura_look_soft_mask", 0],
                "x": 0, "y": 0, "operation": "multiply"}}
            graph["zura_masked_look"] = {"class_type": "ImageCompositeMasked", "inputs": {
                "destination": ["zura_look_source", 0], "source": ["92:105", 0],
                "mask": ["zura_look_inside_mask", 0], "x": 0, "y": 0, "resize_source": False},
                "_meta": {"title": "Opening look · change only the reviewed area"}}
            graph["122"]["inputs"]["images"] = ["zura_masked_look", 0]
            if c.get("workflow_mode") in ("swap", "motion"):
                constrain_sampling(graph, ["zura_look_boundary", 0])
        from .opening_models import apply_model
        apply_model(graph, c.get("opening_model", "klein9b"), references)
        if c.get("opening_width") and c.get("opening_height"):
            graph["92:111"] = {"class_type": "ImageScale", "inputs": {
                "image": ["125", 0], "width": c["opening_width"], "height": c["opening_height"],
                "upscale_method": "lanczos", "crop": "center"},
                "_meta": {"title": "Starting image generation resolution"}}
        restore_source_size(graph)
        graph["122"]["inputs"]["filename_prefix"] = "genj/studio_images/" + project["id"]
        if c.get("workflow_mode") == "relight" and not references:
            from .h3 import reachable_graph
            graph = reachable_graph(graph, ["122"])
    elif stage in ("background", "restyle"):
        if project.get("opening_approval") != project.get("opening_key") or not project.get("opening_input"):
            raise ValueError("Check the character preview and choose Animate this look first.")
        check_asset(project["opening_input"])
        graph["2004"]["inputs"]["image"] = project["opening_input"]["file"]
        for node in graph.values():
            if node["class_type"] == "GenjLoadReviewedShot":
                node["inputs"]["render_long_edge"] = c.get("resolution", c.get("render_size") or c["size"])
                node["inputs"]["output_scale"] = 1 if stage == "background" else 2
                node["inputs"]["preview_seconds"] = 0
        if stage == "background":
            # The preview decoder may have rounded the aspect ratio differently.
            # Restore its normalised registration before I2V's implicit centre crop.
            graph["5408:5188"]["inputs"] = {"input": ["2004", 0], "resize_type": "match size",
                "scale_method": "lanczos", "resize_type.match": ["5408:5371", 0], "resize_type.crop": "disabled"}
            for mask_resize in ("5408:5373", "5408:5381"):
                graph[mask_resize]["inputs"]["resize_type.crop"] = "disabled"
            # Native square max-pooling is extremely slow on HD CPU masks.
            # Mask Fix uses the equivalent rectangular maximum filter; keep
            # the exact radius and >0.5 threshold with no blur or hole filling.
            for identity in ("5408:5379", "5408:5382"):
                inputs = graph[identity]["inputs"]
                kernel, grow = identity + "_kernel", identity + "_grow"
                graph[kernel] = {"class_type": "ComfyMathExpression", "inputs": {
                    "expression": "2*a+1", "values.a": inputs["spatial_radius"]}}
                graph[grow] = {"class_type": "MaskFix+", "inputs": {"mask": inputs["mask"],
                    "erode_dilate": [kernel, 1], "fill_holes": 0, "remove_isolated_pixels": 0,
                    "smooth": 0, "blur": 0}}
                graph[identity] = {"class_type": "ThresholdMask", "inputs": {"mask": [grow, 0], "value": 0.5}}
        # Replacement always uses the approved scene image. The CLI exporter can
        # ignore promoted native widgets and retain the inner T2V default instead.
        image_switch = "5408:9018" if stage == "background" else "5014:5506"
        graph[image_switch]["inputs"]["value"] = True
        for node in graph.values():
            if node["class_type"] == "LTXVImgToVideoInplace":
                node["inputs"]["bypass"] = False
        # Use the LTX-2.5 A2V template's zero-noise source-audio path.
        # Speaker-reference tokens are identity context, not timed speech.
        graph["zura_fixed_audio_mask"] = {"class_type": "SolidMask", "inputs": {
            "value": 0.0, "width": 1024, "height": 1024}}
        if stage == "background":
            first_cond, second_cond = "5409:5114", "5410:5013"
            guiders, concats = ("5410:4828", "5414:5209"), ("5409:5391", "5413:5396")
            audio_latents = (["5409:5389", 0], ["5410:5394", 1])
            graph["5410:5013"]["inputs"].update(positive=[first_cond, 0], negative=[first_cond, 1])
            graph.pop("5409:5390")
            graph.pop("5413:5395")
            audio_model = ["5407:5607", 0]
        else:
            graph["9002:3980"] = {"class_type": "VAEEncodeAudio", "inputs": {
                "audio": ["9006", 1], "vae": ["5004:5600", 0]}}
            first_cond, second_cond = "9002:5012", "5549"
            guiders, concats = ("5516:4828", "5517:4964"), ("9002:4528", "5517:4969")
            audio_latents = (["9002:3980", 0], ["5516:4845", 1])
            graph["5549"]["inputs"].update(positive=[first_cond, 0], negative=[first_cond, 1])
            audio_model = ["5004:5607", 0]
        graph["zura_av_coupling"] = {"class_type": "LTXVModalityGuidance", "inputs": {
            "model": audio_model, "modality_scale": 1.0, "start_percent": 0.0, "end_percent": 1.0}}
        for index, (guider, concat, cond, audio) in enumerate(zip(
                guiders, concats, (first_cond, second_cond), audio_latents)):
            frozen = "zura_frozen_audio_" + str(index)
            graph[frozen] = {"class_type": "SetLatentNoiseMask", "inputs": {
                "samples": audio, "mask": ["zura_fixed_audio_mask", 0]}}
            graph[concat]["inputs"]["audio_latent"] = [frozen, 0]
            graph[guider]["inputs"].update(model=["zura_av_coupling", 0],
                positive=[cond, 0], negative=[cond, 1])
        key = "5404" if stage == "background" else "5508"
        if c["edit_area"] == "scene" or c["mask_method"] != "auto":
            area = "the whole scene" if c["edit_area"] == "scene" else "only the reviewed masked area"
            graph[key]["inputs"]["value"] = (
                "Transform " + area + " to match the approved opening image and appearance reference. "
                "Follow the source video's changing camera perspective, framing, object positions, "
                "body action, ground plane and foot contact throughout. Keep the original facial performance "
                "and lip movements where a performer is present. Do not introduce sliding feet, extra objects "
                "or reference-sheet layouts. " + ("Preserve all unselected surroundings. " if c["edit_area"] == "mask" else ""))
        if project.get("audio") and c.get("lip_sync"):
            direction = graph[key]["inputs"]["value"]
            direction = direction.replace("Keep the original facial performance and lip movements where a performer is present.",
                "Retain head direction, eye expression and body gestures where a performer is present.")
            direction = direction.replace("expression and lip movements", "head direction, eye expression and body gestures")
            direction = direction.replace("lip movements", "head direction and eye expression")
            graph[key]["inputs"]["value"] = direction + (
                " The supplied audio is the replacement dialogue. Articulate its words through natural mouth and jaw motion,"
                " following the audio timing. Keep a resting mouth during silence. Ignore the source video's old dialogue"
                " and lip movements. Preserve the replacement character's identity from the approved opening image.")
        if c["prompt"]:
            graph[key]["inputs"]["value"] += " Appearance direction: " + c["prompt"]
        if c.get("remove_text"):
            graph[key]["inputs"]["value"] += " Remove the masked captions, subtitles and title banners completely. Fill those areas with clean background or character clothing. No overlaid text or lettering."
        from . import text_cache_path
        cache_key, _ = text_cache_info(graph, stage)
        # These local Studio paths always use the installed text encoder. Strip
        # the template's unused cloud option so graph view cannot activate it.
        cloud_switches = ("5408:5612", "5408:5613") if stage == "background" else ("5014:5558", "5014:5560")
        local_text = {identity: graph[identity]["inputs"]["on_false"] for identity in cloud_switches}
        cloud_nodes = [graph[identity]["inputs"]["on_true"][0] for identity in cloud_switches]
        cloud_flag = graph[cloud_switches[0]]["inputs"]["switch"][0]
        for node in graph.values():
            for name, value in list(node["inputs"].items()):
                if isinstance(value, list) and len(value) == 2 and value[0] in local_text:
                    node["inputs"][name] = local_text[value[0]]
        for identity in (*cloud_switches, *cloud_nodes, cloud_flag):
            graph.pop(identity)
        if use_cache and text_cache_path(cache_key).exists():
            prefix = "5408" if stage == "background" else "5014"
            replacements = {prefix + ":2483": 0, prefix + ":2612": 1}
            for node in graph.values():
                for name, value in node["inputs"].items():
                    if isinstance(value, list) and len(value) == 2 and value[0] in replacements:
                        node["inputs"][name] = ["genj_cached_text", replacements[value[0]]]
            for name in replacements:
                graph.pop(name)
            graph["genj_cached_text"] = {"class_type": "GenjLoadTextConditioning", "inputs": {"cache_key": cache_key}}
    elif stage == "draft":
        from . import verify_review
        _, manifest = verify_review(project["review"])
        if manifest["clip"]["duration"] < 1.8:
            raise ValueError("Seedance needs a clip of at least 1.8 seconds. Choose a longer clip and prepare it again.")
        if c["resolution"] not in (512, 1280, 1920):
            raise ValueError("Seedance supports 480p (the small 512 px option), 720p or 1080p. Choose one of those resolutions.")
        graph["100"]["inputs"]["model.resolution"] = {512: "480p", 1280: "720p", 1920: "1080p"}[c["resolution"]]
        graph["2"]["inputs"]["image"] = project["character"]["file"]
        if c.get("remove_text"):
            graph["100"]["inputs"]["model.prompt"] += " Remove all on-screen captions, subtitles and title banners. Fill their former areas naturally. Do not add text overlays."
        if c["edit_area"] == "mask" and c["mask_method"] == "auto" and c["scope"] == "head":
            graph["100"]["inputs"]["model.prompt"] = graph["100"]["inputs"]["model.prompt"].replace(
                "entire selected subject", "selected head only; keep the body and clothing unchanged")
        if c["background"] == "restyle":
            graph["100"]["inputs"]["model.prompt"] = graph["100"]["inputs"]["model.prompt"].replace(
                "Keep the original RGB background, framing, camera movement", "Restyle the background while retaining framing and camera movement").replace(
                "or change the background", "or change the camera timing")
        graph["100"]["inputs"]["model.prompt"] += " " + c["prompt"]
        graph["100"]["inputs"]["seed"] = c["seed"]
    elif stage == "final":
        task = project.get("draft_task")
        if not task or project.get("accepted_draft") != task:
            raise ValueError("Inspect the draft and choose Finish at 1080p first.")
        graph["2"]["inputs"].update(draft_task_id=task, accepted_draft_id=task)
        graph["2"]["_meta"] = {"title": "Use the accepted draft · automatic"}
    if stage in ("background", "restyle", "draft", "final"):
        from .speech import add_finish
        add_finish(graph, project, native_speech=stage in ("background", "restyle"))
    return graph


def _needs_h3_reference_stage(project, graph):
    """Only legacy H3 needs a serialized reference-conditioning hand-off."""
    return (project.get("config", {}).get("h3_character_method") != "openjutsu"
            and not head_swap_setup(project.get("config", {})) and "h3_cached" not in graph
            and not _viewport_project(project).get("viewport_render", False))


def editable_graph(project, stage="auto"):
    """Export a snapshot without queuing, spending credits or changing approvals."""
    p = copy.deepcopy(project)
    p["config"] = clean_config(p["config"])
    if camera_setup(p["config"]):
        camera_stage = ("h3" if p.get("opening_input") else "design") if stage == "auto" else ("h3" if stage == "animate" else stage)
        if camera_stage == "h3":
            p["opening_approval"] = p.get("opening_key")
        return build_graph(p, camera_stage), camera_stage
    if head_swap_setup(p["config"]):
        if stage not in ("auto", "animate", "h3"):
            raise ValueError("Head & face uses your portrait directly. Open its H3 graph.")
        return build_graph(p, "h3"), "h3"
    if stage == "auto":
        stage = ("prepare" if not p.get("approval") or p["approval"] != prep_key(p) else
                 "animate" if (p.get("opening_input") or h3_viewport_direct(p)) and p["config"]["engine"] != "seedance" else
                 "design" if p["config"]["engine"] != "seedance" else "draft")
    if stage == "animate":
        # Opening the animation stage accepts the visible
        # opening for this exported snapshot. The saved Studio state is untouched.
        if not p.get("opening_input") and not h3_viewport_direct(p):
            raise ValueError("Create the character preview before opening its animation graph.")
        if not h3_viewport_direct(p):
            p["opening_approval"] = p["opening_key"]
        if p["config"].get("workflow_mode") == "relight":
            stage = "wan21_relight" if p["config"].get("relight_engine") == "wan21" else "h3"
        else:
            stage = (p["config"]["engine"] if p["config"]["engine"] in ("h3", "wan", "wan2") else
                 "background" if p["config"]["background"] == "keep" else "restyle")
    if p["config"].get("custom_loras") and (stage in ("draft", "final", "h3_enhance", "wan_speech") or
            stage in ("background", "restyle") and not ltx25_scene_route(p, stage)):
        raise ValueError("Custom LoRAs aren't available on this video graph yet. Remove them before opening this stage.")
    if stage in ("h3", "wan21_relight") and p.get("opening_input") and not h3_viewport_direct(p):
        p["opening_approval"] = p["opening_key"]
    if stage == "wan":
        from .wan_speech import enabled, guide_ready
        if enabled(p) and not guide_ready(p):
            stage = "wan_speech"
    if stage == "wan_speech" and p.get("opening_input"):
        p["opening_approval"] = p["opening_key"]
    if ltx25_scene_route(p, stage):
        run = p.get("ltx25_run")
        if not run or not run.get("namespace"):
            run = p["ltx25_run"] = {"namespace": uuid.uuid4().hex}
        plan = ltx25_native_plan(p)
        if not run or run.get("plan", {}).get("key") != plan["key"]:
            p["ltx25_run"] = {"namespace": run["namespace"], "plan": plan, "receipts": {}, "next_phase": "text"}
        stage = "ltx25_" + (p["ltx25_run"].get("next_phase") or "decode")
    if stage not in ("prepare", "design", "background", "restyle", "h3", "h3_enhance", "wan", "wan2", "wan21_relight", "wan_speech", "draft", "final") and not stage.startswith("ltx25_"):
        raise ValueError("Choose preparation, character preview or animation.")
    # Each native Wan preparation section is a separate queue job. Folding
    # the old full-clip IMAGE branch into subgraphs does not bound memory.
    graph = build_graph(p, stage, use_cache=stage == "wan")
    if stage in ("background", "restyle", "h3"):
        shot = next((k for k, n in graph.items() if n["class_type"] == "GenjLoadReviewedShot"), None)
        if shot is not None:
            for n in graph.values():
                for name, value in list(n["inputs"].items()):
                    if value == [shot, 0]:
                        n["inputs"][name] = ["zura_audio_selection", 0]
                    elif value == [shot, 3]:
                        n["inputs"][name] = ["zura_audio_selection", 1]
            inputs = {"video": [shot, 0], "clip_details": [shot, 3],
                      "audio_start_seconds": p["config"]["audio_start"]}
            if p.get("audio"):
                graph["zura_reference_audio"] = {"class_type": "LoadAudio",
                    "inputs": {"audio": p["audio"]["file"]}, "_meta": {"title": "Reference audio · optional"}}
                inputs["audio"] = ["zura_reference_audio", 0]
            graph["zura_audio_selection"] = {"class_type": "GenjApplyReferenceAudio", "inputs": inputs}
    if stage == "wan":
        classes = {node["class_type"] for node in graph.values()}
        if "ZuraWanSavePreparationPart" in classes:
            stage = "wan_prepare"
        elif "ZuraWanMergePreparation" in classes:
            stage = "wan_merge"
    return graph, stage


def _wan_graph_snapshot(project):
    """Accept the visible look only in a private, editable Graph snapshot."""
    snapshot = copy.deepcopy(project)
    snapshot["config"] = clean_config(snapshot["config"])
    if snapshot["config"]["engine"] != "wan":
        raise ValueError("Choose Wan before opening its motion graph.")
    if not snapshot.get("opening_input") or not snapshot.get("opening_key"):
        raise ValueError("Create the character preview before editing Wan motion.")
    snapshot["opening_approval"] = snapshot["opening_key"]
    return snapshot


def _materialise_wan_graph_plan(snapshot, plan):
    """Attach a strict streamed render only after the metadata planner is ready."""
    if plan["action"] != "render":
        return plan
    from .wan import build_wan_graph, cache_path
    request = plan.get("render_request") or {}
    pins = plan["context"]["project_pins"]
    key = request.get("cache_key_override")
    stamp = request.get("cache_stamp")
    if request.get("require_streamed_sampler") is not True or type(stamp) is not dict:
        raise ValueError("Finish motion preparation before opening its render.")
    path = cache_path(key)
    current = path.stat()
    if (str(path) != stamp.get("path") or current.st_size != stamp.get("size") or
            str(current.st_mtime_ns) != str(stamp.get("mtime_ns"))):
        raise ValueError("The prepared Wan motion changed. Update the section again.")
    graph = build_wan_graph(snapshot, use_cache=True, cache_key_override=key,
        preparation_controls={"resolution": pins["resolution"], "scope": pins["scope"]})
    classes = {node["class_type"] for node in graph.values()}
    if (not {"ZuraWanLoadWindowPreparation", "ZuraWan22StreamedSampler"} <= classes or
            classes & {"ZuraWanReviewedFrames", "ZuraWanPackPreparation", "ZuraWan22LoopedChunksSampler"}):
        raise ValueError("Wan Graph rendering requires completed motion and bounded video output.")
    return {**plan, "graph": graph}


def wan_graph_plan_payload(project, body):
    """Read-only Graph planning; artists still submit every job with Queue."""
    if type(body) is not dict or body.get("action") not in ("next", "finish", "render", "edit_motion"):
        raise ValueError("Choose the next motion section or open its render.")
    from .wan import build_wan_graph, cache_path
    from .wan_graph import plan_wan_graph
    snapshot = _wan_graph_snapshot(project)
    action, context, prompt = body["action"], body.get("context"), body.get("prompt")
    if action == "edit_motion":
        # A cold bounded native template preserves all editable preparation
        # nodes. The planner derives the real recipe key before any job runs.
        key = hashlib.sha256(("editable-wan:" + uuid.uuid4().hex).encode()).hexdigest()
        if cache_path(key).exists():
            raise ValueError("The temporary motion key is occupied. Open Edit motion again.")
        prompt = build_wan_graph(snapshot, use_cache=True, cache_key_override=key)
        context = None
    elif action == "render" and context is None:
        # Automatic Studio preparation can be opened directly at its CPU merge
        # stage. Its render becomes available only after the native merge runs.
        graph = build_wan_graph(snapshot, use_cache=True)
        classes = {node["class_type"] for node in graph.values()}
        if classes == {"ZuraWanMergePreparation"}:
            return {"action": "merge", "graph": graph, "context": None, "progress": None}
        if {"ZuraWanLoadWindowPreparation", "ZuraWan22StreamedSampler"} <= classes:
            return {"action": "render", "graph": graph, "context": None, "progress": None}
        raise ValueError("Use Queue to finish the approved motion preparation first.")
    if type(prompt) is not dict or not prompt:
        raise ValueError("The editable Wan motion graph is missing. Open Edit motion again.")
    return _materialise_wan_graph_plan(snapshot, plan_wan_graph(snapshot, prompt, context))


def graph_export_payload(project, stage="auto"):
    graph, stage = editable_graph(project, stage)
    payload = {"graph": graph, "stage": stage, "project_id": project["id"],
        "name": "Zura Studio · " + stage + " · " + project["id"][:8]}
    if stage == "wan_prepare":
        from .wan_graph import plan_wan_graph
        plan = _materialise_wan_graph_plan(_wan_graph_snapshot(project),
            plan_wan_graph(_wan_graph_snapshot(project), graph))
        stage = {"prepare": "wan_prepare", "merge": "wan_merge", "render": "wan"}[plan["action"]]
        payload.update(plan)
        payload["stage"] = stage
        payload["name"] = "Zura Studio · " + stage + " · " + project["id"][:8]
    return payload


def media_url(asset):
    return "/view?" + urlencode({k: asset[k] for k in ("filename", "subfolder", "type") if k in asset})


def append_result_once(project, item):
    """Append an action result at most once, even after collector retries."""
    action_id = item.get("action_id")
    results = project.setdefault("results", [])
    if action_id and any(existing.get("action_id") == action_id for existing in results):
        return False
    results.append(item)
    return True


def public_project(project):
    p = copy.deepcopy(project)
    from .opening_subject import directed_source_subject
    p["selection_target"] = directed_source_subject(p.get("config", {}))
    if p.get("audio") and "audio_id" not in p.get("config", {}) and p["audio"].get("id"):
        p["config"]["audio_id"] = p["audio"]["id"]
    for key in ("source", "character", "opening_input", "audio", "reference_audio"):
        if p.get(key):
            a = p[key]
            a["url"] = media_url({"filename": Path(a["file"]).name, "subfolder": str(Path(a["file"]).parent).replace("\\", "/"), "type": "input"})
    for a in [*p.get("references", []), *([p["starting_asset"]] if p.get("starting_asset") else [])]:
        a["url"] = media_url({"filename": Path(a["file"]).name,
                              "subfolder": str(Path(a["file"]).parent).replace("\\", "/"), "type": "input"})
    for a in [p, *([p["source"]] if p.get("source") else [])]:
        from .preview_proxy import describe_existing
        describe_existing(a, folder_paths.get_input_directory())
        if a.get("thumbnail_file"):
            a["thumbnail_url"] = media_url({"filename": Path(a["thumbnail_file"]).name,
                "subfolder": str(Path(a["thumbnail_file"]).parent).replace("\\", "/"), "type": "input"})
        if a.get("preview_file"):
            preview = Path(folder_paths.get_input_directory()) / a["preview_file"]
            if preview.is_file():
                a["preview_url"] = media_url({"filename": preview.name,
                    "subfolder": str(Path(a["preview_file"]).parent).replace("\\", "/"), "type": "input"})
                a["preview_status"] = "ready"
            else:
                a["preview_status"] = "preparing"
    for action in p.get("actions", []):
        action.pop("graph", None)
    p.pop("ltx25_run", None)  # Native graphs, histories and cache paths stay private.
    from .enhancement import generation_key
    base = p.get("h3_enhancement_base")
    p["h3_enhancement_ready"] = bool(
        base and p.get("config", {}).get("delivery_mode") == "enhanced1080"
        and base.get("generation_key") == generation_key(p))
    p.pop("h3_enhancement_base", None)
    return p


class Studio:
    def __init__(self, server, store=None):
        self.server = server
        self.store = store or Store()
        self.lock = asyncio.Lock()
        self.watcher = None
        self.resuming = set()
        self.resume_scheduled = set()
        from .progress import NativeProgressAdapter
        self.progress_adapter = NativeProgressAdapter()
        from comfy.cli_args import args
        self.server_address = f"{args.listen}:{args.port}"

    def start_watcher(self):
        if self.watcher is None or self.watcher.done():
            self.watcher = asyncio.create_task(self.watch())

    async def watch(self):
        while True:
            # Short active handoffs; idle projects do not need a fast poll.
            await asyncio.sleep(.5 if getattr(self, "_watch_active", False) else 2)
            active = False
            async with self.lock:
                for p in self.store.list(active_only=True):
                    if p.get("phase") != "working":
                        continue
                    active = True
                    try:
                        self.collect(p)
                    except Exception:
                        logging.exception("Zura Studio: could not collect a project result")
            self._watch_active = active

    def schedule_resume(self, identity, action_id):
        """Schedule a handoff once while repeated collector polls are running."""
        scheduled = getattr(self, "resume_scheduled", None)
        if scheduled is None:
            self.resume_scheduled = scheduled = set()
        if action_id in scheduled:
            return None
        scheduled.add(action_id)
        try:
            task = asyncio.create_task(self.resume_text(identity, action_id))
        except Exception:
            scheduled.discard(action_id)
            raise
        task.add_done_callback(lambda _task: scheduled.discard(action_id))
        return task

    @staticmethod
    def _history_has_action_tag(history, action_id):
        try:
            prompt = history.get("prompt", ())
            extra_data = prompt[3]
            return isinstance(extra_data, dict) and extra_data.get("zura_studio_action") == action_id
        except (IndexError, TypeError, AttributeError):
            return False

    async def resume_text(self, identity, action_id):
        active = getattr(self, "resuming", None)
        if active is None:
            self.resuming = active = set()
        if action_id in active:
            return
        active.add(action_id)
        try:
            async with self.lock:
                p = self.store.load(identity)
                action = p["actions"][-1]
                if (action["id"] != action_id or action["state"] != "complete" or p["phase"] != "working"
                        or action.get("server_address", self.server_address) != self.server_address):
                    return
                try:
                    await self.action(p, action["next_stage"], {"request_key": str(uuid.uuid5(uuid.NAMESPACE_URL, action_id))})
                except Exception as e:
                    p.update(phase="error", error="Could not continue this render: " + str(e)[:1600])
                    self.store.save(p)
        finally:
            active.discard(action_id)

    def advance_wan_cleanup(self, p):
        """Wait for an idle serial worker, then acknowledge model release.

        A /free success only submits flags. The CPU marker executes after the
        worker consumes those flags and completes its normal cleanup, so no
        InfiniteTalk or Animate model loads before the boundary is acknowledged.
        """
        action = p["actions"][-1]
        h3_handoff = action.get("next_stage") == "h3_enhance"
        engine_name = "LTX" if action.get("stage") == "ltx25_cleanup" else "H3 enhancement" if h3_handoff else "Wan"
        queue = self.server.prompt_queue
        with queue.mutex:
            running, pending = queue.get_current_queue_volatile()
            if running or pending:
                return p
            if not action.get("cleanup_requested"):
                from .memory_policy import release_policy
                policy = release_policy(p)
                action["memory_policy"] = policy
                action["cleanup_requested"] = time.time()
                queue.set_flag("unload_models", True)
                if policy["purge_cache"]:
                    queue.set_flag("free_memory", True)
                self.store.save(p)
                return p
            flags = queue.get_flags(reset=False)
            if flags.get("free_memory") or flags.get("unload_models"):
                if time.time() - action["cleanup_requested"] > 120:
                    raise ValueError(f"ComfyUI did not finish releasing models for {engine_name}. Check its queue before trying again.")
                return p
            action["state"] = "submitting"
            self.store.save(p)
            extra = {"client_id": "zura-studio", "create_time": int(time.time() * 1000),
                     "comfy_usage_source": "zura-studio"}
            from .live_preview import preview_method
            extra["preview_method"] = preview_method(p["config"], action["stage"])
            action["preview_method"] = extra["preview_method"]
            number = self.server.number
            self.server.number += 1
            queue.put((number, action["id"], action["graph"], extra, action["output_nodes"], {}))
            action["state"] = "queued"
            self.store.save(p)
        return p

    def _collect_ltx25_phase(self, p, action, history):
        """Freeze native producer receipts and advance without artist IDs."""
        from .ltx25 import PHASES, digest, bind_phase, image_sequence_receipt
        run = p.get("ltx25_run") or {}
        plan = run.get("plan") or {}
        phase = action["stage"].removeprefix("ltx25_")
        prompt = history.get("prompt", [])
        if (action.get("ltx25_plan_key") != plan.get("key") or len(prompt) < 3 or
                prompt[1] != action["id"] or prompt[2] != action.get("graph") or
                history.get("status", {}).get("completed") is not True or
                history.get("status", {}).get("status_str") != "success"):
            raise ValueError("LTX returned a different or incomplete native phase.")
        if ltx25_native_plan(p)["key"] != plan["key"]:
            raise ValueError("The LTX source, audio or model files changed during this phase.")
        submitted = action["graph"]
        frozen = {"prompt": copy.deepcopy(prompt[:3]),
                  "status": {"status_str": "success", "completed": True},
                  "outputs": copy.deepcopy(history.get("outputs", {}))}
        output_root = Path(folder_paths.get_output_directory()).resolve()
        input_root = Path(folder_paths.get_input_directory()).resolve()
        receipts = run.setdefault("receipts", {})
        for name, spec in plan["artifacts"].items():
            if spec["phase"] != phase:
                continue
            receipt = {"plan_key": plan["key"], "scenario": plan["scenario"], "artifact": name,
                "producer_phase": phase, "template_graph_sha256": plan["graph_hashes"][phase],
                "producer_graph_sha256": digest(submitted), "submitted_graph": copy.deepcopy(submitted),
                "prompt_id": action["id"], "history": frozen}
            if spec["kind"] == "images":
                receipt.update(image_sequence_receipt(spec, frozen, output_directory=output_root))
                receipts[name] = receipt
                continue
            if spec["kind"] == "audio":
                assets = frozen["outputs"].get(spec["node"], {}).get("latents", [])
                if len(assets) != 1 or assets[0].get("type") != "output":
                    raise ValueError("LTX returned no unique conditioning-audio latent.")
                asset = assets[0]
                path = (output_root / asset.get("subfolder", "") / asset["filename"]).resolve()
                prefix = Path(submitted[spec["node"]]["inputs"]["filename_prefix"])
                if (not path.is_relative_to(output_root) or not path.is_file() or
                        path.parent != (output_root / prefix.parent).resolve() or
                        not re.fullmatch(re.escape(prefix.name) + r"_\d+_\.latent", path.name)):
                    raise ValueError("LTX returned an audio latent outside its output folder.")
                value = sha(path)
                filename = "zura_ltx25_" + plan["key"][:16] + "_" + value[:16] + ".latent"
                target = input_root / filename
                if target.exists():
                    if target.is_symlink() or sha(target) != value:
                        raise ValueError("The LTX audio input cache is occupied by changed data.")
                else:
                    temporary = input_root / ("." + filename + "." + uuid.uuid4().hex + ".tmp")
                    try:
                        shutil.copyfile(path, temporary)
                        if sha(temporary) != value:
                            raise ValueError("The LTX audio latent changed during copying.")
                        # Exclusive publication cannot overwrite another render's cache.
                        try:
                            import os
                            os.link(temporary, target)
                        except FileExistsError:
                            if sha(target) != value:
                                raise ValueError("The LTX audio input cache changed during copying.")
                    finally:
                        temporary.unlink(missing_ok=True)
                receipt.update(input_filename=filename, input_path=str(target))
            else:
                relative = (Path("genj/text_cache") / (spec["key"] + ".pt") if spec["kind"] == "text" else
                            Path("zura/latent_data") / (spec["key"] + ".safetensors"))
                path = (output_root / relative).resolve()
                if not path.is_relative_to(output_root) or not path.is_file():
                    raise ValueError("The completed LTX phase returned no matching data cache.")
                value = sha(path)
                receipt["cache_key"] = spec["key"]
            receipt.update(path=str(path), sha256=value)
            receipts[name] = receipt
        index = PHASES.index(phase)
        if phase == "decode":
            assets = frozen["outputs"].get("save_video", {}).get("images", [])
            prefix = Path(submitted["save_video"]["inputs"]["filename_prefix"])
            candidates = [asset for asset in assets if asset.get("type") == "output" and
                Path(asset.get("subfolder", "")) == prefix.parent and
                re.fullmatch(re.escape(prefix.name) + r"_\d+_\.mp4", asset.get("filename", ""))]
            if len(candidates) != 1:
                raise ValueError("LTX returned no unique matching final video.")
            asset = candidates[0]
            path = (output_root / asset["subfolder"] / asset["filename"]).resolve()
            if not path.is_relative_to(output_root):
                raise ValueError("LTX returned a video outside its output folder.")
            from .enhancement import inspect_video
            width, height = plan["basis"]["delivery"]
            # The sampler receives an 8k+1 padded guide, while delivery is
            # trimmed back to the exact reviewed source interval.
            expected_frames = plan["basis"].get("source_frames", plan["basis"]["frames"])
            actual = inspect_video(path, expected_frames=expected_frames,
                expected_width=width, expected_height=height, expected_fps=24,
                expected_audio_tracks=0 if plan["scenario"] == "silent" else 1)
            append_result_once(p, {"stage": "restyle", "label": "LTX 2.5", "url": media_url(asset),
                "asset": asset, "created": time.time(), "action_id": action["id"],
                "resolution": action["resolution"], "duration": actual["frames"] / actual["fps"],
                "quality": action["quality"], "audio_mode": plan["scenario"],
                "generation_audio": plan.get("generation_audio"), "delivery_audio": plan.get("delivery_audio"),
                "output_raster": actual, "sha256": sha(path)})
            run["next_phase"] = None
            p["phase"] = "done"
        else:
            run["next_phase"] = PHASES[index + 1]
            # Check the full upstream provenance now, before the cleanup handoff.
            bind_phase(plan, run["next_phase"], receipts,
                       output_directory=output_root, input_directory=input_root)
            p["phase"] = "working"
        action["state"] = "complete"
        p["error"] = None
        self.store.save(p)
        if phase != "decode":
            self.schedule_resume(p["id"], action["id"])
        return p

    def collect(self, p):
        try:
            result = self._collect(p)
        except Exception as e:
            if p.get("actions"):
                p["actions"][-1]["state"] = "failed"
            p["phase"] = "error"
            p["error"] = "Could not read this job's output: " + (str(e) or type(e).__name__)[:1600]
            self.store.save(p)
            result = p
        try:
            self._attach_progress(result)
        except Exception:
            # Optional telemetry must never fail an otherwise valid render.
            logging.getLogger(__name__).debug("Progress snapshot unavailable", exc_info=True)
            result.pop("progress", None)
        return result

    def _attach_progress(self, project):
        """Attach a transient, action-scoped snapshot for the Studio JSON response."""
        if not getattr(self, "progress_adapter", None) or not getattr(self, "server_address", None):
            project.pop("progress", None)
            return
        actions = project.get("actions", [])
        if not actions:
            project.pop("progress", None)
            return
        action = actions[-1]
        if action.get("server_address", self.server_address) != self.server_address:
            project.pop("progress", None)
            return
        queue_position = None
        try:
            _running, pending = self.server.prompt_queue.get_current_queue_volatile()
            for index, item in enumerate(pending, 1):
                if len(item) > 1 and item[1] == action.get("id"):
                    queue_position = index
                    break
        except (AttributeError, TypeError):
            pass
        project["progress"] = self.progress_adapter.project_progress(
            self.server, self.server_address, action, queue_position)
        if isinstance(project["progress"], dict):
            project["progress"].update(action_id=action.get("id"), action_stage=action.get("stage"))

    def _collect_h3_base(self, p, action, history):
        """Keep the 720p H3 file internal and hand it to the enhancer."""
        if action.get("delivery_mode") != "enhanced1080":
            return False
        if (action.get("studio_action_tag") != action.get("id")
                or not self._history_has_action_tag(history, action.get("id"))):
            raise ValueError("The H3 base render did not return its matching Studio action tag.")
        from . import verify_review
        from .enhancement import (audio_mode, checked_output_path, generation_key,
                                  inspect_video)

        node = history.get("outputs", {}).get("h3_export", {})
        assets = [asset for asset in node.get("gifs", [])
                  if asset.get("subfolder") == "genj/studio_intermediate"
                  and asset.get("type") == "output"]
        if len(assets) != 1:
            raise ValueError("The H3 base render did not return one private intermediate file.")
        asset = assets[0]
        path = checked_output_path(asset, expected_subfolder="genj/studio_intermediate")
        manifest = verify_review(p["review"])[1]
        mode = audio_mode(p, manifest["clip"])
        tracks = 0 if mode == "silent" else 1
        raster = action.get("base_output_raster", {})
        actual = inspect_video(path, expected_frames=action.get("expected_frames"),
                               expected_width=raster.get("width"), expected_height=raster.get("height"),
                               expected_fps=24, expected_audio_tracks=tracks)
        if actual["frames"] > 120:
            raise ValueError("The H3 base render is longer than this Studio route supports.")
        delivery_raster = h3_render_rasters(p, 1920, delivery=True)[1]
        p["h3_enhancement_base"] = {
            "asset": copy.deepcopy(asset), "sha256": sha(path),
            "generation_key": generation_key(p), "generation_resolution": action.get("generation_resolution"),
            "generation_raster": copy.deepcopy(action.get("generation_raster")),
            "output_raster": copy.deepcopy(raster), "delivery_raster": delivery_raster,
            "frames": actual["frames"], "fps": actual["fps"], "audio_mode": mode,
            "audio_tracks": actual["audio_tracks"], "created": time.time(),
        }
        action["state"] = "complete"
        p["phase"] = "working"
        p["error"] = None
        self.store.save(p)
        self.schedule_resume(p["id"], action["id"])
        return True

    def _collect_h3_enhancement(self, p, action):
        """Track every VHS continuation carrying this Studio action tag."""
        queue = self.server.prompt_queue
        history = queue.get_history()
        running, pending = queue.get_current_queue_volatile()
        action_id = action["id"]

        def tagged_prompt(item):
            try:
                return item[3].get("zura_studio_action") == action_id
            except (IndexError, AttributeError, TypeError):
                return False

        family = {prompt_id: record for prompt_id, record in history.items()
                  if tagged_prompt(record.get("prompt", ())) }
        active_running = [item for item in running if tagged_prompt(item)]
        active_pending = [item for item in pending if tagged_prompt(item)]
        for record in family.values():
            status = record.get("status") or {}
            if status.get("status_str") != "success":
                action["state"] = "failed"
                p["phase"] = "error"
                p["error"] = "The Enhanced 1080p continuation stopped before finishing. It has not been replayed. Check the Comfy job before trying again."
                self.store.save(p)
                return p

        expected = int(action.get("expected_frames") or 0)
        completed = len(family)
        if completed > expected:
            action["state"] = "failed"
            p["phase"] = "error"
            p["error"] = "The Enhanced 1080p continuation family returned more jobs than expected. No result was recorded."
            self.store.save(p)
            return p
        if active_running or active_pending or completed < expected:
            if active_running:
                action["state"] = "running"
                action.pop("absent_since", None)
            elif active_pending:
                action["state"] = "queued"
                action.pop("absent_since", None)
            elif completed < expected:
                action["state"] = "interrupted"
                action.setdefault("absent_since", time.time())
                if time.time() - action["absent_since"] > 90:
                    action["state"] = "failed"
                    p["phase"] = "error"
                    p["error"] = "The Enhanced 1080p continuation is no longer in ComfyUI's queue. It has not been replayed. Check the Comfy job before trying again."
                    self.store.save(p)
                    return p
            p["phase"] = "working"
            self.store.save(p)
            return p

        final_assets = []
        take_name = action.get("take_name", "")
        for record in family.values():
            outputs = record.get("outputs", {}).get("h3_enhance_export", {})
            for asset in outputs.get("gifs", []):
                if (asset.get("subfolder") == "genj/final" and asset.get("type") == "output"
                        and str(asset.get("filename", "")).startswith(take_name + "_")
                        and str(asset.get("filename", "")).lower().endswith(".mp4")):
                    final_assets.append(asset)
        if len(final_assets) != 1:
            action["state"] = "failed"
            p["phase"] = "error"
            p["error"] = "The Enhanced 1080p continuation completed without one verified final video. No result was recorded."
            self.store.save(p)
            return p

        from .enhancement import checked_output_path, inspect_video
        asset = final_assets[0]
        path = checked_output_path(asset, expected_subfolder="genj/final")
        raster = action.get("output_raster", {})
        base = p.get("h3_enhancement_base", {})
        tracks = 0 if base.get("audio_mode") == "silent" else 1
        actual = inspect_video(path, expected_frames=expected,
                               expected_width=raster.get("width"), expected_height=raster.get("height"),
                               expected_fps=24, expected_audio_tracks=tracks)
        item = {"stage": "h3_enhance", "label": "Enhanced 1080p", "delivery_mode": "enhanced1080",
                "url": media_url(asset), "asset": asset, "created": time.time(), "action_id": action_id,
                "resolution": 1920, "generation_resolution": action.get("generation_resolution"),
                "generation_raster": copy.deepcopy(action.get("generation_raster")),
                "base_output_raster": copy.deepcopy(action.get("base_output_raster")),
                "output_raster": actual, "duration": action.get("duration"), "quality": action.get("quality"),
                "h3_preset": action.get("h3_preset"), "audio_mode": base.get("audio_mode"),
                "audio_tracks": actual["audio_tracks"], "sha256": sha(path)}
        append_result_once(p, item)
        action["state"] = "complete"
        action["output_raster"] = actual
        p["phase"] = "done"
        p["error"] = None
        self.store.save(p)
        return p

    def _collect(self, p):
        actions = p.get("actions", [])
        if actions and actions[-1]["state"] == "complete" and p["phase"] == "working":
            action = actions[-1]
            action_id = action.get("id")
            server_matches = action.get("server_address", self.server_address) == self.server_address
            auto_handoff = (action.get("stage") in ("video_text", "h3_references", "wan_prepare", "wan_speech", "wan_cleanup", "ltx25_cleanup") or
                            str(action.get("stage", "")).startswith("ltx25_") and action.get("stage") != "ltx25_decode")
            auto_handoff = auto_handoff or (action.get("stage") == "prepare" and action.get("next_stage") == "create_look")
            if auto_handoff and server_matches:
                self.schedule_resume(p["id"], action_id)
                return p
            if (action.get("stage") == "h3" and action.get("delivery_mode") == "enhanced1080"
                    and action.get("server_address") == self.server_address):
                from .enhancement import generation_key
                base = p.get("h3_enhancement_base") or {}
                if (action.get("next_stage") != "wan_cleanup"
                        or action.get("studio_action_tag") != action_id
                        or base.get("generation_key") != generation_key(p)):
                    action["state"] = "failed"
                    p["phase"] = "error"
                    p["error"] = "The completed H3 base has no matching Enhanced 1080p hand-off record. It was not resumed."
                    self.store.save(p)
                    return p
                self.schedule_resume(p["id"], action_id)
                return p
        if not actions or actions[-1]["state"] not in ("waiting", "submitting", "queued", "running", "interrupted"):
            return p
        action = actions[-1]
        if action.get("server_address", self.server_address) != self.server_address:
            return p  # Shared output folders can be used by another ComfyUI instance.
        if action["stage"] == "h3_enhance":
            return self._collect_h3_enhancement(p, action)
        if action["stage"] in ("wan_cleanup", "ltx25_cleanup") and action["state"] == "waiting":
            return self.advance_wan_cleanup(p)
        history = self.server.prompt_queue.get_history(action["id"]).get(action["id"])
        if not history:
            before = (action.get("state"), action.get("absent_since"), p.get("phase"), p.get("error"))
            if action["state"] == "interrupted":
                running, pending = self.server.prompt_queue.get_current_queue_volatile()
                if any(item[1] == action["id"] for item in running + pending):
                    action["state"] = "running" if any(item[1] == action["id"] for item in running) else "queued"
                    p.update(phase="working", error=None)
                else:
                    return p  # Reconcile late completion, never resubmit an ambiguous job.
            running, pending = self.server.prompt_queue.get_current_queue_volatile()
            if (any(item[1] == action["id"] for item in running)
                    or getattr(self.server, "last_prompt_id", None) == action["id"]):
                action["state"] = "running"
                action.pop("absent_since", None)
            elif not any(item[1] == action["id"] for item in pending) and time.time() - action["created"] > 20:
                # History and queue are separate snapshots. The worker can finish
                # between them; check again before declaring the job absent.
                if self.server.prompt_queue.get_history(action["id"]).get(action["id"]):
                    return self._collect(p)
                action.setdefault("absent_since", time.time())
                if time.time() - action["absent_since"] > 90:
                    action["state"] = "interrupted"
                    p["phase"] = "error"
                    p["error"] = "ComfyUI restarted or this job is no longer in its queue. It has not been resubmitted. Check the Comfy job before repeating a paid render."
            else:
                action.pop("absent_since", None)
            after = (action.get("state"), action.get("absent_since"), p.get("phase"), p.get("error"))
            if after != before:
                self.store.save(p)
            return p
        status = history["status"]
        if status.get("status_str") != "success":
            action["state"] = "failed"
            p["phase"] = "error"
            errors = [m[1].get("exception_message", "") for m in status.get("messages", []) if m[0] == "execution_error"]
            p["error"] = (errors[-1] if errors else "The job stopped before completing. Check the Comfy job for details.")[:1800]
            self.store.save(p)
            return p
        outputs = history.get("outputs", {})
        stage = action["stage"]
        if stage.startswith("ltx25_") and stage != "ltx25_cleanup":
            return self._collect_ltx25_phase(p, action, history)
        if stage == "wan_speech":
            from .wan_speech import record_guide
            record_guide(p, history)
        if stage in ("video_text", "h3_references", "wan_prepare", "wan_speech", "wan_cleanup", "ltx25_cleanup"):
            if stage in ("wan_cleanup", "ltx25_cleanup"):
                marker = history.get("prompt", [None, None, {}])[2].get("ack", {})
                if marker != action.get("graph", {}).get("ack"):
                    raise ValueError("Wan's memory hand-off returned an unexpected acknowledgement.")
            action["state"] = "complete"
            self.store.save(p)
            self.schedule_resume(p["id"], action["id"])
            return p
        elif stage == "prepare":
            text = "\n".join(s for value in outputs.values() for s in value.get("text", []))
            match = re.search(r"shot_[a-f0-9]{16}", text)
            if not match:
                raise ValueError("Preparation returned no review. Check the Comfy job.")
            p["review"] = match.group()
            p.update(approval=None, opening_input=None, opening_key=None, opening_url=None,
                     opening_approval=None, draft_task=None, accepted_draft=None)
            p["prepared_key"] = prep_key(p)
            p["phase"] = "review"
            folder = "genj/reviews/" + p["review"]
            p["mask_url"] = media_url({"filename": "mask_review.mp4", "subfolder": folder, "type": "output"})
            p["guide_url"] = media_url({"filename": "guide.mp4", "subfolder": folder, "type": "output"})
            p["selected_url"] = media_url({"filename": "source.mp4", "subfolder": folder, "type": "output"})
            from . import verify_review
            _, manifest = verify_review(p["review"])
            p["tracking_coverage"] = manifest["clip"].get("tracking_coverage")
        elif stage == "design":
            image = next(a for value in outputs.values() for a in value.get("images", []) if a.get("type") == "output")
            source = Path(folder_paths.get_output_directory()) / image.get("subfolder", "") / image["filename"]
            if not source.resolve().is_relative_to(Path(folder_paths.get_output_directory()).resolve()):
                raise ValueError("The image output is outside ComfyUI's output folder.")
            relative = "genj_studio/" + p["id"] + "/opening_" + action["id"] + ".png"
            target = Path(folder_paths.get_input_directory()) / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            p["opening_input"] = {"file": relative, "sha": sha(target)}
            p["opening_key"] = p["opening_input"]["sha"]
            p["opening_approval"] = None
            p["opening_url"] = media_url(image)
            p["phase"] = "opening"
        elif stage == "h3" and action.get("delivery_mode") == "enhanced1080":
            self._collect_h3_base(p, action, history)
            return p
        else:
            if action.get("h3_character_method") == "openjutsu":
                video = next(dict(a, subfolder="genj/final", format="video/mp4")
                             for value in outputs.values() for a in value.get("images", [])
                             if a.get("type") == "output" and a.get("subfolder", "").replace("\\", "/") == "genj/final"
                             and a.get("filename", "").startswith("studio_" + p["id"] + "_openjutsu")
                             and a["filename"].endswith(".mp4"))
            else:
                video = next(a for value in outputs.values() for a in value.get("gifs", []) if a.get("subfolder") == "genj/final")
            item = {"stage": stage, "url": media_url(video), "asset": video, "created": time.time(),
                    "action_id": action["id"],
                    "render_size": action.get("render_size", 0), "h3_preset": action.get("h3_preset"),
                    "resolution": action.get("resolution"), "duration": action.get("duration"), "quality": action.get("quality")}
            if stage == "h3":
                from .enhancement import checked_output_path, inspect_video
                path = checked_output_path(video)
                actual = inspect_video(path, expected_frames=action.get("expected_frames"),
                                       expected_width=action.get("base_output_raster", {}).get("width"),
                                       expected_height=action.get("base_output_raster", {}).get("height"),
                                       expected_fps=24)
                item.update(label=("H3 · Camera angle" if action.get("h3_preset") == "camera_ref2va_8step" else "H3 · Head & face" if action.get("h3_preset") == "head_face_8step" else "Native H3 · 1080p" if action.get("resolution") == 1920
                                   else "H3 · 720p"),
                            delivery_mode=action.get("delivery_mode", "native"),
                            generation_resolution=action.get("generation_resolution"),
                            generation_raster=copy.deepcopy(action.get("generation_raster")),
                            output_raster=actual, sha256=sha(path))
            elif stage == "wan21_relight":
                from .enhancement import checked_output_path, inspect_video
                path = checked_output_path(video)
                actual = inspect_video(path, expected_frames=action.get("expected_frames"),
                                       expected_width=action.get("output_raster", {}).get("width"),
                                       expected_height=action.get("output_raster", {}).get("height"),
                                       expected_fps=24)
                item.update(label="Wan 2.1 Relight", delivery_mode="native",
                            generation_resolution=action.get("generation_resolution"),
                            generation_raster=copy.deepcopy(action.get("generation_raster")),
                            output_raster=actual, relight_recipe=action.get("relight_recipe"),
                            sha256=sha(path))
            if action.get("h3_character_method") == "openjutsu":
                item.update(label="OpenJutsu", h3_character_method="openjutsu")
            append_result_once(p, item)
            if stage == "draft":
                text = "\n".join(s for value in outputs.values() for s in value.get("text", []))
                match = re.search(r"Draft task ID: ([^\s]+)", text)
                if not match:
                    raise ValueError("The draft returned no completion ID. Inspect its Comfy job before submitting again.")
                p["draft_task"] = match.group(1)
                p["accepted_draft"] = None
                p["phase"] = "draft"
            else:
                p["phase"] = "done"
        action["state"] = "complete"
        p["error"] = None
        if stage == "prepare" and action.get("next_stage") == "create_look":
            p["phase"] = "working"
            self.store.save(p)
            self.schedule_resume(p["id"], action["id"])
            return p
        self.store.save(p)
        return p

    def configure(self, p, value):
        self.collect(p)
        if p["phase"] == "working":
            raise ValueError("Wait for the current job before changing its settings.")
        prior_value = dict(p["config"])
        if "audio_id" not in prior_value and p.get("audio") and p["audio"].get("id"):
            prior_value["audio_id"] = p["audio"]["id"]
        old_key, prior = prep_key(p), clean_config(prior_value)
        config = clean_config(value)
        audio = self.store.load(config["audio_id"]) if config["audio_id"] else None
        if audio:
            if audio.get("asset_kind") != "audio":
                raise ValueError("Choose an audio file for the reference soundtrack.")
            check_asset(audio)
        # Selecting the original performance must not discard an uploaded or
        # generated track. `audio` remains the active input for every engine;
        # this separate asset only remembers the last reference selection.
        remembered_audio = audio or p.get("reference_audio") or p.get("audio")
        if remembered_audio:
            p["reference_audio"] = copy.deepcopy(remembered_audio)
        p["config"], p["audio"] = config, audio
        stale_text_review = bool(config.get("remove_text") and p.get("review")
                                 and p.get("prepared_key") != prep_key(p))
        if old_key != prep_key(p) or stale_text_review:
            # Earlier text reviews did not save the independent genuine mask
            # needed by the text-repair path. Reprepare them when text removal
            # is active so a legacy review cannot claim the newer capability.
            p.update(phase="new", review=None, approval=None, opening_input=None,
                     opening_key=None, opening_url=None, opening_approval=None,
                     draft_task=None, accepted_draft=None)
        elif prior != p["config"]:
            p.update(draft_task=None, accepted_draft=None)
            if any(prior[key] != config[key] for key in ("finished_frame_position", "finished_frame_number")):
                p["opening_approval"] = None
                p.pop("ltx25_run", None)
            if (any(prior[k] != config[k] for k in ("openjutsu_direct", "openjutsu_background", "h3_character_method")) or prior["opening_model"] != config["opening_model"] or prior["h3_viewport_direct"] != config["h3_viewport_direct"] or prior["workflow_mode"] != config["workflow_mode"] or prior["image_prompt"] != config["image_prompt"] or (prior["prompt"] != config["prompt"] and not config["image_prompt"])
                    or any(prior[k] != config[k] for k in ("camera_preset", "camera_prompt", "camera_width", "camera_height", "opening_width", "opening_height"))):
                p.update(opening_input=None, opening_key=None, opening_url=None, opening_approval=None)
            p["phase"] = ("opening" if p.get("opening_input") and p["config"]["engine"] in ("local", "h3", "wan", "wan2")
                          else "approved" if p.get("approval") else "review" if p.get("review") else "new")
        self.store.save(p)
        return p

    async def action(self, p, stage, body):
        self.collect(p)
        approve_opening = stage == "animate"
        if p.get("actions") and p["actions"][-1]["state"] in ("waiting", "submitting", "queued", "running"):
            return p  # A double-click/reconnect never queues another job.
        create_look = stage == "create_look"
        if create_look:
            require_verified_setup(p["config"], stage)
            request_key = str(body.get("request_key", ""))
            if not re.fullmatch(r"[a-f0-9-]{36}", request_key):
                raise ValueError("Reload Zura Studio before continuing.")
            if any(a.get("request_key") == request_key for a in p.get("actions", [])):
                return p
            if h3_viewport_direct(p):
                raise ValueError("This workflow uses references directly, without a starting frame.")
            if camera_setup(p["config"]):
                stage = "design"
            elif p.get("review") and p.get("prepared_key") == prep_key(p):
                # Preparation is internal to creating the look. The artist
                # reviews both the frame and tracked selection before Animate.
                await self.action(p, "approve", body)
                if p.get("look_mode") == "ready":
                    return p
                stage = "design"
            else:
                stage = "prepare"
        if stage == "approve":
            from . import verify_review
            if p.get("prepared_key") != prep_key(p):
                raise ValueError("The source settings changed. Prepare the updated shot first.")
            check_asset(p["source"])
            verify_review(p["review"])
            p["approval"] = prep_key(p)
            p["phase"] = "approved"
            if p.get("look_mode") == "ready" and p.get("starting_asset"):
                from .opening import bind_uploaded_opening
                bind_uploaded_opening(p, p["starting_asset"], folder_paths.get_input_directory(),
                                      assert_approved=assert_approved, check_asset=check_asset, media_url=media_url)
            self.store.save(p)
            return p
        if stage == "animate":
            from .opening_subject import missing_opening_selection
            if missing_opening_selection(p):
                raise ValueError("The source subject was not selected. In Source, choose Describe area (for example, 'chicken nugget') or click the subject, then create the frame again. An empty person mask cannot guide character replacement.")
            if not p.get("opening_input") and not h3_viewport_direct(p) and not head_swap_setup(p["config"]):
                raise ValueError("Create the character preview first.")
            if p["config"].get("workflow_mode") == "relight":
                stage = "wan21_relight" if p["config"].get("relight_engine") == "wan21" else "h3"
            else:
                stage = (p["config"]["engine"] if p["config"]["engine"] in ("h3", "wan", "wan2")
                         else "background" if p["config"]["background"] == "keep" else "restyle")
        if stage == "final":
            p["accepted_draft"] = p.get("draft_task")
        if (p["config"].get("custom_loras") and
                stage in ("h3", "wan", "wan2", "wan21_relight", "background", "restyle", "draft", "final", "h3_enhance") and
                custom_lora_family(p["config"]) is None):
            raise ValueError("Custom LoRAs are not available on this video route. Remove them or choose H3, Wan 2.2, Wan Animate 2 or Wan 2.1 Relight.")
        if stage not in STAGES:
            raise ValueError("Choose an available action.")
        # Prevent replay of a completed request caused by duplicate network delivery.
        request_key = str(body.get("request_key", ""))
        if not re.fullmatch(r"[a-f0-9-]{36}", request_key):
            raise ValueError("Reload Zura Studio before continuing.")
        if any(a.get("request_key") == request_key for a in p.get("actions", [])):
            return p
        if stage in ("prepare", "design", "h3", "wan", "wan2", "wan21_relight", "wan_speech"):
            validate_selection(p)
        if stage == "h3" and p["config"].get("delivery_mode") == "enhanced1080":
            from .enhancement import readiness as enhancement_readiness, SETUP_COMMAND, UPSCALE_MODEL
            available = enhancement_readiness()
            if not available["ready"]:
                missing = ", ".join(available["missing_nodes"])
                if not available["model_ready"]:
                    missing = (missing + ", " if missing else "") + UPSCALE_MODEL
                message = "H3 Enhanced 1080p is unavailable until these installed components are ready: " + missing + "."
                if not available["model_ready"]:
                    message += " Run " + available.get("setup_command", SETUP_COMMAND) + " and restart ComfyUI."
                raise ValueError(message)
        if approve_opening and not h3_viewport_direct(p) and not head_swap_setup(p["config"]):
            p["opening_approval"] = p["opening_key"]
        auth = {k: body.get(k) for k in ("auth_token_comfy_org", "api_key_comfy_org") if body.get(k)}
        if stage in ("draft", "final") and not auth:
            raise ValueError("Sign in to your Comfy account in ComfyUI before using Seedance. Local generation needs no sign-in.")
        if p.get("audio") and p["config"].get("lip_sync") and stage in ("wan", "h3", "background", "restyle", "draft", "final"):
            from .speech import readiness
            needs_speech_model = stage in ("draft", "final") or p["config"].get("refine_lips")
            if needs_speech_model and not readiness()["ready"]:
                raise ValueError("Install the local speech models with Setup_Speech_Windows.cmd, or untick Create a new facial performance to use this track as a soundtrack.")
        next_stage = "create_look" if create_look and stage == "prepare" else None
        if ltx25_scene_route(p, stage):
            # Request replay was rejected above. A new render owns fresh files;
            # subsequent native phases retain this persisted namespace.
            namespace = uuid.uuid4().hex
            plan = ltx25_native_plan({**p, "ltx25_run": {"namespace": namespace}})
            p["ltx25_run"] = {"namespace": namespace, "plan": plan, "receipts": {}, "next_phase": "text"}
            stage, next_stage = "ltx25_cleanup", "ltx25_text"
        elif stage == "ltx25_cleanup":
            phase = (p.get("ltx25_run") or {}).get("next_phase")
            if not phase:
                raise ValueError("This LTX render has no pending native phase.")
            next_stage = "ltx25_" + phase
        elif stage.startswith("ltx25_") and stage != "ltx25_decode":
            next_stage = "ltx25_cleanup"
        if stage == "wan":
            from .wan_speech import enabled, guide_ready, readiness as wan_speech_readiness
            previous = p.get("actions", [])[-1] if p.get("actions") else {}
            just_cleaned = (previous.get("stage") == "wan_cleanup" and previous.get("state") == "complete"
                            and previous.get("next_stage") == "wan"
                            and request_key == str(uuid.uuid5(uuid.NAMESPACE_URL, previous["id"])))
            if enabled(p) and not just_cleaned:
                has_guide = guide_ready(p)
                if not has_guide and not wan_speech_readiness()["ready"]:
                    raise ValueError("Set up Wan speech with Setup_Wan_Speech_Windows.cmd before creating a new facial performance.")
                # A serial CPU acknowledgement clears previously retained
                # models, including a guide run manually from graph view.
                stage, next_stage = "wan_cleanup", "wan" if has_guide else "wan_speech"
        if stage == "wan21_relight":
            previous = p.get("actions", [])[-1] if p.get("actions") else {}
            just_cleaned = (previous.get("stage") == "wan_cleanup" and previous.get("state") == "complete"
                            and previous.get("next_stage") == "wan21_relight"
                            and request_key == str(uuid.uuid5(uuid.NAMESPACE_URL, previous["id"])))
            if not just_cleaned:
                # Clear the image-generation stack before loading Wan 2.1.
                stage, next_stage = "wan_cleanup", "wan21_relight"
        if stage == "wan_cleanup" and next_stage is None:
            previous = p.get("actions", [])[-1] if p.get("actions") else {}
            next_stage = ("wan21_relight" if previous.get("next_stage") == "wan21_relight" else
                          "h3_enhance" if previous.get("stage") == "h3"
                          and previous.get("delivery_mode") == "enhanced1080" else "wan")
        elif stage == "wan_speech":
            next_stage = "wan_cleanup"
        if stage == "h3" and p["config"].get("delivery_mode") == "enhanced1080":
            next_stage = "wan_cleanup"
        prompt_id = str(uuid.uuid4())
        # File validation and conditioning inspection must not freeze Comfy's
        # websocket, progress or upload endpoints while preparing a prompt.
        graph = (await asyncio.to_thread(build_graph, p, stage, run_id=prompt_id) if stage == "h3_enhance"
                 else await asyncio.to_thread(build_graph, p, stage))
        if stage in ("background", "restyle") and "genj_cached_text" not in graph:
            cache_key, info = text_cache_info(graph, stage)
            next_stage, stage = stage, "video_text"
            graph = text_graph(info, cache_key)
        elif stage == "h3" and not camera_setup(p["config"]) and _needs_h3_reference_stage(p, graph):
            from .h3 import cache_key as h3_cache_key, reference_graph
            next_stage, stage = stage, "h3_references"
            graph = reference_graph(graph, h3_cache_key(p))
        elif stage == "wan" and "wan_save" in graph:
            # The native preprocessing tensors must leave the previous worker
            # graph before loading the file-backed Animate sampling route.
            next_stage, stage = "wan_cleanup", "wan_prepare"
        import execution
        planned_graph = copy.deepcopy(graph) if stage.startswith("ltx25_") else None
        data = self.server.trigger_on_prompt({"prompt": graph, "prompt_id": prompt_id,
                                             "client_id": body.get("client_id", "genj-studio")})
        graph = data["prompt"]
        self.server.node_replace_manager.apply_replacements(graph)
        if planned_graph is not None and graph != planned_graph:
            raise ValueError("An extension changed this LTX native phase. Its data handoff cannot be verified.")
        valid = await execution.validate_prompt(prompt_id, graph, None)
        if not valid[0]:
            details = "; ".join(e.get("message", "") for n in valid[3].values() for e in n.get("errors", []))
            raise ValueError("ComfyUI needs attention before this can run: " + (details or str(valid[1]))[:1800])
        action = {"id": prompt_id, "stage": stage, "state": "submitting", "created": time.time(),
                  "request_key": request_key, "paid": stage in ("draft", "final"),
                  "render_size": p["config"].get("render_size", 0), "server_address": self.server_address,
                  "resolution": 1920 if stage == "final" else p["config"].get("resolution"),
                  "duration": (p["source"].get("duration") if p["config"].get("length_mode") == "original" else p["config"]["duration"]),
                  "quality": p["config"]["quality"]}
        if stage in ("h3", "h3_references"):
            action["render_size"] = 0
            action["h3_preset"] = p["config"]["h3_preset"]
            action["delivery_mode"] = p["config"].get("delivery_mode", "native")
            action["generation_resolution"] = h3_generation_resolution(p["config"])
            if stage == "h3" and p["config"].get("h3_character_method") == "openjutsu":
                from . import verify_review
                action.update(h3_character_method="openjutsu", h3_preset="openjutsu_8step",
                              generation_resolution=int(p["config"]["openjutsu_resolution"]),
                              resolution=int(p["config"]["openjutsu_resolution"]),
                              expected_frames=verify_review(p["review"])[1]["clip"]["frames"], label="OpenJutsu · experimental")
            elif stage == "h3" and camera_setup(p["config"]):
                from .h3_camera import selected_frame_count
                raster = {"width": p["config"]["camera_width"], "height": p["config"]["camera_height"]}
                action.update(resolution=max(raster.values()), generation_resolution=max(raster.values()),
                              h3_preset="camera_ref2va_8step", expected_frames=selected_frame_count(p, check_asset),
                              generation_raster=raster, base_output_raster=raster, label="H3 · Camera angle")
            elif stage == "h3" and head_swap_setup(p["config"]):
                from .h3_head_swap import selected_frame_count
                action.update(resolution=1024, generation_resolution=1024,
                              h3_preset="head_face_8step", expected_frames=selected_frame_count(p, check_asset))
            elif stage == "h3":
                from . import verify_review
                generation_raster, base_output_raster = h3_render_rasters(
                    p, action["generation_resolution"])
                action["generation_raster"] = generation_raster
                action["base_output_raster"] = base_output_raster
                action["expected_frames"] = verify_review(p["review"])[1]["clip"]["frames"]
                if action["delivery_mode"] == "enhanced1080":
                    action["next_stage"] = "wan_cleanup"
                    action["studio_action_tag"] = prompt_id
        elif stage == "wan21_relight":
            from . import verify_review
            _, manifest = verify_review(p["review"])
            size = graph["272:407:89"]["inputs"]
            action.update(label="Wan 2.1 Relight", resolution=max(size["width"], size["height"]),
                          generation_resolution=max(size["width"], size["height"]),
                          generation_raster={"width": size["width"], "height": size["height"]},
                          expected_frames=manifest["clip"]["frames"],
                          relight_recipe="wan21-relight-switchx-v1")
            delivery = graph["wan21_export"]["inputs"]
            if delivery.get("output_width") and delivery.get("output_height"):
                action["output_raster"] = {"width": delivery["output_width"], "height": delivery["output_height"]}
        elif stage == "h3_enhance":
            base = p.get("h3_enhancement_base") or {}
            action["delivery_mode"] = "enhanced1080"
            action["generation_resolution"] = 1280
            action["generation_raster"] = base.get("generation_raster")
            action["base_output_raster"] = base.get("output_raster")
            action["output_raster"] = h3_render_rasters(p, 1920, delivery=True)[1]
            action["expected_frames"] = base.get("frames")
            action["audio_mode"] = base.get("audio_mode")
            action["label"] = "Enhanced 1080p"
            action["filename_prefix"] = f"genj/studio_h3_enhance/{p['id']}/{prompt_id}"
            action["take_name"] = f"studio_{p['id'][:8]}_h3_enhanced_{prompt_id}"
            action["studio_action_tag"] = prompt_id
        if next_stage:
            action["next_stage"] = next_stage
        if stage.startswith("ltx25_"):
            action.update(graph=copy.deepcopy(graph), ltx25_plan_key=p["ltx25_run"]["plan"]["key"])
        if stage in ("wan_cleanup", "ltx25_cleanup"):
            action.update(state="waiting", graph=graph, output_nodes=valid[2])
        p.setdefault("actions", []).append(action)
        p["phase"] = "working"
        p["error"] = None
        self.store.save(p)  # Persist BEFORE queueing; ambiguity is never retried automatically.
        if stage in ("wan_cleanup", "ltx25_cleanup"):
            self.start_watcher()
            return p
        from .live_preview import preview_method
        extra = {"client_id": data.get("client_id", "genj-studio"), "create_time": int(time.time() * 1000),
                 "comfy_usage_source": "zura-studio", "preview_method": preview_method(p["config"], stage)}
        action["preview_method"] = extra["preview_method"]
        if (stage == "h3_enhance"
                or stage == "h3" and p["config"].get("delivery_mode") == "enhanced1080"):
            # VHS copies extra_data unchanged to each freshly numbered continuation.
            extra["zura_studio_action"] = prompt_id
        number = self.server.number
        self.server.number += 1
        self.server.prompt_queue.put((number, prompt_id, graph, extra, valid[2], auth))
        action["state"] = "queued"
        self.store.save(p)
        self.start_watcher()
        return p


def register():
    from server import PromptServer
    if not getattr(PromptServer, "instance", None):
        return
    server = PromptServer.instance
    if getattr(server, "_zura_artist_studio_registered", False):
        return
    server._zura_artist_studio_registered = True
    studio = Studio(server)
    routes = server.routes
    proxy_jobs = {}
    proxy_errors = {}

    def ensure_preview(asset):
        from .preview_proxy import describe_existing
        describe_existing(asset, folder_paths.get_input_directory())
        if not asset.get("preview_file"):
            return
        identity = asset["id"]
        target = Path(folder_paths.get_input_directory()) / asset["preview_file"]
        if target.is_file() or identity in proxy_jobs or identity in proxy_errors:
            return
        async def make_preview():
            try:
                from .preview_proxy import build_proxy
                from . import ffmpeg
                source = await asyncio.to_thread(check_asset, asset)
                await asyncio.to_thread(build_proxy, source, target, ffmpeg)
            except Exception as exc:
                logging.exception("Zura Studio: playback proxy failed")
                proxy_errors[identity] = str(exc)
            finally:
                proxy_jobs.pop(identity, None)
        proxy_jobs[identity] = asyncio.create_task(make_preview())

    def same_origin(request):
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            raise web.HTTPForbidden(text="Open Zura Studio inside this ComfyUI instance.")

    def response(fn):
        async def wrapped(request):
            try:
                same_origin(request)
                studio.start_watcher()
                return await fn(request)
            except (ValueError, KeyError, TypeError, OSError, av.error.FFmpegError) as e:
                return web.json_response({"error": str(e)}, status=400)
        return wrapped

    from .opening import register as register_opening
    register_opening(studio, routes, response)
    from .content import register as register_content
    register_content(studio, routes, response)
    from .model_downloads import register as register_model_downloads
    register_model_downloads(routes, response)
    from .hdr_studio import register as register_hdr_studio
    register_hdr_studio(studio, routes, response, check_asset)
    from .hdr_native_studio import register as register_hdr_native_studio
    register_hdr_native_studio(studio, routes, response, check_asset)
    from .outpaint_jobs import register as register_outpaint_jobs
    register_outpaint_jobs(studio, routes, response)

    @routes.get("/zura/studio/loras")
    @routes.get("/genj/studio/loras")
    @response
    async def list_custom_loras(request):
        from .custom_loras import catalogue
        entries = await asyncio.to_thread(catalogue, folder_paths.get_filename_list("loras"), folder_paths.get_full_path)
        return web.json_response({"loras": entries})

    @routes.post("/zura/studio/image-loras/validate")
    @routes.post("/genj/studio/image-loras/validate")
    @response
    async def validate_image_loras(request):
        from .custom_loras import validate_image_loras as validate
        data = await request.json()
        selections = data.get("loras", [])
        if not isinstance(selections, list):
            raise ValueError("Choose a list of installed LoRAs.")
        result = await asyncio.to_thread(validate, data.get("model"), selections,
            folder_paths.get_filename_list("loras"), folder_paths.get_full_path)
        return web.json_response({"loras": result})

    @routes.get("/zura/studio/status")
    @routes.get("/genj/studio/status")
    @response
    async def status(request):
        from .hardware import snapshot as hardware_snapshot
        required = {
            "inpaint": ("loras", "ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors"),
            "ltx": ("diffusion_models", "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"),
            "klein": ("diffusion_models", "flux-2-klein-9b-fp8.safetensors"),
            "sam": ("checkpoints", "sam3.1_multiplex_fp16.safetensors"),
            "vocals": ("diffusion_models", "MelBandRoformer_fp16.safetensors"),
            "ltx_text": ("text_encoders", "gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors"),
            "ltx_video_vae": ("vae", "ltx-2.5-video-vae-bf16.safetensors"),
            "ltx_scene_video_vae": ("vae", "ltx-2.5-video-vae-conv-bf16.safetensors"),
            "ltx_audio_vae": ("vae", "ltx-2.5-audio-vae-bf16.safetensors"),
            "ltx_upscaler": ("latent_upscale_models", "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"),
            "klein_text": ("text_encoders", "qwen_3_8b_fp8mixed.safetensors"),
            "klein_vae": ("vae", "full_encoder_small_decoder.safetensors"),
            "depth_control": ("loras", "ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors"),
        }
        models = {key: bool(folder_paths.get_full_path(folder, name)) for key, (folder, name) in required.items()}
        from .h3 import (H3_MODELS, H3_NATIVE_NODES, H3_VIEWPORT_MODELS,
                         H3_VIEWPORT_NATIVE_NODES, text_cleanup_readiness)
        import nodes
        h3_models = {key: bool(folder_paths.get_full_path(folder, name)) for key, (folder, name) in H3_MODELS.items()}
        missing_h3_nodes = [name for name in H3_NATIVE_NODES if name not in nodes.NODE_CLASS_MAPPINGS]
        missing_h3_viewport_nodes = [name for name in H3_VIEWPORT_NATIVE_NODES
                                     if name not in nodes.NODE_CLASS_MAPPINGS]
        h3_viewport_ready = (all(h3_models[key] for key in H3_VIEWPORT_MODELS)
                             and not missing_h3_viewport_nodes)
        ltx_viewport = ltx25_viewport_readiness(nodes.NODE_CLASS_MAPPINGS)
        from .wan import WAN_MODELS, WAN_NATIVE_NODES
        missing_ltx_nodes = [name for name in ("LTXVModalityGuidance", "SolidMask", "SetLatentNoiseMask",
                                              "MaskFix+", "ThresholdMask", "ComfyMathExpression")
                             if name not in nodes.NODE_CLASS_MAPPINGS]
        scene_keys = set(required) - {"inpaint", "ltx_video_vae", "vocals"}
        scene_nodes = ("DWPreprocessor", "ResizeImageMaskNode", "VHS_LoadImagesPath",
                       "LTXVConditioning", "LTXVPreprocess", "LTXVImgToVideoInplace", "LTXVAddGuide",
                       "LTXAddVideoICLoRAGuideAdvanced", "LTXICLoRALoaderModelOnly",
                       "LTXVEmptyLatentAudio", "LTXVAudioVAEEncode", "LTXVConcatAVLatent",
                       "LTXVSeparateAVLatent", "LTXVCropGuides", "LTXVLatentUpsampler",
                       "LatentUpscaleModelLoader", "ManualSigmas", "GenjLTXFramePad",
                       "GenjLoadReviewedShot", "GenjApplyReferenceAudio", "GenjSaveTextConditioning",
                       "GenjLoadTextConditioning", "ZuraSaveVideoLatentData", "ZuraLoadVideoLatentData")
        missing_ltx_scene_nodes = [name for name in scene_nodes if name not in nodes.NODE_CLASS_MAPPINGS]
        detectors = ltx25_detector_paths()
        masked_keys = set(required) - {"ltx_scene_video_vae"}
        wan_models = {key: bool(folder_paths.get_full_path(folder, name)) for key, (folder, name) in WAN_MODELS.items()}
        missing_wan_nodes = [name for name in WAN_NATIVE_NODES if name not in nodes.NODE_CLASS_MAPPINGS]
        from .enhancement import readiness as h3_enhancement_readiness
        h3_enhancement = h3_enhancement_readiness()
        from .speech import readiness
        from .wan_speech import readiness as wan_speech_readiness
        from .h3_head_swap import readiness as head_swap_readiness
        head_swap = head_swap_readiness(nodes.NODE_CLASS_MAPPINGS, folder_paths.get_full_path)
        from .wan_animate2 import readiness as wan2_readiness
        wan2 = wan2_readiness(nodes.NODE_CLASS_MAPPINGS, folder_paths.get_full_path)
        from .h3_camera import readiness as camera_readiness
        camera = camera_readiness(nodes.NODE_CLASS_MAPPINGS, folder_paths.get_full_path)
        from .wan21_relight import readiness as wan21_relight_readiness
        wan21_relight = wan21_relight_readiness(nodes.NODE_CLASS_MAPPINGS, folder_paths.get_full_path)
        design = design_readiness(nodes.NODE_CLASS_MAPPINGS, folder_paths.get_full_path)
        from .opening_models import readiness as opening_models_readiness
        opening_models = opening_models_readiness(nodes.NODE_CLASS_MAPPINGS, folder_paths.get_full_path)
        from .openjutsu import installed_readiness
        openjutsu = installed_readiness(nodes.NODE_CLASS_MAPPINGS)
        return web.json_response({**hardware_snapshot(), "models": models, "h3_models": h3_models, "wan_models": wan_models, "speech": readiness(),
            "h3_text_cleanup": text_cleanup_readiness(),
            "h3_head_swap": head_swap, "wan2": wan2, "h3_camera": camera,
            "wan21_relight": wan21_relight,
            "opening_models": opening_models,
            "openjutsu": openjutsu,
            "missing_openjutsu_nodes": openjutsu["missing_nodes"],
            "h3_attention_backends": h3_attention_capabilities(nodes.NODE_CLASS_MAPPINGS),
            "wan_speech": wan_speech_readiness(),
            "engine_ready": {"openjutsu": openjutsu["ready"], "design": design["ready"], "h3_camera": camera["ready"], "wan2": wan2["ready"], "local": all(models[key] for key in masked_keys) and not missing_ltx_nodes,
                             "local_scene": all(models[key] for key in scene_keys) and all(detectors.values()) and not missing_ltx_scene_nodes,
                             "local_viewport": ltx_viewport["ready"],
                             "h3": all(h3_models.values()) and not missing_h3_nodes,
                             "h3_viewport": h3_viewport_ready,
                             "h3_head_swap": head_swap["ready"],
                             "h3_enhanced1080": all(h3_models.values()) and not missing_h3_nodes and h3_enhancement["ready"],
                             "wan21_relight": wan21_relight["ready"],
                             "wan": all(wan_models.values()) and not missing_wan_nodes},
            "engine_quality": {"local": "Reviewed five-second whole-scene examples; masked speech and longer continuation remain experimental",
                               "h3": "Native fixed-audio speech and source-background guidance; review timing and motion",
                               "wan": "Native source performance or an audio-driven face guide; review head turns and speech timing",
                               "wan21_relight": wan21_relight["note"]},
            "missing_ltx_nodes": missing_ltx_nodes,
            "missing_design_nodes": design["missing_nodes"],
            "missing_ltx_scene_nodes": missing_ltx_scene_nodes,
            "missing_ltx_viewport_nodes": ltx_viewport["missing_nodes"],
            "missing_h3_viewport_nodes": missing_h3_viewport_nodes,
            "missing_wan2_nodes": wan2["missing_nodes"],
            "model_files": {"openjutsu": openjutsu["model_files"], "design": design["model_files"], "wan2": wan2["model_files"],
                "wan21_relight": wan21_relight["model_files"],
                "local_viewport": ltx_viewport["model_files"],
                "h3_viewport": [{"folder": folder, "filename": name, "ready": h3_models[key]}
                                for key, (folder, name) in H3_VIEWPORT_MODELS.items()],
                "local_scene": [{"folder": folder, "filename": name, "ready": models[key]}
                                for key, (folder, name) in required.items() if key in scene_keys] +
                               [{"path": "custom_nodes/" + relative.as_posix(), "ready": detectors[key] is not None}
                                for key, relative in LTX25_DETECTORS.items()],
                "local": [{"folder": folder, "filename": name, "ready": models[key]}
                          for key, (folder, name) in required.items() if key in masked_keys],
                "h3": [{"folder": folder, "filename": name, "ready": h3_models[key]}
                       for key, (folder, name) in H3_MODELS.items()],
                "wan": [{"folder": folder, "filename": name, "ready": wan_models[key]}
                        for key, (folder, name) in WAN_MODELS.items()]},
            "missing_wan_nodes": missing_wan_nodes,
            "missing_h3_nodes": missing_h3_nodes, "h3_enhancement": h3_enhancement,
            "ready": all(models[key] for key in masked_keys) and not missing_ltx_nodes, "version": 6, "brand": "Zura Studio", "package": "comfyui-zura-nodes",
            "runtime": {"source": str(HERE), "prompt_id": getattr(server, "last_prompt_id", None),
                        "running": [item[1] for item in server.prompt_queue.get_current_queue_volatile()[0]]}})

    @routes.post("/zura/studio/upload")
    @routes.post("/genj/studio/upload")
    @response
    async def upload(request):
        reader = await request.multipart()
        part = await reader.next()
        if part is None or not part.filename:
            raise ValueError("Choose a video, image or audio file.")
        kind = request.query.get("kind", "")
        suffix = Path(part.filename).suffix.lower()
        supported = {"video": (".mp4", ".mov", ".mkv", ".webm"), "image": (".png", ".jpg", ".jpeg", ".webp"),
                     "audio": (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".aiff", ".mp4", ".mov", ".mkv", ".webm")}
        if kind not in supported or suffix not in supported[kind]:
            raise ValueError("Choose a supported video, image or audio file (WAV, MP3, M4A, FLAC).")
        identity = uuid.uuid4().hex
        relative = "genj_studio/" + identity + "/reference" + suffix
        path = Path(folder_paths.get_input_directory()) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        digest = hashlib.sha256()
        def write_chunk(f, chunk):
            f.write(chunk)
            digest.update(chunk)
        with path.open("wb") as f:
            while chunk := await part.read_chunk(1024 * 1024):
                size += len(chunk)
                if size > 2 * 1024**3:
                    raise ValueError("Use a source video smaller than 2 GB.")
                await asyncio.to_thread(write_chunk, f, chunk)
        def inspect_media():
            details = {}
            if kind == "video":
                with av.open(str(path)) as video:
                    if not video.streams.video:
                        raise ValueError("This file contains no video. Choose a performance clip.")
                    stream = video.streams.video[0]
                    duration = float(stream.duration * stream.time_base) if stream.duration else float((video.duration or 0) / av.time_base)
                    if not math.isfinite(duration) or duration <= 0:
                        raise ValueError("The clip length could not be read. Export an MP4 and upload it again.")
                    details = {"duration": duration, "width": stream.width, "height": stream.height,
                               "has_audio": bool(video.streams.audio), "video_codec": stream.codec_context.name}
                    from .preview_proxy import needs_proxy
                    if needs_proxy(stream.codec_context.name):
                        details["preview_file"] = str(Path(relative).parent / "preview.mp4").replace("\\", "/")
                    frame = next(video.decode(video=0), None)
                    if frame is None:
                        raise ValueError("The video has no readable frames. Export an MP4 and try again.")
                    thumbnail = frame.to_image()
                    thumbnail.thumbnail((480, 480))
                    thumbnail_path = path.parent / "thumbnail.jpg"
                    thumbnail.convert("RGB").save(thumbnail_path, quality=85)
                    details["thumbnail_file"] = thumbnail_path.relative_to(Path(folder_paths.get_input_directory())).as_posix()
            elif kind == "audio":
                with av.open(str(path)) as media:
                    if not media.streams.audio:
                        raise ValueError("This file has no audio track.")
                    stream = media.streams.audio[0]
                    duration = float(stream.duration * stream.time_base) if stream.duration else float((media.duration or 0) / av.time_base)
                    if not math.isfinite(duration) or duration <= 0:
                        raise ValueError("The audio length could not be read. Export a WAV and try again.")
                    details = {"duration": duration}
            else:
                with Image.open(path) as image:
                    image.verify()
            return details

        details = await asyncio.to_thread(inspect_media)
        if kind == "audio" and suffix in supported["video"]:
            from . import ffmpeg
            extracted = path.with_suffix(".wav")
            await asyncio.to_thread(ffmpeg, "-i", path, "-map", "0:a:0", "-vn", "-c:a", "pcm_f32le", extracted)
            path, relative = extracted, str(Path(relative).with_suffix(".wav")).replace("\\", "/")
        asset = {"id": identity, "kind": "asset", "asset_kind": kind, "file": relative,
                 "sha": (await asyncio.to_thread(sha, path)) if kind == "audio" and suffix in supported["video"] else digest.hexdigest(),
                 "name": Path(part.filename).name, **details}
        studio.store.save(asset)
        ensure_preview(asset)
        return web.json_response(public_project(asset))

    @routes.get("/zura/studio/assets/{identity}/preview")
    @routes.get("/genj/studio/assets/{identity}/preview")
    @response
    async def preview_status(request):
        asset = studio.store.load(request.match_info["identity"])
        if asset.get("asset_kind") != "video":
            raise ValueError("Choose an uploaded video.")
        ensure_preview(asset)
        visible = public_project(asset)
        if asset["id"] in proxy_errors:
            visible["preview_status"] = "error"
            visible["preview_error"] = "Could not create a playback preview. The original remains available for generation."
        return web.json_response(visible)

    @routes.post("/zura/studio/voice")
    @routes.post("/genj/studio/voice")
    @response
    async def create_voice_track(request):
        raise ValueError("Voice creation is not available in the verified Studio. Upload an existing audio track instead.")

    @routes.get("/zura/studio/voice/{identity}")
    @routes.get("/genj/studio/voice/{identity}")
    @response
    async def voice_track_status(request):
        from .voice import collect_voice
        async with studio.lock:
            return web.json_response(public_project(collect_voice(studio, request.match_info["identity"])))

    @routes.get("/zura/studio/projects")
    @routes.get("/genj/studio/projects")
    @response
    async def list_projects(request):
        async with studio.lock:
            return web.json_response([public_project(studio.collect(p)) for p in studio.store.list()])

    @routes.post("/zura/studio/projects")
    @routes.post("/genj/studio/projects")
    @response
    async def create_project(request):
        body = await request.json()
        source = studio.store.load(body["source"])
        if source.get("asset_kind") != "video":
            raise ValueError("Choose a source video.")
        from .appearance import resolve_appearance
        config = clean_config(body.get("config", {}))
        require_verified_setup(config)
        require_relight_direction(config, supplied_image=body.get("look_mode") == "ready" and bool(body.get("starting_image")))
        appearance = resolve_appearance({**body, "config": config}, studio.store.load, check_asset)
        p = {"id": uuid.uuid4().hex, "kind": "project", "name": source["name"], "source": source,
             **appearance, "config": config, "phase": "new",
             "actions": [], "results": [], "created": time.time()}
        studio.configure(p, p["config"])
        return web.json_response(public_project(p))

    @routes.get("/zura/studio/projects/{identity}")
    @routes.get("/genj/studio/projects/{identity}")
    @response
    async def get_project(request):
        async with studio.lock:
            return web.json_response(public_project(studio.collect(studio.store.load(request.match_info["identity"]))))

    @routes.get("/zura/studio/projects/{identity}/graph")
    @routes.get("/genj/studio/projects/{identity}/graph")
    @response
    async def export_project_graph(request):
        async with studio.lock:
            p = studio.store.load(request.match_info["identity"])
            require_verified_setup(p["config"], request.query.get("stage", "auto"))
            payload = await asyncio.to_thread(graph_export_payload, p, request.query.get("stage", "auto"))
            return web.json_response(payload)

    @routes.post("/zura/studio/projects/{identity}/wan-graph/plan")
    @routes.post("/genj/studio/projects/{identity}/wan-graph/plan")
    @response
    async def plan_project_wan_graph(request):
        body = await request.json()
        async with studio.lock:
            p = studio.store.load(request.match_info["identity"])
            require_verified_setup(p["config"])
            payload = await asyncio.to_thread(wan_graph_plan_payload, p, body)
            return web.json_response(payload)

    @routes.post("/zura/studio/projects/{identity}/config")
    @routes.post("/genj/studio/projects/{identity}/config")
    @response
    async def configure(request):
        async with studio.lock:
            p = studio.store.load(request.match_info["identity"])
            body = await request.json()
            require_verified_setup(clean_config(body.get("config", {})))
            roles = body.get("reference_roles")
            if roles is not None:
                from .appearance import REFERENCE_ROLES
                if not p.get("references") and roles and p.get("character"):
                    p["references"] = [copy.deepcopy(p["character"])]
                references = p.get("references", [])
                if not isinstance(roles, list) or len(roles) != len(references) or any(role not in REFERENCE_ROLES for role in roles):
                    raise ValueError("Choose a valid role for every reference image.")
                if any(reference.get("role", "auto") != role for reference, role in zip(references, roles)):
                    for reference, role in zip(references, roles):
                        reference["role"] = role
                    p.update(opening_input=None, opening_key=None, opening_url=None, opening_approval=None,
                             draft_task=None, accepted_draft=None)
                    p["phase"] = "approved" if p.get("approval") else "review" if p.get("review") else "new"
            p = studio.configure(p, body.get("config", {}))
            return web.json_response(public_project(p))

    @routes.post("/zura/studio/projects/{identity}/action")
    @routes.post("/genj/studio/projects/{identity}/action")
    @response
    async def action(request):
        async with studio.lock:
            p = studio.store.load(request.match_info["identity"])
            body = await request.json()
            require_verified_setup(p["config"], body.get("action"))
            p = await studio.action(p, body.get("action"), body)
            return web.json_response(public_project(p))

    @routes.post("/zura/studio/projects/{identity}/cancel")
    @routes.post("/genj/studio/projects/{identity}/cancel")
    @response
    async def cancel(request):
        async with studio.lock:
            p = studio.collect(studio.store.load(request.match_info["identity"]))
            if p["phase"] == "working":
                action = p["actions"][-1]
                identity = action["id"]
                queue = server.prompt_queue
                if action["stage"] == "h3_enhance":
                    # VHS gives each continuation a new prompt id but preserves
                    # this action tag. Stop only this family, including children.
                    with queue.mutex:
                        running, pending = queue.get_current_queue_volatile()
                        family = [item for item in running + pending
                                  if len(item) > 3 and isinstance(item[3], dict)
                                  and item[3].get("zura_studio_action") == identity]
                        for item in running:
                            if len(item) > 3 and isinstance(item[3], dict) and item[3].get("zura_studio_action") == identity:
                                queue.interrupt_if_running(item[1])
                        family_ids = {item[1] for item in family}
                        queue.delete_queue_item(lambda item: item[1] in family_ids)
                else:
                    # Atomic and scoped: never interrupt the user's other Comfy jobs.
                    queue.interrupt_if_running(identity)
                    queue.delete_queue_item(lambda item: item[1] == identity)
                action["state"] = "cancelled"
                p["phase"] = "error"
                p["error"] = ("Stopped this job. A provider request that already started may still be billed; it was not resubmitted."
                              if action.get("paid") else "Stopped this local job. The continuation will not be replayed.")
                studio.store.save(p)
            return web.json_response(public_project(p))
