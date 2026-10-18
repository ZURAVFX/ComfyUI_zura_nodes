"""Head/face-swap recipe adapted from the artist's v3 graph.

Builds native API graphs only. Studio exposes the approved short audio recipe.
This route uses source-latent masking AND explicit crop compositing; it is not
the qualified full-frame character pipeline or a promise of native inpainting.
"""
from dataclasses import dataclass
import math
import re


MODELS = {
    "base": ("UNETLoader", "unet_name", "minimax_h3_ref2va_pruned_int8_convrot.safetensors"),
    "text": ("CLIPLoader", "clip_name", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"),
    "video_vae": ("VAELoader", "vae_name", "minimax_h3_video_vae_fp16.safetensors"),
    "audio_vae": ("VAELoader", "vae_name", "minimax_h3_audio_vae_fp32.safetensors"),
    "sam": ("CheckpointLoaderSimple", "ckpt_name", "sam3.1_multiplex_fp16.safetensors"),
    "background": ("LoadBackgroundRemovalModel", "bg_removal_name", "birefnet.safetensors"),
}
# Preserve the supplied combination for the first comparison. These are not
# face-identity LoRAs, and stacking them is not an established speed benchmark.
LORAS = (
    ("acceleration", "MiniMax-H3-FL2VA-Acc-8Step.safetensors", .75),
    ("taomate", "minimax_h3_taomate_3step_lora_avg_rank_19_bf16.safetensors", .5),
    ("turbo4", "minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors", .5),
    ("camera", "camera_motion_h3_lora_v1_1000_pruned.safetensors", .5),
)
SIGMA_CURVE = ('{"points":[[0,1,1],[1,1,1],[1,0,1]],"interpolation":"smooth",'
               '"tension":1,"endpointsLocked":true,"snapToSteps":true}')


@dataclass(frozen=True)
class HeadSwapRequest:
    source_video: str
    portrait_image: str
    source_has_audio: bool
    start_seconds: float = 0.
    duration_seconds: float = 2.
    seed: int = 2
    take_name: str = "zura_h3_head_swap_dev"
    selection_prompt: str = "face, glasses"
    object_indices: str = ""
    prompt: str = ""
    reference_size: str = "max"


def build_graph(request: HeadSwapRequest):
    """Adapt one short, continuous, original-audio shot; never submit it.

    Source selection normalises to 24 fps and a 1024-pixel long edge. Unlike
    the supplied graph, frame count comes from the selected batch, not a stale
    saved widget. Valid H3 temporal padding is trimmed after reassembly.
    Silence/new dialogue require independent qualification, so are excluded.
    """
    for name in ("source_video", "portrait_image", "selection_prompt"):
        if not isinstance(getattr(request, name), str) or not getattr(request, name).strip():
            raise ValueError(f"Provide {name}.")
    if request.source_has_audio is not True:
        raise ValueError("This head-swap comparison requires verified original audio. Silent footage and new dialogue are not qualified.")
    for name in ("start_seconds", "duration_seconds"):
        value = getattr(request, name)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"Provide a finite nonnegative {name}.")
    if not 5 <= int(request.duration_seconds * 24 + 1e-6) <= 120:
        raise ValueError("Select 5 to 120 frames at 24 fps, up to five seconds.")
    if type(request.seed) is not int or not 0 <= request.seed <= 2**64 - 1:
        raise ValueError("Provide an unsigned 64-bit seed.")
    if request.reference_size not in ("max", "match"):
        raise ValueError("Choose max or match reference sizing.")
    if not isinstance(request.prompt, str) or not isinstance(request.take_name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request.take_name):
        raise ValueError("Provide a text prompt and simple take name.")
    if not isinstance(request.object_indices, str) or not re.fullmatch(r"(?:\d+(?:,\d+)*)?", request.object_indices):
        raise ValueError("Use comma-separated tracked face indices, or leave blank.")
    graph = {}

    def node(key, kind, **inputs):
        graph[key] = {"class_type": kind, "inputs": inputs}
        return [key, 0]

    source = node("source", "LoadVideo", file=request.source_video)
    selected = node("select", "GenjSelectClip", video=source, start_seconds=request.start_seconds,
                    duration_seconds=request.duration_seconds, long_edge=1024, use_original_length=False)
    images = node("components", "GetVideoComponents", video=selected)
    audio = ["components", 1]
    node("source_size", "GetImageSize", image=images)
    # H3's VAE encodes whole 17-frame chunks after its first five frames.
    # Without padding, a 48-frame input decodes to only 39 frames. Repeat the
    # final source frame to the next valid length, then trim AFTER uncropping.
    images = node("pad", "LayerUtility: Pad Image Batch to 8n+1", images=images,
                  multiplier=17, remainder=5)
    sam = node("sam", "CheckpointLoaderSimple", ckpt_name=MODELS["sam"][2])
    face_text = node("face_text", "CLIPTextEncode", clip=["sam", 1], text=request.selection_prompt)
    track = node("track", "SAM3_VideoTrack", images=images, model=sam, conditioning=face_text,
                 detection_threshold=.5, max_objects=0, detect_interval=1)
    mask = node("face_mask", "SAM3_TrackToMask", track_data=track, object_indices=request.object_indices)
    crop = node("crop", "MVEx_SubjectCrop", original_images=images, masks=mask,
                divisible_by=32, upscale_megapixels=.35, resize_method="auto",
                **{"mode": "tracked", "mode.crop_scale": 1.5, "mode.padding": "firm",
                   "mode.prefer": "stillness", "mode.aspect_ratio": 0., "mode.seamless_loop": False})
    node("crop_size", "GetImageSize", image=crop)
    mask_image = node("mask_image", "MaskToImage", mask=mask)
    node("selection_preview", "PreviewImage", images=mask_image)
    node("crop_preview", "PreviewImage", images=crop)
    pose = node("face_motion", "DWPreprocessor", image=crop, detect_hand="disable", detect_body="enable",
                detect_face="enable", resolution=512, bbox_detector="yolox_l.onnx",
                pose_estimator="dw-ll_ucoco_384_bs5.torchscript.pt", scale_stick_for_xinsr_cn="disable")
    portrait = node("portrait", "LoadImage", image=request.portrait_image)
    portrait = node("portrait_half", "ImageScaleBy", image=portrait, upscale_method="lanczos", scale_by=.5)
    node("portrait_size", "GetImageSize", image=portrait)
    background = node("background_model", "LoadBackgroundRemovalModel", bg_removal_name=MODELS["background"][2])
    foreground = node("portrait_mask", "RemoveBackground", bg_removal_model=background, image=portrait)
    inverted = node("portrait_background", "InvertMask", mask=foreground)
    white = node("white", "EmptyImage", width=["portrait_size", 0], height=["portrait_size", 1], batch_size=1, color=16777215)
    portrait = node("portrait_white", "ImageCompositeMasked", destination=portrait, source=white,
                    mask=inverted, x=0, y=0, resize_source=True)
    model = node("model", "UNETLoader", unet_name=MODELS["base"][2], weight_dtype="default")
    model = node("attention", "ModelAttentionBackend", model=model, attention="comfy kitchen attention")
    for key, filename, strength in LORAS:
        model = node(key, "LoraLoaderModelOnly", model=model, lora_name=filename, strength_model=strength)
    raw_model = model
    model = node("shift", "MiniMaxH3SigmaShift", model=model, shift_video=12., shift_audio=1.5)
    clip = node("text", "CLIPLoader", clip_name=MODELS["text"][2], type="minimax", device="default")
    vae = node("video_vae", "VAELoader", vae_name=MODELS["video_vae"][2])
    audio_vae = node("audio_vae", "VAELoader", vae_name=MODELS["audio_vae"][2])
    mask = node("latent_mask", "NKDMaskOps", mask=["crop", 1], vae=vae, model=raw_model,
                invert=False, black_point=0., white_point=1., despeckle=2, fill_holes=False,
                close_gaps=0, temporal_expand=1, temporal_smooth=0, expand=30, blockify=0,
                blockify_threshold=.05, feather=0, edge_low=0., edge_high=1.)
    blend_mask = node("blend_mask", "NKDMaskOpsLean", mask=mask, fill_holes=False, expand=10, feather=20)
    prompt = ("<Subject 1> is the character represented in <Picture 1>. The video is a close up face of <Subject 1>. "
              "The target face must reproduce the original person's facial performance from <Video 1> "
              "while maintaining the target identity from <Picture 1>.\n\n"
              "<Video 1> Transfer the original person's: facial expressions, mouth opening and closing, "
              "lip shapes, jaw movement, cheek movement, eye movement, blinking, eyebrow movement, "
              "subtle facial muscle movement, head rotation, head tilt, facial timing and performance rhythm. "
              + request.prompt.strip())
    conditioning = node("references", "MiniMaxH3ReferenceToVideo", clip=clip, vae=vae, audio_vae=audio_vae,
                        prompt=prompt, width=["crop_size", 0], height=["crop_size", 1], length=["crop_size", 2],
                        ref_image_size=request.reference_size,
                        **{"ref_images.ref_image_0": portrait, "ref_videos.ref_video_0": pose})
    latent = node("source_latent", "NKDAVLatent", images=crop, audio=audio, video_vae=vae, audio_vae=audio_vae,
                  latent_mask=["latent_mask", 2], audio_mode="keep", fps=24., ramp_ticks=0, ramp_out_ticks=0, ramp_shape="cosine")
    guider = node("guider", "BasicGuider", model=model, conditioning=conditioning)
    noise = node("noise", "RandomNoise", noise_seed=request.seed)
    sampler = node("sampler", "KSamplerSelect", sampler_name="sa_solver_pece")
    sigmas = node("sigmas", "NKDSigmasCurve", curve_data=SIGMA_CURVE, steps=8, max_sigma=1.)
    samples = node("sample", "SamplerCustomAdvanced", noise=noise, guider=guider, sampler=sampler,
                   sigmas=sigmas, latent_image=latent)
    decoded = node("decode", "VAEDecode", samples=samples, vae=vae)
    decoded = node("trim", "GetImageRangeFromBatch", images=decoded, start_index=0, num_frames=["crop_size", 2])
    node("generated_face_preview", "PreviewImage", images=decoded)
    finished = node("uncrop", "MVEx_SubjectUncrop", cropped_images=decoded, original_images=images,
                    bboxes=["crop", 2], cropped_masks=blend_mask, feather=16, resize_method="auto")
    finished = node("trim_output", "GetImageRangeFromBatch", images=finished, start_index=0,
                    num_frames=["source_size", 2])
    video = node("video", "CreateVideo", images=finished, audio=audio, fps=24.)
    node("export", "GenjRestoreSoundtrack", video=video, clip_details=["select", 1], take_name=request.take_name)
    return graph


