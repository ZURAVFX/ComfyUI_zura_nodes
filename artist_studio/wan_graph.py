"""Metadata-only planning for the persistent, bounded Wan graph workflow.

The planner never evaluates a Comfy node or reads tensor/media/model contents.
It scans bounded preparation receipts and uses file stamps only.  Actual source
approval remains enforced by GenjLoadReviewedShot and the native preparation
workers when a graph is queued.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any


SCHEMA = "zura_wan_graph_context_v1"
PLAN_SCHEMA = "zura_wan_graph_plan_v1"
GRAPH_GUARD = "ZuraWanGraphQueueGuard"
WINDOW = "ZuraWanPreparationWindow"
CARRY = "ZuraWanCarryPoseWindow"
PART_SAVER = "ZuraWanSavePreparationPart"
MERGE = "ZuraWanMergePreparation"
SHOT = "GenjLoadReviewedShot"
MAX_GRAPH_BYTES = 16 * 1024 * 1024
MAX_RECEIPTS = 4096
JS_MAX_SAFE_INTEGER = 9_007_199_254_740_991
KEY_RE = re.compile(r"[a-f0-9]{64}")
SHOT_RE = re.compile(r"shot_[a-f0-9]{16}")
RESOLUTIONS = (256, 512, 768, 960, 1280, 1920)


class WanGraphPlanError(ValueError):
    """The current editable graph or its persistent motion context is unsafe."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _runtime_is_changed_size(value: Any) -> int:
    """Bound Comfy's non-semantic per-node cache marker without hashing it.

    ``IsChangedCache`` adds this node-level field to DynamicPrompt during native
    execution. Always-refresh nodes can contribute NaN, which is not JSON, but
    this runtime value is not part of an artist's graph recipe. Count its
    bounded JSON-shaped representation toward the prompt size limit, mapping
    non-finite numbers only inside this one runtime field.
    """
    def json_safe_marker(item: Any) -> Any:
        if type(item) is float and not math.isfinite(item):
            if math.isnan(item):
                return "<comfy-is-changed-nan>"
            return "<comfy-is-changed-positive-infinity>" if item > 0 else "<comfy-is-changed-negative-infinity>"
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise TypeError("Comfy runtime marker has a non-string key")
            return {key: json_safe_marker(child) for key, child in item.items()}
        if type(item) in (list, tuple):
            return [json_safe_marker(child) for child in item]
        if item is None or type(item) in (bool, int, float, str):
            return item
        raise TypeError("Comfy runtime marker is not JSON-shaped")

    return len(canonical(json_safe_marker(value)).encode("utf-8"))


def _key_number_value(value: Any) -> Any:
    """Normalise only integral floats in key payloads for JS JSON stability."""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _key_number_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_key_number_value(item) for item in value]
    return value


def canonical_key_payload(value: Any) -> str:
    """Canonicalise a context key without stripping workflow or metadata keys."""
    return canonical(_key_number_value(value))


def _browser_timestamp(value: Any) -> Any:
    """Keep nanosecond file timestamps exact across JavaScript JSON numbers."""
    if type(value) is int and abs(value) > JS_MAX_SAFE_INTEGER:
        return str(value)
    if (type(value) is str and len(value) <= 20 and
            re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value) and
            abs(int(value)) > JS_MAX_SAFE_INTEGER):
        return value
    return value


