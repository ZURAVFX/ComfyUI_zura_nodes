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
from urllib.parse import urlsplit

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
MAX_SESSIONS = 32
MAX_ORIGINAL_BYTES = float_io.MAX_TRANSFER_BYTES
_ORIGINAL_TYPES = {".exr": "image/x-exr", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".webp": "image/webp", ".mp4": "video/mp4", ".mov": "video/quicktime",
                   ".mkv": "video/x-matroska", ".webm": "video/webm", ".zip": "application/zip"}
_STUDIO_MODES = {"swap", "ripple", "viewport", "camera", "relight", "paintout", "watermark", "alpha",
                 "outpaint", "hdr", "director", "frames", "references", "image"}
_BROKER_DIAGNOSTICS = {"float import needs a known colour profile; the result remains available",
                       "float import requires verified straight alpha",
                       "Result retained; native import needs attention",
                       "Result retained: dimensions, frame count or frame rate do not match the original layer."}
_SDR_TRANSFERS = {2: "unspecified", 1: "bt709", 4: "gamma22", 5: "gamma28", 6: "smpte170m", 7: "smpte240m", 13: "srgb"}
_SDR_PRIMARIES = {2: "unspecified", 1: "bt709", 4: "bt470m", 5: "bt470bg", 6: "smpte170m", 7: "smpte240m", 22: "ebu3213"}
_COLOUR_META = ("icc", "hdr", "exif", "xmp", "gamma", "chromatic", "cicp", "gainmap", "jumbf", "photoshop", "colour", "color", "profile")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
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
    for side in getattr(value, "side_data", ()):
        # x264's ordinary encoder identification SEI is unrelated to colour.
        if getattr(side.type, "name", "") == "SEI_UNREGISTERED" and bytes(side)[16:].startswith(b"x264 - core "):
            continue
        raise ValueError("Video side metadata cannot be proven unmanaged SDR")
    fmt = getattr(value, "format", None)
    if fmt is None or not fmt.components or any(component.bits != 8 for component in fmt.components):
        raise ValueError("Video storage is not eight bits per component")
    transfer, primaries = int(value.color_trc), int(value.color_primaries)
    space = int(value.colorspace)
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


