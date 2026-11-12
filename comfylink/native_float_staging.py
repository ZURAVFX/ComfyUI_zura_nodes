"""One-frame, capability-scoped FLOAT staging for a local Comfy server.

The caller supplies bytes, never a server filesystem path. Each completed
manifest is immutable and is published only after byte and sample validation.
"""
import asyncio
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import time


from aiohttp import web

from . import float_io
from .security import require_local
from .studio_sessions import _bounded_json

PREFIX = "/zura/comfylink/v1/float-staging"
HEADER = "X-ComfyLink-Float-Capability"
MAX_PENDING = 8
TTL = 300
READY_TTL = 25 * 60 * 60  # longer than the native job maximum of 24 hours


def _input_root():
    import folder_paths
    return Path(folder_paths.get_input_directory())


def _delete_exact_leaf(path, expected):
    # Windows deletes by verified handle, not by a separately checked pathname.
    # Other platforms retain files until an equally strong deletion route exists.
    if os.name != "nt":
        return False
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x10000 | 0x80, 3, None, 3, 0x00200000, None)
    if handle == wintypes.HANDLE(-1).value:
        return False
    fd = None
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        handle = None
        opened = os.fstat(fd)
        current = float_io._safe_stat(path)
        if float_io._identity(opened) != expected or float_io._identity(current) != expected or opened.st_nlink != 1:
            return False
        delete = wintypes.BOOL(True)
        return bool(kernel.SetFileInformationByHandle(msvcrt.get_osfhandle(fd), 4, ctypes.byref(delete), ctypes.sizeof(delete)))
    finally:
        if fd is not None:
            os.close(fd)
        elif handle is not None:
            kernel.CloseHandle(handle)


