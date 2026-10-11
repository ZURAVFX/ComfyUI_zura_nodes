"""Bounded equality checks delegated by the existing Wan provenance guard.

No manifest, review, seed, opening-image, source or soundtrack provenance gate
is replaced here. The root guard must retain those checks around these helpers.
"""
from __future__ import annotations

import math
import torch

from .bounded_video_audio import (audio_signature, decode_selected_audio, file_digest,
                                  identity, inspect_video, iter_native_frames, verify_file)
from .wan_preparation_windows import WindowArray, TENSOR_NAMES, _plain


def validate_window_footage(footage, interrupt=lambda: None):
    """Bind the actual connected arrays to their verified preparation reader."""
    if not isinstance(footage, dict):
        raise ValueError("Connect verified bounded Wan preparation.")
    values = [footage.get(name) for name in TENSOR_NAMES[:-1]]
    if not all(isinstance(value, WindowArray) for value in values):
        raise ValueError("Connect exact read-only Wan preparation windows.")
    reader = values[0]._reader
    for name, value in zip(TENSOR_NAMES[:-1], values):
        if value._reader is not reader or reader.arrays.get(name) is not value:
            raise ValueError("The connected conditioning belongs to different preparation caches.")
    if footage.get("streaming_preparation") != reader.provenance:
        raise ValueError("The connected preparation receipt differs from its actual windows.")
    reader.assert_renderable()
    interrupt()
    reader.verify()
    # Compare immutable approved cache metadata, not shallow dict aliases that
    # a connected graph can mutate after the loader returned its footage.
    from torch._subclasses.fake_tensor import FakeTensorMode
    members = reader._members()
    with FakeTensorMode():
        saved = torch.load(reader.path, weights_only=True, mmap=False, map_location="cpu")
    metadata = _plain({key: value for key, value in saved["footage"].items() if key not in TENSOR_NAMES[:-1]})
    if set(footage) != set(metadata) | set(TENSOR_NAMES[:-1]) | {"streaming_preparation"}:
        raise ValueError("The connected footage has missing or unexpected preparation metadata.")
    for name in metadata:
        if footage[name] != metadata[name]:
            raise ValueError("The connected preparation metadata changed after validation.")
    for name, value in zip(TENSOR_NAMES[:-1], values):
        proof = reader._layout(saved["footage"][name], members)
        if (value.name != name or value._layout != proof or value.shape != proof.shape or
                value.ndim != len(proof.shape)):
            raise ValueError("The connected preparation storage view changed after validation.")
    del saved
    return reader


def verify_selected_media(footage, selected_video, expected_source, expected_audio,
                          interrupt=lambda: None, window_frames=4):
    """Verify native selected frame/audio equality while holding at most a window.

    Return the original timeline and audio signature for root assertions. Any
    mismatch raises before inference; source and preparation bytes are rehashed
    after comparison so restored-mtime mutations cannot silently pass.
    """
    if type(window_frames) is not int or not 1 <= window_frames <= 8:
        raise ValueError("Speech-source comparison requires a small bounded frame window.")
    reader = validate_window_footage(footage, interrupt)
    info = inspect_video(selected_video, interrupt)
    expected_duration = float(expected_source["duration"])
    if (info.fps != expected_source["fps"] or info.frames != expected_source["frames"] or
            not math.isfinite(expected_duration) or abs(float(info.duration) - expected_duration) > 1e-9 or
            footage["video_info"].get("fps") != expected_source["fps"] or
            len(footage["frames"]) != info.frames or
            footage["frames"].shape[1:3] != (info.height, info.width)):
        raise ValueError("The actual selected video no longer matches the facial-performance timeline.")
    stamp, digest = identity(info.path), file_digest(info.path, interrupt)
    size = min(window_frames, reader.max_window_frames)
    decoded = []
    checked = 0
    for index, frame in iter_native_frames(selected_video, info, interrupt):
        decoded.append(frame)
        if len(decoded) == size or index + 1 == info.frames:
            actual = torch.stack(decoded)
            expected = footage["frames"][checked:checked + len(decoded)]
            if not torch.equal(expected, actual):
                raise ValueError("The actual selected frames differ from the prepared motion.")
            checked += len(decoded)
            decoded.clear()
            del actual, expected
    if checked != info.frames:
        raise ValueError("The selected video frame comparison did not cover the complete timeline.")
    audio = decode_selected_audio(selected_video, info, interrupt)
    if audio is None or audio_signature(audio) != expected_audio:
        raise ValueError("The selected audio or its start time changed after the facial performance was created.")
    actual_signature = audio_signature(audio)
    del audio
    reader.verify()
    verify_file(info.path, stamp, digest, interrupt)
    return {"frames": checked, "fps": float(info.fps), "duration": float(info.duration),
            "selected_audio": actual_signature, "selected_video_sha": digest,
            "comparison_window_frames": size}
