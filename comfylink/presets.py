"""Versioned ComfyLink graph catalogue; graph bytes retain their MIT provenance."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

CATALOGUE_DIR = Path(__file__).with_name("catalogue")
SCHEMA_VERSION = 1


def _sorted_maps(value):
    if isinstance(value, dict):
        return {key: _sorted_maps(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted_maps(item) for item in value]
    return value


def graph_hash(graph):
    # Match Go's json.Marshal(map[string]Node): maps are sorted but Node has
    # fixed field order. Keep original number spellings in the stored graphs.
    ordered = {}
    for key in sorted(graph):
        node = graph[key]
        ordered[key] = {"class_type": node["class_type"], "inputs": _sorted_maps(node["inputs"])}
        if node.get("_meta"):
            ordered[key]["_meta"] = _sorted_maps(node["_meta"])
    raw = json.dumps(ordered, separators=(",", ":"), ensure_ascii=False)
    for char, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        raw = raw.replace(char, escaped)
    return sha256(raw.encode("utf-8")).hexdigest()


def _entry(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    graph = data["workflow"]
    inputs = data.get("input") or {"node": "1", "field": "file"}
    output = data.get("output") or {"node": "2"}
    video = data["mode"] == "video"
    mask = data["id"] in ("zura-character-mask-video", "zura-character-matte-video")
    return {
        **data,
        "schemaVersion": SCHEMA_VERSION,
        "revision": data.get("revision") or "legacy-1",
        "workflowHash": graph_hash(graph),
        "input": inputs,
        "output": {**output, "field": "filename_prefix"},
        "media_type": "video" if video else "frames",
        "outputRole": "matte" if data["id"] == "zura-character-matte-video" else "replacement",
        "range_modes": ["work_area", "layer_duration"] if video else ["current_frame", "work_area", "layer_duration"],
        "required_nodes": sorted({node["class_type"] for node in graph.values()}),
        "required_models": None if mask else [],
        "parameters": [],
        "minimum_protocol": "1",
        "color_alpha": "workflow-defined; no automatic HDR or alpha conversion",
        "duration_policy": "match input",
        "dimensions_policy": "match input",
    }


def catalogue():
    return [_entry(path) for path in sorted(CATALOGUE_DIR.glob("*.json"))]


def preset_by_id(preset_id):
    for preset in catalogue():
        if preset["id"] == preset_id:
            return deepcopy(preset)
    return None
