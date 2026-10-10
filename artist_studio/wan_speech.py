"""Native InfiniteTalk preparation for Wan, with verified local guide reuse.

This module builds graphs and verifies their local outputs. It never submits
jobs, downloads weights or performs diffusion inference itself.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

RECIPE = "wan21-infinitetalk-i2v-sdpa-v1"
CROP_RECIPE = "approved-face-portrait-v1"
MAX_SECONDS = 30
GUIDE_SIZE = (480, 640)
GUIDE_FPS = 25
SOURCE_FPS = 24
POSITIVE = ("The person in the reference talks naturally. Their lips, jaw and facial "
            "expression follow the supplied speech, with a resting mouth during silence. "
            "A steady camera and restrained head movement. Consistent identity.")
NEGATIVE = ("blurry face, distorted mouth, frozen face, unnatural expression, extra teeth, "
            "subtitles, text, camera movement, exaggerated head motion")

# folder, canonical basename, loader, input, compatible upstream spelling
MODELS = {
    "base": ("diffusion_models", "Wan2_1-I2V-14B-480P_fp8_e4m3fn.safetensors", "WanVideoModelLoader", "model", ()),
    "speech": ("diffusion_models", "Wan2_1-InfiniteTalk-Single_fp16.safetensors", "MultiTalkModelLoader", "model",
               ("Wan2_1-InfiniTetalk-Single_fp16.safetensors",)),
    "lora": ("loras", "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors", "WanVideoLoraSelect", "lora", ()),
    "vae": ("vae", "Wan2_1_VAE_bf16.safetensors", "WanVideoVAELoader", "model_name", ()),
    "text": ("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "CLIPLoader", "clip_name", ()),
    "vision": ("clip_vision", "clip_vision_h.safetensors", "CLIPVisionLoader", "clip_name", ()),
    "wav2vec": ("wav2vec2", "chinese-wav2vec2-base.bin", "Wav2VecModelLoader", "model", ()),
    "pose": ("detection", "vitpose-l-wholebody.onnx", "OnnxDetectionModelLoader", "vitpose_model", ()),
    "detector": ("detection", "yolov10m.onnx", "OnnxDetectionModelLoader", "yolo_model", ()),
}
NATIVE_NODES = (
    "GenjLoadReviewedShot", "GenjApplyReferenceAudio", "ZuraWanReviewedFrames",
    "LoadImage", "LoadAudio", "GetVideoComponents", "GetImageRangeFromBatch",
    "GetImageSizeAndCount", "ImageResizeKJv2", "OnnxDetectionModelLoader", "PoseAndFaceDetection",
    "ZuraWanSpeechReferenceCrop", "ZuraWanSpeechSaveGuide", "EmptyAudio", "AudioConcat",
    "WanVideoVAELoader", "WanVideoBlockSwap", "WanVideoLoraSelect", "MultiTalkModelLoader",
    "WanVideoModelLoader", "CLIPVisionLoader", "WanVideoClipVisionEncode", "CLIPLoader",
    "CLIPTextEncode", "WanVideoTextEmbedBridge", "Wav2VecModelLoader", "MultiTalkWav2VecEmbeds",
    "WanVideoImageToVideoMultiTalk", "WanVideoSampler", "WanVideoPassImagesFromSamples", "VHS_VideoCombine",
)
NODE_PACKS = [
    {"id": "comfyui-wanvideowrapper", "name": "ComfyUI-WanVideoWrapper", "tested_version": "1.4.7",
     "repository": "https://github.com/kijai/ComfyUI-WanVideoWrapper"},
    {"id": "comfyui-wananimatepreprocess", "name": "ComfyUI-WanAnimatePreprocess", "tested_version": "1.0.3",
     "repository": "https://github.com/kijai/ComfyUI-WanAnimatePreprocess"},
    {"id": "comfyui-kjnodes", "name": "ComfyUI-KJNodes", "repository": "https://github.com/kijai/ComfyUI-KJNodes"},
    {"id": "comfyui-videohelpersuite", "name": "VideoHelperSuite", "tested_version": "1.7.9",
     "repository": "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite"},
]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def enabled(project):
    c = project.get("config", {})
    return c.get("engine") == "wan" and bool(project.get("audio")) and bool(c.get("lip_sync"))


def _classes():
    try:
        import nodes
        return nodes.NODE_CLASS_MAPPINGS
    except (ImportError, AttributeError):
        return {}


def _choices(loader, field):
    cls = _classes().get(loader)
    if cls is None:
        return []
    inputs = cls.INPUT_TYPES()
    spec = {**inputs.get("optional", {}), **inputs.get("required", {})}[field]
    return spec[0] if isinstance(spec[0], list) else (spec[1].get("options", []) if len(spec) > 1 else [])


def _resolve_model(identity):
    import folder_paths
    folder, basename, loader, field, aliases = MODELS[identity]
    options = _choices(loader, field)
    for name in (basename, *aliases):
        matches = [value for value in options if value.replace("\\", "/").split("/")[-1] == name]
        if len(matches) > 1:
            raise ValueError("Choose one unambiguous Wan speech model: " + name)
        if matches:
            filename = folder_paths.get_full_path(folder, matches[0])
            if filename and Path(filename).is_file():
                return matches[0], Path(filename)
    raise ValueError("Missing Wan speech model: " + folder + "/" + basename)


def readiness():
    classes = _classes()
    missing_nodes = [name for name in NATIVE_NODES if name not in classes]
    missing_models = []
    for identity, (folder, basename, *_) in MODELS.items():
        try:
            _resolve_model(identity)
        except (ValueError, KeyError, AttributeError, OSError):
            missing_models.append(folder + "/" + basename)
    unsupported = []
    for loader, field, choice in (("WanVideoModelLoader", "base_precision", "fp16"),
                                   ("WanVideoModelLoader", "attention_mode", "sdpa"),
                                   ("WanVideoModelLoader", "quantization", "disabled"),
                                   ("WanVideoModelLoader", "rms_norm_function", "default"),
                                   ("WanVideoImageToVideoMultiTalk", "mode", "infinitetalk")):
        if loader in classes:
            try:
                if choice not in _choices(loader, field):
                    unsupported.append(loader + "." + field + "=" + choice)
            except (KeyError, AttributeError, TypeError):
                unsupported.append(loader + "." + field + "=" + choice)
    if "WanVideoVAELoader" in classes:
        schema = classes["WanVideoVAELoader"].INPUT_TYPES()
        fields = {**schema.get("optional", {}), **schema.get("required", {})}
        for field in ("use_cpu_cache", "verbose"):
            if field not in fields or fields[field][0] != "BOOLEAN":
                unsupported.append("WanVideoVAELoader." + field)
    vhs_class = classes.get("VHS_VideoCombine")
    vhs_module = sys.modules.get(getattr(vhs_class, "__module__", ""))
    vhs_ffmpeg = getattr(vhs_module, "ffmpeg_path", None)
    resolved_ffmpeg = (vhs_ffmpeg if vhs_ffmpeg and (Path(vhs_ffmpeg).is_file() or shutil.which(vhs_ffmpeg))
                       else shutil.which("ffmpeg"))
    missing_tools = [] if resolved_ffmpeg else ["ffmpeg"]
    return {"ready": not (missing_nodes or missing_models or missing_tools or unsupported),
            "missing_nodes": missing_nodes, "missing_models": missing_models, "missing_tools": missing_tools,
            "unsupported_options": unsupported, "node_packs": NODE_PACKS,
            "setup": "Setup_Wan_Speech_Windows.cmd", "recipe": RECIPE,
            "tested_seconds": 5, "max_seconds": MAX_SECONDS, "guide_size": list(GUIDE_SIZE)}


def _timeline(project):
    from . import verify_review
    _, manifest = verify_review(project["review"])
    clip = manifest["clip"]
    frames = int(clip["frames"])
    if frames < 1 or float(clip["fps"]) != SOURCE_FPS:
        raise ValueError("Prepare the source at 24 fps before creating Wan speech.")
    seconds = frames / SOURCE_FPS
    if seconds > MAX_SECONDS:
        raise ValueError("Wan reference speech currently supports up to 30 seconds. Choose a shorter clip.")
    return {"review": project["review"], "mask_sha": manifest["files"]["mask.mp4"],
            "frames": frames, "fps": SOURCE_FPS, "duration": seconds,
            "guide_frames": math.ceil(frames * GUIDE_FPS / SOURCE_FPS),
            "source_start": float(clip["start"]), "source_sha": clip["source_hash"]}


def audio_signature(audio):
    wave = audio["waveform"].detach().cpu().float().contiguous()
    if wave.ndim != 3 or wave.shape[0] != 1 or wave.shape[1] not in (1, 2):
        raise ValueError("Choose one mono or stereo speech track for Wan facial performance.")
    import torch
    rate = int(audio["sample_rate"])
    if rate < 1 or rate > 192000 or not torch.isfinite(wave).all():
        raise ValueError("Choose a valid reference speech track.")
    return {"sha": hashlib.sha256(wave.numpy().tobytes()).hexdigest(), "sample_rate": rate,
            "channels": int(wave.shape[1]), "samples": int(wave.shape[-1])}


def _selected_audio(project, timeline):
    from .studio import check_asset
    from . import fit_audio
    from comfy_extras.nodes_audio import load
    wave, rate = load(str(check_asset(project["audio"])))
    start = float(project["config"].get("audio_start", 0))
    if not math.isfinite(start) or start < 0 or round(start * rate) >= wave.shape[-1]:
        raise ValueError("The audio start must be within the reference track.")
    selected = fit_audio({"waveform": wave[None, :, round(start * rate):], "sample_rate": rate}, timeline["duration"])
    return audio_signature(selected)


def _key_data(project):
    from .studio import assert_approved, check_asset
    if not enabled(project):
        raise ValueError("Choose Wan and Reference audio + new performance first.")
    assert_approved(project)
    if project.get("opening_approval") != project.get("opening_key") or not project.get("opening_input"):
        raise ValueError("Approve the character preview before creating its facial performance.")
    check_asset(project["opening_input"])
    timeline = _timeline(project)
    stamps = {}
    for identity in MODELS:
        name, path = _resolve_model(identity)
        stat = path.stat()
        stamps[identity] = [name, stat.st_size, stat.st_mtime_ns]
    # Changes to the installed loader invalidate its old recipe cache, without
    # reading model weights or including machine-specific absolute paths.
    cls = _classes().get("WanVideoModelLoader")
    module = sys.modules.get(getattr(cls, "__module__", ""))
    file = getattr(module, "__file__", None)
    provider = digest(file) if file and Path(file).is_file() else "schema-only"
    return {"version": 1, "recipe": RECIPE, "crop_recipe": CROP_RECIPE,
            "preparation_approval": project["approval"],
            "opening_sha": project["opening_input"]["sha"], "opening_approval": project["opening_approval"],
            "source": timeline, "performer": int(project["config"].get("performer", -1)),
            "audio_sha": project["audio"]["sha"], "audio_start": float(project["config"].get("audio_start", 0)),
            "selected_audio": _selected_audio(project, timeline), "seed": int(project["config"]["seed"]),
            "models": stamps, "provider_sha": provider, "guide_size": list(GUIDE_SIZE), "guide_fps": GUIDE_FPS,
            "driver_frames": max(81, timeline["guide_frames"]),
            "audio_policy": "unchanged-selection; zero-tail-on-driver-only; no-onset-shift",
            "sampler": {"steps": 6, "cfg": 1, "audio_cfg": 2, "shift": 11, "scheduler": "dpm++_sde",
                        "window": 81, "motion": 9, "precision": "fp16", "attention": "sdpa",
                        "swap": 32, "non_blocking": False, "prefetch": 0, "merge_loras": False}}


def guide_key(project):
    return hashlib.sha256(canonical(_key_data(project)).encode()).hexdigest()


def _root():
    import folder_paths
    return Path(folder_paths.get_output_directory()).resolve() / "genj" / "wan_speech_guides"


def _manifest_path(key, pending=False):
    if not re.fullmatch(r"[a-f0-9]{64}", key):
        raise ValueError("Invalid Wan speech guide key.")
    return _root() / (key + (".pending.json" if pending else ".json"))


def _atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(canonical(data), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _expand_signals(graph):
    """Expand the graph view's lossless stage hand-offs before provenance checks."""
    stack = set()
    def resolve(value):
        node = graph.get(str(value[0])) if isinstance(value, list) and len(value) == 2 else None
        if node and node["class_type"] == "ZuraStudioReadSignal":
            return signal(str(node["inputs"]["stage_data"][0]), node["inputs"]["key"])
        return value
    def signal(identity, key):
        marker = (identity, key)
        if marker in stack:
            raise ValueError("A speech stage hand-off contains a cycle.")
        stack.add(marker)
        node = graph[identity]
        if node["class_type"] != "ZuraStudioSignals":
            raise ValueError("A speech stage hand-off is missing.")
        fields = node["inputs"]
        names = json.loads(fields["keys"])
        if key in names:
            value = resolve(fields["value_" + str(names.index(key))])
        elif fields.get("previous"):
            value = signal(str(fields["previous"][0]), key)
        else:
            raise ValueError("A speech stage hand-off value is missing.")
        stack.remove(marker)
        return value
    return {str(identity): {"class_type": node["class_type"],
            "inputs": {name: resolve(value) for name, value in node["inputs"].items()}}
            for identity, node in graph.items()
            if node["class_type"] not in ("ZuraStudioSignals", "ZuraStudioReadSignal")}


