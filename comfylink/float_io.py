"""Original ComfyLink high-depth transport. SPDX-License-Identifier: MIT.

Copyright (c) 2026 Zura. Permission is hereby granted, free of charge, to any
person obtaining a copy of this software and associated documentation files
(the "Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies of the Software, and to permit persons to whom
the Software is furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS
IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED
TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR
THE USE OR OTHER DEALINGS IN THE SOFTWARE.

No colour, gamma, range or alpha conversion is implicit. RGBA float32 little
endian is bit-preserving; uint16_ae explicitly uses AE's 32768 white scale.
Callers supply a trusted root, never a graph-supplied absolute path.
"""
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
import copy
import hashlib
import json
import os
import re
import shutil
import stat
import uuid

import numpy as np

MAX_DIMENSION = 16384
MAX_PIXELS = 16 * 1024 * 1024
MAX_FRAMES = 10000
MAX_TRANSFER_BYTES = 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FOLDER = re.compile(r"ComfyLink/[0-9a-f]{32}\Z")
_ENCODINGS = {"scene_linear_rec709", "acescg", "acescct", "ae_project_icc", "unknown"}


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"Invalid {name}")
    return value


def _rational(value, name, positive=False, signed=False):
    if not isinstance(value, dict) or set(value) != {"numerator", "denominator"}:
        raise ValueError(f"Invalid {name} rational")
    n = _integer(value["numerator"], name, -(2**53 - 1) if signed else (1 if positive else 0), 2**53 - 1)
    d = _integer(value["denominator"], name, 1, 2**31 - 1)
    return Fraction(n, d)


def validate_colour(colour):
    if not isinstance(colour, dict) or not {"encoding", "sceneLinear"} <= set(colour) or set(colour) - {"encoding", "sceneLinear", "profileSha256"}:
        raise ValueError("Invalid colour declaration")
    encoding = colour["encoding"]
    if not isinstance(encoding, str) or encoding not in _ENCODINGS or type(colour["sceneLinear"]) is not bool:
        raise ValueError("Invalid colour encoding or sceneLinear")
    if encoding in {"scene_linear_rec709", "acescg"} and not colour["sceneLinear"]:
        raise ValueError("Linear colour encoding contradicts sceneLinear")
    if encoding == "acescct" and colour["sceneLinear"]:
        raise ValueError("ACEScct is not scene linear")
    if "profileSha256" in colour and (not isinstance(colour["profileSha256"], str) or not _SHA.fullmatch(colour["profileSha256"])):
        raise ValueError("Invalid profileSha256")
    if encoding == "ae_project_icc" and "profileSha256" not in colour:
        raise ValueError("AE project ICC requires profileSha256 identity")
    return copy.deepcopy(colour)


