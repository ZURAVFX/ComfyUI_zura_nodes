"""Native image-edit recipes for the video starting-frame stage.

The original-frame, mask and output-registration nodes remain shared. Model
selection changes only its loaders, conditioning and supported sampler path.
"""
import json
import math
from pathlib import Path

# The browser Image workspace and native video starting-frame recipes share the
# unchanged, pinned Black Forest Labs instructions and upstream licence notice.
FLUX3_PROMPT_SYSTEMS = json.loads((Path(__file__).resolve().parent.parent / "web" / "flux3_prompt_upsampling.json").read_text(encoding="utf-8"))

MODELS = {
    "chatgpt": {"id": "chatgpt", "name": "ChatGPT Image · browser sign-in", "provider": "chatgpt",
                "node": "ZuraChatGPTImage", "max_references": 7, "files": ()},
    "gemini": {"id": "gemini", "name": "Gemini Image · browser sign-in", "provider": "gemini",
               "node": "ZuraGeminiImage", "max_references": 7, "files": ()},
    "flux3": {
        "id": "flux3", "name": "Flux 3 Klein", "max_references": 9,
        "files": (("diffusion_models", "flux3-image-klein-int8-convrot.safetensors"),
                  ("text_encoders", "qwen3vl_4b_int8_convrot.safetensors"),
                  ("vae", "flux2-vae.safetensors"),
                  ("text_encoders", "qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors")),
    },
    "ph3": {
        "id": "ph3", "name": "P-H3 Image", "max_references": 7,
        "files": (("diffusion_models", "minimax_h3_fl2va_pruned_int8_convrot.safetensors"),
                  ("text_encoders", "p-h3-image_text_encoder_int8_convrot.safetensors"),
                  ("vae", "p-h3-image_vae_int8_convrot.safetensors"),
                  ("loras", "p-h3-image_lora_bf16.safetensors"),
                  ("text_encoders", "p-h3-image_prompt_upsampler_w4a8.safetensors")),
    },
    "klein9b": {
        "id": "klein9b", "name": "FLUX Klein 9B", "max_references": 3,
        "files": (("diffusion_models", "flux-2-klein-9b-fp8.safetensors"),
                  ("text_encoders", "qwen_3_8b_fp8mixed.safetensors"),
                  ("vae", "full_encoder_small_decoder.safetensors")),
    },
    "qwen21": {
        "id": "qwen21", "name": "Qwen Image 2.1", "max_references": 9, "experimental": True,
        "files": (("diffusion_models", "qwen_image_2.1_int8_convrot.safetensors"),
                  ("text_encoders", "qwen3vl_8b_int8_convrot.safetensors"),
                  ("vae", "qwen_image_2.1_vae_bf16.safetensors")),
    },
    "qwen2511": {
        "id": "qwen2511", "name": "Qwen Image Edit 2511", "max_references": 2,
        "files": (("diffusion_models", "qwen_image_edit_2511_int8_convrot.safetensors"),
                  ("text_encoders", "qwen_2.5_vl_7b_fp8_scaled.safetensors"),
                  ("vae", "qwen_image_vae.safetensors"),
                  ("loras", "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors")),
    },
}


PROPORTIONS = ("Do not change the proportions of Image 1 at all. Preserve its aspect ratio and output canvas dimensions; "
               "do not stretch or squash the image. Keep the framing unchanged unless the requested edit explicitly "
               "changes the camera view. Make only the requested edit.")


def browser_node(model, prompt, source, references, width, height, *, identity="92:105"):
    recipe = MODELS[model]
    if len(references) > recipe['max_references']:
        raise ValueError('Browser image generation accepts seven appearance references plus the original frame.')
    inputs = dict(prompt=prompt.strip() + '\n\n' + PROPORTIONS, size='Custom',
                  custom_width=width, custom_height=height, timeout_seconds=300, reference_1=source)
    graph = {}
    for index, ref in enumerate(references, 2):
        if not isinstance(ref, dict) or not ref.get('file'):
            raise ValueError('Upload each appearance reference before generating the starting image.')
        key = f'zura_browser_reference_{index}'
        graph[key] = {'class_type': 'LoadImage', 'inputs': {'image': ref['file']}}
        inputs[f'reference_{index}'] = [key, 0]
    graph[identity] = {'class_type': recipe['node'], 'inputs': inputs,
                       '_meta': {'title': recipe['name'] + ' · original frame edit'}}
    return graph