def _browser_stamp_snapshot(stamps: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(stamps)
    for stamp in result.values():
        if type(stamp) is dict and "mtime_ns" in stamp:
            stamp["mtime_ns"] = _browser_timestamp(stamp["mtime_ns"])
    return result


def _browser_file_pin(pin: dict[str, Any] | None) -> dict[str, Any] | None:
    result = copy.deepcopy(pin)
    if result is not None and "mtime_ns" in result:
        result["mtime_ns"] = _browser_timestamp(result["mtime_ns"])
    return result


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not KEY_RE.fullmatch(value):
        raise WanGraphPlanError(f"The Wan {label} pin is malformed.")
    return value


def _link(value: Any, graph: dict[str, dict[str, Any]]) -> tuple[str, int] | None:
    """Recognise only a valid Comfy prompt edge, never an arbitrary pair."""
    if (type(value) is not list or len(value) != 2 or type(value[0]) is not str or
            type(value[1]) is not int or value[1] < 0 or value[0] not in graph):
        return None
    return value[0], value[1]


def _normalise_prompt(prompt: Any) -> dict[str, dict[str, Any]]:
    if type(prompt) is not dict or not prompt or len(prompt) > 10000:
        raise WanGraphPlanError("The compiled Wan graph is empty or malformed.")
    normalized: dict[str, dict[str, Any]] = {}
    runtime_marker_bytes = 0
    for identity, node in prompt.items():
        if type(identity) is not str or not identity or type(node) is not dict:
            raise WanGraphPlanError("The compiled Wan graph contains an invalid node.")
        class_type, inputs = node.get("class_type"), node.get("inputs")
        if not isinstance(class_type, str) or not class_type or type(inputs) is not dict:
            raise WanGraphPlanError("The compiled Wan graph contains an invalid node input map.")
        if "is_changed" in node:
            try:
                runtime_marker_bytes += _runtime_is_changed_size(node["is_changed"])
            except (TypeError, ValueError, RecursionError) as error:
                raise WanGraphPlanError("The compiled Wan graph has an invalid Comfy runtime cache marker.") from error
        # This exact node-level key is injected by Comfy's IsChangedCache and
        # does not describe inference. Keep every other node property and all
        # artist inputs (including an input literally named ``is_changed``).
        normalized[identity] = {key: value for key, value in node.items() if key != "is_changed"}
    try:
        size = len(canonical(normalized).encode("utf-8")) + runtime_marker_bytes
    except (TypeError, ValueError, RecursionError) as error:
        raise WanGraphPlanError("The compiled Wan graph is not serialisable JSON.") from error
    if size > MAX_GRAPH_BYTES:
        raise WanGraphPlanError("The compiled Wan graph exceeds its metadata limit.")
    return normalized


def _stage_keys(node: dict[str, Any]) -> list[str]:
    raw = node.get("inputs", {}).get("keys")
    if not isinstance(raw, str) or len(raw) > 8192:
        raise WanGraphPlanError("A graph stage hand-off has invalid signal names.")
    try:
        keys = json.loads(raw)
    except (json.JSONDecodeError, RecursionError) as error:
        raise WanGraphPlanError("A graph stage hand-off has invalid signal names.") from error
    if (type(keys) is not list or len(keys) > 64 or
            any(type(key) is not str or not key or len(key) > 256 for key in keys) or
            len(set(keys)) != len(keys)):
        raise WanGraphPlanError("A graph stage hand-off has invalid signal names.")
    return keys


def expand_stage_signals(prompt: Any) -> dict[str, dict[str, Any]]:
    """Expand ZuraStudioSignals exactly as the graph view does.

    Only a valid link to an actual ZuraStudioReadSignal is expanded.  Literal
    values (including two-item JSON arrays that do not identify a live signal
    node and output) are returned unchanged.
    """
    graph = _normalise_prompt(prompt)
    signals = {"ZuraStudioSignals", "ZuraStudioReadSignal"}
    stack: set[tuple[str, str]] = set()

    def read_signal(identity: str, key: str) -> Any:
        marker = (identity, key)
        if marker in stack:
            raise WanGraphPlanError("A Wan stage hand-off contains a cycle.")
        node = graph.get(identity)
        if not node or node["class_type"] != "ZuraStudioSignals":
            raise WanGraphPlanError("A Wan stage hand-off is missing its signal pack.")
        keys = _stage_keys(node)
        inputs = node["inputs"]
        stack.add(marker)
        try:
            if key in keys:
                slot = "value_" + str(keys.index(key))
                if slot not in inputs:
                    raise WanGraphPlanError("A Wan stage hand-off is missing a connected value.")
                return resolve_value(inputs[slot])
            previous = _link(inputs.get("previous"), graph)
            if previous is None or previous[1] != 0:
                raise WanGraphPlanError("A Wan stage hand-off value is missing.")
            previous_node = graph[previous[0]]
            if previous_node["class_type"] != "ZuraStudioSignals":
                raise WanGraphPlanError("A Wan stage hand-off chain is malformed.")
            return read_signal(previous[0], key)
        finally:
            stack.remove(marker)

    def resolve_value(value: Any) -> Any:
        edge = _link(value, graph)
        if edge is None:
            return copy.deepcopy(value)
        identity, output = edge
        node = graph[identity]
        if node["class_type"] != "ZuraStudioReadSignal":
            return copy.deepcopy(value)
        if output != 0:
            raise WanGraphPlanError("A graph signal reader uses an invalid output.")
        inputs = node["inputs"]
        pack = _link(inputs.get("stage_data"), graph)
        key = inputs.get("key")
        if (pack is None or pack[1] != 0 or type(key) is not str or not key or
                graph[pack[0]]["class_type"] != "ZuraStudioSignals"):
            raise WanGraphPlanError("A graph signal reader is malformed.")
        return read_signal(pack[0], key)

    # Validate every declared key and reader, including currently unused ones,
    # so a malformed or cyclic side chain cannot hide in the saved workflow.
    for identity, node in graph.items():
        if node["class_type"] == "ZuraStudioSignals":
            for key in _stage_keys(node):
                read_signal(identity, key)
        elif node["class_type"] == "ZuraStudioReadSignal":
            inputs = node["inputs"]
            pack = _link(inputs.get("stage_data"), graph)
            key = inputs.get("key")
            if (pack is None or pack[1] != 0 or type(key) is not str or not key or
                    graph[pack[0]]["class_type"] != "ZuraStudioSignals"):
                raise WanGraphPlanError("A graph signal reader is malformed.")
            read_signal(pack[0], key)

    expanded: dict[str, dict[str, Any]] = {}
    for identity, node in graph.items():
        if node["class_type"] in signals:
            continue
        expanded[identity] = {
            "class_type": node["class_type"],
            "inputs": {name: resolve_value(value) for name, value in node["inputs"].items()},
            **({"_meta": copy.deepcopy(node["_meta"])} if "_meta" in node else {}),
        }
    return expanded


def _stable_value(value: Any) -> Any:
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _stable_value(item) for key, item in sorted(value.items()) if key not in ("ui", "_meta")}
    if isinstance(value, list):
        return [_stable_value(item) for item in value]
    return value


BOOKKEEPING_INPUTS = {
    WINDOW: {"start_frame", "frame_count"},
    CARRY: {"cache_key"},
    PART_SAVER: {"cache_key"},
    GRAPH_GUARD: {"plan_json"},
}

# Native graph import materialises these optional empty string widgets even
# when the API builder omits them. Their implementations use the same empty
# behaviour for omission; nonempty values still belong to the recipe.
EMPTY_OPTIONAL_INPUTS = {
    "SAM3_Detect": {"positive_coords", "negative_coords"},
    CARRY: {"speech_guide_key", "speech_guide_sha"},
    PART_SAVER: {"speech_guide_key", "speech_guide_sha"},
}


def _node_fingerprint(identity: str, graph: dict[str, dict[str, Any]],
                      visiting: set[str], memo: dict[str, str],
                      guide_loader_id: str | None = None) -> str:
    if identity in memo:
        return memo[identity]
    if identity in visiting:
        raise WanGraphPlanError("The native Wan preparation graph contains a cycle.")
    node = graph.get(identity)
    if node is None:
        raise WanGraphPlanError("The native Wan preparation graph has a dangling connection.")
    if node["class_type"] == GRAPH_GUARD:
        raise WanGraphPlanError("The queue guard cannot be part of the preparation recipe.")
    visiting.add(identity)
    fields = {}
    ignored = BOOKKEEPING_INPUTS.get(node["class_type"], set())
    if identity == guide_loader_id:
        # These two inputs are the section cursor for the selected facial
        # guide. They are guarded runtime bookkeeping only on this exact
        # loader; other VHS nodes remain part of the artist's recipe.
        ignored = ignored | {"frame_load_cap", "start_time"}
    for name, value in sorted(node["inputs"].items()):
        if name in ignored:
            continue
        if (name in EMPTY_OPTIONAL_INPUTS.get(node["class_type"], set()) and
                type(value) is str and value == ""):
            continue
        edge = _link(value, graph)
        if edge is None:
            fields[name] = _stable_value(value)
        else:
            upstream, output = edge
            fields[name] = ["link", _node_fingerprint(upstream, graph, visiting, memo,
                                                       guide_loader_id), output]
    visiting.remove(identity)
    digest = hashlib.sha256(canonical([node["class_type"], fields]).encode("utf-8")).hexdigest()
    memo[identity] = digest
    return digest


def preparation_fingerprint(prompt: Any, saver_id: str | None = None,
                            guide_loader_id: str | None = None) -> str:
    graph = expand_stage_signals(prompt)
    savers = [identity for identity, node in graph.items() if node["class_type"] == PART_SAVER]
    if saver_id is None:
        if len(savers) != 1:
            raise WanGraphPlanError("The Wan graph needs exactly one bounded preparation saver.")
        saver_id = savers[0]
    if saver_id not in graph or graph[saver_id]["class_type"] != PART_SAVER:
        raise WanGraphPlanError("The Wan graph has no bounded preparation saver.")
    if guide_loader_id is not None and (
            guide_loader_id not in graph or
            graph[guide_loader_id]["class_type"] != "VHS_LoadVideoFFmpegPath"):
        raise WanGraphPlanError("The selected speech guide loader changed during planning.")
    return _node_fingerprint(saver_id, graph, set(), {}, guide_loader_id)


