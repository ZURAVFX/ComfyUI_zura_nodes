"""Bounded Wan preparation windows and native pose carry checkpoints.

This module contains only data adapters.  Pose/face inference and pose drawing
remain ordinary visible WanAnimatePreprocess nodes in the graph.  The adapter
keeps each preparation job below 81 frames and saves an ordinary version-1
Torch preparation shard for the separately reviewed merger.
"""
from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

import numpy as np
import torch
import torch.nn.functional as F

from .bounded_video_audio import inspect_video, iter_native_frames


MAX_PART_FRAMES = 81
WINDOW_SCHEMA = "zura_wan_preparation_window_v1"
PART_SCHEMA = "zura_wan_preparation_part_v1"
CARRY_SCHEMA = "zura_wan_pose_carry_v1"
NONE_CARRY_SHA256 = hashlib.sha256(b"zura-wan-pose-carry-v1:none").hexdigest()
_KEY_RE = re.compile(r"^[a-f0-9]{64}$")
_SHOT_RE = re.compile(r"^shot_[a-f0-9]{16}$")
_HEX_RE = _KEY_RE
_POSE_BODY_SHAPE = (20, 3)
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024


def _interrupt():
    try:
        from comfy.model_management import throw_exception_if_processing_interrupted
        throw_exception_if_processing_interrupted()
    except ImportError:
        return


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha(value) -> str:
    return _sha_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                 allow_nan=False, ensure_ascii=False).encode("utf-8"))


def _file_sha(path: Path, interrupt=None) -> str:
    interrupt = interrupt or _interrupt
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(4 * 1024 * 1024)
            if not block:
                break
            interrupt()
            digest.update(block)
    return digest.hexdigest()


def _stable_file_pin(path: Path, expected_sha=None, interrupt=None):
    path = Path(path)
    _ensure_no_symlink(path)
    if not path.is_file():
        raise ValueError("A reviewed Wan source or mask file is missing.")
    before = path.stat()
    sha = _file_sha(path, interrupt)
    after = path.stat()
    if (before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns or
            (expected_sha is not None and sha != expected_sha)):
        raise ValueError("A reviewed Wan source or mask changed while it was being verified.")
    return {"path": str(path.resolve(strict=True)), "sha256": sha,
            "size": after.st_size, "mtime_ns": after.st_mtime_ns}


def _check_render_pin_stamps(render_pin):
    _render_pin_shape(render_pin)
    for pin in render_pin.values():
        path = Path(pin["path"])
        _ensure_no_symlink(path)
        if not path.is_file():
            raise ValueError("A reviewed Wan source or mask file is missing.")
        current = path.stat()
        if current.st_size != pin["size"] or current.st_mtime_ns != pin["mtime_ns"]:
            raise ValueError("The reviewed Wan source or mask cache changed during preparation.")


def _safe_hash(value, label):
    if not isinstance(value, str) or not _HEX_RE.fullmatch(value):
        raise ValueError(f"Wan {label} must be a 64-character SHA256 digest.")
    return value


def _plain_tensor(value, name, *, dimensions, shape_tail=None, bounded_frames=None,
                  allow_empty_mask=False):
    if (not isinstance(value, torch.Tensor) or value.layout != torch.strided or
            value.device.type != "cpu" or value.dtype != torch.float32 or
            value.ndim != dimensions or not value.is_contiguous()):
        raise ValueError(f"Wan {name} must be a contiguous CPU float32 tensor.")
    if any(type(size) is not int or size < 1 for size in value.shape):
        raise ValueError(f"Wan {name} has an empty or invalid dimension.")
    if value.storage_offset() != 0 or value.untyped_storage().nbytes() != value.numel() * value.element_size():
        raise ValueError(f"Wan {name} must not retain storage outside this bounded window.")
    if shape_tail is not None and tuple(value.shape[-len(shape_tail):]) != tuple(shape_tail):
        raise ValueError(f"Wan {name} has an unsupported raster or channel count.")
    if bounded_frames is not None and value.shape[0] != bounded_frames:
        raise ValueError(f"Wan {name} does not cover exactly this preparation window.")
    for index in range(value.shape[0]):
        if not torch.isfinite(value[index]).all():
            raise ValueError(f"Wan {name} contains non-finite values.")
    if name == "character_mask":
        if value.min() < 0 or value.max() > 1:
            raise ValueError("Wan reviewed masks must be in [0,1].")
        if not allow_empty_mask and not bool((value > 0.5).any()):
            raise ValueError("The complete Wan preparation must contain an approved performer mask.")
    return value


def _window_fields(window):
    if not isinstance(window, dict) or window.get("schema") != WINDOW_SCHEMA:
        raise ValueError("Wan preparation requires a validated bounded window.")
    wanted = {"schema", "start", "count", "total_frames", "fps", "width", "height",
              "mask_width", "mask_height", "render_cache_pin"}
    if set(window) != wanted:
        raise ValueError("Wan preparation window metadata is incomplete or unsupported.")
    for field in ("start", "count", "total_frames", "width", "height", "mask_width", "mask_height"):
        if type(window[field]) is not int:
            raise ValueError("Wan preparation window dimensions must be integers.")
    start, count, total = window["start"], window["count"], window["total_frames"]
    if (start < 0 or not 1 <= count <= MAX_PART_FRAMES or total < 1 or
            start + count > total or type(window["fps"]) is not int or window["fps"] != 24 or
            min(window["width"], window["height"], window["mask_width"], window["mask_height"]) < 1):
        raise ValueError("Wan preparation window is outside its reviewed 24-fps timeline.")
    _render_pin_shape(window["render_cache_pin"])
    return start, count, total


