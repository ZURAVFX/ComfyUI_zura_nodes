"""Join reviewed FP32 preparation parts without assembling a full tensor.

Parts remain ordinary version-1 Torch caches. The delivered file uses the
same format, five contiguous CPU FloatStorage members, and bounded copies.
No inference, source preprocessing, or approved metadata is changed here.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import pickle
import re
import shutil
import uuid
import zipfile

import numpy as np
import torch

from .wan_preparation_windows import (
    MAX_METADATA_BYTES, TENSOR_NAMES, WanPreparationWindows, _plain, _sha, _stamp,
)


@dataclass(frozen=True)
class ShardSpec:
    """Identity approved by the preparation worker, before merge is invoked."""
    cache_key: str
    path: str | Path
    start: int
    count: int
    sha256: str
    size: int
    mtime_ns: int
    window_source_sha256: str | None = None
    reference_sha256: str | None = None
    footage_metadata_sha256: str | None = None
    render_cache_pin: dict | None = None


def _render_pin(value):
    if type(value) is not dict or set(value) != {"source","mask"}:
        raise ValueError("Wan part receipt lacks derived source/mask file pins.")
    for pin in value.values():
        if (type(pin) is not dict or set(pin) != {"path","sha256","size","mtime_ns"} or
                type(pin["path"]) is not str or not Path(pin["path"]).is_absolute() or
                type(pin["size"]) is not int or pin["size"] < 1 or
                type(pin["mtime_ns"]) is not int or pin["mtime_ns"] < 0):
            raise ValueError("Wan derived source/mask file pin is invalid.")
        _key(pin["sha256"])
    return _plain(value)


def _verify_render_files(value, root, total_frames, interrupt):
    from .wan_preparation_runtime import validate_render_cache_pin
    source = Path(value["source"]["path"])
    shot = source.parent.name if source.parent.parent.name == "reviews" else source.parent.parent.name
    if not re.fullmatch(r"shot_[a-f0-9]{16}",shot):
        raise ValueError("Wan derived cache does not belong to an approved review.")
    validate_render_cache_pin(value,root,shot,total_frames)
    for pin in value.values():
        path = _confined(pin["path"],root)
        before = _stamp(path)
        if _sha(path,interrupt) != pin["sha256"] or _stamp(path) != before:
            raise ValueError("Wan derived source/mask bytes changed after preparation.")


def _metadata_sha(metadata):
    return hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode("utf-8")).hexdigest()


def shards_from_receipts(receipts, cache_key, total_frames, metadata):
    """Validate worker receipts before constructing the explicit merge specs.

    Production callers use this for source/review/pose-carry provenance. The
    plain ShardSpec API also supports already verified internal fixtures.
    """
    _key(cache_key)
    if type(total_frames) is not int or total_frames < 1:
        raise ValueError("Wan receipts require an explicit positive full frame count.")
    meta_sha = _metadata_sha(_plain(metadata))
    specs, stable, carry = [], None, None
    for receipt in receipts:
        if (type(receipt) is not dict or receipt.get("schema") != "zura_wan_preparation_part_v1" or
                receipt.get("cache_key") != cache_key or type(receipt.get("total_frames")) is not int or
                receipt["total_frames"] != total_frames):
            raise ValueError("Wan part receipt does not describe the reviewed full cache.")
        source, review = receipt.get("source_pin"), receipt.get("review_pin")
        if (type(source) is not dict or set(source) != {"review_shot_id", "original_source_sha256", "window_source_sha256"} or
                type(review) is not dict or set(review) != {"manifest_sha256", "mask_sha256"} or
                not isinstance(source["review_shot_id"], str) or not source["review_shot_id"]):
            raise ValueError("Wan part receipt is missing its source or review pins.")
        for value in [source["original_source_sha256"], source["window_source_sha256"], *review.values(),
                      receipt.get("reference_sha256"), receipt.get("footage_metadata_sha256"),
                      receipt.get("carry_in_sha256"), receipt.get("carry_out_sha256")]:
            _key(value)
        if receipt["footage_metadata_sha256"] != meta_sha:
            raise ValueError("Wan part receipt metadata pin differs from the full timeline.")
        render = _render_pin(receipt.get("render_cache_pin"))
        source_path,mask_path = Path(render["source"]["path"]),Path(render["mask"]["path"])
        shot_id = source["review_shot_id"]
        if (not isinstance(shot_id,str) or not re.fullmatch(r"shot_[a-f0-9]{16}",shot_id) or
                source_path.name != "source.mp4" or mask_path.name != "mask.mp4" or source_path.parent != mask_path.parent or
                (source_path.parent.name != shot_id and source_path.parent.parent.name != shot_id)):
            raise ValueError("Wan part receipt derived pair differs from its approved review identity.")
        pins = (source["review_shot_id"], source["original_source_sha256"], review,
                receipt["reference_sha256"], receipt["footage_metadata_sha256"],render)
        if stable is not None and not _same(stable, pins):
            raise ValueError("Wan part receipts mix different approved source or review identities.")
        if carry is not None and carry != receipt["carry_in_sha256"]:
            raise ValueError("Wan part receipts have a discontinuous pose-carry chain.")
        if ((not specs and (receipt.get("carry_in_kind") != "none" or
                receipt["carry_in_sha256"] != hashlib.sha256(b"zura-wan-pose-carry-v1:none").hexdigest())) or
                (specs and receipt.get("carry_in_kind") != "body")):
            raise ValueError("Wan part receipts have an invalid initial or continued pose carry.")
        stable, carry = pins, receipt["carry_out_sha256"]
        try:
            specs.append(ShardSpec(**{name: receipt[name] for name in
                ("cache_key", "path", "start", "count", "sha256", "size", "mtime_ns")},
                window_source_sha256=source["window_source_sha256"],
                reference_sha256=receipt["reference_sha256"],
                footage_metadata_sha256=receipt["footage_metadata_sha256"],render_cache_pin=render))
        except KeyError as error:
            raise ValueError("Wan part receipt lacks its approved file identity.") from error
    if not specs:
        raise ValueError("Wan merge requires approved part receipts.")
    return specs


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("Invalid Wan preparation key or digest.")
    return value


def _same(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_same(left[k], right[k]) for k in left)
    if type(left) in (list, tuple):
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    return left == right


def _confined(path, root, *, exists=True):
    result = Path(path).resolve(strict=exists)
    if not result.is_relative_to(root):
        raise ValueError("Wan preparation merge leaves its approved output directory.")
    if exists and not result.is_file():
        raise ValueError("Wan preparation part must be a regular file.")
    return result


def _verify_part(spec, original, root, interrupt):
    current = _confined(spec.path, root)
    if current != original or _stamp(current)[2:] != (spec.size, spec.mtime_ns):
        raise ValueError("Wan preparation part identity changed after approval.")
    before = _stamp(current)
    if _sha(current, interrupt) != spec.sha256 or _stamp(current) != before:
        raise ValueError("Wan preparation part bytes changed after approval.")
    return before


class _StorageProxy:
    def __init__(self, key, count):
        self.key, self.count = key, count


class _TensorProxy:
    def __init__(self, key, shape):
        self.shape = tuple(shape)
        self.storage = _StorageProxy(key, math.prod(shape))
        stride, tail = [], 1
        for size in reversed(shape):
            stride.append(tail)
            tail *= size
        self.stride = tuple(reversed(stride))

    def __reduce_ex__(self, protocol):
        return torch._utils._rebuild_tensor_v2, (
            self.storage, 0, self.shape, self.stride, False, OrderedDict(),
        )


class _MetadataPickler(pickle.Pickler):
    def persistent_id(self, obj):
        if isinstance(obj, _StorageProxy):
            return "storage", torch.FloatStorage, str(obj.key), "cpu", obj.count
        return None


def _write_archive(path, shapes, metadata, blocks, interrupt):
    """Internal format writer; each yielded ndarray contains at most 4 frames."""
    payload = {"version": 1, "footage": dict(metadata), "reference": None}
    for index, name in enumerate(TENSOR_NAMES):
        proxy = _TensorProxy(index, shapes[name])
        if name == "reference":
            payload[name] = proxy
        else:
            payload["footage"][name] = proxy
    buffer = io.BytesIO()
    _MetadataPickler(buffer, protocol=2).dump(payload)
    if buffer.tell() > MAX_METADATA_BYTES:
        raise ValueError("Wan merge metadata exceeds its bounded size.")
    stats = {"maximum_copy_bytes": 0, "maximum_block_frames": 0, "storage_bytes": 0}
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        archive.writestr("archive/data.pkl", buffer.getvalue())
        archive.writestr("archive/byteorder", b"little")
        archive.writestr("archive/version", b"3\n")
        for index, name in enumerate(TENSOR_NAMES):
            wanted = shapes[name]
            rows = 0
            with archive.open(f"archive/data/{index}", "w", force_zip64=True) as member:
                for array in blocks(name):
                    interrupt()
                    if (not isinstance(array, np.ndarray) or array.dtype != np.dtype("float32") or
                            array.ndim != len(wanted) or array.shape[1:] != wanted[1:] or
                            not 1 <= array.shape[0] <= 4 or not array.flags.c_contiguous):
                        raise ValueError("Wan merge requires bounded contiguous FP32 frame blocks.")
                    if not np.isfinite(array).all() or array.min() < 0 or array.max() > 1:
                        raise ValueError("Wan merge conditioning contains invalid pixels.")
                    rows += array.shape[0]
                    if rows > wanted[0]:
                        raise ValueError("Wan merge storage exceeds its reviewed timeline.")
                    data = array.tobytes(order="C")
                    member.write(data)
                    stats["maximum_copy_bytes"] = max(stats["maximum_copy_bytes"], len(data))
                    stats["maximum_block_frames"] = max(stats["maximum_block_frames"], array.shape[0])
                    stats["storage_bytes"] += len(data)
                    del data, array
                if rows != wanted[0]:
                    raise ValueError("Wan merge storage does not cover its reviewed timeline.")
    with Path(path).open("r+b") as handle:
        os.fsync(handle.fileno())
    return stats


def merge_preparation(shards, output_root, cache_key, total_frames, metadata, *, interrupt=None):
    """Atomically deliver one normal cache from exact consecutive approved parts.

    Returns the verified final cache provenance plus merge statistics. Parts
    may contain empty masks; the merged timeline must contain a performer.
    Existing final caches are never overwritten. Paths and receipts are
    explicit, so directory order cannot silently alter the timeline.
    """
    interrupt = interrupt or (lambda: None)
    root = Path(output_root).resolve(strict=True)
    _key(cache_key)
    if type(total_frames) is not int or total_frames < 1:
        raise ValueError("Wan merge requires an explicit positive full frame count.")
    metadata = _plain(metadata)
    if type(metadata) is not dict or any(name in metadata for name in TENSOR_NAMES):
        raise ValueError("Supply only the exact non-tensor Wan footage metadata.")
    if len(json.dumps(metadata)) > MAX_METADATA_BYTES:
        raise ValueError("Wan merge metadata exceeds its bounded size.")
    specs = list(shards)
    if not specs or len(specs) > 4096:
        raise ValueError("Wan merge requires a bounded list of preparation parts.")
    expected_start = 0
    paths = []
    for spec in specs:
        if not isinstance(spec, ShardSpec):
            raise ValueError("Wan merge requires explicit approved ShardSpec receipts.")
        _key(spec.cache_key)
        _key(spec.sha256)
        for value in (spec.window_source_sha256, spec.reference_sha256, spec.footage_metadata_sha256):
            if value is not None:
                _key(value)
        if spec.footage_metadata_sha256 is not None and spec.footage_metadata_sha256 != _metadata_sha(metadata):
            raise ValueError("Wan part metadata digest differs from its approved timeline.")
        if (type(spec.start) is not int or type(spec.count) is not int or spec.start != expected_start or
                not 1 <= spec.count <= total_frames or type(spec.size) is not int or spec.size < 1 or
                type(spec.mtime_ns) is not int or spec.mtime_ns < 0):
            raise ValueError("Wan parts must have exact contiguous chronological coverage.")
        expected_start += spec.count
        paths.append(_confined(spec.path, root))
    if expected_start != total_frames or len(set(paths)) != len(paths):
        raise ValueError("Wan parts must cover the full timeline exactly once.")
    render_pin = specs[0].render_cache_pin
    if any(not _same(spec.render_cache_pin,render_pin) for spec in specs):
        raise ValueError("Wan parts mix different derived source/mask file identities.")
    if render_pin is not None:
        render_pin = _render_pin(render_pin)
        _verify_render_files(render_pin,root,total_frames,interrupt)
    destination = root / "genj" / "wan_conditioning"
    if destination.resolve(strict=False) != destination:
        raise ValueError("Wan merge destination has a redirected directory.")
    destination.mkdir(parents=True, exist_ok=True)
    if destination.resolve(strict=True) != destination or not destination.is_relative_to(root):
        raise ValueError("Wan merge destination has a redirected directory.")
    final = destination / (cache_key + ".pt")
    if final.exists() or final.is_symlink():
        raise FileExistsError("The reviewed Wan preparation cache already exists.")
    lock = destination / (cache_key + ".merge.lock")
    scratch = destination / (".merge-" + uuid.uuid4().hex)
    readers, aliases, subdirs = [], [], []
    locked, created = False, False
    try:
        with lock.open("x"):
            locked = True
        scratch.mkdir()
        created = True
        temporary = scratch / (cache_key + ".pt")
        identities = []
        for index, (spec, original) in enumerate(zip(specs, paths)):
            interrupt()
            identity = _verify_part(spec, original, root, interrupt)
            identities.append(identity)
            folder = scratch / str(index)
            folder.mkdir()
            subdirs.append(folder)
            alias = folder / (spec.cache_key + ".pt")
            os.link(original, alias)  # No tensor, archive, or storage copy.
            aliases.append(alias)
            if _stamp(alias) != identity:
                raise ValueError("Wan part alias differs from its approved file identity.")
            reader = WanPreparationWindows(alias, spec.cache_key, root, max_window_frames=4,
                expected_sha256=spec.sha256, interrupt=interrupt, require_nonempty_mask=False)
            if len(reader.arrays["frames"]) != spec.count or not _same(reader.metadata, metadata):
                raise ValueError("Wan part count or metadata differs from the reviewed full timeline.")
            readers.append(reader)
        shapes = {name: readers[0].arrays[name].shape for name in TENSOR_NAMES}
        ref = readers[0].arrays["reference"][:1].numpy().tobytes()
        ref_digest = hashlib.sha256(ref).hexdigest()
        del ref
        if any(spec.reference_sha256 is not None and spec.reference_sha256 != ref_digest for spec in specs):
            raise ValueError("Wan part reference digest differs from the approved character.")
        for reader in readers[1:]:
            if any(reader.arrays[name].shape[1:] != shapes[name][1:] for name in TENSOR_NAMES):
                raise ValueError("Wan preparation parts have incompatible conditioning rasters.")
            other = reader.arrays["reference"][:1].numpy().tobytes()
            if hashlib.sha256(other).hexdigest() != ref_digest:
                raise ValueError("Wan preparation parts have different approved character references.")
            del other
        shapes = {name: ((1 if name == "reference" else total_frames),) + shape[1:]
                  for name, shape in shapes.items()}
        storage_bytes = sum(math.prod(shape) * 4 for shape in shapes.values())
        if shutil.disk_usage(destination).free < storage_bytes + 16 * 1024 ** 2:
            raise OSError("There is insufficient disk space for the complete Wan preparation cache.")

        def blocks(name):
            selected = list(zip(specs, readers))[:1] if name == "reference" else zip(specs, readers)
            for spec, reader in selected:
                value = reader.arrays[name]
                stride = max(1, min(4, 4_000_000 // math.prod(value.shape[1:])))
                source_digest = hashlib.sha256()
                for start in range(0, len(value), stride):
                    array = value[start:min(start + stride, len(value))].numpy()
                    if name == "frames" and spec.window_source_sha256 is not None:
                        source_digest.update(memoryview(array).cast("B"))
                    yield array
                    del array
                if (name == "frames" and spec.window_source_sha256 is not None and
                        source_digest.hexdigest() != spec.window_source_sha256):
                    raise ValueError("Wan part source pixels differ from their approved window digest.")

        stats = _write_archive(temporary, shapes, metadata, blocks, interrupt)
        verified = WanPreparationWindows(temporary, cache_key, root, max_window_frames=4,
                                          interrupt=interrupt)
        if (len(verified.arrays["frames"]) != total_frames or not _same(verified.metadata, metadata) or
                hashlib.sha256(verified.arrays["reference"][:1].numpy().tobytes()).hexdigest() != ref_digest):
            raise ValueError("The merged Wan cache differs from its reviewed contract.")
        for spec, original, identity in zip(specs, paths, identities):
            if _verify_part(spec, original, root, interrupt) != identity:
                raise ValueError("Wan preparation part identity changed during merge.")
        verified.verify()
        interrupt()
        if render_pin is not None:
            _verify_render_files(render_pin,root,total_frames,interrupt)
        if destination.resolve(strict=True) != destination or final.exists() or final.is_symlink():
            raise ValueError("Wan merge destination changed before publication.")
        os.replace(temporary, final)
        receipt = dict(verified.provenance)
        receipt["path"] = str(final)
        receipt["merge"] = {**stats, "parts": len(readers), "reference_sha256": ref_digest,
                            "part_sha256": [spec.sha256 for spec in specs]}
        return receipt
    finally:
        # Delete only these explicitly created, confined temporary files.
        if created:
            for alias in aliases:
                alias.unlink(missing_ok=True)
            for folder in reversed(subdirs):
                folder.rmdir()
            (scratch / (cache_key + ".pt")).unlink(missing_ok=True)
            scratch.rmdir()
        if locked:
            lock.unlink(missing_ok=True)