def _role_id(role: str, identity: str, graph: dict[str, dict[str, Any]]) -> str:
    # Structural role discovery guarantees uniqueness. Keep this tag stable
    # when artists edit native settings; recipe identity is tracked separately.
    return "zura.wan." + role


def _find_one(graph: dict[str, dict[str, Any]], class_type: str, label: str) -> str:
    found = [identity for identity, node in graph.items() if node["class_type"] == class_type]
    if len(found) != 1:
        raise WanGraphPlanError(f"The Wan graph needs exactly one {label} node.")
    return found[0]


def _require_edge(graph: dict[str, dict[str, Any]], node_id: str, field: str,
                  expected_id: str, expected_output: int, message: str) -> None:
    if _link(graph[node_id]["inputs"].get(field), graph) != (expected_id, expected_output):
        raise WanGraphPlanError(message)


def _ancestor_ids(graph: dict[str, dict[str, Any]], value: Any) -> set[str]:
    result: set[str] = set()
    visiting: set[str] = set()

    def visit(value: Any) -> None:
        edge = _link(value, graph)
        if edge is None:
            return
        identity, _ = edge
        if identity in visiting:
            raise WanGraphPlanError("The Wan graph contains a cyclic native connection.")
        if identity in result:
            return
        result.add(identity)
        visiting.add(identity)
        for child in graph[identity]["inputs"].values():
            visit(child)
        visiting.remove(identity)

    visit(value)
    return result


def _depends_on_file(graph: dict[str, dict[str, Any]], value: Any, file_path: str) -> bool:
    expected = os.path.normcase(os.path.normpath(file_path))
    for identity in _ancestor_ids(graph, value):
        node = graph[identity]
        if node["class_type"] == "LoadImage":
            image = node["inputs"].get("image")
            if type(image) is str and os.path.normcase(os.path.normpath(image)) == expected:
                return True
    return False


def _output_of(graph: dict[str, dict[str, Any]], value: Any, class_type: str,
               field: str, label: str) -> tuple[str, dict[str, Any]]:
    edge = _link(value, graph)
    if edge is None or edge[1] < 0 or graph[edge[0]]["class_type"] != class_type:
        raise WanGraphPlanError(f"The Wan graph's {label} must come from {class_type}.")
    return edge[0], graph[edge[0]]