def _signature_values(value):
    """JSON and Comfy FLOAT coercion preserve values but change 0.0 to/from 0."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _signature_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_signature_values(item) for item in value]
    return value


def graph_signature(graph, output):
    graph = _expand_signals({str(k): v for k, v in graph.items()})
    stack, memo = set(), {}
    def visit(identity):
        identity = str(identity)
        if identity in stack:
            raise ValueError("A native speech graph contains a cycle.")
        if identity not in memo:
            stack.add(identity)
            node = graph[identity]
            fields = {}
            for name, value in node["inputs"].items():
                if isinstance(value, list) and len(value) == 2 and str(value[0]) in graph:
                    value = [visit(value[0]), value[1]]
                fields[name] = value
            memo[identity] = hashlib.sha256(canonical(_signature_values([node["class_type"], fields])).encode()).hexdigest()
            stack.remove(identity)
        return memo[identity]
    return visit(output)


def build_graph(project):
    state = readiness()
    if not state["ready"]:
        missing = state["missing_nodes"] + state["missing_models"] + state["missing_tools"] + state["unsupported_options"]
        raise ValueError("Wan facial performance needs setup: " + ", ".join(missing) + ". Use Setup_Wan_Speech_Windows.cmd and the listed native node packs.")
    data = _key_data(project)
    key = hashlib.sha256(canonical(data).encode()).hexdigest()
    timeline, audio = data["source"], data["selected_audio"]
    models = {identity: stamp[0] for identity, stamp in data["models"].items()}
    graph = {}
    def node(identity, typ, **inputs):
        graph[identity] = {"class_type": typ, "inputs": inputs}
        return [identity, 0]
    shot = node("ws_shot", "GenjLoadReviewedShot", shot_id=project["review"], approved_shot_id=project["review"],
                render_long_edge=0, output_scale=1, preview_seconds=0.0)
    selected = node("ws_audio_file", "LoadAudio", audio=project["audio"]["file"])
    shot_audio = node("ws_audio_selection", "GenjApplyReferenceAudio", video=shot, clip_details=["ws_shot", 3],
                      audio=selected, audio_start_seconds=data["audio_start"])
    node("ws_components", "GetVideoComponents", video=shot_audio)
    frames = node("ws_reviewed", "ZuraWanReviewedFrames", source=shot, mask_video=["ws_shot", 1])
    first = node("ws_first", "GetImageRangeFromBatch", images=frames, masks=["ws_reviewed", 1], start_index=0, num_frames=1)
    detector = node("ws_detector", "OnnxDetectionModelLoader", vitpose_model=models["pose"],
                    yolo_model=models["detector"], onnx_device="CPUExecutionProvider")
    source_pose = node("ws_source_pose", "PoseAndFaceDetection", model=detector, images=first,
                       width=["ws_reviewed", 2], height=["ws_reviewed", 3], face_padding=0)
    opening = node("ws_opening", "LoadImage", image=project["opening_input"]["file"])
    detection_image = node("ws_opening_detection_size", "ImageResizeKJv2", image=opening,
        width=1024, height=1024, upscale_method="lanczos", keep_proportion="resize",
        pad_color="0, 0, 0", crop_position="center", divisible_by=16, device="cpu")
    opening_pose = node("ws_opening_pose", "PoseAndFaceDetection", model=detector, images=detection_image,
                        width=["ws_opening_detection_size", 1], height=["ws_opening_detection_size", 2], face_padding=0)
    crop = node("ws_crop", "ZuraWanSpeechReferenceCrop", opening=opening, source_images=first,
        approved_mask=["ws_first", 1], source_pose=source_pose, source_boxes=["ws_source_pose", 4],
        opening_pose=opening_pose, opening_boxes=["ws_opening_pose", 4], guide_key=key)
    image = node("ws_crop_size", "ImageResizeKJv2", image=crop, width=480, height=640,
        upscale_method="lanczos", keep_proportion="resize", pad_color="0, 0, 0", crop_position="center", divisible_by=16, device="cpu")
    # Enough real silence for a partial25fps frame and the81-frame first window.
    # Native export and Wan's final soundtrack use the unmodified selection.
    tail = node("ws_driver_silence", "EmptyAudio", duration=max(0, data["driver_frames"] / 25 - timeline["duration"]) + 1 / 25,
                sample_rate=audio["sample_rate"], channels=audio["channels"])
    driver_audio = node("ws_driver_audio", "AudioConcat", audio1=["ws_components", 1], audio2=tail, direction="after")
    vae = node("ws_vae", "WanVideoVAELoader", model_name=models["vae"], precision="bf16",
               use_cpu_cache=False, verbose=False)
    swap = node("ws_swap", "WanVideoBlockSwap", blocks_to_swap=32, offload_img_emb=False,
        offload_txt_emb=False, use_non_blocking=False, vace_blocks_to_swap=0, prefetch_blocks=0, block_swap_debug=False)
    lora = node("ws_lora", "WanVideoLoraSelect", lora=models["lora"], strength=1.0, low_mem_load=False, merge_loras=False)
    speech = node("ws_speech_model", "MultiTalkModelLoader", model=models["speech"])
    model = node("ws_model", "WanVideoModelLoader", model=models["base"], base_precision="fp16",
        quantization="disabled", load_device="offload_device", attention_mode="sdpa", rms_norm_function="default",
        block_swap_args=swap, lora=lora, multitalk_model=speech)
    vision = node("ws_vision", "CLIPVisionLoader", clip_name=models["vision"])
    image_clip = node("ws_image_clip", "WanVideoClipVisionEncode", clip_vision=vision, image_1=image,
        strength_1=1.0, strength_2=1.0, crop="center", combine_embeds="average", force_offload=True, tiles=0, ratio=0.5)
    text_encoder = node("ws_text_encoder", "CLIPLoader", clip_name=models["text"], type="wan", device="cpu")
    positive = node("ws_positive", "CLIPTextEncode", clip=text_encoder, text=POSITIVE)
    negative = node("ws_negative", "CLIPTextEncode", clip=text_encoder, text=NEGATIVE)
    text = node("ws_text", "WanVideoTextEmbedBridge", positive=positive, negative=negative)
    wav2vec = node("ws_wav2vec", "Wav2VecModelLoader", model=models["wav2vec"], base_precision="fp16", load_device="offload_device")
    audio_embeds = node("ws_audio_features", "MultiTalkWav2VecEmbeds", wav2vec_model=wav2vec,
        audio_1=driver_audio, normalize_loudness=True, num_frames=data["driver_frames"], fps=25.0,
        audio_scale=1.0, audio_cfg_scale=2.0, multi_audio_type="para", add_noise_floor=False, smooth_transients=False)
    image_embeds = node("ws_image_features", "WanVideoImageToVideoMultiTalk", vae=vae, start_image=image,
        clip_embeds=image_clip, width=480, height=640, frame_window_size=81, motion_frame=9,
        force_offload=True, colormatch="disabled", tiled_vae=False, mode="infinitetalk", output_path="")
    samples = node("ws_sample", "WanVideoSampler", model=model, image_embeds=image_embeds, text_embeds=text,
        multitalk_embeds=audio_embeds, steps=6, cfg=1.0, shift=11.0, seed=data["seed"], force_offload=True,
        scheduler="dpm++_sde", riflex_freq_index=0, denoise_strength=1.0, batched_cfg=False,
        rope_function="comfy", start_step=0, end_step=-1, add_noise_to_samples=False)
    images = node("ws_decoded", "WanVideoPassImagesFromSamples", samples=samples)
    images = node("ws_trim", "GetImageRangeFromBatch", images=images, start_index=0, num_frames=timeline["guide_frames"])
    exported = node("ws_export", "VHS_VideoCombine", images=images, audio=["ws_components", 1], frame_rate=25.0,
        loop_count=0, filename_prefix="genj/wan_speech_guides/" + key, format="video/h264-mp4",
        pix_fmt="yuv420p", crf=18, save_metadata=False, trim_to_audio=False, pingpong=False, save_output=True)
    recipe = {"guide_key": key, "key_data": data, "graph_signature": graph_signature(graph, "ws_export")}
    node("ws_save", "ZuraWanSpeechSaveGuide", filenames=exported, crop_metadata=["ws_crop", 1],
         selected_audio=["ws_components", 1], guide_key=key, recipe_json=canonical(recipe))
    return graph


def _video_info(path):
    import av
    try:
        with av.open(str(path)) as container:
            if len(container.streams.video) != 1:
                raise ValueError("The speech guide must contain one video stream.")
            stream = container.streams.video[0]
            fps = float(stream.average_rate or 0)
            if not math.isfinite(fps) or fps <= 0:
                raise ValueError("The speech guide has no valid frame rate.")
            count = sum(1 for _ in container.decode(stream))
            return {"width": stream.width, "height": stream.height, "frames": count, "fps": fps,
                    "duration": float(stream.duration * stream.time_base) if stream.duration is not None else count / fps}
    except av.FFmpegError as error:
        raise ValueError("The speech guide cannot be decoded. Prepare it again.") from error


def _verified_artifact(path, key_data):
    path = Path(path).resolve()
    if not path.is_relative_to(_root()) or not path.is_file() or path.suffix.lower() != ".mp4":
        raise ValueError("The speech guide must be an existing local output in Zura's guide folder.")
    info = _video_info(path)
    wanted = key_data["source"]["guide_frames"]
    if (info["width"], info["height"]) != GUIDE_SIZE or info["frames"] != wanted or abs(info["fps"] - 25) > 1e-6:
        raise ValueError("The speech guide does not match the selected dimensions and timeline.")
    if abs(info["duration"] - wanted / 25) > 1 / 1000:
        raise ValueError("The speech guide has changed its duration.")
    return {"path": str(path), "sha": digest(path), "video": info}


def _validate_crop(crop, key):
    if crop.get("recipe") != CROP_RECIPE or crop.get("guide_key") != key:
        raise ValueError("The guide's actual crop recipe is missing or changed.")
    x, y, width, height = crop["crop_xywh"]
    opening_w, opening_h = crop["opening_size"]
    if (any(type(n) is not int for n in (x, y, width, height, opening_w, opening_h)) or
            min(width, height) < 4 or min(x, y) < 0 or x + width > opening_w or y + height > opening_h or width * 4 != height * 3):
        raise ValueError("The guide's actual reference crop is invalid.")
    measurements = [crop.get("source_mask_overlap", 0), crop.get("opening_mask_overlap", 0),
                    crop.get("source_confidence", 0), crop.get("opening_confidence", 0)]
    if (not all(isinstance(value, (int, float)) and math.isfinite(value) for value in measurements) or
            min(measurements[:2]) < .5 or min(measurements[2:]) < .3):
        raise ValueError("The speech reference does not have a trustworthy approved face.")


def save_pending(filenames, crop_metadata, selected_audio, guide_key, recipe_json, prompt, unique_id):
    """CPU/IO endpoint for native graph queues; success promotion happens later."""
    from server import PromptServer
    recipe = json.loads(recipe_json)
    data = recipe["key_data"]
    if recipe.get("guide_key") != guide_key or hashlib.sha256(canonical(data).encode()).hexdigest() != guide_key:
        raise ValueError("The guide's request provenance changed.")
    running, _ = PromptServer.instance.prompt_queue.get_current_queue_volatile()
    if len(running) != 1:
        raise ValueError("The speech guide must belong to the serial running Comfy job.")
    owning = running[0]
    prompt = {str(k): v for k, v in prompt.items()}
    if str(unique_id) not in prompt or prompt[str(unique_id)]["class_type"] != "ZuraWanSpeechSaveGuide":
        raise ValueError("The guide save endpoint is not part of its executed prompt.")
    expanded = _expand_signals({str(k): v for k, v in prompt.items()})
    fields = expanded[str(unique_id)]["inputs"]
    export_id = str(fields["filenames"][0])
    if graph_signature(prompt, export_id) != recipe["graph_signature"]:
        # Advanced edits remain renderable; they cannot warm an unchanged Studio recipe.
        return {"ui": {"text": ["Guide rendered with an edited recipe. Studio will prepare its own selected settings."]}, "result": ("",)}
    owning_graph = _expand_signals({str(k): v for k, v in owning[2].items()})
    owning_save = owning_graph.get(str(unique_id), {})
    if (owning_save.get("class_type") != "ZuraWanSpeechSaveGuide" or owning_save.get("inputs") != fields or
            graph_signature(owning[2], export_id) != recipe["graph_signature"]):
        raise ValueError("The guide does not belong to the recorded running prompt.")
    crop = json.loads(crop_metadata)
    _validate_crop(crop, guide_key)
    actual_audio = audio_signature(selected_audio)
    if actual_audio != data["selected_audio"]:
        raise ValueError("The guide changed the selected audio waveform or timing.")
    if not isinstance(filenames, (tuple, list)) or len(filenames) != 2 or filenames[0] is not True:
        raise ValueError("Save the native speech guide to Comfy's output folder.")
    paths = [Path(value) for value in filenames[1] if str(value).lower().endswith(".mp4")]
    # VHS exposes both its silent intermediate and its final audio-muxed MP4.
    # Its successful UI history points to the final file ending in -audio.
    finals = [path for path in paths if path.stem.endswith("-audio")]
    if len(finals) != 1 or any(not path.name.startswith(guide_key + "_") for path in paths):
        raise ValueError("Expected the native audio-muxed video exported for this guide recipe.")
    artifact = _verified_artifact(finals[0], data)
    record = {"version": 1, **recipe, **artifact, "crop": crop, "audio": actual_audio,
              "prompt_id": owning[1], "state": "pending", "created": time.time()}
    _atomic_json(_manifest_path(guide_key, pending=True), record)
    return {"ui": {"text": [canonical({"guide_key": guide_key, "crop": crop, "audio": actual_audio})]}, "result": (guide_key,)}


def _executed_graph(history):
    status = history.get("status", {})
    if status.get("status_str") != "success" or status.get("completed") is not True:
        raise ValueError("Only a successfully completed speech guide can be reused.")
    prompt = history.get("prompt")
    if not isinstance(prompt, (list, tuple)) or len(prompt) < 3 or not isinstance(prompt[2], dict):
        raise ValueError("The completed guide lacks its executed graph provenance.")
    return prompt[1], prompt[2]


def record_guide(project, history):
    data = _key_data(project)
    key = hashlib.sha256(canonical(data).encode()).hexdigest()
    prompt_id, graph = _executed_graph(history)
    expanded = _expand_signals({str(k): v for k, v in graph.items()})
    saves = [(identity, node) for identity, node in expanded.items() if node["class_type"] == "ZuraWanSpeechSaveGuide"]
    if len(saves) != 1:
        raise ValueError("The completed guide must have one native Zura cache endpoint.")
    identity, save = saves[0]
    recipe = json.loads(save["inputs"]["recipe_json"])
    if recipe.get("key_data") != data or recipe.get("guide_key") != key or save["inputs"]["guide_key"] != key:
        raise ValueError("The completed guide no longer matches this approved shot and voice.")
    export_id = str(save["inputs"]["filenames"][0])
    expected = build_graph(project)
    if recipe["graph_signature"] != graph_signature(expected, "ws_export") or graph_signature(graph, export_id) != recipe["graph_signature"]:
        raise ValueError("The completed guide's executed native recipe changed.")
    pending = json.loads(_manifest_path(key, pending=True).read_text(encoding="utf-8"))
    if pending.get("prompt_id") != prompt_id or pending.get("guide_key") != key or pending.get("key_data") != data:
        raise ValueError("The guide's pending provenance does not belong to this successful job.")
    if pending.get("graph_signature") != recipe["graph_signature"] or pending.get("audio") != data["selected_audio"]:
        raise ValueError("The recorded guide altered its native recipe or selected speech.")
    _validate_crop(pending["crop"], key)
    actual = _verified_artifact(pending["path"], data)
    if actual["sha"] != pending["sha"]:
        raise ValueError("The rendered speech guide changed before completion.")
    output_files = []
    for value in history.get("outputs", {}).values():
        for kind in ("gifs", "videos", "images"):
            for item in value.get(kind, []):
                if item.get("type") == "output" and str(item.get("filename", "")).lower().endswith(".mp4"):
                    import folder_paths
                    output_files.append((Path(folder_paths.get_output_directory()) / item.get("subfolder", "") / item["filename"]).resolve())
    if Path(actual["path"]) not in output_files:
        raise ValueError("The successful history did not export this speech guide.")
    record = {**pending, **actual, "state": "complete", "completed": time.time()}
    _atomic_json(_manifest_path(key), record)
    return record


def _history(prompt_id):
    try:
        from server import PromptServer
        return PromptServer.instance.prompt_queue.get_history(prompt_id).get(prompt_id)
    except (ImportError, AttributeError):
        return None


def load_guide(project):
    data = _key_data(project)
    key = hashlib.sha256(canonical(data).encode()).hexdigest()
    path = _manifest_path(key)
    if not path.is_file():
        pending_path = _manifest_path(key, pending=True)
        if pending_path.is_file():
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            history = _history(pending.get("prompt_id"))
            if history and history.get("status", {}).get("status_str") == "success":
                record_guide(project, history)
        if not path.is_file():
            raise ValueError("Create this shot's native facial performance before preparing Wan animation.")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("state") != "complete" or record.get("guide_key") != key or record.get("key_data") != data:
        raise ValueError("The cached facial performance no longer matches this shot and voice.")
    _validate_crop(record["crop"], key)
    actual = _verified_artifact(record["path"], data)
    if actual["sha"] != record["sha"]:
        raise ValueError("The cached facial performance changed. Prepare it again.")
    return {**record, **actual}


def guide_ready(project):
    if not enabled(project):
        return False
    try:
        load_guide(project)
        return True
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError):
        return False
