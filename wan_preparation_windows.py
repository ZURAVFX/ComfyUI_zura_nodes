"""Exact read-only windows from native Wan preparation ZIP caches.

Metadata uses Torch's weights-only FakeTensor loader, never its full-file
copy-on-write mmap. Each IMAGE/MASK slice opens only its storage byte span
read-only, makes a bounded writable FP32 copy, and immediately unmaps it.
This module does not sample, preprocess poses, or change approved pixels.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import mmap
from pathlib import Path
import re
import struct
import sys
import zipfile

import numpy as np
import torch

TENSOR_NAMES = ("frames", "character_mask", "pose_video", "face_video", "reference")
DEFAULT_MAX_WINDOW_BYTES = 1024 ** 3
MAX_METADATA_BYTES = 1024 ** 2


def _sha(path, interrupt):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            interrupt()
            digest.update(block)
    return digest.hexdigest()


def _stamp(path):
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _plain(value, depth=0):
    """Preserve finite, JSON-like metadata; reject hidden tensor payloads."""
    if depth > 12:
        raise ValueError("Wan preparation metadata is too deeply nested.")
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) in (list, tuple) and len(value) <= 4096:
        return type(value)(_plain(item, depth + 1) for item in value)
    if type(value) is dict and len(value) <= 4096 and all(type(key) is str for key in value):
        return {key: _plain(item, depth + 1) for key, item in value.items()}
    raise ValueError("Wan preparation has unsupported metadata or hidden tensors.")


@dataclass(frozen=True)
class TensorLayout:
    shape: tuple[int, ...]
    stride: tuple[int, ...]
    member_offset: int
    member_bytes: int
    storage_offset: int


@dataclass(frozen=True)
class MaskValidation:
    strict: bool
    nonempty: bool


class WindowArray:
    """Shape-only handle. Only bounded first-axis slices become tensors."""
    def __init__(self, reader, name, layout):
        self._reader, self.name, self._layout = reader, name, layout
        self.shape, self.ndim = layout.shape, len(layout.shape)

    def __len__(self):
        return self.shape[0]

    def __getitem__(self, index):
        squeeze = False
        if type(index) is int:
            if index < 0:
                index += len(self)
            if not 0 <= index < len(self):
                raise IndexError("Wan frame index is outside the prepared timeline.")
            start, stop, squeeze = index, index + 1, True
        elif isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            if step != 1:
                raise ValueError("Wan preparation supports contiguous frame windows only.")
        else:
            raise ValueError("Read Wan preparation with a bounded frame slice.")
        result = self._reader._read(self._layout, start, stop)
        return result[0] if squeeze else result


class WanPreparationWindows:
    """A verified CPU preparation reader holding metadata, never full tensors."""
    def __init__(self, path, cache_key, output_root, *, max_window_frames=81,
                 max_window_bytes=DEFAULT_MAX_WINDOW_BYTES, expected_sha256=None, interrupt=None,
                 require_nonempty_mask=True):
        if type(require_nonempty_mask) is not bool:
            raise ValueError("Wan preparation mask policy must be explicit.")
        self.require_nonempty_mask = require_nonempty_mask
        if not isinstance(cache_key, str) or not re.fullmatch(r"[a-f0-9]{64}", cache_key):
            raise ValueError("Invalid Wan preparation cache key.")
        if type(max_window_frames) is not int or not 1 <= max_window_frames <= 409:
            raise ValueError("Wan preparation window bound must be between 1 and 409 frames.")
        if type(max_window_bytes) is not int or max_window_bytes < 4:
            raise ValueError("Wan preparation requires a positive byte bound.")
        if expected_sha256 is not None and (not isinstance(expected_sha256, str) or
                not re.fullmatch(r"[a-f0-9]{64}", expected_sha256)):
            raise ValueError("Invalid expected Wan preparation digest.")
        self.root = Path(output_root).resolve(strict=True)
        self.path = Path(path).resolve(strict=True)
        if not self.path.is_relative_to(self.root) or self.path.name != cache_key + ".pt":
            raise ValueError("Wan preparation leaves its approved output cache.")
        self._identity = _stamp(self.path)
        self.interrupt = interrupt or (lambda: None)
        self.max_window_frames, self.max_window_bytes = max_window_frames, max_window_bytes
        self.stats = {"reads": 0, "maximum_copy_bytes": 0, "maximum_map_bytes": 0}
        self.sha256 = _sha(self.path, self.interrupt)
        if expected_sha256 is not None and expected_sha256 != self.sha256:
            raise ValueError("Wan preparation digest differs from its approved cache.")
        members = self._members()
        # This verified native metadata path does not read tensor storage or
        # request a full-file mmap. Unsupported Torch versions fail closed.
        try:
            from torch._subclasses.fake_tensor import FakeTensorMode
            with FakeTensorMode():
                data = torch.load(self.path, map_location="cpu", weights_only=True, mmap=False)
        except Exception as error:
            raise ValueError("This Wan cache does not support safe metadata-only loading.") from error
        if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
            raise ValueError("Prepare this Wan shot again: unsupported cache version.")
        if set(data) != {"version", "footage", "reference"} or not isinstance(data["footage"], dict):
            raise ValueError("Wan preparation has an unsupported cache payload.")
        raw = data["footage"]
        if not all(name in raw for name in TENSOR_NAMES[:-1]):
            raise ValueError("Wan preparation is missing native conditioning.")
        self.metadata = _plain({name: value for name, value in raw.items() if name not in TENSOR_NAMES[:-1]})
        if len(json.dumps(self.metadata)) > MAX_METADATA_BYTES:
            raise ValueError("Wan preparation metadata is too large.")
        if (not isinstance(self.metadata.get("video_info"), dict) or
                self.metadata["video_info"].get("fps") != 24 or self.metadata.get("keep_audio") is not False or
                self.metadata.get("replacement_area") not in ("Whole character", "Whole head")):
            raise ValueError("Wan streaming cache must have a reviewed 24-fps video-only timeline and scope.")
        speech = self.metadata.get("speech_provenance")
        if speech is not None and (not isinstance(speech, dict) or set(speech) != {"guide_key", "guide_sha"} or
                not all(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) for value in speech.values())):
            raise ValueError("Wan preparation speech provenance is invalid.")
        self.arrays = {}
        for name in TENSOR_NAMES:
            tensor = data["reference"] if name == "reference" else raw[name]
            layout = self._layout(tensor, members)
            self.arrays[name] = WindowArray(self, name, layout)
        self._validate_shapes()
        self._validate_pixels()
        self.verify()
        self.provenance = {"version": 1, "cache_key": cache_key, "path": str(self.path),
            "sha256": self.sha256, "size": self._identity[2], "mtime_ns": self._identity[3],
            "storage": "torch_zip_readonly_windows_float32", "frames": len(self.arrays["frames"]),
            "fps": 24, "max_window_frames": max_window_frames, "max_window_bytes": max_window_bytes,
            "file_id": list(self._identity[:2])}

    def _members(self):
        result = {}
        try:
            with zipfile.ZipFile(self.path) as archive, self.path.open("rb") as handle:
                entries = archive.infolist()
                names = [entry.filename for entry in entries]
                if len(entries) > 1024 or len(set(names)) != len(names):
                    raise ValueError("Wan ZIP cache has duplicate or excessive members.")
                prefixes = {name.split("/")[0] for name in names}
                if len(prefixes) != 1:
                    raise ValueError("Wan ZIP cache has inconsistent storage roots.")
                prefix = next(iter(prefixes))
                if (prefix in ("", ".", "..") or any(".." in Path(name).parts or "\\" in name for name in names)):
                    raise ValueError("Wan ZIP cache has unsupported member paths.")
                occupied = []
                for entry in entries:
                    if entry.compress_type != zipfile.ZIP_STORED or entry.flag_bits & 1:
                        raise ValueError("Wan streaming requires uncompressed, unencrypted ZIP members.")
                    if entry.file_size != entry.compress_size:
                        raise ValueError("Wan ZIP member size is inconsistent.")
                    handle.seek(entry.header_offset)
                    local = handle.read(30)
                    if len(local) != 30:
                        raise ValueError("Wan ZIP member header is truncated.")
                    header = struct.unpack("<IHHHHHIIIHH", local)
                    if header[0] != 0x04034B50 or header[3] != zipfile.ZIP_STORED or header[2] & 1:
                        raise ValueError("Wan ZIP member header is unsupported.")
                    offset = entry.header_offset + 30 + header[-2] + header[-1]
                    local_name = handle.read(header[-2]).decode("utf-8")
                    if local_name != entry.filename or offset + entry.file_size > archive.start_dir:
                        raise ValueError("Wan ZIP member does not match its directory or file bounds.")
                    occupied.append((entry.header_offset, offset + entry.file_size))
                    if "/data/" in entry.filename:
                        if not re.fullmatch(re.escape(prefix) + r"/data/[0-9]+", entry.filename) or entry.file_size % 4:
                            raise ValueError("Wan ZIP tensor storage is unsupported.")
                        result[offset] = entry.file_size
                    elif entry.file_size > MAX_METADATA_BYTES:
                        raise ValueError("Wan ZIP metadata exceeds its bounded size.")
                if prefix + "/data.pkl" not in names or prefix + "/byteorder" not in names:
                    raise ValueError("Wan ZIP cache lacks native metadata or byte order.")
                if archive.read(prefix + "/byteorder") != b"little" or sys.byteorder != "little":
                    raise ValueError("Wan streaming requires native little-endian float32 storage.")
                ranges = sorted((offset, offset + length) for offset, length in result.items())
                occupied.sort()
                if (any(a[1] > b[0] for a, b in zip(ranges, ranges[1:])) or
                        any(a[1] > b[0] for a, b in zip(occupied, occupied[1:]))):
                    raise ValueError("Wan ZIP tensor storage overlaps.")
        except (OSError, zipfile.BadZipFile, UnicodeDecodeError, struct.error) as error:
            raise ValueError("Wan preparation is not a supported native torch ZIP cache.") from error
        return result

    @staticmethod
    def _layout(tensor, members):
        if (not isinstance(tensor, torch.Tensor) or tensor.dtype != torch.float32 or
                tensor.layout != torch.strided or str(getattr(tensor, "fake_device", "")) != "cpu"):
            raise ValueError("Wan conditioning must use exact CPU float32 strided tensors.")
        shape, stride = tuple(tensor.shape), tuple(tensor.stride())
        if not shape or any(type(value) is not int or value < 1 for value in shape) or any(value < 0 for value in stride):
            raise ValueError("Wan tensor layout is invalid.")
        storage = tensor.untyped_storage()
        offset = getattr(storage, "_checkpoint_offset", None)
        storage_offset = tensor.storage_offset()
        if type(offset) is not int or offset not in members or storage_offset < 0:
            raise ValueError("Wan tensor lacks a verified uncompressed storage offset.")
        length = members[offset]
        end = 4 * (storage_offset + sum((size - 1) * step for size, step in zip(shape, stride)) + 1)
        # FakeTensorMode's synthetic storage nbytes is not the checkpoint's
        # byte length (Torch 2.9 can multiply it by the element width again).
        # The independently verified ZIP member bounds are authoritative.
        if end > length:
            raise ValueError("Wan tensor view exceeds its native storage member.")
        return TensorLayout(shape, stride, offset, length, storage_offset)

    def _validate_shapes(self):
        frames = self.arrays["frames"]
        if frames.ndim != 4 or frames.shape[-1] != 3:
            raise ValueError("Wan source must contain RGB frames.")
        if self.arrays["character_mask"].shape != frames.shape[:3]:
            raise ValueError("Wan mask must cover the complete source raster and timeline.")
        for name in ("pose_video", "face_video", "reference"):
            value = self.arrays[name]
            if value.ndim != 4 or value.shape[-1] != 3 or len(value) != (1 if name == "reference" else len(frames)):
                raise ValueError("Wan native conditioning does not cover the source timeline.")

    def _validate_pixels(self):
        mask_seen = False
        for name, value in self.arrays.items():
            pixels = math.prod(value.shape[1:])
            stride = max(1, min(4, self.max_window_frames, 4_000_000 // pixels))
            for start in range(0, len(value), stride):
                self.interrupt()
                block = value[start:min(start + stride, len(value))]
                if not torch.isfinite(block).all() or block.min() < 0 or block.max() > 1:
                    raise ValueError("Wan conditioning contains invalid pixels outside [0,1].")
                if name == "character_mask" and (block > .5).any():
                    mask_seen = True
                del block
        if not mask_seen and self.require_nonempty_mask:
            raise ValueError("Wan streaming requires a non-empty approved performer mask.")
        self._mask_validation = MaskValidation(self.require_nonempty_mask, mask_seen)

    def assert_renderable(self):
        if self._mask_validation != MaskValidation(True, True):
            raise ValueError("Preparation parts must be merged and fully reviewed before rendering.")

    def _check_identity(self):
        resolved = self.path.resolve(strict=True)
        if not resolved.is_relative_to(self.root) or resolved != self.path or _stamp(resolved) != self._identity:
            raise ValueError("Wan preparation file identity changed after review.")

    def verify(self):
        self._check_identity()
        if _sha(self.path, self.interrupt) != self.sha256:
            raise ValueError("Wan preparation bytes changed after review.")
        self._check_identity()

    def _read(self, layout, start, stop):
        count = stop - start
        if start < 0 or stop > layout.shape[0] or count < 1 or count > self.max_window_frames:
            raise ValueError("Read only a non-empty bounded Wan frame window.")
        shape = (count,) + layout.shape[1:]
        copy_bytes = math.prod(shape) * 4
        span_bytes = 4 * (sum((size - 1) * step for size, step in zip(shape, layout.stride)) + 1)
        offset = layout.member_offset + 4 * (layout.storage_offset + start * layout.stride[0])
        # Windows rounds the mapping start down to allocation granularity.
        # Include that small prefix in the actual mapped-view byte budget.
        map_bytes = span_bytes + offset % mmap.ALLOCATIONGRANULARITY
        if max(copy_bytes, map_bytes) > self.max_window_bytes:
            raise ValueError("Wan window exceeds its bounded storage budget.")
        self.interrupt()
        self._check_identity()
        mapping = np.memmap(self.path, mode="r", dtype="<f4", offset=offset, shape=(span_bytes // 4,))
        try:
            view = np.ndarray(shape=shape, dtype="<f4", buffer=mapping,
                              strides=tuple(step * 4 for step in layout.stride))
            # Only this bounded copy becomes writable or visible to Torch.
            copied = np.array(view, dtype=np.float32, copy=True, order="C")
            del view
        finally:
            mapping._mmap.close()
        self._check_identity()
        self.stats["reads"] += 1
        self.stats["maximum_copy_bytes"] = max(self.stats["maximum_copy_bytes"], copy_bytes)
        self.stats["maximum_map_bytes"] = max(self.stats["maximum_map_bytes"], map_bytes)
        return torch.from_numpy(copied)

    def footage(self):
        self.assert_renderable()
        result = dict(self.metadata)
        result.update({name: value for name, value in self.arrays.items() if name != "reference"})
        result["streaming_preparation"] = dict(self.provenance)
        return result


class ZuraWanLoadWindowPreparation:
    """Thin data adapter for visible native Wan sampling nodes."""
    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "load"
    RETURN_TYPES = ("ZURA_FOOTAGE", "IMAGE", "INT", "INT")
    RETURN_NAMES = ("footage", "character_view", "width", "height")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cache_key": ("STRING", {"default": ""})},
                "optional": {"max_window_frames": ("INT", {"default": 81, "min": 5, "max": 409})}}

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def load(self, cache_key, max_window_frames=81):
        import folder_paths
        root = Path(folder_paths.get_output_directory())
        path = root / "genj" / "wan_conditioning" / (cache_key + ".pt")
        def interrupt():
            from comfy.model_management import throw_exception_if_processing_interrupted
            throw_exception_if_processing_interrupted()
        reader = WanPreparationWindows(path, cache_key, root, max_window_frames=max_window_frames,
                                       interrupt=interrupt)
        frames = reader.arrays["frames"]
        return reader.footage(), reader.arrays["reference"][:1], int(frames.shape[2]), int(frames.shape[1])
