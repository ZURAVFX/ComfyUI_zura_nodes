"""Ephemeral, instance-bound Studio bridge. SPDX-License-Identifier: MIT.

The broker owns AE authority. This service neither changes Studio settings nor
submits, interrupts or deletes Comfy jobs. No profile token reaches a browser.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import time
import zipfile
from urllib.parse import parse_qs, urlsplit

import aiohttp
from aiohttp import web

from .security import require_local
from . import float_io

PREFIX = "/zura/comfylink/v1/studio"
SESSION_HEADER = "X-ComfyLink-Studio-Session"
TOKEN_HEADER = "X-ComfyLink-Studio-Token"
DOWNLOAD_HEADER = "X-ComfyLink-Studio-Download"
MAX_JSON = float_io.MAX_MANIFEST_BYTES
TTL = 15 * 60
MAX_LEASE_AGE = 8 * 60 * 60
BROKER_LEASE_WINDOW = 30 * 60
MAX_SESSIONS = 32
MAX_ORIGINAL_BYTES = float_io.MAX_TRANSFER_BYTES
SOURCE_DISK_HEADROOM = 4 * 1024**3
SOURCE_FRAME_OVERHEAD = 8 * 1024**2
SOURCE_SYSTEM_MEMORY_HEADROOM = 6 * 1024**3
_ORIGINAL_TYPES = {".exr": "image/x-exr", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".webp": "image/webp", ".mp4": "video/mp4", ".mov": "video/quicktime",
                   ".mkv": "video/x-matroska", ".webm": "video/webm", ".zip": "application/zip"}
_STUDIO_MODES = {"swap", "ripple", "viewport", "camera", "relight", "paintout", "watermark", "alpha",
                 "outpaint", "hdr", "director", "frames", "references", "image"}
_BROKER_DIAGNOSTICS = {"float import needs a known colour profile; the result remains available",
                       "float import requires verified straight alpha",
                       "HDR master retained. Choose a scene-linear AE working space such as ACEScg for verified HDR transfer.",
                       "HDR master retained. This AE working space uses colour files that are not yet verified. Use ACEScg or linear Rec.709 and send the shot again.",
                       "Result retained; native import needs attention",
                       "Result retained: dimensions, frame count or frame rate do not match the original layer."}
_SDR_TRANSFERS = {2: "unspecified", 1: "bt709", 4: "gamma22", 5: "gamma28", 6: "smpte170m", 7: "smpte240m", 13: "srgb"}
_SDR_PRIMARIES = {2: "unspecified", 1: "bt709", 4: "bt470m", 5: "bt470bg", 6: "smpte170m", 7: "smpte240m", 22: "ebu3213"}
_COLOUR_META = ("icc", "hdr", "exif", "xmp", "gamma", "chromatic", "cicp", "gainmap", "jumbf", "photoshop", "colour", "color", "profile")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")


def _require_raw_numeric_video_info(asset, info, manifest, input_root):
    """Do not advertise a normal clip until its actual editor and player inputs exist."""
    if not isinstance(asset, dict) or not isinstance(info, dict):
        raise ValueError('The normal eight-bit clip could not be inspected')
    relative = asset.get('file')
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError('The lossless processing clip has no registered file')
    root = Path(input_root).resolve(strict=True)
    source = root / relative
    if source.is_symlink():
        raise ValueError('The registered processing clip is a link')
    path = source.resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() != '.mkv':
        raise ValueError('The registered processing clip is unavailable')
    if not isinstance(info.get('path'), str) or Path(info['path']).resolve(strict=True) != path:
        raise ValueError('The native editor resolved a different processing clip')
    preview_file = asset.get('preview_file')
    if asset.get('preview_status') != 'ready' or not isinstance(preview_file, str) or not preview_file:
        raise ValueError('The normal playback preview is not ready')
    preview = asset.get('preview_url')
    parsed = urlsplit(preview) if isinstance(preview, str) else None
    query = parse_qs(parsed.query) if parsed else {}
    preview_path = Path(preview_file)
    if (not parsed or parsed.path != '/view' or parsed.netloc or not preview.startswith('/view?')
            or preview_path.is_absolute() or query.get('filename') != [preview_path.name]
            or query.get('subfolder') != [preview_path.parent.as_posix()] or query.get('type') != ['input']):
        raise ValueError('The normal playback preview has no local URL')
    if any(type(info.get(key)) is not int or info[key] != manifest[expected]
           for key, expected in (('width', 'width'), ('height', 'height'))):
        raise ValueError('The inspected processing clip has a different raster')
    if type(info.get('frames')) is not int or info['frames'] != len(manifest['frames']) or info.get('kind') != 'video':
        raise ValueError('The inspected processing clip has a different frame count')
    fps = info.get('fps')
    rate = manifest['frameRate']
    expected_fps = rate['numerator'] / rate['denominator']
    if type(fps) not in (int, float) or not math.isfinite(fps) or abs(fps - expected_fps) > .001:
        raise ValueError('The inspected processing clip has a different frame rate')
    duration = info.get('duration')
    if duration is not None and (type(duration) not in (int, float) or not math.isfinite(duration)
                                 or abs(duration - len(manifest['frames']) / expected_fps) > 1 / expected_fps + .002):
        raise ValueError('The inspected processing clip has a different duration')
    return info
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_BROKER_PATH = re.compile(r"/studio-bridge/[0-9a-f]{32}\Z")


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


async def _bounded_json(stream, limit=MAX_JSON):
    chunks, size = [], 0
    async for chunk in stream.iter_chunked(65536):
        size += len(chunk)
        if size > limit:
            raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=size)
        chunks.append(chunk)
    try:
        value = _json(b"".join(chunks))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise web.HTTPBadRequest(text="Expected a bounded JSON object")


def _origin(request):
    require_local(request)
    return request.scheme + "://" + request.headers["Host"]


def _broker(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or not parsed.port or parsed.username or parsed.password
                or "?" in value or "#" in value or parsed.query or parsed.fragment or not _BROKER_PATH.fullmatch(parsed.path)
                or parsed.netloc != "127.0.0.1:" + str(parsed.port)):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise web.HTTPBadRequest(text="Expected a loopback Studio broker URL")
    return value


def _secret(value):
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))


def _equal(value, expected):
    return isinstance(value, str) and secrets.compare_digest(value.encode(), expected.encode())


def _expiry(value):
    try:
        if not isinstance(value, str):
            raise ValueError()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.timestamp()
    except (ValueError, TypeError, OverflowError):
        raise web.HTTPBadGateway(text="Invalid broker grant expiry")


def _stamp(state):
    # Windows Python exposes different ctime semantics for stat and fstat.
    # Object identity, exact length, modification stamp and full SHA are used.
    return state.st_dev, state.st_ino, state.st_size, state.st_mtime_ns


def _file_record(path, limit, expected=None):
    """Hash one private file object with bounded reads and identity checks."""
    with float_io._locked_parents(path.parent):
        before = float_io._safe_stat(path)
        if not 0 < before.st_size <= limit:
            raise ValueError("Master container size exceeds bounds")
        digest, size = hashlib.sha256(), 0
        with path.open("rb") as stream:
            if _stamp(os.fstat(stream.fileno())) != _stamp(before):
                raise ValueError("Master file identity changed")
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise ValueError("Master file exceeded byte bound")
                digest.update(chunk)
            if _stamp(os.fstat(stream.fileno())) != _stamp(before):
                raise ValueError("Master file changed during read")
        if _stamp(float_io._safe_stat(path)) != _stamp(before) or size != before.st_size:
            raise ValueError("Master file identity or size changed")
        descriptor = {"filename": path.name, "byteLength": size, "sha256": digest.hexdigest()}
        if expected and any(descriptor[name] != expected[name] for name in ("byteLength", "sha256")):
            raise ValueError("Master file integrity mismatch")
        return path, _stamp(before), descriptor


def _unmanaged_metadata(metadata):
    if any(any(word in str(key).lower() for word in _COLOUR_META) for key in metadata):
        raise ValueError("Managed colour, ICC or HDR metadata requires explicit float export")


def _image_container(path, suffix):
    """Inspect actual image depth and colour-bearing container chunks."""
    size = path.stat().st_size
    transfer = "unspecified"
    with path.open("rb") as stream:
        if suffix == ".png":
            if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                raise ValueError("Invalid PNG master")
            first, ended = True, False
            while stream.tell() < size:
                header = stream.read(8)
                if len(header) != 8:
                    raise ValueError("Truncated PNG chunk")
                length, kind = int.from_bytes(header[:4], "big"), header[4:]
                start = stream.tell()
                if start + length + 4 > size:
                    raise ValueError("PNG chunk exceeds container")
                if first:
                    if kind != b"IHDR" or length != 13:
                        raise ValueError("Invalid PNG header")
                    ihdr = stream.read(13)
                    if ihdr[8] != 8:
                        raise ValueError("PNG master is not stored at eight bits")
                    first = False
                elif kind == b"sRGB":
                    if length != 1 or stream.read(1)[0] > 3:
                        raise ValueError("Invalid PNG sRGB declaration")
                    transfer = "srgb"
                elif kind in {b"tEXt", b"zTXt", b"iTXt"}:
                    keyword = stream.read(min(length, 80)).split(b"\0", 1)[0].decode("latin1")
                    _unmanaged_metadata({keyword: None})
                elif kind not in {b"PLTE", b"tRNS", b"IDAT", b"IEND", b"pHYs", b"tIME", b"bKGD", b"hIST"}:
                    # Includes iCCP/gAMA/cHRM/cICP/mDCV/cLLI/eXIf/APNG,
                    # and unknown colour extensions which cannot be proven SDR.
                    raise ValueError("Unsupported PNG colour or ancillary metadata")
                stream.seek(start + length + 4)
                if kind == b"IEND":
                    if length != 0 or stream.tell() != size:
                        raise ValueError("Trailing PNG container data")
                    ended = True
                    break
            if not ended:
                raise ValueError("PNG end marker is missing")
        elif suffix in {".jpg", ".jpeg"}:
            if stream.read(2) != b"\xff\xd8":
                raise ValueError("Invalid JPEG master")
            precision = None
            while stream.tell() < size:
                if stream.read(1) != b"\xff":
                    raise ValueError("Invalid JPEG marker")
                marker = stream.read(1)
                while marker == b"\xff":
                    marker = stream.read(1)
                if len(marker) != 1:
                    raise ValueError("Truncated JPEG marker")
                code = marker[0]
                if code in (0xda, 0xd9):
                    break
                length_raw = stream.read(2)
                if len(length_raw) != 2:
                    raise ValueError("Truncated JPEG segment")
                length = int.from_bytes(length_raw, "big")
                start = stream.tell()
                if length < 2 or start + length - 2 > size:
                    raise ValueError("JPEG segment exceeds container")
                if 0xe1 <= code <= 0xef:
                    raise ValueError("JPEG ICC, EXIF, XMP or extended colour metadata is unsupported")
                if code in {0xc0, 0xc1, 0xc2}:
                    precision = stream.read(1)
                elif 0xc0 <= code <= 0xcf and code not in {0xc4, 0xc8, 0xcc}:
                    raise ValueError("Unsupported JPEG precision or coding mode")
                stream.seek(start + length - 2)
            if precision != b"\x08":
                raise ValueError("JPEG master precision is not eight bits")
        elif suffix == ".webp":
            header = stream.read(12)
            if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WEBP" or int.from_bytes(header[4:8], "little") + 8 != size:
                raise ValueError("Invalid WebP container")
            image_chunks = 0
            while stream.tell() < size:
                header = stream.read(8)
                if len(header) != 8:
                    raise ValueError("Truncated WebP chunk")
                kind, length = header[:4], int.from_bytes(header[4:], "little")
                start = stream.tell()
                if start + length + (length & 1) > size or kind not in {b"VP8 ", b"VP8L", b"VP8X", b"ALPH"}:
                    raise ValueError("WebP ICC, EXIF, XMP, animation or unknown extension is unsupported")
                if kind == b"VP8X":
                    flags = stream.read(1)
                    if length != 10 or not flags or flags[0] & ~0x10:
                        raise ValueError("WebP colour, HDR or animation flags are unsupported")
                if kind in {b"VP8 ", b"VP8L"}:
                    # VP8 and VP8L are defined as eight-bit image codecs.
                    image_chunks += 1
                stream.seek(start + length + (length & 1))
            if image_chunks != 1:
                raise ValueError("Choose a single eight-bit WebP image")
        else:
            raise ValueError("Unsupported SDR image container")
    return transfer


def _video_sdr_metadata(value, inherited=None):
    """Validate every decoded frame as well as its stream/container metadata."""
    _unmanaged_metadata(getattr(value, "metadata", {}))
    side_data = getattr(value, "side_data", ())
    for entry in side_data:
        # PyAV 14/17 iterate SideData objects; PyAV 19 iterates Type keys.
        # Resolve mapping keys to their payloads, never discard an entry.
        side = entry
        if getattr(side, "type", None) is None:
            try:
                side = side_data[entry]
            except (KeyError, IndexError, TypeError, AttributeError):
                raise ValueError("Video side metadata payload is unavailable") from None
        side_type = getattr(side, "type", None)
        if side_type is None:
            raise ValueError("Video side metadata payload has no declared type")
        # x264's ordinary encoder identification SEI is unrelated to colour.
        if getattr(side_type, "name", "") == "SEI_UNREGISTERED" and bytes(side)[16:].startswith(b"x264 - core "):
            continue
        raise ValueError("Video side metadata cannot be proven unmanaged SDR")
    fmt = getattr(value, "format", None)
    if fmt is None or not fmt.components or any(component.bits != 8 for component in fmt.components):
        raise ValueError("Video storage is not eight bits per component")
    # Older PyAV builds expose transfer/primaries on the codec context but
    # omit them on decoded frames. Missing fields are unspecified, so inherit
    # only the separately validated current stream declaration below.
    transfer = getattr(value, "color_trc", None)
    primaries = getattr(value, "color_primaries", None)
    space = getattr(value, "colorspace", None)
    transfer, primaries, space = (2 if item is None else int(item) for item in (transfer, primaries, space))
    if inherited is not None:
        transfer = inherited[0] if transfer == 2 else transfer
        primaries = inherited[1] if primaries == 2 else primaries
        space = inherited[2] if space == 2 else space
    if transfer not in _SDR_TRANSFERS or primaries not in _SDR_PRIMARIES or space not in {0, 1, 2, 4, 5, 6, 7}:
        raise ValueError("Video colour metadata is not an allowed standard SDR declaration")
    return transfer, primaries, space


def _iso_bmff_sdr_container(path):
    # Colour profile and HDR sample-entry atoms have literal type identifiers.
    # A bounded conservative scan also rejects those atoms when a decoder build
    # does not expose stream side data to Python. No metadata is interpreted.
    forbidden = (b"colrprof", b"colrrICC", b"ICC_PROFILE", b"http://ns.adobe.com/xap/1.0/")
    hdr_atoms = (b"mdcv", b"clli", b"dvcC", b"dvvC", b"dvwC")
    overlap = max(map(len, forbidden)) + 4
    previous = b""
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            data = previous + chunk
            if any(marker in data for marker in forbidden):
                raise ValueError("Container embeds ICC, HDR or unsupported colour metadata")
            for marker in hdr_atoms:
                offset = data.find(marker)
                while offset >= 0:
                    if offset >= 4 and 8 <= int.from_bytes(data[offset - 4:offset], "big") <= 4096:
                        raise ValueError("Container declares HDR or Dolby Vision metadata")
                    offset = data.find(marker, offset + 1)
            previous = data[-overlap:]


def _studio_module(name):
    """Resolve the installed sibling module without importing a second Studio."""
    from importlib import import_module
    if not __package__ or "." not in __package__:
        raise ImportError("Native Studio package context is required")
    return import_module("..artist_studio." + name, __package__)


def _grant(value, origin, broker):
    if (type(value.get("schemaVersion")) is not int or value.get("schemaVersion") != 1 or not _HEX32.fullmatch(str(value.get("id", "")))
            or value["id"] != broker.rsplit("/", 1)[1] or value.get("comfyOrigin") != origin):
        raise web.HTTPForbidden(text="Broker grant belongs to another Comfy instance")
    target = value.get("target")
    if (not isinstance(target, dict) or set(target) != {"label"}
            or not isinstance(target["label"], str) or not 1 <= len(target["label"]) <= 200
            or any(ord(c) < 32 for c in target["label"])):
        raise web.HTTPBadGateway(text="Invalid broker target label")
    capabilities = value.get("capabilities")
    if not isinstance(capabilities, dict) or any(type(capabilities.get(key)) is not bool for key in ("source", "transfer")):
        raise web.HTTPBadGateway(text="Invalid broker capabilities")
    expires = _expiry(value.get("expiresAt"))
    if expires <= time.time():
        raise web.HTTPGone(text="Studio grant has expired")
    # Only declared fields are ever exposed to the UI. Broker-private metadata
    # and tokens are not copied into the public context.
    context = {"target": {"label": target["label"]}, "capabilities": {
        "source": capabilities["source"], "transfer": capabilities["transfer"]}}
    if capabilities.get("renew") is True:
        context["capabilities"]["renew"] = True
    if 'sdr32ImageReturn' in capabilities and type(capabilities['sdr32ImageReturn']) is not bool:
        raise web.HTTPBadGateway(text='Invalid SDR float image capability')
    if capabilities.get('sdr32ImageReturn') is True:
        context['capabilities']['sdr32ImageReturn'] = True
    if 'nativeVideoReturn' in capabilities and type(capabilities['nativeVideoReturn']) is not bool:
        raise web.HTTPBadGateway(text='Invalid native video return capability')
    if capabilities.get('nativeVideoReturn') is True:
        context['capabilities']['nativeVideoReturn'] = True
    if 'nativeStillReturn' in capabilities and type(capabilities['nativeStillReturn']) is not bool:
        raise web.HTTPBadGateway(text='Invalid native still return capability')
    if capabilities.get('nativeStillReturn') is True:
        context['capabilities']['nativeStillReturn'] = True
    transfer_precision = value.get('transferPrecision')
    if transfer_precision is not None:
        if type(transfer_precision) is not str or transfer_precision not in {'sdr8', 'prores12', 'float32'}:
            raise web.HTTPBadGateway(text='Invalid AE transfer precision')
        context['transferPrecision'] = transfer_precision
    for name in ("range", "source"):
        item = value.get(name)
        if isinstance(item, dict):
            context[name] = {key: entry for key, entry in item.items()
                             if key in {"width", "height", "frameCount", "startFrame", "endFrame", "fps", "mode"}
                             and isinstance(entry, (int, float, str)) and not isinstance(entry, bool)}
    return context, min(expires, time.time() + TTL)


@dataclass
class Session:
    id: str
    capability: str = field(repr=False)
    broker: str
    token: str = field(repr=False)
    origin: str
    context: dict
    expires: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    source: dict = field(default_factory=dict)
    result_files: list = field(default_factory=list)
    original_files: list = field(default_factory=list)
    download_capability: str = field(default="", repr=False)
    closed: bool = False
    preview_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    created_at: float = field(default_factory=time.time)
    max_expires: float = 0
    renew_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class StudioSessions:
    def __init__(self, input_root=None, output_root=None, instance_id="", importer=None, history_reader=None):
        self.input_root = Path(input_root) if input_root is not None else None
        self.output_root = Path(output_root) if output_root is not None else None
        self.instance_id = instance_id
        self.importer = importer
        self.history_reader = history_reader
        self.sessions = {}
        self.used = {}
        self._registration_lock = asyncio.Lock()
        self._revocations = set()
        self._source_reservations = {}
        self._preview_slots = asyncio.Semaphore(2)

    def roots(self):
        if self.input_root is None or self.output_root is None:
            import folder_paths
            self.input_root = Path(folder_paths.get_input_directory())
            self.output_root = Path(folder_paths.get_output_directory())
        return self.input_root, self.output_root

    def cleanup(self):
        now = time.time()
        for identity, session in list(self.sessions.items()):
            if session.expires <= now:
                authority = self.close_local(session)
                if authority is not None:
                    try:
                        task = asyncio.get_running_loop().create_task(self.revoke_broker(authority))
                        self._revocations.add(task)
                        task.add_done_callback(self._revocations.discard)
                    except RuntimeError:
                        authority.token = ""
        self.used = {key: expiry for key, expiry in self.used.items() if expiry > now}

    def close_local(self, session):
        """Revoke immediately; never queue departure behind source/result work."""
        authority = None
        if not session.closed and session.token:
            authority = Session(session.id, "", session.broker, session.token, session.origin, {}, session.expires)
        session.closed = True
        if getattr(self, 'work', None) is not None:
            self.work.schedule(session)
        if self.sessions.get(session.id) is session:
            self.sessions.pop(session.id, None)
        session.token = session.capability = session.download_capability = ""
        session.result_files.clear()
        session.original_files.clear()
        return authority

    async def revoke_broker(self, authority):
        try:
            await self.broker_json(authority, "/leave", {})
        except Exception:
            # Local authority stays revoked even if the broker is unreachable.
            pass
        finally:
            authority.token = ""

    def authorize(self, request, download=False):
        origin = _origin(request)
        self.cleanup()
        session = self.sessions.get(request.match_info.get("id"))
        if session is None:
            raise web.HTTPGone(text="Studio session is unavailable or expired")
        if session.origin != origin or not _equal(request.headers.get(DOWNLOAD_HEADER if download else SESSION_HEADER),
                                                  session.download_capability if download else session.capability):
            raise web.HTTPForbidden(text="Studio session authentication failed")
        if download and not session.download_capability:
            raise web.HTTPForbidden(text="No result is awaiting transfer")
        return session

    def active(self, session):
        if session.closed or self.sessions.get(session.id) is not session or session.expires <= time.time():
            raise web.HTTPGone(text="Studio session is unavailable or expired")

    async def broker_json(self, session, suffix, body=None):
        try:
            transfer_bytes = 0
            if suffix == "/result" and isinstance(body, dict):
                transfer_bytes = sum(item["byteLength"] for name in ("files", "originals") for item in body.get(name, []))
            deadline = min(1800, 180 + transfer_bytes / (16 * 1024**2)) if suffix == "/result" else 30
            timeout = aiohttp.ClientTimeout(total=deadline, connect=3, sock_read=deadline if suffix == "/result" else 30)
            async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as client:
                async with client.request("GET" if body is None else "POST", session.broker + suffix,
                                          headers={TOKEN_HEADER: session.token}, json=body,
                                          allow_redirects=False) as response:
                    if response.status < 200 or response.status >= 300:
                        if response.status in (401, 403, 404, 410):
                            raise web.HTTPGone(text="Broker authority is unavailable or expired")
                        raise web.HTTPBadGateway(text="Broker declined the Studio request")
                    return await _bounded_json(response.content)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise web.HTTPBadGateway(text="Local Studio broker is unavailable")

    def public(self, session):
        return {"id": session.id, "comfyOrigin": session.origin, "context": session.context, "label": session.context["target"]["label"],
                "expiresAt": datetime.fromtimestamp(session.expires, timezone.utc).isoformat(),
                **({"lease": {"renewable": True, "renewAfterSeconds": 300,
                    "maxExpiresAt": datetime.fromtimestamp(session.max_expires, timezone.utc).isoformat()}}
                   if session.context.get("capabilities", {}).get("renew") is True else {}),
                "modes": {"registry": "native_studio", "source": session.context["capabilities"]["source"],
                          "transfer": session.context["capabilities"]["transfer"]}}

    async def create(self, request):
        origin = _origin(request)
        body = await _bounded_json(request.content, 4096)
        broker, token = _broker(body.get("broker")), body.get("token")
        if set(body) != {"broker", "token"} or not _secret(token):
            raise web.HTTPBadRequest(text="Expected a broker and scoped Studio token")
        fingerprint = hashlib.sha256((broker + token).encode()).hexdigest()
        async with self._registration_lock:
            self.cleanup()
            if fingerprint in self.used:
                raise web.HTTPConflict(text="This Studio grant was already used")
            if len(self.sessions) >= MAX_SESSIONS or len(self.used) >= MAX_SESSIONS * 8:
                raise web.HTTPTooManyRequests(text="Too many active Studio sessions")
            session = Session(secrets.token_hex(16), secrets.token_hex(32), broker, token, origin, {}, 0)
            grant = await self.broker_json(session, "/grant")
            session.context, session.expires = _grant(grant, origin, broker)
            session.max_expires = session.created_at + MAX_LEASE_AGE
            self.sessions[session.id] = session
            if getattr(self, 'work', None) is not None:
                self.work.watch(session)
            self.used[fingerprint] = max(_expiry(grant["expiresAt"]), time.time() + TTL)
            loop = asyncio.get_running_loop()
            loop.call_later(max(0, session.expires - time.time()) + .05, self.cleanup)
            loop.call_later(TTL + .05, self.cleanup)
            return web.json_response({**self.public(session), "capability": session.capability}, status=201,
                                     headers={"Cache-Control": "no-store"})

    async def get(self, request):
        return web.json_response(self.public(self.authorize(request)))

    async def renew(self, request):
        session = self.authorize(request)
        body = await _bounded_json(request.content, 4096)
        if not isinstance(body, dict) or body:
            raise web.HTTPBadRequest(text="Renewal requires an empty object")
        if session.context.get("capabilities", {}).get("renew") is not True:
            raise web.HTTPConflict(text="This AE link does not support renewal. Reopen Studio from After Effects")
        observed = session.expires
        # Independent from source/result locks: a long transfer must not queue
        # the renewal until after its own authority has expired.
        async with session.renew_lock:
            self.active(session)
            now = time.time()
            if not session.max_expires or now >= session.max_expires:
                raise web.HTTPGone(text="The maximum AE session duration has ended; results are retained")
            if session.expires <= observed:
                try:
                    response = await self.broker_json(session, "/renew", {})
                except web.HTTPGone:
                    authority = self.close_local(session)
                    if authority is not None:
                        await self.revoke_broker(authority)
                    raise
                self.active(session)
                now = time.time()
                try:
                    if not isinstance(response, dict) or response.get("ok") is not True:
                        raise ValueError()
                    expires, maximum = _expiry(response.get("expiresAt")), _expiry(response.get("maxExpiresAt"))
                    if not now < expires <= now + BROKER_LEASE_WINDOW + 5 or not expires <= maximum <= now + MAX_LEASE_AGE + 5:
                        raise ValueError()
                except (ValueError, TypeError, web.HTTPException):
                    raise web.HTTPBadGateway(text="Invalid AE session renewal") from None
                maximum = min(maximum, session.max_expires)
                if maximum <= now:
                    raise web.HTTPGone(text="The maximum AE session duration has ended; results are retained")
                session.max_expires = maximum
                session.expires = min(expires, now + TTL, maximum)
                fingerprint = hashlib.sha256((session.broker + session.token).encode()).hexdigest()
                self.used[fingerprint] = max(self.used.get(fingerprint, 0), expires)
                asyncio.get_running_loop().call_later(max(0, session.expires-now)+.05, self.cleanup)
            return web.json_response({"ok": True,
                "expiresAt": datetime.fromtimestamp(session.expires, timezone.utc).isoformat(),
                "maxExpiresAt": datetime.fromtimestamp(session.max_expires, timezone.utc).isoformat()},
                headers={"Cache-Control": "no-store"})

    async def download(self, session, filename, destination, expected):
        self.active(session)
        timeout = aiohttp.ClientTimeout(total=180, connect=3, sock_read=30)
        try:
            async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as client:
                async with client.get(session.broker + "/source/" + filename,
                                      headers={TOKEN_HEADER: session.token}, allow_redirects=False) as response:
                    if response.status != 200 or (response.content_length is not None and response.content_length != expected["byteLength"]):
                        raise ValueError("Broker source size/status mismatch")
                    digest, size = hashlib.sha256(), 0
                    with destination.open("xb") as stream:
                        async for chunk in response.content.iter_chunked(1024 * 1024):
                            self.active(session)
                            size += len(chunk)
                            if size > expected["byteLength"]:
                                raise ValueError("Broker source exceeded declared size")
                            stream.write(chunk)
                            digest.update(chunk)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if size != expected["byteLength"] or digest.hexdigest() != expected["sha256"]:
                        raise ValueError("Broker source integrity mismatch")
                    self.active(session)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise web.HTTPBadGateway(text="Local Studio source transfer failed")

    async def stage_source(self, session, data):
        if isinstance(data, dict) and "nativeVideo" in data:
            return await self.stage_native_video(session, data)
        manifest = float_io.validate_manifest(data.get("manifest", data))
        still = self.validate_native_still_descriptor(data["nativeStill"], manifest) if "nativeStill" in data else None
        input_root, _ = self.roots()
        wire_bytes = sum(frame["byteLength"] for frame in manifest["frames"])
        decoded_bytes = manifest["width"] * manifest["height"] * 16 * len(manifest["frames"])
        # Raw staging plus FLOAT EXR cache and the existing native uploader's
        # own copy. Admission counts unwritten reservations from other sessions.
        budget = wire_bytes + 2 * (decoded_bytes + SOURCE_FRAME_OVERHEAD * len(manifest["frames"])) + SOURCE_DISK_HEADROOM
        if still:
            budget += 2 * still["file"]["byteLength"]
        free = shutil.disk_usage(input_root).free
        if free < budget + sum(self._source_reservations.values()):
            raise web.HTTPInsufficientStorage(text=f"Studio source needs {budget / 2**30:.1f} GiB free input disk including native cache and safety headroom")
        if decoded_bytes > float_io.LEGACY_BATCH_BYTES:
            self.check_stream_memory(manifest["width"] * manifest["height"] * 16)
        self._source_reservations[session.id] = budget
        try:
            return await self._stage_source_reserved(session, data)
        finally:
            self._source_reservations.pop(session.id, None)

    @staticmethod
    def validate_native_still_descriptor(value, manifest):
        """Admit one hashed AE Render Queue still beside its captured FLOAT frame."""
        from fractions import Fraction
        fields={"schemaVersion","kind","profile","file","width","height","frameRate","sourceStart","sourceColour",
                "sourceBitDepth","transferBitDepth","storageBitDepth","codec","hasAlpha","requestedPrecision","preserveRGBQualified"}
        if not isinstance(value,dict) or set(value)!=fields or value.get('schemaVersion')!=2 or value.get('kind')!='native_still':
            raise ValueError('Invalid native AE still descriptor')
        file=value['file'];rate=value['frameRate'];start=value['sourceStart']
        profiles={'png8':('sdr8',8,'png'),'png16':('prores12',16,'png'),'exr32':('float32',32,'exr')}
        selected=profiles.get(value['profile']) if type(value['profile']) is str else None
        if (selected is None or (value['requestedPrecision'],value['transferBitDepth'],value['codec'])!=selected
                or value['storageBitDepth']!=selected[1] or value['hasAlpha'] is not True
                or value['preserveRGBQualified'] is not False
                or value['sourceBitDepth']!=manifest['sourceBitDepth'] or manifest['sampleType']!='float32'
                or manifest['sourceBitDepth'] not in (16,32) or manifest['alphaAssociation']!='straight'
                or len(manifest['frames'])!=1 or (value['width'],value['height'])!=(manifest['width'],manifest['height'])
                or value['sourceColour']!=manifest['colour'] or rate!=manifest['frameRate']
                or start!=manifest.get('sourceStart') or not isinstance(start,dict)
                or set(start)!={'numerator','denominator'} or type(start['numerator']) is not int
                or type(start['denominator']) is not int or start['denominator']<=0
                or not isinstance(rate,dict) or set(rate)!={'numerator','denominator'}
                or type(rate['numerator']) is not int or type(rate['denominator']) is not int
                or rate['denominator']<=0 or not 0<Fraction(rate['numerator'],rate['denominator'])<=1000
                or not isinstance(file,dict) or set(file)!={'filename','sha256','byteLength'}
                or not re.fullmatch(r'native-still-'+value['profile']+r'_[0-9]{5,6}\.'+selected[2],str(file['filename']))
                or not re.fullmatch(r'[0-9a-f]{64}',str(file['sha256']))
                or type(file['byteLength']) is not int or not 64<=file['byteLength']<=512*1024**2):
            raise ValueError('Native AE PNG16 source identity or precision changed')
        return value

    @staticmethod
    def verify_native_png16(path, frame_path, manifest):
        """Require AE's real PNG16 codes to match the selected numeric SDR view."""
        import numpy as np
        import OpenImageIO as oiio
        from .studio_processing import encode_sdr8
        with Path(path).open('rb') as stream:
            header=stream.read(29)
        if (header[:8]!=b'\x89PNG\r\n\x1a\n' or header[12:16]!=b'IHDR'
                or int.from_bytes(header[8:12],'big')!=13
                or (int.from_bytes(header[16:20],'big'),int.from_bytes(header[20:24],'big'))
                    !=(manifest['width'],manifest['height']) or header[24:29]!=bytes((16,6,0,0,0))):
            raise ValueError('AE did not render the requested RGBA PNG16')
        reader=oiio.ImageInput.open(str(path))
        if reader is None:raise ValueError('AE PNG16 could not be decoded')
        try:
            spec=reader.spec();actual=reader.read_image(format=oiio.UINT16)
        finally:reader.close()
        if (spec.format!=oiio.UINT16 or spec.nchannels!=4 or actual.shape!=(manifest['height'],manifest['width'],4)
                or actual.dtype!=np.uint16):
            raise ValueError('AE PNG16 storage or channel layout changed')
        raw=np.fromfile(frame_path,dtype='<f4')
        if raw.size!=manifest['width']*manifest['height']*4:raise ValueError('Captured FLOAT source changed size')
        rgba=raw.reshape(manifest['height'],manifest['width'],4)
        if not np.isfinite(rgba).all():raise ValueError('Captured FLOAT source has non-finite samples')
        expected16=np.rint(np.clip(rgba.astype(np.float64),0,1)*65535).astype(np.uint16)
        delta=np.abs(actual.astype(np.int32)-expected16.astype(np.int32))
        if np.any(delta>2):raise ValueError('AE PNG16 differs from the selected eight-bit numeric source; Preserve RGB is not verified')
        return encode_sdr8(rgba,derived=True,processor=None)

    @staticmethod
    def verify_native_still(path, frame_path, manifest, profile):
        if profile=='png16':return StudioSessions.verify_native_png16(path,frame_path,manifest)
        import numpy as np
        import OpenImageIO as oiio
        from .studio_processing import encode_sdr8
        raw=np.fromfile(frame_path,dtype='<f4')
        if raw.size!=manifest['width']*manifest['height']*4:raise ValueError('Captured AE FLOAT frame changed size')
        rgba=raw.reshape(manifest['height'],manifest['width'],4)
        if not np.isfinite(rgba).all():raise ValueError('Captured AE FLOAT frame has non-finite pixels')
        reader=oiio.ImageInput.open(str(path))
        if reader is None:raise ValueError('AE Render Queue still could not be decoded')
        try:
            spec=reader.spec()
            if (spec.width,spec.height,spec.nchannels)!=(manifest['width'],manifest['height'],4):
                raise ValueError('AE Render Queue still changed the source raster or channels')
            if profile=='png8':
                with Path(path).open('rb') as stream:header=stream.read(29)
                if (header[:8]!=b'\x89PNG\r\n\x1a\n' or header[12:16]!=b'IHDR'
                        or header[24:29]!=bytes((8,6,0,0,0)) or spec.format!=oiio.UINT8):
                    raise ValueError('AE did not render an RGBA PNG8')
                actual=reader.read_image(format=oiio.UINT8)
            elif profile=='exr32':
                if spec.format!=oiio.FLOAT or set(spec.channelnames)!={'R','G','B','A'}:
                    raise ValueError('AE did not render an RGBA FLOAT32 EXR')
                actual=reader.read_image(format=oiio.FLOAT)
                actual=actual[..., [list(spec.channelnames).index(name) for name in ('R','G','B','A')]]
            else:raise ValueError('Unknown AE still profile')
        finally:reader.close()
        if profile=='png8':
            expected=encode_sdr8(rgba,derived=True,processor=None)
            if actual.dtype!=np.uint8 or actual.shape!=expected.shape or np.any(
                    np.abs(actual.astype(np.int16)-expected.astype(np.int16))>1):
                raise ValueError('AE PNG8 differs from the selected eight-bit numeric source; Preserve RGB is not verified')
            return expected
        if actual.dtype!=np.float32 or actual.shape!=rgba.shape or not np.isfinite(actual).all():
            raise ValueError('AE EXR32 has invalid FLOAT pixels')
        return None

    @staticmethod
    def validate_native_video(path, descriptor):
        """Verify the native ProRes storage and every frame timestamp."""
        from fractions import Fraction
        import av
        rate = descriptor["frameRate"]
        expected_rate = Fraction(rate["numerator"], rate["denominator"])
        with av.open(str(path)) as movie:
            if len(movie.streams.video) != 1:
                raise ValueError("The native source has an unexpected video track count")
            stream = movie.streams.video[0]
            codec = stream.codec_context
            if (codec.name != "prores" or codec.codec_tag not in {"ap4h", "ap4x"}
                    or codec.profile not in {"4444", "XQ"} or stream.average_rate != expected_rate
                    or (stream.width, stream.height) != (descriptor["width"], descriptor["height"])):
                raise ValueError("The native source is not the requested ProRes4444 range")
            first_time, count = None, 0
            for frame in movie.decode(video=0):
                if count >= descriptor["frameCount"] or frame.format.name not in {"yuv444p12le", "yuva444p12le"}:
                    raise ValueError("The native source has extra frames or reduced precision")
                if (frame.width, frame.height) != (descriptor["width"], descriptor["height"]):
                    raise ValueError("The native source raster changed")
                if type(frame.pts) is not int or frame.time_base is None:
                    raise ValueError("The native source frame clock is missing")
                instant = frame.pts * frame.time_base
                if first_time is None:
                    first_time = instant
                if instant != first_time + Fraction(count, 1) / expected_rate:
                    raise ValueError("The native source frame cadence changed")
                count += 1
            if count != descriptor["frameCount"]:
                raise ValueError("The native source has missing frames")

    async def stage_native_video(self, session, data):
        """Keep the AE MOV as the registered processing original; preview separately."""
        from fractions import Fraction
        descriptor = data.get("nativeVideo")
        if not isinstance(descriptor, dict) or set(descriptor) not in ({"schemaVersion", "kind", "file", "width", "height", "frameCount", "frameRate", "sourceColour", "sourceBitDepth", "transferBitDepth", "codec", "hasAlpha"}, {"schemaVersion", "kind", "file", "width", "height", "frameCount", "frameRate", "sourceStart", "sourceColour", "sourceBitDepth", "transferBitDepth", "codec", "hasAlpha"}):
            raise ValueError("Invalid native source descriptor")
        file = descriptor["file"]
        rate = descriptor["frameRate"]
        if (descriptor["schemaVersion"] != 2 or descriptor["kind"] != "native_video" or descriptor["codec"] != "prores4444"
                or descriptor["transferBitDepth"] != 12 or descriptor["sourceBitDepth"] not in (16, 32)
                or type(descriptor["hasAlpha"]) is not bool
                or not isinstance(file, dict) or set(file) != {"filename", "byteLength", "sha256"}
                or file["filename"] != "source.mov" or type(file["byteLength"]) is not int
                or not 8 <= file["byteLength"] <= 2 * 1024**3 or not re.fullmatch(r"[0-9a-f]{64}", str(file["sha256"]))
                or type(descriptor["width"]) is not int or type(descriptor["height"]) is not int
                or not 1 <= descriptor["width"] <= 16384 or not 1 <= descriptor["height"] <= 16384
                or descriptor["width"] * descriptor["height"] > 16777216
                or type(descriptor["frameCount"]) is not int or not 1 <= descriptor["frameCount"] <= 10000
                or not isinstance(rate, dict) or set(rate) != {"numerator", "denominator"}
                or type(rate["numerator"]) is not int or type(rate["denominator"]) is not int or rate["denominator"] <= 0
                or not 0 < Fraction(rate["numerator"], rate["denominator"]) <= 1000
                or not isinstance(descriptor["sourceColour"], dict)):
            raise ValueError("Invalid native ProRes range or file identity")
        start = descriptor.get("sourceStart")
        if start is not None and (not isinstance(start, dict) or set(start) != {"numerator", "denominator"}
                                  or type(start["numerator"]) is not int or type(start["denominator"]) is not int
                                  or start["denominator"] <= 0):
            raise ValueError("Invalid native source start time")
        profile = data.get("profile")
        if descriptor["sourceColour"].get("encoding") == "ae_project_icc":
            if (not isinstance(profile, dict) or set(profile) != {"filename", "byteLength", "sha256"}
                    or profile.get("filename") != "source.icc" or profile.get("sha256") != descriptor["sourceColour"].get("profileSha256")
                    or type(profile.get("byteLength")) is not int or not 128 <= profile["byteLength"] <= 1024*1024):
                raise ValueError("Native source ICC profile is missing")
        elif profile is not None:
            raise ValueError("Unexpected native source ICC profile")
        input_root, _ = self.roots()
        budget = file["byteLength"] * 2 + SOURCE_DISK_HEADROOM
        if shutil.disk_usage(input_root).free < budget + sum(self._source_reservations.values()):
            raise web.HTTPInsufficientStorage(text="The native MOV needs space for its registered original and browser preview")
        self._source_reservations[session.id] = budget
        try:
            parent = input_root.absolute() / "ComfyLink"
            with float_io._locked_parents(input_root.absolute()):
                parent.mkdir(exist_ok=True)
            folder = parent / session.id
            with float_io._locked_parents(parent):
                folder.mkdir(exist_ok=False)
            try:
                movie = folder / "source.mov"
                await self.download(session, "source.mov", movie, file)
                if profile:
                    await self.download(session, "source.icc", folder / "source.icc", profile)
                await asyncio.to_thread(self.validate_native_video, movie, descriptor)
                self.active(session)
                form = aiohttp.FormData()
                with movie.open("rb") as stream:
                    form.add_field("file", stream, filename="source.mov", content_type="video/quicktime")
                    timeout = min(1800, 180 + file["byteLength"] / (16 * 1024**2))
                    async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=timeout, connect=3, sock_read=180)) as client:
                        async with client.post(session.origin + "/zura/studio/upload?kind=video", data=form,
                                               headers={"Origin": session.origin}, allow_redirects=False) as response:
                            if response.status != 200:
                                raise ValueError("Native Studio movie import unavailable")
                            asset = await _bounded_json(response.content)
                self.active(session)
                if asset.get("sha") != file["sha256"] or not _HEX32.fullmatch(str(asset.get("id", ""))):
                    raise ValueError("Studio registered different source movie bytes")
                deadline = time.monotonic() + timeout
                while asset.get("preview_status") != "ready":
                    if asset.get("preview_status") == "error" or time.monotonic() >= deadline:
                        raise ValueError("Native movie preview failed; the original remains registered")
                    await asyncio.sleep(.1)
                    async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=30, connect=3)) as client:
                        async with client.get(session.origin + "/zura/studio/assets/" + asset["id"] + "/preview",
                                              headers={"Origin": session.origin}, allow_redirects=False) as response:
                            if response.status != 200:
                                raise ValueError("Native movie preview status unavailable")
                            asset = await _bounded_json(response.content)
                async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=30, connect=3)) as client:
                    async with client.post(session.origin + "/zura/studio/assets/" + asset["id"] + "/ripple",
                                           json={}, headers={"Origin": session.origin}, allow_redirects=False) as response:
                        if response.status != 200:
                            raise ValueError("Native movie editor source unavailable")
                        info = await _bounded_json(response.content)
                if not isinstance(info, dict) or not isinstance(info.get("path"), str):
                    raise ValueError("Native movie editor did not confirm its original")
                info["media_url"] = asset["preview_url"]
                return {"sourceTransfer": descriptor, "studioAsset": asset, "mediaInfo": info,
                        "width": descriptor["width"], "height": descriptor["height"], "frameCount": descriptor["frameCount"],
                        "fps": float(Fraction(rate["numerator"], rate["denominator"])),
                        "precision": {"sampleType": "video", "sourceBitDepth": descriptor["sourceBitDepth"], "transferBitDepth": 12},
                        "colour": descriptor["sourceColour"]}
            except BaseException:
                with float_io._locked_parents(parent):
                    shutil.rmtree(folder)
                raise
        finally:
            self._source_reservations.pop(session.id, None)

    @staticmethod
    def check_stream_memory(frame_bytes):
        needed = max(2 * 1024**3, frame_bytes * 4) + SOURCE_SYSTEM_MEMORY_HEADROOM
        if float_io.available_memory_bytes() < needed:
            raise ValueError(f"Streamed float input needs {needed / 2**30:.1f} GiB currently available RAM for frame buffers and OS/AE headroom")

    async def _stage_source_reserved(self, session, data):
        manifest = float_io.validate_manifest(data.get("manifest", data))
        native_still = self.validate_native_still_descriptor(data["nativeStill"], manifest) if "nativeStill" in data else None
        if native_still and data.get('sourceTransfer')!=native_still:
            raise ValueError('Native AE still transfer descriptor changed')
        # Only the authenticated local broker response supplies conversion
        # authority. Browser POST fields never enter this descriptor.
        from .studio_processing import validate_processing_input, verified_linear_srgb_icc
        processing = validate_processing_input(data.get("processingInput"), manifest)
        if native_still and native_still['codec']=='png' and (not processing or processing['conversion']!='raw_numeric_to_sdr8'):
            raise ValueError('Native PNG source needs the verified eight-bit numeric model view')
        if native_still and native_still['profile']=='exr32' and processing is not None and processing['conversion'] not in {
                'verified_icc_to_sdr8','verified_icc_numeric_to_sdr8','verified_ocio_to_sdr8','verified_srgb_to_sdr8'}:
            raise ValueError('The FLOAT32 AE source needs a separately verified SDR model view')
        expected = [{key: frame[key] for key in ("filename", "byteLength", "sha256")} for frame in manifest["frames"]]
        if "files" in data and data["files"] != expected:
            raise ValueError("Source file list differs from manifest")
        profile = data.get("profile")
        if manifest["colour"]["encoding"] == "ae_project_icc":
            if (not isinstance(profile, dict) or set(profile) != {"filename", "byteLength", "sha256"}
                    or profile.get("filename") != "source.icc" or type(profile.get("byteLength")) is not int
                    or not 128 <= profile["byteLength"] <= 4 * 1024 * 1024
                    or profile.get("sha256") != manifest["colour"]["profileSha256"]):
                raise ValueError("Project ICC profile is missing or differs from colour identity")
        elif profile is not None:
            raise ValueError("Unexpected source ICC profile")
        input_root, _ = self.roots()
        parent = input_root.absolute() / "ComfyLink"
        with float_io._locked_parents(input_root.absolute()):
            parent.mkdir(exist_ok=True)
        folder = parent / session.id
        if folder.exists() and not folder.is_symlink():
            retained = float_io.validate_manifest(json.loads(float_io._read_private(folder / "manifest.json", 8*1024*1024)))
            if retained != manifest:
                raise ValueError("The staged source belongs to a different capture")
            return await self.finish_staged_source(session, folder, manifest, native_still, processing)
        temporary = parent / (".studio-" + secrets.token_hex(16))
        with float_io._locked_parents(parent):
            if folder.exists() or folder.is_symlink():
                raise ValueError("Source destination already exists")
            temporary.mkdir()
        try:
            # This directory is exclusively owned and every leaf comes from the
            # validated strict manifest, never an arbitrary URL or source path.
            with float_io._locked_parents(temporary):
                for entry in expected:
                    await self.download(session, entry["filename"], temporary / entry["filename"], entry)
                if native_still:
                    await self.download(session,native_still['file']['filename'],temporary/native_still['file']['filename'],native_still['file'])
                if profile:
                    await self.download(session, "source.icc", temporary / "source.icc", profile)
                    encoded_profile = float_io._read_private(temporary / "source.icc", 4 * 1024 * 1024)
                    if (encoded_profile[36:40] != b"acsp"
                            or int.from_bytes(encoded_profile[:4], "big") != len(encoded_profile)):
                        raise ValueError("Invalid project ICC profile header")
                    if processing and processing['conversion'] in {'verified_icc_to_sdr8', 'verified_icc_numeric_to_sdr8'}:
                        verified_linear_srgb_icc(encoded_profile)
                if native_still:
                    await asyncio.to_thread(self.verify_native_still,temporary/native_still['file']['filename'],
                                            temporary/manifest['frames'][0]['filename'],manifest,native_still['profile'])
                float_io._exclusive_write(temporary / "manifest.json", float_io.canonical_manifest_bytes(manifest))
                if processing:
                    float_io._exclusive_write(temporary / "processing-input.json", float_io.canonical_manifest_bytes(processing))
            # Validate actual pixels before publication, including NaN/Inf.
            probe = secrets.token_hex(16)
            validation_folder = parent / probe
            with float_io._locked_parents(parent):
                os.rename(temporary, validation_folder)
            try:
                await asyncio.to_thread(float_io.verify_transfer, input_root, "ComfyLink/" + probe + "/manifest.json")
                self.active(session)
                with float_io._locked_parents(parent):
                    if folder.exists() or folder.is_symlink():
                        raise ValueError("Source destination already exists")
                    os.rename(validation_folder, folder)
            finally:
                if validation_folder.exists():
                    with float_io._locked_parents(parent):
                        shutil.rmtree(validation_folder)
        finally:
            if temporary.exists():
                with float_io._locked_parents(parent):
                    shutil.rmtree(temporary)
        return await self.finish_staged_source(session, folder, manifest, native_still, processing)

    async def finish_staged_source(self, session, folder, manifest, native_still, processing):
        rate = manifest["frameRate"]
        result = {"floatManifest": {"filename": "manifest.json", "subfolder": "ComfyLink/" + session.id, "type": "input"},
                  "precision": {"sampleType": manifest["sampleType"], "sourceBitDepth": manifest["sourceBitDepth"]},
                  "colour": manifest["colour"], "alpha": manifest["alphaAssociation"],
                  "width": manifest["width"], "height": manifest["height"], "frameCount": len(manifest["frames"]),
                  "fps": rate["numerator"] / rate["denominator"], "manifest": manifest}
        try:
            self.active(session)
            imported = await (self.native_still_import(session, folder, manifest, native_still, processing)
                              if native_still else (self.importer or self.native_import)(session, folder, manifest))
            result.update({key: value for key, value in imported.items() if key in {"studioAsset", "mediaInfo", "stills", "nativeInputColour", "resolved_colour"}})
            if native_still:
                result["sourceTransfer"] = native_still
                result["precision"] = {"sampleType": {'png8':'uint8','png16':'uint16_png','exr32':'float32'}[native_still['profile']],
                                       "sourceBitDepth": manifest["sourceBitDepth"],
                                       "transferBitDepth": native_still['transferBitDepth'],
                                       "storageBitDepth": native_still['storageBitDepth']}
            if processing:
                # The PNG16 remains the original. Models receive the separately
                # verified SDR8 copy, never an implicit decode of PNG16.
                model_imported = imported.get('processingInput', imported)
                model_input = model_imported.get('processingInput', model_imported)
                result["processingInput"] = {**processing,
                    "precision": {"sampleType": "uint8", "sourceBitDepth": 8},
                    **{key: value for key, value in model_input.items() if key in {"studioAsset", "mediaInfo", "stills"}}}
                if processing['conversion'] == 'raw_numeric_to_sdr8':
                    result['processingInput']['returnPolicy'] = 'unqualified_raw_numeric'
        except Exception:
            if native_still:
                raise
            # Media decoders use several library-specific exception classes.
            # Keep the verified raw source available without logging filenames.
            result["nativeImport"] = {"status": "unavailable", "diagnostic":
                ("The SDR model input could not be prepared. The FLOAT source is retained. Check its colour mapping and installed EXR support."
                 if processing else "Float source retained. Native Studio import needs a compatible media route and installed EXR support for high-depth sources.")}
        return result

    async def source(self, request):
        session = self.authorize(request)
        if request.can_read_body:
            await _bounded_json(request.content, 4096)
        if not session.context["capabilities"]["source"]:
            raise web.HTTPForbidden(text="This session has no source authority")
        async with session.lock:
            self.active(session)
            if session.source:
                return web.json_response(session.source)
            data = await self.broker_json(session, "/source")
            self.active(session)
            try:
                session.source = await self.stage_source(session, data)
            except (ValueError, OSError):
                raise web.HTTPUnprocessableEntity(text="Source validation failed; the AE source is retained")
            self.active(session)
            return web.json_response(session.source)

    async def model_source(self, request):
        """Separate working movie; original source/return authority is unchanged."""
        import copy
        from .studio_rate import reinterpret_movie
        session=self.authorize(request)
        if not session.context.get('capabilities',{}).get('source'):raise web.HTTPForbidden(text='This session has no source authority')
        body=await _bounded_json(request.content,4096)
        if body != {"frameRate":24}:
            raise web.HTTPBadRequest(text="Choose a supported native model frame rate")
        async with session.lock:
            self.active(session)
            if not session.source:raise web.HTTPConflict(text="Load the AE source first")
            cached=getattr(session,'model_sources',{})
            if 24 in cached:return web.json_response(cached[24])
            source=copy.deepcopy(session.source)
            rate=(source.get('manifest') or source.get('sourceTransfer') or {}).get('frameRate')
            if not rate:raise web.HTTPConflict(text="The original AE frame rate is unavailable")
            if rate['numerator']==24*rate['denominator']:return web.json_response(source)
            model=source.get('processingInput',source)
            asset=model.get('studioAsset')
            if not asset or not isinstance(asset.get('file'),str):raise web.HTTPConflict(text="The AE working movie is unavailable")
            root,_=self.roots();root=root.absolute()
            path=(root/asset['file']).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():raise web.HTTPConflict(text="The working movie is unavailable")
            folder=root/'ComfyLink'/session.id
            movie=folder/'model-clock-24.mkv'
            try:
                await asyncio.to_thread(reinterpret_movie,path,movie,rate,24,source['frameCount'])
                self.active(session)
                form=aiohttp.FormData()
                with movie.open('rb') as stream:
                    form.add_field('file',stream,filename=movie.name,content_type='video/x-matroska')
                    async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=600,connect=3)) as client:
                        async with client.post(session.origin+'/zura/studio/upload?kind=video',data=form,headers={'Origin':session.origin},allow_redirects=False) as response:
                            if response.status!=200:raise ValueError('Could not register the model-rate movie')
                            prepared=await _bounded_json(response.content)
                        if not _HEX32.fullmatch(str(prepared.get('id',''))):raise ValueError('Invalid working movie')
                        deadline=time.monotonic()+300
                        while prepared.get('preview_status')!='ready':
                            if prepared.get('preview_status')=='error' or time.monotonic()>deadline:raise ValueError('The working movie preview could not be prepared')
                            self.active(session);await asyncio.sleep(.2)
                            async with client.get(session.origin+'/zura/studio/assets/'+prepared['id']+'/preview',headers={'Origin':session.origin},allow_redirects=False) as response:
                                if response.status!=200:raise ValueError('Working movie preview unavailable')
                                prepared=await _bounded_json(response.content)
                        async with client.post(session.origin+'/zura/studio/assets/'+prepared['id']+'/ripple',json={},headers={'Origin':session.origin},allow_redirects=False) as response:
                            if response.status!=200:raise ValueError('Working movie metadata unavailable')
                            info=await _bounded_json(response.content)
                info['media_url']=prepared.get('preview_url',prepared.get('url',''))
                model.update(studioAsset=prepared,mediaInfo=info,fps=24)
                source['modelFrameRate']={'numerator':24,'denominator':1}
                source['fps']=24
                self.active(session)
                cached[24]=source;session.model_sources=cached
                return web.json_response(source)
            except (ValueError,OSError) as error:
                raise web.HTTPUnprocessableEntity(text=str(error)) from None

    async def retained_images(self, request):
        from .studio_recovery import retained_images, MAX_HISTORY
        session = self.authorize(request)
        body = await _bounded_json(request.content, 4096)
        if (not isinstance(body, dict) or set(body) not in (set(), {'candidateId'})
                or 'candidateId' in body and not _secret(body['candidateId'])):
            raise web.HTTPBadRequest(text='Invalid retained-result selection')
        if not session.context['capabilities']['source'] or not session.context['capabilities']['transfer']:
            raise web.HTTPForbidden(text='This session cannot recover an image result')
        async with session.lock:
            self.active(session)
            if not session.source.get('manifest'):
                raise web.HTTPConflict(text='Load the AE source before looking for a saved result')
            try:
                history = await asyncio.to_thread(self.history_reader, MAX_HISTORY) if self.history_reader else {}
                self.active(session)
                input_root, output_root = self.roots()
                results = await asyncio.to_thread(retained_images, input_root, session.id,
                    session.source['manifest'], history, self.resolve_master,
                    lambda path: _image_container(path, '.png'), output_root)
                self.active(session)
            except (ValueError, OSError):
                raise web.HTTPUnprocessableEntity(text='The retained result could not be verified against this AE source')
            if 'candidateId' in body:
                selected = next((item for item in results if item['id'] == body['candidateId']), None)
                if selected is None:
                    return web.json_response({'error': 'No matching saved result is available. Its files have not been changed'},
                                             status=409, headers={'Cache-Control': 'no-store'})
                return web.json_response({'result': selected}, headers={'Cache-Control': 'no-store'})
            return web.json_response({'results': results}, headers={'Cache-Control': 'no-store'})

    async def display_config(self, request):
        session = self.authorize(request)
        self.active(session)
        from . import display_view
        try:
            colour = session.source.get('colour') if session.source else None
            if colour is None:
                data = await self.broker_json(session, '/source')
                colour = float_io.validate_manifest(data.get('manifest', data))['colour']
                self.active(session)
            result = await asyncio.to_thread(display_view.describe, request.query.get("config", ""), source_colour=colour)
            self.active(session)
            return web.json_response(result, headers={"Cache-Control": "no-store"})
        except (ValueError, ImportError):
            raise web.HTTPBadRequest(text="This display configuration is unavailable")

    async def display_frame(self, request):
        """Preview one session-owned raw frame without changing its master."""
        session = self.authorize(request)
        if not session.context["capabilities"]["source"]:
            raise web.HTTPForbidden(text="This session has no source authority")
        index_text = request.query.get("index", "0")
        if not re.fullmatch(r"0|[1-9][0-9]{0,4}", index_text):
            raise web.HTTPBadRequest(text="Invalid preview frame")
        index = int(index_text)
        async with session.preview_lock, self._preview_slots:
            self.active(session)
            data = await self.broker_json(session, "/source")
            try:
                manifest = float_io.validate_manifest(data.get("manifest", data))
                if index >= len(manifest["frames"]):
                    raise ValueError("Preview frame is outside the source range")
                expected = manifest["frames"][index]
                descriptor = {key: expected[key] for key in ("filename", "byteLength", "sha256")}
                if "files" in data and data["files"] != [{key: frame[key] for key in descriptor} for frame in manifest["frames"]]:
                    raise ValueError("Source file list differs from manifest")
                payload = bytearray()
                digest = hashlib.sha256()
                profile_bytes = None
                timeout = aiohttp.ClientTimeout(total=180, connect=3, sock_read=30)
                async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as client:
                    async with client.get(session.broker + "/source/" + expected["filename"],
                                          headers={TOKEN_HEADER: session.token}, allow_redirects=False) as response:
                        if response.status != 200 or (response.content_length is not None and response.content_length != expected["byteLength"]):
                            raise ValueError("Preview frame size changed")
                        async for chunk in response.content.iter_chunked(1024 * 1024):
                            self.active(session)
                            payload.extend(chunk)
                            if len(payload) > expected["byteLength"]:
                                raise ValueError("Preview frame exceeds declared size")
                            digest.update(chunk)
                    if manifest['colour']['encoding'] == 'ae_project_icc':
                        profile = data.get('profile')
                        if (not isinstance(profile, dict) or set(profile) != {'filename', 'byteLength', 'sha256'}
                                or profile.get('filename') != 'source.icc' or type(profile.get('byteLength')) is not int
                                or not 132 <= profile['byteLength'] <= 4 * 1024 * 1024
                                or profile.get('sha256') != manifest['colour'].get('profileSha256')):
                            raise ValueError('Captured ICC profile identity changed')
                        async with client.get(session.broker + '/source/source.icc',
                                              headers={TOKEN_HEADER: session.token}, allow_redirects=False) as response:
                            if response.status != 200 or (response.content_length is not None and response.content_length != profile['byteLength']):
                                raise ValueError('Captured ICC profile size changed')
                            encoded = bytearray()
                            async for chunk in response.content.iter_chunked(65536):
                                self.active(session)
                                encoded.extend(chunk)
                                if len(encoded) > profile['byteLength']:
                                    raise ValueError('Captured ICC profile exceeds its declared size')
                        profile_bytes = bytes(encoded)
                        if len(profile_bytes) != profile['byteLength'] or hashlib.sha256(profile_bytes).hexdigest() != profile['sha256']:
                            raise ValueError('Captured ICC profile failed its integrity check')
                if len(payload) != expected["byteLength"] or digest.hexdigest() != expected["sha256"]:
                    raise ValueError("Preview frame failed its integrity check")
                from . import display_view
                render_options = {'profile': profile_bytes} if profile_bytes is not None else {}
                image = await asyncio.to_thread(display_view.render, payload, manifest,
                    request.query.get("config", ""), request.query.get("display", ""), request.query.get("view", ""), **render_options)
                self.active(session)
                headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
                if manifest["sourceBitDepth"] == 8 and manifest["colour"]["encoding"] == "unknown":
                    headers["X-ComfyLink-Preview-Note"] = "Untagged 8-bit preview assumes sRGB"
                elif manifest["colour"].get("management") == "ocio":
                    headers["X-ComfyLink-Preview-Note"] = "Preview uses the verified AE working space"
                elif manifest['colour']['encoding'] == 'ae_project_icc':
                    headers['X-ComfyLink-Preview-Note'] = 'Display-only preview uses the captured linear ICC profile'
                return web.Response(body=image, content_type="image/png", headers=headers)
            except (ValueError, OSError, aiohttp.ClientError, asyncio.TimeoutError):
                raise web.HTTPUnprocessableEntity(text="Display preview is unavailable for this source or colour space")

    async def native_still_import(self, session, folder, manifest, descriptor, processing):
        """Register the real AE still; numeric SDR copies remain separate."""
        from PIL import Image
        from importlib import import_module
        original=folder/descriptor['file']['filename']
        if hashlib.sha256(original.read_bytes()).hexdigest()!=descriptor['file']['sha256']:
            raise ValueError('The AE Render Queue still changed after source verification')
        if descriptor['profile']=='exr32':
            await asyncio.to_thread(self.verify_native_still,original,folder/manifest['frames'][0]['filename'],manifest,'exr32')
            # AE's EXR has no ComfyLink colour header. Keep its bytes as the
            # original, then make a separately receipted FLOAT copy with only
            # explicit interpretation metadata for the native HDR uploader.
            colour=manifest['colour']
            if colour.get('management')=='icc':
                from .studio_processing import verified_linear_srgb_icc
                profile=float_io._read_private(folder/'source.icc',4*1024*1024)
                verified_linear_srgb_icc(profile)
                upload_colour={'encoding':'scene_linear_rec709','sceneLinear':True}
            else:
                upload_colour=colour
            tagged_dir=folder/('native-'+secrets.token_hex(16))
            with float_io._locked_parents(folder):tagged_dir.mkdir()
            tagged=tagged_dir/'000001.exr'
            try:
                import numpy as np
                original_side={'schemaVersion':1,'storage':'float32','layout':'RGBA',
                    'channelNames':['R','G','B','A'],'nonfinitePolicy':'reject',
                    'colour':colour,'alphaAssociation':manifest['alphaAssociation'],
                    'width':manifest['width'],'height':manifest['height'],
                    'sha256':descriptor['file']['sha256']}
                side_path=original.with_suffix(original.suffix+'.json')
                if not side_path.exists():
                    float_io._exclusive_write(side_path,float_io.canonical_manifest_bytes(original_side))
                raw,_=await asyncio.to_thread(float_io.read_exr,original)
                await asyncio.to_thread(float_io.write_exr,tagged,raw,colour=upload_colour,
                                        storage='float32',alpha_association='straight')
                decoded,_=await asyncio.to_thread(float_io.read_exr,tagged)
                if not np.array_equal(decoded.view('<u4'),raw.view('<u4')):
                    raise ValueError('The colour-tagged EXR changed the actual AE FLOAT pixels')
                result=await self.native_import(session,folder,manifest,existing_exr=tagged)
                if colour.get('management')=='icc':
                    mapped=result['studioAsset'].get('nativeInputColour')
                    if (not isinstance(mapped,dict) or mapped.get('encoding')!='scene_linear_rec709'
                            or result['studioAsset'].get('resolved_colour')!='linear_rec709'):
                        raise ValueError('The linear ICC EXR was registered with a different colour interpretation')
                    result['nativeInputColour']=mapped;result['resolved_colour']='linear_rec709'
                if processing is not None:
                    result['processingInput']=await self.importer(session,folder,manifest) if self.importer else await self.native_import(session,folder,manifest,retain_source=False)
                return result
            except BaseException:
                with float_io._locked_parents(folder):shutil.rmtree(tagged_dir,ignore_errors=True)
                raise
        model_pixels=await asyncio.to_thread(self.verify_native_still,original,
            folder/manifest['frames'][0]['filename'],manifest,descriptor['profile'])
        generated=folder/('native-'+secrets.token_hex(16)) if descriptor['profile']=='png16' else None
        if generated:
            with float_io._locked_parents(folder):generated.mkdir()
        model=generated/'model-8bit.png' if generated else original
        try:
            if generated:await asyncio.to_thread(lambda:Image.fromarray(model_pixels,'RGBA').save(model))
            async def upload(path):
                self.active(session)
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
                form=aiohttp.FormData()
                with path.open('rb') as stream:
                    form.add_field('file',stream,filename=path.name,content_type='image/png')
                    timeout=min(1800,180+path.stat().st_size/(16*1024**2))
                    async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(
                            total=timeout,connect=3,sock_read=180)) as client:
                        async with client.post(session.origin+'/zura/studio/upload?kind=image',data=form,
                                               headers={'Origin':session.origin},allow_redirects=False) as response:
                            if response.status!=200:raise ValueError('Native AE still upload unavailable')
                            asset=await _bounded_json(response.content)
                if (not isinstance(asset,dict) or asset.get('sha')!=digest or asset.get('asset_kind')!='image'
                        or not _HEX32.fullmatch(str(asset.get('id','')))):
                    raise ValueError('Studio registered different AE still bytes')
                return asset
            original_asset=await upload(original)
            model_asset=await upload(model) if generated else original_asset
            describe_media=import_module('..paintout.browser',__package__).describe_media
            info=await asyncio.to_thread(describe_media,str(model.absolute()))
            if (info.get('kind'),info.get('frames'),info.get('width'),info.get('height'))!=(
                    'image',1,manifest['width'],manifest['height']):
                raise ValueError('Studio model image changed the AE source raster')
            input_root,_=self.roots()
            def still(path):
                relative=path.relative_to(Path(input_root).absolute())
                return {'filename':path.name,'subfolder':relative.parent.as_posix(),'file':relative.as_posix(),
                        'type':'input','width':manifest['width'],'height':manifest['height']}
            return {'studioAsset':original_asset,'stills':{'first':still(original),'last':still(original)},
                    'processingInput':{'studioAsset':model_asset,'mediaInfo':info,
                                       'stills':{'first':still(model),'last':still(model)}}}
        except BaseException:
            if generated:
                with float_io._locked_parents(folder):shutil.rmtree(generated,ignore_errors=True)
            raise

    async def native_import(self, session, folder, manifest, *, existing_exr=None, retain_source=True):
        """Use Studio's existing upload API; never manufacture asset records.

        Raw float authority is retained even when optional EXR support is absent.
        Eight-bit source pixels may also be encoded losslessly for SDR controls.
        An explicit broker-authorised SDR copy may quantise verified display
        values. Higher-depth source manifests are never relabelled or changed.
        """
        import numpy as np
        input_root, _ = self.roots()
        relative_manifest = "ComfyLink/" + session.id + "/manifest.json"
        count = len(manifest["frames"])
        from .studio_processing import validate_processing_input, encode_sdr8, model_input_processor
        processing_path = folder / "processing-input.json"
        processing = validate_processing_input(json.loads(float_io._read_private(processing_path, 32768)), manifest) if processing_path.exists() else None
        processor = model_input_processor(processing)
        retain_native = bool(retain_source and existing_exr is None and processing and (processing['conversion'] == 'verified_ocio_to_sdr8' or processing['conversion'] in {'verified_icc_to_sdr8', 'verified_icc_numeric_to_sdr8'} and session.context.get('transferPrecision') == 'float32'))
        generated = folder / ("native-" + secrets.token_hex(16))
        if existing_exr is None:
            with float_io._locked_parents(folder):
                generated.mkdir()
        is_sdr8 = existing_exr is None and (bool(processing) or (manifest["sourceBitDepth"] == 8 and manifest["colour"]["encoding"] == "unknown"
                   and manifest["colour"]["sceneLinear"] is False and manifest["alphaAssociation"] == "straight"))
        native_colour=None
        native_encoding_colour=manifest['colour']
        if (not is_sdr8 or retain_native) and manifest['colour'].get('management')=='icc':
            from .studio_processing import verified_linear_srgb_icc
            verified_linear_srgb_icc(float_io._read_private(folder/'source.icc',4*1024*1024))
            native_encoding_colour={'encoding':'scene_linear_rec709','sceneLinear':True}
            native_colour={'encoding':'scene_linear_rec709','sceneLinear':True,'source':'declared_exr',
                'sourceColourSha256':hashlib.sha256(float_io.canonical_manifest_bytes(native_encoding_colour)).hexdigest()}
        if (not is_sdr8 or retain_native) and manifest['colour'].get('management')=='ocio':
            from .display_view import _verified_ocio_source
            encoding=_verified_ocio_source(manifest['colour'])
            if encoding not in {'acescg','acescct','scene_linear_rec709'}:
                raise ValueError('The verified AE working space is not a supported native HDR input.')
            native_colour={'encoding':encoding,'sceneLinear':encoding!='acescct','source':'verified_ae_ocio',
                'sourceColourSha256':hashlib.sha256(float_io.canonical_manifest_bytes(manifest['colour'])).hexdigest(),
                'ocioConfigFileSha256':manifest['colour']['ocioConfigFileSha256']}
        async def upload(paths, endpoint):
            self.active(session)
            form = aiohttp.FormData()
            streams = []
            try:
                for path in paths:
                    stream = path.open("rb")
                    streams.append(stream)
                    form.add_field("frames" if len(paths) > 1 or endpoint.endswith("exr-sequence") else "file",
                                   stream, filename=path.name, content_type="application/octet-stream")
                # Scoped native upload can be a complete 16 GiB shot. JSON and
                # capability probes retain their separate short deadlines.
                timeout = min(1800, 180 + sum(path.stat().st_size for path in paths) / (16 * 1024**2))
                async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=timeout, connect=3, sock_read=180)) as client:
                    async with client.post(session.origin + endpoint, data=form, headers={"Origin": session.origin}, allow_redirects=False) as response:
                        if response.status != 200:
                            raise ValueError("Native Studio upload unavailable")
                        asset = await _bounded_json(response.content)
                        self.active(session)
                        return asset
            finally:
                for stream in streams:
                    stream.close()

        def encode(native=False):
            if existing_exr is not None:return [existing_exr],None,None
            if is_sdr8 and not native:
                from PIL import Image
                from fractions import Fraction
                # Quantisation requires separate broker authority; unconverted
                # eight-bit inputs still need exact representable sample levels.
                def encode_eight(rgba):
                    return encode_sdr8(rgba, derived=bool(processing), processor=processor)
                first = generated / "first.png"
                last = first
                if count > 1:
                    last = generated / "last.png"
                    import av
                    video = generated / "source.mkv"
                    rate = Fraction(manifest["frameRate"]["numerator"], manifest["frameRate"]["denominator"])
                    with av.open(str(video), "w") as container:
                        stream = container.add_stream("ffv1", rate=rate)
                        stream.width, stream.height, stream.pix_fmt = manifest["width"], manifest["height"], "bgra"
                        # Declare actual RGB packing and full numeric range,
                        # not an inferred transfer function or colour gamut.
                        stream.codec_context.colorspace = 0
                        stream.codec_context.color_range = 2
                        if processing and processing['conversion'] == 'raw_numeric_to_sdr8':
                            # Define the explicitly chosen SDR8 copy's code-value
                            # interpretation. This is not a source conversion:
                            # encode_eight still receives no colour processor.
                            stream.codec_context.color_trc = 13
                            stream.codec_context.color_primaries = 1
                        for index, rgba in enumerate(float_io.iter_transfer(input_root, relative_manifest)):
                            self.active(session)
                            encoded = encode_eight(rgba)
                            if index == 0:
                                Image.fromarray(encoded, "RGBA").save(first)
                            if index == count - 1:
                                Image.fromarray(encoded, "RGBA").save(last)
                            frame = av.VideoFrame.from_ndarray(encoded, format="rgba")
                            frame.pts, frame.time_base = index, 1 / rate
                            for packet in stream.encode(frame):
                                container.mux(packet)
                        for packet in stream.encode():
                            container.mux(packet)
                    return [video], first, last
                rgba = next(float_io.iter_transfer(input_root, relative_manifest))
                Image.fromarray(encode_eight(rgba), "RGBA").save(first)
                return [first], first, last
            paths = []
            for index, rgba in enumerate(float_io.iter_transfer(input_root, relative_manifest)):
                self.active(session)
                if manifest["width"] * manifest["height"] * 16 * count > float_io.LEGACY_BATCH_BYTES:
                    self.check_stream_memory(rgba.nbytes)
                path = generated / (f"{index + 1:06d}.exr")
                float_io.write_exr(path, rgba, colour=native_encoding_colour, storage="float32",
                                   alpha_association=manifest["alphaAssociation"])
                paths.append(path)
            return paths, None, None

        paths, first, last = await asyncio.to_thread(encode)
        self.active(session)
        asset = await upload(paths, "/zura/studio/upload?kind=" + ("video" if count > 1 else "image")
                             if is_sdr8 else "/zura/studio/hdr/exr-sequence")
        if is_sdr8 and count > 1 and asset.get('preview_file'):
            # Use the same registered browser-preview path as an ordinary
            # uploaded editing codec. Never substitute that display-only
            # derivative for the lossless source used by a model or editor.
            original_identity = (asset.get('id'), asset.get('file'), asset.get('sha'))
            if not _HEX32.fullmatch(str(asset.get('id', ''))):
                raise ValueError('Normal playback preview has no registered asset identity')
            deadline = time.monotonic() + min(1800, 180 + sum(path.stat().st_size for path in paths) / (16 * 1024**2))
            while asset.get('preview_status') != 'ready':
                self.active(session)
                if asset.get('preview_status') == 'error' or time.monotonic() >= deadline:
                    raise ValueError('The normal playback preview could not be prepared; lossless source retained')
                await asyncio.sleep(.1)
                endpoint = session.origin + '/zura/studio/assets/' + str(asset.get('id', '')) + '/preview'
                async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=30, connect=3)) as client:
                    async with client.get(endpoint, headers={'Origin': session.origin}, allow_redirects=False) as response:
                        if response.status != 200:
                            raise ValueError('Normal playback preview status is unavailable')
                        refreshed = await _bounded_json(response.content)
                if (refreshed.get('id'), refreshed.get('file'), refreshed.get('sha')) != original_identity:
                    raise ValueError('Playback preview changed the registered processing asset')
                asset = refreshed
            preview_url = asset.get('preview_url')
            if not isinstance(preview_url, str) or not preview_url.startswith('/') or preview_url.startswith('//'):
                raise ValueError('Normal playback preview has no local display URL')
            self.active(session)
        result = {"studioAsset": asset}
        if native_colour is not None and not retain_native:
            expected_space={'scene_linear_rec709':'linear_rec709'}.get(native_colour['encoding'],native_colour['encoding'])
            if asset.get('nativeInputColour')!=native_colour or asset.get('resolved_colour')!=expected_space:
                raise ValueError('The uploaded EXR colour mapping differs from the captured AE identity.')
            result.update(nativeInputColour=native_colour,resolved_colour=expected_space)
        if first:
            stills = {}
            for key, path in (("first", first), ("last", last)):
                relative = path.relative_to(input_root.absolute())
                stills[key] = {"filename": relative.name, "subfolder": relative.parent.as_posix(),
                               "file": relative.as_posix(), "type": "input", "width": manifest["width"], "height": manifest["height"]}
            result["stills"] = stills
        raw_numeric_video = bool(processing and processing['conversion'] == 'raw_numeric_to_sdr8' and count > 1)
        try:
            if is_sdr8 and count > 1 and _HEX32.fullmatch(str(asset.get("id", ""))):
                endpoint = session.origin + "/zura/studio/assets/" + asset["id"] + "/ripple"
                async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=30, connect=3)) as client:
                    async with client.post(endpoint, json={}, headers={"Origin": session.origin}, allow_redirects=False) as response:
                        if response.status == 200:
                            result["mediaInfo"] = await _bounded_json(response.content)
            else:
                # The native inspection function is called directly so absolute
                # media paths cannot appear in HTTP access logs or URLs.
                if __package__ and "." in __package__:
                    from importlib import import_module
                    describe_media = import_module("..paintout.browser", __package__).describe_media
                    result["mediaInfo"] = await asyncio.to_thread(describe_media,
                        str((first if first else paths[0].parent).absolute()))
        except Exception as error:
            if raw_numeric_video:
                raise ValueError('The normal eight-bit clip could not be inspected; the FLOAT source is retained') from error
        if is_sdr8 and count > 1 and asset.get('preview_status') == 'ready' and asset.get('preview_url') and 'mediaInfo' in result:
            # Paintout/camera read path from the lossless original, while their
            # ordinary HTML video element plays the registered browser copy.
            result['mediaInfo']['media_url'] = asset['preview_url']
        if raw_numeric_video:
            _require_raw_numeric_video_info(asset, result.get('mediaInfo'), manifest, input_root)
        if native_colour is not None and not retain_native and 'mediaInfo' in result:
            result['mediaInfo'].pop('colour_error',None)
            result['mediaInfo'].update(nativeInputColour=native_colour,resolved_colour=expected_space)
        if retain_native:
            # HDR modes consume the original EXR asset. Ordinary models consume
            # the independently prepared SDR asset above; neither replaces the
            # retained FLOAT frames or their captured colour identity.
            native_paths, _, _ = await asyncio.to_thread(encode, True)
            self.active(session)
            native_asset = await upload(native_paths, '/zura/studio/hdr/exr-sequence')
            expected_space = {'scene_linear_rec709': 'linear_rec709'}.get(native_colour['encoding'], native_colour['encoding'])
            if native_asset.get('nativeInputColour') != native_colour or native_asset.get('resolved_colour') != expected_space:
                raise ValueError('The original EXR colour mapping differs from the captured AE identity.')
            result = {'studioAsset': native_asset, 'nativeInputColour': native_colour,
                      'resolved_colour': expected_space, 'processingInput': result}
            def native_ref(path):
                relative=path.relative_to(input_root.absolute())
                return {'filename':path.name,'subfolder':relative.parent.as_posix(),'file':relative.as_posix(),'type':'input','width':manifest['width'],'height':manifest['height']}
            result['stills']={'first':native_ref(native_paths[0]),'last':native_ref(native_paths[-1])}
        if existing_exr is not None and not is_sdr8:
            relative=existing_exr.relative_to(input_root.absolute())
            frame={'filename':existing_exr.name,'subfolder':relative.parent.as_posix(),'file':relative.as_posix(),'type':'input','width':manifest['width'],'height':manifest['height']}
            result['stills']={'first':frame,'last':frame}
        # Media-specific descriptors are obtained from the native API itself;
        # no fabricated duration or fake playable asset is returned.
        return result

    def resolve_master(self, ref):
        if not isinstance(ref, dict) or set(ref) - {"filename", "subfolder", "type", "format"} or ref.get("type") != "output":
            raise ValueError("Select an explicit Comfy output master")
        filename, subfolder = ref.get("filename"), ref.get("subfolder", "")
        if (not isinstance(filename, str) or not filename or len(filename) > 255 or any(c in filename for c in '/\\:\x00')
                or filename in (".", "..") or not isinstance(subfolder, str) or "\\" in subfolder or ":" in subfolder
                or subfolder.startswith("/") or any(p in (".", "..") for p in subfolder.split("/") if p)):
            raise ValueError("Invalid output master reference")
        # Guide edits are useful inputs to a later video run, never a final AE
        # result. The preparation endpoint owns this reserved output namespace.
        if tuple(part.casefold() for part in subfolder.split('/') if part)[:2] == ('comfylink', 'intermediate'):
            raise ValueError("Return this edited guide to its video workspace before sending the completed shot to AE")
        _, output_root = self.roots()
        root = output_root.absolute()
        path = root / subfolder / filename
        if not path.absolute().is_relative_to(root):
            raise ValueError("Output master is outside this Comfy instance")
        with float_io._locked_parents(path.parent):
            float_io._safe_stat(path)
        return path

    def prepare_result(self, session, body, *, source_manifest=None):
        if body.get('kind') == 'native_video':
            return self.prepare_direct_video_result(session, body, source_manifest=source_manifest)
        if set(body) - {"kind", "master", "preview", "original", "colour", "alpha", "width", "height", "frameCount", "fps", "precision"}:
            raise ValueError("Unsupported result descriptor fields")
        if not isinstance(body.get("kind", "float_sequence"), str) or body.get("kind", "float_sequence") not in {"image", "video", "float_sequence", "float_manifest", "hdr_sequence", "sequence", "alpha_extract"}:
            raise ValueError("Unsupported result kind")
        alpha_extract = body.get('kind') == 'alpha_extract'
        if 'original' in body and not alpha_extract:
            raise ValueError('An explicit original is only supported for source-bound alpha')
        for name in ("width", "height", "frameCount"):
            if name in body and (type(body[name]) is not int or body[name] < 1):
                raise ValueError("Invalid result dimensions or frame count")
        if "fps" in body and (type(body["fps"]) not in {int, float} or not math.isfinite(body["fps"]) or not 0 < body["fps"] <= 1000):
            raise ValueError("Invalid result frame rate")
        selected = body.get("master")
        if isinstance(selected, list):
            if body.get("kind") not in {"hdr_sequence", "sequence"} or not 1 <= len(selected) <= float_io.MAX_FRAMES or "fps" not in body:
                raise ValueError("An EXR master sequence needs explicit ordered frames and frame rate")
            originals = [self.resolve_master(ref) for ref in selected]
            if any(path.suffix.lower() != ".exr" for path in originals) or len({os.path.normcase(str(path)) for path in originals}) != len(originals):
                raise ValueError("Master sequence must contain unique explicit EXR frames")
            path = None
        else:
            path = self.resolve_master(selected)
            originals = [] if path.name == "manifest.json" else [path]
            if alpha_extract:
                original = self.resolve_master(body.get('original'))
                if path.name != 'manifest.json' or original.suffix.lower() != '.mov':
                    raise ValueError('AE alpha needs its FLOAT manifest and retained MOV')
                originals = [original]
        _, root = self.roots()
        original_records, original_descriptors, total = [], [], 0
        for index, original in enumerate(originals):
            if original.suffix.lower() not in _ORIGINAL_TYPES:
                raise ValueError("Unsupported original master media type")
            record = _file_record(original, MAX_ORIGINAL_BYTES)
            total += record[2]["byteLength"]
            if total > MAX_ORIGINAL_BYTES:
                raise ValueError("Original master containers exceed aggregate byte limit")
            original_records.append(record)
            original_descriptors.append({"index": index, **record[2], "mediaType": _ORIGINAL_TYPES[original.suffix.lower()]})
        provenance = None
        if path is None:
            path, storages = self.convert_exr_sequence(originals, body)
            for descriptor, storage in zip(original_descriptors, storages):
                descriptor["storage"] = storage
        elif originals and path.suffix.lower() == ".zip":
            path = self.convert_zip_master(session, path, body)
        elif originals and not alpha_extract:
            frame_rate = None
            if path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.exr'}:
                from fractions import Fraction
                source = float_io.validate_manifest(source_manifest or session.source.get('manifest'))
                frame_rate = Fraction(source['frameRate']['numerator'], source['frameRate']['denominator'])
            path, storage, provenance = self.convert_master(path, body, frame_rate=frame_rate, source_manifest=source if frame_rate is not None else None)
            if storage is not None:
                original_descriptors[0]["storage"] = storage
        relative = path.relative_to(root.absolute()).as_posix()
        manifest = float_io.verify_transfer(root, relative)
        if alpha_extract:
            source = float_io.validate_manifest(source_manifest or session.source.get('manifest'))
            if (manifest['sampleType'] != 'float32' or manifest['sourceBitDepth'] != 32
                    or manifest['alphaAssociation'] != 'straight'
                    or any(manifest.get(key) != source.get(key) for key in ('width', 'height', 'frameRate', 'colour', 'sourceStart'))
                    or len(manifest['frames']) != len(source['frames'])):
                raise ValueError('The alpha FLOAT master differs from its original AE source')
            provenance = {'schemaVersion': 1, 'kind': 'source_alpha_float32',
                'sourceManifestSha256': hashlib.sha256(float_io.canonical_manifest_bytes(source)).hexdigest(),
                'alphaOperation': 'multiply'}
        for field_name, actual in (("width", manifest["width"]), ("height", manifest["height"]),
                                   ("frameCount", len(manifest["frames"])), ("colour", manifest["colour"]),
                                   ("alpha", manifest["alphaAssociation"])):
            declared = body.get(field_name)
            if field_name == 'colour' and provenance and provenance.get('kind') == 'sdr32_image' and declared == {'encoding':'srgb_display','sceneLinear':False}:
                declared = {'encoding':'unknown','sceneLinear':False}
            if field_name in body and declared != actual:
                raise ValueError("Result declaration does not match actual master")
        rate = manifest["frameRate"]["numerator"] / manifest["frameRate"]["denominator"]
        if "fps" in body and body["fps"] != rate:
            raise ValueError("Result frame rate does not match actual master")
        # A browser-provided precision label can never change pixel storage.
        if "precision" in body and body["precision"] not in ({"sampleType": manifest["sampleType"], "sourceBitDepth": manifest["sourceBitDepth"]}, manifest["sourceBitDepth"]):
            raise ValueError("Result precision does not match actual master")
        for original, stamp, metadata in original_records:
            verified = _file_record(original, MAX_ORIGINAL_BYTES, metadata)
            if verified[1] != stamp:
                raise ValueError("Original master changed during conversion")
        files = []
        records = []
        for index, frame in enumerate(manifest["frames"]):
            source = path.parent / frame["filename"]
            files.append({"index": index, **{key: frame[key] for key in ("filename", "byteLength", "sha256")}})
            records.append(_file_record(source, frame["byteLength"], frame))
        session.result_files = records
        session.original_files = original_records
        session.download_capability = secrets.token_hex(32)
        return {"schemaVersion": 1, "instanceId": self.instance_id, "adapterSessionId": session.id,
                "downloadCapability": session.download_capability, "kind": body.get("kind", "float_sequence"),
                "master": {"filename": "manifest.json", "subfolder": path.parent.relative_to(root.absolute()).as_posix(), "type": "output"},
                "manifest": manifest, "files": files,
                **({"originals": original_descriptors} if original_descriptors else {}),
                **({"provenance": {**provenance, "originalSha256": original_descriptors[0]["sha256"]}} if provenance else {}),
                "colour": manifest["colour"], "alpha": manifest["alphaAssociation"],
                "width": manifest["width"], "height": manifest["height"], "frameCount": len(files),
                "fps": manifest["frameRate"]["numerator"] / manifest["frameRate"]["denominator"]}

    def prepare_direct_video_result(self, session, body, *, source_manifest=None):
        """Publish the selected physical master without decoding into transfer frames."""
        if session.context['capabilities'].get('nativeVideoReturn') is not True:
            raise ValueError('Native video return is not available for this AE session')
        if set(body) - {'kind', 'master'}:
            raise ValueError('Native return takes only a selected output master')
        path = self.resolve_master(body.get('master'))
        source_video = session.source.get('sourceTransfer')
        if isinstance(source_video, dict) and source_video.get('kind') == 'native_video':
            source = source_video
            source_hash = source['file']['sha256']
            width, height, count, rate = source['width'], source['height'], source['frameCount'], source['frameRate']
        else:
            source = float_io.validate_manifest(source_manifest or session.source.get('manifest'))
            source_hash = hashlib.sha256(float_io.canonical_manifest_bytes(source)).hexdigest()
            width, height, count, rate = source['width'], source['height'], len(source['frames']), source['frameRate']
        from .studio_direct_video import inspect_video_master, prepare_video_delivery
        precision = session.context.get('transferPrecision')
        if precision in {'sdr8', 'prores12'}:
            _, output_root = self.roots()
            path = prepare_video_delivery(path, output_root, precision=precision, width=width, height=height,
                                          frame_count=count, frame_rate=rate)
        first = _file_record(path, MAX_ORIGINAL_BYTES)
        video = inspect_video_master(path, width=width, height=height, frame_count=count, frame_rate=rate)
        if _file_record(path, MAX_ORIGINAL_BYTES, first[2])[1] != first[1]:
            raise ValueError('Native video master changed during inspection')
        session.result_files = [first]
        session.original_files = []
        session.download_capability = secrets.token_hex(32)
        _, root = self.roots()
        subfolder = path.parent.relative_to(root.absolute()).as_posix()
        return {'schemaVersion': 2, 'instanceId': self.instance_id, 'adapterSessionId': session.id,
                'downloadCapability': session.download_capability, 'kind': 'native_video',
                'master': {'filename': path.name, 'subfolder': '' if subfolder == '.' else subfolder, 'type': 'output'},
                'sourceSha256': source_hash, 'video': {**first[2], **video}}

    def convert_master(self, path, body, *, frame_rate=None, source_manifest=None):
        """Decode a declared master and publish a separate verified float transfer.

        Only actual eight-bit SDR images/video enter the SDR decoder. A high
        depth EXR requires float_io's metadata, storage and finite-pixel checks.
        Native HDR videos without a verified float export remain pending.
        """
        import numpy as np
        from fractions import Fraction
        suffix = path.suffix.lower()
        # A still inherits the authenticated AE timeline's rational cadence.
        # A browser label cannot replace it with a rounded decimal or 24 fps.
        rate = frame_rate
        colour = {"encoding": "unknown", "sceneLinear": False}
        alpha, depth, storage, provenance = "straight", 8, None, None
        with float_io._locked_parents(path.parent):
            state = float_io._safe_stat(path)
            if state.st_size > float_io.MAX_TRANSFER_BYTES:
                raise ValueError("Output master exceeds transfer limit")
            if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                from PIL import Image
                transfer = _image_container(path, suffix)
                with Image.open(path) as image:
                    expected = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}[suffix]
                    if image.format != expected or image.width * image.height > float_io.MAX_PIXELS or image.mode not in {"RGB", "RGBA", "P", "L", "LA"} or getattr(image, "n_frames", 1) != 1:
                        raise ValueError("Unsupported master image dimensions, depth or frame count")
                    _unmanaged_metadata(image.info)
                    pixels = np.array(image.convert("RGBA"), dtype=np.float32)[None] / np.float32(255)
                    _unmanaged_metadata(image.info)
                provenance = {"schemaVersion": 1, "kind": "sdr8_image", "sourceBitDepth": 8,
                              "embeddedICC": False, "hdrMetadata": False, "transfer": transfer,
                              "primaries": "bt709" if transfer == "srgb" else "unspecified", "validatedFrameCount": 1}
            elif suffix == ".exr":
                _, output_root = self.roots()
                relative = path.relative_to(output_root.absolute())
                product = len(relative.parts) >= 2 and relative.parts[:2] == ('ZURA STUDIO','image-layers')
                if product:
                    source = float_io.validate_manifest(source_manifest)
                    pixels, side = float_io.read_image_layer_exr(path, output_root)
                    if len(source['frames']) != 1 or (source['width'],source['height']) != (pixels.shape[1],pixels.shape[0]):
                        raise ValueError('Use original image dimensions to return one frame to AE')
                    if body.get('colour') != {'encoding':'srgb_display','sceneLinear':False}:
                        raise ValueError('The image-layer colour declaration differs from its verified master')
                    provenance = {'schemaVersion':1,'kind':'sdr32_image','sourceBitDepth':32,'embeddedICC':False,'hdrMetadata':False,
                                  'transfer':'srgb','primaries':'bt709','validatedFrameCount':1,
                                  'sourceManifestSha256':hashlib.sha256(float_io.canonical_manifest_bytes(source)).hexdigest(),
                                  'receiptSha256':side['receiptSha256'],'sourceImageSha256':side['sourceImageSha256'],'productReceipt':side['productReceipt']}
                else:
                    pixels, side = float_io.read_exr(path)
                pixels = pixels[None]
                colour, alpha, depth = side["colour"], side["alphaAssociation"], 32
                storage = side["storage"]
            elif suffix in {".mp4", ".mov", ".mkv", ".webm"}:
                import av
                with av.open(str(path)) as media:
                    _unmanaged_metadata(media.metadata)
                    iso = suffix in {".mp4", ".mov"}
                    if (iso and "mov" not in media.format.name
                            or not iso and "matroska" not in media.format.name and "webm" not in media.format.name):
                        raise ValueError("Video container does not match selected master media type")
                    if any(stream.type not in {"video", "audio"} for stream in media.streams):
                        raise ValueError("Video attachments or data streams cannot be proven unmanaged SDR")
                    if iso:
                        _iso_bmff_sdr_container(path)
                    if len(media.streams.video) != 1:
                        raise ValueError("Select one master video stream")
                    stream = media.streams.video[0]
                    context = stream.codec_context
                    if context.format and context.format.name == "yuv420p10le":
                        from .sdr10_video import decode_sdr10
                        with decode_sdr10(path) as (rate10, frames10):
                            _, output_root = self.roots()
                            relative, wire = float_io.write_transfer_frames(output_root, "ComfyLink/" + secrets.token_hex(16), frames10,
                                colour=colour, frame_rate={"numerator": rate10.numerator, "denominator": rate10.denominator},
                                source_bit_depth=32, alpha_association="straight")
                        if _stamp(float_io._safe_stat(path)) != _stamp(state): raise ValueError("Master changed during validation")
                        provenance = {"schemaVersion":1, "kind":"sdr10_video", "sourceBitDepth":10,
                            "embeddedICC":False, "hdrMetadata":False, "transfer":"srgb", "primaries":"bt709",
                            "matrix":"bt709", "range":"limited", "validatedFrameCount":len(wire["frames"])}
                        return output_root.absolute() / relative, None, provenance
                    _video_sdr_metadata(context)
                    _unmanaged_metadata(stream.metadata)
                    if getattr(stream, "side_data", ()):
                        raise ValueError("Unsupported video stream side metadata")
                    rate = stream.average_rate
                    if rate is None or rate <= 0:
                        raise ValueError("Unknown master video frame rate")
                    if "colour" in body and body["colour"] != colour:
                        raise ValueError("An SDR master cannot be labelled as HDR or scene linear")
                    actual_colour = None
                    def decoded_frames():
                        nonlocal actual_colour
                        for frame in media.decode(video=0):
                            current_stream_colour = _video_sdr_metadata(context)
                            frame_colour = _video_sdr_metadata(frame, current_stream_colour)
                            if actual_colour is not None and frame_colour != actual_colour:
                                raise ValueError("Video colour metadata changes between frames")
                            actual_colour = frame_colour
                            if frame.width * frame.height > float_io.MAX_PIXELS:
                                raise ValueError("Master video dimensions exceed limit")
                            yield frame.to_ndarray(format="rgba").astype(np.float32) / np.float32(255)
                    _, output_root = self.roots()
                    relative, wire = float_io.write_transfer_frames(output_root, "ComfyLink/" + secrets.token_hex(16), decoded_frames(),
                        colour=colour, frame_rate={"numerator": rate.numerator, "denominator": rate.denominator},
                        source_bit_depth=8, alpha_association="straight")
                    provenance = {"schemaVersion": 1, "kind": "sdr8_video", "sourceBitDepth": 8,
                                  "embeddedICC": False, "hdrMetadata": False, "transfer": _SDR_TRANSFERS[actual_colour[0]],
                                  "primaries": _SDR_PRIMARIES[actual_colour[1]], "validatedFrameCount": len(wire["frames"])}
                if _stamp(float_io._safe_stat(path)) != _stamp(state):
                    raise ValueError("Master changed during validation")
                return output_root.absolute() / relative, None, provenance
            else:
                raise ValueError("Unsupported master format; retain pending")
            if not isinstance(rate, Fraction) or rate <= 0:
                raise ValueError("A still master needs its authenticated AE source frame rate")
            actual = float_io._safe_stat(path)
            if (actual.st_dev, actual.st_ino, actual.st_size, actual.st_mtime_ns) != (state.st_dev, state.st_ino, state.st_size, state.st_mtime_ns):
                raise ValueError("Master changed during validation")
        if depth == 8 and "colour" in body and body["colour"] != colour:
            raise ValueError("An SDR master cannot be labelled as HDR or scene linear")
        _, output_root = self.roots()
        relative, _ = float_io.write_transfer(output_root, "ComfyLink/" + secrets.token_hex(16), pixels,
                                              colour=colour, frame_rate={"numerator": rate.numerator, "denominator": rate.denominator},
                                              source_bit_depth=depth, alpha_association=alpha)
        return output_root.absolute() / relative, storage, provenance

    def convert_exr_sequence(self, paths, body, *, native_records=None, frame_rate=None, rgba_master=False, alpha_hashes=None):
        """Convert only explicitly selected, verified EXRs, preserving originals."""
        import numpy as np
        from fractions import Fraction
        def read(path):
            if native_records is None:
                return float_io.read_exr(path)
            pixels, side = self.native_archive_frame(path, native_records[path], rgba_master=rgba_master)
            if rgba_master and hashlib.sha256(np.ascontiguousarray(pixels[:, :, 3], dtype="<f4").tobytes()).hexdigest() != alpha_hashes[path]:
                raise ValueError("Native HDR alpha differs from its archive proof")
            return pixels, side
        first, side = read(paths[0])
        contract = (first.shape, side["colour"], side["alphaAssociation"])
        storages = [side["storage"]]
        def frames():
            yield first
            for path in paths[1:]:
                pixels, current = read(path)
                if contract != (pixels.shape, current["colour"], current["alphaAssociation"]):
                    raise ValueError("EXR master sequence shape, colour or alpha differs")
                storages.append(current["storage"])
                yield pixels
        rate = frame_rate if frame_rate is not None else Fraction(str(body["fps"]))
        _, root = self.roots()
        relative, _ = float_io.write_transfer_frames(root, "ComfyLink/" + secrets.token_hex(16), frames(),
            colour=contract[1], frame_rate={"numerator": rate.numerator, "denominator": rate.denominator},
            source_bit_depth=32, alpha_association=contract[2], expected_count=len(paths))
        return root.absolute() / relative, storages

    def native_archive_frame(self, path, expected, *, rgba_master=False):
        """Read a Studio-validated RGB AP1 frame without colour/range changes."""
        import numpy as np
        import OpenImageIO as oiio
        record = _file_record(path, float_io.MAX_TRANSFER_BYTES, expected)
        with float_io._locked_parents(path.parent):
            config = oiio.ImageSpec()
            if rgba_master: config.attribute("oiio:UnassociatedAlpha", 1)
            reader = oiio.ImageInput.open(str(path), config)
            if reader is None:
                raise ValueError("Unreadable native EXR frame")
            try:
                spec = reader.spec()
                storage = "float32" if spec.format == oiio.FLOAT else "half" if spec.format == oiio.HALF else None
                if (storage is None or spec.deep or spec.depth != 1 or spec.nchannels != (4 if rgba_master else 3)
                        or set(spec.channelnames) != ({"R", "G", "B", "A"} if rgba_master else {"R", "G", "B"})
                        or (rgba_master and (storage != "float32" or spec.get_string_attribute("comfylink:alphaAssociation") != "straight"
                            or spec.get_string_attribute("comfylink:colour") != '{"encoding":"acescg","sceneLinear":true}')) or not 1 <= spec.width <= float_io.MAX_DIMENSION
                        or not 1 <= spec.height <= float_io.MAX_DIMENSION or spec.width * spec.height > float_io.MAX_PIXELS
                        or any(fmt != spec.format for fmt in spec.channelformats)):
                    raise ValueError("Native EXR raster or storage differs from its archive")
                chroma = spec.getattribute("chromaticities")
                tag = str(spec.getattribute("oiio:ColorSpace") or spec.getattribute("colorSpace") or "").lower()
                ap1 = (.713, .293, .165, .830, .128, .044, .32168, .33767)
                if (chroma is None or len(chroma) != 8 or not all(abs(float(a) - b) < .002 for a, b in zip(chroma, ap1))
                        or tag not in {"acescg", "lin_ap1_scene", "linear", "scene_linear", "scene-linear", "unknown", ""}
                        or any("icc" in attribute.name.lower() or "profile" in attribute.name.lower() for attribute in spec.extra_attribs)):
                    raise ValueError("Actual native EXR colour metadata is not unmanaged scene-linear AP1")
                pixels = reader.read_image(format=oiio.FLOAT)
                if pixels is None or pixels.shape != (spec.height, spec.width, 4 if rgba_master else 3) or not np.isfinite(pixels).all():
                    raise ValueError("Native EXR contains nonfinite or malformed pixels")
                rgb = pixels[:, :, [list(spec.channelnames).index(channel) for channel in "RGB"]]
                rgba = np.concatenate((rgb, pixels[:, :, [list(spec.channelnames).index("A")]] if rgba_master else np.ones((*rgb.shape[:2], 1), dtype=np.float32)), axis=2)
                if rgba_master and (np.any(rgba[:, :, 3] < 0) or np.any(rgba[:, :, 3] > 1)):
                    raise ValueError("Native EXR contains invalid alpha")
            finally:
                reader.close()
        if _file_record(path, float_io.MAX_TRANSFER_BYTES, expected)[1] != record[1]:
            raise ValueError("Native EXR changed during decode")
        return rgba, {"storage": storage, "colour": {"encoding": "acescg", "sceneLinear": True}, "alphaAssociation": "straight"}

    def convert_zip_master(self, session, path, body):
        """Prepare only the native Studio's bounded stored ACEScg EXR ZIP."""
        import OpenImageIO as oiio
        from fractions import Fraction
        from .archive_zip import bounded_stored_archive
        with float_io._locked_parents(path.parent), bounded_stored_archive(path, max_entries=float_io.MAX_FRAMES+1) as archive:
            infos = archive.infolist()
            proof_info = next((i for i in infos if i.filename == "zura_hdr_delivery.json"), None)
            frame_infos = [i for i in infos if i.filename != "zura_hdr_delivery.json"]
            if not 1 <= len(frame_infos) <= float_io.MAX_FRAMES or len(infos) != len(frame_infos) + bool(proof_info):
                raise ValueError("Native archive frame count exceeds bounds")
            names, total = set(), 0
            for info in frame_infos:
                name = info.filename
                kind = (info.external_attr >> 16) & 0o170000
                if (not isinstance(name, str) or not re.fullmatch(r"frame_[0-9]{5}\.exr", name)
                        or name.casefold() in names or info.is_dir() or info.flag_bits & 1
                        or kind not in {0, stat.S_IFREG}
                        or info.compress_type != zipfile.ZIP_STORED or info.compress_size != info.file_size
                        or not 0 < info.file_size <= float_io.MAX_TRANSFER_BYTES):
                    raise ValueError("Archive contains unsafe paths, metadata, links or compressed entries")
                names.add(name.casefold())
                total += info.file_size
                if total > float_io.MAX_TRANSFER_BYTES:
                    raise ValueError("Native archive exceeds aggregate byte bound")
            expected_names = [f"frame_{index:05d}.exr" for index in range(len(frame_infos))]
            if sorted(info.filename for info in frame_infos) != expected_names:
                raise ValueError("Native archive has missing or unordered frame numbers")
            source = float_io.validate_manifest(session.source.get("manifest"))
            rate = Fraction(source["frameRate"]["numerator"], source["frameRate"]["denominator"])
            if "fps" in body and body["fps"] != float(rate):
                rate = Fraction(str(body["fps"]))
            proof = None
            if proof_info is not None:
                if (proof_info.is_dir() or proof_info.flag_bits & 1 or ((proof_info.external_attr >> 16) & 0o170000) not in {0, stat.S_IFREG}
                        or proof_info.compress_type != zipfile.ZIP_STORED or not 1 <= proof_info.file_size <= 4 * 1024 * 1024):
                    raise ValueError("Native HDR proof is invalid")
                with archive.open(proof_info) as stream:
                    raw = stream.read(proof_info.file_size + 1)
                if len(raw) != proof_info.file_size: raise ValueError("Native HDR proof is truncated")
                proof = json.loads(raw.decode("utf-8"), object_pairs_hook=float_io._json_pairs,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite HDR proof")))
                required = {"schemaVersion", "kind", "colour", "alphaAssociation", "width", "height", "frameCount", "frameRate", "alphaSource", "frames"}
                if (not isinstance(proof, dict) or not required <= set(proof) or set(proof) - required - {"sourceStart"}
                        or type(proof["schemaVersion"]) is not int or proof["schemaVersion"] != 1 or proof["kind"] != "rgba_hdr"
                        or proof["colour"] != {"encoding": "acescg", "sceneLinear": True} or proof["colour"].get("sceneLinear") is not True
                        or proof["alphaAssociation"] != "straight" or any(type(proof[k]) is not int or proof[k] < 1 for k in ("width", "height", "frameCount"))
                        or proof["frameCount"] != len(frame_infos) or float_io._rational(proof["frameRate"], "HDR proof frame rate", True) != rate):
                    raise ValueError("Native HDR proof does not match the selected result")
                if "sourceStart" in proof: float_io._rational(proof["sourceStart"], "HDR source start", signed=True)
                origin = proof["alphaSource"]
                if (not isinstance(origin, dict) or set(origin) != {"kind", "sha256"} or origin["kind"] not in {"alpha_float32", "float_manifest", "rgba_image"}
                        or not isinstance(origin["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", origin["sha256"])):
                    raise ValueError("Native HDR alpha provenance is invalid")
                if not isinstance(proof["frames"], list) or len(proof["frames"]) != len(frame_infos): raise ValueError("Native HDR proof count differs")
                for name, item in zip(expected_names, proof["frames"]):
                    if (not isinstance(item, dict) or set(item) != {"filename", "sha256", "alphaSha256"} or item["filename"] != name
                            or any(not isinstance(item[k], str) or not re.fullmatch(r"[a-f0-9]{64}", item[k]) for k in ("sha256", "alphaSha256"))):
                        raise ValueError("Native HDR frame proof is invalid")
            _, root = self.roots()
            parent = root.absolute() / "ComfyLink"
            with float_io._locked_parents(root.absolute()):
                parent.mkdir(exist_ok=True)
            private = parent / secrets.token_hex(16)
            with float_io._locked_parents(parent):
                private.mkdir()
            prepared = private / "prepared-zip"
            prepared.mkdir()
            complete = False
            try:
                records = {}
                with float_io._locked_parents(prepared):
                    for name in expected_names:
                        info = archive.getinfo(name)
                        destination, digest, length = prepared / name, hashlib.sha256(), 0
                        with archive.open(info) as incoming, destination.open("xb") as outgoing:
                            while chunk := incoming.read(1024 * 1024):
                                self.active(session)
                                length += len(chunk)
                                if length > info.file_size:
                                    raise ValueError("Native ZIP entry exceeded its declared bound")
                                outgoing.write(chunk)
                                digest.update(chunk)
                            outgoing.flush()
                            os.fsync(outgoing.fileno())
                        if length != info.file_size:
                            raise ValueError("Native ZIP entry length differs")
                        records[destination] = {"byteLength": length, "sha256": digest.hexdigest()}
                        if proof is not None and records[destination]["sha256"] != proof["frames"][len(records)-1]["sha256"]:
                            raise ValueError("Native HDR frame differs from its proof")
                reader = oiio.ImageInput.open(str(prepared / expected_names[0]))
                if reader is None:
                    raise ValueError("Native archive has no readable first EXR")
                try:
                    spec = reader.spec()
                    width, height = spec.width, spec.height
                    storage = "half" if spec.format == oiio.HALF else "float32" if spec.format == oiio.FLOAT else None
                    if (storage is None or not 1 <= width <= float_io.MAX_DIMENSION or not 1 <= height <= float_io.MAX_DIMENSION
                            or width * height > float_io.MAX_PIXELS or width * height * 16 * len(frame_infos) > float_io.MAX_TRANSFER_BYTES
                            or (proof is not None and (storage != "float32" or (width, height) != (proof["width"], proof["height"])))):
                        raise ValueError("Native archive decoded pixels exceed bounds")
                finally:
                    reader.close()
                # Reuse Studio's actual archive validator. It checks every RGB
                # EXR's storage, AP1 chromaticities, scene-linear colour tags,
                # raster, finite pixels and complete frame numbering.
                if proof is None:
                    _studio_module("ltx25_hdr_result")._check_archive(path, len(frame_infos), width, height, exr_storage=storage)
                self.active(session)
                converted, _ = self.convert_exr_sequence([prepared / name for name in expected_names],
                    {}, native_records=records, frame_rate=rate, rgba_master=proof is not None,
                    alpha_hashes={prepared / item["filename"]: item["alphaSha256"] for item in proof["frames"]} if proof else None)
                complete = True
                return converted
            finally:
                # This directory contains only the temporary EXR extraction;
                # the verified original ZIP and converted transfer are separate.
                with float_io._locked_parents(prepared):
                    for extracted in prepared.iterdir():
                        if extracted.name not in expected_names:
                            raise ValueError("Unexpected file in native ZIP extraction")
                        float_io._safe_stat(extracted)
                        extracted.unlink()
                with float_io._locked_parents(parent):
                    prepared.rmdir()
                    private.rmdir()

    async def result(self, request):
        session = self.authorize(request)
        if not session.context["capabilities"]["transfer"]:
            raise web.HTTPForbidden(text="This session has no result authority")
        body = await _bounded_json(request.content, 65536)
        async with session.lock:
            self.active(session)
            product = isinstance(body.get('master'),dict) and str(body['master'].get('subfolder','')).startswith('ZURA STUDIO/image-layers/')
            if product and session.context['capabilities'].get('sdr32ImageReturn') is not True:
                return web.json_response({'ok':False,'status':'pending','diagnostic':'Update ComfyLink to send float image-layer composites. Your result is retained.'},status=409)
            try:
                source_manifest = session.source.get('manifest')
                master = body.get('master')
                if (source_manifest is None and isinstance(master, dict) and isinstance(master.get('filename'), str)
                        and Path(master['filename']).suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.exr'}):
                    # A restored result can precede source import in this tab.
                    # Read only the broker's source metadata; do not fabricate
                    # a staged source or change the user's Studio workspace.
                    source_data = await self.broker_json(session, '/source')
                    self.active(session)
                    source_manifest = float_io.validate_manifest(source_data.get('manifest', source_data))
                descriptor = await asyncio.to_thread(self.prepare_result, session, body, source_manifest=source_manifest)
            except web.HTTPGone:
                # A restarted broker has lost this scoped authority. Do not
                # misreport its missing source grant as invalid image pixels.
                session.download_capability = ""
                session.result_files.clear()
                session.original_files.clear()
                raise
            except Exception:
                # Decode errors are returned without codec diagnostics, paths
                # or capabilities; the original output is always retained.
                session.download_capability = ""
                session.result_files.clear()
                session.original_files.clear()
                product = isinstance(body.get('master'),dict) and str(body['master'].get('subfolder','')).startswith('ZURA STUDIO/image-layers/')
                diagnostic = ('Image-layer master could not be verified. Recompose the layers after updating and choose original output dimensions before Send to AE. Your result is retained.' if product else
                              'Master validation failed or this format is unsupported. Save a ComfyLink float master; the result is retained.')
                return web.json_response({"ok": False, "status": "pending", "diagnostic":diagnostic}, status=422)
            try:
                self.active(session)
                response = await self.broker_json(session, "/result", descriptor)
                self.active(session)
                # Broker output is untrusted; never echo download capabilities.
                sent = response.get("ok") is True and response.get("status") == "sent"
                pending = response.get("ok") is True and response.get("status") == "import_pending"
                diagnostic = response.get("diagnostic")
                safe_diagnostic = diagnostic if isinstance(diagnostic, str) and diagnostic in _BROKER_DIAGNOSTICS else None
                return web.json_response({"ok": sent or pending,
                                          "status": "sent" if sent else "import_pending" if pending else "pending",
                                          "diagnostic": "Sent to After Effects" if sent else
                                          (safe_diagnostic or "Master transferred; After Effects import is pending") if pending else
                                          (safe_diagnostic or "Broker retained the result pending delivery")},
                                         status=200 if sent else 202 if pending else 422)
            finally:
                session.download_capability = ""
                session.result_files.clear()
                session.original_files.clear()

    async def status(self, request):
        session = self.authorize(request)
        try:
            response = await self.broker_json(session, "/status")
        except web.HTTPGone:
            authority = self.close_local(session)
            if authority is not None:
                await self.revoke_broker(authority)
            if getattr(self, 'work', None) is not None:
                await self.work.cancel(session)
            return web.json_response({'ok': True, 'status': 'cancelled', 'ready': False})
        self.active(session)
        status = response.get("status")
        from .studio_cancel import broker_ended
        if broker_ended(response):
            authority = self.close_local(session)
            if authority is not None:
                await self.revoke_broker(authority)
            if getattr(self, 'work', None) is not None:
                await self.work.cancel(session)
            return web.json_response({'ok': True, 'status': 'cancelled', 'ready': False})
        if not isinstance(status, str) or status not in {"preparing", "ready", "import_pending", "sent"}:
            status = "pending"
        diagnostic = response.get("diagnostic")
        return web.json_response({"ok": True, "status": status, "ready": response.get("ready") is True,
                                  "importPending": response.get("importPending") is True,
                                  **({"diagnostic": diagnostic} if isinstance(diagnostic, str) and diagnostic in _BROKER_DIAGNOSTICS else {})},
                                 headers={"Cache-Control": "no-store"})

    async def prepare_graph(self, request):
        from fractions import Fraction
        from .frame_contract import (normalise_frame_contract, prepare_frame_contract_graph,
                                     prepare_intermediate_image_graph, IMAGE_SAVERS, VIDEO_SAVERS)
        session = self.authorize(request)
        body = await _bounded_json(request.content, 16 * 1024 * 1024)
        try:
            required = {"mode", "graph", "ae_frame_contract"}
            if (set(body) not in (required, required | {"ae_intermediate_image"})
                    or not isinstance(body["mode"], str) or body["mode"] not in _STUDIO_MODES):
                raise ValueError("Choose a supported native Studio mode")
            raw_contract = body["ae_frame_contract"]
            if not isinstance(raw_contract, dict) or type(raw_contract.get("schemaVersion")) is not int:
                raise ValueError("Choose a valid AE frame contract")
            contract = normalise_frame_contract(raw_contract)
            if 'ae_intermediate_image' in contract:
                raise ValueError("Provide the unchanged AE parent source contract")
            manifest = float_io.validate_manifest(session.source.get("manifest"))
            if (contract["sessionId"] != session.id or contract["frameCount"] != len(manifest["frames"])
                    or contract["width"] != manifest["width"] or contract["height"] != manifest["height"]
                    or Fraction(**{"numerator": contract["frameRate"]["numerator"], "denominator": contract["frameRate"]["denominator"]})
                    != Fraction(manifest["frameRate"]["numerator"], manifest["frameRate"]["denominator"])
                    or contract["modelFrames"] > float_io.MAX_FRAMES):
                raise ValueError("AE frame contract differs from this session's stored source")
            graph = body["graph"]
            if not isinstance(graph, dict) or not 1 <= len(graph) <= 10000:
                raise ValueError("Choose a bounded native Studio graph")
            for identity, node in graph.items():
                if (not isinstance(identity, str) or not isinstance(node, dict) or not isinstance(node.get("class_type"), str)
                        or not isinstance(node.get("inputs"), dict)):
                    raise ValueError("Malformed native Studio graph")
                if node["class_type"] in set(IMAGE_SAVERS) | VIDEO_SAVERS | {"ZuraPaintoutUncrop", "ZuraHDRPackageEXR", "ZuraHDRPackageEXRLong"}:
                    for field_name in ("filename_prefix", "prefix", "output_name"):
                        if field_name not in node["inputs"]:
                            continue
                        value = node["inputs"][field_name]
                        if (not isinstance(value, str) or not value or len(value) > 255 or "\\" in value
                                or ":" in value or "\0" in value or value.startswith("/")
                                or any(part in {".", ".."} for part in value.split("/"))):
                            raise ValueError("Native output must stay inside this Comfy output directory")
            self.active(session)
            if 'ae_intermediate_image' in body:
                if body['mode'] != 'image':
                    raise ValueError("Only the Image workspace can prepare an intermediate guide")
                prepared, contract = await asyncio.to_thread(prepare_intermediate_image_graph,
                    graph, contract, body['ae_intermediate_image'])
            else:
                if body['mode'] == 'alpha':
                    contract['sourceManifestSha256'] = hashlib.sha256(float_io.canonical_manifest_bytes(manifest)).hexdigest()
                prepared = await asyncio.to_thread(prepare_frame_contract_graph, graph, contract, body["mode"])
            self.active(session)
            return web.json_response({"graph": prepared, "ae_frame_contract": contract,
                **({'ae_intermediate_image': contract['ae_intermediate_image']} if 'ae_intermediate_image' in contract else {})},
                headers={"Cache-Control": "no-store"})
        except (ValueError, TypeError, KeyError):
            raise web.HTTPUnprocessableEntity(text="Graph preparation requires this active session's exact source interval and a supported native output")

    def download_active(self, request, session):
        self.active(session)
        if not session.download_capability or not _equal(request.headers.get(DOWNLOAD_HEADER), session.download_capability):
            raise web.HTTPForbidden(text="Result download authority has expired")

    async def result_file(self, request):
        session = self.authorize(request, download=True)
        return await self.download_file(request, session, session.result_files)

    async def original_file(self, request):
        session = self.authorize(request, download=True)
        return await self.download_file(request, session, session.original_files)

    async def download_file(self, request, session, records):
        response = None
        try:
            index = int(request.match_info["index"])
            if str(index) != request.match_info["index"] or index < 0:
                raise ValueError()
            path, stamp, frame = records[index]
            verified = await asyncio.to_thread(_file_record, path, frame["byteLength"], frame)
            if verified[1] != stamp:
                raise ValueError("Result object identity changed")
            self.download_active(request, session)
            with float_io._locked_parents(path.parent):
                actual = float_io._safe_stat(path)
                if _stamp(actual) != stamp:
                    raise ValueError("Result object identity changed")
                with path.open("rb") as stream:
                    if _stamp(os.fstat(stream.fileno())) != stamp:
                        raise ValueError("Result object changed before streaming")
                    response = web.StreamResponse(headers={"Content-Type": "application/octet-stream",
                        "Content-Length": str(frame["byteLength"]), "Cache-Control": "no-store",
                        "X-Content-Type-Options": "nosniff"})
                    await response.prepare(request)
                    size, digest, pending = 0, hashlib.sha256(), None
                    while chunk := stream.read(1024 * 1024):
                        self.download_active(request, session)
                        size += len(chunk)
                        if size > frame["byteLength"]:
                            raise ValueError("Result exceeds declared byte bound")
                        digest.update(chunk)
                        if pending is not None:
                            await response.write(pending)
                        pending = chunk
                    # Hold back the final chunk until identity and full SHA are
                    # verified. A failed or revoked stream cannot look complete.
                    if (_stamp(os.fstat(stream.fileno())) != stamp or _stamp(float_io._safe_stat(path)) != stamp
                            or size != frame["byteLength"] or digest.hexdigest() != frame["sha256"]):
                        raise ValueError("Result changed during streaming")
                    self.download_active(request, session)
                    if pending is not None:
                        await response.write(pending)
                    await response.write_eof()
            return response
        except (ValueError, OSError, IndexError, web.HTTPException, ConnectionError):
            if response is not None and response.prepared:
                if request.transport is not None:
                    request.transport.abort()
                return response
            raise web.HTTPNotFound(text="Result payload is unavailable or changed")

    async def leave(self, request):
        session = self.authorize(request)
        if request.can_read_body:
            await _bounded_json(request.content, 4096)
        self.active(session)
        authority = self.close_local(session)
        if getattr(self, 'work', None) is not None:
            await self.work.cancel(session)
        if authority is not None:
            await self.revoke_broker(authority)
        return web.json_response({"ok": True, "status": "left"})


def register(server, instance_id="", **options):
    if getattr(server, "_zura_comfylink_studio_sessions", None) is not None:
        return server._zura_comfylink_studio_sessions
    if 'history_reader' not in options:
        queue = getattr(server, 'prompt_queue', None)
        reader = getattr(queue, 'get_history', None)
        if callable(reader):
            options['history_reader'] = lambda limit: reader(max_items=limit)
    service = StudioSessions(instance_id=instance_id, **options)
    from .studio_cancel import SessionWork
    service.work = SessionWork(service, server)
    if getattr(server, 'app', None) is not None:
        server.app.middlewares.append(service.work.middleware)
    server.routes.post(PREFIX + "/sessions")(service.create)
    server.routes.get(PREFIX + "/sessions/{id}")(service.get)
    server.routes.post(PREFIX + "/sessions/{id}/renew")(service.renew)
    server.routes.post(PREFIX + "/sessions/{id}/source")(service.source)
    server.routes.post(PREFIX + "/sessions/{id}/model-source")(service.model_source)
    server.routes.post(PREFIX + "/sessions/{id}/retained-images")(service.retained_images)
    server.routes.get(PREFIX + "/sessions/{id}/display-config")(service.display_config)
    server.routes.get(PREFIX + "/sessions/{id}/display-frame")(service.display_frame)
    server.routes.post(PREFIX + "/sessions/{id}/result")(service.result)
    server.routes.get(PREFIX + "/sessions/{id}/status")(service.status)
    server.routes.post(PREFIX + "/sessions/{id}/prepare-graph")(service.prepare_graph)
    server.routes.post(PREFIX + "/sessions/{id}/leave")(service.leave)
    server.routes.post(PREFIX + "/sessions/{id}/cancel")(service.leave)
    server.routes.get(PREFIX + "/sessions/{id}/result-files/{index}")(service.result_file)
    server.routes.get(PREFIX + "/sessions/{id}/original-files/{index}")(service.original_file)
    from . import studio_desktop
    service.desktop = studio_desktop.register(server)
    server._zura_comfylink_studio_sessions = service
    return service
