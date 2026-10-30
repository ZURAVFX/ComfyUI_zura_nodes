"""Inspect installed LoRAs and add model-only adapters to native Comfy graphs.

An adapter's filename is only a hint, never proof of model compatibility.
Adapters with no recognised base-model metadata require explicit confirmation.
This module deliberately rejects specialised guidance adapters and text-encoder
weights rather than silently applying them with a generic model-only loader.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

MAX_HEADER = 16 * 1024 * 1024
MAX_ADAPTERS = 4
FAMILIES = ("h3", "wan21", "wan22", "wan_animate2", "ltx25",
            "flux2_klein9b", "flux3_klein", "qwen2511", "qwen21", "zimage")


def model_family(name):
    """Recognise only exact model families for which Studio builds a native UNET."""
    text = str(name).lower().replace("-", "_").replace(" ", "_")
    if "minimax_h3" in text or text.startswith("h3_") or text.startswith("fasth3_omniref_8step_pruned_"):
        return "h3"
    if "wan_animate_2" in text or "wananimate2" in text:
        return "wan_animate2"
    if "wan2_1" in text or "wan_2.1" in text or "wan2.1" in text:
        return "wan21"
    if "wan2_2" in text or "wan_2.2" in text or "wan2.2" in text:
        return "wan22"
    if "ltx_2.5" in text or "ltx_2_5" in text:
        return "ltx25"
    if "flux3" in text and "klein" in text:
        return "flux3_klein"
    if ("flux_2" in text or "flux2" in text) and "klein" in text and "9b" in text:
        return "flux2_klein9b"
    if "qwen_image" in text and "2511" in text:
        return "qwen2511"
    if "qwen_image" in text and "2.1" in text:
        return "qwen21"
    if "z_image" in text or "zimage" in text:
        return "zimage"
    return None


def inspect_header(path):
    """Read bounded safetensors metadata only; never load model weights."""
    path = Path(path)
    if path.suffix.lower() != ".safetensors":
        raise ValueError("Only installed safetensors LoRAs are supported.")
    with path.open("rb") as stream:
        raw = stream.read(8)
        if len(raw) != 8:
            raise ValueError("The LoRA file is incomplete.")
        length = int.from_bytes(raw, "little")
        if length < 2 or length > MAX_HEADER or length > path.stat().st_size - 8:
            raise ValueError("The LoRA header is invalid or incomplete.")
        try:
            header = json.loads(stream.read(length))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("The LoRA header is invalid.") from exc
    if not isinstance(header, dict):
        raise ValueError("The LoRA header is invalid.")
    metadata = header.get("__metadata__", {})
    if not isinstance(metadata, dict):
        metadata = {}
    metadata_values = [metadata.get(key, "") for key in
                       ("ss_base_model_version", "modelspec.architecture", "base_model", "base_model_name")]
    families = {family for family in map(model_family, metadata_values) if family}
    if len(families) > 1:
        raise ValueError("This LoRA reports conflicting base models.")
    tensors = [str(key).lower() for key in header if key != "__metadata__"]
    has_text_weights = any(key.startswith(("lora_te", "text_encoder.", "text_encoders.", "clip.")) for key in tensors)
    return {"metadata_family": next(iter(families), None),
            "filename_hint": model_family(path.name),
            "has_text_weights": has_text_weights,
            "size_bytes": path.stat().st_size}


def catalogue(names, get_path):
    """List registered Comfy LoRAs with size and candid compatibility hints."""
    entries = []
    for name in names:
        if not isinstance(name, str) or not name.lower().endswith(".safetensors"):
            continue
        path = get_path("loras", name)
        if not path:
            continue
        try:
            entry = inspect_header(path)
            entry.update(name=name, usable=not entry["has_text_weights"], error=None)
        except (OSError, ValueError) as exc:
            entry = {"name": name, "usable": False, "error": str(exc)}
        entries.append(entry)
    return entries


def apply_to_graph(graph, family, selections, registered_names, get_path, *, target_ids=None, namespace=None):
    """Return a patched graph; reject unsupported adapters and model paths.

    selections: [{name, strength, confirm_unknown}] from the user interface.
    The caller must use this on each separate sampling phase of a multi-stage
    job. It must not apply it to auxiliary graph phases with no diffusion model.
    """
    if not selections:
        return copy.deepcopy(graph)
    if family not in FAMILIES:
        raise ValueError("Custom LoRAs are not supported for this model route.")
    if not isinstance(selections, list) or len(selections) > MAX_ADAPTERS:
        raise ValueError(f"Choose up to {MAX_ADAPTERS} custom LoRAs.")
    names = set(registered_names)
    checked = []
    for selection in selections:
        if not isinstance(selection, dict):
            raise ValueError("Choose an installed LoRA.")
        name = selection.get("name")
        if not isinstance(name, str) or name not in names:
            raise ValueError("Choose a LoRA from ComfyUI's registered models folder.")
        path = get_path("loras", name)
        if not path:
            raise ValueError("The selected LoRA is no longer installed.")
        if "ic-lora" in name.lower() or "ic_lora" in name.lower():
            raise ValueError("IC-LoRAs need a matching guide workflow and cannot be added as a generic style LoRA.")
        info = inspect_header(path)
        if info["has_text_weights"]:
            raise ValueError("This LoRA includes text-encoder weights; this model-only route cannot apply it fully.")
        if info["metadata_family"] and info["metadata_family"] != family:
            raise ValueError("The LoRA's declared base model is incompatible with this route.")
        if not info["metadata_family"] and selection.get("confirm_unknown") is not True:
            raise ValueError("This LoRA has no recognised base-model metadata. Confirm compatibility with the selected model.")
        try:
            strength = float(selection.get("strength", 1.0))
        except (TypeError, ValueError) as exc:
            raise ValueError("Choose a valid LoRA strength.") from exc
        if not math.isfinite(strength) or not -2 <= strength <= 2:
            raise ValueError("LoRA strength must be between -2 and 2.")
        checked.append((name, strength))
    if len({name for name, _ in checked}) != len(checked):
        raise ValueError("Choose each LoRA only once.")

    result = copy.deepcopy(graph)
    targets = [identity for identity, node in result.items()
               if node.get("class_type") == "UNETLoader"
               and model_family(node.get("inputs", {}).get("unet_name")) == family]
    if target_ids is not None:
        if not isinstance(target_ids, (list, tuple)) or not target_ids or any(identity not in targets for identity in target_ids):
            raise ValueError('The selected model phase is not available in this workflow.')
        targets = list(target_ids)
    if not targets:
        raise ValueError("This workflow does not expose a compatible native model loader for custom LoRAs.")
    for target_index, identity in enumerate(targets):
        current = [identity, 0]
        additions = []
        for index, (name, strength) in enumerate(checked):
            new_id = f"zura_custom_lora_{namespace + '_' if namespace else ''}{target_index}_{index}"
            if new_id in result:
                raise ValueError("Custom LoRAs have already been added to this graph.")
            additions.append((new_id, {"class_type": "LoraLoaderModelOnly", "inputs":
                {"model": current, "lora_name": name, "strength_model": strength},
                "_meta": {"title": f"Custom LoRA {index + 1}"}}))
            current = [new_id, 0]
        for node in result.values():
            for key, value in node.get("inputs", {}).items():
                if value == [identity, 0]:
                    node["inputs"][key] = current.copy()
        result.update(additions)
    return result


def apply_installed_ltx_loras(graph, selections):
    """Validate installed adapters and insert them before LTX guidance adapters.

    Running this for each graph (including every long-render window) also
    catches missing or incompatible selections before submission.
    """
    if not selections:
        return copy.deepcopy(graph)
    import folder_paths
    return apply_to_graph(graph, 'ltx25', selections,
                          folder_paths.get_filename_list('loras'),
                          folder_paths.get_full_path)


def apply_studio_video_loras(graph, family, selections, registered_names, get_path):
    """Patch a supplied prompt without executing it, with distinct Wan phases."""
    if family not in ('h3', 'wan22_high', 'wan22_low', 'ltx25') or not isinstance(graph, dict) or not 1 <= len(graph) <= 512 or not isinstance(selections, list):
        raise ValueError('Choose a supported video model and installed LoRAs.')
    if any(not isinstance(node, dict) or not isinstance(node.get('inputs', {}), dict) for node in graph.values()):
        raise ValueError('The video graph is not valid.')
    target = None
    if family in ('wan22_high', 'wan22_low'):
        phase = family.rsplit('_', 1)[-1]
        identity = phase + '_model'
        node = graph.get(identity, {})
        if not isinstance(node, dict) or not isinstance(node.get('inputs'), dict):
            raise ValueError('The selected Wan noise phase does not match this graph.')
        name = str(node['inputs'].get('unet_name', '')).lower().replace('\\', '/')
        if node.get('class_type') != 'UNETLoader' or ('_' + phase + '_noise_') not in name or 'wan2.2' not in name:
            raise ValueError('The selected Wan noise phase does not match this graph.')
        other = 'low' if phase == 'high' else 'high'
        if any(isinstance(item, dict) and (other + '_noise') in str(item.get('name', '')).lower().replace('-', '_') for item in selections):
            raise ValueError('This LoRA is named for the other Wan noise phase. Choose the matching phase.')
        target = {'target_ids': [identity], 'namespace': phase}
        family = 'wan22'
    return apply_to_graph(graph, family, selections, registered_names, get_path, **(target or {}))


IMAGE_FAMILIES = {
    "flux2": ("flux2_klein9b", "flux-2-klein-9b-fp8.safetensors"),
    "klein9b": ("flux2_klein9b", "flux-2-klein-9b-fp8.safetensors"),
    "flux3": ("flux3_klein", "flux3-image-klein-int8-convrot.safetensors"),
    "qwen2511": ("qwen2511", "qwen_image_edit_2511_int8_convrot.safetensors"),
    "zimage": ("zimage", "z_image_turbo_bf16.safetensors"),
}


def validate_image_loras(model, selections, registered_names, get_path):
    """Validate the same sampler model used by the frontend's native image recipe."""
    if model not in IMAGE_FAMILIES:
        raise ValueError("Custom image LoRAs are not supported for this model.")
    family, checkpoint = IMAGE_FAMILIES[model]
    graph = {"model": {"class_type": "UNETLoader", "inputs": {"unet_name": checkpoint}},
             "consumer": {"class_type": "Example", "inputs": {"model": ["model", 0]}}}
    patched = apply_to_graph(graph, family, selections, registered_names, get_path)
    return [{"name": patched[f"zura_custom_lora_0_{i}"]["inputs"]["lora_name"],
             "strength": patched[f"zura_custom_lora_0_{i}"]["inputs"]["strength_model"]}
            for i in range(len(selections))]
