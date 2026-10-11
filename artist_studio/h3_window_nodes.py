"""Unregistered, data-only IO helpers for bounded native MiniMax H3 windows.

These helpers decode only requested frame intervals through ComfyUI's native
VIDEO ``get_stream_source`` contract. They do not call ``get_components``, run
models, infer masks, or register nodes. Durable state is confined to the
configured ComfyUI output folder and addressed by neutral digests.
"""

from __future__ import annotations

from contextlib import contextmanager
import copy
from dataclasses import dataclass, fields
from fractions import Fraction
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Iterator

import av
import numpy as np
import torch

from .h3_windows import (
    H3_CONTEXT_FRAMES,
    H3_FPS,
    H3_PREFIX_FRAMES,
    H3VideoPrefix,
    H3Window,
    apply_video_prefix,
    audio_sample_bounds,
    extract_video_prefix,
    slice_audio_frames,
)


STATE_SCHEMA = "zura.h3.continuation.v2"
_MAX_STATE_BYTES = 256 * 1024 * 1024
_WINDOW_FIELDS = frozenset(field.name for field in fields(H3Window))


@dataclass(frozen=True)
class H3WindowData:
    """Bounded source tensors and shot-level metadata for one H3 context."""

    source_frames: torch.Tensor
    combined_mask: torch.Tensor
    genuine_mask: torch.Tensor
    whole_shot_genuine_union: torch.Tensor
    audio: dict
    clip_details: dict
    window: H3Window


@dataclass(frozen=True)
class H3ContinuationState:
    """Safetensors-backed guide and latent prefix for one same-shot handoff."""

    prefix: H3VideoPrefix
    guide_frames: torch.Tensor
    previous_window: H3Window
    raster: tuple[int, int]
    generation_digest: str
    model_digest: str
    state_sha256: str


def _window_from_json(value: str) -> H3Window:
    """Parse the planner's internal window record without exposing manual IDs."""

    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("Connect one bounded H3 window record from the internal planner.")
    try:
        record = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("The internal H3 window record is not valid JSON.") from exc
    if not isinstance(record, dict) or set(record) != _WINDOW_FIELDS:
        raise ValueError("The internal H3 window record has missing or unexpected fields.")
    try:
        window = H3Window(**record)
    except (TypeError, ValueError) as exc:
        raise ValueError("The internal H3 window record is malformed.") from exc
    return _validate_window(window)


def _int(value: object, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer of at least {minimum}.")
    return value


def _positive_raster(raster: tuple[int, int], *, multiple32: bool) -> tuple[int, int]:
    if (not isinstance(raster, (tuple, list)) or len(raster) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in raster)):
        raise ValueError("Video raster must be a positive (width, height) pair.")
    width, height = raster
    if multiple32 and (width % 32 or height % 32):
        raise ValueError("The H3 generation width and height must be multiples of 32.")
    return width, height


def _validate_window(window: H3Window, total_frames: int | None = None) -> H3Window:
    if not isinstance(window, H3Window):
        raise ValueError("Supply a validated H3Window from the bounded planner.")
    integer_fields = (
        (window.index, "window index", 0), (window.shot_index, "shot index", 0),
        (window.shot_start, "shot start", 0), (window.shot_end, "shot end", 1),
        (window.input_start, "window input start", 0),
        (window.valid_frames, "window valid frame count", 1),
        (window.owned_start, "owned frame start", 0),
        (window.owned_end, "owned frame end", 1),
        (window.overlap_frames, "window overlap", 0),
        (window.padded_frames, "window padding", 0),
    )
    for value, name, minimum in integer_fields:
        _int(value, name, minimum)
    if total_frames is not None:
        _int(total_frames, "clip frame count", 1)
        if window.shot_end > total_frames:
            raise ValueError("The H3 window shot lies beyond the selected clip.")
    if (window.shot_start >= window.shot_end or window.valid_frames > H3_CONTEXT_FRAMES
            or window.input_start < window.shot_start
            or window.input_start + window.valid_frames != window.owned_end
            or window.owned_start >= window.owned_end
            or window.owned_start < window.shot_start or window.owned_end > window.shot_end
            or window.padded_frames != H3_CONTEXT_FRAMES - window.valid_frames):
        raise ValueError("The H3 window has inconsistent shot, context or ownership bounds.")
    if window.overlap_frames not in (0, H3_PREFIX_FRAMES):
        raise ValueError("H3 windows may repeat exactly five frames or none.")
    if window.overlap_frames:
        if (window.input_start + H3_PREFIX_FRAMES != window.owned_start
                or window.owned_start - window.shot_start < H3_PREFIX_FRAMES):
            raise ValueError("The H3 prefix cannot reach across the start of its shot.")
    elif window.input_start != window.owned_start:
        raise ValueError("A cut-reset H3 window must begin at its owned frame.")
    if window.carry_video_tokens is None:
        if window.owned_end != window.shot_end:
            raise ValueError("A terminal H3 window must end at its shot boundary.")
    else:
        if window.carry_video_tokens != 2 or window.owned_end >= window.shot_end:
            raise ValueError("Only a two-token same-shot prefix can continue to another window.")
        from .h3_windows import h3_video_token_count
        h3_video_token_count(window.valid_frames)
    return window