def _render_pin_shape(value):
    if not isinstance(value, dict) or set(value) != {"source", "mask"}:
        raise ValueError("Wan preparation lacks its derived source/mask file pin.")
    for label in ("source", "mask"):
        pin = value[label]
        if not isinstance(pin, dict) or set(pin) != {"path", "sha256", "size", "mtime_ns"}:
            raise ValueError("Wan preparation derived file pin is malformed.")
        if (not isinstance(pin["path"], str) or not Path(pin["path"]).is_absolute() or
                type(pin["size"]) is not int or pin["size"] < 1 or
                type(pin["mtime_ns"]) is not int or pin["mtime_ns"] < 0):
            raise ValueError("Wan preparation derived file pin is malformed.")
        _safe_hash(pin["sha256"], "derived file pin")
    if Path(value["source"]["path"]).parent != Path(value["mask"]["path"]).parent:
        raise ValueError("Wan source and mask file pins must belong to one loader cache.")
    return value


def _native_pair_window(source, mask_video, source_timeline, mask_timeline,
                        start, count, interrupt):
    """Read aligned source/mask frames while retaining only the returned window."""
    source_part = replace(source_timeline, start=source_timeline.start + Fraction(start, 24),
                          duration=Fraction(count, 24), frames=count)
    mask_part = replace(mask_timeline, start=mask_timeline.start + Fraction(start, 24),
                        duration=Fraction(count, 24), frames=count)
    frames = torch.empty((count, source_timeline.height, source_timeline.width, 3), dtype=torch.float32)
    masks = torch.empty((count, source_timeline.height, source_timeline.width), dtype=torch.float32)
    source_iter = iter(iter_native_frames(source, source_part, interrupt=interrupt))
    mask_iter = iter(iter_native_frames(mask_video, mask_part, interrupt=interrupt))
    for index in range(count):
        try:
            source_index, source_frame = next(source_iter)
            mask_index, mask_frame = next(mask_iter)
        except StopIteration as error:
            raise ValueError("Wan native decoder returned an incomplete source/mask window.") from error
        if (source_index != index or mask_index != index or
                tuple(source_frame.shape) != (source_timeline.height, source_timeline.width, 3) or
                tuple(mask_frame.shape) != (mask_timeline.height, mask_timeline.width, 3)):
            raise ValueError("Wan native decoder returned a non-contiguous source/mask window.")
        frames[index].copy_(source_frame.to(device="cpu", dtype=torch.float32))
        gray = mask_frame.float().mean(dim=-1)[None, None]
        resized = F.interpolate(gray, (source_timeline.height, source_timeline.width), mode="nearest")[0, 0]
        masks[index].copy_((resized > 0.5).float())
        interrupt()
    try:
        next(source_iter)
        raise ValueError("Wan native source decoder returned frames beyond the approved window.")
    except StopIteration:
        pass
    try:
        next(mask_iter)
        raise ValueError("Wan native mask decoder returned frames beyond the approved window.")
    except StopIteration:
        pass
    return frames, masks


def _binary_mask_window(mask_video, timeline, start, count, target_raster, interrupt):
    shifted = replace(timeline, start=timeline.start + Fraction(start, 24),
                      duration=Fraction(count, 24), frames=count)
    height, width = target_raster
    masks = torch.empty((count, height, width), dtype=torch.float32)
    rows = 0
    for local_index, frame in iter_native_frames(mask_video, shifted, interrupt=interrupt):
        if local_index != rows or tuple(frame.shape) != (timeline.height, timeline.width, 3):
            raise ValueError("The approved review mask returned a non-contiguous frame window.")
        gray = frame.float().mean(dim=-1)[None, None]
        resized = F.interpolate(gray, (height, width), mode="nearest")[0, 0]
        masks[rows].copy_((resized > 0.5).float())
        rows += 1
    if rows != count:
        raise ValueError("The approved review mask did not cover this source window.")
    return masks.contiguous()