def apply_model(graph, model="klein9b", references=None, *, dimensions=None):
    """Apply a native recipe, keeping existing source and mask connections.

    references contains appearance images only. Qwen's first image is always
    the original video frame. Edit 2511 accepts two additional references;
    the experimental 2.1 recipe accepts nine.
    """
    if model not in MODELS:
        raise ValueError("Choose an available starting image generator.")
    if model == "klein9b":
        return graph  # Keep the existing approved Klein recipe exactly.
    references = references or []
    if MODELS[model].get('provider'):
        graph['zura_original_size'] = {'class_type': 'GetImageSize', 'inputs': {'image': ['125', 0]}}
        width, height = dimensions or (['zura_original_size', 0], ['zura_original_size', 1])
        graph.update(browser_node(model, graph['127']['inputs']['value'], ['125', 0], references, width, height))
        # Browser providers cannot consume local diffusion weights or latents.
        return _prune(graph, roots=('122', 'zura_original_size'))
    if model == "flux3":
        return _apply_flux3(graph, references)
    if model == "ph3":
        return _apply_ph3(graph, references)
    if model == "qwen21":
        return _apply_qwen21(graph, references)
    if len(references) > 2:
        raise ValueError("Qwen Image Edit 2511 accepts two appearance references plus the original video frame. Remove an extra reference or choose FLUX Klein 9B.")
    def node(identity, kind, title, **inputs):
        graph[identity] = {"class_type": kind, "inputs": inputs, "_meta": {"title": title}}
        return [identity, 0]
    base = node("92:107", "UNETLoader", "Qwen Image Edit 2511 · INT8",
                unet_name=MODELS[model]["files"][0][1], weight_dtype="default")
    clip = node("92:108", "CLIPLoader", "Qwen edit text encoder",
                clip_name=MODELS[model]["files"][1][1], type="qwen_image", device="default")
    vae = node("92:110", "VAELoader", "Qwen image VAE", vae_name=MODELS[model]["files"][2][1])
    accelerated = node("zura_qwen_lightning", "LoraLoaderModelOnly", "Qwen 4-step Lightning",
                       model=base, lora_name=MODELS[model]["files"][3][1], strength_model=1.0)
    shifted = node("zura_qwen_sampling", "ModelSamplingAuraFlow", "Qwen sampling shift", model=accelerated, shift=3.1)
    normalised = node("zura_qwen_cfg_norm", "CFGNorm", "Qwen guidance normalisation", model=shifted, strength=1.0)
    images = {"image1": ["92:111", 0]}
    for index, ref in enumerate(references, 2):
        if not isinstance(ref, dict) or not ref.get("file"):
            raise ValueError("Upload each appearance reference before generating the starting image.")
        images[f"image{index}"] = node(f"zura_qwen_reference_{index}", "LoadImage", f"Appearance reference {index-1}", image=ref["file"])
    pos = node("92:109", "TextEncodeQwenImageEditPlus", "Edit the original video frame",
               clip=clip, vae=vae, prompt=["127", 0], **images)
    neg = node("92:86", "TextEncodeQwenImageEditPlus", "Qwen negative conditioning",
               clip=clip, vae=vae, prompt="", **images)
    positive = node("zura_qwen_positive", "FluxKontextMultiReferenceLatentMethod", "Qwen positive reference method",
                    conditioning=pos, reference_latents_method="index_timestep_zero")
    negative = node("zura_qwen_negative", "FluxKontextMultiReferenceLatentMethod", "Qwen negative reference method",
                    conditioning=neg, reference_latents_method="index_timestep_zero")
    graph["92:103"]["inputs"] = {"model": normalised, "positive": positive, "negative": negative, "cfg": 4.0}
    node("92:102", "BasicScheduler", "Qwen 4-step simple schedule", model=normalised, scheduler="simple", steps=4, denoise=1.0)
    # Existing masked source latents must survive the model switch. Both this
    # encoder and the mask node refer to the selected VAE at stable ID92:110.
    if graph["92:104"]["inputs"]["latent_image"] == ["92:113", 0]:
        graph["92:104"]["inputs"]["latent_image"] = ["92:127", 0]
    graph["92:127"]["inputs"].update(pixels=["92:111", 0], vae=vae)
    graph["92:105"]["inputs"]["vae"] = vae
    # Drop the now-unused Flux conditioning/latent branches. Standalone native
    # graphs should not require Flux-only nodes to run the Qwen recipe.
    return _prune(graph)



