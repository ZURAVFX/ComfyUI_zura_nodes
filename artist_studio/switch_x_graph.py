"""Local MiniMax H3 masked environment generation for Switch X Remake."""

from math import ceil

DIFFUSION = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
TEXT = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_int8_convrot.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
TURBO = "minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors"
CONTROL = "minimax_h3_fun_controlnet_union_2.0_pruned_int8_convrot.safetensors"


def model_length(count):
    return 5 + 17 * max(0, ceil((count - 5) / 17))


def generation_graph(refs, prompt, width, height, count, seed=42, steps=8, guidance=1.0):
    """Source and matte are frame-indexed, aspect-fitted model guides."""
    if refs and not prompt.strip():
        prompt = "Transform the surrounding scene and its light using the supplied reference images. Preserve the original performance and camera motion."
    if not prompt.strip() or len(refs) > 4:
        raise ValueError("Describe the scene and choose up to four reference images.")
    if count < 1 or model_length(count) > 3600:
        raise ValueError("The source exceeds the native H3 latent length.")
    graph = {}

    def add(key, kind, **inputs):
        graph[key] = {"class_type": kind, "inputs": inputs}
        return [key, 0]

    model = add("model", "UNETLoader", unet_name=DIFFUSION, weight_dtype="default")
    if steps == 8:
        model = add(
            "turbo", "LoraLoaderModelOnly", model=model, lora_name=TURBO, strength_model=1.0
        )
    model = add(
        "attention", "ModelAttentionBackend", model=model, attention="comfy kitchen attention"
    )
    model = add("shift", "MiniMaxH3SigmaShift", model=model, shift_video=12.0, shift_audio=6.0)
    vae = add("vae", "VAELoader", vae_name=VIDEO_VAE)
    source_latent = add("source_latent", "VAEEncode", pixels=["plates", 0], vae=vae)
    structure = add(
        "structure",
        "ZuraH3SourceStructure",
        model=model,
        source=source_latent,
        replace=["plates", 1],
        strength=guidance,
    )
    images = {
        f"ref_images.ref_image_{i}": add(f"ref_{i}", "LoadImage", image=f)
        for i, f in enumerate(refs)
    }
    positive = add(
        "scene",
        "MiniMaxH3ReferenceToVideo",
        clip=add("text", "CLIPLoader", clip_name=TEXT, type="minimax", device="default"),
        vae=vae,
        audio_vae=add("audio_vae", "VAELoader", vae_name=AUDIO_VAE),
        prompt=prompt,
        width=width,
        height=height,
        ref_image_size="match",
        length=model_length(count),
        **{"ref_videos.ref_video_0": ["plates", 2]},
        **images,
    )
    samples = add(
        "sample",
        "SamplerCustomAdvanced",
        latent_image=["scene", 1],
        noise=add("noise", "RandomNoise", noise_seed=seed),
        guider=add("guide", "BasicGuider", model=structure, conditioning=positive),
        sampler=add("sampler", "KSamplerSelect", sampler_name="res_multistep"),
        sigmas=add(
            "schedule",
            "BasicScheduler",
            model=model,
            scheduler="simple" if steps == 8 else "beta",
            steps=steps,
            denoise=1.0,
        ),
    )
    add("decode", "VAEDecode", samples=samples, vae=vae)
    return graph