def decode_preparation_window(source, mask_video, clip_details, start_frame, frame_count,
                              interrupt=_interrupt):
    """Decode one exact, native VIDEO frame range and its approved binary mask.

    This intentionally mirrors ZuraWanReviewedFrames' grayscale/nearest/
    threshold operations while retaining only this window in memory.
    """
    if type(start_frame) is not int or type(frame_count) is not int:
        raise ValueError("Choose an integer Wan window start and length.")
    if not 1 <= frame_count <= MAX_PART_FRAMES or start_frame < 0:
        raise ValueError("Wan preparation windows must contain 1 to 81 frames.")
    if not isinstance(clip_details, dict):
        raise ValueError("Wan preparation needs the reviewed shot details.")
    total = clip_details.get("frames")
    if type(total) is not int or total < 1 or start_frame + frame_count > total:
        raise ValueError("Wan preparation window exceeds the reviewed clip length.")
    if clip_details.get("fps", 24) != 24 or abs(float(clip_details.get("duration", total / 24)) - total / 24) > 1e-6:
        raise ValueError("Wan preparation requires the approved complete 24-fps clip timeline.")

    source_info = inspect_video(source, interrupt=interrupt)
    mask_info = inspect_video(mask_video, interrupt=interrupt)
    output_root = _output_root()
    review_pins = _review_pins(output_root, clip_details)
    render_pin = _require_review_video_paths(
        output_root, clip_details, source_info, mask_info, source, mask_video, review_pins)
    if source_info.fps != 24 or mask_info.fps != 24:
        raise ValueError("Wan review videos must be prepared at 24 fps.")
    if source_info.start != 0 or mask_info.start != 0:
        raise ValueError("Wan source and reviewed mask must start at the approved shot beginning.")
    if source_info.frames != total or mask_info.frames != total:
        raise ValueError("Source and approved mask must cover the same reviewed timeline.")
    if ("width" in clip_details and clip_details["width"] != source_info.width) or (
            "height" in clip_details and clip_details["height"] != source_info.height):
        raise ValueError("The decoded source raster differs from the reviewed shot details.")

    # Match ZuraWanReviewedFrames exactly, but reduce each mask frame before
    # decoding the next one so a high-resolution part does not keep a second
    # full RGB video window and its grayscale/resized copies in memory.
    frames, binary = _native_pair_window(source, mask_video, source_info, mask_info,
                                         start_frame, frame_count, interrupt)
    if clip_details.get("render_long_edge", 0) > 0:
        # High-resolution render masks must remain exactly the approved review
        # mask after the same per-frame grayscale/nearest/threshold transform.
        from comfy_api.latest import InputImpl
        review_dir, _, approved_mask_path = _expected_review_video_paths(output_root, clip_details)
        approved_mask_path = review_dir / "mask.mp4"
        approved_mask = InputImpl.VideoFromFile(str(approved_mask_path))
        approved_info = inspect_video(approved_mask, interrupt=interrupt)
        if (approved_info.fps != 24 or approved_info.start != 0 or
                approved_info.frames != total):
            raise ValueError("The approved review mask does not cover the complete Wan timeline.")
        approved_window = _binary_mask_window(
            approved_mask, approved_info, start_frame, frame_count,
            (source_info.height, source_info.width), interrupt)
        if not torch.equal(binary, approved_window):
            raise ValueError("The high-resolution Wan mask differs from the approved review mask.")
    _validate_render_cache_pin(output_root, clip_details, review_pins, render_pin)
    binary = binary.contiguous()
    _plain_tensor(frames, "source frames", dimensions=4, shape_tail=(source_info.height, source_info.width, 3),
                  bounded_frames=frame_count)
    _plain_tensor(binary, "character_mask", dimensions=3, bounded_frames=frame_count, allow_empty_mask=True)
    window = {"schema": WINDOW_SCHEMA, "start": start_frame, "count": frame_count,
              "total_frames": total, "fps": 24, "width": source_info.width, "height": source_info.height,
              "mask_width": mask_info.width, "mask_height": mask_info.height,
              "render_cache_pin": render_pin}
    return frames, binary, source_info.width, source_info.height, window


def _body_is_all_invalid(body):
    # Keep the exact native loader predicate, including its unusual use of
    # minimum per coordinate and maximum across joints.
    return bool(body[:, :2].min(axis=1).max() < 0)


def _body_copy(body):
    array = np.asarray(body)
    if (array.shape != _POSE_BODY_SHAPE or array.dtype != np.float32 or
            not np.isfinite(array).all()):
        raise ValueError("Wan pose carry requires finite normalized float32 body keypoints.")
    return np.array(array, dtype=np.float32, order="C", copy=True)


def apply_pose_carry(pose_data, carry_body=None):
    """Apply native previous-body fallback across a bounded PAF window.

    Faces, hands and all caller-owned arrays are left unchanged.  This adapter
    refuses retargeted pose data because its temporal transform is global.
    """
    if not isinstance(pose_data, dict) or pose_data.get("retarget_image") is not None or pose_data.get("refer_pose_meta") is not None:
        raise ValueError("Wan windowed pose carry supports the current non-retargeted pose path only.")
    originals = pose_data.get("pose_metas_original")
    metas = pose_data.get("pose_metas")
    if (not isinstance(originals, list) or not originals or not isinstance(metas, list) or
            len(originals) != len(metas)):
        raise ValueError("Wan pose data has no matching native pose metadata sequence.")
    if carry_body is not None:
        previous = _body_copy(carry_body)
    else:
        previous = None

    corrected = []
    final_body = None
    for raw_meta in originals:
        if not isinstance(raw_meta, dict) or set(raw_meta) != {
                "width", "height", "keypoints_body", "keypoints_left_hand", "keypoints_right_hand", "keypoints_face"}:
            raise ValueError("Wan pose metadata has an unsupported native shape.")
        if (type(raw_meta["width"]) is not int or type(raw_meta["height"]) is not int or
                raw_meta["width"] < 1 or raw_meta["height"] < 1):
            raise ValueError("Wan native pose metadata has an invalid source raster.")
        body = _body_copy(raw_meta["keypoints_body"])
        item = dict(raw_meta)
        for field, expected_shape in (("keypoints_left_hand", (21, 3)),
                                      ("keypoints_right_hand", (21, 3)),
                                      ("keypoints_face", (69, 3))):
            points = np.asarray(raw_meta[field])
            if (points.dtype != np.float32 or points.shape != expected_shape or
                    not np.isfinite(points).all()):
                raise ValueError("Wan native hand or face keypoints have an unsupported shape.")
            item[field] = points
        if previous is not None and _body_is_all_invalid(body):
            body = previous.copy()
        item["keypoints_body"] = body
        # The native recurrence always assigns the selected current body,
        # including the untouched invalid sentinel in an all-invalid shot.
        previous = body.copy()
        final_body = previous
        corrected.append(item)

    # ComfyUI imports custom-node packages using a transformed dynamic module
    # name.  Derive the helper from the actual native metadata object emitted
    # by PoseAndFaceDetection instead of importing the pack a second time.
    pose_meta_type = type(metas[0])
    converter = getattr(pose_meta_type, "from_humanapi_meta", None)
    if (pose_meta_type.__name__ != "AAPoseMeta" or
            "pose2d_utils" not in pose_meta_type.__module__ or not callable(converter)):
        raise ValueError("Wan pose data was not produced by the native AAPoseMeta path.")
    if any(type(meta) is not pose_meta_type for meta in metas):
        raise ValueError("Wan pose data contains mixed native metadata types.")
    new_data = dict(pose_data)
    new_data["pose_metas_original"] = corrected
    new_data["pose_metas"] = [pose_meta_type.from_humanapi_meta(item) for item in corrected]
    return new_data, final_body


