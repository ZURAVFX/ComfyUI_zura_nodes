"""Fixed, loopback-only Studio assets for the verified AE host cache."""
import asyncio
import hashlib
import io
import json
import re
from pathlib import Path

from aiohttp import web

from .security import require_local

PREFIX = "/zura/comfylink/v1/studio-host/"
WEB_ROOT = (Path(__file__).resolve().parent.parent / "web").resolve()
MANIFEST = "studio_host_manifest.json"
MIME = {
    ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
    ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf",
}
NAME = re.compile(r"[A-Za-z0-9._/-]+\Z", re.ASCII)
HASH = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)
HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def _valid_name(name):
    return (isinstance(name, str) and bool(NAME.fullmatch(name))
            and all(part not in ("", ".", "..", "node_modules", "workflows", "workflow", "private", "work", "tests")
                    and not part.startswith(".") for part in name.split("/"))
            and Path(name).suffix.lower() in MIME)


def _runtime_asset_name(name):
    suffix = Path(name).suffix.lower()
    media = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".woff", ".woff2", ".ttf"}
    return (name == "flux3_prompt_upsampling.json"
            or name.startswith("vendor/") and suffix in (".js", ".mjs", ".css")
            or (name.startswith("assets/") or name.startswith("paintout_studio/assets/")) and suffix in media)


def _manifest(package_version):
    raw = (WEB_ROOT / MANIFEST).read_bytes()
    value = json.loads(raw)
    if (value.get("hostSchema") != 1 or value.get("backendVersion") != package_version
            or value.get("uiVersion") != package_version
            or value.get("entries") != {"comfy": "studio.js", "ae": "studio_ae.html"}
            or not HASH.fullmatch(value.get("sourceSha256", ""))):
        raise ValueError("Studio host version or schema differs from this backend")
    source = value.get("sourceFiles")
    assets = value.get("assetSha256")
    entries = value.get("entrySha256")
    if not isinstance(source, list) or not isinstance(assets, dict) or not isinstance(entries, dict):
        raise ValueError("Studio host file list is missing")
    if len(source) != len(set(source)) or any(not _valid_name(name) or name.startswith("vendor/")
                                             or Path(name).suffix.lower() not in (".js", ".css", ".html") for name in source):
        raise ValueError("Studio host source file list is invalid")
    if any(not _valid_name(name) or not _runtime_asset_name(name) or name == MANIFEST or name in source or not HASH.fullmatch(digest)
           for name, digest in assets.items()):
        raise ValueError("Studio host asset list is invalid")
    required = {"studio_ae.html", "studio_ae_probe.js", "studio_ae_entry.js", "studio_host_version.js"}
    if not required <= set(source) or set(entries) != required or any(not HASH.fullmatch(value) for value in entries.values()):
        raise ValueError("Studio host entry hashes are missing")
    return raw, value, set(source) | set(assets)


def register(server, package_version):
    @server.routes.get(PREFIX + "{relative:.+}")
    async def studio_host_asset(request):
        require_local(request)
        raw_path = request.raw_path
        if (not raw_path.startswith(PREFIX) or "?" in raw_path or "%" in raw_path
                or "\\" in raw_path):
            raise web.HTTPNotFound(text="Unknown Studio host asset")
        relative = raw_path[len(PREFIX):]
        if not _valid_name(relative):
            raise web.HTTPNotFound(text="Unknown Studio host asset")
        try:
            manifest_bytes, manifest, allowed = _manifest(package_version)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            raise web.HTTPServiceUnavailable(text="Studio host manifest is unavailable")
        if relative == MANIFEST:
            return web.Response(body=manifest_bytes, content_type=MIME[".json"], headers=HEADERS)
        if relative not in allowed:
            raise web.HTTPNotFound(text="Unknown Studio host asset")
        file = (WEB_ROOT / relative).resolve()
        if not file.is_relative_to(WEB_ROOT) or not file.is_file():
            raise web.HTTPNotFound(text="Unknown Studio host asset")
        try:
            contents = await asyncio.to_thread(file.read_bytes)
        except OSError:
            raise web.HTTPNotFound(text="Unknown Studio host asset")
        expected = manifest["entrySha256"].get(relative) or manifest["assetSha256"].get(relative)
        if expected and hashlib.sha256(contents).hexdigest() != expected:
            raise web.HTTPServiceUnavailable(text="Studio host asset differs from its manifest")
        return web.Response(body=io.BytesIO(contents), content_type=MIME[file.suffix.lower()], headers=HEADERS)