class StudioSessions:
    def __init__(self, input_root=None, output_root=None, instance_id="", importer=None):
        self.input_root = Path(input_root) if input_root is not None else None
        self.output_root = Path(output_root) if output_root is not None else None
        self.instance_id = instance_id
        self.importer = importer
        self.sessions = {}
        self.used = {}
        self._registration_lock = asyncio.Lock()
        self._revocations = set()

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
            timeout = aiohttp.ClientTimeout(total=180 if suffix == "/result" else 30, connect=3, sock_read=30)
            async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as client:
                async with client.request("GET" if body is None else "POST", session.broker + suffix,
                                          headers={TOKEN_HEADER: session.token}, json=body,
                                          allow_redirects=False) as response:
                    if response.status < 200 or response.status >= 300:
                        if response.status in (401, 403, 410):
                            raise web.HTTPGone(text="Broker authority is unavailable or expired")
                        raise web.HTTPBadGateway(text="Broker declined the Studio request")
                    return await _bounded_json(response.content)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise web.HTTPBadGateway(text="Local Studio broker is unavailable")

    def public(self, session):
        return {"id": session.id, "context": session.context, "label": session.context["target"]["label"],
                "expiresAt": datetime.fromtimestamp(session.expires, timezone.utc).isoformat(),
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
            self.sessions[session.id] = session
            self.used[fingerprint] = max(_expiry(grant["expiresAt"]), time.time() + TTL)
            loop = asyncio.get_running_loop()
            loop.call_later(max(0, session.expires - time.time()) + .05, self.cleanup)
            loop.call_later(TTL + .05, self.cleanup)
            return web.json_response({**self.public(session), "capability": session.capability}, status=201,
                                     headers={"Cache-Control": "no-store"})

    async def get(self, request):
        return web.json_response(self.public(self.authorize(request)))

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
        manifest = float_io.validate_manifest(data.get("manifest", data))
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
                if profile:
                    await self.download(session, "source.icc", temporary / "source.icc", profile)
                    encoded_profile = float_io._read_private(temporary / "source.icc", 4 * 1024 * 1024)
                    if (encoded_profile[36:40] != b"acsp"
                            or int.from_bytes(encoded_profile[:4], "big") != len(encoded_profile)):
                        raise ValueError("Invalid project ICC profile header")
                float_io._exclusive_write(temporary / "manifest.json", float_io.canonical_manifest_bytes(manifest))
            # Validate actual pixels before publication, including NaN/Inf.
            probe = secrets.token_hex(16)
            validation_folder = parent / probe
            with float_io._locked_parents(parent):
                os.rename(temporary, validation_folder)
            try:
                await asyncio.to_thread(float_io.load_transfer, input_root, "ComfyLink/" + probe + "/manifest.json")
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
        rate = manifest["frameRate"]
        result = {"floatManifest": {"filename": "manifest.json", "subfolder": "ComfyLink/" + session.id, "type": "input"},
                  "precision": {"sampleType": manifest["sampleType"], "sourceBitDepth": manifest["sourceBitDepth"]},
                  "colour": manifest["colour"], "alpha": manifest["alphaAssociation"],
                  "width": manifest["width"], "height": manifest["height"], "frameCount": len(manifest["frames"]),
                  "fps": rate["numerator"] / rate["denominator"], "manifest": manifest}
        try:
            self.active(session)
            imported = await (self.importer or self.native_import)(session, folder, manifest)
            result.update({key: value for key, value in imported.items() if key in {"studioAsset", "mediaInfo", "stills"}})
        except Exception:
            # Media decoders use several library-specific exception classes.
            # Keep the verified raw source available without logging filenames.
            result["nativeImport"] = {"status": "unavailable", "diagnostic":
                "Float source retained. Native Studio import needs a compatible media route and installed EXR support for high-depth sources."}
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

    async def native_import(self, session, folder, manifest):
        """Use Studio's existing upload API; never manufacture asset records.

        Raw float authority is retained even when optional EXR support is absent.
        Eight-bit source pixels may also be encoded losslessly for SDR controls.
        Higher-depth sources exclusively use FLOAT EXR, without PIL conversion.
        """
        import numpy as np
        input_root, _ = self.roots()
        pixels, _ = await asyncio.to_thread(float_io.load_transfer, input_root,
                                              "ComfyLink/" + session.id + "/manifest.json")
        generated = folder / ("native-" + secrets.token_hex(16))
        with float_io._locked_parents(folder):
            generated.mkdir()
        is_sdr8 = (manifest["sourceBitDepth"] == 8 and manifest["colour"]["encoding"] == "unknown"
                   and manifest["colour"]["sceneLinear"] is False and manifest["alphaAssociation"] == "straight"
                   and np.all(pixels >= 0) and np.all(pixels <= 1))
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
                async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=180, connect=3)) as client:
                    async with client.post(session.origin + endpoint, data=form, headers={"Origin": session.origin}, allow_redirects=False) as response:
                        if response.status != 200:
                            raise ValueError("Native Studio upload unavailable")
                        asset = await _bounded_json(response.content)
                        self.active(session)
                        return asset
            finally:
                for stream in streams:
                    stream.close()

        def encode():
            if is_sdr8:
                from PIL import Image
                from fractions import Fraction
                # Source bit depth alone is insufficient to authorise a lossy
                # quantisation. Only exact eight-bit levels enter this path.
                encoded = np.rint(pixels * 255).astype(np.uint8)
                if not np.array_equal(pixels, encoded.astype(np.float32) / np.float32(255)):
                    raise ValueError("Source samples are not eight-bit levels")
                first = generated / "first.png"
                Image.fromarray(encoded[0], "RGBA").save(first)
                last = first
                if len(encoded) > 1:
                    last = generated / "last.png"
                    Image.fromarray(encoded[-1], "RGBA").save(last)
                    import av
                    video = generated / "source.mkv"
                    rate = Fraction(manifest["frameRate"]["numerator"], manifest["frameRate"]["denominator"])
                    with av.open(str(video), "w") as container:
                        stream = container.add_stream("ffv1", rate=rate)
                        stream.width, stream.height, stream.pix_fmt = manifest["width"], manifest["height"], "bgra"
                        for index, rgba in enumerate(encoded):
                            frame = av.VideoFrame.from_ndarray(rgba, format="rgba")
                            frame.pts, frame.time_base = index, 1 / rate
                            for packet in stream.encode(frame):
                                container.mux(packet)
                        for packet in stream.encode():
                            container.mux(packet)
                    return [video], first, last
                return [first], first, last
            paths = []
            for index, rgba in enumerate(pixels):
                path = generated / (f"{index + 1:06d}.exr")
                float_io.write_exr(path, rgba, colour=manifest["colour"], storage="float32",
                                   alpha_association=manifest["alphaAssociation"])
                paths.append(path)
            return paths, None, None

        paths, first, last = await asyncio.to_thread(encode)
        self.active(session)
        asset = await upload(paths, "/zura/studio/upload?kind=" + ("video" if len(pixels) > 1 else "image")
                             if is_sdr8 else "/zura/studio/hdr/exr-sequence")
        result = {"studioAsset": asset}
        if first:
            stills = {}
            for key, path in (("first", first), ("last", last)):
                relative = path.relative_to(input_root.absolute())
                stills[key] = {"filename": relative.name, "subfolder": relative.parent.as_posix(),
                               "file": relative.as_posix(), "type": "input", "width": manifest["width"], "height": manifest["height"]}
            result["stills"] = stills
        try:
            if is_sdr8 and len(pixels) > 1 and _HEX32.fullmatch(str(asset.get("id", ""))):
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
        except Exception:
            pass
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
        _, output_root = self.roots()
        root = output_root.absolute()
        path = root / subfolder / filename
        if not path.absolute().is_relative_to(root):
            raise ValueError("Output master is outside this Comfy instance")
        with float_io._locked_parents(path.parent):
            float_io._safe_stat(path)
        return path

    def prepare_result(self, session, body):
        if set(body) - {"kind", "master", "preview", "colour", "alpha", "width", "height", "frameCount", "fps", "precision"}:
            raise ValueError("Unsupported result descriptor fields")
        if not isinstance(body.get("kind", "float_sequence"), str) or body.get("kind", "float_sequence") not in {"image", "video", "float_sequence", "float_manifest", "hdr_sequence", "sequence"}:
            raise ValueError("Unsupported result kind")
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
        elif originals:
            path, storage, provenance = self.convert_master(path, body)
            if storage is not None:
                original_descriptors[0]["storage"] = storage
        relative = path.relative_to(root.absolute()).as_posix()
        _, manifest = float_io.load_transfer(root, relative)
        for field_name, actual in (("width", manifest["width"]), ("height", manifest["height"]),
                                   ("frameCount", len(manifest["frames"])), ("colour", manifest["colour"]),
                                   ("alpha", manifest["alphaAssociation"])):
            if field_name in body and body[field_name] != actual:
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

    def convert_master(self, path, body):
        """Decode a declared master and publish a separate verified float transfer.

        Only actual eight-bit SDR images/video enter the SDR decoder. A high
        depth EXR requires float_io's metadata, storage and finite-pixel checks.
        Native HDR videos without a verified float export remain pending.
        """
        import numpy as np
        from fractions import Fraction
        suffix = path.suffix.lower()
        rate = Fraction(24, 1)
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
                # Still images have no inherent frame rate; an explicitly
                # selected timeline rate is metadata, not a pixel conversion.
                if "fps" in body:
                    if isinstance(body["fps"], bool):
                        raise ValueError("Invalid result frame rate")
                    rate = Fraction(str(body["fps"]))
            elif suffix == ".exr":
                pixels, side = float_io.read_exr(path)
                pixels = pixels[None]
                colour, alpha, depth = side["colour"], side["alphaAssociation"], 32
                storage = side["storage"]
                if "fps" in body:
                    rate = Fraction(str(body["fps"]))
            elif suffix in {".mp4", ".mov", ".mkv", ".webm"}:
                import av
                frames, total = [], 0
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
                    stream_colour = _video_sdr_metadata(context)
                    _unmanaged_metadata(stream.metadata)
                    if getattr(stream, "side_data", ()):
                        raise ValueError("Unsupported video stream side metadata")
                    rate = stream.average_rate
                    if rate is None or rate <= 0:
                        raise ValueError("Unknown master video frame rate")
                    for frame in media.decode(video=0):
                        frame_colour = _video_sdr_metadata(frame, stream_colour)
                        if frames and frame_colour != actual_colour:
                            raise ValueError("Video colour metadata changes between frames")
                        actual_colour = frame_colour
                        if (frame.width * frame.height > float_io.MAX_PIXELS
                                or len(frames) >= float_io.MAX_FRAMES):
                            raise ValueError("Master video dimensions or count exceed limit")
                        total += frame.width * frame.height * 16
                        if total > float_io.MAX_TRANSFER_BYTES:
                            raise ValueError("Decoded video exceeds transfer limit")
                        frames.append(frame.to_ndarray(format="rgba").astype(np.float32) / np.float32(255))
                    if not frames:
                        raise ValueError("Master video has no readable pixels")
                    pixels = np.stack(frames)
                    provenance = {"schemaVersion": 1, "kind": "sdr8_video", "sourceBitDepth": 8,
                                  "embeddedICC": False, "hdrMetadata": False, "transfer": _SDR_TRANSFERS[actual_colour[0]],
                                  "primaries": _SDR_PRIMARIES[actual_colour[1]], "validatedFrameCount": len(frames)}
            else:
                raise ValueError("Unsupported master format; retain pending")
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

    def convert_exr_sequence(self, paths, body, *, native_records=None, frame_rate=None):
        """Convert only explicitly selected, verified EXRs, preserving originals."""
        import numpy as np
        from fractions import Fraction
        frames, storages, total, contract = [], [], 0, None
        for path in paths:
            if native_records is None:
                pixels, side = float_io.read_exr(path)
            else:
                pixels, side = self.native_archive_frame(path, native_records[path])
            current = (pixels.shape, side["colour"], side["alphaAssociation"])
            if contract is not None and contract != current:
                raise ValueError("EXR master sequence shape, colour or alpha differs")
            contract = current
            total += pixels.nbytes
            if total > float_io.MAX_TRANSFER_BYTES:
                raise ValueError("Decoded EXR sequence exceeds byte limit")
            frames.append(pixels)
            storages.append(side["storage"])
        rate = frame_rate if frame_rate is not None else Fraction(str(body["fps"]))
        _, root = self.roots()
        relative, _ = float_io.write_transfer(root, "ComfyLink/" + secrets.token_hex(16), np.stack(frames),
            colour=contract[1], frame_rate={"numerator": rate.numerator, "denominator": rate.denominator},
            source_bit_depth=32, alpha_association=contract[2])
        return root.absolute() / relative, storages

    def native_archive_frame(self, path, expected):
        """Read a Studio-validated RGB AP1 frame without colour/range changes."""
        import numpy as np
        import OpenImageIO as oiio
        record = _file_record(path, float_io.MAX_TRANSFER_BYTES, expected)
        with float_io._locked_parents(path.parent):
            reader = oiio.ImageInput.open(str(path))
            if reader is None:
                raise ValueError("Unreadable native EXR frame")
            try:
                spec = reader.spec()
                storage = "float32" if spec.format == oiio.FLOAT else "half" if spec.format == oiio.HALF else None
                if (storage is None or spec.deep or spec.depth != 1 or spec.nchannels != 3
                        or set(spec.channelnames) != {"R", "G", "B"} or not 1 <= spec.width <= float_io.MAX_DIMENSION
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
                if pixels is None or pixels.shape != (spec.height, spec.width, 3) or not np.isfinite(pixels).all():
                    raise ValueError("Native EXR contains nonfinite or malformed pixels")
                rgb = pixels[:, :, [list(spec.channelnames).index(channel) for channel in "RGB"]]
                rgba = np.concatenate((rgb, np.ones((*rgb.shape[:2], 1), dtype=np.float32)), axis=2)
            finally:
                reader.close()
        if _file_record(path, float_io.MAX_TRANSFER_BYTES, expected)[1] != record[1]:
            raise ValueError("Native EXR changed during decode")
        return rgba, {"storage": storage, "colour": {"encoding": "acescg", "sceneLinear": True}, "alphaAssociation": "straight"}

    def convert_zip_master(self, session, path, body):
        """Prepare only the native Studio's bounded stored ACEScg EXR ZIP."""
        import OpenImageIO as oiio
        from fractions import Fraction
        with float_io._locked_parents(path.parent), zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if not 1 <= len(infos) <= float_io.MAX_FRAMES:
                raise ValueError("Native archive frame count exceeds bounds")
            names, total = set(), 0
            for info in infos:
                name = info.filename
                kind = (info.external_attr >> 16) & 0o170000
                if (not isinstance(name, str) or not re.fullmatch(r"frame_[0-9]{5}\.exr", name)
                        or name.casefold() in names or info.is_dir() or info.flag_bits & 1
                        or kind not in {0, stat.S_IFREG} or info.extra
                        or info.compress_type != zipfile.ZIP_STORED or info.compress_size != info.file_size
                        or not 0 < info.file_size <= float_io.MAX_TRANSFER_BYTES):
                    raise ValueError("Archive contains unsafe paths, metadata, links or compressed entries")
                names.add(name.casefold())
                total += info.file_size
                if total > float_io.MAX_TRANSFER_BYTES:
                    raise ValueError("Native archive exceeds aggregate byte bound")
            expected_names = [f"frame_{index:05d}.exr" for index in range(len(infos))]
            if sorted(info.filename for info in infos) != expected_names:
                raise ValueError("Native archive has missing or unordered frame numbers")
            source = float_io.validate_manifest(session.source.get("manifest"))
            rate = Fraction(source["frameRate"]["numerator"], source["frameRate"]["denominator"])
            if "fps" in body and body["fps"] != float(rate):
                rate = Fraction(str(body["fps"]))
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
                reader = oiio.ImageInput.open(str(prepared / expected_names[0]))
                if reader is None:
                    raise ValueError("Native archive has no readable first EXR")
                try:
                    spec = reader.spec()
                    width, height = spec.width, spec.height
                    storage = "half" if spec.format == oiio.HALF else "float32" if spec.format == oiio.FLOAT else None
                    if (storage is None or not 1 <= width <= float_io.MAX_DIMENSION or not 1 <= height <= float_io.MAX_DIMENSION
                            or width * height > float_io.MAX_PIXELS or width * height * 16 * len(infos) > float_io.MAX_TRANSFER_BYTES):
                        raise ValueError("Native archive decoded pixels exceed bounds")
                finally:
                    reader.close()
                # Reuse Studio's actual archive validator. It checks every RGB
                # EXR's storage, AP1 chromaticities, scene-linear colour tags,
                # raster, finite pixels and complete frame numbering.
                _studio_module("ltx25_hdr_result")._check_archive(path, len(infos), width, height, exr_storage=storage)
                self.active(session)
                converted, _ = self.convert_exr_sequence([prepared / name for name in expected_names],
                    {}, native_records=records, frame_rate=rate)
                complete = True
                return converted
            finally:
                if not complete:
                    # Only this fresh, private extraction subtree is disposable.
                    with float_io._locked_parents(parent):
                        shutil.rmtree(private)

    async def result(self, request):
        session = self.authorize(request)
        if not session.context["capabilities"]["transfer"]:
            raise web.HTTPForbidden(text="This session has no result authority")
        body = await _bounded_json(request.content, 65536)
        async with session.lock:
            self.active(session)
            try:
                descriptor = await asyncio.to_thread(self.prepare_result, session, body)
            except Exception:
                # Decode errors are returned without codec diagnostics, paths
                # or capabilities; the original output is always retained.
                session.download_capability = ""
                session.result_files.clear()
                session.original_files.clear()
                return web.json_response({"ok": False, "status": "pending", "diagnostic":
                    "Master validation failed or this format is unsupported. Save a ComfyLink float master; the result is retained."}, status=422)
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
        response = await self.broker_json(session, "/status")
        self.active(session)
        status = response.get("status")
        if not isinstance(status, str) or status not in {"preparing", "ready", "import_pending", "sent"}:
            status = "pending"
        diagnostic = response.get("diagnostic")
        return web.json_response({"ok": True, "status": status, "ready": response.get("ready") is True,
                                  "importPending": response.get("importPending") is True,
                                  **({"diagnostic": diagnostic} if isinstance(diagnostic, str) and diagnostic in _BROKER_DIAGNOSTICS else {})},
                                 headers={"Cache-Control": "no-store"})

    async def prepare_graph(self, request):
        from fractions import Fraction
        from .frame_contract import normalise_frame_contract, prepare_frame_contract_graph, IMAGE_SAVERS, VIDEO_SAVERS
        session = self.authorize(request)
        body = await _bounded_json(request.content, 16 * 1024 * 1024)
        try:
            if set(body) != {"mode", "graph", "ae_frame_contract"} or not isinstance(body["mode"], str) or body["mode"] not in _STUDIO_MODES:
                raise ValueError("Choose a supported native Studio mode")
            raw_contract = body["ae_frame_contract"]
            if not isinstance(raw_contract, dict) or type(raw_contract.get("schemaVersion")) is not int:
                raise ValueError("Choose a valid AE frame contract")
            contract = normalise_frame_contract(raw_contract)
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
            prepared = await asyncio.to_thread(prepare_frame_contract_graph, graph, contract, body["mode"])
            self.active(session)
            return web.json_response({"graph": prepared}, headers={"Cache-Control": "no-store"})
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
        if authority is not None:
            await self.revoke_broker(authority)
        return web.json_response({"ok": True, "status": "left"})


def register(server, instance_id="", **options):
    if getattr(server, "_zura_comfylink_studio_sessions", None) is not None:
        return server._zura_comfylink_studio_sessions
    service = StudioSessions(instance_id=instance_id, **options)
    server.routes.post(PREFIX + "/sessions")(service.create)
    server.routes.get(PREFIX + "/sessions/{id}")(service.get)
    server.routes.post(PREFIX + "/sessions/{id}/source")(service.source)
    server.routes.post(PREFIX + "/sessions/{id}/result")(service.result)
    server.routes.get(PREFIX + "/sessions/{id}/status")(service.status)
    server.routes.post(PREFIX + "/sessions/{id}/prepare-graph")(service.prepare_graph)
    server.routes.post(PREFIX + "/sessions/{id}/leave")(service.leave)
    server.routes.get(PREFIX + "/sessions/{id}/result-files/{index}")(service.result_file)
    server.routes.get(PREFIX + "/sessions/{id}/original-files/{index}")(service.original_file)
    server._zura_comfylink_studio_sessions = service
    return service