def _carry_sha(body):
    if body is None:
        return NONE_CARRY_SHA256
    return _sha_bytes(_body_copy(body).tobytes(order="C"))


def _output_root():
    import folder_paths
    return Path(folder_paths.get_output_directory()).resolve(strict=True)


def _ensure_no_symlink(path: Path):
    if path.is_symlink():
        raise ValueError("Wan preparation state cannot use symbolic links.")


def _confined_directory(root: Path, *parts) -> Path:
    target = root
    for part in parts:
        target = target / part
        _ensure_no_symlink(target)
        target.mkdir(exist_ok=True)
        target = target.resolve(strict=True)
        if not target.is_relative_to(root):
            raise ValueError("Wan preparation state leaves the configured output directory.")
    return target


def _cache_directory(root: Path, cache_key: str) -> Path:
    if not _KEY_RE.fullmatch(cache_key):
        raise ValueError("Invalid Wan preparation cache key.")
    return _confined_directory(root, "genj", "wan_preparation_parts", cache_key)


def _review_pins(root: Path, clip_details):
    if not isinstance(clip_details, dict):
        raise ValueError("Wan preparation requires reviewed shot details.")
    shot_id = clip_details.get("review_shot_id")
    if not isinstance(shot_id, str) or not _SHOT_RE.fullmatch(shot_id):
        raise ValueError("Review and approve this shot in Zura Studio before preparation.")
    directory = root / "genj" / "reviews" / shot_id
    for parent in (root / "genj", root / "genj" / "reviews", directory):
        if parent.is_symlink():
            raise ValueError("The approved review uses a redirected directory.")
    if not directory.resolve(strict=True).is_relative_to(root):
        raise ValueError("The approved review leaves the configured output directory.")
    manifest_path = directory / "review.json"
    _ensure_no_symlink(manifest_path)
    raw = manifest_path.read_bytes()
    if not 1 <= len(raw) <= _MAX_MANIFEST_BYTES:
        raise ValueError("The approved review manifest is empty or too large.")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("The approved review manifest is invalid.") from error
    clip = manifest.get("clip") if isinstance(manifest, dict) else None
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if (not isinstance(manifest, dict) or manifest.get("shot_id") != shot_id or
            not isinstance(clip, dict) or not isinstance(files, dict) or
            clip.get("source_hash") != clip_details.get("source_hash") or
            clip.get("source") != clip_details.get("source") or
            clip.get("frames") != clip_details.get("frames") or clip.get("fps") != 24 or
            clip.get("start") != clip_details.get("start") or
            abs(float(clip.get("duration", -1)) - float(clip_details.get("duration", -2))) > 1e-6):
        raise ValueError("The approved review no longer matches the selected shot details.")
    mask_sha = files.get("mask.mp4")
    _safe_hash(mask_sha, "approved mask pin")
    if not isinstance(files.get("source.mp4"), str):
        raise ValueError("The approved review is missing its source-video digest.")
    verified_files = {}
    for name, expected_sha in files.items():
        if (not isinstance(name, str) or "/" in name or "\\" in name or
                Path(name).name != name or name in (".", "..") or
                not isinstance(expected_sha, str)):
            raise ValueError("The approved review contains an invalid file pin.")
        _safe_hash(expected_sha, "review file pin")
        file_path = directory / name
        _ensure_no_symlink(file_path)
        try:
            verified_files[name] = _stable_file_pin(file_path, expected_sha)
        except (OSError, ValueError) as error:
            raise ValueError("The approved review files changed after approval. Review the shot again.") from error
    return {"review_shot_id": shot_id,
            "source_pin": {"review_shot_id": shot_id,
                           "original_source_sha256": _safe_hash(clip_details.get("source_hash"), "source pin")},
            "review_pin": {"manifest_sha256": _sha_bytes(raw), "mask_sha256": mask_sha},
            "verified_files": verified_files}


def _expected_review_video_paths(root, clip_details):
    shot_id = clip_details.get("review_shot_id")
    if not isinstance(shot_id, str) or not _SHOT_RE.fullmatch(shot_id):
        raise ValueError("Decode only a source and mask already approved in Zura Studio.")
    review_dir = root / "genj" / "reviews" / shot_id
    for directory in (root / "genj", root / "genj" / "reviews", review_dir):
        if directory.is_symlink():
            raise ValueError("Wan preparation cannot follow a redirected review directory.")
    resolved_dir = review_dir.resolve(strict=True)
    if not resolved_dir.is_relative_to(root):
        raise ValueError("The approved source and mask leave the configured output folder.")
    render_long_edge = clip_details.get("render_long_edge", 0)
    if type(render_long_edge) is not int or render_long_edge < 0:
        raise ValueError("Wan preparation has an invalid reviewed render size.")
    if render_long_edge == 0:
        expected_source, expected_mask = review_dir / "source.mp4", review_dir / "mask.mp4"
    else:
        if not 256 <= render_long_edge <= 1920:
            raise ValueError("Wan preparation has an unsupported reviewed render size.")
        selected = clip_details.get("selected_path")
        if not isinstance(selected, str) or not Path(selected).is_absolute():
            raise ValueError("The approved high-resolution source path is missing.")
        expected_source = Path(selected)
        render_dir = expected_source.parent
        try:
            relative_dir = render_dir.relative_to(review_dir)
        except ValueError as error:
            raise ValueError("The approved high-resolution source must use its reviewed render cache.") from error
        expected_cache = re.fullmatch(
            rf"render_audio_v2_{render_long_edge}_x[12]_{clip_details.get('frames')}f", render_dir.name)
        if len(relative_dir.parts) != 1 or not expected_cache or expected_source.name != "source.mp4":
            raise ValueError("The high-resolution source is outside its approved render cache.")
        expected_mask = render_dir / "mask.mp4"
    return review_dir, expected_source, expected_mask


