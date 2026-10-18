"""Native Comfy graph for Wan Animate 2 full-frame motion transfer.

The Studio adapter exposes a setup-gated full-frame option. Wan
Animate 2 transfers a driving video's motion to a reference character while
generating a new scene from text; it is not an object-swap node and exposes no
spatial mask. The node's internal anchor mask is part of its model conditioning
and cannot be used to constrain arbitrary image regions.

The graph follows Comfy's distilled blueprint (10 LCM steps, CFG 1, shift 5,
simple scheduler) and pins the repacked checkpoint filenames. Its bounded
route limits output to 480p-class dimensions and 81 frames. The cache uses
CPU/int8 by default because the local 16 GB GPU cannot safely hold the model
and pose cache together. None of these choices have been performance- or
quality-validated on this workstation; the model weights were not installed
when this prototype was created.

References:
* https://github.com/Wan-Video/Wan-Animate-2
* https://arxiv.org/abs/2608.06009
* https://github.com/Comfy-Org/workflow_templates/blob/main/blueprints/motion_transfer_wan_animate_2_distilled.json
* https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_wan_animate2_distilled.json
* https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_wan.py
"""

from collections.abc import Mapping
from typing import Any


STUDIO_INTEGRATED = True

# Comfy-Org's repacked distilled workflow assets. These names are intentionally
# fixed so a graph cannot silently fall back to the older Wan2.2 Animate model.
MODEL_FILES = {
    "diffusion": "wan_animate_2_distill_int8_convrot.safetensors",
    "text_encoder": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    "clip_vision": "clip_vision_h.safetensors",
    "vae": "Wan2_1_VAE_bf16.safetensors",
}

DEFAULT_WIDTH = 832
DEFAULT_HEIGHT = 480
DEFAULT_FRAME_COUNT = 81
MAX_FRAME_COUNT = 81
MIN_FRAME_COUNT = 5
OUTPUT_FPS = 24.0
MAX_OUTPUT_PIXELS = DEFAULT_WIDTH * DEFAULT_HEIGHT
MAX_OUTPUT_SIDE = DEFAULT_WIDTH

# Distilled blueprint sampling settings: ModelSamplingSD3 shift=5,
# BasicScheduler simple/10/1.0, KSamplerSelect lcm and CFG=1.
DISTILLED_SAMPLING = {
    "shift": 5.0,
    "scheduler": "simple",
    "steps": 10,
    "denoise": 1.0,
    "sampler": "lcm",
    "cfg": 1.0,
}

OFFICIAL_NEGATIVE_PROMPT = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，"
    "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，"
    "画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，"
    "杂乱的背景，三条腿，背景人很多，倒着走"
)

# Fields consumed by the API graph. This contract is intentionally local and
# testable without connecting to a running ComfyUI server.
NATIVE_NODE_INPUTS = {
    "UNETLoader": {"unet_name", "weight_dtype"},
    "CLIPLoader": {"clip_name", "type", "device"},
    "CLIPVisionLoader": {"clip_name"},
    "VAELoader": {"vae_name"},
    "LoadImage": {"image"},
    "LoadVideo": {"file"},
    "GetVideoComponents": {"video"},
    "ImageFromBatch": {"image", "batch_index", "length"},
    "CLIPVisionEncode": {"clip_vision", "image", "crop"},
    "CLIPTextEncode": {"clip", "text"},
    "WanAnimate2ToVideo": {
        "positive", "negative", "vae", "width", "height", "length", "batch_size",
        "reference_image", "pose_video", "clip_vision_output", "positive_pose", "clip_vision_output_pose",
        "video_frame_offset", "pose_strength", "pose_start_percent", "pose_end_percent",
        "reference_image_strength",
    },
    "WanAnimate2Cache": {"model", "device", "dtype"},
    "ModelSamplingSD3": {"model", "shift"},
    "BasicScheduler": {"model", "scheduler", "steps", "denoise"},
    "KSamplerSelect": {"sampler_name"},
    "SamplerCustom": {
        "model", "add_noise", "noise_seed", "cfg", "positive", "negative", "sampler",
        "sigmas", "latent_image",
    },
    "TrimVideoLatent": {"samples", "trim_amount"},
    "VAEDecode": {"samples", "vae"},
    "CreateVideo": {"images", "fps"},
    "SaveVideo": {"video", "filename_prefix", "format"},
}


