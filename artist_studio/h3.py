"""H3 data padding and orchestration of native reference/inpainting nodes."""
from math import ceil
import math
import hashlib
import json
import pickle
import re
from pathlib import Path
from collections import OrderedDict
import threading

import torch
import torch.nn.functional as F


H3_MODELS = {
    "h3": ("diffusion_models", "minimax_h3_ref2va_pruned_int8_convrot.safetensors"),
    "h3_text": ("text_encoders", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"),
    "h3_video_vae": ("vae", "minimax_h3_video_vae_int8_convrot.safetensors"),
    "h3_audio_vae": ("vae", "minimax_h3_audio_vae_fp32.safetensors"),
    "h3_control": ("model_patches", "minimax_h3_fun_controlnet_union_2.0_pruned_int8_convrot.safetensors"),
    "h3_turbo": ("loras", "minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors"),
}
H3_NATIVE_NODES = ("MiniMaxH3ReferenceToVideo", "MiniMaxH3AddGuide",
                   "MiniMaxH3FunControlNetApply", "MiniMaxH3SigmaShift",
                   "DepthAnythingV2Preprocessor", "GetImageRangeFromBatch")
H3_VIEWPORT_MODELS = {key: value for key, value in H3_MODELS.items() if key != "h3_control"}
H3_VIEWPORT_NATIVE_NODES = ("MiniMaxH3ReferenceToVideo", "MiniMaxH3AddGuide",
                            "MiniMaxH3SigmaShift", "GetImageRangeFromBatch",
                            "LoadVideo", "LoadAudio", "GenjSelectClip", "GenjH3ViewportFrameData",
                            "GetVideoComponents", "LoadImage", "UNETLoader", "LoraLoaderModelOnly",
                            "CLIPLoader", "VAELoader", "ZuraH3LockReferenceAudio", "BasicGuider",
                            "RandomNoise", "BasicScheduler", "KSamplerSelect", "SamplerCustomAdvanced",
                            "VAEDecode", "ImageCrop", "CreateVideo", "GenjRestoreSoundtrack")
H3_TEXT_CLEANUP_NODES = ("LoadLaMaModel", "LaMaInpaint", "LazySwitchKJ")
H3_PRESETS = ("preview_fast", "preview_quality", "take_fast", "take_quality")


def text_cleanup_readiness():
    import nodes
    missing = [name for name in H3_TEXT_CLEANUP_NODES if name not in nodes.NODE_CLASS_MAPPINGS]
    return {"ready": not missing, "missing_nodes": missing}


def sampling_steps(config, fast):
    """Zero preserves legacy preset defaults; explicit counts reach the sampler."""
    raw = config.get("h3_steps", 0)
    if isinstance(raw, bool):
        raise ValueError("Choose an integer H3 step count from 4 to 80.")
    count = int(raw)
    if float(raw) != count or count != 0 and not 4 <= count <= 80:
        raise ValueError("Choose an integer H3 step count from 4 to 80.")
    return count or (8 if fast else 40)



def apply_attention_backend(node, model, config):
    """Opt-in native model patches; the approved default graph stays unchanged.

    Kitchen changes dense attention only. Sage + Sol additionally approximates
    attention inside its selected sampling interval, so it remains a separate
    experimental choice rather than an automatic quality-preserving fallback.
    """
    backend = config.get("h3_attention", "native")
    if backend == "native":
        return model
    if backend == "kitchen":
        return node("h3_attention", "ModelAttentionBackend", model=model,
                    attention="comfy kitchen attention")
    if backend == "sage_sol":
        model = node("h3_sage_attention", "PathchSageAttentionKJ", model=model,
                     sage_attention="auto", allow_compile=False)
        return node("h3_attention", "SolAttnPatch", model=model,
                    tau=1.5, start_percent=0.2, end_percent=0.9,
                    min_tokens=4096, int8_qk=True, sink_conditioning="exact_kv",
                    morton=False, morton_curve="3d", int8_pv=False,
                    verbose=False, use_tma=False, dense_blocks="")
    raise ValueError("Choose Native, Comfy Kitchen or Sage + Sol for H3 attention.")


def cache_path(key):
    from . import root
    if not re.fullmatch(r"[a-f0-9]{64}", key):
        raise ValueError("Invalid H3 reference cache key.")
    directory = root() / "h3_conditioning"
    directory.mkdir(exist_ok=True)
    return directory / (key + ".pt")


def cache_key(project):
    import folder_paths
    stamps = {}
    for key in ("h3_text", "h3_video_vae", "h3_audio_vae"):
        folder, name = H3_MODELS[key]
        filename = folder_paths.get_full_path(folder, name)
        if not filename:
            raise ValueError("An H3 reference encoder is missing: " + name)
        stamp = Path(filename).stat()
        stamps[key] = [name, stamp.st_size, stamp.st_mtime_ns]
    c = project["config"]
    generation_resolution = 1280 if c.get("delivery_mode") == "enhanced1080" else c.get("resolution")
    data = {"version": 6, "motion": "native_depth_control", "review": project["review"], "character": (project.get("character") or {}).get("sha"),
            "opening": project["opening_key"], "settings": {**{k: c.get(k) for k in ("size", "scope", "prompt", "pitch")},
                                                                "resolution": generation_resolution},
            "audio": (project.get("audio") or {}).get("sha"), "audio_start": c.get("audio_start", 0),
            "lip_sync": c.get("lip_sync", False), "preview": False, "encoders": stamps}
    if c.get("workflow_mode") == "relight":
        data["workflow_mode"] = "relight"
        data["relight_conditioning_recipe"] = 2
        if not c.get("remove_text"):
            data["relight_text_protection"] = 2
        if c.get("preserve_identity"):
            data["identity_reference_recipe"] = 1
    if c.get("preserve_people"):
        data["preserve_people"] = True
        data["person_conditioning_recipe"] = 2
    if project.get("look_mode") == "ready" and project.get("starting_asset"):
        position = c.get("finished_frame_position", "first")
        # The first-frame cache already represents the same approved opening.
        # Key other placements separately so a prior conditioning cache cannot
        # silently put the finished frame back at frame zero.
        if position != "first":
            data["finished_frame"] = {
                "position": position,
                "number": c.get("finished_frame_number", 1) if position == "frame" else None,
            }
    if c.get("edit_area", "mask") == "scene":
        data["selection"] = {"edit_area": "scene"}
    elif c.get("mask_method", "auto") != "auto":
        data["selection"] = {"mask_method": c["mask_method"],
                             "mask_prompt": c.get("mask_prompt", "") if c["mask_method"] == "text" else ""}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _finished_frame_index(project, delivered_frame_count):
    """Return the selected finished-frame index within the delivered H3 clip.

    H3 pads short takes to its 17k+5 latent grid. Artists select a frame in the
    delivered 24 fps clip, so Last must resolve to the final real frame rather
    than the last padded latent frame.
    """
    if project.get("look_mode") != "ready" or not project.get("starting_asset"):
        return None
    if isinstance(delivered_frame_count, bool):
        raise ValueError("The selected H3 clip has no valid delivered frame count.")
    try:
        count = int(delivered_frame_count)
        exact_count = float(delivered_frame_count) == count
    except (TypeError, ValueError, OverflowError):
        exact_count = False
        count = 0
    if not exact_count or count < 1:
        raise ValueError("The selected H3 clip has no valid delivered frame count.")

    config = project.get("config") or {}
    position = config.get("finished_frame_position", "first")
    if position == "first":
        return 0
    if position == "last":
        return count - 1
    if position != "frame":
        raise ValueError("Choose First frame, Last frame or a specific finished frame.")
    raw_number = config.get("finished_frame_number", 1)
    if isinstance(raw_number, bool):
        raise ValueError(f"Choose a finished frame from 1 to {count} for this clip.")
    try:
        number = int(raw_number)
        valid_number = math.isfinite(float(raw_number)) and float(raw_number) == number
    except (TypeError, ValueError, OverflowError):
        valid_number = False
        number = 0
    if not valid_number or not 1 <= number <= count:
        raise ValueError(f"Choose a finished frame from 1 to {count} for this clip.")
    return number - 1


def cpu_values(value):
    from comfy.nested_tensor import NestedTensor
    if isinstance(value, NestedTensor):
        return {"genj_h3_nested_tensors": [cpu_values(t) for t in value.tensors]}
    if isinstance(value, torch.Tensor):
        return value.detach().cpu()
    if isinstance(value, dict):
        return {k: cpu_values(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [cpu_values(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("The H3 encoder returned an unsupported cache value.")


def native_values(value):
    from comfy.nested_tensor import NestedTensor
    if isinstance(value, dict):
        if set(value) == {"genj_h3_nested_tensors"}:
            return NestedTensor([native_values(t) for t in value["genj_h3_nested_tensors"]])
        return {k: native_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [native_values(v) for v in value]
    return value


def _cache_file_digest(stream):
    stream.seek(0)
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
        digest.update(block)
    stream.seek(0)
    return digest.hexdigest()


def _cache_tensor(value, shape, *, floating=True):
    if (not isinstance(value, torch.Tensor) or value.device.type != "cpu"
            or value.layout != torch.strided or value.ndim != len(shape)
            or any(size <= 0 or (expected is not None and size != expected)
                   for size, expected in zip(value.shape, shape))
            or (floating and not value.is_floating_point())
            or not bool(torch.isfinite(value).all())):
        raise ValueError("Invalid H3 conditioning tensor.")


def _validate_cache_values(value):
    if isinstance(value, torch.Tensor):
        if value.device.type != "cpu" or value.layout != torch.strided or not bool(torch.isfinite(value).all()):
            raise ValueError("Invalid H3 conditioning metadata tensor.")
    elif isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("Invalid H3 conditioning metadata keys.")
        for child in value.values():
            _validate_cache_values(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _validate_cache_values(child)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Invalid H3 conditioning metadata number.")
    elif value is not None and not isinstance(value, (str, int, bool)):
        raise ValueError("Unsupported H3 conditioning metadata.")


def _validate_conditioning_cache(data):
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("Unsupported H3 conditioning cache version.")
    positive = data.get("positive")
    if not isinstance(positive, (list, tuple)) or not positive:
        raise ValueError("Missing H3 positive conditioning.")
    for entry in positive:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2 or not isinstance(entry[1], dict):
            raise ValueError("Invalid H3 positive conditioning.")
        _cache_tensor(entry[0], (1, None, 5120))
        _validate_cache_values(entry[1])
        for name in ("minimax_refs", "minimax_keyframes"):
            blocks = entry[1].get(name, [])
            if not isinstance(blocks, (list, tuple)):
                raise ValueError("Invalid H3 reference conditioning.")
            for block in blocks:
                if not isinstance(block, dict):
                    raise ValueError("Invalid H3 reference block.")
                if name == "minimax_refs":
                    kind = block.get("kind")
                    if kind not in ("image", "video", "audio", "video_audio"):
                        raise ValueError("Invalid H3 reference kind.")
                    if kind != "audio":
                        _cache_tensor(block.get("latent"), (1, 24, None, None, None))
                    if kind in ("audio", "video_audio"):
                        _cache_tensor(block.get("audio_latent"), (1, 32, 2, None))
                else:
                    frame = block.get("resolved_frame_index")
                    if type(frame) is not int or frame < 0 or not any(k in block for k in ("latent", "audio_latent")):
                        raise ValueError("Invalid H3 timeline guide.")
                    if "latent" in block:
                        _cache_tensor(block["latent"], (1, 24, None, None, None))
                    if "audio_latent" in block:
                        _cache_tensor(block["audio_latent"], (1, 32, 2, None))
    latent = data.get("latent")
    packed = latent.get("samples") if isinstance(latent, dict) else None
    if not isinstance(packed, dict) or set(packed) != {"genj_h3_nested_tensors"}:
        raise ValueError("Missing H3 paired video/audio latent.")
    streams = packed["genj_h3_nested_tensors"]
    if not isinstance(streams, (list, tuple)) or len(streams) != 2:
        raise ValueError("Invalid H3 paired video/audio latent.")
    video, audio = streams
    _cache_tensor(video, (1, 24, None, None, None))
    _cache_tensor(audio, (1, 32, 2, None))
    if video.shape[-1] % 2 or video.shape[-2] % 2:
        raise ValueError("Invalid H3 video canvas.")
    if video.shape[2] < 2 or (video.shape[2] - 2) % 5:
        raise ValueError("Invalid H3 video timeline.")
    frames = 5 + 17 * ((video.shape[2] - 2) // 5)
    if audio.shape[-1] != round(frames / 24 * 40):
        raise ValueError("H3 video and audio timelines do not match.")
    _validate_cache_values(latent)


def _read_conditioning_cache(key, expected_digest=""):
    with cache_path(key).open("rb") as stream:
        digest = _cache_file_digest(stream)
        if expected_digest and digest != expected_digest:
            raise ValueError("H3 character references changed after this take was prepared.")
        data = torch.load(stream, map_location="cpu", weights_only=True)
        _validate_conditioning_cache(data)
        if _cache_file_digest(stream) != digest:
            raise ValueError("H3 character references changed while being read.")
    return data


_CACHE_READ_ERRORS = (OSError, EOFError, pickle.UnpicklingError, ValueError, TypeError, RuntimeError, KeyError, IndexError)
_CACHE_REBUILD_MESSAGE = (
    "H3's saved character references are damaged, incompatible or changed. "
    "Generate this take again in Zura Studio to rebuild them. Your approved shot and character look are kept."
)

# Only planning reuses a successful integrity/shape check. The execution node
# still opens and strictly validates the actual tensor payload on every load.
_VALIDATED_CACHE_FILES = OrderedDict()
_VALIDATED_CACHE_LOCK = threading.RLock()
_VALIDATED_CACHE_LIMIT = 64


def cache_valid(key, expected_frames=None):
    """Read only CPU tensor data; invalid caches use Studio's native rebuild stage."""
    from .file_cache import file_identity
    try:
        identity = file_identity(cache_path(key))
        with _VALIDATED_CACHE_LOCK:
            frames = _VALIDATED_CACHE_FILES.get(identity)
            if frames is not None:
                if file_identity(cache_path(key)) != identity:
                    return False
                _VALIDATED_CACHE_FILES.move_to_end(identity)
                return expected_frames is None or frames == expected_frames
        data = _read_conditioning_cache(key)
        video = data["latent"]["samples"]["genj_h3_nested_tensors"][0]
        frames = 5 + 17 * ((video.shape[2] - 2) // 5)
        if file_identity(cache_path(key)) != identity:
            return False
        with _VALIDATED_CACHE_LOCK:
            _VALIDATED_CACHE_FILES[identity] = frames
            _VALIDATED_CACHE_FILES.move_to_end(identity)
            while len(_VALIDATED_CACHE_FILES) > _VALIDATED_CACHE_LIMIT:
                _VALIDATED_CACHE_FILES.popitem(last=False)
        if expected_frames is not None and frames != expected_frames:
            return False
    except _CACHE_READ_ERRORS:
        return False
    return True


class GenjSaveH3Conditioning:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"positive": ("CONDITIONING",), "latent": ("LATENT",),
                             "cache_key": ("STRING", {"default": ""})}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "save"
    CATEGORY = "Zura/Artist Studio"
    OUTPUT_NODE = True

    def save(self, positive, latent, cache_key):
        path = cache_path(cache_key)
        temporary = path.with_suffix(".tmp")
        torch.save({"version": 1, "positive": cpu_values(positive), "latent": cpu_values(latent)}, temporary)
        temporary.replace(path)
        return {"ui": {"text": ["H3 character and performance references ready."]}, "result": (cache_key,)}


class GenjLoadH3Conditioning:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cache_key": ("STRING", {"default": ""})},
                "optional": {"cache_digest": ("STRING", {"default": ""})}}
    RETURN_TYPES = ("CONDITIONING", "LATENT")
    FUNCTION = "load"
    CATEGORY = "Zura/Artist Studio"

    @classmethod
    def IS_CHANGED(cls, cache_key, cache_digest=""):
        from . import digest_file
        try:
            return digest_file(cache_path(cache_key))
        except OSError:
            return float("nan")  # Let load() report the actionable recovery message.

    def load(self, cache_key, cache_digest=""):
        try:
            data = _read_conditioning_cache(cache_key, cache_digest)
        except _CACHE_READ_ERRORS as error:
            raise ValueError(_CACHE_REBUILD_MESSAGE) from error
        return native_values(data["positive"]), native_values(data["latent"])


def reachable_graph(graph, outputs):
    visited = set()

    def visit(identity):
        if identity in visited:
            return
        visited.add(identity)
        for value in graph[identity]["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] in graph:
                visit(value[0])

    for identity in outputs:
        visit(identity)
    return {key: value for key, value in graph.items() if key in visited}


def reference_graph(graph, key):
    graph = dict(graph)
    graph["h3_save_references"] = {"class_type": "GenjSaveH3Conditioning", "inputs": {
        "positive": ["h3_speech", 0], "latent": ["h3_references", 1], "cache_key": key}}
    return reachable_graph(graph, ["h3_save_references"])


def valid_length(count):
    return 5 + 17 * max(0, ceil((count - 5) / 17))


class GenjH3ViewportFrameData:
    """Validate a prepared viewport clip and size the local H3 target latent."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"video": ("VIDEO",)}}

    RETURN_TYPES = ("IMAGE", "INT", "INT", "INT", "INT", "INT", "INT", "INT", "INT")
    RETURN_NAMES = ("reference_frames", "width", "height", "padded_frames", "real_frames",
                    "crop_x", "crop_y", "crop_width", "crop_height")
    FUNCTION = "prepare"
    CATEGORY = "Zura/Artist Studio"

    def prepare(self, video):
        components = video.get_components()
        images = components.images
        if images.ndim != 4 or not torch.isfinite(images).all():
            raise ValueError("Connect a valid viewport video with decoded frames.")
        count, height, width = images.shape[:3]
        if abs(float(components.frame_rate) - 24) > 0.001:
            raise ValueError("Prepare the viewport clip at 24 fps before using H3.")
        if not 5 <= count <= 120:
            raise ValueError("Local H3 viewport renders currently support 0.21–5 seconds per take. Choose a section up to five seconds long.")
        # Preserve the full camera frame with a tiny replicated border rather
        # than cropping or stretching common 16:9 sizes such as 1280x720.
        target_width, target_height = ceil(width / 32) * 32, ceil(height / 32) * 32
        left, top = (target_width - width) // 2, (target_height - height) // 2
        padded = F.pad(images.permute(0, 3, 1, 2),
                       (left, target_width - width - left, top, target_height - height - top),
                       mode="replicate").permute(0, 2, 3, 1)
        reference_count = valid_length(count)
        if reference_count > count:
            padded = torch.cat((padded, padded[-1:].expand(reference_count - count, -1, -1, -1)))
        return (padded, target_width, target_height, reference_count, count,
                left, top, width, height)


H3_VIEWPORT_ROLES = {
    "auto": "a visual appearance reference for the scene",
    "environment": "the environment and scene design",
    "character": "the character appearance and identity",
    "object": "the object or product design",
    "detail": "a close-up detail to reproduce accurately",
    "style": "the visual style and material treatment",
}


def build_h3_viewport_graph(project):
    """Build a local reference-to-video graph for a complete viewport scene."""
    from .studio import assert_approved, check_asset, h3_generation_resolution

    if not project.get("viewport_render"):
        raise ValueError("Choose Viewport render mode before starting this H3 route.")
    assert_approved(project)
    c = project["config"]
    if c["engine"] != "h3":
        raise ValueError("Choose MiniMax H3 before starting a viewport render.")
    if c.get("refine_lips"):
        raise ValueError("Optional lip refinement is not available for viewport renders. Use H3's native audio guidance instead.")
    source = project.get("source")
    if not source:
        raise ValueError("Upload the viewport blockout video first.")
    source_path = check_asset(source)
    import av
    with av.open(str(source_path)) as container:
        stream = container.streams.video[0]
        available = (float(stream.duration * stream.time_base) if stream.duration
                     else float(container.duration / av.time_base))
    original_length = c.get("length_mode") == "original"
    start = 0.0 if original_length else c["start"]
    if start >= available:
        raise ValueError("The selected start time is beyond the end of this viewport video.")
    selected_seconds = available if original_length else min(c["duration"], available - start)
    selected_frames = max(1, int(selected_seconds * 24 + 1e-6))
    if not 5 <= selected_frames <= 120:
        raise ValueError("Local H3 viewport renders currently support 0.21–5 seconds per take. Choose a section up to five seconds long.")
    references = list(project.get("viewport_references") or [])
    finished_frame_index = _finished_frame_index(project, selected_frames)
    finished_reference_index = None
    if finished_frame_index is not None:
        starting_asset = project["starting_asset"]
        for index, reference in enumerate(references):
            same_asset = (reference.get("sha") == starting_asset.get("sha")
                          if reference.get("sha") and starting_asset.get("sha")
                          else reference.get("file") == starting_asset.get("file"))
            if same_asset:
                finished_reference_index = index
                references[index] = {**reference, "role": "environment",
                                      "viewport_role": "starting_frame"}
                break
        if finished_reference_index is None:
            if len(references) >= 9:
                raise ValueError("H3 can use a finished scene image plus up to eight extra look references.")
            references.insert(0, {**starting_asset, "role": "environment",
                                  "viewport_role": "starting_frame"})
            finished_reference_index = 0
    if not 1 <= len(references) <= 9:
        raise ValueError("Add between one and nine appearance references for the H3 viewport render.")
    for reference in references:
        check_asset(reference)

    # H3 Max's TrainScene prompt treats the viewport as a camera/layout guide
    # and assigns a separate job to each still. Keep those roles explicit in
    # the local route instead of trying to collapse the references into one
    # opening frame or one collage.
    role_lines = []
    for index, reference in enumerate(references):
        if reference.get("viewport_role") == "starting_frame":
            role_lines.append(
                f"<Picture {index + 1}> is the finished scene image supplied by the artist. Use it for the scene's "
                "materials, lighting and overall visual treatment; the viewport video remains authoritative for "
                "camera, framing, layout and motion.")
        else:
            role = H3_VIEWPORT_ROLES.get(reference.get("role", "auto"), H3_VIEWPORT_ROLES["auto"])
            role_lines.append(f"<Picture {index + 1}> is {role}. Use it only for the depicted design details.")
    prompt = (
        "<Video 1> is the grey 3D viewport/blockout for the shot. Use it as the guide for the exact camera path, "
        "perspective, framing, timing, object placement, scale, scene layout and motion. Recreate the whole frame "
        "as a finished scene; do not preserve the grey viewport shading, untextured materials, or blockout appearance. "
        + " ".join(role_lines) + " "
        "Build one coherent final scene from the references. Keep distinct character designs distinct, place each "
        "reference on its corresponding subject, and do not turn the reference images into a collage or add duplicate people. "
        "Retain the source camera movement, parallax, subject and object motion, geometry and timing throughout the shot. "
        "Preserve the visible design details and marks supplied by the references without inventing extra details. "
        + str(c.get("prompt", "")).strip()
    ).strip()
    if finished_frame_index is not None:
        prompt += (f" <Picture {finished_reference_index + 1}> is also the artist's finished frame for output "
                   f"frame {finished_frame_index + 1} of {selected_frames}. Match it at that exact point in time; "
                   "use the viewport video to guide motion and camera movement between frames.")
    if c.get("remove_text"):
        prompt += " Remove all on-screen text, subtitles, labels and interface overlays. Rebuild their former areas as part of the finished scene."
    if project.get("audio"):
        prompt += (" <Audio 1> is the selected replacement speech. Synchronize visible speaking characters' mouth movements and facial performance to its words and timing."
                   if c.get("lip_sync") else
                   " <Audio 1> is the selected music or sound-design track. Keep the source visual performance and do not invent dialogue or talking mouth movements.")

    graph = {}

    def node(identity, typ, **inputs):
        graph[identity] = {"class_type": typ, "inputs": inputs}
        return [identity, 0]

    source_video = node("h3_viewport_source", "LoadVideo", file=source["file"])
    audio_inputs = {}
    if project.get("audio"):
        check_asset(project["audio"])
        audio_inputs = {"audio": node("h3_viewport_audio", "LoadAudio", audio=project["audio"]["file"]),
                        "audio_start_seconds": c.get("audio_start", 0.0)}
    selected = node("h3_viewport_clip", "GenjSelectClip", video=source_video,
                    start_seconds=c["start"], duration_seconds=c["duration"],
                    long_edge=h3_generation_resolution(c),
                    use_original_length=original_length, **audio_inputs)
    node("h3_viewport_data", "GenjH3ViewportFrameData", video=selected)
    selected_audio = None
    if audio_inputs:
        node("h3_viewport_components", "GetVideoComponents", video=selected)
        selected_audio = ["h3_viewport_components", 1]
    image_refs = {}
    for index, reference in enumerate(references):
        image_refs[f"ref_images.ref_image_{index}"] = node(
            f"h3_viewport_image_{index + 1}", "LoadImage", image=reference["file"])

    model = node("h3_model", "UNETLoader", unet_name=H3_MODELS["h3"][1], weight_dtype="default")
    fast = c.get("h3_preset", "take_quality").endswith("_fast")
    if fast:
        model = node("h3_turbo", "LoraLoaderModelOnly", model=model,
                     lora_name=H3_MODELS["h3_turbo"][1], strength_model=1.0)
    model = node("h3_shift", "MiniMaxH3SigmaShift", model=model, shift_video=12.0, shift_audio=3.0)
    model = apply_attention_backend(node, model, c)
    clip = node("h3_clip", "CLIPLoader", clip_name=H3_MODELS["h3_text"][1], type="minimax", device="default")
    vae = node("h3_vae", "VAELoader", vae_name=H3_MODELS["h3_video_vae"][1])
    audio_vae = node("h3_audio_vae", "VAELoader", vae_name=H3_MODELS["h3_audio_vae"][1])
    width = ["h3_viewport_data", 1]
    height = ["h3_viewport_data", 2]
    length = ["h3_viewport_data", 3]
    positive = node("h3_references", "MiniMaxH3ReferenceToVideo", clip=clip, vae=vae,
                    audio_vae=audio_vae, prompt=prompt, width=width, height=height,
                    length=length, ref_image_size="match", **image_refs,
                    **({"ref_audios.ref_audio_0": selected_audio} if selected_audio else {}),
                    **{"ref_videos.ref_video_0": ["h3_viewport_data", 0]})
    latent = ["h3_references", 1]
    if finished_frame_index is not None:
        positive = node("h3_finished_frame", "MiniMaxH3AddGuide", positive=positive, latent=latent,
                        vae=vae, image=[f"h3_viewport_image_{finished_reference_index + 1}", 0],
                        frame_idx=finished_frame_index)
    if selected_audio:
        positive = node("h3_viewport_speech", "MiniMaxH3AddGuide", positive=positive, latent=latent,
                        audio_vae=audio_vae, audio=selected_audio, frame_idx=0)
        latent = node("h3_locked_audio", "ZuraH3LockReferenceAudio", latent=latent,
                      audio_vae=audio_vae, audio=selected_audio)
    guider = node("h3_guider", "BasicGuider", model=model, conditioning=positive)
    noise = node("h3_noise", "RandomNoise", noise_seed=c["seed"])
    sigmas = node("h3_schedule", "BasicScheduler", model=model, scheduler="simple",
                  steps=sampling_steps(c, fast), denoise=1.0)
    sampler = node("h3_sampler", "KSamplerSelect", sampler_name="res_multistep" if fast else "euler")
    sampled = node("h3_sample", "SamplerCustomAdvanced", noise=noise, guider=guider,
                   sampler=sampler, sigmas=sigmas, latent_image=latent)
    decoded = node("h3_decode", "VAEDecode", samples=sampled, vae=vae)
    trimmed = node("h3_trim", "GetImageRangeFromBatch", images=decoded,
                    start_index=0, num_frames=["h3_viewport_data", 4])
    cropped = node("h3_crop", "ImageCrop", image=trimmed,
                   width=["h3_viewport_data", 7], height=["h3_viewport_data", 8],
                   x=["h3_viewport_data", 5], y=["h3_viewport_data", 6])
    video = node("h3_video", "CreateVideo", images=cropped, fps=24.0,
                 **({"audio": selected_audio} if selected_audio else {}))
    enhanced_delivery = c.get("delivery_mode") == "enhanced1080"
    node("h3_export", "GenjRestoreSoundtrack", video=video,
         clip_details=["h3_viewport_clip", 1],
         take_name="studio_" + project["id"][:8] + ("_h3_base" if enhanced_delivery else "_h3_viewport"),
         **({"output_subfolder": "studio_intermediate"} if enhanced_delivery else {}))
    return graph


class GenjH3FramePad:
    """Pad source and approved mask together; never perform model inference."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source": ("VIDEO",), "mask_video": ("VIDEO",)},
                "optional": {"guidance_audio": ("AUDIO",)}}

    RETURN_TYPES = ("IMAGE", "MASK", "AUDIO", "INT", "INT", "INT", "INT")
    RETURN_NAMES = ("source_frames", "performer_mask", "speech", "width", "height",
                    "padded_frames", "real_frames")
    FUNCTION = "pad"
    CATEGORY = "Zura/Artist Studio"

    def pad(self, source, mask_video, guidance_audio=None):
        components = source.get_components()
        images = components.images
        mask_components = mask_video.get_components()
        mask_images = mask_components.images
        count, height, width = images.shape[:3]
        if abs(float(components.frame_rate) - 24) > 0.001 or abs(float(mask_components.frame_rate) - 24) > 0.001:
            raise ValueError("Prepare this shot at 24 fps before using H3.")
        if not 5 <= count <= 124:
            raise ValueError("H3 currently supports one continuous shot between 0.21 and 5 seconds. Choose a shorter clip or the two-second H3 preview.")
        if width % 32 or height % 32:
            raise ValueError("H3 source dimensions must be multiples of 32.")
        if len(mask_images) != count:
            raise ValueError("The approved mask and source have different frame counts. Prepare the shot again.")
        mask = mask_images[..., 0]
        mask = F.interpolate(mask[:, None].float(), size=(height, width), mode="nearest")[:, 0]
        mask = (mask >= 0.5).to(images.dtype)
        if not bool(mask.any()):
            raise ValueError("The replacement mask is empty. Check the selection before rendering.")
        # The native H3 examples use at least 124 frames (~5 seconds). Keep a
        # full temporal context for short previews, then trim the decoded take.
        length = max(124, valid_length(count))
        extra = length - count
        if extra:
            images = torch.cat((images, images[-1:].expand(extra, -1, -1, -1)))
            mask = torch.cat((mask, mask[-1:].expand(extra, -1, -1)))
        audio = guidance_audio if guidance_audio is not None else components.audio
        if audio is None:
            audio = {"sample_rate": 24000, "waveform": torch.zeros(1, 2, count * 1000)}
        samples = round(count / 24 * audio["sample_rate"])
        waveform = audio["waveform"]
        audio = {"sample_rate": audio["sample_rate"],
                 "waveform": F.pad(waveform, (0, max(0, samples - waveform.shape[-1])))[..., :samples]}
        return (images, mask, audio, width, height, length, count)


class ZuraH3LockReferenceAudio:
    """Fit and encode the selected track into H3's preserved audio stream.

    Uses ComfyUI's native nested latent/noise-mask contract. The distinction
    between an audio reference and a fixed sampling stream is demonstrated by
    Pixaroma's H3 Audio Sync workflow; no inference or model patch is hidden here.
    """

    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "lock"
    RETURN_TYPES = ("LATENT",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"latent": ("LATENT",), "audio_vae": ("VAE",), "audio": ("AUDIO",)}}

    def lock(self, latent, audio_vae, audio):
        from comfy.nested_tensor import NestedTensor
        import comfy.audio

        samples = latent.get("samples")
        if not isinstance(samples, NestedTensor) or len(samples.tensors) != 2:
            raise ValueError("Connect a MiniMax H3 audio-video latent.")
        video, template = samples.tensors
        if video.ndim != 5 or video.shape[:2] != (1, 24) or template.ndim != 4 or template.shape[:3] != (1, 32, 2) or template.shape[-1] < 1:
            raise ValueError("Reference audio locking requires a single MiniMax H3 take.")
        wave = audio["waveform"]
        rate = int(audio["sample_rate"])
        if rate <= 0 or wave.ndim != 3 or wave.shape[0] != 1 or wave.shape[1] not in (1, 2) or wave.shape[-1] == 0 or not torch.isfinite(wave).all():
            raise ValueError("Provide a finite mono or stereo reference audio track.")
        vae_rate = int(getattr(audio_vae, "audio_sample_rate", 32000))
        if rate != vae_rate:
            wave = comfy.audio.resample(wave, rate, vae_rate)
        if wave.shape[1] == 1:
            wave = wave.repeat(1, 2, 1)
        count = round(template.shape[-1] * vae_rate / 40)
        # Pad real waveform silence before encoding, never empty audio latents.
        wave = F.pad(wave[..., :count], (0, max(0, count - wave.shape[-1])))
        encoded = audio_vae.encode(wave.movedim(1, -1))
        if encoded.shape[:-1] != template.shape[:-1] or encoded.shape[-1] < 1 or abs(encoded.shape[-1] - template.shape[-1]) > 2:
            raise ValueError("Choose the MiniMax H3 audio VAE for this speech track.")
        missing = template.shape[-1] - encoded.shape[-1]
        if missing > 0:
            encoded = torch.cat((encoded, encoded[..., -1:].expand(*encoded.shape[:-1], missing)), dim=-1)
        encoded = encoded[..., :template.shape[-1]]
        previous = latent.get("noise_mask")
        if previous is not None and (not isinstance(previous, NestedTensor) or len(previous.tensors) != 2):
            raise ValueError("Connect an H3 latent with separate video and audio noise masks.")
        video_mask = previous.tensors[0] if isinstance(previous, NestedTensor) else torch.ones_like(video)
        return ({**latent, "samples": NestedTensor((video, encoded)),
                 "noise_mask": NestedTensor((video_mask, torch.zeros_like(encoded)))},)


class ZuraH3PreserveBackground:
    """Pack a native source-video latent with conservative H3 edit masks.

    Video encoding remains a visible native VAEEncode node. This adapter only
    aligns the reviewed mask with H3's temporal bins and 32-pixel DiT patches.
    Causal caption timing avoids locking regions before their text appears,
    but the VAE mixes a whole chunk and can still leave lighting boundaries.
    Neither timing setting guarantees exact decoded lettering or colours.
    """

    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "preserve"
    RETURN_TYPES = ("LATENT",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"latent": ("LATENT",), "source_latent": ("LATENT",), "mask": ("MASK",)},
                "optional": {"protect_unedited_regions": ("BOOLEAN", {"default": False,
                    "tooltip": "Protect the union of unedited pixels across each VAE chunk. Keep original people or source lettering while changing the surrounding pixels."}),
                             "protection_timing": (["chunk", "causal"], {"default": "chunk",
                                 "tooltip": "Chunk protects moving subjects conservatively. Causal prevents future captions from locking earlier empty areas; H3 VAE decoding can still mix pixels within a chunk."})}}

    def preserve(self, latent, source_latent, mask, protect_unedited_regions=False, protection_timing="chunk"):
        from comfy.nested_tensor import NestedTensor
        samples = latent.get("samples")
        if not isinstance(samples, NestedTensor) or len(samples.tensors) != 2:
            raise ValueError("Connect a MiniMax H3 audio-video latent.")
        template, audio = samples.tensors
        video = source_latent.get("samples")
        if not isinstance(video, torch.Tensor) or video.shape != template.shape or video.ndim != 5 or video.shape[:2] != (1,24):
            raise ValueError("Encode the padded H3 source video with the MiniMax H3 video VAE.")
        tokens, height, width = video.shape[-3:]
        frames = sum((1,4,4,4,4)[k % 5] for k in range(tokens))
        if mask.shape != (frames,height*16,width*16) or height % 2 or width % 2 or not torch.isfinite(mask).all():
            raise ValueError("The approved mask must match the padded H3 source video.")
        if protection_timing not in ("chunk", "causal"):
            raise ValueError("Choose chunk or causal protection timing.")
        pixel = (mask > .5).float()
        # Ordinary replacement expands the EDIT union to retain brief moving
        # edges. People or lettering protection needs the opposite guarantee:
        # any protected pixel locks its entire spatial patch in the selected
        # temporal context. Pool protection, then invert after all unions.
        pool_pixels = 1 - pixel if protect_unedited_regions else pixel
        spatial = F.max_pool2d(pool_pixels[:,None],16,16)[:,0]
        # Each native VAE chunk spans 17 frames. Conservative protection
        # shares the full union; Relight captions use past context only.
        def temporal_end(k):
            start = (k // 5) * 17
            if protect_unedited_regions and protection_timing == "causal":
                # Each encoded chunk has frame bins 1,4,4,4,4. Retain past
                # caption context, without locking empty areas before a caption
                # exists. The bidirectional VAE decoder can still blend within
                # its chunk: this is conditioning, not an exact RGB guarantee.
                return min(start + 1 + 4 * (k % 5), frames)
            return min(start + 17, frames)

        temporal = torch.stack([spatial[(k//5)*17:temporal_end(k)].amax(0)
                                for k in range(tokens)])[None,None]
        patches = F.max_pool3d(temporal,(1,2,2),(1,2,2))
        if protect_unedited_regions:
            patches = 1 - patches
        video_mask = patches.repeat_interleave(2,-2).repeat_interleave(2,-1).expand(video.shape)
        previous = latent.get("noise_mask")
        audio_mask = previous.tensors[1] if isinstance(previous,NestedTensor) and len(previous.tensors)==2 else torch.ones_like(audio)
        return ({**latent, "samples": NestedTensor((video,audio)),
                 "noise_mask": NestedTensor((video_mask,audio_mask))},)


class ZuraH3CleanDepthTextRegions:
    """Remove detected caption geometry from a native depth guide, not RGB."""

    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "clean"
    RETURN_TYPES = ("IMAGE",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"depth": ("IMAGE",), "clip_details": ("GENJ_CLIP",)}}

    def clean(self, depth, clip_details):
        regions = clip_details.get("text_regions", [])
        if not regions:
            return (depth,)
        reference = clip_details.get("text_regions_size")
        if not reference or len(reference) != 2 or min(reference) <= 0:
            raise ValueError("Prepare the text removal mask again before cleaning depth.")
        if depth.ndim != 4 or not torch.isfinite(depth).all():
            raise ValueError("Connect the source video's native depth guide.")
        height, width = depth.shape[1:3]
        result = depth.clone()
        for region in regions:
            x,y,w,h = (float(region[key]) for key in ("x","y","width","height"))
            if not all(math.isfinite(value) for value in (x,y,w,h)) or w <= 0 or h <= 0:
                continue
            left=max(0,min(width,math.floor(x*width/reference[0])))
            right=max(0,min(width,math.ceil((x+w)*width/reference[0])))
            top=max(0,min(height,math.floor(y*height/reference[1])))
            bottom=max(0,min(height,math.ceil((y+h)*height/reference[1])))
            if right<=left or bottom<=top:
                continue
            # Interpolate neighbouring depth rows across the text panel. Keep
            # source pose, facial geometry and every other depth pixel intact.
            above = depth[:,max(0,top-3):top,left:right].mean(1,keepdim=True) if top else None
            below = depth[:,bottom:min(height,bottom+3),left:right].mean(1,keepdim=True) if bottom<height else None
            if above is None and below is None:
                continue
            if above is None: above=below
            if below is None: below=above
            amount=((torch.arange(bottom-top,device=depth.device,dtype=depth.dtype)+1)/(bottom-top+1))[None,:,None,None]
            result[:,top:bottom,left:right] = above*(1-amount)+below*amount
        return (result,)


def build_h3_graph(project, use_cache=True, preserve_background=True):
    """Separate picture references, native audio and depth-controlled masked conditioning."""
    if project.get("viewport_render"):
        return build_h3_viewport_graph(project)
    from . import verify_review
    from .studio import assert_approved, check_asset, require_relight_direction

    assert_approved(project)
    c = project["config"]
    require_relight_direction(c)
    if c["engine"] != "h3":
        raise ValueError("Choose MiniMax H3 before starting an H3 take.")
    if c["background"] != "keep":
        raise ValueError("H3 currently keeps the original background. Choose LTX for scene restyling.")
    if project.get("opening_approval") != project.get("opening_key") or not project.get("opening_input"):
        raise ValueError("Check the character preview and choose Animate this look first.")
    if c.get("preserve_people") and project.get("look_mode") == "ready":
        raise ValueError("Keep original people currently requires Build from references so the opening can be registered to the protected source.")
    if c.get("preserve_people") and not preserve_background:
        raise ValueError("Keep original people requires native source preservation during sampling.")
    relight = c.get("workflow_mode") == "relight"
    if relight:
        if project.get("look_mode") == "ready":
            raise ValueError("Relight requires Build from references to create and review a lighting frame from your prompt.")
        if c.get("remove_text"):
            preserve_background = False
        elif not preserve_background:
            raise ValueError("Relight with source lettering requires native source preservation during sampling.")
    else:
        check_asset(project["character"])
    check_asset(project["opening_input"])
    _, manifest = verify_review(project["review"])
    preset = c["h3_preset"]
    preview = False
    count = manifest["clip"]["frames"]
    if not 5 <= count <= 120:
        raise ValueError("H3 supports a selected clip between 0.21 and 5 seconds. Change Clip length and prepare it again.")
    finished_frame_index = _finished_frame_index(project, count)
    if finished_frame_index is not None:
        check_asset(project["starting_asset"])
    direction = ("Replace only the selected head; keep the body and clothing unchanged. "
                 if c["scope"] == "head" else "Replace the selected performer's head, body and clothing. ")
    prompt = (
        "<Picture 1> is the approved opening scene and defines framing, pose, lighting and the replacement character in this shot. "
        "<Picture 2> is the same replacement character's appearance reference: use its face, hairstyle, clothing, "
        "colours and details whenever they become visible. Treat any multiple views on this image as reference views of one character, "
        "never as a collage or extra people. The depth control supplies the source performance's geometry and motion, "
        "not the output's appearance. Match its changing hand positions, body gestures, facial movement and camera timing. "
        "Use the replacement character's face and clothes throughout; do not return to the original performer's costume. "
        "<Audio 1> supplies the original performance and speech timing. " + direction +
        "Keep one performer in the scene. Follow the source gestures and speech. Preserve the background, objects, "
        "camera and lighting outside the replacement area. " + c["prompt"])
    if c.get("edit_area", "mask") == "scene" or c.get("mask_method", "auto") != "auto":
        area = ("Transform the whole scene. " if c.get("edit_area") == "scene" else
                "Transform only the reviewed masked area" +
                (" described as " + c.get("mask_prompt", "") if c.get("mask_method") == "text" else " selected by the artist") + ". ")
        prompt = (
            "<Picture 1> is the approved opening scene. Match its appearance throughout the shot. "
            "<Picture 2> supplies additional appearance details for the selected area. " + area +
            "The depth control supplies the source geometry and motion, not its appearance. "
            "Retain the changing camera perspective, framing, ground plane, object positions and foot contact. "
            "Where a performer is present, match the changing hand positions, body gestures, facial movement and camera timing. "
            "<Audio 1> supplies the original performance and speech timing. Follow the source gestures and speech. " +
            ("Preserve the background, objects and lighting outside the selected area. " if c.get("edit_area") != "scene" else "") +
            "Do not reproduce a reference collage or add extra people. " + c["prompt"])
    if c.get("preserve_people"):
        prompt = (
            "<Picture 1> is the approved scene. Native masked source and depth conditioning supply the original people and performance. "
            "Change only the surroundings outside the protected people to match the approved scene. "
            "<Picture 2> provides environment appearance details only; never replace people from a reference image. "
            "Retain every original person's identity, apparent age, face, hair, clothing, body, changing pose and facial performance. "
            "The reviewed edit mask excludes the original people. Retain their appearance through native latent conditioning while regenerating moving boundaries. "
            "Depth control supplies source geometry, layout, camera movement, object positions and ground contact. "
            "<Audio 1> supplies the original performance and speech timing. Follow the source gestures and speech. " + c["prompt"])
    if relight:
        prompt = (
            "<Picture 1> is the approved relit version of this same source scene. "
            "The native source-video and depth controls provide the original scene and performance. Change only lighting to match <Picture 1> "
            "throughout the complete frame: light direction, intensity, colour, shadows, highlights and exposure. "
            "Retain the original people and their identities, apparent age, facial details, clothes and materials. "
            "Retain all objects, geometry, scene layout, camera movement, framing and source body and facial performance. "
            "The depth control preserves the source geometry and movement. Do not replace, add or remove any subject or object. "
            "<Audio 1> supplies the original performance and speech timing. Follow the source gestures and speech. "
            + (c.get("image_prompt") or c["prompt"]))
        if c.get("preserve_identity"):
            prompt += (
                " <Picture 2>, <Picture 3> and <Picture 4> show the same original performer at early, middle and late moments. "
                "Use these source-frame references only to preserve this person's facial identity, apparent age, hair and facial features. "
                "Do not copy their original lighting, background, framing or pose from those references; follow the approved relit frame and source motion instead.")
    if c.get("remove_text"):
        prompt += " Remove all masked title banners, captions and subtitles completely. Fill them with clean background or character clothing. Do not reproduce any on-screen text overlays."
    if project.get("audio") and c.get("lip_sync"):
        prompt = prompt.replace("facial movement and camera timing", "head direction, eye expression and camera timing")
        prompt = prompt.replace("<Audio 1> supplies the original performance and speech timing.",
            "<Audio 1> is the replacement dialogue. Reproduce its words and timing through natural mouth and jaw articulation, with a resting mouth during silence. Ignore the source video's original dialogue and mouth movements.")
        prompt = prompt.replace("Follow the source gestures and speech.", "Follow the source body gestures and the replacement audio's speech.")
    if finished_frame_index is not None:
        prompt += (f" The approved finished image (<Picture 1>) is the visual keyframe for output frame "
                   f"{finished_frame_index + 1} of {count}. Match that frame to the supplied image; use the source "
                   "performance and depth guide to carry motion through the rest of the clip.")
    graph = {}

    def node(identity, typ, **inputs):
        graph[identity] = {"class_type": typ, "inputs": inputs}
        return [identity, 0]

    generation_resolution = 1280 if c.get("delivery_mode") == "enhanced1080" else c.get("resolution", c["size"])
    reviewed = node("h3_shot", "GenjLoadReviewedShot", shot_id=project["review"],
                    approved_shot_id=project["review"], render_long_edge=generation_resolution,
                    output_scale=1, preview_seconds=2 if preview else 0)
    pad_inputs = {"source": reviewed, "mask_video": ["h3_shot", 1]}
    if c["pitch"]:
        node("h3_guidance", "GetVideoComponents", video=["h3_shot", 2])
        pad_inputs["guidance_audio"] = ["h3_guidance", 1]
    node("h3_pad", "GenjH3FramePad", **pad_inputs)
    model_source = ["h3_pad", 0]
    model_mask = ["h3_pad", 1]
    has_verified_performer_mask = "performer_mask.mp4" in manifest.get("files", {})
    repair_background_text = bool(
        preserve_background and c.get("remove_text") and manifest["clip"].get("text_regions")
        and has_verified_performer_mask)
    if repair_background_text:
        cleanup = text_cleanup_readiness()
        if not cleanup["ready"]:
            raise ValueError(
                "H3 background text cleanup needs ComfyUI-ArtVenture and ComfyUI-KJNodes. "
                "Install these packs, restart ComfyUI and try again. Missing nodes: "
                + ", ".join(cleanup["missing_nodes"]))
        genuine_pad_inputs = {"source": reviewed, "mask_video": ["h3_shot", 4]}
        if c["pitch"]:
            genuine_pad_inputs["guidance_audio"] = ["h3_guidance", 1]
        node("h3_genuine_mask_pad", "GenjH3FramePad", **genuine_pad_inputs)
        node("h3_text_background_mask", "ZuraTextBackgroundRepairMask",
             combined_mask=["h3_pad", 1], performer_mask=["h3_genuine_mask_pad", 1],
             clip_details=["h3_shot", 3], context=32)
        node("h3_text_background_crop", "ImageCrop", image=["h3_pad", 0],
             width=["h3_text_background_mask", 2], height=["h3_text_background_mask", 3],
             x=["h3_text_background_mask", 4], y=["h3_text_background_mask", 5])
        node("h3_lama_model", "LoadLaMaModel", model_name="big-lama.pt")
        node("h3_lama_inpaint", "LaMaInpaint", image=["h3_text_background_crop", 0],
             mask=["h3_text_background_mask", 0], device_mode="AUTO", lama_model=["h3_lama_model", 0])
        node("h3_text_background_composite", "ImageCompositeMasked", destination=["h3_pad", 0],
             source=["h3_lama_inpaint", 0], x=["h3_text_background_mask", 4],
             y=["h3_text_background_mask", 5], resize_source=False,
             mask=["h3_text_background_mask", 0])
        model_source = node("h3_text_repair_switch", "LazySwitchKJ",
                            switch=["h3_text_background_mask", 6], on_false=["h3_pad", 0],
                            on_true=["h3_text_background_composite", 0])
        model_mask = ["h3_text_background_mask", 1]
    node("h3_opening", "LoadImage", image=project["opening_input"]["file"])
    if not relight:
        node("h3_character", "LoadImage", image=project["character"]["file"])
    opening = node("h3_opening_size", "ImageScale", image=["h3_opening", 0], upscale_method="lanczos",
                   width=["h3_pad", 3], height=["h3_pad", 4], crop="disabled")
    model = node("h3_model", "UNETLoader", unet_name=H3_MODELS["h3"][1], weight_dtype="default")
    fast = preset.endswith("_fast")
    if fast:
        model = node("h3_turbo", "LoraLoaderModelOnly", model=model,
                     lora_name=H3_MODELS["h3_turbo"][1], strength_model=1.0)
    model = node("h3_shift", "MiniMaxH3SigmaShift", model=model, shift_video=12.0, shift_audio=3.0)
    model = apply_attention_backend(node, model, c)
    clip = node("h3_clip", "CLIPLoader", clip_name=H3_MODELS["h3_text"][1], type="minimax", device="default")
    vae = node("h3_vae", "VAELoader", vae_name=H3_MODELS["h3_video_vae"][1])
    audio_vae = node("h3_audio_vae", "VAELoader", vae_name=H3_MODELS["h3_audio_vae"][1])
    patch = node("h3_patch", "ModelPatchLoader", name=H3_MODELS["h3_control"][1])
    depth = node("h3_depth", "DepthAnythingV2Preprocessor", image=model_source,
                 ckpt_name="depth_anything_v2_vitl.pth", resolution=512)
    depth = node("h3_depth_size", "ImageScale", image=depth, upscale_method="bilinear",
                 width=["h3_pad", 3], height=["h3_pad", 4], crop="disabled")
    if c.get("remove_text") and manifest["clip"].get("text_regions"):
        depth = node("h3_clean_depth", "ZuraH3CleanDepthTextRegions", depth=depth, clip_details=["h3_shot",3])
    model = node("h3_inpaint", "MiniMaxH3FunControlNetApply", model=model, model_patch=patch,
                 vae=vae, strength=1.0, start_percent=0.0, end_percent=1.0,
                 source_video=model_source, mask=model_mask, control_video=depth)
    live_preview_node = None
    try:
        import nodes
        if "MiniMaxH3PreviewOverrideCS" in nodes.NODE_CLASS_MAPPINGS:
            live_preview_node = "h3_live_preview_" + str(project["id"])
    except (ImportError, AttributeError):
        pass
    if live_preview_node:
        # Reuse the installed H3 Director's low-cost latent-RGB sampler preview.
        # Its VAE-quality mode adds decode time and VRAM, so Studio keeps the fast
        # approximation and labels it honestly in the canvas.
        model = node(live_preview_node, "MiniMaxH3PreviewOverrideCS", model=model,
                     decode="latent2rgb (fast)", preview_target="node", max_resolution=512,
                     preview_frames=12, preview_fps=24.0, playback="true speed",
                     webp_quality=60, every_n_steps=2, max_preview_overhead=10,
                     suppress_default_preview=True)
    # A native prompt source keeps the artist control in Your inputs and lets
    # the reference stage receive its inputs in a single ordered hand-off.
    prompt_input = node("h3_prompt", "PrimitiveStringMultiline", value=prompt)
    reference_inputs = {"ref_images.ref_image_0": opening, "ref_audios.ref_audio_0": ["h3_pad", 2]}
    if relight and c.get("preserve_identity"):
        # Three evenly spaced stills give H3 identity context across the source
        # performance without loading another detector or extracting a new model.
        for slot, frame_index in enumerate(sorted({0, count // 2, count - 1}), start=1):
            identity = f"h3_identity_ref_{slot}"
            node(identity, "ImageFromBatch", image=["h3_pad", 0],
                 batch_index=frame_index, length=1)
            reference_inputs[f"ref_images.ref_image_{slot}"] = [identity, 0]
    if not relight:
        reference_inputs["ref_images.ref_image_1"] = ["h3_character", 0]
    positive = node("h3_references", "MiniMaxH3ReferenceToVideo", clip=clip, vae=vae, audio_vae=audio_vae,
                    prompt=prompt_input, width=["h3_pad", 3], height=["h3_pad", 4], length=["h3_pad", 5],
                    ref_image_size="match", **reference_inputs)
    latent = ["h3_references", 1]
    if finished_frame_index is not None and finished_frame_index != 0:
        positive = node("h3_finished_frame", "MiniMaxH3AddGuide", positive=positive, latent=latent,
                        vae=vae, image=opening, frame_idx=finished_frame_index)
    else:
        # Preserve the normal generated-opening behaviour when no finished
        # frame is supplied, and retain the existing first-frame route when the
        # uploaded finished image is explicitly assigned to frame one.
        positive = node("h3_first_frame", "MiniMaxH3AddGuide", positive=positive, latent=latent,
                        vae=vae, image=opening, frame_idx=0)
    positive = node("h3_speech", "MiniMaxH3AddGuide", positive=positive, latent=latent,
                    audio_vae=audio_vae, audio=["h3_pad", 2], frame_idx=0)
    if preserve_background:
        source_latent = node("h3_source_latent", "VAEEncode", pixels=model_source, vae=vae)
        latent = node("h3_preserve_background", "ZuraH3PreserveBackground", latent=latent,
                      source_latent=source_latent, mask=model_mask,
                      **({"protect_unedited_regions": bool(relight)} if c.get("preserve_people") or relight else {}),
                      **({"protection_timing": "causal"} if relight else {}))
    # Keep the actual selected soundtrack fixed in both original-performance
    # and replacement-dialogue modes, including valid silence for silent clips.
    latent = node("h3_locked_audio", "ZuraH3LockReferenceAudio", latent=latent,
                  audio_vae=audio_vae, audio=["h3_pad", 2])
    guider = node("h3_guider", "BasicGuider", model=model, conditioning=positive)
    noise = node("h3_noise", "RandomNoise", noise_seed=c["seed"])
    sigmas = node("h3_schedule", "BasicScheduler", model=model, scheduler="simple",
                  steps=sampling_steps(c, fast), denoise=1.0)
    sampler = node("h3_sampler", "KSamplerSelect", sampler_name="res_multistep" if fast else "euler")
    sampled = node("h3_sample", "SamplerCustomAdvanced", noise=noise, guider=guider,
                   sampler=sampler, sigmas=sigmas, latent_image=latent)
    decoded = node("h3_decode", "VAEDecode", samples=sampled, vae=vae)
    trimmed = node("h3_trim", "GetImageRangeFromBatch", images=decoded, start_index=0, num_frames=["h3_pad", 6])
    video = node("h3_video", "CreateVideo", images=trimmed, fps=24.0, audio=["h3_pad", 2])
    enhanced_delivery = c.get("delivery_mode") == "enhanced1080"
    node("h3_export", "GenjRestoreSoundtrack", video=video, clip_details=["h3_shot", 3],
         take_name="studio_" + project["id"][:8] + ("_h3_base" if enhanced_delivery else "_h3"),
         **({"output_subfolder": "studio_intermediate"} if enhanced_delivery else {}))
    key = cache_key(project)
    cached_digest = None
    if use_cache and cache_valid(key, expected_frames=max(124, valid_length(count))):
        try:
            from .file_cache import digest_file
            cached_digest = digest_file(cache_path(key))
        except OSError:
            pass  # A disappearing file also needs the native reference rebuild.
    if cached_digest:
        node("h3_cached", "GenjLoadH3Conditioning", cache_key=key, cache_digest=cached_digest)
        graph["h3_guider"]["inputs"]["conditioning"] = ["h3_cached", 0]
        if "h3_preserve_background" in graph:
            graph["h3_preserve_background"]["inputs"]["latent"] = ["h3_cached", 1]
        elif "h3_locked_audio" in graph:
            graph["h3_locked_audio"]["inputs"]["latent"] = ["h3_cached", 1]
        else:
            graph["h3_sample"]["inputs"]["latent_image"] = ["h3_cached", 1]
        graph = reachable_graph(graph, ["h3_export"])
    from .speech import add_finish
    return add_finish(graph, project, native_speech=True)


NODE_CLASS_MAPPINGS = {c.__name__: c for c in (GenjH3FramePad, GenjH3ViewportFrameData, GenjSaveH3Conditioning, GenjLoadH3Conditioning, ZuraH3LockReferenceAudio, ZuraH3PreserveBackground, ZuraH3CleanDepthTextRegions)}
NODE_DISPLAY_NAME_MAPPINGS = {"GenjH3FramePad": "Prepare H3 Frames and Mask",
    "GenjH3ViewportFrameData": "Prepare H3 Viewport Frames",
    "GenjSaveH3Conditioning": "Save H3 Character References", "GenjLoadH3Conditioning": "Load H3 Character References",
    "ZuraH3LockReferenceAudio": "Zura · Keep Selected Audio During H3 Sampling",
    "ZuraH3PreserveBackground": "Zura · Preserve H3 Background During Sampling",
    "ZuraH3CleanDepthTextRegions": "Zura · Remove Captions from H3 Depth Guide"}