def _require_review_video_paths(root, clip_details, source_info, mask_info, source, mask_video, review_pins):
    review_dir, expected_source, expected_mask = _expected_review_video_paths(root, clip_details)
    resolved_dir = review_dir.resolve(strict=True)

    raw_paths = []
    for video in (source, mask_video):
        try:
            raw = Path(video.get_stream_source())
        except (AttributeError, TypeError) as error:
            raise ValueError("Wan preparation accepts only file-backed reviewed VIDEO inputs.") from error
        if not raw.is_absolute():
            raise ValueError("Wan preparation source paths must be absolute.")
        raw_paths.append(raw)
    if (raw_paths[0].resolve(strict=True) != expected_source.resolve(strict=True) or
            raw_paths[1].resolve(strict=True) != expected_mask.resolve(strict=True)):
        raise ValueError("Wan preparation requires the exact source/mask files returned by GenjLoadReviewedShot.")
    for raw, expected in zip(raw_paths, (expected_source, expected_mask)):
        if raw.is_symlink():
            raise ValueError("Wan preparation cannot follow a redirected reviewed video.")
        try:
            relative = raw.relative_to(review_dir)
        except ValueError as error:
            raise ValueError("The approved Wan source and mask must come from the review folder.") from error
        candidate = review_dir
        for component in relative.parts:
            candidate = candidate / component
            _ensure_no_symlink(candidate)
        if not expected.is_file():
            raise ValueError("A reviewed Wan source or mask file is missing.")
    if clip_details.get("render_long_edge", 0) == 0:
        render_pin = {"source": dict(review_pins["verified_files"]["source.mp4"]),
                      "mask": dict(review_pins["verified_files"]["mask.mp4"])}
    else:
        render_pin = {"source": _stable_file_pin(expected_source),
                      "mask": _stable_file_pin(expected_mask)}
    _render_pin_shape(render_pin)
    return render_pin


def _validate_render_cache_pin(root, clip_details, review_pins, render_pin):
    _render_pin_shape(render_pin)
    review_dir, expected_source, expected_mask = _expected_review_video_paths(root, clip_details)
    expected_files = (expected_source, expected_mask)
    for label, expected in zip(("source", "mask"), expected_files):
        pin = render_pin[label]
        path = Path(pin["path"])
        if path.resolve(strict=True) != expected.resolve(strict=True):
            raise ValueError("Wan window file pins do not match GenjLoadReviewedShot output paths.")
        try:
            relative = path.relative_to(review_dir)
        except ValueError as error:
            raise ValueError("Wan window file pins leave the approved review folder.") from error
        candidate = review_dir
        for component in relative.parts:
            candidate = candidate / component
            _ensure_no_symlink(candidate)
        current = path.stat()
        if current.st_size != pin["size"] or current.st_mtime_ns != pin["mtime_ns"]:
            raise ValueError("The reviewed Wan source or mask cache changed during preparation.")
    if clip_details.get("render_long_edge", 0) == 0:
        verified = review_pins["verified_files"]
        if render_pin != {"source": verified["source.mp4"], "mask": verified["mask.mp4"]}:
            raise ValueError("Wan source/mask file pins differ from the approved review files.")
    return render_pin


def _metadata(scope, speech_guide_key="", speech_guide_sha=""):
    if scope not in ("person", "head"):
        raise ValueError("Choose a supported Wan replacement scope.")
    footage = {"replacement_area": "Whole head" if scope == "head" else "Whole character",
               "video_info": {"fps": 24}, "keep_audio": False}
    if bool(speech_guide_key) != bool(speech_guide_sha):
        raise ValueError("Both verified Wan speech guide pins must be supplied together.")
    if speech_guide_key or speech_guide_sha:
        footage["speech_provenance"] = {
            "guide_key": _safe_hash(speech_guide_key, "speech guide key"),
            "guide_sha": _safe_hash(speech_guide_sha, "speech guide digest")}
    return footage


def _tensor_digest(tensor, *, label):
    if not isinstance(tensor, torch.Tensor) or tensor.device.type != "cpu" or tensor.dtype != torch.float32:
        raise ValueError(f"Wan {label} must be a CPU float32 tensor.")
    digest = hashlib.sha256()
    if tensor.ndim == 0:
        digest.update(tensor.contiguous().numpy().tobytes())
    else:
        for index in range(tensor.shape[0]):
            _interrupt()
            array = tensor[index].contiguous().numpy()
            digest.update(memoryview(array).cast("B"))
    return digest.hexdigest()


def _identity_pins(root, clip_details, reference, metadata, cache_key, render_cache_pin):
    if not isinstance(cache_key, str) or not _KEY_RE.fullmatch(cache_key):
        raise ValueError("Invalid Wan preparation cache key.")
    review = _review_pins(root, clip_details)
    render_pin = _validate_render_cache_pin(root, clip_details, review, render_cache_pin)
    _plain_tensor(reference, "character reference", dimensions=4, shape_tail=(3,), bounded_frames=1)
    reference_sha = _tensor_digest(reference, label="character reference")
    metadata_sha = _canonical_sha(metadata)
    return {"cache_key": cache_key,
            "source_pin": dict(review["source_pin"], window_source_sha256=""),
            "review_pin": review["review_pin"],
            "render_cache_pin": render_pin,
            "reference_sha256": reference_sha,
            "footage_metadata_sha256": metadata_sha}


def _body_json(body):
    return _body_copy(body).tolist()


