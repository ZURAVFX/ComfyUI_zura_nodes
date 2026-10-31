"""Bind an artist-uploaded still as the approved-source opening input."""

from __future__ import annotations

import hashlib
import copy
import re
import shutil
from pathlib import Path


_ACTIVE_ACTION_STATES = {"waiting", "submitting", "queued", "running", "interrupted"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bind_uploaded_opening(
    project,
    uploaded,
    input_directory,
    *,
    assert_approved,
    check_asset,
    media_url,
    store=None,
):
    """Copy an approved image into project storage and reset opening approval.

    Returns True when project state changed. Does no generation, queue, or
    ComfyUI work. The callback arguments keep this module importable without
    loading Studio's ComfyUI runtime.
    """
    actions = project.get("actions") or []
    if project.get("phase") == "working" or (actions and actions[-1].get("state") in _ACTIVE_ACTION_STATES):
        raise ValueError("Wait for the current job before changing the opening image.")

    assert_approved(project)
    if (not isinstance(uploaded, dict) or uploaded.get("kind") != "asset"
            or uploaded.get("asset_kind") != "image"):
        raise ValueError("Choose an uploaded image for the opening frame.")
    expected_sha = uploaded.get("sha")
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha):
        raise ValueError("The uploaded image has no valid content hash. Upload it again.")
    from .ltx25_hdr_input import opening_identity, resolve_asset
    resolve_asset(uploaded, project.get("config", {}), store, check_asset)
    marker = copy.deepcopy(uploaded.get("native_hdr"))
    identity = opening_identity(expected_sha, marker)

    input_root = Path(input_directory).resolve()
    asset_root = (input_root / "genj_studio").resolve()
    source = Path(check_asset(uploaded)).resolve(strict=True)
    if not source.is_relative_to(asset_root) or not source.is_file() or _sha256(source) != expected_sha:
        raise ValueError("The uploaded image is outside Studio storage or has changed. Upload it again.")

    suffix = source.suffix.lower()
    if suffix not in _IMAGE_EXTENSIONS:
        raise ValueError("Choose a PNG, JPEG or WebP image.")
    project_id = project.get("id", "")
    if not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise ValueError("Choose a valid saved shot before setting its opening image.")

    relative = Path("genj_studio") / project_id / f"opening_uploaded_{expected_sha}{suffix}"
    destination = (input_root / relative).resolve()
    project_root = (asset_root / project_id).resolve()
    if not destination.is_relative_to(project_root) or not project_root.is_relative_to(asset_root):
        raise ValueError("The opening image destination is outside Studio storage.")

    current = project.get("opening_input") or {}
    if (current.get("file") == relative.as_posix() and current.get("sha") == expected_sha
            and current.get("native_hdr") == marker
            and project.get("opening_key") == identity and destination.is_file()
            and _sha256(destination) == expected_sha):
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        shutil.copyfile(source, temporary)
        if _sha256(temporary) != expected_sha:
            raise ValueError("The opening image changed while it was being copied. Upload it again.")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)

    relative_text = relative.as_posix()
    project.update(
        opening_input={"file": relative_text, "sha": expected_sha,
                       **({"native_hdr": marker} if marker is not None else {})},
        opening_key=identity,
        opening_url=media_url({
            "filename": destination.name,
            "subfolder": f"genj_studio/{project_id}",
            "type": "input",
        }),
        opening_approval=None,
        phase="opening",
        draft_task=None,
        accepted_draft=None,
    )
    project.pop("ltx25_run", None)
    return True


def register(studio, routes, response):
    """Register the optional starting-image endpoint beside Studio routes."""
    from aiohttp import web
    import folder_paths

    @routes.post("/zura/studio/projects/{identity}/opening")
    @routes.post("/genj/studio/projects/{identity}/opening")
    @response
    async def use_starting_image(request):
        from .studio import assert_approved, check_asset, media_url, public_project

        body = await request.json()
        asset_id = body.get("asset_id")
        if not isinstance(asset_id, str) or not re.fullmatch(r"[a-f0-9]{32}", asset_id):
            raise ValueError("Upload a starting image first.")
        async with studio.lock:
            project = studio.store.load(request.match_info["identity"])
            uploaded = studio.store.load(asset_id)
            if uploaded.get("id") != asset_id:
                raise ValueError("The uploaded image could not be verified. Upload it again.")
            changed = bind_uploaded_opening(
                project,
                uploaded,
                folder_paths.get_input_directory(),
                assert_approved=assert_approved,
                check_asset=check_asset,
                media_url=media_url,
                store=studio.store,
            )
            if changed or project.get("look_mode") != "ready" or (project.get("starting_asset") or {}).get("id") != asset_id:
                project.update(look_mode="ready", starting_asset=dict(uploaded))
                studio.store.save(project)
            return web.json_response(public_project(project))

