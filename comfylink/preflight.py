"""Validate graph bindings and installed model paths without loading models."""
import importlib.util
import os
from pathlib import Path, PurePosixPath
import sys


def inspect_graph(graph, input_binding, output_binding, available):
    errors = []
    if not isinstance(graph, dict) or not graph or len(graph) > 5000:
        return {"ready": False, "errors": ["Expected a non-empty API-format graph of at most 5000 nodes."], "missing_nodes": []}
    for node_id, node in graph.items():
        if not isinstance(node_id, str) or not isinstance(node, dict) or not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
            return {"ready": False, "errors": ["Expected API-format nodes with class_type and inputs; export API JSON from ComfyUI."], "missing_nodes": []}
    missing = sorted({node["class_type"] for node in graph.values()} - set(available))
    if missing:
        errors.append("Required node types are missing.")
    if not isinstance(input_binding, dict) or not isinstance(output_binding, dict):
        return {"ready": False, "errors": errors + ["Explicit input and output bindings are required."], "missing_nodes": missing}
    in_id, out_id = input_binding.get("node"), output_binding.get("node")
    field = input_binding.get("field")
    if not all(isinstance(value, str) for value in (in_id, out_id, field)):
        return {"ready": False, "errors": errors + ["Binding node IDs and input field must be strings."], "missing_nodes": missing}
    if in_id not in graph or field not in graph.get(in_id, {}).get("inputs", {}):
        errors.append("Input binding does not identify an existing node field.")
    if out_id not in graph:
        errors.append("Output binding does not identify an existing node.")
    elif graph[out_id]["class_type"] not in ("SaveVideo", "SaveImage", "PreviewImage", "VHS_VideoCombine", "ZuraComfyLinkSaveFloatFrames"):
        errors.append("Output binding must identify a supported output node.")
    if in_id in graph and out_id in graph:
        seen, pending = set(), [out_id]
        while pending:
            node_id = pending.pop()
            if node_id in seen:
                continue
            seen.add(node_id)
            for value in graph[node_id]["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
                    if value[0] not in graph:
                        errors.append("Graph has a link to a missing node.")
                    else:
                        pending.append(value[0])
        if in_id not in seen:
            errors.append("The selected output does not depend on the selected input.")
    if in_id in graph and out_id in graph and (graph[in_id]["class_type"] == "ZuraComfyLinkLoadFloatFrames" or graph[out_id]["class_type"] == "ZuraComfyLinkSaveFloatFrames"):
        if graph[in_id]["class_type"] != "ZuraComfyLinkLoadFloatFrames" or field != "manifest" or graph[out_id]["class_type"] != "ZuraComfyLinkSaveFloatFrames":
            errors.append("Float transfer requires a typed manifest loader and float saver.")
        else:
            def reaches_input(value):
                if not isinstance(value, list) or len(value) != 2 or not isinstance(value[0], str):
                    return False
                seen, pending = set(), [value[0]]
                while pending:
                    current = pending.pop()
                    if current == in_id:
                        return True
                    if current in seen or current not in graph:
                        continue
                    seen.add(current)
                    for link in graph[current]["inputs"].values():
                        if isinstance(link, list) and len(link) == 2 and isinstance(link[0], str):
                            pending.append(link[0])
                return False
            if not all(reaches_input(graph[out_id]["inputs"].get(name)) for name in ("images", "frame_metadata")):
                errors.append("Float saver images and metadata must depend on the selected float input.")
    return {"ready": not errors, "errors": errors, "missing_nodes": missing,
            "models": "not_checked", "inference": "not_run",
            "trust_warning": "Workflows can execute installed custom-node code. Import only graphs you trust."}


def _model_name_valid(category, name):
    if not isinstance(category, str) or not category or len(category) > 120 or any(c in category for c in "/\\\0"):
        return False
    if not isinstance(name, str) or not name or len(name) > 1024 or "\0" in name:
        return False
    normal = name.replace("\\", "/")
    parts = normal.split("/")
    return not (PurePosixPath(normal).is_absolute() or any(p in ("", ".", "..") or ":" in p for p in parts))


def _mask_requirements(available):
    """Read the loaded Zura node's own model constants; avoid guessing other packs."""
    cls = available.get("TrendStudioV2MaskPerformer")
    if cls is None or getattr(cls, "__name__", "") != "ZuraMask":
        return [], False
    prepare = getattr(cls, "prepare", None)
    namespace = getattr(prepare, "__globals__", {})
    detect = namespace.get("detect")
    module = sys.modules.get(getattr(detect, "__module__", ""))
    segment_model = getattr(module, "MODEL_NAME", None)
    pose = namespace.get("_run_pose_face")
    code = getattr(pose, "__code__", None)
    pose_names = [x for x in (code.co_consts if code else ()) if isinstance(x, str) and x.endswith(".onnx")]
    if not isinstance(segment_model, str) or len(set(pose_names)) != 2:
        return [], False
    return ([{"category": "ultralytics", "name": "segm/" + segment_model, "fallback": "ultralytics"}]
            + [{"category": "detection", "name": name} for name in pose_names]), True


def _model_status(folders, requirement):
    category, name = requirement["category"], requirement["name"]
    result = {"category": category, "name": name, "status": "not_resolvable"}
    try:
        roots = folders.get_folder_paths(category)
    except (KeyError, AttributeError, TypeError):
        roots = []
    result["available_roots"] = sum(1 for root in roots if os.path.isdir(root) and os.access(root, os.R_OK | os.X_OK))
    result["unavailable_roots"] = len(roots) - result["available_roots"]
    try:
        path = folders.get_full_path(category, name)
    except (AttributeError, KeyError, TypeError, ValueError, OSError):
        path = None
    if not path and requirement.get("fallback") == "ultralytics":
        # segmentation._model_path uses this fallback when the category isn't registered.
        root = getattr(folders, "models_dir", None)
        fallback = Path(root) / "ultralytics" / name if root else None
        if fallback and fallback.is_file():
            path = str(fallback)
            result["resolution"] = "default_model_fallback"
    if not path:
        return result
    try:
        if not Path(path).is_file():
            return result
        with open(path, "rb") as model:
            model.read(1)
    except OSError:
        result["status"] = "unreadable"
        return result
    result["status"] = "resolved"
    result.setdefault("resolution", "category")
    return result


def inspect_requirements(graph, available, folders, preset_id=None, declared=None, canonical_match=False):
    """Report only checks we can establish; a resolved file is not an inference test."""
    requirements, complete, errors = [], False, []
    builtins = {"01-roundtrip", "02-invert", "03-batch-invert", "native-video-roundtrip"}
    mask_presets = {"zura-character-mask-video", "zura-character-matte-video"}
    missing_dependencies = []
    has_mask = isinstance(graph, dict) and any(
        isinstance(node, dict) and node.get("class_type") == "TrendStudioV2MaskPerformer"
        for node in graph.values())
    if canonical_match and preset_id in builtins:
        complete = True
    if has_mask:
        requirements, mask_known = _mask_requirements(available)
        if canonical_match and preset_id in mask_presets:
            complete = mask_known
        for name in ("OnnxDetectionModelLoader", "PoseAndFaceDetection", "DrawViTPose"):
            if name not in available:
                missing_dependencies.append(name)
        for package in ("ultralytics", "onnxruntime"):
            try:
                installed = importlib.util.find_spec(package) is not None
            except (ImportError, ValueError):
                installed = False
            if not installed:
                missing_dependencies.append(package)
    if declared is not None:
        if not isinstance(declared, list) or len(declared) > 256:
            errors.append("required_models must be a list of at most 256 category/name objects.")
        else:
            for item in declared:
                if not isinstance(item, dict) or not _model_name_valid(item.get("category"), item.get("name")):
                    errors.append("Each required model needs a category and a safe relative name.")
                else:
                    requirements.append({"category": item["category"], "name": item["name"]})
    unique = {}
    for item in requirements:
        if not _model_name_valid(item.get("category"), item.get("name")):
            errors.append("The loaded node declares an invalid model name.")
            complete = False
            continue
        key = item["category"], item["name"]
        if key not in unique:
            unique[key] = item
    models = [_model_status(folders, item) for item in unique.values()]
    return {"models": models, "model_requirements": "complete" if complete else "unknown",
            "missing_dependencies": missing_dependencies, "errors": errors}