class FloatStaging:
    def __init__(self, roots=None):
        self.roots = roots or _input_root
        self.pending = {}

    @staticmethod
    def discard(session, folder):
        # Only remove our exact directory and exact regular owned leaves.
        try:
            with float_io._locked_parents(folder):
                if float_io._identity(float_io._safe_stat(folder, directory=True)) != session["identity"]:
                    return False
                identities = session["leaves"]
                entries = list(folder.iterdir())
                if any(entry.name not in identities for entry in entries):
                    return False
                for entry in entries:
                    if not _delete_exact_leaf(entry, identities[entry.name]):
                        return False
            with float_io._locked_parents(session["parent"]):
                if float_io._identity(float_io._safe_stat(folder, directory=True)) == session["identity"]:
                    folder.rmdir()
                    return True
        except (OSError, ValueError):
            pass
        return False

    async def create(self, request):
        require_local(request)
        if os.name != "nt":
            raise web.HTTPNotImplemented(text="FLOAT staging is available on Windows")
        for ident, session in list(self.pending.items()):
            if session["expires"] < time.monotonic() and not session["busy"]:
                self.pending.pop(ident, None)
                # Ready inputs may still belong to an uncertain Comfy prompt.
                if not session.get("ready"):
                    self.discard(session, session["temp"])
        if len(self.pending) >= MAX_PENDING:
            raise web.HTTPServiceUnavailable(text="Too many pending float transfers")
        body = await _bounded_json(request.content, 65536)
        # Other requests may have filled the slots while the body was read.
        if len(self.pending) >= MAX_PENDING:
            raise web.HTTPServiceUnavailable(text="Too many pending float transfers")
        try:
            if set(body) != {"manifest"}:
                raise ValueError("Invalid staging request")
            manifest = float_io.validate_manifest(body["manifest"])
            if len(manifest["frames"]) != 1 or manifest["sampleType"] != "float32":
                raise ValueError("Only one FLOAT frame may be staged at a time")
            if manifest["colour"]["encoding"] == "ae_project_icc":
                raise ValueError("This staging route requires a separately verified ICC transport")
            root = self.roots().absolute()
            parent = root / "ComfyLink"
            reserved = sum(item["manifest"]["frames"][0]["byteLength"] for item in self.pending.values())
            if shutil.disk_usage(root).free < reserved + manifest["frames"][0]["byteLength"] + 4 * 1024**3:
                raise ValueError("Not enough free storage for float staging")
            with float_io._locked_parents(root):
                parent.mkdir(exist_ok=True)
            ident, secret = secrets.token_hex(16), secrets.token_hex(32)
            temporary = parent / (".float-upload-" + ident)
            with float_io._locked_parents(parent):
                temporary.mkdir()
                stamp = float_io._identity(float_io._safe_stat(temporary, directory=True))
            self.pending[ident] = {"secret": secret, "manifest": manifest, "root": root,
                                   "parent": parent, "temp": temporary, "identity": stamp,
                                   "expires": time.monotonic() + TTL, "busy": False, "leaves": {}}
        except (ValueError, OSError):
            raise web.HTTPBadRequest(text="FLOAT staging could not be prepared")
        return web.json_response({"id": ident, "capability": secret}, headers={"Cache-Control": "no-store"})

    async def frame(self, request):
        require_local(request)
        import numpy as np
        ident = request.match_info["id"]
        session = self.pending.get(ident)
        supplied = request.headers.get(HEADER, "")
        if not session or len(supplied) != 64 or not supplied.isascii() or not secrets.compare_digest(supplied, session["secret"]):
            raise web.HTTPForbidden(text="FLOAT transfer is unavailable")
        if session["expires"] < time.monotonic() or session["busy"] or session.get("ready"):
            raise web.HTTPConflict(text="FLOAT transfer expired or is already active")
        session["busy"] = True
        frame = session["manifest"]["frames"][0]
        if request.content_length is not None and request.content_length != frame["byteLength"]:
            self.pending.pop(ident, None)
            self.discard(session, session["temp"])
            raise web.HTTPBadRequest(text="FLOAT frame size does not match its manifest")
        root, parent, temporary = session["root"], session["parent"], session["temp"]
        target = temporary / frame["filename"]
        relative = "ComfyLink/" + ident + "/manifest.json"
        final = parent / ident
        try:
            with float_io._locked_parents(temporary):
                if float_io._identity(float_io._safe_stat(temporary, directory=True)) != session["identity"]:
                    raise ValueError("FLOAT staging directory changed")
                digest, total, tail = hashlib.sha256(), 0, b""
                with target.open("xb") as output:
                    session["leaves"][target.name] = float_io._identity(os.fstat(output.fileno()))
                    async def receive():
                        nonlocal total, tail
                        async for chunk in request.content.iter_chunked(1024 * 1024):
                            total += len(chunk)
                            if total > frame["byteLength"]:
                                raise ValueError("FLOAT frame exceeds declared size")
                            digest.update(chunk)
                            samples = tail + chunk
                            aligned = len(samples) - len(samples) % 4
                            if not np.isfinite(np.frombuffer(samples[:aligned], dtype="<f4")).all():
                                raise ValueError("Nonfinite FLOAT samples")
                            tail = samples[aligned:]
                            output.write(chunk)
                    await asyncio.wait_for(receive(), timeout=TTL)
                    output.flush()
                if tail or total != frame["byteLength"] or not secrets.compare_digest(digest.hexdigest(), frame["sha256"]):
                    raise ValueError("FLOAT frame checksum mismatch")
                manifest_path = temporary / "manifest.json"
                with manifest_path.open("xb") as manifest_file:
                    session["leaves"][manifest_path.name] = float_io._identity(os.fstat(manifest_file.fileno()))
                    manifest_file.write(float_io.canonical_manifest_bytes(session["manifest"]))
            # Move into the final server-owned UUID folder only after upload.
            # Consumers cannot discover a completed manifest before validation.
            with float_io._locked_parents(parent):
                if final.exists() or final.is_symlink():
                    raise ValueError("FLOAT staging destination already exists")
                os.rename(temporary, final)
            try:
                task = asyncio.create_task(asyncio.to_thread(float_io.verify_transfer, root, relative))
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    # Do not remove a directory while its verification thread is reading it.
                    try:
                        await task
                    except Exception:
                        pass
                    raise
            except Exception:
                # Retain an untrusted failed staging folder rather than deleting
                # anything whose identity could have changed concurrently.
                raise ValueError("FLOAT frame sample validation failed")
        except (ValueError, OSError):
            self.discard(session, temporary)
            self.discard(session, final)
            self.pending.pop(ident, None)
            raise web.HTTPUnprocessableEntity(text="FLOAT transfer could not be verified")
        except BaseException:
            self.discard(session, temporary)
            self.discard(session, final)
            self.pending.pop(ident, None)
            raise
        session["busy"] = False
        session["ready"] = True
        session["expires"] = time.monotonic() + READY_TTL
        return web.json_response({"manifest": relative}, headers={"Cache-Control": "no-store"})

    async def release(self, request):
        require_local(request)
        ident = request.match_info["id"]
        session = self.pending.get(ident)
        supplied = request.headers.get(HEADER, "")
        if not session or len(supplied) != 64 or not supplied.isascii() or not secrets.compare_digest(supplied, session["secret"]):
            raise web.HTTPForbidden(text="FLOAT transfer is unavailable")
        if not session.get("ready") or session["busy"]:
            raise web.HTTPConflict(text="FLOAT transfer is still active")
        if not self.discard(session, session["parent"] / ident):
            raise web.HTTPConflict(text="The FLOAT staging directory changed and was retained")
        self.pending.pop(ident, None)
        return web.json_response({"released": True}, headers={"Cache-Control": "no-store"})


def register(server):
    service = FloatStaging()
    server.routes.post(PREFIX)(service.create)
    server.routes.post(PREFIX + "/{id}/frame")(service.frame)
    server.routes.post(PREFIX + "/{id}/release")(service.release)
    return service