def canonical_manifest_bytes(manifest):
    """Canonical JSON for optional {manifest, sha256} transport wrappers."""
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def validate_manifest(value):
    if not isinstance(value, dict):
        raise ValueError("Manifest must be an object")
    if set(value) == {"manifest", "sha256"}:
        if not isinstance(value["sha256"], str) or not _SHA.fullmatch(value["sha256"]) or hashlib.sha256(canonical_manifest_bytes(value["manifest"])).hexdigest() != value["sha256"]:
            raise ValueError("Manifest SHA256 mismatch")
        value = value["manifest"]
    if not isinstance(value, dict):
        raise ValueError("Manifest must be an object")
    m = copy.deepcopy(value)
    required = {"schemaVersion", "sampleType", "layout", "byteOrder", "width", "height", "alphaAssociation", "sourceBitDepth", "colour", "frameRate", "frames"}
    if not required <= set(m) or set(m) - required - {"sourceStart"} or type(m["schemaVersion"]) is not int or m["schemaVersion"] != 1:
        raise ValueError("Unsupported manifest schema or fields")
    if not isinstance(m["sampleType"], str) or m["sampleType"] not in {"float32", "uint16_ae"} or m["layout"] != "RGBA" or m["byteOrder"] != "little":
        raise ValueError("Unsupported sample type, layout or byte order")
    w = _integer(m["width"], "width", 1, MAX_DIMENSION)
    h = _integer(m["height"], "height", 1, MAX_DIMENSION)
    if w * h > MAX_PIXELS:
        raise ValueError("Pixel limit exceeded")
    if not isinstance(m["alphaAssociation"], str) or m["alphaAssociation"] not in {"straight", "premultiplied"} or type(m["sourceBitDepth"]) is not int or m["sourceBitDepth"] not in {8, 16, 32}:
        raise ValueError("Invalid alphaAssociation or sourceBitDepth")
    if m["sampleType"] == "uint16_ae" and m["sourceBitDepth"] != 16:
        raise ValueError("uint16_ae requires sourceBitDepth 16")
    validate_colour(m["colour"])
    if "sourceStart" in m:
        _rational(m["sourceStart"], "sourceStart", signed=True)
    rate = _rational(m["frameRate"], "frameRate", True)
    if not Fraction(1, 1000) <= rate <= 1000:
        raise ValueError("Frame rate exceeds bounds")
    frames = m["frames"]
    if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_FRAMES:
        raise ValueError("Frame count limit exceeded")
    size = w * h * 4 * (4 if m["sampleType"] == "float32" else 2)
    if w * h * 16 * len(frames) > MAX_TRANSFER_BYTES:
        raise ValueError("Transfer byte limit exceeded")
    extension = "rgba32f" if m["sampleType"] == "float32" else "rgba16u"
    for i, frame in enumerate(frames):
        if not isinstance(frame, dict) or set(frame) != {"index", "filename", "byteLength", "sha256", "time"}:
            raise ValueError("Invalid frame fields")
        if type(frame["index"]) is not int or frame["index"] != i or frame["filename"] != f"{i+1:06d}.{extension}":
            raise ValueError("Invalid frame order or filename")
        if type(frame["byteLength"]) is not int or frame["byteLength"] != size:
            raise ValueError("Invalid frame byteLength")
        if not isinstance(frame["sha256"], str) or not _SHA.fullmatch(frame["sha256"]):
            raise ValueError("Invalid frame SHA256")
        if _rational(frame["time"], "time") != Fraction(i, 1) / rate:
            raise ValueError("Frame time does not match frameRate/order")
    return m


def _identity(s):
    return s.st_dev, s.st_ino


def _safe_stat(path, directory=False):
    s = Path(path).lstat()
    if stat.S_ISLNK(s.st_mode) or getattr(s, "st_file_attributes", 0) & 0x400:
        raise ValueError("Links and reparse points are forbidden")
    if directory and not stat.S_ISDIR(s.st_mode):
        raise ValueError("Expected directory")
    if not directory and (not stat.S_ISREG(s.st_mode) or s.st_nlink != 1):
        raise ValueError("Expected private regular file, without hard links")
    return s


@contextmanager
def _locked_parents(path):
    """Keep Windows directory identities pinned against rename/junction swaps."""
    chain = list(reversed(Path(path).absolute().parents)) + [Path(path).absolute()]
    handles, states = [], []
    try:
        for part in chain:
            before = _safe_stat(part, True)
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
                kernel.CreateFileW.restype = wintypes.HANDLE
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                handle = kernel.CreateFileW(str(part), 0x80, 3, None, 3, 0x02200000, None)
                if handle == wintypes.HANDLE(-1).value:
                    raise OSError(ctypes.get_last_error(), "Cannot pin directory identity", str(part))
                handles.append((kernel, handle))
            after = _safe_stat(part, True)
            if _identity(before) != _identity(after):
                raise ValueError("Directory identity changed")
            states.append((part, _identity(after)))
        yield
        for part, identity in states:
            if _identity(_safe_stat(part, True)) != identity:
                raise ValueError("Directory identity changed")
    finally:
        for kernel, handle in reversed(handles):
            kernel.CloseHandle(handle)


def _read_private(path, max_bytes, exact=None):
    before = _safe_stat(path)
    if before.st_size > max_bytes or (exact is not None and before.st_size != exact):
        raise ValueError("Invalid file size")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if _identity(before) != _identity(opened) or opened.st_nlink != 1:
            raise ValueError("File identity changed or shared hard link")
        data = stream.read(max_bytes + 1)
        after = os.fstat(stream.fileno())
        if _identity(_safe_stat(path)) != _identity(opened) or opened.st_size != after.st_size or opened.st_mtime_ns != after.st_mtime_ns:
            raise ValueError("File changed during read")
    if len(data) > max_bytes or (exact is not None and len(data) != exact):
        raise ValueError("Invalid file size")
    return data