def _load_previous_carry(root, cache_key, window, pins):
    start, count, total = _window_fields(window)
    if start == 0:
        return None, {"kind": "none", "sha256": NONE_CARRY_SHA256,
                      "previous_receipt_sha256": NONE_CARRY_SHA256}
    directory = _cache_directory(root, cache_key)
    carry_path = directory / f"carry_{start:08d}.json"
    _ensure_no_symlink(carry_path)
    if not carry_path.is_file() or carry_path.stat().st_size > 256 * 1024:
        raise ValueError("The preceding Wan preparation part has not saved a valid pose carry.")
    try:
        state = json.loads(carry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("The preceding Wan pose carry file is corrupt.") from error
    wanted_fields = {"schema", "cache_key", "end_frame", "total_frames", "source_pin", "review_pin",
                     "render_cache_pin",
                     "reference_sha256", "footage_metadata_sha256", "carry_out_sha256", "carry_body",
                     "receipt_name", "receipt_sha256"}
    if (not isinstance(state, dict) or set(state) != wanted_fields or state.get("schema") != CARRY_SCHEMA or
            state.get("cache_key") != cache_key or state.get("end_frame") != start or
            state.get("total_frames") != total):
        raise ValueError("The saved Wan pose carry belongs to another preparation timeline.")
    for key in ("source_pin", "review_pin", "render_cache_pin", "reference_sha256", "footage_metadata_sha256"):
        expected = pins[key]
        actual = state.get(key)
        if key == "source_pin":
            expected = {k: v for k, v in expected.items() if k != "window_source_sha256"}
        if actual != expected:
            raise ValueError("The saved Wan pose carry belongs to different approved source or settings.")
    body = _body_copy(np.asarray(state["carry_body"], dtype=np.float32))
    carry_sha = _carry_sha(body)
    _safe_hash(state["carry_out_sha256"], "pose carry digest")
    _safe_hash(state["receipt_sha256"], "preceding receipt digest")
    if carry_sha != state["carry_out_sha256"]:
        raise ValueError("The saved Wan pose carry body failed its digest check.")
    if not isinstance(state["receipt_name"], str) or not re.fullmatch(
            r"part_[0-9]{8}_[0-9]{5}\.receipt\.json", state["receipt_name"]):
        raise ValueError("The saved Wan pose carry has an invalid predecessor link.")
    receipt_path = directory / state["receipt_name"]
    _ensure_no_symlink(receipt_path)
    if not receipt_path.is_file() or receipt_path.stat().st_size > _MAX_RECEIPT_BYTES:
        raise ValueError("The preceding Wan preparation receipt is missing or too large.")
    receipt_raw = receipt_path.read_bytes()
    if _sha_bytes(receipt_raw) != state["receipt_sha256"]:
        raise ValueError("The preceding Wan preparation receipt changed after the pose carry was saved.")
    try:
        receipt = json.loads(receipt_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("The preceding Wan preparation receipt is corrupt.") from error
    if not isinstance(receipt, dict):
        raise ValueError("The preceding Wan preparation receipt is corrupt.")
    prev_start, prev_count = receipt.get("start"), receipt.get("count")
    receipt_source = receipt.get("source_pin")
    expected_source = {k: v for k, v in pins["source_pin"].items() if k != "window_source_sha256"}
    expected_previous_kind = "none" if prev_start == 0 else "body"
    if (receipt.get("schema") != PART_SCHEMA or receipt.get("cache_key") != cache_key or
            type(prev_start) is not int or type(prev_count) is not int or prev_start + prev_count != start or
            receipt.get("total_frames") != total or receipt.get("carry_out_sha256") != carry_sha or
            receipt.get("carry_in_kind") != expected_previous_kind or
            not isinstance(receipt_source, dict) or
            {k: v for k, v in receipt_source.items() if k != "window_source_sha256"} != expected_source or
            receipt.get("review_pin") != pins["review_pin"] or
            receipt.get("render_cache_pin") != pins["render_cache_pin"] or
            receipt.get("reference_sha256") != pins["reference_sha256"] or
            receipt.get("footage_metadata_sha256") != pins["footage_metadata_sha256"]):
        raise ValueError("Wan pose carry does not continue the immediately preceding preparation part.")
    path_name = receipt.get("path_name")
    if not isinstance(path_name, str) or not re.fullmatch(r"part_[0-9]{8}_[0-9]{5}\.pt", path_name):
        raise ValueError("The preceding Wan preparation receipt has an invalid part path.")
    part_path = directory / path_name
    _ensure_no_symlink(part_path)
    receipt_path_value = receipt.get("path")
    if not isinstance(receipt_path_value, str) or receipt_path_value != str(part_path.resolve(strict=True)):
        raise ValueError("The preceding Wan preparation receipt has an invalid part path.")
    if not part_path.is_file():
        raise ValueError("The preceding Wan preparation part is missing.")
    before = part_path.stat()
    part_sha = _file_sha(part_path)
    after = part_path.stat()
    if (before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns or
            before.st_size != receipt.get("size") or before.st_mtime_ns != receipt.get("mtime_ns") or
            part_sha != receipt.get("sha256")):
        raise ValueError("The preceding Wan preparation part changed after its receipt was approved.")
    return body, {"kind": "body", "sha256": carry_sha,
                  "previous_receipt_sha256": state["receipt_sha256"]}


def carry_pose_window(pose_data, window, clip_details, reference, cache_key, scope,
                      speech_guide_key="", speech_guide_sha="", output_root=None):
    start, count, total = _window_fields(window)
    root = Path(output_root).resolve(strict=True) if output_root is not None else _output_root()
    metadata = _metadata(scope, speech_guide_key, speech_guide_sha)
    pins = _identity_pins(root, clip_details, reference, metadata, cache_key,
                          window["render_cache_pin"])
    if int(clip_details.get("frames", -1)) != total:
        raise ValueError("Wan pose carry window does not match the reviewed full clip.")
    carry_in, carry_fields = _load_previous_carry(root, cache_key, window, pins)
    corrected, carry_out = apply_pose_carry(pose_data, carry_in)
    if len(corrected["pose_metas_original"]) != count:
        raise ValueError("Wan pose inference must cover exactly the bounded source window.")
    state = {"schema": CARRY_SCHEMA, "cache_key": cache_key, "start": start,
             "count": count, "total_frames": total, "source_pin": pins["source_pin"],
             "review_pin": pins["review_pin"], "reference_sha256": pins["reference_sha256"],
             "render_cache_pin": pins["render_cache_pin"],
             "footage_metadata_sha256": pins["footage_metadata_sha256"],
             "carry_in_kind": carry_fields["kind"], "carry_in_sha256": carry_fields["sha256"],
             "previous_receipt_sha256": carry_fields["previous_receipt_sha256"],
             "carry_out_sha256": _carry_sha(carry_out), "carry_out_body": _body_json(carry_out)}
    return corrected, state


def _save_json_atomic(path: Path, value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(data) > _MAX_RECEIPT_BYTES:
        raise ValueError("Wan preparation receipt exceeds the safe metadata limit.")
    _ensure_no_symlink(path)
    if path.exists():
        raise ValueError("This Wan preparation part already exists. Use a new preparation cache key.")
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    published = False
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        published = True
    except BaseException:
        if published:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return data


def save_preparation_part(frames, mask, pose, face, reference, window, carry_state,
                          clip_details, cache_key, scope, speech_guide_key="",
                          speech_guide_sha="", output_root=None, interrupt=_interrupt):
    start, count, total = _window_fields(window)
    if not isinstance(carry_state, dict) or carry_state.get("schema") != CARRY_SCHEMA:
        raise ValueError("Apply the verified Wan pose carry before saving a preparation part.")
    if (carry_state.get("cache_key") != cache_key or carry_state.get("start") != start or
            carry_state.get("count") != count or carry_state.get("total_frames") != total):
        raise ValueError("Wan pose carry and preparation part describe different frame windows.")
    root = Path(output_root).resolve(strict=True) if output_root is not None else _output_root()
    metadata = _metadata(scope, speech_guide_key, speech_guide_sha)
    pins = _identity_pins(root, clip_details, reference, metadata, cache_key,
                          window["render_cache_pin"])
    for field in ("source_pin", "review_pin", "render_cache_pin", "reference_sha256", "footage_metadata_sha256"):
        wanted = pins[field]
        got = carry_state.get(field)
        if field == "source_pin":
            wanted = {k: v for k, v in wanted.items() if k != "window_source_sha256"}
            got = {k: v for k, v in got.items() if k != "window_source_sha256"} if isinstance(got, dict) else got
        if got != wanted:
            raise ValueError("Wan pose carry provenance does not match this preparation part.")
    if carry_state.get("carry_in_kind") not in ("none", "body"):
        raise ValueError("Wan pose carry has an invalid initial-state marker.")
    carry_in_sha = _safe_hash(carry_state.get("carry_in_sha256"), "pose carry input")
    carry_out_sha = _safe_hash(carry_state.get("carry_out_sha256"), "pose carry output")
    carry_out_body = _body_copy(np.asarray(carry_state.get("carry_out_body"), dtype=np.float32))
    if _carry_sha(carry_out_body) != carry_out_sha:
        raise ValueError("Wan pose carry output body failed its digest check.")
    if start == 0:
        if carry_state.get("carry_in_kind") != "none" or carry_in_sha != NONE_CARRY_SHA256:
            raise ValueError("The first Wan preparation part must start with the canonical empty carry.")
    else:
        _, expected_in = _load_previous_carry(root, cache_key, window, pins)
        if (carry_state.get("carry_in_kind") != "body" or carry_in_sha != expected_in["sha256"] or
                carry_state.get("previous_receipt_sha256") != expected_in["previous_receipt_sha256"]):
            raise ValueError("Wan preparation pose carry is stale or not adjacent to its predecessor.")

    _plain_tensor(frames, "source frames", dimensions=4, shape_tail=(3,), bounded_frames=count)
    _plain_tensor(mask, "character_mask", dimensions=3, bounded_frames=count, allow_empty_mask=True)
    _plain_tensor(pose, "pose frames", dimensions=4, shape_tail=(3,), bounded_frames=count)
    _plain_tensor(face, "face frames", dimensions=4, shape_tail=(3,), bounded_frames=count)
    _plain_tensor(reference, "character reference", dimensions=4, shape_tail=(3,), bounded_frames=1)
    if tuple(mask.shape) != tuple(frames.shape[:3]):
        raise ValueError("Wan performer mask must match the source window raster exactly.")
    if tuple(frames.shape[1:3]) != (window["height"], window["width"]):
        raise ValueError("Wan source raster differs from its bounded window metadata.")
    for name, tensor in (("pose", pose), ("face", face)):
        if tensor.shape[0] != count:
            raise ValueError(f"Wan {name} images must cover exactly this preparation window.")
    _safe_hash(clip_details.get("source_hash"), "source pin")
    if int(clip_details.get("frames", -1)) != total:
        raise ValueError("Wan part does not match the reviewed full clip length.")

    window_source_sha = _tensor_digest(frames, label="source frames")
    source_pin = dict(pins["source_pin"], window_source_sha256=window_source_sha)
    directory = _cache_directory(root, cache_key)
    part_name = f"part_{start:08d}_{count:05d}.pt"
    receipt_name = f"part_{start:08d}_{count:05d}.receipt.json"
    part_path, receipt_path = directory / part_name, directory / receipt_name
    for candidate in (part_path, receipt_path):
        _ensure_no_symlink(candidate)
        if candidate.exists():
            raise ValueError("This Wan preparation part already exists. Use a new preparation cache key.")
    payload = {"version": 1, "footage": {
        "frames": frames, "character_mask": mask, "pose_video": pose, "face_video": face,
        **metadata}, "reference": reference}
    temporary = part_path.with_name(part_path.name + "." + uuid.uuid4().hex + ".tmp")
    checkpoint_path = directory / f"carry_{start + count:08d}.json"
    checkpoint_needed = start + count < total
    if checkpoint_needed:
        _ensure_no_symlink(checkpoint_path)
        if checkpoint_path.exists():
            raise ValueError("This Wan preparation pose checkpoint already exists. Use a new cache key.")
    created_paths = []
    try:
        with temporary.open("xb") as handle:
            torch.save(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        interrupt()
        os.link(temporary, part_path)
        created_paths.append(part_path)
        temporary.unlink()
        stat = part_path.stat()
        digest = _file_sha(part_path, interrupt)
        receipt = {"schema": PART_SCHEMA, "cache_key": cache_key, "path": str(part_path.resolve(strict=True)),
                   "path_name": part_name, "start": start, "count": count, "total_frames": total,
                   "sha256": digest, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                   "source_pin": source_pin, "review_pin": pins["review_pin"],
                   "render_cache_pin": pins["render_cache_pin"],
                   "reference_sha256": pins["reference_sha256"],
                   "footage_metadata_sha256": pins["footage_metadata_sha256"],
                   "carry_in_kind": carry_state["carry_in_kind"],
                   "carry_in_sha256": carry_in_sha,
                   "carry_out_sha256": carry_out_sha,
                   "previous_receipt_sha256": carry_state.get("previous_receipt_sha256")}
        receipt_raw = _save_json_atomic(receipt_path, receipt)
        created_paths.append(receipt_path)
        receipt_sha = _sha_bytes(receipt_raw)
        end = start + count
        if end < total:
            checkpoint = {"schema": CARRY_SCHEMA, "cache_key": cache_key, "end_frame": end,
                          "total_frames": total,
                          "source_pin": {k: v for k, v in source_pin.items() if k != "window_source_sha256"},
                          "review_pin": pins["review_pin"],
                          "render_cache_pin": pins["render_cache_pin"],
                          "reference_sha256": pins["reference_sha256"],
                          "footage_metadata_sha256": pins["footage_metadata_sha256"],
                          "carry_out_sha256": carry_out_sha,
                          "carry_body": _body_json(carry_out_body),
                          "receipt_name": receipt_name, "receipt_sha256": receipt_sha}
            _save_json_atomic(checkpoint_path, checkpoint)
            created_paths.append(checkpoint_path)
        return receipt
    except BaseException:
        for created in reversed(created_paths):
            try:
                _ensure_no_symlink(created)
                created.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class ZuraWanPreparationWindow:
    """Decode an artist-bounded native source/mask window (no inference)."""
    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "decode"
    RETURN_TYPES = ("IMAGE", "MASK", "INT", "INT", "ZURA_WAN_WINDOW")
    RETURN_NAMES = ("source_frames", "approved_mask", "width", "height", "window")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source": ("VIDEO",), "mask_video": ("VIDEO",),
                             "clip_details": ("GENJ_CLIP",),
                             "start_frame": ("INT", {"default": 0, "min": 0, "max": 1000000}),
                             "frame_count": ("INT", {"default": 81, "min": 1, "max": MAX_PART_FRAMES})}}

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def decode(self, source, mask_video, clip_details, start_frame, frame_count):
        return decode_preparation_window(source, mask_video, clip_details, start_frame, frame_count)


class ZuraWanCarryPoseWindow:
    """Preserve WanAnimatePreprocess's body fallback across separate windows."""
    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "apply"
    RETURN_TYPES = ("POSEDATA", "ZURA_WAN_POSE_CARRY")
    RETURN_NAMES = ("pose_data", "carry_state")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"pose_data": ("POSEDATA",), "window": ("ZURA_WAN_WINDOW",),
                             "clip_details": ("GENJ_CLIP",), "reference": ("IMAGE",),
                             "cache_key": ("STRING", {"default": ""}),
                             "scope": (["person", "head"],)},
                "optional": {"speech_guide_key": ("STRING", {"default": ""}),
                             "speech_guide_sha": ("STRING", {"default": ""})}}

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def apply(self, pose_data, window, clip_details, reference, cache_key, scope,
              speech_guide_key="", speech_guide_sha=""):
        pose, carry = carry_pose_window(pose_data, window, clip_details, reference, cache_key,
                                        scope, speech_guide_key, speech_guide_sha)
        return pose, carry


class ZuraWanSavePreparationPart:
    """Write one ordinary native-compatible Wan preparation shard and receipt."""
    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "save"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("approved_part_receipt",)
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"frames": ("IMAGE",), "mask": ("MASK",), "pose": ("IMAGE",),
                             "face": ("IMAGE",), "reference": ("IMAGE",),
                             "window": ("ZURA_WAN_WINDOW",),
                             "carry_state": ("ZURA_WAN_POSE_CARRY",),
                             "clip_details": ("GENJ_CLIP",),
                             "cache_key": ("STRING", {"default": ""}),
                             "scope": (["person", "head"],)},
                "optional": {"speech_guide_key": ("STRING", {"default": ""}),
                             "speech_guide_sha": ("STRING", {"default": ""})}}

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def save(self, frames, mask, pose, face, reference, window, carry_state, clip_details,
             cache_key, scope, speech_guide_key="", speech_guide_sha=""):
        receipt = save_preparation_part(frames, mask, pose, face, reference, window, carry_state,
                                        clip_details, cache_key, scope, speech_guide_key, speech_guide_sha)
        return {"ui": {"text": [f"Saved bounded Wan preparation part {receipt['start']}-{receipt['start'] + receipt['count']}. "]},
                "result": (receipt["path"],)}
