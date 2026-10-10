"""H3 data padding and orchestration of native reference/inpainting nodes."""
from math import ceil
import hashlib
import json
import re
from pathlib import Path

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
                   "MiniMaxH3FunControlNetApply", "MiniMaxH3SigmaShift")
H3_PRESETS = ("preview_fast", "preview_quality", "take_fast", "take_quality")


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
    data = {"version": 6, "motion": "native_depth_control", "review": project["review"], "character": project["character"]["sha"],
            "opening": project["opening_key"], "settings": {k: c.get(k) for k in ("resolution", "size", "scope", "prompt", "pitch")},
            "audio": (project.get("audio") or {}).get("sha"), "audio_start": c.get("audio_start", 0),
            "lip_sync": c.get("lip_sync", False), "preview": False, "encoders": stamps}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


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
        return {"required": {"cache_key": ("STRING", {"default": ""})}}
    RETURN_TYPES = ("CONDITIONING", "LATENT")
    FUNCTION = "load"
    CATEGORY = "Zura/Artist Studio"

    @classmethod
    def IS_CHANGED(cls, cache_key):
        from . import digest_file
        return digest_file(cache_path(cache_key))

    def load(self, cache_key):
        data = torch.load(cache_path(cache_key), map_location="cpu", weights_only=True)
        if data.get("version") != 1:
            raise ValueError("This H3 reference cache must be prepared again.")
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


