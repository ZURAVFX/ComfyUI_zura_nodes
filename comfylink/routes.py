"""Small local discovery and preflight API; the supervisor owns all jobs."""
import asyncio
from datetime import datetime, timezone
import json
import os
import secrets
from pathlib import Path
import sys

from aiohttp import web

from .preflight import inspect_graph, inspect_requirements
from .presets import catalogue, graph_hash, preset_by_id
from .security import require_local, require_token

try:
    import psutil
except ImportError:
    psutil = None

PREFIX = "/zura/comfylink/v1"
PROTOCOL_VERSION = "1"
ADAPTER_VERSION = "0.1.0-dev.2"
MAX_PREFLIGHT_BYTES = 16 * 1024 * 1024


def register(server, package_version):
    if getattr(server, "_zura_comfylink_registered", False):
        return
    # These values describe this process at startup, not later changes to os.environ.
    token = os.environ.get("COMFYLINK_TOKEN", "")
    instance_id = os.environ.get("COMFYLINK_INSTANCE_ID", "")
    fingerprint = os.environ.get("COMFYLINK_CONFIG_FINGERPRINT", "")
    # Studio can attach to an already-running, unpaired ComfyUI process.
    # Its public process nonce is distinct from private supervisor identity.
    studio_instance_id = secrets.token_hex(16)

    @server.routes.get(PREFIX + "/capabilities")
    async def capabilities(request):
        require_local(request)
        return web.json_response({"protocol_version": PROTOCOL_VERSION,
                                  "adapter_version": ADAPTER_VERSION,
                                  "zura_version": package_version,
                                  "pairing_configured": bool(token and instance_id and fingerprint),
                                  "features": ["identity", "presets", "graph_preflight", "studio_sessions", "studio_source_float32", "studio_result_float32", "float_frames_v1"],
                                  "studio": {"schemaVersion": 1, "instanceId": studio_instance_id, "prefix": PREFIX + "/studio",
                                             "sessionHeader": "X-ComfyLink-Studio-Session",
                                             "sourceFormats": ["rgba32f", "rgba16u"],
                                             "resultFormats": ["float_manifest", "sdr8_image", "sdr8_video", "verified_exr"],
                                             "nativeModeRegistry": True},
                                  "job_authority": "comfylink_supervisor"})

    @server.routes.get(PREFIX + "/identity")
    async def identity(request):
        require_token(request, token)
        import folder_paths
        started = None
        if psutil is not None:
            try:
                started = datetime.fromtimestamp(psutil.Process(os.getpid()).create_time(), timezone.utc).isoformat()
            except (psutil.Error, OSError, OverflowError):
                pass
        return web.json_response({"protocol_version": PROTOCOL_VERSION,
                                  "instance_id": instance_id,
                                  "config_fingerprint": fingerprint,
                                  "pid": os.getpid(),
                                  "executable": str(Path(sys.executable).resolve()),
                                  "installation_path": str(Path(folder_paths.base_path).resolve()),
                                  "input_root": str(Path(folder_paths.get_input_directory()).resolve()),
                                  "process_started_at": started})

    @server.routes.get(PREFIX + "/presets")
    async def presets(request):
        require_token(request, token)
        return web.json_response({"schema_version": 1, "presets": catalogue()})

    @server.routes.get(PREFIX + "/diagnostics")
    async def diagnostics(request):
        require_token(request, token)
        import nodes
        return web.json_response({"protocol_version": PROTOCOL_VERSION,
                                  "adapter_version": ADAPTER_VERSION,
                                  "zura_version": package_version,
                                  "managed_identity_configured": bool(instance_id and fingerprint),
                                  "native_video_nodes_available": all(name in nodes.NODE_CLASS_MAPPINGS for name in ("LoadVideo", "SaveVideo")),
                                  "batch_node_available": "ComfyLinkLoadFrames" in nodes.NODE_CLASS_MAPPINGS,
                                  "jobs": "owned by the ComfyLink supervisor",
                                  "model_validation": "not run"})

    @server.routes.post(PREFIX + "/preflight")
    async def preflight(request):
        require_token(request, token)
        if request.content_length is not None and request.content_length > MAX_PREFLIGHT_BYTES:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_PREFLIGHT_BYTES, actual_size=request.content_length)
        chunks, size = [], 0
        async for chunk in request.content.iter_chunked(65536):
            size += len(chunk)
            if size > MAX_PREFLIGHT_BYTES:
                raise web.HTTPRequestEntityTooLarge(max_size=MAX_PREFLIGHT_BYTES, actual_size=size)
            chunks.append(chunk)
        raw = b"".join(chunks)
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise web.HTTPBadRequest(text="Expected a JSON object")
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text="Expected a JSON object")
        preset_id = data.get("preset_id")
        if preset_id is not None and not isinstance(preset_id, str):
            raise web.HTTPBadRequest(text="Preset ID must be a string")
        preset = preset_by_id(preset_id) if preset_id else None
        supplied = {key for key in ("workflow", "input", "output") if key in data}
        if supplied:
            if len(supplied) != 3:
                raise web.HTTPBadRequest(text="Provide the workflow and both bindings together")
            graph, inputs, output = data["workflow"], data["input"], data["output"]
        elif preset is not None:
            graph, inputs, output = preset["workflow"], preset["input"], preset["output"]
        elif preset_id:
            raise web.HTTPNotFound(text="Unknown preset")
        else:
            raise web.HTTPBadRequest(text="Provide a preset ID or workflow and bindings")
        import folder_paths
        import nodes
        graph_result = inspect_graph(graph, inputs, output, nodes.NODE_CLASS_MAPPINGS)
        canonical_match = False
        if preset is not None and graph_result["ready"]:
            try:
                canonical_match = (graph_hash(graph) == preset["workflowHash"]
                                   and inputs == preset["input"] and output == preset["output"])
            except (TypeError, KeyError, ValueError):
                pass
        requirements = await asyncio.to_thread(inspect_requirements, graph, nodes.NODE_CLASS_MAPPINGS, folder_paths,
                                                preset_id=preset_id, declared=data.get("required_models"),
                                                canonical_match=canonical_match)
        errors = graph_result["errors"] + requirements["errors"]
        for item in requirements["models"]:
            if item["status"] != "resolved":
                errors.append("Model %s/%s is %s." % (item["category"], item["name"], item["status"]))
        if requirements["missing_dependencies"]:
            errors.append("Required mask dependencies are missing.")
        blocked = bool(errors)
        execution_ready = ("blocked" if blocked else
                           "unknown" if requirements["model_requirements"] != "complete" else "ready")
        return web.json_response({**graph_result, **requirements, "errors": errors,
                                  "graph_ready": graph_result["ready"],
                                  "execution_ready": execution_ready, "ready": execution_ready == "ready"})

    from .studio_sessions import register as register_studio_sessions
    register_studio_sessions(server, instance_id=studio_instance_id)
    server._zura_comfylink_registered = True