def _selection(project, check_asset):
    import av
    config = project["config"]
    source = check_asset(project["source"])
    with av.open(str(source)) as container:
        stream = container.streams.video[0]
        available = (float(stream.duration * stream.time_base) if stream.duration is not None
                     else float((container.duration or 0) / av.time_base))
        has_audio = bool(container.streams.audio)
    start = 0. if config.get("length_mode") == "original" else config["start"]
    duration = available if config.get("length_mode") == "original" else min(config["duration"], available - start)
    frames = int(duration * 24 + 1e-6) if math.isfinite(duration) else 0
    if not has_audio:
        raise ValueError("Head & face requires original audio. Use Full character for silent footage or new dialogue.")
    if not 5 <= frames <= 48:
        raise ValueError("Head & face is approved for 0.21 to 2 seconds. Choose a shorter custom clip.")
    return start, frames / 24, frames


def selected_frame_count(project, check_asset):
    return _selection(project, check_asset)[2]


def build_studio_graph(project, check_asset):
    from .availability import head_swap_setup
    if not head_swap_setup(project["config"]):
        raise ValueError("Choose the approved H3 Head & face setup with original audio.")
    refs = project.get("references") or ([project["character"]] if project.get("character") else [])
    if not refs:
        raise ValueError("Upload a portrait or character sheet for Head & face.")
    check_asset(refs[0])
    start, duration, _ = _selection(project, check_asset)
    config = project["config"]
    return build_graph(HeadSwapRequest(source_video=project["source"]["file"], portrait_image=refs[0]["file"],
        source_has_audio=True, start_seconds=start, duration_seconds=duration, seed=config["seed"],
        prompt=config.get("prompt", ""), take_name="studio_" + project["id"][:8] + "_h3_head_face"))


def readiness(node_mappings, get_full_path):
    folders = {"base":"diffusion_models", "text":"text_encoders", "video_vae":"vae",
               "audio_vae":"vae", "sam":"checkpoints", "background":"background_removal"}
    files = [{"folder":folders[key], "filename":value[2]} for key,value in MODELS.items()]
    files += [{"folder":"loras", "filename":filename} for _,filename,_ in LORAS]
    for item in files:
        try:
            item["ready"] = bool(get_full_path(item["folder"], item["filename"]))
        except KeyError:
            item["ready"] = False
    required = {n["class_type"] for n in build_graph(HeadSwapRequest("source.mp4", "portrait.png", True)).values()}
    missing = sorted(required - set(node_mappings))
    return {"ready":not missing and all(f["ready"] for f in files), "missing_nodes":missing, "model_files":files}