def build_h3_graph(project, use_cache=True):
    """Separate picture references, native audio and depth-controlled masked conditioning."""
    from . import verify_review
    from .studio import assert_approved, check_asset

    assert_approved(project)
    c = project["config"]
    if c["engine"] != "h3":
        raise ValueError("Choose MiniMax H3 before starting an H3 take.")
    if c["background"] != "keep":
        raise ValueError("H3 currently keeps the original background. Choose LTX for scene restyling.")
    if project.get("opening_approval") != project.get("opening_key") or not project.get("opening_input"):
        raise ValueError("Check the character preview and choose Animate this look first.")
    check_asset(project["character"])
    check_asset(project["opening_input"])
    _, manifest = verify_review(project["review"])
    preset = c["h3_preset"]
    preview = False
    count = manifest["clip"]["frames"]
    if not 5 <= count <= 120:
        raise ValueError("H3 supports a selected clip between 0.21 and 5 seconds. Change Clip length and prepare it again.")
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
    if c.get("remove_text"):
        prompt += " Remove all masked title banners, captions and subtitles completely. Fill them with clean background or character clothing. Do not reproduce any on-screen text overlays."
    if project.get("audio") and c.get("lip_sync"):
        prompt = prompt.replace("facial movement and camera timing", "head direction, eye expression and camera timing")
        prompt = prompt.replace("<Audio 1> supplies the original performance and speech timing.",
            "<Audio 1> is the replacement dialogue. Reproduce its words and timing through natural mouth and jaw articulation, with a resting mouth during silence. Ignore the source video's original dialogue and mouth movements.")
        prompt = prompt.replace("Follow the source gestures and speech.", "Follow the source body gestures and the replacement audio's speech.")
    graph = {}

    def node(identity, typ, **inputs):
        graph[identity] = {"class_type": typ, "inputs": inputs}
        return [identity, 0]

    reviewed = node("h3_shot", "GenjLoadReviewedShot", shot_id=project["review"],
                    approved_shot_id=project["review"], render_long_edge=c.get("resolution", c["size"]),
                    output_scale=1, preview_seconds=2 if preview else 0)
    pad_inputs = {"source": reviewed, "mask_video": ["h3_shot", 1]}
    if c["pitch"]:
        node("h3_guidance", "GetVideoComponents", video=["h3_shot", 2])
        pad_inputs["guidance_audio"] = ["h3_guidance", 1]
    node("h3_pad", "GenjH3FramePad", **pad_inputs)
    node("h3_opening", "LoadImage", image=project["opening_input"]["file"])
    node("h3_character", "LoadImage", image=project["character"]["file"])
    opening = node("h3_opening_size", "ImageScale", image=["h3_opening", 0], upscale_method="lanczos",
                   width=["h3_pad", 3], height=["h3_pad", 4], crop="disabled")
    model = node("h3_model", "UNETLoader", unet_name=H3_MODELS["h3"][1], weight_dtype="default")
    fast = preset.endswith("_fast")
    if fast:
        model = node("h3_turbo", "LoraLoaderModelOnly", model=model,
                     lora_name=H3_MODELS["h3_turbo"][1], strength_model=1.0)
    model = node("h3_shift", "MiniMaxH3SigmaShift", model=model, shift_video=12.0, shift_audio=3.0)
    clip = node("h3_clip", "CLIPLoader", clip_name=H3_MODELS["h3_text"][1], type="minimax", device="default")
    vae = node("h3_vae", "VAELoader", vae_name=H3_MODELS["h3_video_vae"][1])
    audio_vae = node("h3_audio_vae", "VAELoader", vae_name=H3_MODELS["h3_audio_vae"][1])
    patch = node("h3_patch", "ModelPatchLoader", name=H3_MODELS["h3_control"][1])
    depth = node("h3_depth", "DepthAnythingV2Preprocessor", image=["h3_pad", 0],
                 ckpt_name="depth_anything_v2_vitl.pth", resolution=512)
    depth = node("h3_depth_size", "ImageScale", image=depth, upscale_method="bilinear",
                 width=["h3_pad", 3], height=["h3_pad", 4], crop="disabled")
    model = node("h3_inpaint", "MiniMaxH3FunControlNetApply", model=model, model_patch=patch,
                 vae=vae, strength=1.0, start_percent=0.0, end_percent=1.0,
                 source_video=["h3_pad", 0], mask=["h3_pad", 1], control_video=depth)
    # A native prompt source keeps the artist control in Your inputs and lets
    # the reference stage receive its inputs in a single ordered hand-off.
    prompt_input = node("h3_prompt", "PrimitiveStringMultiline", value=prompt)
    positive = node("h3_references", "MiniMaxH3ReferenceToVideo", clip=clip, vae=vae, audio_vae=audio_vae,
                    prompt=prompt_input, width=["h3_pad", 3], height=["h3_pad", 4], length=["h3_pad", 5],
                    ref_image_size="match", **{"ref_images.ref_image_0": opening,
                    "ref_images.ref_image_1": ["h3_character", 0],
                    "ref_audios.ref_audio_0": ["h3_pad", 2]})
    latent = ["h3_references", 1]
    positive = node("h3_first_frame", "MiniMaxH3AddGuide", positive=positive, latent=latent,
                    vae=vae, image=opening, frame_idx=0)
    positive = node("h3_speech", "MiniMaxH3AddGuide", positive=positive, latent=latent,
                    audio_vae=audio_vae, audio=["h3_pad", 2], frame_idx=0)
    guider = node("h3_guider", "BasicGuider", model=model, conditioning=positive)
    noise = node("h3_noise", "RandomNoise", noise_seed=c["seed"])
    sigmas = node("h3_schedule", "BasicScheduler", model=model, scheduler="simple",
                  steps=8 if fast else 40, denoise=1.0)
    sampler = node("h3_sampler", "KSamplerSelect", sampler_name="res_multistep" if fast else "euler")
    sampled = node("h3_sample", "SamplerCustomAdvanced", noise=noise, guider=guider,
                   sampler=sampler, sigmas=sigmas, latent_image=latent)
    decoded = node("h3_decode", "VAEDecode", samples=sampled, vae=vae)
    trimmed = node("h3_trim", "GetImageRangeFromBatch", images=decoded, start_index=0, num_frames=["h3_pad", 6])
    video = node("h3_video", "CreateVideo", images=trimmed, fps=24.0, audio=["h3_pad", 2])
    node("h3_export", "GenjRestoreSoundtrack", video=video, clip_details=["h3_shot", 3],
         take_name="studio_" + project["id"][:8] + "_h3")
    key = cache_key(project)
    if use_cache and cache_path(key).exists():
        node("h3_cached", "GenjLoadH3Conditioning", cache_key=key)
        graph["h3_guider"]["inputs"]["conditioning"] = ["h3_cached", 0]
        graph["h3_sample"]["inputs"]["latent_image"] = ["h3_cached", 1]
        graph = reachable_graph(graph, ["h3_export"])
    from .speech import add_finish
    return add_finish(graph, project, native_speech=True)


NODE_CLASS_MAPPINGS = {c.__name__: c for c in (GenjH3FramePad, GenjSaveH3Conditioning, GenjLoadH3Conditioning)}
NODE_DISPLAY_NAME_MAPPINGS = {"GenjH3FramePad": "Prepare H3 Frames and Mask",
    "GenjSaveH3Conditioning": "Save H3 Character References", "GenjLoadH3Conditioning": "Load H3 Character References"}