def readiness(node_mappings, get_full_path):
    """Report each generator independently, rather than requiring both."""
    template = json.loads((Path(__file__).parent / "graphs" / "01B_Design_Opening_Frame.json").read_text(encoding="utf-8"))
    result = {}
    for identity, model in MODELS.items():
        if model.get('provider'):
            missing = [name for name in (model['node'], 'LoadImage', 'GetImageSize', 'SaveImage') if name not in node_mappings]
            result[identity] = {**{key: model[key] for key in ('id', 'name', 'max_references', 'provider')},
                                'ready': not missing, 'missing_nodes': missing, 'model_files': []}
            continue
        graph = json.loads(json.dumps(template))
        apply_model(graph, identity, [{"file": "availability-check.png"}])
        missing = sorted({node["class_type"] for node in graph.values()} - set(node_mappings))
        files = [{"folder": folder, "filename": filename, "ready": bool(get_full_path(folder, filename))}
                 for folder, filename in model["files"]]
        result[identity] = {"id": identity, "name": model["name"], "max_references": model["max_references"],
                            "ready": not missing and all(item["ready"] for item in files),
                            "missing_nodes": missing, "model_files": files, "experimental": model.get("experimental", False)}
    return result


def _prune(graph, roots=None):
    reachable = set()
    def visit(identity):
        if identity in reachable or identity not in graph:
            return
        reachable.add(identity)
        for value in graph[identity].get("inputs", {}).values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                visit(value[0])
    for identity in (roots if roots is not None else ("122", "zura_original_size", "92:114", "125", "92:111", "92:127", "92:105", "92:104", "127")):
        visit(identity)
    for identity in list(graph):
        if identity not in reachable:
            del graph[identity]
    return graph


def _apply_ph3(graph, references):
    """Edit the source frame using Pruna's P-H3 image LoRA and prompt upsampler.

    P-H3 returns a nested audio/video latent, not the ordinary image latent
    used by the other opening recipes. The artist's reviewed selection is
    retained by Studio's post-decode mask composite, rather than passing the
    incompatible VAEEncode image latent into this sampler.
    """
    if len(references) > 7:
        raise ValueError("P-H3 Image accepts seven appearance references plus the original frame.")

    def node(identity, kind, title, **inputs):
        graph[identity] = {"class_type": kind, "inputs": inputs, "_meta": {"title": title}}
        return [identity, 0]

    files = MODELS["ph3"]["files"]
    base = node("92:107", "UNETLoader", "P-H3 Image · H3 FL2VA INT8",
                unet_name=files[0][1], weight_dtype="default")
    clip = node("92:108", "CLIPLoader", "P-H3 image text encoder",
                clip_name=files[1][1], type="minimax", device="default")
    vae = node("92:110", "VAELoader", "P-H3 image VAE", vae_name=files[2][1])
    adapted = node("zura_ph3_adapter", "LoraLoaderBypassModelOnly", "P-H3 image adapter",
                   model=base, lora_name=files[3][1], strength_model=1.0)
    model = node("zura_ph3_shift", "MiniMaxH3SigmaShift", "P-H3 image sampling",
                 model=adapted, shift_video=1.0, shift_audio=1.0)
    upsampler = node("zura_ph3_upsampler", "CLIPLoader", "P-H3 prompt upsampler",
                     clip_name=files[4][1], type="minimax", device="default")

    # The main image is always the original video frame, including on retries.
    # The native conditioning node expects all image slots in a fixed order.
    graph["92:111"]["inputs"]["resolution_steps"] = 32
    images = {"images.image_1": ["92:111", 0]}
    prompt_image = node("zura_ph3_prompt_source", "ImageScaleToTotalPixels", "Prompt source image",
                        image=["92:111", 0], upscale_method="lanczos", megapixels=1.0, resolution_steps=1)
    source_size = node("zura_ph3_prompt_size", "GetImageSize", "Prompt image dimensions", image=prompt_image)
    batch_images = {"images.image0": prompt_image}
    for index, ref in enumerate(references, 2):
        if not isinstance(ref, dict) or not ref.get("file"):
            raise ValueError("Upload each appearance reference before generating the starting image.")
        image = node(f"zura_ph3_reference_{index}", "LoadImage", f"Appearance reference {index-1}", image=ref["file"])
        images[f"images.image_{index}"] = image
        batch_images[f"images.image{index-1}"] = node(
            f"zura_ph3_prompt_ref_{index}", "ResizeAndPadImage", "Prepare prompt reference",
            image=image, target_width=source_size, target_height=["zura_ph3_prompt_size", 1],
            padding_color="white", interpolation="lanczos")
    image_batch = node("zura_ph3_prompt_images", "BatchImagesNode", "Prompt images", **batch_images)
    picture_tokens = "".join(
        f"<Picture {i}>: <|vision_start|><|image_pad|><|vision_end|>"
        for i in range(1, len(references) + 2))
    request = graph["127"]["inputs"]["value"].strip()
    prompt = (f"<|im_start|>user\n{picture_tokens}Edit <Picture 1>. {request}"
              "<|im_end|>\n<|im_start|>assistant\n<think>\n")
    expanded = node("zura_ph3_prompt", "TextGenerate", "Expand image edit instruction",
                    clip=upsampler, prompt=prompt, image=image_batch, max_length=3072,
                    sampling_mode="off", thinking=False, use_default_template=True, mtp="auto")
    node("92:109", "PH3ImageConditioning", "Original frame and appearance references",
         clip=clip, vae=vae, prompt=expanded, width=["92:114", 0], height=["92:114", 1], **images)
    node("92:103", "BasicGuider", "P-H3 image guidance", model=model, conditioning=["92:109", 0])
    node("92:102", "ManualSigmas", "P-H3 8-step schedule",
         sigmas="1.0, 0.984753, 0.967905, 0.951688, 0.925372, 0.881923, 0.810083, 0.528718, 0.0")
    graph["92:104"]["inputs"]["latent_image"] = ["92:109", 1]
    graph["92:105"]["inputs"]["vae"] = vae
    # Prune the old incompatible Flux source latent and any latent noise mask.
    # The separately connected zura_masked_look composite remains reachable.
    return _prune(graph, roots=("122", "zura_original_size", "92:114", "125", "92:111", "92:105", "92:104", "127"))