def _guide_metadata(graph: dict[str, dict[str, Any]], face_detector_id: str,
                    carry: dict[str, Any], saver: dict[str, Any], project: dict[str, Any],
                    root: Path) -> tuple[dict[str, Any] | None, str | None, int | None]:
    inputs = carry["inputs"]
    save_inputs = saver["inputs"]
    carry_key = inputs.get("speech_guide_key", "")
    carry_sha = inputs.get("speech_guide_sha", "")
    save_key = save_inputs.get("speech_guide_key", "")
    save_sha = save_inputs.get("speech_guide_sha", "")
    wants_guide = bool(project.get("audio")) and bool(project.get("config", {}).get("lip_sync"))
    if not wants_guide:
        if any((carry_key, carry_sha, save_key, save_sha)):
            raise WanGraphPlanError("The graph includes a speech guide that is not approved by this shot.")
        return None, None, None
    key = _sha(carry_key, "speech guide")
    guide_sha = _sha(carry_sha, "speech guide file")
    if (save_key != key or save_sha != guide_sha or
            graph[face_detector_id]["class_type"] != "PoseAndFaceDetection"):
        raise WanGraphPlanError("The graph's facial guide pins do not match its approved face route.")
    guide_input = graph[face_detector_id]["inputs"].get("images")
    loader_id, loader = _output_of(graph, guide_input, "VHS_LoadVideoFFmpegPath", "video", "facial guide")
    guide_path = loader["inputs"].get("video")
    if type(guide_path) is not str or not Path(guide_path).is_absolute():
        raise WanGraphPlanError("The graph's facial guide path is invalid.")
    from ..wan_preparation_runtime import confined, read_json
    manifest_path = root / "genj" / "wan_speech_guides" / (key + ".json")
    record, record_sha = read_json(manifest_path, root, 2 * 1024 * 1024)
    key_data = record.get("key_data")
    if (record.get("state") != "complete" or record.get("guide_key") != key or
            record.get("sha") != guide_sha or type(key_data) is not dict or
            hashlib.sha256(canonical(key_data).encode("utf-8")).hexdigest() != key):
        raise WanGraphPlanError("The saved facial guide metadata no longer matches the graph pins.")
    source = key_data.get("source")
    config = project.get("config", {})
    expected_audio = project.get("audio", {})
    if (key_data.get("preparation_approval") != project.get("approval") or
            key_data.get("opening_sha") != project.get("opening_input", {}).get("sha") or
            key_data.get("opening_approval") != project.get("opening_approval") or
            type(source) is not dict or source.get("review") != project.get("review") or
            source.get("source_sha") != project.get("source", {}).get("sha") or
            key_data.get("audio_sha") != expected_audio.get("sha") or
            key_data.get("audio_start") != float(config.get("audio_start", 0))):
        raise WanGraphPlanError("The saved facial guide belongs to another reviewed shot or voice.")
    source_frames = source.get("frames")
    if type(source_frames) is not int or not 1 <= source_frames <= 1_000_000:
        raise WanGraphPlanError("The approved facial guide has an invalid source timeline.")
    expected_dir = root / "genj" / "wan_speech_guides"
    guide_file = confined(Path(guide_path), root)
    if (Path(record.get("path", "")) != guide_file or guide_file.parent != expected_dir or
            not guide_file.name.startswith(key + "_") or guide_file.suffix.lower() != ".mp4"):
        raise WanGraphPlanError("The facial guide file path does not match its approved metadata.")
    stat = guide_file.stat()
    if not guide_file.is_file() or stat.st_size < 1:
        raise WanGraphPlanError("The approved facial guide file is missing.")
    return ({"guide_key": key, "guide_sha": guide_sha, "path": str(guide_file),
             "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "manifest_sha256": record_sha},
            loader_id, source_frames)


def _expected_scope(project: dict[str, Any]) -> str:
    config = project["config"]
    custom = config.get("edit_area", "mask") == "scene" or config.get("mask_method", "auto") != "auto"
    return "person" if custom else config.get("scope")


def _project_pins(project: Any) -> dict[str, Any]:
    if type(project) is not dict or type(project.get("config")) is not dict:
        raise WanGraphPlanError("Open an approved Wan shot before planning graph sections.")
    config = project["config"]
    if config.get("engine") != "wan":
        raise WanGraphPlanError("Wan graph mode needs an approved Wan project.")
    review = project.get("review")
    if type(review) is not str or not SHOT_RE.fullmatch(review):
        raise WanGraphPlanError("The Wan project has no approved reviewed shot.")
    project_id = project.get("id")
    if type(project_id) is not str or not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise WanGraphPlanError("The Wan project identity is invalid.")
    source, character, opening = project.get("source"), project.get("character"), project.get("opening_input")
    if type(source) is not dict or type(character) is not dict or type(opening) is not dict:
        raise WanGraphPlanError("The Wan project is missing its approved source or appearance references.")
    source_sha = _sha(source.get("sha"), "source")
    character_sha = _sha(character.get("sha"), "character appearance")
    opening_sha = _sha(opening.get("sha"), "opening appearance")
    approval = _sha(project.get("approval"), "mask approval")
    opening_key = _sha(project.get("opening_key"), "opening review")
    opening_approval = project.get("opening_approval")
    if opening_approval != opening_key:
        raise WanGraphPlanError("Approve the opening appearance before planning Wan motion.")
    # PREP_KEY is a pure hash of the Studio snapshot; it does not inspect asset
    # contents. The queue-time Genj loader remains the full SHA verifier.
    try:
        from .studio import prep_key
        if approval != prep_key(project):
            raise WanGraphPlanError("The Wan project's mask approval is stale. Review the mask again.")
    except WanGraphPlanError:
        raise
    except Exception as error:
        raise WanGraphPlanError("The Wan project approval cannot be verified.") from error
    # The saved project's resolution is not authoritative in editable Graph
    # view. The compiled reviewed-shot loader selects 1280 or 1920 later.
    resolution = config.get("resolution")
    scope = _expected_scope(project)
    if scope not in ("person", "head"):
        raise WanGraphPlanError("The approved Wan replacement scope is invalid.")
    audio = project.get("audio") or {}
    if audio and type(audio) is not dict:
        raise WanGraphPlanError("The approved Wan audio selection is malformed.")
    audio_sha = audio.get("sha", "")
    if audio and not audio_sha:
        raise WanGraphPlanError("The approved Wan audio selection has no content pin.")
    if audio_sha:
        audio_sha = _sha(audio_sha, "audio")
    lip_sync = config.get("lip_sync", False)
    if type(lip_sync) is not bool or (lip_sync and not audio_sha):
        raise WanGraphPlanError("The approved Wan speech setting has no matching audio track.")
    audio_start = config.get("audio_start", 0)
    if (type(audio_start) not in (int, float) or not math.isfinite(audio_start) or
            audio_start < 0):
        raise WanGraphPlanError("The approved audio in-point is malformed.")
    start = config.get("start", 0)
    duration = config.get("duration", 0)
    length_mode = config.get("length_mode", "custom")
    if (type(start) not in (int, float) or not math.isfinite(start) or start < 0 or
            type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0 or
            length_mode not in ("custom", "original")):
        raise WanGraphPlanError("The approved source interval is malformed.")
    return {
        "project_id": project_id,
        "review": review,
        "source_sha": source_sha,
        "source_file": source.get("file"),
        "approval": approval,
        "character_sha": character_sha,
        "character_file": character.get("file"),
        "opening_sha": opening_sha,
        "opening_key": opening_key,
        "opening_approval": opening_approval,
        "audio_sha": audio_sha,
        "audio_start": float(audio_start),
        "lip_sync": lip_sync,
        "start": float(start),
        "duration": float(duration),
        "length_mode": length_mode,
        "resolution": resolution,
        "scope": scope,
    }


def _review_metadata(root: Path, pins: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str], str]:
    from ..wan_preparation_runtime import read_json
    manifest_path = root / "genj" / "reviews" / pins["review"] / "review.json"
    manifest, manifest_sha = read_json(manifest_path, root, 1024 * 1024)
    clip, files = manifest.get("clip"), manifest.get("files")
    if (manifest.get("shot_id") != pins["review"] or type(clip) is not dict or type(files) is not dict or
            type(clip.get("frames")) is not int or clip["frames"] < 1 or
            clip.get("fps") != 24 or clip.get("source_hash") != pins["source_sha"]):
        raise WanGraphPlanError("The approved review metadata no longer matches this Wan project.")
    try:
        clip_start, clip_duration = float(clip.get("start")), float(clip.get("duration"))
    except (TypeError, ValueError) as error:
        raise WanGraphPlanError("The reviewed source interval is missing or malformed.") from error
    if (not math.isfinite(clip_start) or not math.isfinite(clip_duration) or clip_duration <= 0 or
            abs(clip_start - pins["start"]) > 1e-6 or
            clip_duration > pins["duration"] + 1e-6 or
            (pins["length_mode"] == "original" and
             (clip_start != 0 or clip.get("full_source") is not True))):
        raise WanGraphPlanError("The reviewed source interval changed. Review the selected clip again.")
    mask_sha = _sha(files.get("mask.mp4"), "review mask")
    return clip, {"manifest_sha256": manifest_sha, "mask_sha256": mask_sha}, manifest_sha


def _render_cache_paths(root: Path, review: str, resolution: int, total: int) -> dict[str, str]:
    review_dir = root / "genj" / "reviews" / review
    if resolution == 0:
        directory = review_dir
    else:
        directory = review_dir / f"render_audio_v2_{resolution}_x1_{total}f"
    return {"source": str(directory / "source.mp4"),
            "mask": str(directory / "mask.mp4")}


