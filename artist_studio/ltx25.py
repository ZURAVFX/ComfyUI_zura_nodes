"""Plan visible native LTX 2.5 phases; this module never queues or samples.

The body-guided A2V recipe regenerates the whole scene. A performer mask is
not a background constraint in this route. Longer clips need a separately
qualified continuation recipe. Receipts bind completed native phases to their
actual files before the caller queues a dependent phase.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re

SCHEMA = "zura.ltx25.native-plan/2"
STAGE1_SIGMAS = "1,0.99375,0.9875,0.98125,0.975,0.909375,0.725,0.421875,0"
STAGE2_SIGMAS = "0.909375, 0.725, 0.421875, 0.0"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
PHASES = ("text", "motion", "stage1", "upscale", "refine", "decode")
QUALIFIED_MODELS = {
    "model": "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
    "video_vae": "ltx-2.5-video-vae-conv-bf16.safetensors",
    "audio_vae": "ltx-2.5-audio-vae-bf16.safetensors",
    "union": "ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors",
    "upscaler": "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
    "bbox_detector": "yolox_l.onnx",
    "pose_estimator": "dw-ll_ucoco_384_bs5.torchscript.pt",
}
VIEWPORT_MODELS = {name: value for name, value in QUALIFIED_MODELS.items()
                   if name not in ("bbox_detector", "pose_estimator")}
VIEWPORT_MODELS["union"] = "ltx-2.5-22b-ic-lora-layout-to-render-1.0.safetensors"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _sha(value, label):
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise ValueError(f"{label} needs an actual SHA-256 digest.")
    return value


def _asset(asset, label):
    if not isinstance(asset, dict) or not isinstance(asset.get("file"), str) or not asset["file"]:
        raise ValueError(f"Choose a valid {label}.")
    _sha(asset.get("sha"), label)
    return {"file": asset["file"], "sha": asset["sha"]}


def build_plan(project, *, scenario, timeline, models, text_encoder_inputs,
               model_pins, approval_key, original_audio_sha=None,
               union_downscale_factor=None):
    """Return serial native API phases plus dependency/artifact specifications.

    Call Studio's assert_approved/check_asset before this function. ``timeline``
    is the verified reviewed interval: frames, fps, width, height, has_audio.
    ``model_pins`` contains caller-verified file stamps/digests for every model
    and detector; no model payload is read here. ``approval_key`` must be the
    freshly computed Studio preparation key, not the remembered approval.
    ``timeline.source_has_audio`` describes the raw source container, before
    an optional soundtrack replaced its reviewed audio. ``original_audio_sha``
    identifies that raw source container. A selected soundtrack with no new
    performance affects delivery only in original mode.
    """
    if project.get("config", {}).get("viewport_render"):
        if union_downscale_factor is None:
            union_downscale_factor = 1
        return build_viewport_plan(project, scenario=scenario, timeline=timeline,
                                   models=models, text_encoder_inputs=text_encoder_inputs,
                                   model_pins=model_pins, approval_key=approval_key,
                                   union_downscale_factor=union_downscale_factor)
    if union_downscale_factor is None:
        union_downscale_factor = 2
    if scenario not in ("original", "replacement", "silent"):
        raise ValueError("Choose original performance, replacement speech or silence.")
    if not approval_key or project.get("approval") != approval_key or not project.get("review"):
        raise ValueError("Approve the current source selection before animating.")
    if (not project.get("opening_key") or
            project.get("opening_approval") != project["opening_key"]):
        raise ValueError("Approve the current opening appearance before animating.")
    c = project["config"]
    objects = c.get("subject_mode") == "objects"
    namespace = (project.get("ltx25_run") or {}).get("namespace")
    if not isinstance(namespace, str) or not re.fullmatch(r"[a-f0-9]{32}", namespace):
        raise ValueError("Start a new LTX render to prepare its files safely.")
    if c.get("edit_area", "mask") != "scene":
        raise ValueError("This LTX body-guided route changes the whole scene. Masked background preservation is not supported here.")
    if union_downscale_factor != 2:
        raise ValueError("The qualified Union adapter requires verified reference_downscale_factor 2.")
    source = _asset(project.get("source"), "source video")
    opening = _asset(project.get("opening_input"), "approved opening image")
    character = _asset(project.get("character"), "appearance reference")
    required_models = {"model", "video_vae", "audio_vae", "union", "upscaler", "bbox_detector", "pose_estimator"}
    if objects:
        required_models -= {"bbox_detector", "pose_estimator"}
    if set(models) != required_models or set(model_pins) != required_models | {"text_encoder"}:
        raise ValueError("Resolve and pin every LTX model, encoder and pose detector first.")
    if any(not isinstance(value, str) or not value for value in models.values()) or any(not value for value in model_pins.values()):
        raise ValueError("Model names and verified model pins cannot be empty.")
    if any(models[name] != QUALIFIED_MODELS[name] for name in required_models):
        raise ValueError("This bounded planner requires the qualified LTX 2.5 model, Union adapter, VAEs and pose detectors.")
    if not isinstance(text_encoder_inputs, dict) or not text_encoder_inputs.get("clip_name"):
        raise ValueError("Resolve the native LTX text encoder inputs first.")
    frames, fps = timeline.get("frames"), timeline.get("fps")
    if type(frames) is not int or frames < 1 or type(fps) not in (int, float) or not math.isfinite(fps) or fps != 24:
        raise ValueError("This bounded LTX recipe currently requires a verified 24 fps interval.")
    seconds = frames / fps
    if seconds > 5:
        raise ValueError("This LTX recipe supports up to five seconds. Longer continuation is not qualified yet.")
    width, height = timeline.get("width"), timeline.get("height")
    if type(width) is not int or type(height) is not int or min(width, height) < 1:
        raise ValueError("Verify the reviewed video's dimensions first.")
    resolution = c.get("resolution")
    if type(resolution) is not int or resolution not in (512, 768, 960, 1280, 1920):
        raise ValueError("Choose an LTX output resolution of at least 512 pixels.")
    seed = c.get("seed", 42)
    if type(seed) is not int or not 0 <= seed <= 2**53 - 1:
        raise ValueError("Choose a valid seed.")
    audio_start = c.get("audio_start", 0.0)
    if type(audio_start) not in (int, float) or not math.isfinite(audio_start) or audio_start < 0:
        raise ValueError("Choose a valid audio start time.")
    audio = None
    source_has_audio = timeline.get("source_has_audio", timeline.get("has_audio"))
    if type(source_has_audio) is not bool:
        raise ValueError("Verify whether the original source contains audio.")
    source_start = timeline.get("start", 0.0)
    if type(source_start) not in (int, float) or not math.isfinite(source_start) or source_start < 0:
        raise ValueError("Verify the selected original source start time.")
    if scenario == "replacement":
        audio = _asset(project.get("audio"), "replacement audio")
        audio_identity = {**audio, "start": audio_start}
    elif scenario == "original":
        if not source_has_audio and not project.get("audio"):
            raise ValueError("The source has no audio. Choose silence or provide replacement audio.")
        if project.get("audio"):
            audio = _asset(project["audio"], "selected soundtrack")
        audio_identity = {
            "generation": {"raw_source_sha": _sha(original_audio_sha or source["sha"], "original source"),
                           "start": source_start, "has_audio": source_has_audio},
            "delivery": {"selected": audio, "start": audio_start} if audio else {"original_reviewed_soundtrack": True},
        }
    else:
        audio_identity = {"kind": "zero_latent", "delivered_audio": False}
    padded = frames + (1 - frames) % 8
    scale = resolution / max(width, height)
    delivery = [max(2, 2 * round(width * scale / 2)), max(2, 2 * round(height * scale / 2))]
    # Stage 1 needs a multiple of 64 for the Union adapter's small-grid guide.
    base = [max(64, 64 * round(value / 128)) for value in delivery]
    native = [2 * value for value in base]
    prompt = str(c.get("prompt", "")).strip()
    direction = {
        "original": "Follow the source body, hand and facial performance, including its original mouth motion. The selected soundtrack does not direct a new facial performance.",
        "replacement": "Follow the source body and hand motion. Speak the supplied replacement audio naturally at its timing. Keep a resting mouth during silence; ignore the source mouth performance.",
        "silent": "Follow the source body and hand motion. The performer stays silent with a relaxed resting mouth; do not articulate speech.",
    }[scenario]
    if objects:
        direction = "Follow the source scene, camera movement, object placement and object motion."
    positive = "Match the approved opening appearance and scene. " + direction
    if prompt:
        positive += " " + prompt
    negative = "warped anatomy, sliding feet, flicker, extra people, text, subtitles"
    if objects:
        negative = "warped objects, drifting camera, flicker, text, subtitles"
    basis = {"schema": SCHEMA, "run_namespace": namespace, "scenario": scenario, "review": project["review"],
             "approval": approval_key, "opening_key": project["opening_key"],
             "source": source, "opening": opening, "character": character,
             "audio": audio_identity, "timeline": copy.deepcopy(timeline),
             "frames": frames, "delivery": delivery, "native": native, "base": base, "padded": padded,
             "seed": seed, "positive": positive, "negative": negative,
             "models": copy.deepcopy(models), "model_pins": copy.deepcopy(model_pins),
             "encoder": copy.deepcopy(text_encoder_inputs), "union_factor": 2,
             "sigmas": [STAGE1_SIGMAS, STAGE2_SIGMAS]}
    if objects:
        basis["guide_type"] = "canny_objects"
    key = digest(basis)
    keys = {name: digest({"plan": key, "artifact": name}) for name in
            ("text", "guided_text", "initial_video", "audio", "stage1_video", "upscaled_video", "stage2_video")}
    phases = {}
    dependencies = {}
    artifacts = {}

    def graph(phase):
        phases[phase] = {}
        dependencies[phase] = []
        return phases[phase]

    def node(g, name, typ, **inputs):
        g[name] = {"class_type": typ, "inputs": inputs}
        return [name, 0]

    def save(g, phase, name, link, kind="video"):
        identity = "save_" + name
        if kind == "video":
            node(g, identity, "ZuraSaveVideoLatentData", samples=link, cache_key=keys[name])
        elif kind == "text":
            node(g, identity, "GenjSaveTextConditioning", positive=link, negative=[link[0], 1], cache_key=keys[name])
        else:
            node(g, identity, "SaveLatent", samples=link, filename_prefix="zura/ltx25/" + key + "/" + name)
        artifacts[name] = {"phase": phase, "node": identity, "kind": kind, "key": keys[name]}

    def load(g, phase, name):
        dependencies[phase].append(name)
        kind = artifacts[name]["kind"]
        typ = {"video": "ZuraLoadVideoLatentData", "text": "GenjLoadTextConditioning", "audio": "LoadLatent",
               "images": "VHS_LoadImagesPath"}[kind]
        inputs = ({"directory": "__UNBOUND__", "image_load_cap": frames, "skip_first_images": 0,
                   "select_every_nth": 1} if kind == "images" else
                  {"latent": "__UNBOUND__"} if kind == "audio" else {"cache_key": keys[name]})
        if kind == "video":
            inputs["cache_digest"] = "__UNBOUND__"
        return node(g, "load_" + name, typ, **inputs)

    def source_video(g):
        return node(g, "source", "GenjLoadReviewedShot", shot_id=project["review"],
                    approved_shot_id=project["review"], render_long_edge=max(base),
                    output_scale=1, preview_seconds=0)

    g = graph("text")
    encoder = node(g, "encoder", "CLIPLoader", **text_encoder_inputs)
    p = node(g, "positive", "CLIPTextEncode", clip=encoder, text=positive)
    n = node(g, "negative", "CLIPTextEncode", clip=encoder, text=negative)
    # Save receives two encoders, unlike later paired guide output.
    node(g, "save_text", "GenjSaveTextConditioning", positive=p, negative=n, cache_key=keys["text"])
    artifacts["text"] = {"phase": "text", "node": "save_text", "kind": "text", "key": keys["text"]}

    g = graph("motion")
    src = source_video(g)
    components = node(g, "source_components", "GetVideoComponents", video=src)
    if objects:
        pose = node(g, "pose", "Canny", image=components, low_threshold=.1, high_threshold=.2)
    else:
        pose = node(g, "pose", "DWPreprocessor", image=components, detect_body="enable", detect_hand="enable",
                    detect_face="enable" if scenario == "original" else "disable", resolution=512,
                    scale_stick_for_xinsr_cn="disable", bbox_detector=models["bbox_detector"], pose_estimator=models["pose_estimator"])
    pose = node(g, "pose_fit", "ResizeImageMaskNode", input=pose, resize_type="match size",
                scale_method="lanczos", **{"resize_type.match": components, "resize_type.crop": "center"})
    pose_prefix = "zura/ltx25/" + key + "/pose/frame"
    node(g, "save_pose", "SaveImage", images=pose, filename_prefix=pose_prefix)
    # The reviewed loader rounds the resized source raster to multiples of 64.
    pose_scale = max(base) / max(width, height)
    pose_raster = [max(64, 64 * round(value * pose_scale / 64)) for value in (width, height)]
    artifacts["pose"] = {"phase": "motion", "node": "save_pose", "kind": "images",
                         "prefix": pose_prefix, "frames": frames, "raster": pose_raster}
    audio_vae = node(g, "audio_vae", "VAELoader", vae_name=models["audio_vae"])
    if scenario == "silent" or scenario == "original" and not source_has_audio:
        encoded = node(g, "zero_audio", "LTXVEmptyLatentAudio", frames_number=padded, frame_rate=fps, batch_size=1, audio_vae=audio_vae)
    else:
        av_source = src
        if scenario == "replacement":
            selected = node(g, "selected_audio", "LoadAudio", audio=audio["file"])
            av_source = node(g, "apply_audio", "GenjApplyReferenceAudio", video=src, clip_details=["source", 3],
                             audio=selected, audio_start_seconds=audio_start)
        else:
            # The reviewed video may already carry the selected soundtrack.
            # Read the real original audio independently to retain performance.
            original = node(g, "original_audio", "LoadAudio", audio=source["file"])
            original = node(g, "original_audio_interval", "TrimAudioDuration", audio=original,
                            start_index=float(source_start), duration=seconds)
            av_source = node(g, "original_audio_video", "CreateVideo", images=components,
                             fps=fps, audio=original, bit_depth=8, color_space="sRGB", codec="none")
        padded_source = node(g, "pad_source", "GenjLTXFramePad", video=av_source)
        av = node(g, "audio_components", "GetVideoComponents", video=padded_source)
        encoded = node(g, "encode_audio", "LTXVAudioVAEEncode", audio=[av[0], 1], audio_vae=audio_vae)
    save(g, "motion", "audio", encoded, "audio")

    g = graph("prepare")
    raw_text = load(g, "prepare", "text")
    cond = node(g, "conditioning", "LTXVConditioning", positive=raw_text, negative=[raw_text[0], 1], frame_rate=fps)
    pose = load(g, "prepare", "pose")
    if padded != frames:
        tail = node(g, "pose_tail", "ImageFromBatch", image=pose, batch_index=frames - 1, length=1)
        for index in range(padded - frames):
            pose = node(g, "pose_pad_" + str(index), "ImageBatch", image1=pose, image2=tail)
    vae = node(g, "video_vae", "VAELoader", vae_name=models["video_vae"])
    image = node(g, "opening", "LoadImage", image=opening["file"])
    image = node(g, "preprocess", "LTXVPreprocess", image=image, img_compression=18)
    initial = node(g, "empty_video", "EmptyLTXVLatentVideo", width=base[0], height=base[1], length=padded, batch_size=1)
    initial = node(g, "first_frame", "LTXVImgToVideoInplace", image=image, vae=vae, latent=initial, strength=.7, bypass=False)
    guided = node(g, "guide", "LTXAddVideoICLoRAGuideAdvanced", positive=cond, negative=[cond[0], 1],
                  vae=vae, latent=initial, image=pose, frame_idx=0, strength=1, latent_downscale_factor=2,
                  crop="disabled", use_tiled_encode=True, tile_size=256, tile_overlap=64, attention_strength=1)
    save(g, "prepare", "guided_text", guided, "text")
    save(g, "prepare", "initial_video", [guided[0], 2])
    encoded = load(g, "prepare", "audio")

    def sample(phase, video_name, text_name, union):
        g = graph(phase)
        text = load(g, phase, text_name)
        cond = text if union else node(g, "conditioning", "LTXVConditioning", positive=text, negative=[text[0], 1], frame_rate=fps)
        video = load(g, phase, video_name)
        aud = load(g, phase, "audio")
        mask = node(g, "audio_mask", "SolidMask", value=0., width=1024, height=1024)
        frozen = node(g, "frozen_audio", "SetLatentNoiseMask", samples=aud, mask=mask)
        av = node(g, "concat", "LTXVConcatAVLatent", video_latent=video, audio_latent=frozen)
        model = node(g, "model", "UNETLoader", unet_name=models["model"], weight_dtype="default")
        if union:
            model = node(g, "union", "LTXICLoRALoaderModelOnly", model=model, lora_name=models["union"], strength_model=1)
        guider = node(g, "guider", "CFGGuider", model=model, positive=cond, negative=[cond[0], 1], cfg=1)
        noise = node(g, "noise", "RandomNoise", noise_seed=seed)
        sampler = node(g, "sampler", "KSamplerSelect", sampler_name="euler_ancestral" if union else "euler")
        sigmas = node(g, "sigmas", "ManualSigmas", sigmas=STAGE1_SIGMAS if union else STAGE2_SIGMAS)
        sampled = node(g, "sample", "SamplerCustomAdvanced", noise=noise, guider=guider, sampler=sampler, sigmas=sigmas, latent_image=av)
        separated = node(g, "separate", "LTXVSeparateAVLatent", av_latent=sampled)
        if union:
            separated = [node(g, "crop_guides", "LTXVCropGuides", positive=cond, negative=[cond[0], 1], latent=separated)[0], 2]
        save(g, phase, "stage1_video" if union else "stage2_video", separated)

    sample("sample", "initial_video", "guided_text", True)
    # Native Union guides contain signed sentinel masks. The generic video
    # data cache deliberately permits only [0, 1], and SaveLatent drops masks.
    # Keep native guide preparation and Stage 1 sampling together instead of
    # changing, clamping or accidentally discarding those model semantics.
    preparation = phases.pop("prepare")
    sampling = phases.pop("sample")
    preparation.pop("save_initial_video")
    preparation.pop("save_guided_text")
    for identity in ("load_initial_video", "load_guided_text", "load_audio"):
        sampling.pop(identity)
    def rewire(value):
        if isinstance(value, list):
            if len(value) == 2 and value[0] == "load_initial_video":
                return ["guide", 2]
            if len(value) == 2 and value[0] == "load_guided_text":
                return ["guide", value[1]]
            if len(value) == 2 and value[0] == "load_audio":
                return encoded
            return [rewire(item) for item in value]
        if isinstance(value, dict):
            return {name: rewire(item) for name, item in value.items()}
        return value
    phases["stage1"] = {**preparation, **rewire(sampling)}
    stage1_dependencies = dependencies.pop("prepare")
    dependencies.pop("sample")
    dependencies["stage1"] = stage1_dependencies
    artifacts.pop("initial_video")
    artifacts.pop("guided_text")
    artifacts["stage1_video"]["phase"] = "stage1"
    g = graph("upscale")
    video = load(g, "upscale", "stage1_video")
    vae = node(g, "video_vae", "VAELoader", vae_name=models["video_vae"])
    upscaler = node(g, "upscaler", "LatentUpscaleModelLoader", model_name=models["upscaler"])
    video = node(g, "upscale", "LTXVLatentUpsampler", samples=video, upscale_model=upscaler, vae=vae)
    image = node(g, "opening", "LoadImage", image=opening["file"])
    image = node(g, "preprocess", "LTXVPreprocess", image=image, img_compression=18)
    video = node(g, "first_frame", "LTXVImgToVideoInplace", image=image, vae=vae, latent=video, strength=1., bypass=False)
    save(g, "upscale", "upscaled_video", video)
    sample("refine", "upscaled_video", "text", False)

    g = graph("decode")
    video = load(g, "decode", "stage2_video")
    vae = node(g, "video_vae", "VAELoader", vae_name=models["video_vae"])
    images = node(g, "decode", "VAEDecodeTiled", samples=video, vae=vae, tile_size=256, overlap=64, temporal_size=128, temporal_overlap=8)
    images = node(g, "trim_frames", "ImageFromBatch", image=images, batch_index=0, length=frames)
    images = node(g, "delivery_size", "ImageScale", image=images, width=delivery[0], height=delivery[1], upscale_method="lanczos", crop="disabled")
    inputs = {"images": images, "fps": fps, "bit_depth": 8, "color_space": "sRGB", "codec": "none"}
    if scenario != "silent":
        src = source_video(g)
        if audio is not None:
            selected = node(g, "selected_audio", "LoadAudio", audio=audio["file"])
            src = node(g, "apply_audio", "GenjApplyReferenceAudio", video=src, clip_details=["source", 3], audio=selected, audio_start_seconds=audio_start)
        components = node(g, "source_components", "GetVideoComponents", video=src)
        inputs["audio"] = node(g, "trim_audio", "TrimAudioDuration", audio=[components[0], 1], start_index=0., duration=seconds)
    video = node(g, "create_video", "CreateVideo", **inputs)
    node(g, "save_video", "SaveVideo", video=video, filename_prefix="zura/ltx25/" + key + "/result",
         format="mp4", **{"format.codec": "h264", "format.codec.encoding": "re-encode", "format.codec.encoding.crf": 16.})
    return {"schema": SCHEMA, "key": key, "scenario": scenario, "basis": basis,
            "phases": {phase: phases[phase] for phase in PHASES}, "dependencies": dependencies, "artifacts": artifacts,
            "scope": "whole_scene", "background_preservation": False,
            "generation_audio": ("zero" if scenario == "silent" or scenario == "original" and not source_has_audio else
                                 "replacement" if scenario == "replacement" else "raw_original"),
            "delivery_audio": "none" if scenario == "silent" else "selected_soundtrack" if scenario == "original" and audio else
                              "replacement" if scenario == "replacement" else "original",
            "stage1_vae_sampling_split": False,
            "motion_preparation_split": True,
            "stage1_handoff": "Native guide preparation and sampling stay together to retain signed Union mask sentinels. Only the cropped ordinary video latent is cached.",
            "qualification": "Native replacement-speech recipe basis; new assets, scenarios and delivery rasters require visual testing.",
            "graph_hashes": {phase: digest(value) for phase, value in phases.items()}}


def build_viewport_plan(project, *, scenario, timeline, models, text_encoder_inputs,
                        model_pins, approval_key, union_downscale_factor=1):
    """Plan the native LTX 2.5 Layout-to-Render viewport route.

    The approved opening must be a composed final scene plate. It is an
    appearance reference at RoPE -1, never an I2V frame or a character sheet.
    Layout guidance is retained in BOTH sampling stages and cropped before
    caching/upscaling. This experimental route needs a real visual qualification.
    """
    c = project["config"]
    if scenario not in ("silent", "original"):
        raise ValueError("Viewport rendering supports silence or the original soundtrack. Replacement speech is not qualified with Layout-to-Render yet.")
    if not approval_key or project.get("approval") != approval_key or not project.get("review"):
        raise ValueError("Approve the current source selection before animating.")
    if not project.get("opening_key") or project.get("opening_approval") != project["opening_key"]:
        raise ValueError("Approve the composed final scene appearance before animating.")
    if c.get("edit_area", "mask") != "scene":
        raise ValueError("Viewport rendering changes the whole scene; choose whole scene.")
    namespace = (project.get("ltx25_run") or {}).get("namespace")
    if not isinstance(namespace, str) or not re.fullmatch(r"[a-f0-9]{32}", namespace):
        raise ValueError("Start a new LTX render to prepare its files safely.")
    source = _asset(project.get("source"), "viewport video")
    look = _asset(project.get("opening_input"), "approved composed scene plate")
    expected_models = VIEWPORT_MODELS
    expected_pins = set(expected_models) | {"text_encoder"}
    if models != expected_models or set(model_pins) != expected_pins or any(not v for v in model_pins.values()):
        raise ValueError("Resolve and pin the LTX 2.5 Layout-to-Render model, adapter, encoder and VAEs first.")
    if union_downscale_factor != 1:
        raise ValueError("The LTX 2.5 Layout-to-Render adapter requires guide downscale factor 1.")
    if not isinstance(text_encoder_inputs, dict) or not text_encoder_inputs.get("clip_name"):
        raise ValueError("Resolve the native LTX text encoder inputs first.")
    source_frames, fps = timeline.get("frames"), timeline.get("fps")
    if type(source_frames) is not int or source_frames < 9 or type(fps) not in (int, float) or fps != 24:
        raise ValueError("Viewport rendering requires at least nine verified frames at 24 fps.")
    if source_frames > 360:
        raise ValueError("Viewport rendering currently supports up to fifteen seconds per shot.")
    # Layout-to-Render requires 8k+1 frames. Pad the guide's final frame for
    # sampling, then trim delivery back to the exact reviewed interval.
    frames = source_frames
    padded = frames + (1 - frames) % 8
    width, height = timeline.get("width"), timeline.get("height")
    if type(width) is not int or type(height) is not int or min(width, height) < 1:
        raise ValueError("Verify the viewport video's dimensions first.")
    resolution, seed = c.get("resolution"), c.get("seed", 42)
    if type(resolution) is not int or resolution not in (512, 768, 960, 1280, 1920):
        raise ValueError("Choose an LTX output resolution of at least 512 pixels.")
    if type(seed) is not int or not 0 <= seed <= 2**53 - 1:
        raise ValueError("Choose a valid seed.")
    has_audio = timeline.get("has_audio")
    if type(has_audio) is not bool:
        raise ValueError("Verify whether the reviewed source contains audio.")
    if scenario == "original" and not has_audio:
        raise ValueError("The source has no audio. Choose silence for viewport rendering.")
    delivery = [max(2, 2 * round(v * resolution / max(width, height) / 2)) for v in (width, height)]
    # Keep the 16:9 layout route at the tested 960x544 -> 1920x1088 raster.
    base = [max(32, 32 * round(v / 64)) for v in delivery]
    native = [2 * v for v in base]
    positive = ("Render the complete scene in the appearance of the approved scene reference. "
                "Follow the guide camera movement, framing, timing, object placement and animation throughout. "
                + str(c.get("prompt", "")).strip())
    negative = "flicker, sliding feet, warped anatomy, text, subtitles"
    basis = {"schema": SCHEMA, "route": "viewport_layout_to_render", "recipe_version": 2,
             "run_namespace": namespace,
             "scenario": scenario, "review": project["review"], "approval": approval_key,
             "opening_key": project["opening_key"], "source": source, "opening": look,
             "timeline": copy.deepcopy(timeline), "frames": padded, "padded": padded,
             "source_frames": source_frames,
             "delivery": delivery, "base": base, "native": native, "seed": seed,
             "positive": positive, "negative": negative, "models": copy.deepcopy(models),
             "model_pins": copy.deepcopy(model_pins), "encoder": copy.deepcopy(text_encoder_inputs),
             "audio": {"generation": "silent", "delivery": scenario},
             "sigmas": [STAGE1_SIGMAS, STAGE2_SIGMAS]}
    key = digest(basis)
    phases, dependencies, artifacts = {}, {}, {}

    def graph(phase):
        phases[phase], dependencies[phase] = {}, []
        return phases[phase]

    def node(g, name, typ, **inputs):
        g[name] = {"class_type": typ, "inputs": inputs}
        return [name, 0]

    def save(g, phase, name, value, kind="video"):
        cache_key = digest({"plan": key, "artifact": name})
        node(g, "save_" + name, "ZuraSaveVideoLatentData", samples=value, cache_key=cache_key)
        artifacts[name] = {"phase": phase, "node": "save_" + name, "kind": kind, "key": cache_key}

    def load(g, phase, name):
        spec = artifacts[name]
        dependencies[phase].append(name)
        if spec["kind"] == "images":
            return node(g, "load_" + name, "VHS_LoadImagesPath", directory="__UNBOUND__",
                        image_load_cap=padded, skip_first_images=0, select_every_nth=1)
        typ = "GenjLoadTextConditioning" if spec["kind"] == "text" else "ZuraLoadVideoLatentData"
        args = {"cache_key": spec["key"]}
        if spec["kind"] == "video":
            args["cache_digest"] = "__UNBOUND__"
        return node(g, "load_" + name, typ, **args)

    def reviewed(g):
        return node(g, "source", "GenjLoadReviewedShot", shot_id=project["review"],
                    approved_shot_id=project["review"], render_long_edge=max(base), output_scale=1, preview_seconds=0)

    g = graph("text")
    encoder = node(g, "encoder", "CLIPLoader", **text_encoder_inputs)
    p = node(g, "positive", "CLIPTextEncode", clip=encoder, text=positive)
    n = node(g, "negative", "CLIPTextEncode", clip=encoder, text=negative)
    text_key = digest({"plan": key, "artifact": "text"})
    node(g, "save_text", "GenjSaveTextConditioning", positive=p, negative=n, cache_key=text_key)
    artifacts["text"] = {"phase": "text", "node": "save_text", "kind": "text", "key": text_key}
    g = graph("motion")
    padded_source = node(g, "pad_source", "GenjLTXFramePad", video=reviewed(g))
    components = node(g, "components", "GetVideoComponents", video=padded_source)
    images = node(g, "trim_layout", "ImageFromBatch", image=components, batch_index=0, length=padded)
    images = node(g, "fit_layout", "ImageScale", image=images, width=base[0], height=base[1], upscale_method="lanczos", crop="disabled")
    prefix = "zura/ltx25/" + key + "/layout/frame"
    node(g, "save_layout", "SaveImage", images=images, filename_prefix=prefix)
    artifacts["layout"] = {"phase": "motion", "node": "save_layout", "kind": "images",
                           "prefix": prefix, "frames": padded, "raster": base, "guide": "raw_layout"}

    def sample(phase, raster, initial_name=None):
        g = graph(phase)
        text = load(g, phase, "text")
        cond = node(g, "conditioning", "LTXVConditioning", positive=text, negative=[text[0], 1], frame_rate=fps)
        vae = node(g, "video_vae", "VAELoader", vae_name=models["video_vae"])
        model = node(g, "model", "UNETLoader", unet_name=models["model"], weight_dtype="default")
        adapter = node(g, "layout_adapter", "LTXICLoRALoaderModelOnly", model=model,
                       lora_name=models["union"], strength_model=1)
        adapter_factor = [adapter[0], 1]
        latent = load(g, phase, initial_name) if initial_name else node(g, "empty_video", "EmptyLTXVLatentVideo", width=raster[0], height=raster[1], length=padded, batch_size=1)
        layout = load(g, phase, "layout")
        layout = node(g, "fit_layout", "ImageScale", image=layout, width=raster[0], height=raster[1], upscale_method="lanczos", crop="disabled")
        look_image = node(g, "look", "LoadImage", image=look["file"])
        # Match the dedicated Layout-to-Render graph: full-canvas guide VAE
        # encoding on both stages. Decode tiling must not change guide latents.
        guided = node(g, "layout_guide", "LTXAddVideoICLoRAGuide", positive=cond, negative=[cond[0], 1],
                      vae=vae, latent=latent, image=layout, frame_idx=0, strength=1, latent_downscale_factor=adapter_factor,
                      crop="disabled", use_tiled_encode=False, tile_size=256, tile_overlap=64)
        guided = node(g, "appearance_guide", "LTXAddVideoICLoRAGuide", positive=guided, negative=[guided[0], 1],
                      vae=vae, latent=[guided[0], 2], image=look_image, frame_idx=-1, strength=1,
                      latent_downscale_factor=adapter_factor, crop="center", use_tiled_encode=False, tile_size=256, tile_overlap=64)
        audio_vae = node(g, "audio_vae", "VAELoader", vae_name=models["audio_vae"])
        audio = node(g, "zero_audio", "LTXVEmptyLatentAudio", frames_number=padded, frame_rate=fps, batch_size=1, audio_vae=audio_vae)
        av = node(g, "concat", "LTXVConcatAVLatent", video_latent=[guided[0], 2], audio_latent=audio)
        guider = node(g, "guider", "CFGGuider", model=adapter, positive=guided, negative=[guided[0], 1], cfg=1)
        noise = node(g, "noise", "RandomNoise", noise_seed=seed)
        sampler = node(g, "sampler", "KSamplerSelect", sampler_name="euler_ancestral")
        sigmas = node(g, "sigmas", "ManualSigmas", sigmas=STAGE1_SIGMAS if phase == "stage1" else STAGE2_SIGMAS)
        output = node(g, "sample", "SamplerCustomAdvanced", noise=noise, guider=guider, sampler=sampler, sigmas=sigmas, latent_image=av)
        video = node(g, "separate", "LTXVSeparateAVLatent", av_latent=output)
        cropped = node(g, "crop_guides", "LTXVCropGuides", positive=guided, negative=[guided[0], 1], latent=video)
        save(g, phase, "stage1_video" if phase == "stage1" else "stage2_video", [cropped[0], 2])

    sample("stage1", base)
    g = graph("upscale")
    video = load(g, "upscale", "stage1_video")
    vae = node(g, "video_vae", "VAELoader", vae_name=models["video_vae"])
    upscaler = node(g, "upscaler", "LatentUpscaleModelLoader", model_name=models["upscaler"])
    video = node(g, "upscale", "LTXVLatentUpsampler", samples=video, upscale_model=upscaler, vae=vae)
    save(g, "upscale", "upscaled_video", video)
    sample("refine", native, "upscaled_video")
    g = graph("decode")
    video = load(g, "decode", "stage2_video")
    vae = node(g, "video_vae", "VAELoader", vae_name=models["video_vae"])
    images = node(g, "decode", "VAEDecodeTiled", samples=video, vae=vae, tile_size=256, overlap=64, temporal_size=128, temporal_overlap=8)
    images = node(g, "trim_frames", "ImageFromBatch", image=images, batch_index=0, length=source_frames)
    images = node(g, "delivery_size", "ImageScale", image=images, width=delivery[0], height=delivery[1], upscale_method="lanczos", crop="disabled")
    args = {"images": images, "fps": fps, "bit_depth": 8, "color_space": "sRGB", "codec": "none"}
    if scenario == "original":
        components = node(g, "source_components", "GetVideoComponents", video=reviewed(g))
        args["audio"] = node(g, "trim_audio", "TrimAudioDuration", audio=[components[0], 1], start_index=0., duration=source_frames / fps)
    video = node(g, "create_video", "CreateVideo", **args)
    node(g, "save_video", "SaveVideo", video=video, filename_prefix="zura/ltx25/" + key + "/result",
         format="mp4", **{"format.codec": "h264", "format.codec.encoding": "re-encode", "format.codec.encoding.crf": 16.})
    return {"schema": SCHEMA, "key": key, "scenario": scenario, "basis": basis,
            "phases": {phase: phases[phase] for phase in PHASES}, "dependencies": dependencies, "artifacts": artifacts,
            "scope": "whole_scene", "background_preservation": False, "generation_audio": "zero",
            "delivery_audio": "original" if scenario == "original" else "none",
            "stage1_vae_sampling_split": False, "motion_preparation_split": True,
            "stage1_handoff": "Layout and appearance guides remain native and are cropped before caching.",
            "qualification": "Experimental viewport route; current-media visual testing required.",
            "source_frames": source_frames, "generation_frames": padded,
            "delivered_frames": source_frames, "trimmed_tail_frames": 0,
            "appearance_reference_role": "composed_scene_plate_at_rope_minus_one",
            "graph_hashes": {phase: digest(value) for phase, value in phases.items()}}


def image_sequence_receipt(spec, history, *, output_directory):
    """Inspect the exact ordered native SaveImage outputs before a VHS handoff."""
    from PIL import Image
    root = Path(output_directory).resolve()
    prefix = Path(spec["prefix"])
    directory = (root / prefix.parent).resolve()
    if not directory.is_relative_to(root) or not directory.is_dir():
        raise ValueError("The motion frames are outside the output folder or missing.")
    outputs = history.get("outputs", {}).get(spec["node"], {}).get("images", [])
    if not isinstance(outputs, list) or len(outputs) != spec["frames"]:
        raise ValueError("The motion frame count does not match the selected clip.")
    entries, counters = [], []
    for item in outputs:
        if not isinstance(item, dict) or item.get("type") != "output":
            raise ValueError("Only native saved motion frames may guide LTX.")
        filename = item.get("filename", "")
        match = re.fullmatch(re.escape(prefix.name) + r"_(\d{5,})_\.png", filename)
        if not match or Path(item.get("subfolder", "")) != prefix.parent:
            raise ValueError("The motion frames do not match their native save location.")
        path = directory / filename
        if path.is_symlink() or not path.is_file() or path.resolve().parent != directory:
            raise ValueError("A motion frame is missing or outside its saved sequence.")
        value = file_digest(path)
        with Image.open(path) as image:
            if image.format != "PNG" or list(image.size) != spec["raster"]:
                raise ValueError("The motion frame dimensions do not match the reviewed clip.")
            image.verify()
        if file_digest(path) != value:
            raise ValueError("The motion frames changed during verification.")
        entries.append({"filename": filename, "sha256": value, "raster": spec["raster"]})
        counters.append(int(match[1]))
    names = [entry["filename"] for entry in entries]
    if (names != sorted(names) or len(set(names)) != len(names) or
            counters != list(range(counters[0], counters[0] + len(counters)))):
        raise ValueError("The native motion frames are duplicated or reordered.")
    # VHS reads the directory, so its entire contents must be this exact set.
    if set(path.name for path in directory.iterdir()) != set(names):
        raise ValueError("The motion sequence has missing or extra files.")
    return {"directory": str(directory), "files": entries, "sha256": digest(entries)}


def bind_phase(plan, phase, receipts, *, output_directory, input_directory):
    """Validate successful producer receipts and hash files before binding.

    A receipt includes plan_key, scenario, artifact, producer_graph_sha256,
    submitted_graph, prompt_id, history (one native history entry), path and
    sha256. Native LoadLatent additionally requires an input_filename and an
    input_path pointing to the byte-identical Comfy input copy. Caller freezes
    receipts privately and revalidates assets immediately before queueing.
    Directory arguments must be Comfy's actual configured directories.
    Text/LoadLatent nodes lack digest inputs: binding verifies their files, but
    filesystem mutation between binding and execution is not prevented here.
    """
    if (plan.get("schema") != SCHEMA or plan.get("key") != digest(plan.get("basis")) or
            phase not in PHASES or phase not in plan.get("phases", {})):
        raise ValueError("The native LTX plan is stale or malformed.")
    if plan.get("scenario") != plan["basis"].get("scenario"):
        raise ValueError("The native LTX scenario changed.")
    g = copy.deepcopy(plan["phases"][phase])
    if digest(g) != plan["graph_hashes"][phase]:
        raise ValueError("The planned graph changed. Rebuild its content keys first.")
    for name in plan["dependencies"][phase]:
        spec = plan["artifacts"][name]
        receipt = receipts.get(name, {})
        if any(receipt.get(field) != value for field, value in
               (("plan_key", plan["key"]), ("scenario", plan["scenario"]), ("artifact", name))):
            raise ValueError("A cache receipt belongs to another plan or scenario.")
        submitted = receipt.get("submitted_graph")
        producer_sha = receipt.get("producer_graph_sha256")
        history = receipt.get("history", {})
        prompt = history.get("prompt", [])
        if (not submitted or producer_sha != digest(submitted) or
                receipt.get("producer_phase") != spec["phase"] or
                history.get("status", {}).get("status_str") != "success" or
                history.get("status", {}).get("completed") is not True or
                len(prompt) < 3 or prompt[1] != receipt.get("prompt_id") or prompt[2] != submitted):
            raise ValueError("Only the exact successful native producer may supply this cache.")
        # Reconstruct every upstream handoff rather than trusting a receipt's
        # assertion that its graph came from this template.
        if receipt.get("template_graph_sha256") != plan["graph_hashes"][spec["phase"]]:
            raise ValueError("The producer was not bound from this plan's phase.")
        expected_producer = bind_phase(plan, spec["phase"], receipts,
                                       output_directory=output_directory, input_directory=input_directory)
        if submitted != expected_producer:
            raise ValueError("The producer's native controls or cache bindings changed.")
        expected_save = plan["phases"][spec["phase"]][spec["node"]]
        if submitted.get(spec["node"]) != expected_save:
            raise ValueError("The producer saved a different artifact.")
        if spec["kind"] == "images":
            inspected = image_sequence_receipt(spec, history, output_directory=output_directory)
            if any(receipt.get(field) != value for field, value in inspected.items()):
                raise ValueError("The motion sequence receipt is stale or changed.")
            g["load_" + name]["inputs"]["directory"] = inspected["directory"]
            continue
        actual_digest = _sha(receipt.get("sha256"), "cache")
        path = Path(receipt.get("path", ""))
        if not path.is_file() or file_digest(path) != actual_digest:
            raise ValueError("The native cache is missing or changed.")
        target = g["load_" + name]["inputs"]
        output_root = Path(output_directory).resolve()
        if spec["kind"] == "video":
            # Data nodes independently validate metadata, tensor schema and digest.
            if receipt.get("cache_key") != spec["key"] or path.name != spec["key"] + ".safetensors":
                raise ValueError("The video cache key does not match its producer.")
            expected_path = output_root / "zura" / "latent_data" / path.name
            if path.resolve() != expected_path.resolve() or not path.resolve().is_relative_to(output_root):
                raise ValueError("Verify the actual Comfy video cache file.")
            target["cache_digest"] = actual_digest
        elif spec["kind"] == "text":
            if path.name != spec["key"] + ".pt" or receipt.get("cache_key") != spec["key"]:
                raise ValueError("The text cache key does not match its producer.")
            expected_path = output_root / "genj" / "text_cache" / path.name
            if path.resolve() != expected_path.resolve() or not path.resolve().is_relative_to(output_root):
                raise ValueError("Verify the actual Comfy text cache file.")
        else:
            prefix = Path(expected_save["inputs"]["filename_prefix"])
            if (path.parent.resolve() != (output_root / prefix.parent).resolve() or
                    not path.resolve().is_relative_to(output_root) or
                    not re.fullmatch(re.escape(prefix.name) + r"_\d+_\.latent", path.name)):
                raise ValueError("The audio cache does not match its native save location.")
            filename = receipt.get("input_filename")
            input_path = Path(receipt.get("input_path", ""))
            if not isinstance(filename, str) or not filename or not input_path.is_file() or file_digest(input_path) != actual_digest:
                raise ValueError("Bind a verified byte-identical native audio latent input copy.")
            if Path(filename).is_absolute() or ".." in Path(filename).parts or input_path.name != Path(filename).name:
                raise ValueError("Use a contained Comfy input latent filename.")
            input_root = Path(input_directory).resolve()
            if input_path.resolve() != (input_root / filename).resolve() or not input_path.resolve().is_relative_to(input_root):
                raise ValueError("Verify the actual Comfy input latent copy.")
            native_outputs = history.get("outputs", {}).get(spec["node"], {}).get("latents", [])
            matched_output = False
            for item in native_outputs:
                if not isinstance(item, dict) or item.get("type") != "output":
                    continue
                candidate = output_root / item.get("subfolder", "") / item.get("filename", "")
                if candidate.resolve().is_relative_to(output_root) and candidate.resolve() == path.resolve():
                    matched_output = True
            if not matched_output:
                raise ValueError("The audio cache is not this successful native SaveLatent output.")
            target["latent"] = filename
    return g