@contextmanager
def _open_video(video):
    """Open only the native VIDEO stream source and its declared active trim."""

    source_method = getattr(video, "get_stream_source", None)
    if not callable(source_method):
        raise ValueError("Connect a ComfyUI VIDEO with a stream source.")
    source = source_method()
    if isinstance(source, io.BytesIO):
        source.seek(0)
    elif isinstance(source, os.PathLike):
        source = str(source)
    elif not isinstance(source, str):
        raise ValueError("The native VIDEO stream source must be a path or BytesIO.")

    trim_method = getattr(video, "get_active_trim_window", None)
    if callable(trim_method):
        trim_start, trim_duration = trim_method()
    else:
        trim_start, trim_duration = 0.0, 0.0
    start_frame, duration_frames = _trim_frame_window(trim_start, trim_duration)
    start = Fraction(start_frame, H3_FPS)
    duration = Fraction(duration_frames, H3_FPS)

    try:
        container = av.open(source, mode="r")
    except Exception as exc:
        raise ValueError("The ComfyUI VIDEO stream source could not be opened.") from exc
    try:
        streams = [stream for stream in container.streams if stream.type == "video"]
        if len(streams) != 1:
            raise ValueError("H3 window decoding requires exactly one video stream.")
        stream = streams[0]
        try:
            rate = Fraction(stream.average_rate) if stream.average_rate else None
        except (TypeError, ValueError, ZeroDivisionError):
            rate = None
        if rate != H3_FPS:
            raise ValueError("Prepare source and masks at a constant 24 fps before H3 window decoding.")
        if not stream.time_base or stream.width < 1 or stream.height < 1:
            raise ValueError("The native VIDEO stream has invalid timing or dimensions.")
        yield container, stream, start, duration
    finally:
        container.close()


def _trim_frame_window(trim_start, trim_duration) -> tuple[int, int]:
    """Normalize native float trim values to exact global 24 fps frame counts."""

    try:
        raw_start = Fraction(str(trim_start))
        raw_duration = Fraction(str(trim_duration))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError("The native VIDEO trim window is invalid.") from exc
    start_frames = raw_start * H3_FPS
    duration_frames = raw_duration * H3_FPS
    start_index = round(start_frames)
    duration_count = round(duration_frames)
    if (raw_start < 0 or raw_duration < 0
            or abs(start_frames - start_index) > Fraction(1, 1_000_000)
            or abs(duration_frames - duration_count) > Fraction(1, 1_000_000)):
        raise ValueError("H3 window decoding requires a non-negative frame-aligned VIDEO trim.")
    return start_index, duration_count


def _video_trim_frames(video) -> tuple[int, int]:
    method = getattr(video, "get_active_trim_window", None)
    trim_start, trim_duration = method() if callable(method) else (0.0, 0.0)
    return _trim_frame_window(trim_start, trim_duration)


def _frame_index(frame, stream, trim_start: Fraction) -> int:
    if frame.pts is None:
        raise ValueError("A VIDEO frame is missing its presentation timestamp.")
    time_base = frame.time_base or stream.time_base
    timestamp = Fraction(frame.pts) * Fraction(time_base)
    relative = (timestamp - trim_start) * H3_FPS
    index = round(relative)
    if abs(relative - index) > Fraction(1, 1000):
        raise ValueError("The VIDEO stream is not aligned to the selected 24 fps timeline.")
    return index


def _iter_video_arrays(video, start_frame: int, end_frame: int,
                       pixel_format: str, expected_raster: tuple[int, int] | None = None
                       ) -> Iterator[tuple[int, np.ndarray]]:
    """Yield an exact requested interval after a keyframe seek, without a full decode."""

    start_frame = _int(start_frame, "decode start", 0)
    end_frame = _int(end_frame, "decode end", 1)
    if end_frame <= start_frame:
        raise ValueError("The requested H3 decode interval is empty.")
    with _open_video(video) as (container, stream, trim_start, trim_duration):
        width, height = int(stream.width), int(stream.height)
        if expected_raster is not None and (width, height) != expected_raster:
            raise ValueError("Source, mask and clip metadata rasters do not match.")
        if trim_duration and end_frame > int(trim_duration * H3_FPS):
            raise ValueError("The requested H3 frames lie beyond the native VIDEO trim.")
        time_base = Fraction(stream.time_base)
        requested_time = trim_start + Fraction(start_frame, H3_FPS)
        requested_pts = int(requested_time / time_base)
        try:
            container.seek(requested_pts, stream=stream, backward=True, any_frame=False)
        except Exception as exc:
            raise ValueError("ComfyUI could not seek to the requested H3 frame interval.") from exc
        expected = start_frame
        for frame in container.decode(stream):
            index = _frame_index(frame, stream, trim_start)
            if index < start_frame:
                continue
            if index >= end_frame:
                break
            if index != expected:
                raise ValueError("The source or mask stream has a missing or duplicate frame.")
            if (frame.width, frame.height) != (width, height):
                raise ValueError("The VIDEO raster changed within the requested interval.")
            array = frame.to_ndarray(format=pixel_format)
            if array.shape[:2] != (height, width):
                raise ValueError("The decoded frame raster does not match its VIDEO stream.")
            yield index, np.ascontiguousarray(array)
            expected += 1
        if expected != end_frame:
            raise ValueError("The native VIDEO ended before the requested H3 frame interval.")


