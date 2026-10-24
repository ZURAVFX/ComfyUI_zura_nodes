"""Native image-edit recipes for the video starting-frame stage.

The original-frame, mask and output-registration nodes remain shared. Model
selection changes only its loaders, conditioning and supported sampler path.
"""
import json
from pathlib import Path

MODELS = {
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


def apply_model(graph, model="klein9b", references=None):
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
        graph = json.loads(json.dumps(template))
        apply_model(graph, identity, [{"file": "availability-check.png"}])
        missing = sorted({node["class_type"] for node in graph.values()} - set(node_mappings))
        files = [{"folder": folder, "filename": filename, "ready": bool(get_full_path(folder, filename))}
                 for folder, filename in model["files"]]
        result[identity] = {"id": identity, "name": model["name"], "max_references": model["max_references"],
                            "ready": not missing and all(item["ready"] for item in files),
                            "missing_nodes": missing, "model_files": files, "experimental": model.get("experimental", False)}
    return result


def _prune(graph):
    reachable = set()
    def visit(identity):
        if identity in reachable or identity not in graph:
            return
        reachable.add(identity)
        for value in graph[identity].get("inputs", {}).values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                visit(value[0])
    for identity in ("122", "zura_original_size", "92:114", "125", "92:111", "92:127", "92:105", "92:104", "127"):
        visit(identity)
    for identity in list(graph):
        if identity not in reachable:
            del graph[identity]
    return graph


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
    clip = node("92:108", "CLIPLoader", "Qwen3-VL 8B on CPU", clip_name=files[1][1], type="qwen_image", device="cpu")
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
