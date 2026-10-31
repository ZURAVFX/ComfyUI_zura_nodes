"""Small receipt checks and the visible bounded preparation merge endpoint.

Scanning preparation progress reads only receipts/checkpoints and file stamps.
Actual tensor-cache content hashes remain in the CPU preparation/merge workers.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import struct

MAX_JSON_BYTES = 2 * 1024 ** 2
KEY_RE = re.compile(r"[a-f0-9]{64}")
RECEIPT_RE = re.compile(r"part_([0-9]{8})_([0-9]{5})\.receipt\.json")
PART_RE = re.compile(r"part_([0-9]{8})_([0-9]{5})\.pt")
NONE_CARRY_SHA = hashlib.sha256(b"zura-wan-pose-carry-v1:none").hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)


def metadata_for_scope(scope, guide_key="", guide_sha=""):
    if scope not in ("person", "head") or bool(guide_key) != bool(guide_sha):
        raise ValueError("Wan preparation scope or speech guide pins are invalid.")
    value = {"replacement_area":"Whole head" if scope == "head" else "Whole character",
             "video_info":{"fps":24}, "keep_audio":False}
    if guide_key:
        value["speech_provenance"] = {"guide_key":digest_key(guide_key), "guide_sha":digest_key(guide_sha)}
    return value


def digest_key(value):
    if not isinstance(value, str) or not KEY_RE.fullmatch(value):
        raise ValueError("Invalid Wan preparation key or digest.")
    return value


def confined(path, root, *, exists=True):
    path = Path(path)
    resolved = path.resolve(strict=exists)
    if resolved != path or not resolved.is_relative_to(root):
        raise ValueError("Wan preparation state uses a redirected or outside output path.")
    return resolved


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Wan preparation JSON contains duplicate keys.")
        result[key] = value
    return result


def parse_json(raw):
    if not isinstance(raw, str) or not 1 <= len(raw.encode("utf-8")) <= MAX_JSON_BYTES:
        raise ValueError("Wan preparation JSON is empty or exceeds its safe metadata limit.")
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError("Wan preparation JSON is invalid.") from error


def read_json(path, root, limit=MAX_JSON_BYTES):
    path = confined(path, root)
    before = path.stat()
    if not path.is_file() or not 1 <= before.st_size <= limit:
        raise ValueError("Wan preparation receipt or checkpoint is missing or too large.")
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns) != (
            after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
        raise ValueError("Wan preparation metadata changed while reading.")
    try:
        result = parse_json(raw.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ValueError("Wan preparation metadata is not UTF-8 JSON.") from error
    if type(result) is not dict:
        raise ValueError("Wan preparation receipt or checkpoint must be a JSON object.")
    return result, hashlib.sha256(raw).hexdigest()


def validate_render_cache_pin(value, root, shot_id, total_frames, *, render_long_edge=None):
    """Check canonical derived video identities using stamps, without hashing."""
    if type(value) is not dict or set(value) != {"source","mask"}:
        raise ValueError("Wan preparation is missing its derived source/mask pins.")
    paths = {}
    for label in ("source","mask"):
        pin = value[label]
        if (type(pin) is not dict or set(pin) != {"path","sha256","size","mtime_ns"} or
                type(pin["path"]) is not str or not Path(pin["path"]).is_absolute() or
                type(pin["size"]) is not int or pin["size"] < 1 or
                type(pin["mtime_ns"]) is not int or pin["mtime_ns"] < 0):
            raise ValueError("Wan preparation derived source/mask pin is malformed.")
        digest_key(pin["sha256"])
        path = confined(Path(pin["path"]),root)
        stat = path.stat()
        if not path.is_file() or stat.st_size != pin["size"] or stat.st_mtime_ns != pin["mtime_ns"]:
            raise ValueError("Wan preparation derived source/mask file identity changed.")
        paths[label] = path
    review = root/"genj"/"reviews"/shot_id
    source, mask = paths["source"],paths["mask"]
    if source.name != "source.mp4" or mask.name != "mask.mp4" or source.parent != mask.parent:
        raise ValueError("Wan preparation derived source/mask pair is not canonical.")
    if source.parent == review:
        if render_long_edge not in (None,0):
            raise ValueError("Wan preparation uses another reviewed render resolution.")
    else:
        match = re.fullmatch(r"render_audio_v(?:2|3)_([0-9]+)_x[12]_"+str(total_frames)+r"f(?:_aspect)?",source.parent.name)
        if (source.parent.parent != review or not match or source.parent.name.startswith('render_audio_v2_') and source.parent.name.endswith('_aspect') or not 256 <= int(match[1]) <= 4096 or
                (render_long_edge is not None and int(match[1]) != render_long_edge)):
            raise ValueError("Wan preparation derived pair belongs to another render resolution or review.")
    return value


def scan_parts(output_root, cache_key, total_frames, metadata, *, source_pin=None, review_pin=None,
               max_part_frames=81, render_long_edge=None):
    """Return exact complete prefix receipts; ambiguous partial state is refused."""
    digest_key(cache_key)
    if type(total_frames) is not int or total_frames < 1 or type(max_part_frames) is not int or not 1 <= max_part_frames <= 81:
        raise ValueError("Wan preparation needs a valid full timeline and bounded part size.")
    root = Path(output_root).resolve(strict=True)
    directory = root / "genj" / "wan_preparation_parts" / cache_key
    confined(directory, root, exists=False)
    if not directory.exists():
        return [], [], 0
    if not directory.is_dir():
        raise ValueError("Wan preparation progress is not a directory.")
    entries = list(directory.iterdir())
    if len(entries) > 12288:
        raise ValueError("Wan preparation progress contains excessive metadata files.")
    parts, receipts, checkpoints = {}, {}, {}
    metadata_bytes = 0
    for path in entries:
        confined(path, root)
        match = PART_RE.fullmatch(path.name)
        receipt_match = RECEIPT_RE.fullmatch(path.name)
        carry_match = re.fullmatch(r"carry_([0-9]{8})\.json", path.name)
        if match or receipt_match:
            selected = parts if match else receipts
            start, count = map(int, (match or receipt_match).groups())
            if start in selected:
                raise ValueError("Wan preparation has duplicate or overlapping part starts.")
            selected[start] = (path, count)
            if receipt_match:
                metadata_bytes += path.stat().st_size
        elif carry_match:
            checkpoints[int(carry_match[1])] = path
            metadata_bytes += path.stat().st_size
        else:
            raise ValueError("Wan preparation has incomplete temporary state. Keep it for inspection and prepare a new cache key.")
        if metadata_bytes > MAX_JSON_BYTES:
            raise ValueError("Wan preparation progress exceeds its bounded total metadata budget.")
    if parts.keys() != receipts.keys():
        raise ValueError("Wan preparation has an orphan part or missing receipt. Keep it for inspection and prepare a new cache key.")
    expected, parsed, paths, previous_sha, carry_out, reference = 0, [], [], NONE_CARRY_SHA, None, None
    metadata_sha = hashlib.sha256(canonical(metadata).encode("utf-8")).hexdigest()
    used_checkpoints = set()
    render_cache_pin = None
    for start in sorted(receipts):
        path, count = receipts[start]
        if start != expected or count != min(max_part_frames, total_frames-start) or parts[start][1] != count:
            raise ValueError("Wan preparation parts do not cover a contiguous bounded timeline.")
        value, raw_sha = read_json(path, root)
        part_path = parts[start][0]
        stat = part_path.stat()
        if (value.get("schema") != "zura_wan_preparation_part_v1" or value.get("cache_key") != cache_key or
                type(value.get("start")) is not int or value["start"] != start or
                type(value.get("count")) is not int or value["count"] != count or
                type(value.get("total_frames")) is not int or value["total_frames"] != total_frames or
                value.get("path_name") != part_path.name or value.get("path") != str(part_path) or
                type(value.get("size")) is not int or value["size"] != stat.st_size or
                type(value.get("mtime_ns")) is not int or value["mtime_ns"] != stat.st_mtime_ns):
            raise ValueError("Wan preparation part receipt does not match its canonical file and timeline.")
        for field in ("sha256","reference_sha256","footage_metadata_sha256","carry_in_sha256","carry_out_sha256",
                      "previous_receipt_sha256"):
            digest_key(value.get(field))
        source, review = value.get("source_pin"), value.get("review_pin")
        if (type(source) is not dict or set(source) != {"review_shot_id","original_source_sha256","window_source_sha256"} or
                type(review) is not dict or set(review) != {"manifest_sha256","mask_sha256"}):
            raise ValueError("Wan preparation receipt is missing approved source or review pins.")
        digest_key(source["original_source_sha256"])
        digest_key(source["window_source_sha256"])
        for pin in review.values():
            digest_key(pin)
        stable_source = {k:v for k,v in source.items() if k != "window_source_sha256"}
        if not isinstance(source["review_shot_id"],str) or not re.fullmatch(r"shot_[a-f0-9]{16}",source["review_shot_id"]):
            raise ValueError("Wan preparation lacks its approved review identity.")
        if source_pin is None:
            source_pin = stable_source
        if review_pin is None:
            review_pin = review
        if (stable_source != source_pin or review != review_pin or value["footage_metadata_sha256"] != metadata_sha or
                (reference is not None and value["reference_sha256"] != reference)):
            raise ValueError("Wan preparation parts belong to changed source, review, reference or settings.")
        reference = value["reference_sha256"]
        render = validate_render_cache_pin(value.get("render_cache_pin"),root,source["review_shot_id"],
                                           total_frames,render_long_edge=render_long_edge)
        if render_cache_pin is not None and render != render_cache_pin:
            raise ValueError("Wan preparation parts mix different derived source/mask files.")
        render_cache_pin = render
        if (value.get("carry_in_kind") != ("none" if start == 0 else "body") or
                value["carry_in_sha256"] != (NONE_CARRY_SHA if start == 0 else carry_out) or
                value["previous_receipt_sha256"] != previous_sha):
            raise ValueError("Wan preparation pose-carry chain is missing or changed.")
        expected = start + count
        if expected < total_frames:
            checkpoint_path = checkpoints.get(expected)
            if checkpoint_path is None:
                raise ValueError("Wan preparation has a missing pose-carry checkpoint. Prepare a new cache key.")
            state, _ = read_json(checkpoint_path, root, 256*1024)
            if (state.get("schema") != "zura_wan_pose_carry_v1" or state.get("cache_key") != cache_key or
                    state.get("end_frame") != expected or state.get("total_frames") != total_frames or
                    state.get("source_pin") != stable_source or state.get("review_pin") != review or
                    state.get("render_cache_pin") != render_cache_pin or
                    state.get("reference_sha256") != reference or state.get("footage_metadata_sha256") != metadata_sha or
                    state.get("carry_out_sha256") != value["carry_out_sha256"] or
                    state.get("receipt_name") != path.name or state.get("receipt_sha256") != raw_sha):
                raise ValueError("Wan preparation pose checkpoint does not match its preceding receipt.")
            body = state.get("carry_body")
            if (type(body) is not list or len(body) != 20 or any(type(row) is not list or len(row) != 3 for row in body) or
                    any(type(x) not in (int,float) or not math.isfinite(x) for row in body for x in row)):
                raise ValueError("Wan preparation pose checkpoint contains an invalid body.")
            try:
                body_sha = hashlib.sha256(struct.pack("<60f", *(x for row in body for x in row))).hexdigest()
            except (OverflowError,struct.error) as error:
                raise ValueError("Wan pose carry cannot be represented as native FP32.") from error
            if body_sha != value["carry_out_sha256"]:
                raise ValueError("Wan preparation pose checkpoint body digest differs.")
            used_checkpoints.add(expected)
        previous_sha, carry_out = raw_sha, value["carry_out_sha256"]
        parsed.append(value)
        paths.append(str(path))
    if checkpoints.keys() != used_checkpoints:
        raise ValueError("Wan preparation has an orphan pose checkpoint. Prepare a new cache key.")
    return paths, parsed, expected


class ZuraWanMergePreparation:
    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "merge"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("preparation_cache_key",)
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"cache_key":("STRING",{"default":""}),
            "total_frames":("INT",{"default":120,"min":1}),
            "receipts_json":("STRING",{"default":"[]"}),
            "metadata_json":("STRING",{"default":"{}"})}}

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def merge(self, cache_key, total_frames, receipts_json, metadata_json):
        import folder_paths
        from .wan_preparation_merge import shards_from_receipts, merge_preparation
        from .wan_preparation_windows import WanPreparationWindows
        from .wan_preparation_parts import _review_pins, _file_sha
        def interrupt():
            from comfy.model_management import throw_exception_if_processing_interrupted
            throw_exception_if_processing_interrupted()
        root = Path(folder_paths.get_output_directory()).resolve(strict=True)
        paths, metadata = parse_json(receipts_json), parse_json(metadata_json)
        if type(paths) is not list or not paths or len(paths) > 4096 or not all(type(p) is str for p in paths):
            raise ValueError("Wan merge needs explicit canonical receipt paths.")
        if type(metadata) is not dict:
            raise ValueError("Wan merge metadata must be an object.")
        # The worker receipt constructor fixes the maximum partition size;
        # determine that first size, then verify the entire canonical directory.
        first, _ = read_json(Path(paths[0]), root)
        source_pin = first.get("source_pin")
        shot_id = source_pin.get("review_shot_id") if type(source_pin) is dict else None
        if not isinstance(shot_id,str) or not re.fullmatch(r"shot_[a-f0-9]{16}",shot_id):
            raise ValueError("Wan merge requires the original approved review identity.")
        manifest,_ = read_json(root/"genj"/"reviews"/shot_id/"review.json",root,1024*1024)
        clip = manifest.get("clip")
        if type(clip) is not dict or clip.get("frames") != total_frames:
            raise ValueError("Wan merge no longer matches the reviewed full clip.")
        reviewed = _review_pins(root,{**clip,"review_shot_id":shot_id})
        if _file_sha(Path(clip["source"]),interrupt) != clip["source_hash"]:
            raise ValueError("The original Wan source changed after preparation.")
        bound = first.get("count")
        canonical_paths, receipts, end = scan_parts(root, cache_key, total_frames, metadata,
            source_pin=reviewed["source_pin"],review_pin=reviewed["review_pin"],max_part_frames=bound)
        if paths != canonical_paths or end != total_frames:
            raise ValueError("Wan merge requires every canonical preparation receipt in timeline order.")
        specs = shards_from_receipts(receipts, cache_key, total_frames, metadata)
        receipt = merge_preparation(specs, root, cache_key, total_frames, metadata, interrupt=interrupt)
        WanPreparationWindows(receipt["path"], cache_key, root, expected_sha256=receipt["sha256"],
                              max_window_frames=4, interrupt=interrupt)
        return {"ui":{"text":[f"Prepared {total_frames} Wan frames in bounded windows."]},"result":(cache_key,)}