def _decode_exact(video, start: int, end: int, pixel_format: str,
                  expected_raster: tuple[int, int]) -> list[np.ndarray]:
    return [frame for _, frame in _iter_video_arrays(video, start, end,
                                                      pixel_format, expected_raster)]


def _video_raster(video) -> tuple[int, int]:
    """Read stream metadata without materializing frames or calling get_components."""

    with _open_video(video) as (_, stream, _, _):
        return int(stream.width), int(stream.height)


def _decode_genuine_window_and_union(video, window: H3Window,
                                     raster: tuple[int, int]) -> tuple[list[np.ndarray], np.ndarray]:
    window_frames: list[np.ndarray] = []
    union = np.zeros((raster[1], raster[0]), dtype=np.bool_)
    expected = window.shot_start
    for index, gray in _iter_video_arrays(video, window.shot_start, window.shot_end,
                                          "gray", raster):
        if index != expected:
            raise ValueError("The genuine performer mask has a missing or duplicate shot frame.")
        binary = gray >= 128
        np.logical_or(union, binary, out=union)
        if window.input_start <= index < window.input_end:
            window_frames.append(binary)
        expected += 1
    if expected != window.shot_end or len(window_frames) != window.valid_frames:
        raise ValueError("The genuine performer mask does not cover the full shot and H3 window.")
    return window_frames, union


def _stack_rgb(frames: list[np.ndarray]) -> torch.Tensor:
    return torch.from_numpy(np.stack(frames, axis=0).copy()).to(torch.float32).div_(255.0)


def _stack_masks(frames: list[np.ndarray]) -> torch.Tensor:
    values = np.stack(frames, axis=0)
    if values.dtype == np.bool_:
        binary = values
    else:
        binary = values >= 128
    return torch.from_numpy(binary.copy()).to(torch.float32)


def _pad_context(frames: torch.Tensor, valid_frames: int) -> torch.Tensor:
    if frames.ndim < 1 or frames.shape[0] != valid_frames or valid_frames < 1:
        raise ValueError("Decoded H3 frames do not match the real window length.")
    padding = H3_CONTEXT_FRAMES - valid_frames
    if padding < 0:
        raise ValueError("The decoded H3 window exceeds its 124-frame context.")
    if padding:
        frames = torch.cat((frames, frames[-1:].expand(padding, *frames.shape[1:])), dim=0)
    return frames.contiguous()