def _apply_flux3(graph, references):
    """Use the existing Image workspace's INT8 reference recipe on the source frame."""
    if len(references) > 9:
        raise ValueError("Flux 3 Klein accepts nine appearance references plus the original frame.")
    def node(identity, kind, **inputs):
        graph[identity] = {"class_type": kind, "inputs": inputs}
        return [identity, 0]
    files = MODELS["flux3"]["files"]
    model = node("92:107", "UNETLoader", unet_name=files[0][1], weight_dtype="default")
    clip = node("92:108", "CLIPLoader", clip_name=files[1][1], type="flux3", device="default")
    vae = node("92:110", "VAELoader", vae_name=files[2][1])
    images = {"images.image0": ["92:111", 0]}
    for index, ref in enumerate(references, 1):
        if not isinstance(ref, dict) or not ref.get("file"):
            raise ValueError("Upload each appearance reference before generating the starting image.")
        images[f"images.image{index}"] = node(f"zura_flux3_reference_{index}", "LoadImage", image=ref["file"])
    # Keep source-first image roles and complete donors in the official visual
    # prompt expansion stage, just as in the standalone Image workspace.
    upsampler = node("zura_flux3_upsampler", "CLIPLoader", clip_name=files[3][1], type="flux3", device="default")
    source_size = node("zura_flux3_prompt_size", "GetImageSize", image=["92:111", 0])
    prompt_images = {"images.image0": ["92:111", 0]}
    for index in range(1, len(references) + 1):
        prompt_images[f"images.image{index}"] = node(
            f"zura_flux3_prompt_ref_{index}", "ResizeAndPadImage", image=images[f"images.image{index}"],
            target_width=source_size, target_height=["zura_flux3_prompt_size", 1],
            padding_color="white", interpolation="lanczos")
    image_batch = node("zura_flux3_prompt_images", "BatchImagesNode", **prompt_images)
    request = graph["127"]["inputs"]["value"].strip()
    expanded = node("zura_flux3_prompt", "TextGenerate", clip=upsampler, image=image_batch,
                    prompt=f"Reference images follow in order (the first image, the second image, ...).\nUser request: {request}\nOutput the caption.",
                    system_prompt=FLUX3_PROMPT_SYSTEMS["i2i"], max_length=3584, sampling_mode="on",
                    thinking=False, use_default_template=True, mtp="off", **{
                        "sampling_mode.temperature": 1, "sampling_mode.top_k": 1,
                        "sampling_mode.top_p": 0.95, "sampling_mode.min_p": 0,
                        "sampling_mode.repetition_penalty": 1, "sampling_mode.presence_penalty": 0,
                        "sampling_mode.seed": graph["92:106"]["inputs"]["noise_seed"],
                    })
    positive = node("92:109", "CLIPTextEncode", clip=clip, text=expanded)
    negative = node("zura_flux3_negative", "ConditioningZeroOut", conditioning=positive)
    model = node("zura_flux3_sampling", "ModelSamplingFlux", model=model,
                 max_shift=math.log(16), base_shift=math.log(16), width=["92:114", 0], height=["92:114", 1])
    node("zura_flux3_references", "ReferenceMultiLatent", positive=positive, negative=negative,
         vae=vae, resolution="resize", **{"resolution.megapixels": min(1, 2 / (len(references) + 1)), **images})
    graph["92:103"]["inputs"] = {"model": model, "positive": ["zura_flux3_references", 0],
                                 "negative": ["zura_flux3_references", 1], "cfg": 1.0}
    node("92:102", "BasicScheduler", model=model, scheduler="simple", steps=16, denoise=1.0)
    graph["92:127"]["inputs"].update(pixels=["92:111", 0], vae=vae)
    graph["92:105"]["inputs"]["vae"] = vae
    return _prune(graph)