class WanAnimate2GraphError(ValueError):
    """Raised when a request exceeds the native, bounded Animate 2 path."""


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WanAnimate2GraphError(f"{name} must be a positive integer.")
    return value


def _asset_name(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise WanAnimate2GraphError(f"Choose a valid {name} file from ComfyUI's input list.")
    return value.strip()


def _node(graph: dict[str, dict[str, Any]], key: str, class_type: str, **inputs: Any) -> list[Any]:
    graph[key] = {"class_type": class_type, "inputs": inputs}
    return [key, 0]


def _validate_resolution(width: Any, height: Any) -> tuple[int, int]:
    width = _positive_int("width", width)
    height = _positive_int("height", height)
    if width % 16 or height % 16:
        raise WanAnimate2GraphError("Wan Animate 2 width and height must be multiples of 16.")
    if max(width, height) > MAX_OUTPUT_SIDE or width * height > MAX_OUTPUT_PIXELS:
        raise WanAnimate2GraphError(
            "This developer prototype is capped at 832×480-class output (480p). "
            "Use a smaller supported grid or wait for a separately validated higher-resolution path."
        )
    return width, height


def build_animate2_graph(
    reference_image: str,
    driving_video: str,
    prompt: str,
    frame_count: int = DEFAULT_FRAME_COUNT,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    *,
    motion_prompt: str | None = None,
    negative_prompt: str = OFFICIAL_NEGATIVE_PROMPT,
    seed: int = 0,
    cache_device: str = "cpu",
    spatial_mask: Any = None,
) -> dict[str, dict[str, Any]]:
    """Build a native Comfy API graph for whole-frame character motion transfer.

    ``reference_image`` and ``driving_video`` are filenames already uploaded to
    the ComfyUI input directory. The driving video is read as native video
    frames and truncated to ``frame_count`` before it reaches Animate 2. This
    graph creates a new full scene from the prompt; it does not preserve the
    driving video's background and cannot accept an object/character mask.
    """
    reference_image = _asset_name("reference image", reference_image)
    driving_video = _asset_name("driving video", driving_video)
    if not isinstance(prompt, str) or not prompt.strip() or "\x00" in prompt:
        raise WanAnimate2GraphError("Enter a prompt describing the character and generated scene.")
    if len(prompt) > 10_000:
        raise WanAnimate2GraphError("The prompt must be 10,000 characters or fewer.")
    if motion_prompt is not None and (
        not isinstance(motion_prompt, str) or not motion_prompt.strip() or "\x00" in motion_prompt
    ):
        raise WanAnimate2GraphError("If provided, the motion prompt must contain text.")
    if not isinstance(negative_prompt, str) or "\x00" in negative_prompt:
        raise WanAnimate2GraphError("The negative prompt must be text.")
    if spatial_mask is not None:
        raise WanAnimate2GraphError(
            "Wan Animate 2 has no native spatial-mask input. This prototype generates the full frame; "
            "it does not implement masked replacement or post-generation compositing."
        )
    frame_count = _positive_int("frame_count", frame_count)
    if frame_count < MIN_FRAME_COUNT or frame_count > MAX_FRAME_COUNT or (frame_count - 1) % 4:
        raise WanAnimate2GraphError(
            "Choose 5–81 frames on Wan Animate 2's native 4n+1 grid (5, 9, 13, …, 81)."
        )
    width, height = _validate_resolution(width, height)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 0xFFFFFFFFFFFFFFFF:
        raise WanAnimate2GraphError("Seed must be an unsigned 64-bit integer.")
    if cache_device not in ("cpu", "gpu"):
        raise WanAnimate2GraphError("Cache device must be 'cpu' or 'gpu'.")

    graph: dict[str, dict[str, Any]] = {}
    unet = _node(
        graph, "animate2_unet", "UNETLoader",
        unet_name=MODEL_FILES["diffusion"], weight_dtype="default",
    )
    clip = _node(
        graph, "animate2_text_encoder", "CLIPLoader",
        clip_name=MODEL_FILES["text_encoder"], type="wan", device="default",
    )
    clip_vision = _node(
        graph, "animate2_clip_vision", "CLIPVisionLoader", clip_name=MODEL_FILES["clip_vision"]
    )
    vae = _node(graph, "animate2_vae", "VAELoader", vae_name=MODEL_FILES["vae"])

    reference = _node(graph, "reference_image", "LoadImage", image=reference_image)
    source_video = _node(graph, "driving_video", "LoadVideo", file=driving_video)
    source_frames = _node(graph, "driving_video_frames", "GetVideoComponents", video=source_video)
    pose_frames = _node(
        graph, "pose_frames", "ImageFromBatch", image=source_frames,
        batch_index=0, length=frame_count,
    )
    pose_first_frame = _node(
        graph, "pose_first_frame", "ImageFromBatch", image=pose_frames,
        batch_index=0, length=1,
    )
    reference_vision = _node(
        graph, "reference_vision", "CLIPVisionEncode", clip_vision=clip_vision,
        image=reference, crop="none",
    )
    pose_vision = _node(
        graph, "pose_vision", "CLIPVisionEncode", clip_vision=clip_vision,
        image=pose_first_frame, crop="none",
    )
    positive = _node(graph, "positive_prompt", "CLIPTextEncode", clip=clip, text=prompt.strip())
    negative = _node(
        graph, "negative_prompt", "CLIPTextEncode", clip=clip, text=negative_prompt
    )

    animate_inputs: dict[str, Any] = {
        "positive": positive,
        "negative": negative,
        "vae": vae,
        "width": width,
        "height": height,
        "length": frame_count,
        "batch_size": 1,
        "reference_image": reference,
        "pose_video": pose_frames,
        "clip_vision_output": reference_vision,
        "clip_vision_output_pose": pose_vision,
        "video_frame_offset": 0,
        "pose_strength": 1.0,
        "pose_start_percent": 0.0,
        "pose_end_percent": 1.0,
        "reference_image_strength": 1.0,
    }
    if motion_prompt is not None:
        animate_inputs["positive_pose"] = _node(
            graph, "motion_prompt", "CLIPTextEncode", clip=clip, text=motion_prompt.strip()
        )
    animate = _node(graph, "animate2_conditioning", "WanAnimate2ToVideo", **animate_inputs)

    cached_model = _node(
        graph, "animate2_pose_cache", "WanAnimate2Cache",
        model=unet, device=cache_device, dtype="int8",
    )
    shifted_model = _node(
        graph, "animate2_sampling_shift", "ModelSamplingSD3",
        model=cached_model, shift=DISTILLED_SAMPLING["shift"],
    )
    sigmas = _node(
        graph, "animate2_sigmas", "BasicScheduler", model=shifted_model,
        scheduler=DISTILLED_SAMPLING["scheduler"], steps=DISTILLED_SAMPLING["steps"],
        denoise=DISTILLED_SAMPLING["denoise"],
    )
    sampler = _node(
        graph, "animate2_sampler", "KSamplerSelect", sampler_name=DISTILLED_SAMPLING["sampler"]
    )
    sampled = _node(
        graph, "animate2_sample", "SamplerCustom", model=shifted_model,
        add_noise=True, noise_seed=seed, cfg=DISTILLED_SAMPLING["cfg"],
        positive=["animate2_conditioning", 0], negative=["animate2_conditioning", 1],
        sampler=sampler, sigmas=sigmas, latent_image=["animate2_conditioning", 2],
    )
    trimmed = _node(
        graph, "animate2_trim_reference", "TrimVideoLatent",
        samples=sampled, trim_amount=["animate2_conditioning", 3],
    )
    decoded = _node(graph, "animate2_decode", "VAEDecode", samples=trimmed, vae=vae)
    video = _node(
        graph, "animate2_video", "CreateVideo", images=decoded, fps=OUTPUT_FPS
    )
    _node(
        graph, "animate2_save", "SaveVideo", video=video,
        filename_prefix="zura_dev/wan_animate2", format="auto",
    )
    return graph


def validate_native_schemas(object_info: Mapping[str, Any]) -> None:
    """Raise with missing native node/input details for a Comfy ``/object_info`` map."""
    if not isinstance(object_info, Mapping):
        raise WanAnimate2GraphError("Comfy object_info must be a node-name mapping.")
    errors: list[str] = []
    for node_name, expected_inputs in NATIVE_NODE_INPUTS.items():
        schema = object_info.get(node_name)
        if not isinstance(schema, Mapping):
            errors.append(f"missing native node {node_name}")
            continue
        input_schema = schema.get("input", {})
        if not isinstance(input_schema, Mapping):
            errors.append(f"{node_name} has no readable input schema")
            continue
        available: set[str] = set()
        for group_name in ("required", "optional", "hidden"):
            group = input_schema.get(group_name, {})
            if isinstance(group, Mapping):
                available.update(group)
        missing = sorted(expected_inputs - available)
        if missing:
            errors.append(f"{node_name} missing inputs: {', '.join(missing)}")
    if errors:
        raise WanAnimate2GraphError("Incompatible ComfyUI native schema: " + "; ".join(errors))


MODEL_FOLDERS = {"diffusion": "diffusion_models", "text_encoder": "text_encoders",
                 "clip_vision": "clip_vision", "vae": "vae"}
MODEL_DOWNLOADS = {key: ("https://huggingface.co/Comfy-Org/Wan-Animate-2/resolve/main/"
                         + MODEL_FOLDERS[key] + "/" + name) for key, name in MODEL_FILES.items()}
STUDIO_NODES = {"GenjSelectClip", "GenjLTXFramePad", "GetImageRangeFromBatch", "GenjRestoreSoundtrack"}


def _studio_selection(project, check_asset):
    """Read the actual selected interval, never infer frames from UI labels."""
    import av
    import math
    c = project["config"]
    source = check_asset(project["source"])
    with av.open(str(source)) as container:
        if not container.streams.video:
            raise WanAnimate2GraphError("Upload a video containing a video track.")
        stream = container.streams.video[0]
        available = (float(stream.duration * stream.time_base) if stream.duration is not None
                     else float((container.duration or 0) / av.time_base))
        source_width, source_height = stream.width, stream.height
    original = c.get("length_mode") == "original"
    start = 0. if original else float(c.get("start", 0.))
    duration = available if original else float(c.get("duration", 2.))
    if not all(math.isfinite(v) for v in (available, start, duration)) or start < 0 or duration <= 0 or start >= available:
        raise WanAnimate2GraphError("Choose a valid source interval.")
    duration = min(duration, available - start)
    frames = int(duration * OUTPUT_FPS + 1e-6)
    if not MIN_FRAME_COUNT <= frames <= MAX_FRAME_COUNT:
        raise WanAnimate2GraphError("Wan Animate 2 supports 5 to 81 frames at 24 fps (0.21 to 3.375 seconds). Choose a custom clip length.")
    if min(source_width, source_height) < 1:
        raise WanAnimate2GraphError("The source video's dimensions could not be read.")
    scale = min(1., MAX_OUTPUT_SIDE / max(source_width, source_height),
                math.sqrt(MAX_OUTPUT_PIXELS / (source_width * source_height)))
    width = max(16, int(source_width * scale) // 16 * 16)
    height = max(16, int(source_height * scale) // 16 * 16)
    _validate_resolution(width, height)
    return start, frames / OUTPUT_FPS, frames, width, height


def build_studio_graph(project, check_asset):
    """Build the full-frame route only; never enqueue or load model tensors.

    An approved opening look is the single appearance reference. The source
    drives performance and the original soundtrack is restored after rendering.
    This is not masked inpainting, audio-driven dubbing or viewport rendering.
    """
    c = project["config"]
    if c.get("engine") != "wan2" or c.get("workflow_mode") != "motion" or c.get("edit_area") != "scene":
        raise WanAnimate2GraphError("Choose Wan Animate 2 with full-frame character and background replacement.")
    if c.get("subject_mode", "auto") not in ("auto", "people") or c.get("task_mode", "character") != "character":
        raise WanAnimate2GraphError("Wan Animate 2 requires a human character performance.")
    if any(c.get(key) for key in ("audio_id", "lip_sync", "refine_lips", "preserve_people", "remove_text", "h3_head_swap")):
        raise WanAnimate2GraphError("Wan Animate 2 currently transfers the original performance and audio. New dialogue, text removal and masked edits are not supported.")
    reference = project.get("opening_input")
    if not reference or not project.get("opening_key") or project.get("opening_approval") != project.get("opening_key"):
        raise WanAnimate2GraphError("Generate or upload a finished starting frame, then approve it before creating the video.")
    check_asset(reference)
    start, duration, frames, width, height = _studio_selection(project, check_asset)
    model_frames = max(MIN_FRAME_COUNT, 1 + ((frames - 1 + 3) // 4) * 4)
    prompt = c.get("prompt", "").strip() or "Animate the character and scene from the reference image, preserving the source video's facial performance, body motion and camera timing."
    graph = build_animate2_graph(reference["file"], project["source"]["file"], prompt,
                                frame_count=model_frames, width=width, height=height,
                                seed=c.get("seed", 0), cache_device="cpu")
    graph["select"] = {"class_type": "GenjSelectClip", "inputs": {
        "video": ["driving_video", 0], "start_seconds": start, "duration_seconds": duration,
        "long_edge": MAX_OUTPUT_SIDE, "use_original_length": False}}
    # 8n+1 padding also satisfies the model's 4n+1 grid. pose_frames slices
    # away any padding beyond the exact requested model window.
    graph["pad_source"] = {"class_type": "GenjLTXFramePad", "inputs": {"video": ["select", 0]}}
    graph["driving_video_frames"]["inputs"]["video"] = ["pad_source", 0]
    graph["trim_output"] = {"class_type": "GetImageRangeFromBatch", "inputs": {
        "images": ["animate2_decode", 0], "start_index": 0, "num_frames": frames}}
    graph["animate2_video"]["inputs"]["images"] = ["trim_output", 0]
    del graph["animate2_save"]
    take = "studio_" + str(project["id"])[:8] + "_wan2"
    graph["wan2_export"] = {"class_type": "GenjRestoreSoundtrack", "inputs": {
        "video": ["animate2_video", 0], "clip_details": ["select", 1], "take_name": take}}
    return graph


def readiness(node_mappings, get_full_path):
    files = []
    for key, filename in MODEL_FILES.items():
        folder = MODEL_FOLDERS[key]
        try:
            present = bool(get_full_path(folder, filename))
        except (KeyError, FileNotFoundError):
            present = False
        files.append({"folder": folder, "filename": filename, "ready": present,
                      "url": MODEL_DOWNLOADS[key]})
    required = (set(NATIVE_NODE_INPUTS) - {"SaveVideo"}) | STUDIO_NODES
    missing = sorted(required - set(node_mappings))
    return {"ready": not missing and all(f["ready"] for f in files),
            "model_files": files, "missing_nodes": missing,
            "limits": {"fps": OUTPUT_FPS, "min_frames": MIN_FRAME_COUNT,
                       "max_frames": MAX_FRAME_COUNT, "max_seconds": MAX_FRAME_COUNT / OUTPUT_FPS,
                       "max_long_edge": MAX_OUTPUT_SIDE, "max_pixels": MAX_OUTPUT_PIXELS},
            "quality_verified_locally": False,
            "note": "Full-frame character and background replacement. Local output qualification is pending."}