def _render_cache_stamps(paths: dict[str, str]) -> dict[str, Any]:
    stamps: dict[str, Any] = {}
    exists = [Path(value).exists() for value in paths.values()]
    if any(exists) and not all(exists):
        raise WanGraphPlanError("The reviewed source and mask cache is incomplete.")
    if not any(exists):
        return {name: {"path": path, "size": None, "mtime_ns": None} for name, path in paths.items()}
    for name, value in paths.items():
        path = Path(value)
        stat = path.stat()
        if (path.is_symlink() or path.resolve(strict=True) != path or
                not path.is_file() or stat.st_size < 1):
            raise WanGraphPlanError("The reviewed source or mask cache is redirected or empty.")
        stamps[name] = {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    return stamps


def _validate_roles(prompt: Any, project: dict[str, Any], pins: dict[str, Any], clip: dict[str, Any],
                    root: Path, *, require_guard_wires: bool = False) -> dict[str, Any]:
    graph = expand_stage_signals(prompt)
    old_paths = {"ZuraWanReviewedFrames", "ZuraWanPackPreparation", "GenjApplyReferenceAudio"}
    if any(node["class_type"] in old_paths for node in graph.values()):
        raise WanGraphPlanError("The graph contains the old full-frame IMAGE preparation route.")
    shot_id = _find_one(graph, SHOT, "approved reviewed-shot loader")
    window_id = _find_one(graph, WINDOW, "bounded preparation window")
    carry_id = _find_one(graph, CARRY, "pose-carry adapter")
    saver_id = _find_one(graph, PART_SAVER, "bounded preparation saver")
    guard_ids = [identity for identity, node in graph.items() if node["class_type"] == GRAPH_GUARD]
    if len(guard_ids) > 1:
        raise WanGraphPlanError("The Wan graph contains duplicate section guards.")
    shot = graph[shot_id]["inputs"]
    resolution = pins["resolution"]
    if (shot.get("shot_id") != pins["review"] or shot.get("approved_shot_id") != pins["review"] or
            shot.get("render_long_edge") != resolution or shot.get("output_scale", 1) != 1 or
            shot.get("preview_seconds", 0) != 0):
        raise WanGraphPlanError("The graph's reviewed source, approval or source resolution changed.")
    _require_edge(graph, window_id, "source", shot_id, 0,
                  "The bounded window must read the approved source VIDEO directly.")
    _require_edge(graph, window_id, "mask_video", shot_id, 1,
                  "The bounded window must read the approved mask VIDEO directly.")
    _require_edge(graph, window_id, "clip_details", shot_id, 3,
                  "The bounded window must use the approved shot's clip details.")
    carry_inputs = graph[carry_id]["inputs"]
    save_inputs = graph[saver_id]["inputs"]
    _require_edge(graph, carry_id, "window", window_id, 4,
                  "The pose carry must be bound to this bounded window.")
    _require_edge(graph, carry_id, "clip_details", shot_id, 3,
                  "The pose carry must use the approved clip details.")
    _require_edge(graph, saver_id, "window", window_id, 4,
                  "The preparation saver must own this bounded window.")
    _require_edge(graph, saver_id, "carry_state", carry_id, 1,
                  "The preparation saver must store the bounded pose carry.")
    _require_edge(graph, saver_id, "clip_details", shot_id, 3,
                  "The preparation saver must use the approved clip details.")
    if carry_inputs.get("scope") != pins["scope"] or save_inputs.get("scope") != pins["scope"]:
        raise WanGraphPlanError("The graph's preparation scope differs from the approved shot.")

    pose_detector_id, pose_detector = _output_of(
        graph, carry_inputs.get("pose_data"), "PoseAndFaceDetection", "pose_data", "pose data")
    draw_id, draw = _output_of(graph, save_inputs.get("pose"), "DrawViTPose", "pose", "drawn pose")
    if _link(draw["inputs"].get("pose_data"), graph) != (carry_id, 0):
        raise WanGraphPlanError("The drawing nodes bypass the approved Wan pose carry.")
    block_id, block = _output_of(graph, save_inputs.get("mask"), "BlockifyMask", "mask", "approved mask")
    if _link(block["inputs"].get("masks"), graph) != (window_id, 1):
        raise WanGraphPlanError("The Wan block mask is not derived from the bounded approved mask.")
    if _link(save_inputs.get("frames"), graph) != (window_id, 0):
        raise WanGraphPlanError("The preparation saver must store only bounded source frames.")
    if _link(carry_inputs.get("reference"), graph) != _link(save_inputs.get("reference"), graph):
        raise WanGraphPlanError("The pose carry and saver use different appearance references.")
    if not _depends_on_file(graph, save_inputs.get("reference"), str(pins["character_file"])):
        raise WanGraphPlanError("The preparation graph is missing its approved character reference.")
    if _link(carry_inputs.get("pose_data"), graph) != (pose_detector_id, 0):
        raise WanGraphPlanError("The pose carry is not connected to native pose detection.")

    face_detector_id, _ = _output_of(graph, save_inputs.get("face"), "PoseAndFaceDetection", "face", "face guide")
    wants_guide = bool(project.get("audio")) and bool(project.get("config", {}).get("lip_sync"))
    guide_pin, guide_loader_id, guide_total = _guide_metadata(
        graph, face_detector_id, graph[carry_id], graph[saver_id], project, root)
    if wants_guide and guide_pin is None:
        raise WanGraphPlanError("The selected speech guide is not bound to native face detection.")
    if guide_pin is not None and guide_total != clip.get("frames"):
        raise WanGraphPlanError("The selected facial guide does not cover the approved source timeline.")
    if not wants_guide and face_detector_id != pose_detector_id:
        raise WanGraphPlanError("The face route uses an unapproved external guide.")
    if guide_pin is not None:
        loader_inputs = graph[guide_loader_id]["inputs"]
        if loader_inputs.get("force_rate") not in (24, 24.0):
            raise WanGraphPlanError("The selected facial guide must be sampled at the approved 24 fps source rate.")
    # This derives the semantic roles from class and ancestry rather than the
    # original API IDs, which change when LiteGraph groups native subgraphs.
    roles = {
        "shot": shot_id,
        "window": window_id,
        "carry": carry_id,
        "saver": saver_id,
        "pose_detector": pose_detector_id,
        "pose_draw": draw_id,
        "mask_block": block_id,
        "face_detector": face_detector_id,
    }
    if guide_loader_id is not None:
        roles["guide_loader"] = guide_loader_id
    guard_id = guard_ids[0] if guard_ids else None
    if require_guard_wires:
        if guard_id is None:
            raise WanGraphPlanError("The Wan section guard is missing. Update the section before queuing.")
        for node_id, field, output in ((window_id, "start_frame", 1), (window_id, "frame_count", 2),
                                       (carry_id, "cache_key", 0), (saver_id, "cache_key", 0)):
            if _link(graph[node_id]["inputs"].get(field), graph) != (guard_id, output):
                raise WanGraphPlanError("The section guard is not wired to every bounded adapter input.")
        if guide_loader_id is not None:
            for field, output in (("frame_load_cap", 2), ("start_time", 3)):
                if _link(graph[guide_loader_id]["inputs"].get(field), graph) != (guard_id, output):
                    raise WanGraphPlanError("The section guard is not wired to the selected facial guide timeline.")
    else:
        for field in ("start_frame", "frame_count"):
            value = graph[window_id]["inputs"].get(field)
            if type(value) is not int:
                edge = _link(value, graph)
                if guard_id is None or edge is None or edge[0] != guard_id:
                    raise WanGraphPlanError("The Wan section cursor is not a literal or guarded value.")
        for node_id in (carry_id, saver_id):
            value = graph[node_id]["inputs"].get("cache_key")
            edge = _link(value, graph)
            if type(value) is not str and (guard_id is None or edge is None or edge[0] != guard_id):
                raise WanGraphPlanError("The Wan preparation cache key is not a literal or guarded value.")
        if guide_loader_id is not None:
            loader_inputs = graph[guide_loader_id]["inputs"]
            raw_start = graph[window_id]["inputs"].get("start_frame")
            raw_count = graph[window_id]["inputs"].get("frame_count")
            loader_cap = loader_inputs.get("frame_load_cap")
            loader_start = loader_inputs.get("start_time")
            if type(raw_start) is int and type(raw_count) is int:
                if (type(loader_cap) is not int or loader_cap != raw_count or
                        type(loader_start) not in (int, float) or
                        not math.isfinite(loader_start) or loader_start != raw_start / 24.0):
                    raise WanGraphPlanError("The selected facial guide range must match the bounded window.")
            elif guard_id is None or (
                    _link(loader_cap, graph) != (guard_id, 2) or
                    _link(loader_start, graph) != (guard_id, 3)):
                raise WanGraphPlanError("The selected facial guide range must be bounded by the section guard.")
    return {"graph": graph, "ids": roles, "guide_pin": guide_pin,
            "guard_id": guard_id, "pose_detector": pose_detector,
            "guide_loader_id": guide_loader_id,
            "face_detector": graph[face_detector_id], "window": graph[window_id],
            "carry": graph[carry_id], "saver": graph[saver_id], "shot": graph[shot_id]}


def _root(output_root: str | Path | None) -> Path:
    if output_root is None:
        try:
            import folder_paths
            output_root = folder_paths.get_output_directory()
        except Exception as error:
            raise WanGraphPlanError("ComfyUI's output directory is unavailable for Wan motion planning.") from error
    try:
        path = Path(output_root).resolve(strict=True)
    except OSError as error:
        raise WanGraphPlanError("ComfyUI's output directory is unavailable for Wan motion planning.") from error
    if not path.is_dir():
        raise WanGraphPlanError("ComfyUI's output path is not a directory.")
    return path


def _context_key(pins: dict[str, Any], review_pin: dict[str, str], recipe_sha: str,
                 resolution: int, scope: str, guide_pin: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    guide_identity = ({k: guide_pin[k] for k in ("guide_key", "guide_sha", "path", "manifest_sha256")}
                      if guide_pin else None)
    payload = {"schema": SCHEMA, "project_pins": pins, "review_pin": review_pin,
               "recipe_sha256": recipe_sha, "resolution": resolution,
               "scope": scope, "guide_pin": guide_identity}
    return hashlib.sha256(canonical_key_payload(payload).encode("utf-8")).hexdigest(), payload


def _validate_prior_context(context: Any, current_pins: dict[str, Any], review_pin: dict[str, str],
                            guide_pin: dict[str, Any] | None) -> dict[str, Any] | None:
    if context is None:
        return None
    if type(context) is not dict or context.get("schema") != SCHEMA:
        raise WanGraphPlanError("The saved Wan graph context is unsupported or malformed.")
    try:
        payload = context.get("key_payload")
        if (type(payload) is not dict or
                hashlib.sha256(canonical_key_payload(payload).encode("utf-8")).hexdigest() != context.get("context_key")):
            raise WanGraphPlanError("The saved Wan graph context has an invalid motion key.")
    except (TypeError, ValueError, RecursionError) as error:
        raise WanGraphPlanError("The saved Wan graph context has an invalid motion key.") from error
    if context.get("recipe_sha256") != payload.get("recipe_sha256"):
        raise WanGraphPlanError("The saved Wan graph context has an invalid motion key.")
    previous_pins = payload.get("project_pins")
    if type(previous_pins) is not dict:
        raise WanGraphPlanError("The saved Wan graph context has invalid project pins.")
    # Resolution and the graph's person/head replacement scope create separate
    # motion namespaces. Keep the reviewed shot, appearance and approval fixed
    # while allowing a fresh recipe from frame zero.
    ignored_context_fields = {"resolution", "scope"}
    if ({key: value for key, value in previous_pins.items() if key not in ignored_context_fields} !=
            {key: value for key, value in current_pins.items() if key not in ignored_context_fields}):
        raise WanGraphPlanError("The approved source, review or appearance changed. Review it before starting new motion.")
    if payload.get("review_pin") != review_pin:
        raise WanGraphPlanError("The approved review changed. Inspect it again before starting new motion.")
    old_guide = payload.get("guide_pin")
    current_guide = ({k: guide_pin[k] for k in ("guide_key", "guide_sha", "path", "manifest_sha256")}
                     if guide_pin else None)
    if old_guide != current_guide:
        raise WanGraphPlanError("The approved facial guide changed. Rebuild the section from Studio.")
    if _browser_file_pin(context.get("guide_pin")) != _browser_file_pin(guide_pin):
        raise WanGraphPlanError("The selected facial guide file changed. Rebuild the section from Studio.")
    return context


def _role_ids(info: dict[str, Any]) -> dict[str, str]:
    graph = info["graph"]
    return {name: _role_id(name, identity, graph) for name, identity in info["ids"].items()}


def _guard_plan(context_key: str, recipe_sha: str, project_pins: dict[str, Any],
                source_pin: dict[str, str], review_pin: dict[str, str], metadata: dict[str, Any],
                total: int, bound: int, start: int, count: int,
                guide_pin: dict[str, Any] | None, key_payload: dict[str, Any],
                render_stamps: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": PLAN_SCHEMA,
        "context_key": context_key,
        "recipe_sha256": recipe_sha,
        "key_payload": key_payload,
        "project_pins": project_pins,
        "source_pin": source_pin,
        "review_pin": review_pin,
        "metadata": metadata,
        "total_frames": total,
        "max_part_frames": bound,
        "render_long_edge": project_pins["resolution"],
        "scope": project_pins["scope"],
        "start_frame": start,
        "frame_count": count,
        "guide_pin": guide_pin,
        "render_cache_stamps": render_stamps,
    }


def _serialisable_context(context_key: str, key_payload: dict[str, Any], recipe_sha: str,
                          project_pins: dict[str, Any], review_pin: dict[str, str],
                          source_pin: dict[str, str], metadata: dict[str, Any], total: int,
                          bound: int, workflow: dict[str, Any], guide_pin: dict[str, Any] | None,
                          render_stamps: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "context_key": context_key,
        "key_payload": copy.deepcopy(key_payload),
        "recipe_sha256": recipe_sha,
        "project_pins": copy.deepcopy(project_pins),
        "review_pin": copy.deepcopy(review_pin),
        "source_pin": copy.deepcopy(source_pin),
        "metadata": copy.deepcopy(metadata),
        "total_frames": total,
        "max_part_frames": bound,
        "guide_pin": _browser_file_pin(guide_pin),
        "render_cache_stamps": _browser_stamp_snapshot(render_stamps),
        # This is the user's editable, serialisable API workflow. It contains
        # no tensors or media bytes and survives transitions to Finish/Render.
        "workflow_snapshot": copy.deepcopy(workflow),
    }


def _connection_patch(node_id: str, role_id: str, class_type: str,
                      connections: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"node_id": node_id, "role_id": role_id, "class_type": class_type,
            "connections": copy.deepcopy(connections)}


def _materialise_guard(graph: dict[str, Any], info: dict[str, Any], guard_id: str,
                       guard_plan_json: str) -> dict[str, Any]:
    """Put the queue-time barrier on the bounded node dependency path."""
    result = copy.deepcopy(graph)
    window_id, carry_id, saver_id = (info["ids"][name] for name in ("window", "carry", "saver"))
    guard = result.get(guard_id)
    if guard is None:
        guard = {"class_type": GRAPH_GUARD, "inputs": {"plan_json": guard_plan_json}}
        result[guard_id] = guard
    elif guard.get("class_type") != GRAPH_GUARD or type(guard.get("inputs")) is not dict:
        raise WanGraphPlanError("The Wan graph section guard changed during planning.")
    else:
        guard["inputs"]["plan_json"] = guard_plan_json
    result[window_id]["inputs"]["start_frame"] = [guard_id, 1]
    result[window_id]["inputs"]["frame_count"] = [guard_id, 2]
    result[carry_id]["inputs"]["cache_key"] = [guard_id, 0]
    result[saver_id]["inputs"]["cache_key"] = [guard_id, 0]
    if info["guide_loader_id"] is not None:
        guide_loader_id = info["guide_loader_id"]
        result[guide_loader_id]["inputs"]["frame_load_cap"] = [guard_id, 2]
        result[guide_loader_id]["inputs"]["start_time"] = [guard_id, 3]
    return result


def plan_wan_graph(project_snapshot: dict[str, Any], compiled_api_graph: dict[str, Any],
                   prior_context: dict[str, Any] | None = None, *,
                   output_root: str | Path | None = None) -> dict[str, Any]:
    """Plan exactly one bounded section, merge transition, or render request.

    ``compiled_api_graph`` is never replaced with a default graph. Native node
    settings and connections are preserved on a deep copy; returned patches
    modify only cursor/cache bookkeeping. ``prior_context`` stores the last
    deterministic context and editable workflow snapshot. Receipt scans are
    the authority for progress; prior cursor fields are not trusted.
    """
    root = _root(output_root)
    pins = _project_pins(project_snapshot)
    project = copy.deepcopy(project_snapshot)
    graph = _normalise_prompt(compiled_api_graph)
    # Read the approved review's small JSON manifest and its content digest;
    # no source, mask, preview, model or tensor bytes are opened here.
    clip, review_pin, _ = _review_metadata(root, pins)
    structural_graph = expand_stage_signals(compiled_api_graph)
    shot_for_resolution = _find_one(structural_graph, SHOT, "approved reviewed-shot loader")
    graph_resolution = structural_graph[shot_for_resolution]["inputs"].get("render_long_edge")
    if type(graph_resolution) is not int or graph_resolution not in RESOLUTIONS:
        raise WanGraphPlanError("Choose a supported source resolution in the native Wan source loader.")
    # Graph view is the source of truth for this editable, downstream render
    # resolution. It is not part of mask approval, but it changes the native
    # preparation recipe, cache namespace and safe frames-per-job limit.
    pins["resolution"] = graph_resolution
    saver_for_scope = _find_one(structural_graph, PART_SAVER, "bounded preparation saver")
    selected_scope = structural_graph[saver_for_scope]["inputs"].get("scope")
    if selected_scope not in ("person", "head"):
        raise WanGraphPlanError("Choose whole-person or whole-head motion scope in the native preparation saver.")
    pins["scope"] = selected_scope
    info = _validate_roles(compiled_api_graph, project, pins, clip, root)
    roles_graph = info["graph"]
    node_ids = info["ids"]
    saver_inputs = info["saver"]["inputs"]
    carry_inputs = info["carry"]["inputs"]
    # The scope changes the prepared motion metadata and context key while
    # leaving the reviewed source interval and mask approval untouched.
    if carry_inputs.get("scope") != selected_scope:
        raise WanGraphPlanError("The pose carry and preparation saver must use the same replacement scope.")
    resolution = pins["resolution"]
    bound = 41 if resolution == 1920 else 81
    total = clip["frames"]
    if total > 1_000_000:
        raise WanGraphPlanError("The approved Wan timeline exceeds the safe frame limit.")
    original_source_sha = _sha(clip["source_hash"], "original source")
    if original_source_sha != pins["source_sha"]:
        raise WanGraphPlanError("The approved source identity changed. Review the source again.")
    source_pin = {"review_shot_id": pins["review"], "original_source_sha256": original_source_sha}
    guide_pin = info["guide_pin"]
    scope = pins["scope"]
    if carry_inputs.get("scope") != scope or saver_inputs.get("scope") != scope:
        raise WanGraphPlanError("The Wan preparation scope is not approved by the current project.")
    guide_key = guide_pin["guide_key"] if guide_pin else ""
    guide_sha = guide_pin["guide_sha"] if guide_pin else ""
    from ..wan_preparation_runtime import canonical as runtime_canonical, metadata_for_scope, scan_parts
    metadata = metadata_for_scope(scope, guide_key, guide_sha)
    recipe_sha = preparation_fingerprint(
        compiled_api_graph, guide_loader_id=info["guide_loader_id"])
    context_key, key_payload = _context_key(pins, review_pin, recipe_sha, resolution, scope, guide_pin)
    prior = _validate_prior_context(prior_context, pins, review_pin, guide_pin)
    recipe_forked = bool(prior and prior.get("recipe_sha256") != recipe_sha)

    render_paths = _render_cache_paths(root, pins["review"], resolution, total)
    render_stamps = _render_cache_stamps(render_paths)
    if prior:
        old_stamps = prior.get("render_cache_stamps")
        if type(old_stamps) is not dict or set(old_stamps) != {"source", "mask"}:
            raise WanGraphPlanError("The saved Wan graph has invalid source/mask cache stamps.")
        if prior["project_pins"].get("resolution") == resolution:
            for name in ("source", "mask"):
                old, current = old_stamps[name], render_stamps[name]
                old = _browser_file_pin(old)
                current = _browser_file_pin(current)
                if old.get("path") != current.get("path"):
                    raise WanGraphPlanError("The approved source resolution changed without a fresh section plan.")
                if old.get("size") is not None and (old.get("size"), old.get("mtime_ns")) != (current.get("size"), current.get("mtime_ns")):
                    raise WanGraphPlanError("The approved rendered source or mask changed. Review it again before queuing.")

    role_ids = _role_ids(info)
    paths, receipts, start = scan_parts(
        root, context_key, total, metadata, source_pin=source_pin,
        review_pin=review_pin, max_part_frames=bound, render_long_edge=resolution)
    if len(receipts) > MAX_RECEIPTS:
        raise WanGraphPlanError("The Wan graph has too many preparation receipts.")
    if start > total or (start < total and start % bound != 0):
        raise WanGraphPlanError("Wan preparation progress is not a canonical section boundary.")

    # A stale graph context can be safely forked only for native preparation
    # recipe edits. Source, approval, review and facial guide changes already
    # failed above and require their existing Studio review path.
    context = _serialisable_context(context_key, key_payload, recipe_sha, pins,
        review_pin, source_pin, metadata, total, bound, graph, guide_pin, render_stamps)
    context["recipe_forked"] = recipe_forked
    if start < total:
        count = min(bound, total - start)
        guard_plan = _guard_plan(context_key, recipe_sha, pins, source_pin,
            review_pin, metadata, total, bound, start, count, guide_pin,
            key_payload, render_stamps)
        guard_json = canonical(guard_plan)
        guard_id = info["guard_id"] or _semantic_guard_id(
            recipe_sha, roles_graph, guide_loader_id=info["guide_loader_id"])
        role_ids["guard"] = "zura.wan.guard"
        patches = [
            _connection_patch(node_ids["window"], role_ids["window"], WINDOW, {
                "start_frame": {"source_role": role_ids["guard"], "output": 1},
                "frame_count": {"source_role": role_ids["guard"], "output": 2},
            }),
            _connection_patch(node_ids["carry"], role_ids["carry"], CARRY, {
                "cache_key": {"source_role": role_ids["guard"], "output": 0},
            }),
            _connection_patch(node_ids["saver"], role_ids["saver"], PART_SAVER, {
                "cache_key": {"source_role": role_ids["guard"], "output": 0},
            }),
        ]
        if info["guide_loader_id"] is not None:
            patches.append(_connection_patch(
                node_ids["guide_loader"], role_ids["guide_loader"], "VHS_LoadVideoFFmpegPath", {
                    "frame_load_cap": {"source_role": role_ids["guard"], "output": 2},
                    "start_time": {"source_role": role_ids["guard"], "output": 3},
                }))
        updated = _materialise_guard(graph, info, guard_id, guard_json)
        guard = {
            "node_id": guard_id,
            "role_id": role_ids["guard"],
            "semantic_id": guard_id,
            "class_type": GRAPH_GUARD,
            "inputs": {"plan_json": guard_json},
            "bindings": [
                {"role_id": role_ids["window"], "input": "start_frame", "output": 1},
                {"role_id": role_ids["window"], "input": "frame_count", "output": 2},
                {"role_id": role_ids["carry"], "input": "cache_key", "output": 0},
                {"role_id": role_ids["saver"], "input": "cache_key", "output": 0},
            ],
            "plan_json": guard_json,
        }
        if info["guide_loader_id"] is not None:
            guard["bindings"].extend([
                {"role_id": role_ids["guide_loader"], "input": "frame_load_cap", "output": 2},
                {"role_id": role_ids["guide_loader"], "input": "start_time", "output": 3},
            ])
        context["planned_start"] = start
        context["planned_count"] = count
        context["workflow_snapshot"] = copy.deepcopy(updated)
        return {"schema": PLAN_SCHEMA, "action": "prepare", "graph": updated,
                "context": context, "role_ids": role_ids, "patches": patches,
                "guard": guard, "progress": {"completed_frames": start,
                "total_frames": total, "next_start": start, "next_count": count,
                "section_limit": bound, "section_index": start // bound,
                "section_total": (total + bound - 1) // bound,
                "completed_receipts": len(receipts), "recipe_forked": recipe_forked},
                "render_request": None}

    # All receipts exist and passed the strict metadata/stamp/carry chain scan.
    cache_path = root / "genj" / "wan_conditioning" / (context_key + ".pt")
    cache_exists = False
    cache_stamp = None
    if cache_path.exists():
        resolved = cache_path.resolve(strict=True)
        if resolved != cache_path or not resolved.is_relative_to(root) or cache_path.is_symlink():
            raise WanGraphPlanError("The merged Wan preparation cache is redirected or outside output.")
        stat = cache_path.stat()
        if not cache_path.is_file() or stat.st_size < 1:
            raise WanGraphPlanError("The merged Wan preparation cache is empty.")
        cache_exists = True
        cache_stamp = {"path": str(cache_path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    context["completed_receipts"] = copy.deepcopy(paths)
    if not cache_exists:
        merge_inputs = {"cache_key": context_key, "total_frames": total,
                        "receipts_json": runtime_canonical(paths),
                        "metadata_json": runtime_canonical(metadata)}
        merge_id = "zura.wan.merge"
        merge_patch = {"node_id": merge_id, "role_id": merge_id,
                       "class_type": MERGE, "inputs": merge_inputs}
        merged_graph = {merge_id: {"class_type": MERGE, "inputs": merge_inputs}}
        context["merge_cache_stamp"] = None
        return {"schema": PLAN_SCHEMA, "action": "merge", "graph": merged_graph,
                "context": context, "role_ids": role_ids, "patches": [merge_patch],
                "guard": None, "progress": {"completed_frames": total,
                "total_frames": total, "next_start": total, "next_count": 0,
                "section_limit": bound, "completed_receipts": len(receipts),
                "recipe_forked": recipe_forked}, "render_request": None}
    context["merge_cache_stamp"] = _browser_file_pin(cache_stamp)
    return {"schema": PLAN_SCHEMA, "action": "render", "graph": None,
            "context": context, "role_ids": role_ids, "patches": [], "guard": None,
            "progress": {"completed_frames": total, "total_frames": total,
                         "next_start": total, "next_count": 0, "section_limit": bound,
                         "completed_receipts": len(receipts), "recipe_forked": recipe_forked},
            "render_request": {"builder": "artist_studio.wan.build_wan_graph",
                "cache_key_override": context_key, "require_streamed_sampler": True,
                "cache_stamp": _browser_file_pin(cache_stamp)}}


def _semantic_guard_id(recipe_sha: str, graph: dict[str, dict[str, Any]],
                       guide_loader_id: str | None = None) -> str:
    role_summary = []
    for identity, node in graph.items():
        if node["class_type"] in (WINDOW, CARRY, PART_SAVER, SHOT):
            role_summary.append([node["class_type"], _node_fingerprint(
                identity, graph, set(), {}, guide_loader_id)])
    value = hashlib.sha256(canonical([recipe_sha, sorted(role_summary)]).encode()).hexdigest()[:20]
    return "zura.wan.guard." + value