def _json_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate JSON field")
        obj[key] = value
    return obj


def _scoped_folder(root, relative):
    if not isinstance(relative, str) or not _FOLDER.fullmatch(relative):
        raise ValueError("Expected ComfyLink/<32 lowercase hex> relative folder")
    base = Path(root).absolute()
    _safe_stat(base, True)
    return base / relative


def load_transfer(root, manifest_relative):
    """Return (NHWC float32 RGBA, validated wire manifest) from scoped input."""
    if not isinstance(manifest_relative, str) or not manifest_relative.endswith("/manifest.json"):
        raise ValueError("Expected scoped relative manifest.json path")
    folder = _scoped_folder(root, manifest_relative[:-len("/manifest.json")])
    with _locked_parents(folder):
        raw = _read_private(folder / "manifest.json", MAX_MANIFEST_BYTES)
        m = validate_manifest(json.loads(raw.decode("utf-8"), object_pairs_hook=_json_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON"))))
        result = []
        dtype = "<f4" if m["sampleType"] == "float32" else "<u2"
        for frame in m["frames"]:
            payload = _read_private(folder / frame["filename"], frame["byteLength"], frame["byteLength"])
            if hashlib.sha256(payload).hexdigest() != frame["sha256"]:
                raise ValueError("Frame SHA256 mismatch")
            rgba = np.frombuffer(payload, dtype=dtype).reshape(m["height"], m["width"], 4)
            if m["sampleType"] == "uint16_ae":
                rgba = rgba.astype(np.float32) / np.float32(32768)
            if not np.isfinite(rgba).all():
                raise ValueError("Nonfinite frame samples")
            result.append(rgba)
        return np.stack(result), m


def _exclusive_write(path, data):
    with open(path, "xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _publish_directory(temporary, destination):
    """Atomic no-replace directory publication on supported host platforms."""
    if os.name == "nt":
        os.rename(temporary, destination)  # Windows never replaces a directory.
        return
    import ctypes
    import sys
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        operation = library.renameat2
        operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = operation(-100, os.fsencode(temporary), -100, os.fsencode(destination), 1)
    elif sys.platform == "darwin" and hasattr(library, "renamex_np"):
        operation = library.renamex_np
        operation.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = operation(os.fsencode(temporary), os.fsencode(destination), 4)
    else:
        raise OSError("Host lacks atomic exclusive directory publication")
    if result:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def _rgba(value):
    array = np.asarray(value)
    if array.dtype != np.float32 or array.ndim not in {3, 4} or array.shape[-1] != 4:
        raise ValueError("Expected float32 RGBA array")
    h, w = array.shape[-3:-1]
    n = array.shape[0] if array.ndim == 4 else 1
    if not 1 <= n <= MAX_FRAMES or not 1 <= w <= MAX_DIMENSION or not 1 <= h <= MAX_DIMENSION or w*h > MAX_PIXELS or n*w*h*16 > MAX_TRANSFER_BYTES:
        raise ValueError("Frame dimensions/count/bytes exceed limits")
    if not np.isfinite(array).all():
        raise ValueError("Nonfinite frame samples")
    return array


def write_transfer(root, folder_relative, rgba_frames, *, colour, frame_rate, source_bit_depth=32, alpha_association="straight", sample_type="float32", source_start=None, exr_storage=None):
    """Exclusively publish a new directory; never replace existing job files.

    float32 retains finite sample bits. uint16_ae is an explicit quantising
    conversion and rejects values outside its representable range.
    """
    rgba = _rgba(rgba_frames)
    if rgba.ndim == 3:
        rgba = rgba[None]
    count, h, w, _ = rgba.shape
    folder = _scoped_folder(root, folder_relative)
    parent = folder.parent
    if not parent.exists():
        with _locked_parents(parent.parent):
            try:
                parent.mkdir()
            except FileExistsError:
                pass
    rate = _rational(frame_rate, "frameRate", True)
    sample_bytes = 4 if sample_type == "float32" else 2
    m = {"schemaVersion": 1, "sampleType": sample_type, "layout": "RGBA", "byteOrder": "little", "width": w, "height": h,
         "alphaAssociation": alpha_association, "sourceBitDepth": source_bit_depth, "colour": validate_colour(colour), "frameRate": copy.deepcopy(frame_rate), "frames": []}
    if source_start is not None:
        m["sourceStart"] = copy.deepcopy(source_start)
    if exr_storage not in {None, "float32", "half"}:
        raise ValueError("Invalid EXR storage")
    for i in range(1, count + 1):
        t = Fraction(i - 1, 1) / rate
        m["frames"].append({"index": i - 1, "filename": f"{i:06d}.{'rgba32f' if sample_type == 'float32' else 'rgba16u'}", "byteLength": w*h*4*sample_bytes,
                            "sha256": "0"*64, "time": {"numerator": t.numerator, "denominator": t.denominator}})
    validate_manifest(m)
    with _locked_parents(parent):
        if folder.exists() or folder.is_symlink():
            raise FileExistsError("Transfer destination already exists")
        temporary = parent / (".float-" + uuid.uuid4().hex)
        temporary.mkdir(mode=0o700)
        try:
            with _locked_parents(temporary):
                for frame, array in zip(m["frames"], rgba):
                    if sample_type == "uint16_ae":
                        scaled = array.astype(np.float64) * 32768
                        if np.any(scaled < 0) or np.any(scaled > 65535):
                            raise ValueError("Sample outside uint16_ae range; no implicit clamp")
                        payload = np.rint(scaled).astype("<u2").tobytes()
                    else:
                        payload = array.astype("<f4", copy=False).tobytes(order="C")
                    frame["sha256"] = hashlib.sha256(payload).hexdigest()
                    _exclusive_write(temporary / frame["filename"], payload)
                    if exr_storage is not None:
                        write_exr(temporary / (Path(frame["filename"]).stem + ".exr"), array, colour=m["colour"], storage=exr_storage, alpha_association=alpha_association)
                _exclusive_write(temporary / "manifest.json", canonical_manifest_bytes(m))
            _publish_directory(temporary, folder)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return folder_relative + "/manifest.json", m


_PRIMARIES = {
    "scene_linear_rec709": (0.64, 0.33, 0.30, 0.60, 0.15, 0.06, 0.3127, 0.3290),
    "acescg": (0.713, 0.293, 0.165, 0.830, 0.128, 0.044, 0.32168, 0.33767),
    "acescct": (0.713, 0.293, 0.165, 0.830, 0.128, 0.044, 0.32168, 0.33767),
}


def write_exr(path, rgba, *, colour, storage="float32", alpha_association="straight"):
    """Write declared RGBA channels with no colour transform, plus JSON sidecar.

    Caller supplies an exclusively-owned directory. FLOAT is default; HALF is
    explicit and checked for representability before conversion.
    """
    import OpenImageIO as oiio
    rgba = _rgba(rgba)
    if rgba.ndim != 3 or storage not in {"float32", "half"}:
        raise ValueError("Expected one RGBA frame and float32 or half storage")
    h, w, _ = rgba.shape
    if w > MAX_DIMENSION or h > MAX_DIMENSION or w*h > MAX_PIXELS:
        raise ValueError("EXR dimensions exceed limits")
    colour = validate_colour(colour)
    if alpha_association not in {"straight", "premultiplied"}:
        raise ValueError("Invalid alpha association")
    if storage == "half" and np.any(np.abs(rgba) > np.finfo(np.float16).max):
        raise ValueError("HALF overflow; no implicit clamp")
    path = Path(path).absolute()
    with _locked_parents(path.parent):
        if path.exists() or path.with_suffix(path.suffix + ".json").exists():
            raise FileExistsError("EXR destination already exists")
        token = uuid.uuid4().hex
        temporary = path.parent / (".float-" + token + ".exr")
        side_tmp = path.parent / (".float-" + token + ".json")
        spec = oiio.ImageSpec(w, h, 4, oiio.FLOAT if storage == "float32" else oiio.HALF)
        spec.channelnames = ["R", "G", "B", "A"]
        spec.alpha_channel = 3
        spec.attribute("compression", "zip")
        spec.attribute("oiio:UnassociatedAlpha", int(alpha_association == "straight"))
        spec.attribute("comfylink:colour", canonical_manifest_bytes(colour).decode())
        if colour["encoding"] in _PRIMARIES:
            spec.attribute("chromaticities", oiio.TypeDesc("float[8]"), _PRIMARIES[colour["encoding"]])
        sidecar = {"schemaVersion": 1, "storage": storage, "layout": "RGBA", "channelNames": ["R", "G", "B", "A"], "width": w, "height": h,
                   "alphaAssociation": alpha_association, "colour": colour, "nonfinitePolicy": "reject"}
        try:
            # Reserve the output name exclusively before handing it to OIIO.
            _exclusive_write(temporary, b"")
            out = oiio.ImageOutput.create(str(temporary))
            if out is None or not out.open(str(temporary), spec):
                raise ValueError("Could not open EXR output")
            try:
                if not out.write_image(np.ascontiguousarray(rgba)):
                    raise ValueError("Could not write EXR output: " + out.geterror())
            finally:
                out.close()
            sidecar["sha256"] = hashlib.sha256(_read_private(temporary, MAX_TRANSFER_BYTES)).hexdigest()
            _exclusive_write(side_tmp, canonical_manifest_bytes(sidecar))
            os.link(temporary, path)  # exclusive destination, including POSIX
            temporary.unlink()
            try:
                os.link(side_tmp, path.with_suffix(path.suffix + ".json"))
                side_tmp.unlink()
            except Exception:
                path.unlink()
                raise
        finally:
            temporary.unlink(missing_ok=True)
            side_tmp.unlink(missing_ok=True)
    return sidecar


def read_exr(path):
    """Read named R/G/B/A channels (regardless of file order), never infer colour.

    A validated sidecar is required: EXR storage type does not establish linear
    light or gamut. OIIO automatically sorts EXR channels; names define mapping.
    """
    import OpenImageIO as oiio
    path = Path(path).absolute()
    with _locked_parents(path.parent):
        encoded = _read_private(path, MAX_TRANSFER_BYTES)
        side = json.loads(_read_private(path.with_suffix(path.suffix + ".json"), MAX_MANIFEST_BYTES).decode(), object_pairs_hook=_json_pairs)
        if side.get("schemaVersion") != 1 or side.get("storage") not in {"float32", "half"} or side.get("layout") != "RGBA" or side.get("channelNames") != ["R", "G", "B", "A"] or side.get("nonfinitePolicy") != "reject":
            raise ValueError("Invalid EXR sidecar")
        validate_colour(side.get("colour"))
        if side.get("alphaAssociation") not in {"straight", "premultiplied"}:
            raise ValueError("Invalid EXR alpha association")
        if hashlib.sha256(encoded).hexdigest() != side.get("sha256"):
            raise ValueError("EXR SHA256 mismatch")
        config = oiio.ImageSpec()
        config.attribute("oiio:UnassociatedAlpha", 1)
        inp = oiio.ImageInput.open(str(path), config)
        if inp is None:
            raise ValueError("Could not open EXR")
        try:
            spec = inp.spec()
            w = _integer(spec.width, "EXR width", 1, MAX_DIMENSION)
            h = _integer(spec.height, "EXR height", 1, MAX_DIMENSION)
            if w*h > MAX_PIXELS or [w,h] != [side.get("width"), side.get("height")] or spec.nchannels != 4 or set(spec.channelnames) != {"R","G","B","A"} or spec.deep or spec.depth != 1:
                raise ValueError("EXR shape/channel contract mismatch")
            expected = oiio.FLOAT if side["storage"] == "float32" else oiio.HALF
            formats = list(spec.channelformats) or [spec.format]*4
            if any(f != expected for f in formats):
                raise ValueError("EXR storage does not match sidecar")
            data = inp.read_image(format=oiio.FLOAT)
            if data is None:
                raise ValueError("Could not read EXR")
            rgba = np.ascontiguousarray(data[:, :, [list(spec.channelnames).index(c) for c in "RGBA"]])
            _rgba(rgba)
        finally:
            inp.close()
        if hashlib.sha256(_read_private(path, MAX_TRANSFER_BYTES)).hexdigest() != side["sha256"]:
            raise ValueError("EXR changed during read")
        return rgba, side