def _shot_text_record(details: dict, window: H3Window, mask_raster: tuple[int, int]) -> dict:
    records = details.get("text_regions_by_shot")
    if records is None:
        if window.shot_index != 0 or window.shot_start != 0 or window.shot_end != details["frames"]:
            raise ValueError("Cut-aware H3 cleanup needs shot-local text_regions_by_shot metadata.")
        regions = details.get("text_regions", [])
        record = {"start": window.shot_start, "end": window.shot_end, "regions": regions}
    else:
        if not isinstance(records, list) or window.shot_index >= len(records):
            raise ValueError("The H3 shot index has no matching shot-local text regions.")
        record = records[window.shot_index]
        if (not isinstance(record, dict) or record.get("start") != window.shot_start
                or record.get("end") != window.shot_end
                or not isinstance(record.get("regions"), list)):
            raise ValueError("The H3 shot-local text regions do not match this verified shot.")
        regions = record["regions"]
    for region in regions:
        if not isinstance(region, dict):
            raise ValueError("A shot-local text rectangle is malformed.")
        try:
            x, y, width, height = (float(region[name]) for name in ("x", "y", "width", "height"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("A shot-local text rectangle is malformed.") from exc
        if (not all(math.isfinite(v) for v in (x, y, width, height))
                or width <= 0 or height <= 0):
            raise ValueError("A shot-local text rectangle is malformed.")
    record = {"start": window.shot_start, "end": window.shot_end,
              "regions": [dict(region) for region in regions]}
    ref_size = details.get("text_regions_size")
    if regions and ref_size is not None:
        if _positive_raster(tuple(ref_size), multiple32=False) != mask_raster:
            raise ValueError("The selected shot's text regions use a different review mask raster.")
    elif regions and ref_size is None:
        raise ValueError("Shot-local text regions need their original detection raster.")
    return record


def prepare_full_audio_timeline(audio: dict, total_frames: int,
                                audio_start_frame: int = 0) -> dict:
    """Place one already-resampled CPU AUDIO on the global clip timeline.

    A single full-timeline zero buffer is created before any window is sliced.
    No resampling is performed here. ``audio_start_frame`` is the once-applied
    global timeline onset. The selected track's user in-point must already have
    been applied upstream; it is separate from this placement offset.
    """

    total_frames = _int(total_frames, "total_frames", 1)
    audio_start_frame = _int(audio_start_frame, "audio_start_frame", 0)
    if audio_start_frame > total_frames or not isinstance(audio, dict):
        raise ValueError("Provide one audio track and an in-range global audio start.")
    try:
        waveform = audio["waveform"]
        sample_rate = _int(audio["sample_rate"], "audio sample rate", 1)
    except (KeyError, TypeError) as exc:
        raise ValueError("Provide one valid native AUDIO waveform and sample rate.") from exc
    if (not isinstance(waveform, torch.Tensor) or waveform.layout != torch.strided
            or waveform.device.type != "cpu" or waveform.ndim != 3
            or waveform.shape[0] != 1 or waveform.shape[1] not in (1, 2)
            or waveform.shape[-1] < 1 or not waveform.is_floating_point()
            or not bool(torch.isfinite(waveform).all())):
        raise ValueError("The full AUDIO track must be finite mono or stereo CPU samples.")
    timeline_samples = audio_sample_bounds(0, total_frames, sample_rate)[1]
    if timeline_samples < 1:
        raise ValueError("The selected clip is too short for the supplied audio sample rate.")
    onset_sample = audio_sample_bounds(0, audio_start_frame, sample_rate)[1]
    if onset_sample > timeline_samples:
        raise ValueError("The audio onset lies beyond the selected clip.")
    timeline = torch.zeros((1, waveform.shape[1], timeline_samples), dtype=waveform.dtype)
    count = min(waveform.shape[-1], timeline_samples - onset_sample)
    if count:
        timeline[..., onset_sample:onset_sample + count] = waveform[..., :count]
    return {"waveform": timeline, "sample_rate": sample_rate,
            "h3_timeline_frames": total_frames, "h3_audio_start_frame": audio_start_frame}


def slice_audio_window(full_timeline: dict, window: H3Window,
                       total_frames: int) -> dict:
    """Slice one global audio interval and silence-pad only the 124-frame tail."""

    _validate_window(window, total_frames)
    if (not isinstance(full_timeline, dict)
            or full_timeline.get("h3_timeline_frames") != total_frames):
        raise ValueError("Use the already-resampled full audio timeline for this clip.")
    waveform = full_timeline.get("waveform")
    sample_rate = _int(full_timeline.get("sample_rate"), "audio sample rate", 1)
    expected_total = audio_sample_bounds(0, total_frames, sample_rate)[1]
    if (not isinstance(waveform, torch.Tensor) or waveform.device.type != "cpu"
            or waveform.layout != torch.strided or waveform.ndim != 3 or waveform.shape[0] != 1
            or waveform.shape[1] not in (1, 2)
            or waveform.shape[-1] != expected_total
            or waveform.shape[-1] < 1 or not waveform.is_floating_point()
            or not bool(torch.isfinite(waveform).all())):
        raise ValueError("The H3 audio timeline has a mismatched shape or invalid samples.")

    actual_end = min(window.input_end, total_frames)
    segment = slice_audio_frames(waveform, window.input_start, actual_end, sample_rate)
    start_sample, _ = audio_sample_bounds(window.input_start, window.input_start, sample_rate)
    context_end_sample = audio_sample_bounds(
        window.input_start, window.input_start + H3_CONTEXT_FRAMES, sample_rate)[1]
    target_samples = context_end_sample - start_sample
    if segment.shape[-1] > target_samples:
        raise ValueError("The H3 window audio exceeds its native model context.")
    if segment.shape[-1] < target_samples:
        segment = torch.nn.functional.pad(segment, (0, target_samples - segment.shape[-1]))
    return {"waveform": segment.contiguous(), "sample_rate": sample_rate}


def decode_h3_window_data(source_video, combined_mask_video, genuine_mask_video,
                          full_audio_timeline: dict, clip_details: dict,
                          window: H3Window) -> H3WindowData:
    """Decode only one H3 input context and stream the genuine mask across its shot."""

    if not isinstance(clip_details, dict):
        raise ValueError("Connect the reviewed clip details for this H3 window.")
    total_frames = _int(clip_details.get("frames"), "clip frame count", 1)
    if clip_details.get("fps") != H3_FPS:
        raise ValueError("Prepare the selected clip at 24 fps before H3 continuation.")
    _validate_window(window, total_frames)
    trim_windows = {_video_trim_frames(video) for video in
                    (source_video, combined_mask_video, genuine_mask_video)}
    if len(trim_windows) != 1:
        raise ValueError("Source, combined mask and genuine mask must use the same active VIDEO trim.")
    source_raster = _positive_raster(
        (clip_details.get("width"), clip_details.get("height")), multiple32=True)

    source_rgb = _decode_exact(source_video, window.input_start, window.input_end,
                               "rgb24", source_raster)
    combined_size = _video_raster(combined_mask_video)
    genuine_size = _video_raster(genuine_mask_video)
    if combined_size != genuine_size:
        raise ValueError("The combined and genuine performer masks use different rasters.")
    recorded_mask_size = clip_details.get("text_regions_size")
    if recorded_mask_size is not None:
        if _positive_raster(tuple(recorded_mask_size), multiple32=False) != combined_size:
            raise ValueError("The review mask raster changed after text-region detection.")

    # Decode only this bounded interval; the whole-shot union is streamed below.
    combined_gray = _decode_exact(combined_mask_video, window.input_start,
                                  window.input_end, "gray", combined_size)
    genuine_frames, shot_union = _decode_genuine_window_and_union(
        genuine_mask_video, window, genuine_size)
    record = _shot_text_record(clip_details, window, combined_size)

    source_frames = _pad_context(_stack_rgb(source_rgb), window.valid_frames)
    combined_mask = _pad_context(_stack_masks(combined_gray), window.valid_frames)
    genuine_mask = _pad_context(_stack_masks(genuine_frames), window.valid_frames)
    union_tensor = torch.from_numpy(shot_union.copy()).to(torch.float32).unsqueeze(0)
    details = copy.deepcopy(clip_details)
    details["width"], details["height"] = source_raster
    details["text_regions"] = [dict(region) for region in record["regions"]]
    details.setdefault("text_regions_size", [combined_size[0], combined_size[1]])
    details["h3_window"] = {
        "index": window.index,
        "shot_index": window.shot_index,
        "shot_interval": [window.shot_start, window.shot_end],
        "input_interval": [window.input_start, window.input_end],
        "owned_interval": [window.owned_start, window.owned_end],
        "valid_frames": window.valid_frames,
        "context_frames": H3_CONTEXT_FRAMES,
        "overlap_frames": window.overlap_frames,
        "padded_frames": window.padded_frames,
    }
    return H3WindowData(
        source_frames=source_frames,
        combined_mask=combined_mask,
        genuine_mask=genuine_mask,
        whole_shot_genuine_union=union_tensor,
        audio=slice_audio_window(full_audio_timeline, window, total_frames),
        clip_details=details,
        window=window,
    )


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest.")
    return value


def _window_record(window: H3Window) -> dict:
    return {
        "index": window.index,
        "shot_index": window.shot_index,
        "shot_start": window.shot_start,
        "shot_end": window.shot_end,
        "input_start": window.input_start,
        "valid_frames": window.valid_frames,
        "owned_start": window.owned_start,
        "owned_end": window.owned_end,
        "overlap_frames": window.overlap_frames,
        "padded_frames": window.padded_frames,
        "carry_video_tokens": window.carry_video_tokens,
    }


def _tensor_sha256(tensor: torch.Tensor) -> str:
    if tensor.device.type != "cpu" or tensor.layout != torch.strided:
        raise ValueError("Continuation tensors must be dense CPU tensors.")
    raw = tensor.detach().contiguous().view(torch.uint8).numpy().tobytes()
    return hashlib.sha256(raw).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _is_link_or_junction(path: Path) -> bool:
    junction_check = getattr(path, "is_junction", None)
    return path.is_symlink() or (callable(junction_check) and junction_check())


def _state_root() -> Path:
    try:
        import folder_paths
        output = Path(folder_paths.get_output_directory()).resolve()
    except Exception as exc:
        raise RuntimeError("The configured ComfyUI output directory is unavailable.") from exc
    genj_directory = output / "genj"
    continuation_directory = genj_directory / "h3_continuation"
    if _is_link_or_junction(genj_directory) or _is_link_or_junction(continuation_directory):
        raise ValueError("The H3 continuation store cannot use redirected directories.")
    root = continuation_directory.resolve()
    if not root.is_relative_to(output):
        raise ValueError("The H3 continuation store must stay inside ComfyUI output.")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _state_directory(root: Path, generation_digest: str, window_index: int) -> Path:
    generation_digest = _digest(generation_digest, "generation digest")
    window_index = _int(window_index, "window index", 0)
    generation_path = root / generation_digest
    path = generation_path / f"window-{window_index:06d}"
    if _is_link_or_junction(generation_path) or _is_link_or_junction(path):
        raise ValueError("The H3 continuation key cannot use redirected directories.")
    path = path.resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("The H3 continuation key escaped its output store.")
    return path


def _payload_manifest(prefix: H3VideoPrefix, guide_frames: torch.Tensor,
                      previous_window: H3Window, raster: tuple[int, int],
                      generation_digest: str, model_digest: str) -> dict:
    width, height = raster
    return {
        "schema": STATE_SCHEMA,
        "generation_digest": generation_digest,
        "model_digest": model_digest,
        "context_frames": H3_CONTEXT_FRAMES,
        "prefix_frames": H3_PREFIX_FRAMES,
        "raster": [width, height],
        "endpoint_valid_frames": prefix.valid_frames,
        "endpoint_video_token_count": prefix.token_count,
        "previous_window": _window_record(previous_window),
        "prefix": {"shape": list(prefix.video_tokens.shape),
                   "dtype": str(prefix.video_tokens.dtype),
                   "sha256": _tensor_sha256(prefix.video_tokens)},
        "guide": {"shape": list(guide_frames.shape), "dtype": str(guide_frames.dtype),
                  "window_local_frame_range": [
                      previous_window.valid_frames - H3_PREFIX_FRAMES,
                      previous_window.valid_frames],
                  "global_clip_frame_range": [
                      previous_window.input_start + previous_window.valid_frames - H3_PREFIX_FRAMES,
                      previous_window.input_end],
                  "sha256": _tensor_sha256(guide_frames)},
    }


def _validate_generation_window(window: H3Window, raster: tuple[int, int]) -> None:
    _validate_window(window)
    _positive_raster(raster, multiple32=True)
    if window.carry_video_tokens != 2:
        raise ValueError("Only a nonterminal same-shot window can save continuation state.")


def _existing_state(directory: Path, expected_manifest: dict | None = None) -> H3ContinuationState:
    from safetensors import safe_open
    from safetensors.torch import load_file

    try:
        manifest_path = directory / "state.json"
        state_path = directory / "state.safetensors"
        if (_is_link_or_junction(directory) or not directory.is_dir()
                or _is_link_or_junction(manifest_path) or _is_link_or_junction(state_path)
                or not manifest_path.is_file() or not state_path.is_file()
                or manifest_path.stat().st_size > 1024 * 1024
                or state_path.stat().st_size > _MAX_STATE_BYTES):
            raise ValueError
        envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = envelope["manifest"]
        state_digest = envelope["state_sha256"]
        if not isinstance(manifest, dict) or not isinstance(state_digest, str):
            raise ValueError
        _digest(state_digest, "saved continuation digest")
        if (manifest.get("schema") != STATE_SCHEMA
                or _int(manifest.get("context_frames"), "saved context frame count", 1)
                != H3_CONTEXT_FRAMES
                or _int(manifest.get("prefix_frames"), "saved prefix frame count", 1)
                != H3_PREFIX_FRAMES):
            raise ValueError
        generation_digest = _digest(manifest.get("generation_digest"), "generation digest")
        model_digest = _digest(manifest.get("model_digest"), "model digest")
        raster_value = manifest.get("raster")
        if not isinstance(raster_value, list) or len(raster_value) != 2:
            raise ValueError
        raster = _positive_raster(tuple(raster_value), multiple32=True)
        endpoint = _int(manifest.get("endpoint_valid_frames"), "saved endpoint", H3_PREFIX_FRAMES)
        endpoint_count = _int(manifest.get("endpoint_video_token_count"), "saved endpoint token count", 1)
        from .h3_windows import h3_video_token_count
        if endpoint_count != h3_video_token_count(endpoint):
            raise ValueError
        if _file_sha256(state_path) != state_digest:
            raise ValueError
        with safe_open(str(state_path), framework="pt", device="cpu") as handle:
            metadata = handle.metadata() or {}
        if metadata.get("manifest") != _canonical_json(manifest):
            raise ValueError
        if expected_manifest is not None and manifest != expected_manifest:
            raise ValueError
        tensors = load_file(str(state_path), device="cpu")
        if set(tensors) != {"video_prefix", "guide_frames"}:
            raise ValueError
        prefix_tensor, guide = tensors["video_prefix"], tensors["guide_frames"]
        if (_tensor_sha256(prefix_tensor) != manifest["prefix"]["sha256"]
                or _tensor_sha256(guide) != manifest["guide"]["sha256"]
                or list(prefix_tensor.shape) != manifest["prefix"]["shape"]
                or str(prefix_tensor.dtype) != manifest["prefix"]["dtype"]
                or list(guide.shape) != manifest["guide"]["shape"]
                or str(guide.dtype) != manifest["guide"]["dtype"]):
            raise ValueError
        previous = H3Window(**manifest["previous_window"])
        _validate_generation_window(previous, raster)
        if (endpoint != previous.valid_frames
                or manifest["prefix"].get("shape") != list(prefix_tensor.shape)
                or manifest["guide"].get("window_local_frame_range") != [
                    previous.valid_frames - H3_PREFIX_FRAMES, previous.valid_frames]
                or manifest["guide"].get("global_clip_frame_range") != [
                    previous.input_start + previous.valid_frames - H3_PREFIX_FRAMES,
                    previous.input_end]):
            raise ValueError
        width, height = raster
        if (guide.shape != (H3_PREFIX_FRAMES, height, width, 3)
                or prefix_tensor.shape != (1, 24, 2, height // 16, width // 16)
                or prefix_tensor.device.type != "cpu" or guide.device.type != "cpu"
                or not bool(torch.isfinite(prefix_tensor).all())
                or not bool(torch.isfinite(guide).all())):
            raise ValueError
        prefix = H3VideoPrefix(prefix_tensor, endpoint, endpoint_count)
        return H3ContinuationState(prefix, guide, previous, (width, height),
                                   generation_digest, model_digest,
                                   state_digest)
    except Exception as exc:
        raise ValueError("The saved H3 continuation is missing, stale, corrupt or mismatched.") from exc


def _check_next_window(state: H3ContinuationState, next_window: H3Window,
                       generation_digest: str, model_digest: str,
                       raster: tuple[int, int]) -> None:
    _validate_window(next_window)
    previous = state.previous_window
    if (state.generation_digest != generation_digest or state.model_digest != model_digest
            or state.raster != raster or previous.index + 1 != next_window.index
            or previous.shot_index != next_window.shot_index
            or previous.shot_start != next_window.shot_start
            or previous.shot_end != next_window.shot_end
            or previous.owned_end != next_window.owned_start
            or next_window.overlap_frames != H3_PREFIX_FRAMES
            or next_window.input_start != previous.owned_end - H3_PREFIX_FRAMES
            or state.prefix.valid_frames != previous.valid_frames
            or state.prefix.token_count != 2 + 5 * ((previous.valid_frames - 5) // 17)):
        raise ValueError("The H3 continuation belongs to a different generation, raster, window or shot.")


def save_h3_continuation(sampled_latent: dict, generated_native_frames: torch.Tensor,
                         previous_window: H3Window, generation_digest: str,
                         model_digest: str) -> H3ContinuationState:
    """Atomically save an exact CPU prefix and native five-frame guide.

    ``generated_native_frames`` must be wired from the visible native H3
    ``VAEDecode`` output before any preview resize, crop or export conversion.
    """

    generation_digest = _digest(generation_digest, "generation digest")
    model_digest = _digest(model_digest, "model digest")
    if not isinstance(previous_window, H3Window):
        raise ValueError("Provide the preceding planned H3 window.")
    if (not isinstance(generated_native_frames, torch.Tensor)
            or generated_native_frames.layout != torch.strided
            or generated_native_frames.device.type != "cpu"
            or generated_native_frames.ndim != 4
            or generated_native_frames.shape[0] != H3_CONTEXT_FRAMES
            or generated_native_frames.shape[-1] != 3
            or not generated_native_frames.is_floating_point()
            or not bool(torch.isfinite(generated_native_frames).all())
            or bool((generated_native_frames < 0).any())
            or bool((generated_native_frames > 1).any())):
        raise ValueError("Save the full 124-frame native H3 decode as finite CPU IMAGE data.")
    height, width = int(generated_native_frames.shape[1]), int(generated_native_frames.shape[2])
    raster = _positive_raster((width, height), multiple32=True)
    _validate_generation_window(previous_window, raster)
    if previous_window.valid_frames < H3_PREFIX_FRAMES:
        raise ValueError("The generated H3 window is too short for a five-frame guide.")
    guide_bytes = (H3_PREFIX_FRAMES * height * width * 3
                   * generated_native_frames.element_size())
    if guide_bytes > _MAX_STATE_BYTES:
        raise ValueError("The native H3 guide exceeds the continuation state size limit.")
    prefix = extract_video_prefix(sampled_latent, previous_window.valid_frames)
    expected_video_shape = (1, 24, 2, height // 16, width // 16)
    if tuple(prefix.video_tokens.shape) != expected_video_shape:
        raise ValueError("The sampled H3 latent raster does not match its native decoded guide.")
    if guide_bytes + prefix.video_tokens.numel() * prefix.video_tokens.element_size() + 4096 > _MAX_STATE_BYTES:
        raise ValueError("The H3 continuation state exceeds the configured file size limit.")
    start = previous_window.valid_frames - H3_PREFIX_FRAMES
    guide = generated_native_frames[start:previous_window.valid_frames].detach().contiguous().clone()
    if guide.shape != (H3_PREFIX_FRAMES, height, width, 3):
        raise ValueError("The native H3 guide does not cover its five valid endpoint frames.")

    manifest = _payload_manifest(prefix, guide, previous_window, raster,
                                 generation_digest, model_digest)
    root = _state_root()
    destination = _state_directory(root, generation_digest, previous_window.index)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        existing = _existing_state(destination, manifest)
        return existing

    from safetensors.torch import save_file
    temporary = Path(tempfile.mkdtemp(prefix=".h3-window-", dir=str(destination.parent)))
    try:
        safe_path = temporary / "state.safetensors"
        save_file({"video_prefix": prefix.video_tokens.contiguous(),
                   "guide_frames": guide.contiguous()}, str(safe_path),
                  metadata={"manifest": _canonical_json(manifest)})
        envelope = {"manifest": manifest, "state_sha256": _file_sha256(safe_path)}
        (temporary / "state.json").write_text(
            json.dumps(envelope, sort_keys=True, indent=2, allow_nan=False), encoding="utf-8")
        try:
            os.rename(temporary, destination)
        except OSError:
            if not destination.exists():
                raise
            return _existing_state(destination, manifest)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return _existing_state(destination, manifest)


def load_h3_continuation(next_window: H3Window, generation_digest: str,
                         model_digest: str, raster: tuple[int, int]) -> H3ContinuationState:
    """Load only the previous adjacent window under the configured output root."""

    generation_digest = _digest(generation_digest, "generation digest")
    model_digest = _digest(model_digest, "model digest")
    raster = _positive_raster(raster, multiple32=True)
    _validate_window(next_window)
    if (next_window.index < 1 or next_window.overlap_frames != H3_PREFIX_FRAMES
            or next_window.input_start != next_window.owned_start - H3_PREFIX_FRAMES):
        raise ValueError("This H3 window has no valid same-shot continuation predecessor.")
    root = _state_root()
    directory = _state_directory(root, generation_digest, next_window.index - 1)
    state = _existing_state(directory)
    _check_next_window(state, next_window, generation_digest, model_digest, raster)
    return state


def apply_h3_continuation_state(latent: dict, state: H3ContinuationState
                                ) -> tuple[dict, torch.Tensor]:
    """Apply the prefix after background/audio masks, returning its IMAGE guide."""

    if not isinstance(state, H3ContinuationState):
        raise ValueError("Load a verified H3 continuation state first.")
    updated_latent = apply_video_prefix(latent, state.prefix)
    return updated_latent, state.guide_frames.clone()


class ZuraH3PrepareFullAudioTimeline:
    """Prepare one global CPU audio timeline before any H3 window is sliced."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "audio": ("AUDIO",),
            "total_frames": ("INT", {"default": 124, "min": 1, "max": 1000000}),
            "audio_start_frame": ("INT", {"default": 0, "min": 0, "max": 1000000}),
        }}

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("full_audio_timeline",)
    FUNCTION = "prepare"
    CATEGORY = "Zura/Artist Studio/H3 Windows"

    def prepare(self, audio, total_frames, audio_start_frame=0):
        return (prepare_full_audio_timeline(audio, total_frames, audio_start_frame),)


class ZuraH3WindowInputs:
    """Load one planned context directly from native VIDEO stream sources."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "source_video": ("VIDEO",),
            "combined_mask_video": ("VIDEO",),
            "genuine_mask_video": ("VIDEO",),
            "full_audio_timeline": ("AUDIO",),
            "clip_details": ("GENJ_CLIP",),
            "window_json": ("STRING", {"default": "{}", "multiline": True}),
        }}

    RETURN_TYPES = ("IMAGE", "MASK", "MASK", "MASK", "AUDIO", "GENJ_CLIP")
    RETURN_NAMES = ("source_frames", "combined_mask", "genuine_mask", "performer_guard",
                    "window_audio", "clip_details")
    FUNCTION = "load"
    CATEGORY = "Zura/Artist Studio/H3 Windows"

    def load(self, source_video, combined_mask_video, genuine_mask_video,
             full_audio_timeline, clip_details, window_json):
        window = _window_from_json(window_json)
        data = decode_h3_window_data(source_video, combined_mask_video, genuine_mask_video,
                                     full_audio_timeline, clip_details, window)
        return (data.source_frames, data.combined_mask, data.genuine_mask,
                data.whole_shot_genuine_union, data.audio, data.clip_details)


class ZuraSaveH3Continuation:
    """Persist the previous window's sampled prefix and decoded five-frame guide."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "sampled_latent": ("LATENT",),
            "generated_native_frames": ("IMAGE",),
            "window_json": ("STRING", {"default": "{}", "multiline": True}),
            "generation_digest": ("STRING", {"default": ""}),
            "model_digest": ("STRING", {"default": ""}),
        }}

    RETURN_TYPES = ("H3_CONTINUATION",)
    RETURN_NAMES = ("continuation_state",)
    FUNCTION = "save"
    CATEGORY = "Zura/Artist Studio/H3 Windows"
    OUTPUT_NODE = True

    def save(self, sampled_latent, generated_native_frames, window_json,
             generation_digest, model_digest):
        state = save_h3_continuation(sampled_latent, generated_native_frames,
                                     _window_from_json(window_json),
                                     generation_digest, model_digest)
        return {"ui": {"text": ["H3 continuation state saved for the next same-shot window."]},
                "result": (state,)}


class ZuraLoadH3Continuation:
    """Load the adjacent state and guide for use before reference encoding.

    Always re-execute so changed or corrupted on-disk provenance is validated
    even when ComfyUI reuses an otherwise identical graph prompt.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "next_window_json": ("STRING", {"default": "{}", "multiline": True}),
            "generation_digest": ("STRING", {"default": ""}),
            "model_digest": ("STRING", {"default": ""}),
            "width": ("INT", {"default": 704, "min": 32, "max": 8192, "step": 32}),
            "height": ("INT", {"default": 1280, "min": 32, "max": 8192, "step": 32}),
        }}

    RETURN_TYPES = ("H3_CONTINUATION", "IMAGE")
    RETURN_NAMES = ("continuation_state", "guide_frames")
    FUNCTION = "load"
    CATEGORY = "Zura/Artist Studio/H3 Windows"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # NaN is ComfyUI's documented-style cache-bypass sentinel: this tiny
        # loader must re-check the confined adjacent state on every execution.
        return float("nan")

    def load(self, next_window_json, generation_digest, model_digest, width, height):
        window = _window_from_json(next_window_json)
        state = load_h3_continuation(window, generation_digest, model_digest, (width, height))
        return state, state.guide_frames.clone()


class ZuraApplyH3Continuation:
    """Freeze two video tokens and expose the actual five-frame IMAGE guide."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "latent": ("LATENT",),
            "continuation_state": ("H3_CONTINUATION",),
        }}

    RETURN_TYPES = ("LATENT", "IMAGE")
    RETURN_NAMES = ("latent", "guide_frames")
    FUNCTION = "apply"
    CATEGORY = "Zura/Artist Studio/H3 Windows"

    def apply(self, latent, continuation_state):
        return apply_h3_continuation_state(latent, continuation_state)