def _apply_qwen21(graph, references):
    """Native 2.1 base recipe; never mix in the older Edit2511 LoRA.

    This is a locally discovered research recipe, not an artist-approved render.
    Its own encoder latent keeps the source size aligned to its image tokens.
    """
    if len(references) > 9:
        raise ValueError("Qwen Image 2.1 accepts nine appearance references plus the original frame.")
    def node(identity, kind, title, **inputs):
        graph[identity] = {"class_type": kind, "inputs": inputs, "_meta": {"title": title}}
        return [identity, 0]
    files = MODELS["qwen21"]["files"]
    base = node("92:107", "UNETLoader", "Qwen Image 2.1 INT8", unet_name=files[0][1], weight_dtype="default")
    clip = node("92:108", "CLIPLoader", "Qwen3-VL 8B · automatic device", clip_name=files[1][1], type="qwen_image", device="default")
    vae = node("92:110", "VAELoader", "Qwen 2.1 VAE", vae_name=files[2][1])
    cached = node("zura_qwen21_cache", "QwenImage21Cache", "Lossless reference cache in RAM", model=base, device="cpu", dtype="default")
    graph["92:111"]["inputs"]["resolution_steps"] = 32
    images = {"images.image_1": ["92:111", 0]}
    for index, ref in enumerate(references, 2):
        if not isinstance(ref, dict) or not ref.get("file"):
            raise ValueError("Upload each appearance reference before generating the starting image.")
        images[f"images.image_{index}"] = node(f"zura_qwen21_reference_{index}", "LoadImage", f"Appearance reference {index-1}", image=ref["file"])
    node("92:109", "TextEncodeQwenImage21", "Qwen 2.1 source and references",
         clip=clip, vae=vae, prompt=["127", 0], negative_prompt="", resolution=0, **images)
    graph["92:103"]["inputs"] = {"model": cached, "positive": ["92:109", 0], "negative": ["92:109", 1], "cfg": 1.0}
    node("92:102", "BasicScheduler", "Qwen 2.1 base 40-step schedule", model=cached, scheduler="simple", steps=40, denoise=1.0)
    if graph["92:104"]["inputs"]["latent_image"] == ["92:113", 0]:
        graph["92:104"]["inputs"]["latent_image"] = ["92:109", 2]
    graph["92:127"]["inputs"].update(pixels=["92:111", 0], vae=vae)
    rgba = node("zura_qwen21_decode", "VAEDecodeTiled", "Decode Qwen 2.1 RGBA", samples=["92:104", 0], vae=vae,
                tile_size=512, overlap=64, temporal_size=64, temporal_overlap=8)
    node("92:105", "SplitImageWithAlpha", "Opaque RGB starting image", image=rgba)
    return _prune(graph)
