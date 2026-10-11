"""Safe, data-only persistence for native video LATENT dictionaries.

The nodes in this module do not load models or perform inference. They keep a
bounded CPU copy of the ``samples`` and optional ``noise_mask`` tensors so a
ComfyUI graph can separate native latent preparation from native sampling.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid

import folder_paths
import torch
from safetensors.torch import load as safe_load
from safetensors.torch import save as safe_save


_SCHEMA = "zura.video_latent_data"
_VERSION = "1"
_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_PAYLOAD_BYTES = 256 * 1024 * 1024
_MAX_FILE_OVERHEAD = 64 * 1024
_MAX_FILE_BYTES = _MAX_PAYLOAD_BYTES + _MAX_FILE_OVERHEAD
_MAX_HEADER_BYTES = _MAX_FILE_OVERHEAD - 8  # Safetensors has an 8-byte length prefix.
_FINITE_CHUNK_ELEMENTS = 1_000_000

_FLOAT_DTYPE_BYTES = {
    "F16": 2,
    "BF16": 2,
    "F32": 4,
    "F64": 8,
    "F8_E4M3": 1,
    "F8_E4M3FNUZ": 1,
    "F8_E5M2": 1,
    "F8_E5M2FNUZ": 1,
}


def _key(value: object) -> str:
    if not isinstance(value, str) or not _KEY_RE.fullmatch(value):
        raise ValueError("Cache key must be exactly 64 lowercase hexadecimal characters.")
    return value


def _expected_digest(value: object) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError("Optional cache digest must be 64 lowercase hexadecimal characters.")
    return value


def _cache_directory(*, create: bool) -> Path:
    """Resolve the private cache below ComfyUI output, checking each directory."""

    try:
        output = Path(folder_paths.get_output_directory()).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("ComfyUI's output folder is unavailable for the latent cache.") from exc

    current = output
    for part in ("zura", "latent_data"):
        candidate = current / part
        if not candidate.exists():
            if not create:
                raise FileNotFoundError("Video latent cache is missing. Rebuild it from the native preparation section.")
            try:
                candidate.mkdir()
            except FileExistsError:
                # Another process may have created this directory concurrently;
                # the resolved containment check below still applies.
                pass
            except OSError as exc:
                raise ValueError("Could not create Zura's video latent cache folder in ComfyUI output.") from exc
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("Zura's video latent cache folder could not be resolved safely.") from exc
        if not resolved.is_relative_to(output):
            raise ValueError("Zura's video latent cache folder must stay inside ComfyUI output.")
        if not resolved.is_dir():
            raise ValueError("Zura's video latent cache path is not a folder.")
        current = resolved
    return current


def _cache_path(cache_key: str, *, create_directory: bool = False) -> Path:
    key = _key(cache_key)
    directory = _cache_directory(create=create_directory)
    path = directory / f"{key}.safetensors"
    if path.is_symlink():
        raise ValueError("The video latent cache file cannot be a symbolic link.")
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError("The video latent cache filename could not be resolved safely.") from exc
    if resolved.parent != directory:
        raise ValueError("The video latent cache file must stay inside Zura's cache folder.")
    return path


def _payload_bytes(data: dict[str, torch.Tensor]) -> int:
    total = 0
    for tensor in data.values():
        total += tensor.numel() * tensor.element_size()
        if total > _MAX_PAYLOAD_BYTES:
            raise ValueError("Video latent data exceeds the 256 MiB cache limit.")
    return total


def _validate_shape(tensor: object, name: str) -> torch.Tensor:
    if not isinstance(tensor, torch.Tensor):
        raise ValueError(f"Video latent '{name}' must be a tensor.")
    if tensor.layout is not torch.strided:
        raise ValueError(f"Video latent '{name}' must use standard strided tensor storage.")
    if not tensor.is_floating_point():
        raise ValueError(f"Video latent '{name}' must use a floating-point dtype.")
    if tensor.ndim != 5 or any(int(size) <= 0 for size in tensor.shape):
        raise ValueError(f"Video latent '{name}' must have five non-empty dimensions.")
    dtype_name = _dtype_name(tensor.dtype)
    if dtype_name not in _FLOAT_DTYPE_BYTES:
        raise ValueError(f"Video latent '{name}' uses a floating-point dtype safetensors cannot store safely.")
    return tensor


def _dtype_name(dtype: torch.dtype) -> str:
    # Derive the safetensors spelling from torch's public dtype name, then map
    # the two compact float8 names used by safetensors.
    name = str(dtype).removeprefix("torch.")
    if name == "float16":
        return "F16"
    if name == "bfloat16":
        return "BF16"
    if name == "float32":
        return "F32"
    if name == "float64":
        return "F64"
    return {
        "float8_e4m3fn": "F8_E4M3",
        "float8_e4m3fnuz": "F8_E4M3FNUZ",
        "float8_e5m2": "F8_E5M2",
        "float8_e5m2fnuz": "F8_E5M2FNUZ",
    }.get(name, "")


def _tensor_chunks(tensor: torch.Tensor):
    axis = max(range(tensor.ndim), key=lambda i: tensor.shape[i])
    other_elements = math.prod(tensor.shape[:axis] + tensor.shape[axis + 1 :])
    width = max(1, _FINITE_CHUNK_ELEMENTS // max(1, other_elements))
    for start in range(0, tensor.shape[axis], width):
        yield tensor.narrow(axis, start, min(width, tensor.shape[axis] - start))


def _check_finite(tensor: torch.Tensor, name: str) -> None:
    for chunk in _tensor_chunks(tensor.detach()):
        checked = chunk
        try:
            finite = torch.isfinite(checked)
        except (NotImplementedError, RuntimeError):
            # Some float8 formats expose conversion but not isfinite directly.
            checked = checked.to(torch.float32)
            finite = torch.isfinite(checked)
        if not bool(finite.all().item()):
            raise ValueError(f"Video latent '{name}' contains NaN or infinite values.")


def _check_mask_range(mask: torch.Tensor) -> None:
    for chunk in _tensor_chunks(mask.detach()):
        checked = chunk
        if str(mask.dtype).startswith("torch.float8_"):
            checked = checked.to(torch.float32)
        if bool(((checked < 0) | (checked > 1)).any().item()):
            raise ValueError("Video latent 'noise_mask' values must stay between 0 and 1.")


def _validate_latent(data: object) -> dict[str, torch.Tensor]:
    if not isinstance(data, dict):
        raise ValueError("Connect one native video LATENT dictionary to the cache node.")
    allowed = {"samples", "noise_mask"}
    if set(data) - allowed:
        extra = ", ".join(sorted(str(name) for name in set(data) - allowed)[:4])
        raise ValueError(f"Video latent has unsupported metadata ({extra}). Keep only samples and optional noise_mask.")
    if "samples" not in data:
        raise ValueError("Video latent is missing its samples tensor.")

    samples = _validate_shape(data["samples"], "samples")
    mask = None
    if "noise_mask" in data:
        mask = _validate_shape(data["noise_mask"], "noise_mask")
        if any(mask.shape[axis] not in (1, samples.shape[axis]) for axis in range(5)):
            raise ValueError("Video latent 'noise_mask' must broadcast to the samples shape.")

    normalized = {"samples": samples}
    if mask is not None:
        normalized["noise_mask"] = mask
    _payload_bytes(normalized)

    _check_finite(samples, "samples")
    if mask is not None:
        _check_finite(mask, "noise_mask")
        _check_mask_range(mask)
    return normalized


def _snapshot_cpu(data: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    # Copy only after schema, dimensions, byte limit, finiteness, and mask
    # range have been checked. The copy preserves each floating dtype.
    return {
        name: tensor.detach().to(device="cpu", copy=True).contiguous()
        for name, tensor in data.items()
    }


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Video latent cache header contains a duplicate field.")
        result[key] = value
    return result


def _parse_header(raw: bytes, key: str) -> tuple[dict, int]:
    if len(raw) < 8 or len(raw) > _MAX_FILE_BYTES:
        raise ValueError("Video latent cache file is empty or exceeds the 256 MiB limit.")
    header_len = int.from_bytes(raw[:8], "little", signed=False)
    if header_len <= 0 or header_len > _MAX_HEADER_BYTES or 8 + header_len > len(raw):
        raise ValueError("Video latent cache header is truncated or larger than 64 KiB.")
    try:
        header = json.loads(raw[8 : 8 + header_len].rstrip(b" ").decode("utf-8"), object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("Video latent cache header is malformed.") from exc
    if not isinstance(header, dict):
        raise ValueError("Video latent cache header must be an object.")
    metadata = header.get("__metadata__")
    if metadata != {"cache_key": key, "schema": _SCHEMA, "version": _VERSION}:
        raise ValueError("Video latent cache belongs to another key or uses an unsupported version.")

    names = set(header) - {"__metadata__"}
    if names not in ({"samples"}, {"samples", "noise_mask"}):
        raise ValueError("Video latent cache must contain samples and at most one noise_mask tensor.")

    expected_bytes = 0
    ranges = []
    for name in names:
        info = header[name]
        if not isinstance(info, dict) or set(info) != {"dtype", "shape", "data_offsets"}:
            raise ValueError(f"Video latent cache entry '{name}' has an unsupported tensor schema.")
        dtype = info["dtype"]
        shape = info["shape"]
        offsets = info["data_offsets"]
        if dtype not in _FLOAT_DTYPE_BYTES or not isinstance(shape, list) or len(shape) != 5:
            raise ValueError(f"Video latent cache entry '{name}' must be a five-dimensional floating tensor.")
        if any(isinstance(size, bool) or not isinstance(size, int) or size <= 0 for size in shape):
            raise ValueError(f"Video latent cache entry '{name}' has invalid dimensions.")
        if not isinstance(offsets, list) or len(offsets) != 2 or any(
            isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 for offset in offsets
        ):
            raise ValueError(f"Video latent cache entry '{name}' has invalid byte offsets.")
        tensor_bytes = math.prod(shape) * _FLOAT_DTYPE_BYTES[dtype]
        if tensor_bytes > _MAX_PAYLOAD_BYTES:
            raise ValueError("Video latent data exceeds the 256 MiB cache limit.")
        if offsets[1] - offsets[0] != tensor_bytes:
            raise ValueError(f"Video latent cache entry '{name}' has an inconsistent byte count.")
        ranges.append((offsets[0], offsets[1]))
        expected_bytes += tensor_bytes

    if expected_bytes > _MAX_PAYLOAD_BYTES:
        raise ValueError("Video latent data exceeds the 256 MiB cache limit.")
    payload_start = 8 + header_len
    if payload_start + expected_bytes != len(raw):
        raise ValueError("Video latent cache payload length does not match its header.")
    cursor = 0
    for start, end in sorted(ranges):
        if start != cursor or end < start:
            raise ValueError("Video latent cache tensors overlap or leave gaps in the payload.")
        cursor = end
    if cursor != expected_bytes:
        raise ValueError("Video latent cache payload offsets are incomplete.")
    if "noise_mask" in names:
        sample_shape = header["samples"]["shape"]
        mask_shape = header["noise_mask"]["shape"]
        if any(mask_shape[i] not in (1, sample_shape[i]) for i in range(5)):
            raise ValueError("Video latent cache noise_mask cannot broadcast to samples.")
    return header, payload_start


def _read_stable_bytes(path: Path) -> bytes:
    try:
        if path.is_symlink():
            raise ValueError("The video latent cache file cannot be a symbolic link.")
        resolved = path.resolve(strict=True)
        if resolved.parent != path.parent.resolve(strict=True):
            raise ValueError("The video latent cache file must stay inside Zura's cache folder.")
        with resolved.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if before.st_size <= 0 or before.st_size > _MAX_FILE_BYTES:
                raise ValueError("Video latent cache file is empty or exceeds the 256 MiB limit.")
            raw = stream.read(_MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(raw) != before.st_size or len(raw) > _MAX_FILE_BYTES:
            raise ValueError("Video latent cache file changed size while it was being read.")
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ):
            raise ValueError("Video latent cache file changed while it was being read. Try again.")
        return raw
    except FileNotFoundError as exc:
        raise FileNotFoundError("Video latent cache is missing. Rebuild it from the native preparation section.") from exc
    except OSError as exc:
        raise ValueError("Could not safely read the video latent cache file.") from exc


def _release_owned_file(path: Path, identity: tuple[int, int] | None) -> None:
    if identity is None:
        return
    try:
        info = path.lstat()
        if not path.is_symlink() and (info.st_dev, info.st_ino) == identity:
            path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        # Keep an unexpected replacement rather than deleting a file we do
        # not own. A stale lock then produces a clear error on the next save.
        pass


def _save_atomic(path: Path, key: str, raw: bytes, expected: dict[str, torch.Tensor]) -> str:
    directory = path.parent
    lock = directory / f".{key}.lock"
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("This video latent cache is being written by another queue. Retry after it finishes.") from exc
    except OSError as exc:
        raise ValueError("Could not lock Zura's video latent cache for writing.") from exc

    lock_identity = None
    temp_path = None
    temp_identity = None
    try:
        lock_stat = os.fstat(lock_fd)
        lock_identity = (lock_stat.st_dev, lock_stat.st_ino)
        with os.fdopen(lock_fd, "w", encoding="ascii", closefd=False) as stream:
            stream.write(f"{os.getpid()} {uuid.uuid4().hex}\n")
            stream.flush()
            os.fsync(stream.fileno())

        if path.is_symlink():
            raise ValueError("The video latent cache file cannot be a symbolic link.")
        if path.exists():
            existing = _read_stable_bytes(path)
            if existing == raw:
                return hashlib.sha256(existing).hexdigest()
            if _same_cache_content(existing, key, expected):
                return hashlib.sha256(existing).hexdigest()
            raise ValueError("This cache key already contains different video latent data. Use a new cache key.")

        fd, temp_name = tempfile.mkstemp(prefix=f".{key}.{uuid.uuid4().hex}.", suffix=".tmp", dir=directory)
        temp_path = Path(temp_name)
        temp_stat = os.fstat(fd)
        temp_identity = (temp_stat.st_dev, temp_stat.st_ino)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

        try:
            # A hard link publishes the complete temporary file atomically and
            # fails if any file already owns the cache key; it never overwrites.
            os.link(temp_path, path)
        except FileExistsError:
            existing = _read_stable_bytes(path)
            if existing != raw and not _same_cache_content(existing, key, expected):
                raise ValueError("This cache key already contains different video latent data. Use a new cache key.")
            if existing != raw:
                return hashlib.sha256(existing).hexdigest()
        except OSError as exc:
            raise ValueError("Could not publish the video latent cache atomically.") from exc
        return hashlib.sha256(raw).hexdigest()
    finally:
        if temp_path is not None:
            _release_owned_file(temp_path, temp_identity)
        try:
            os.close(lock_fd)
        except OSError:
            pass
        _release_owned_file(lock, lock_identity)


def _same_cache_content(existing: bytes, key: str, expected: dict[str, torch.Tensor]) -> bool:
    """Compare schema and exact tensor bit patterns, ignoring header key order."""

    try:
        _parse_header(existing, key)
        actual = _validate_latent(safe_load(existing))
    except Exception:
        return False
    if set(actual) != set(expected):
        return False
    for name, tensor in expected.items():
        other = actual[name]
        if tensor.dtype != other.dtype or tuple(tensor.shape) != tuple(other.shape):
            return False
        left = tensor.detach().to(device="cpu").contiguous().view(torch.uint8)
        right = other.detach().to(device="cpu").contiguous().view(torch.uint8)
        if not torch.equal(left, right):
            return False
    return True


class ZuraSaveVideoLatentData:
    """Save native video latent tensors for a later native sampler section."""

    CATEGORY = "Zura/Artist Studio/Data"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("cache_key", "cache_digest")
    FUNCTION = "save"
    OUTPUT_NODE = True
    DESCRIPTION = "Safely caches the prepared video latent on disk so another native graph section can sample it later. No models run here."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": ("LATENT",),
                "cache_key": ("STRING", {"default": "", "multiline": False}),
            }
        }

    def save(self, samples, cache_key):
        key = _key(cache_key)
        data = _validate_latent(samples)
        cpu_data = _snapshot_cpu(data)
        metadata = {"cache_key": key, "schema": _SCHEMA, "version": _VERSION}
        raw = safe_save(cpu_data, metadata=metadata)
        if len(raw) > _MAX_FILE_BYTES:
            raise ValueError("Serialized video latent cache exceeds the 256 MiB plus 64 KiB limit.")
        path = _cache_path(key, create_directory=True)
        digest = _save_atomic(path, key, raw, cpu_data)
        return (key, digest)


class ZuraLoadVideoLatentData:
    """Load a verified native video latent dictionary on CPU."""

    CATEGORY = "Zura/Artist Studio/Data"
    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("samples",)
    FUNCTION = "load"
    OUTPUT_NODE = False
    DESCRIPTION = "Loads the prepared video latent on CPU. Connect it to the native sampler or VAE decode section."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "cache_key": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": {
                "cache_digest": ("STRING", {"default": "", "multiline": False}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, cache_key, cache_digest=""):
        try:
            key = _key(cache_key)
            _expected_digest(cache_digest)
            raw = _read_stable_bytes(_cache_path(key))
            return hashlib.sha256(raw).hexdigest()
        except (OSError, ValueError, RuntimeError):
            return float("nan")

    def load(self, cache_key, cache_digest=""):
        key = _key(cache_key)
        expected = _expected_digest(cache_digest)
        raw = _read_stable_bytes(_cache_path(key))
        digest = hashlib.sha256(raw).hexdigest()
        if expected and digest != expected:
            raise ValueError("Video latent cache digest does not match. Rebuild it from the native preparation section.")
        _parse_header(raw, key)
        try:
            data = safe_load(raw)
        except Exception as exc:
            raise ValueError("Video latent cache is damaged. Rebuild it from the native preparation section.") from exc
        validated = _validate_latent(data)
        # The safetensors parser returns CPU tensors. Keep this explicit in the
        # node contract, even when a future implementation changes loaders.
        result = {name: tensor.to(device="cpu") for name, tensor in validated.items()}
        return (result,)


NODE_CLASS_MAPPINGS = {
    "ZuraSaveVideoLatentData": ZuraSaveVideoLatentData,
    "ZuraLoadVideoLatentData": ZuraLoadVideoLatentData,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ZuraSaveVideoLatentData": "Zura Save Video Latent Data",
    "ZuraLoadVideoLatentData": "Zura Load Video Latent Data",
}
