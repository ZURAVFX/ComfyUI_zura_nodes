"""Two-pass camera reshoot, adapted from the supplied distilled artist graph.

Builds native Comfy graphs only. It never queues work, segments the source or
purges model caches. Camera directions are approximate, not geometric solves.
"""
from dataclasses import dataclass
import math
import re

PRESETS = {
    "Natural medium": "A natural eye-level medium shot, mid-chest upwards with comfortable headroom.",
    "Left three-quarter": "Move the camera to the subject's left for a left three-quarter view, showing the left cheek and ear. Keep the head and body facing their original world direction. Eye-level, chest-up framing.",
    "Right three-quarter": "Move the camera to the subject's right for a right three-quarter view, showing the right cheek and ear. Keep the head and body facing their original world direction. Eye-level, chest-up framing.",
    "Left profile": "Photograph the subject from their left side: a clear left-profile view, nose pointing towards the right edge. Preserve the original head pose in world space. Include the hair, ear, neck and upper chest.",
    "Right profile": "Photograph the subject from their right side: a clear right-profile view, nose pointing towards the left edge. Preserve the original head pose in world space. Include the hair, ear, neck and upper chest.",
    "Low-angle portrait": "Place the camera slightly below eye level for a restrained low-angle portrait, chest-up framing, natural proportions and comfortable headroom.",
    "High-angle portrait": "Place the camera slightly above eye level, looking gently down, with natural proportions and all hair visible.",
    "Tight close-up": "A tight eye-level documentary portrait, shoulders upwards. Keep all hair and the full chin in frame. Preserve the expression and natural skin texture.",
    "Environmental wide": "Move the camera further back for an eye-level environmental portrait, waist upwards, showing more of the actual room and believable geometry.",
    "Custom prompt only": "",
}
MODELS = {
    "h3": ("diffusion_models", "minimax_h3_ref2va_pruned_int8_convrot.safetensors"),
    "turbo": ("loras", "minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors"),
    "text": ("text_encoders", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"),
    "video_vae": ("vae", "minimax_h3_video_vae_int8_convrot.safetensors"),
    "audio_vae": ("vae", "minimax_h3_audio_vae_fp32.safetensors"),
}
STILL_MODELS = {
    "flux": ("diffusion_models", "flux3-image-klein-int8-convrot.safetensors"),
    "text": ("text_encoders", "qwen3vl_4b_int8_convrot.safetensors"),
    "vae": ("vae", "flux2-vae.safetensors"),
}


@dataclass(frozen=True)
class CameraReference:
    image: str
    width: int = 512
    height: int = 688
    role: str = "identity"


@dataclass(frozen=True)
class CameraRequest:
    source_video: str
    source_path: str = ""
    camera_image: str = ""
    finished_camera: bool = False
    source_has_audio: bool = True
    start_seconds: float = 0.
    duration_seconds: float = 2.
    width: int = 768
    height: int = 448
    seed: int = 1052
    preset: str = "Left three-quarter"
    prompt: str = ""
    references: tuple = ()
    take_name: str = "zura_camera"


def _validate(r, video=False):
    if not isinstance(r.source_video, str) or not r.source_video.strip():
        raise ValueError("Upload a source video.")
    for value in (r.start_seconds, r.duration_seconds):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Choose a finite clip interval.")
    if r.start_seconds < 0 or not 3 <= int(r.duration_seconds * 24 + 1e-7) <= 120:
        raise ValueError("Choose a camera test of 0.125 to five seconds at 24 fps.")
    if any(type(x) is not int or x % 32 or not 128 <= x <= 4096 for x in (r.width, r.height)):
        raise ValueError("Camera width and height must be multiples of 32, from 128 to 4096.")
    if type(r.seed) is not int or not 0 <= r.seed <= 2**64 - 1:
        raise ValueError("Choose an unsigned 64-bit seed.")
    if r.preset not in PRESETS or not isinstance(r.prompt, str) or len(r.prompt) > 10000:
        raise ValueError("Choose a camera preset and a prompt up to 10,000 characters.")
    if r.preset == "Custom prompt only" and not r.prompt.strip() and not r.camera_image:
        raise ValueError("Describe the camera look or upload a finished camera image.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", r.take_name):
        raise ValueError("Use a simple camera take name.")
    if len(r.references) > 5:
        raise ValueError("Use up to five optional identity and room references.")
    for ref in r.references:
        if not isinstance(ref, CameraReference) or not ref.image or ref.role not in ("identity", "scene"):
            raise ValueError("Choose valid identity or room references.")
        if any(type(x) is not int or x < 1 for x in (ref.width, ref.height)):
            raise ValueError("Reference image dimensions are invalid.")
    if video and (not r.camera_image or r.source_has_audio is not True):
        raise ValueError("Camera video requires an approved camera still and a source with original audio. Silent footage is not yet qualified.")


def prompts(r):
    direction = "" if r.finished_camera else PRESETS[r.preset]
    still = ("Rephotograph Image 1 using the requested camera composition. This is a camera move, not a head turn. "
             "Preserve the same person or subjects, expression, gaze, recording-day hair, clothes, logos and lighting. "
             "Show the corresponding perspective of the same scene. Keep the entire head in frame. "
             "Preserve the source's visual style, proportions and texture.")
    video = ("Reshoot the exact performance of <Video 1> using the camera position, perspective, framing and appearance "
             "in <Picture 1>. Maintain this viewpoint throughout the shot, including its middle and last frames. "
             "Do not return to the source camera. Match source expressions, head movement, gestures and speech timing. "
             "Keep the same subjects, hair and clothing. No new actions, no slow motion or beautification. "
             "The approved camera image takes priority over conflicting written camera descriptions.")
    if direction:
        still += "\n" + direction
        video += "\nRequested camera look: " + direction
    if r.prompt.strip():
        still += "\n" + r.prompt.strip()
        video += "\nArtist camera direction: " + r.prompt.strip()
    for index, ref in enumerate(r.references, 2):
        role = ("supplies scene geometry only; preserve the source appearance and lighting" if ref.role == "scene" else
                "supplies identity and geometry only; do not copy its camera angle, expression, clothes or lighting")
        still += f"\nImage {index} {role}. Image 1 remains the pose and appearance authority."
        video += f"\n<Picture {index}> {role}. <Picture 1> remains the camera and appearance authority; <Video 1> supplies performance."
    return still, video


def _builder():
    graph = {}
    def node(key, kind, **inputs):
        graph[key] = {"class_type": kind, "inputs": inputs}
        return [key, 0]
    return graph, node


def _refs(r, node):
    result = []
    for i, ref in enumerate(r.references):
        image = node(f"ref_{i}", "LoadImage", image=ref.image)
        # Same proportional reference bounds as the source graph's thin image route.
        maxw, maxh = (640, 480) if ref.role == "scene" else (512, 688)
        ratio = min(1., maxw / ref.width, maxh / ref.height)
        result.append(node(f"ref_size_{i}", "ImageScale", image=image, upscale_method="lanczos",
                           width=max(1, round(ref.width * ratio)), height=max(1, round(ref.height * ratio)), crop="disabled"))
    return result


def build_still_graph(r):
    """Only FLUX runs here; video-model nodes are absent, not merely muted."""
    _validate(r)
    graph, node = _builder()
    if r.camera_image:
        image = node("camera_upload", "LoadImage", image=r.camera_image)
    else:
        # Decode just the selected first frame. No full-clip performance pass yet.
        source = node("source_still", "VHS_LoadVideoPath", video=r.source_path or r.source_video,
                      force_rate=24, custom_width=1280, custom_height=720, frame_load_cap=1,
                      skip_first_frames=math.floor(r.start_seconds * 24 + .5), select_every_nth=1, format="AnimateDiff")
        model = node("still_model", "UNETLoader", unet_name=STILL_MODELS["flux"][1], weight_dtype="default")
        clip = node("still_text", "CLIPLoader", clip_name=STILL_MODELS["text"][1], type="flux3", device="default")
        vae = node("still_vae", "VAELoader", vae_name=STILL_MODELS["vae"][1])
        positive = node("still_prompt", "CLIPTextEncode", clip=clip, text=prompts(r)[0])
        negative = node("still_negative", "ConditioningZeroOut", conditioning=positive)
        inputs = {"images.image0": source}
        inputs.update({f"images.image{i}": image for i, image in enumerate(_refs(r, node), 1)})
        positive = node("still_references", "ReferenceMultiLatent", positive=positive, negative=negative,
                        vae=vae, resolution="keep resolution", **inputs)
        latent = node("still_latent", "EmptyFlux2LatentImage", width=1024, height=576, batch_size=1)
        samples = node("still_sample", "KSampler", model=model, positive=positive,
                       negative=["still_references", 1], latent_image=latent, seed=r.seed, steps=16,
                       cfg=1., sampler_name="euler", scheduler="simple", denoise=1.)
        image = node("still_decode", "VAEDecode", samples=samples, vae=vae)
    node("camera_still", "SaveImage", images=image, filename_prefix="zura_camera/still")
    return graph


def build_graph(r):
    """H3 only, with source RGB performance, joint audio guide and start anchor."""
    _validate(r, video=True)
    graph, node = _builder()
    frames = int(r.duration_seconds * 24 + 1e-7)
    padded = 5 + 17 * max(0, math.ceil((frames - 5) / 17))
    source = node("source", "LoadVideo", file=r.source_video)
    selected = node("select", "GenjSelectClip", video=source, start_seconds=r.start_seconds,
                    duration_seconds=frames / 24, long_edge=1280, use_original_length=False)
    images = node("components", "GetVideoComponents", video=selected)
    audio = ["components", 1]
    images = node("performance_size", "ImageScale", image=images, upscale_method="lanczos", width=r.width, height=r.height, crop="center")
    images = node("performance_pad", "LayerUtility: Pad Image Batch to 8n+1", images=images, multiplier=17, remainder=5)
    still = node("camera_image", "LoadImage", image=r.camera_image)
    still = node("camera_size", "ImageScale", image=still, upscale_method="lanczos", width=r.width, height=r.height, crop="center")
    model = node("model", "UNETLoader", unet_name=MODELS["h3"][1], weight_dtype="default")
    model = node("turbo", "LoraLoaderModelOnly", model=model, lora_name=MODELS["turbo"][1], strength_model=1.)
    model = node("shift", "MiniMaxH3SigmaShift", model=model, shift_video=12., shift_audio=3.)
    model = node("attention", "ModelAttentionBackend", model=model, attention="comfy kitchen attention")
    clip = node("text", "CLIPLoader", clip_name=MODELS["text"][1], type="minimax", device="default")
    vae = node("video_vae", "VAELoader", vae_name=MODELS["video_vae"][1])
    audio_vae = node("audio_vae", "VAELoader", vae_name=MODELS["audio_vae"][1])
    inputs = {"ref_images.ref_image_0": still, "ref_videos.ref_video_0": images, "ref_video_audios.ref_video_audio_0": audio}
    inputs.update({f"ref_images.ref_image_{i}": image for i, image in enumerate(_refs(r, node), 1)})
    positive = node("references", "MiniMaxH3ReferenceToVideo", clip=clip, vae=vae, audio_vae=audio_vae,
                    prompt=prompts(r)[1], width=r.width, height=r.height, length=padded, ref_image_size="match", **inputs)
    latent = ["references", 1]
    positive = node("image_guide", "MiniMaxH3AddGuide", positive=positive, latent=latent, vae=vae, image=still, frame_idx=0)
    positive = node("audio_guide", "MiniMaxH3AddGuide", positive=positive, latent=latent, audio_vae=audio_vae, audio=audio, frame_idx=0)
    encoded = node("start_encode", "VAEEncode", pixels=still, vae=vae)
    latent = node("start_lock", "ZuraH3LockStartFrame", latent=latent, start_frame_latent=encoded)
    latent = node("audio_lock", "ZuraH3LockReferenceAudio", latent=latent, audio_vae=audio_vae, audio=audio)
    guider = node("guider", "BasicGuider", model=model, conditioning=positive)
    noise = node("noise", "RandomNoise", noise_seed=r.seed)
    sigmas = node("sigmas", "BasicScheduler", model=model, scheduler="simple", steps=8, denoise=1.)
    sampler = node("sampler", "KSamplerSelect", sampler_name="res_multistep")
    sample = node("sample", "SamplerCustomAdvanced", noise=noise, guider=guider, sampler=sampler, sigmas=sigmas, latent_image=latent)
    decoded = node("decode", "VAEDecode", samples=sample, vae=vae)
    decoded = node("trim", "ImageFromBatch", image=decoded, batch_index=0, length=frames)
    video = node("video", "CreateVideo", images=decoded, audio=audio, fps=24.)
    node("export", "GenjRestoreSoundtrack", video=video, clip_details=["select", 1], take_name=r.take_name)
    return graph


def _request(project, check_asset, video=False):
    import av
    from PIL import Image
    config = project["config"]
    source_path = check_asset(project["source"])
    with av.open(str(source_path)) as container:
        stream = container.streams.video[0]
        available = (float(stream.duration * stream.time_base) if stream.duration is not None
                     else float((container.duration or 0) / av.time_base))
        has_audio = bool(container.streams.audio)
    start = 0. if config.get("length_mode") == "original" else float(config.get("start", 0))
    duration = available if config.get("length_mode") == "original" else min(float(config.get("duration", 2)), available-start)
    refs = []
    for asset in project.get("references", []):
        path = check_asset(asset)
        with Image.open(path) as image:
            width, height = image.size
        refs.append(CameraReference(asset["file"], width, height, "scene" if asset.get("role") in ("scene", "environment") else "identity"))
    opening = project.get("opening_input") if video else (project.get("starting_asset") if project.get("look_mode") == "ready" else None)
    if opening:
        check_asset(opening)
    request = CameraRequest(source_video=project["source"]["file"], source_path=str(source_path),
        camera_image=opening["file"] if opening else "", finished_camera=project.get("look_mode") == "ready",
        source_has_audio=has_audio, start_seconds=start,
        duration_seconds=duration, width=int(config.get("camera_width", 768)), height=int(config.get("camera_height", 448)),
        seed=config.get("seed", 1052), preset=config.get("camera_preset", "Left three-quarter"),
        prompt=config.get("camera_prompt", ""), references=tuple(refs), take_name="studio_"+project["id"][:8]+"_camera")
    _validate(request, video=video)
    return request


def selected_frame_count(project, check_asset):
    return int(_request(project, check_asset).duration_seconds * 24 + 1e-7)


def build_studio_still_graph(project, check_asset):
    return build_still_graph(_request(project, check_asset))


def build_studio_graph(project, check_asset):
    if not project.get("opening_key") or project.get("opening_approval") != project["opening_key"]:
        raise ValueError("Approve the camera still before generating video.")
    return build_graph(_request(project, check_asset, video=True))


def readiness(node_mappings, get_full_path):
    sample = CameraRequest("source.mp4", camera_image="camera.png")
    graphs = {"video": build_graph(sample), "still": build_still_graph(CameraRequest("source.mp4"))}
    result = {"presets": list(PRESETS), "max_seconds": 5, "fps": 24, "quality_verified_locally": False,
              "requires_original_audio": True, "default_width": 768, "default_height": 448}
    for stage, graph in graphs.items():
        files = []
        for folder, filename in (MODELS if stage == "video" else STILL_MODELS).values():
            try:
                ready = bool(get_full_path(folder, filename))
            except KeyError:
                ready = False
            files.append({"folder":folder, "filename":filename, "ready":ready})
        missing = sorted({n["class_type"] for n in graph.values()} - set(node_mappings))
        result[stage] = {"ready": not missing and all(item["ready"] for item in files), "missing_nodes":missing, "model_files":files}
    result["ready"] = result["still"]["ready"] and result["video"]["ready"]
    result["missing_nodes"] = sorted(set(result["still"]["missing_nodes"] + result["video"]["missing_nodes"]))
    result["model_files"] = result["still"]["model_files"] + result["video"]["model_files"]
    return result
