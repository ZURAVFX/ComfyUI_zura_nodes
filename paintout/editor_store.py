"""Persistent Paintout edits and bounded native SAM mask passes."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import threading
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, maximum_filter

_LOCK = threading.RLock()
_ID = re.compile(r"^[a-f0-9]{16,32}$")
_MAX_JSON = 4 * 1024 * 1024
_OPERATIONS = ("replace", "add", "protect", "absent")


class RevisionConflict(ValueError):
    pass


def project_root():
    import folder_paths
    root = Path(folder_paths.get_user_directory()) / "zura" / "paintout" / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def project_dir(project):
    if not isinstance(project, str) or not _ID.fullmatch(project):
        raise ValueError("Choose a valid Paintout project.")
    return project_root() / project


def _atomic_json(path, value):
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_JSON:
        raise ValueError("The Paintout project is too large to save.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read(project):
    path = project_dir(project) / "project.json"
    if not path.is_file():
        raise ValueError("This Paintout project was not found.")
    return json.loads(path.read_text(encoding="utf-8"))


def _expect(document, expected):
    if expected is not None and int(expected) >= 0 and document["revision"] != int(expected):
        raise RevisionConflict("This project changed while the operation was running. Reload the latest edit before applying it.")


def load_project(project):
    with _LOCK:
        return _read(project)


def save_project(project=None, data=None, expected_revision=None):
    if data is not None and not isinstance(data, dict):
        raise ValueError("Project data must be an object.")
    with _LOCK:
        if project is None:
            if data is None:
                raise ValueError("Provide project data to create a project.")
            project = secrets.token_hex(12)
            document = dict(id=project, revision=0, data={}, mask_revision=None, mask_history=[])
        else:
            document = _read(project)
            _expect(document, expected_revision)
            if data is None:
                return document
            if expected_revision is None:
                raise RevisionConflict("Save the project with its current revision.")
        document["data"] = data
        document["revision"] += 1
        _atomic_json(project_dir(project) / "project.json", document)
        return document


def select_mask_revision(project, mask_revision, expected_revision):
    with _LOCK:
        document = _read(project)
        _expect(document, expected_revision)
        if expected_revision is None:
            raise RevisionConflict("Select a mask with the current project revision.")
        allowed = {entry["revision"] for entry in document["mask_history"]}
        if mask_revision is not None and mask_revision not in allowed:
            raise ValueError("That mask revision does not belong to this project.")
        document["mask_revision"] = mask_revision
        document["revision"] += 1
        _atomic_json(project_dir(project) / "project.json", document)
        return document


def effective_mask(mask, grow=0, feather=0, protection=None):
    grow, feather = int(grow), int(feather)
    if not 0 <= grow <= 512 or not 0 <= feather <= 512:
        raise ValueError("Grow and edge softness must be between 0 and 512 source pixels.")
    binary = np.asarray(mask) > .001
    if binary.ndim != 2:
        raise ValueError("Expected one two-dimensional mask.")
    if not binary.any():
        return np.zeros(binary.shape, dtype=np.float32)
    expanded = maximum_filter(binary, size=2 * grow + 1) if grow else binary
    distance = distance_transform_edt(~expanded)
    alpha = np.clip(1 - distance / max(feather, 1), 0, 1) if feather else expanded.astype(np.float32)
    alpha[expanded] = 1
    if protection is not None:
        alpha[np.asarray(protection) > .001] = 0
    return alpha.astype(np.float32)


def merge_mask(previous, incoming, operation):
    if operation not in _OPERATIONS:
        raise ValueError("Choose Replace, Add, Protect or Absent.")
    previous = np.asarray(previous, dtype=np.float32)
    incoming = np.asarray(incoming, dtype=np.float32)
    if previous.shape != incoming.shape or previous.ndim != 2:
        raise ValueError("Correction masks must match the original footage dimensions.")
    if not np.isfinite(incoming).all() or not np.isfinite(previous).all():
        raise ValueError("The correction contains invalid mask values.")
    incoming = incoming.clip(0, 1)
    if operation == "replace":
        return incoming
    if operation == "add":
        return np.maximum(previous, incoming)
    if operation == "protect":
        return previous * (1 - incoming)
    return np.zeros_like(previous)


def _mask_manifest(project, revision=None):
    document = _read(project)
    selected = document["mask_revision"] if revision is None else revision
    if selected is None:
        return None
    if not any(entry["revision"] == selected for entry in document["mask_history"]):
        raise ValueError("That mask revision does not belong to this project.")
    return json.loads((project_dir(project) / "masks" / str(selected) / "manifest.json").read_text(encoding="utf-8"))


def _load_mask(path, width, height):
    if not path:
        return np.zeros((height, width), dtype=np.float32)
    with Image.open(path) as image:
        if image.size != (width, height):
            raise ValueError("The saved mask does not match the source dimensions.")
        return np.asarray(image.convert("L"), dtype=np.float32) / 255


def read_project_mask(project, frame, revision=None, grow=0, feather=0):
    if int(frame) < 0:
        raise ValueError("Choose a source frame starting at zero.")
    manifest = _mask_manifest(project, revision)
    if manifest is None:
        raise ValueError("Create a removal mask first.")
    if int(frame) >= manifest["source_count"]:
        raise ValueError("The mask frame is outside the source.")
    mask = _load_mask(manifest["files"].get(str(int(frame))), manifest["width"], manifest["height"])
    protection = _load_mask(manifest.get("protection_files", {}).get(str(int(frame))), manifest["width"], manifest["height"])
    return effective_mask(mask, grow, feather, protection)


def mask_descriptor(project, revision=None):
    manifest = _mask_manifest(project, revision)
    if manifest is None:
        raise ValueError("Create a removal mask before rendering.")
    empty = project_dir(project) / "masks" / "empty.png"
    if not empty.is_file():
        Image.new("L", (manifest["width"], manifest["height"])).save(empty)
    files = [manifest["files"].get(str(i), str(empty)) for i in range(manifest["source_count"])]
    protection_files = [manifest.get("protection_files", {}).get(str(i), str(empty)) for i in range(manifest["source_count"])]
    return dict(kind="painted_tracking", start=0, files=files, protection_files=protection_files, width=manifest["width"], height=manifest["height"],
                count=manifest["source_count"], covered_frames=sorted(int(i) for i in manifest['files']), source=manifest["source"], project=project, revision=manifest["revision"])


def save_mask_choices(project, identity, frame, masks, operation, expected_revision, metadata=None):
    """Keep separate detections for explicit choice; never union or commit them."""
    masks = np.asarray(masks)
    if masks.ndim != 3 or not 2 <= len(masks) <= 24 or not np.isfinite(masks).all():
        raise ValueError("Use a more specific description to find up to 24 subject choices.")
    width, height = identity['width'], identity['height']
    if not 0 <= int(frame) < identity['count'] or width * height > 40_000_000 or operation not in ('replace', 'add', 'protect'):
        raise ValueError("Choose a valid subject frame and correction operation.")
    with _LOCK:
        document = _read(project)
        _expect(document, expected_revision)
        token = secrets.token_hex(12)
        directory = project_dir(project) / 'selections' / token
        directory.mkdir(parents=True)
        try:
            choices = []
            for mask in masks:
                pixels = (mask >= .5).astype(np.uint8) * 255
                if not pixels.any():
                    continue
                index = len(choices)
                path = directory / f'{index}.png'
                Image.fromarray(pixels).resize((width, height), Image.Resampling.NEAREST).save(path)
                choices.append(dict(index=index, path=str(path)))
            if len(choices) < 2:
                raise ValueError("Several detections were empty. Refine the subject with an Include point.")
            selection = dict(token=token, project=project, frame=int(frame), source=identity,
                             mask_revision=document['mask_revision'], operation=operation,
                             metadata=metadata or {}, choices=choices)
            _atomic_json(directory / 'manifest.json', selection)
            return selection
        except BaseException:
            for child in directory.iterdir():
                child.unlink()
            directory.rmdir()
            raise


def choose_mask_candidate(body):
    from .browser import checked_path
    from .paintout import describe
    project, token = body['project'], body['token']
    if not isinstance(token, str) or not _ID.fullmatch(token):
        raise ValueError("Choose a subject from the current detection result.")
    with _LOCK:
        document = _read(project)
        if body.get('expected_revision') is None:
            raise RevisionConflict("Reload the project before choosing a subject.")
        _expect(document, body['expected_revision'])
        selection = json.loads((project_dir(project) / 'selections' / token / 'manifest.json').read_text(encoding='utf-8'))
        source = str(checked_path(body['source']))
        if str(checked_path(document.get('data', {}).get('draft', {}).get('source'))) != source:
            raise ValueError('Choose a subject in its original shot project.')
        identity = source_identity(source, describe(source))
        if identity != selection['source'] or int(body['frame']) != selection['frame']:
            raise ValueError("This subject choice belongs to different footage or a different source frame.")
        if document['mask_revision'] != selection['mask_revision']:
            raise RevisionConflict("The mask changed after these subjects were detected. Preview the selection again.")
        index = body['index']
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(selection['choices']):
            raise ValueError("Choose one of the detected subjects.")
        candidate = project_dir(project) / 'selections' / token / f'{index}.png'
        commit_mask_pass(project, identity, {selection['frame']: str(candidate)}, selection['operation'],
                         document['revision'], {**selection['metadata'], 'frame':selection['frame'],
                         'method':'subject-choice', 'choice':index}, preserve_protection=True)
        return project_response(_read(project))


def project_response(document):
    manifest = _mask_manifest(document['id'], document['mask_revision']) if document['mask_revision'] is not None else None
    return {**document, 'mask_coverage': sorted(int(i) for i in manifest['files']) if manifest else [],
            'mask_review_ranges': manifest.get('review_ranges', []) if manifest else [],
            'mask_seed': _mask_seed_response(document['id'], manifest)}


def _mask_seed_response(project, manifest):
    """Grant only the immutable incoming seed, never a cumulative ADD result."""
    seed = manifest.get('seed') if manifest else None
    if not seed:
        return None
    expected = project_dir(project) / 'masks' / str(manifest['revision']) / 'seed.png'
    path = Path(seed['path'])
    if (path.is_symlink() or path.resolve(strict=True) != expected.resolve(strict=True)
            or not path.resolve(strict=True).is_relative_to(project_dir(project).resolve(strict=True))):
        raise ValueError('The saved tracking seed does not belong to this mask revision.')
    if not isinstance(seed['frame'], int) or isinstance(seed['frame'], bool) or not 0 <= seed['frame'] < manifest['source_count']:
        raise ValueError('The saved tracking seed has an invalid source frame.')
    if hashlib.sha256(path.read_bytes()).hexdigest() != seed['sha256']:
        raise ValueError('The saved tracking seed changed. Preview the subject again.')
    with Image.open(path) as image:
        if image.format != 'PNG' or image.size != (manifest['width'], manifest['height']):
            raise ValueError('The saved tracking seed does not match the source dimensions.')
    from .browser import grant
    return dict(url=grant(path), frame=seed['frame'], mask_revision=manifest['revision'],
                operation=manifest['operation'])


def _mask_review_ranges(area_counts, absent_frames, source_pixels):
    """Advisory area checks, never segmentation confidence or automatic occlusion.

    Compare consecutive covered source frames only. A 2.5x area change must also
    change at least max(16 pixels, 0.1% of the source). Empty runs following a
    visible mask and their reappearance need review. Explicit artist-marked
    absence breaks comparison. One integer per frame bounds retained memory.
    """
    absent = set(int(frame) for frame in absent_frames)
    minimum = max(16, int(np.ceil(source_pixels * .001)))
    labels = {'area_change': 'Mask area changed sharply',
              'empty_after_visible': 'Mask disappeared after a visible subject',
              'reappeared': 'Mask reappeared after an unmarked gap'}
    findings = []
    previous_frame = previous_area = None
    empty_run = False
    for frame, area in sorted((int(frame), int(area)) for frame, area in area_counts.items()):
        if frame in absent or previous_frame is None or frame != previous_frame + 1:
            empty_run = False
        else:
            reason = None
            if area == 0 and (previous_area > 0 or empty_run):
                reason = 'empty_after_visible'
                empty_run = True
            elif area > 0 and empty_run:
                reason = 'reappeared'
                empty_run = False
            elif area > 0 and previous_area > 0 and abs(area - previous_area) >= minimum and max(area, previous_area) >= 2.5 * min(area, previous_area):
                reason = 'area_change'
            if reason:
                if findings and findings[-1]['reason'] == reason and findings[-1]['end_frame'] == frame - 1:
                    findings[-1]['end_frame'] = frame
                else:
                    findings.append(dict(start_frame=frame, end_frame=frame, status='needs_review',
                                         reason=reason, label=labels[reason]))
        previous_frame, previous_area = (None, None) if frame in absent else (frame, area)
    return findings


def source_identity(source, description):
    path = Path(source).resolve(strict=True)
    files = description.get("files") or [str(path)]
    digest = hashlib.sha256(str(path).encode())
    for file in files:
        stat = Path(file).stat()
        digest.update(f"{file}\0{stat.st_size}\0{stat.st_mtime_ns}".encode())
    return dict(path=str(path), fingerprint=digest.hexdigest(), width=int(description["width"]),
                height=int(description["height"]), count=int(description["count"]))


def commit_mask_pass(project, identity, frame_masks, operation, expected_revision, metadata=None, preserve_protection=False):
    if not frame_masks:
        raise ValueError("The correction has no frames to save.")
    with _LOCK:
        document = _read(project)
        _expect(document, expected_revision)
        previous = _mask_manifest(project)
        if previous and previous["source"] != identity:
            raise ValueError("The source changed. Start a new mask project for this footage.")
        files = dict(previous["files"]) if previous else {}
        protections = dict(previous.get("protection_files", {})) if previous else {}
        area_counts = dict(previous.get('area_counts', {})) if previous else {}
        absent_frames = set(previous.get('absent_frames', [])) if previous else set()
        revision = document["revision"] + 1
        target = project_dir(project) / "masks" / str(revision)
        target.parent.mkdir(parents=True, exist_ok=True)
        width, height, count = identity["width"], identity["height"], identity["count"]
        # Stage an immutable revision; a failed correction must never poison retries.
        staging = Path(tempfile.mkdtemp(prefix="pending_revision_", dir=target.parent))
        published = False
        seed = None
        seed_frame = (metadata or {}).get('frame')
        try:
            for index, mask in sorted(frame_masks.items()):
                index = int(index)
                if not 0 <= index < count:
                    raise ValueError("A correction frame is outside the source footage.")
                old = _load_mask(files.get(str(index)), width, height)
                incoming = _load_mask(mask, width, height) if isinstance(mask, (str, Path)) else np.asarray(mask)
                if incoming.shape != (height, width):
                    raise ValueError("Correction masks must match the original footage dimensions.")
                result = merge_mask(old, incoming, operation)
                if operation != 'absent' and isinstance(seed_frame, int) and not isinstance(seed_frame, bool) and index == seed_frame:
                    # ADD commits merge with existing coverage. Retain its incoming
                    # subject separately so a subsequent track never seeds that union.
                    seed_path = staging / 'seed.png'
                    Image.fromarray((np.asarray(incoming) >= .5).astype(np.uint8) * 255).save(seed_path)
                    seed = dict(frame=index, path=str(target / 'seed.png'),
                                sha256=hashlib.sha256(seed_path.read_bytes()).hexdigest())
                protected = _load_mask(protections.get(str(index)), width, height)
                if operation == "protect":
                    protected = np.maximum(protected, np.asarray(incoming).clip(0, 1))
                elif operation in ("replace", "absent") and not preserve_protection:
                    protected = np.zeros_like(old)
                # Use the final saved mask and protection, not an inference proxy.
                saved = np.round(result * 255).astype(np.uint8)
                saved_protection = np.round(protected * 255).astype(np.uint8)
                area_counts[str(index)] = int(np.count_nonzero((saved > 0) & (saved_protection == 0)))
                if operation == 'absent':
                    absent_frames.add(index)
                elif operation != 'protect':
                    absent_frames.discard(index)
                for name, pixels, mapping in (("mask", result, files), ("protect", protected, protections)):
                    filename = f"{name}_{index:08d}.png"
                    Image.fromarray(np.round(pixels * 255).astype(np.uint8), mode="L").save(staging / filename)
                    mapping[str(index)] = str(target / filename)
            # Upgrade legacy revisions incrementally with bounded, one-frame reads.
            for index, path in files.items():
                if index not in area_counts:
                    pixels = _load_mask(path, width, height)
                    protected = _load_mask(protections.get(index), width, height)
                    area_counts[index] = int(np.count_nonzero((pixels > .001) & (protected <= .001)))
            review_ranges = _mask_review_ranges(area_counts, absent_frames, width * height)
            manifest = dict(revision=revision, source=identity, source_count=count, width=width, height=height,
                            files=files, protection_files=protections, operation=operation, metadata=metadata or {},
                            area_counts=area_counts, absent_frames=sorted(absent_frames), review_ranges=review_ranges,
                            seed=seed)
            _atomic_json(staging / "manifest.json", manifest)
            staging.rename(target)
            published = True
            document["mask_history"].append(dict(revision=revision, operation=operation,
                                                start_frame=min(frame_masks), end_frame=max(frame_masks), metadata=metadata or {}))
            document["mask_revision"] = revision
            document["revision"] += 1
            _atomic_json(project_dir(project) / "project.json", document)
        except BaseException:
            shutil.rmtree(target if published else staging, ignore_errors=True)
            raise
        summary = dict(project=project, revision=revision, project_revision=document["revision"], path=str(target), width=width,
                       height=height, start_frame=min(frame_masks), frame_count=max(frame_masks) - min(frame_masks) + 1)
        if seed:
            summary.update(seed_file=seed['path'], seed_frame=seed['frame'], seed_revision=revision)
        return summary


def _coords(value, width, height):
    points = json.loads(value or "[]")
    if not isinstance(points, list) or len(points) > 256:
        raise ValueError("Use up to 256 Include or Exclude points.")
    for point in points:
        if not isinstance(point, dict) or set(point) != {"x", "y"}:
            raise ValueError("Mask points need x and y source coordinates.")
        if not all(isinstance(point[k], (int, float)) and np.isfinite(point[k]) for k in ("x", "y")):
            raise ValueError("Mask point coordinates must be finite numbers.")
        if not 0 <= point["x"] < width or not 0 <= point["y"] < height:
            raise ValueError("A mask point is outside the source image.")
    return points


def _decode_paint(value, width, height):
    if not isinstance(value, str) or len(value) > 64 * 1024 * 1024:
        raise ValueError("The painted mask is too large.")
    encoded = value.split(",", 1)[1] if value.startswith("data:image/png;base64,") else value
    with Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))) as image:
        if image.format != "PNG" or image.size != (width, height):
            raise ValueError("Paint a PNG mask matching the original footage size.")
        return np.asarray(image.convert("L"), dtype=np.float32) / 255


def _frame_batch(description, indices, colour_space, proxy_size):
    import torch
    from .paintout import frames, working, resize
    batch = []
    for image in frames(description, min(indices), len(indices)):
        tensor = torch.from_numpy(image)[None]
        height, width = tensor.shape[1:3]
        scale = min(1., proxy_size / max(height, width))
        tensor = resize(tensor, max(1, round(height * scale)), max(1, round(width * scale)))
        batch.append(working(tensor, colour_space, "SDR (sRGB)")[0].clamp(0, 1))
    if indices[0] > indices[-1]:
        batch.reverse()
    return torch.stack(batch)


def _native_masks(images, model, initial_mask):
    import nodes
    tracking = nodes.NODE_CLASS_MAPPINGS["SAM3_VideoTrack"].execute(images=images, model=model,
        initial_mask=initial_mask, detection_threshold=.5, max_objects=1, detect_interval=1)[0]
    return nodes.NODE_CLASS_MAPPINGS["SAM3_TrackToMask"].execute(track_data=tracking, object_indices="0")[0]


def _sam_subject_conditioning(conditioning):
    """Request separate native text detections instead of its one-object fallback.

    Native SAM3 reads sam3_multi_cond from the first metadata row. Copy the
    containers we change while retaining embedding/mask tensors by reference.
    Keep a total budget of 24 detections, matching the explicit subject chooser.
    """
    if not conditioning:
        raise ValueError('Describe a subject or add an Include point first.')
    result = [[row[0], dict(row[1])] for row in conditioning]
    metadata = result[0][1]
    existing = metadata.get('sam3_multi_cond')
    if existing is None:
        entries = [dict(cond=result[0][0], attention_mask=metadata.get('attention_mask'), max_detections=24)]
    else:
        entries = []
        remaining = 24
        for item in existing:
            if not remaining:
                break
            entry = dict(item)
            entry['max_detections'] = min(remaining, max(1, int(entry.get('max_detections', 1))))
            remaining -= entry['max_detections']
            entries.append(entry)
    metadata['sam3_multi_cond'] = entries
    return result


class ZuraPaintoutMaskPass:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source": ("STRING", {"default": ""}), "project": ("STRING", {"default": ""}),
            "frame": ("INT", {"default": 0, "min": 0}), "start_frame": ("INT", {"default": 0, "min": 0}),
            "frame_count": ("INT", {"default": 1, "min": 1, "max": 993}), "colour_space": ("STRING", {"default": "auto"}),
            "operation": (list(_OPERATIONS),), "positive_coords": ("STRING", {"default": "[]"}),
            "negative_coords": ("STRING", {"default": "[]"}), "text": ("STRING", {"default": ""}),
            "direction": (["forward", "backward", "both"],)},
            "optional": {"model": ("MODEL",), "conditioning": ("CONDITIONING",),
                         "paint_mask": ("STRING", {"default": ""}), "expected_revision": ("INT", {"default": -1})}}
    RETURN_TYPES = ("ZURA_MASK",)
    FUNCTION = "run"
    CATEGORY = "Zura/Paintout"
    OUTPUT_NODE = True

    def run(self, source, project, frame, start_frame, frame_count, colour_space, operation,
            positive_coords="[]", negative_coords="[]", text="", direction="both", model=None,
            conditioning=None, paint_mask="", expected_revision=-1):
        import torch
        import torch.nn.functional as functional
        from .browser import checked_path
        from .paintout import describe, selected_space
        if operation not in _OPERATIONS or direction not in ("forward", "backward", "both"):
            raise ValueError("Choose a valid mask correction operation and direction.")
        description = describe(str(checked_path(source)))
        identity = source_identity(source, description)
        start_frame, frame, frame_count = int(start_frame), int(frame), int(frame_count)
        last = start_frame + frame_count - 1
        if frame_count < 1 or frame_count > 993 or start_frame < 0 or last >= identity["count"] or not start_frame <= frame <= last:
            raise ValueError("Choose a mask frame inside the selected source range.")
        document = load_project(project)
        _expect(document, expected_revision)
        base = document["revision"]
        width, height = identity["width"], identity["height"]
        points = _coords(positive_coords, width, height)
        negatives = _coords(negative_coords, width, height)
        with tempfile.TemporaryDirectory(prefix="pending_", dir=project_dir(project)) as pending:
            if operation == "absent":
                empty = np.zeros((height, width), dtype=np.float32)
                masks = {index: empty for index in range(start_frame, last + 1)}
            else:
                space = selected_space(description, colour_space)
                proxy = _frame_batch(description, [frame], space, 1024)
                ph, pw = proxy.shape[1:3]
                if paint_mask:
                    painted_source = _decode_paint(paint_mask, width, height)
                    initial = torch.from_numpy(painted_source)[None]
                    initial = functional.interpolate(initial[:, None], size=(ph, pw), mode="nearest")[:, 0]
                else:
                    if model is None:
                        raise ValueError("Install and select the native SAM3 model before detecting a subject.")
                    if not points and conditioning is None:
                        raise ValueError("Describe a subject or add an Include point first.")
                    if negatives and not points:
                        raise ValueError("Add an Include point before refining the subject with Exclude points.")
                    import nodes
                    kwargs = dict(model=model, image=proxy, threshold=.5, refine_iterations=2, individual_masks=True)
                    if points:
                        scale = lambda items: json.dumps([dict(x=min(pw - 1, round(p["x"] * pw / width)), y=min(ph - 1, round(p["y"] * ph / height))) for p in items])
                        kwargs.update(positive_coords=scale(points), negative_coords=scale(negatives))
                    else:
                        kwargs["conditioning"] = _sam_subject_conditioning(conditioning)
                    initial = nodes.NODE_CLASS_MAPPINGS["SAM3_Detect"].execute(**kwargs)[0]
                    if initial.ndim != 3:
                        raise ValueError("SAM3 returned an unsupported mask shape.")
                    if len(initial) > 1:
                        from .browser import grant
                        selection = save_mask_choices(project, identity, frame, initial.detach().cpu().numpy(),
                                                      operation, base, {'text':str(text)[:4000]})
                        choices = dict(project=project, token=selection['token'], frame=frame,
                                       choices=[{'index':row['index'], 'url':grant(row['path'])} for row in selection['choices']])
                        return {'ui':{'zura_mask_choices':[choices]}, 'result':({'kind':'selection_required'},)}
                    initial = initial[:1]
                if paint_mask and not initial.any() and painted_source.any():
                    # Preserve sub-proxy-pixel strokes for tracker seeding.
                    initial = functional.adaptive_max_pool2d(torch.from_numpy(painted_source)[None, None], (ph, pw))[:, 0]
                if not initial.any():
                    raise ValueError("No subject was selected. Add an Include point on a visible part of the subject.")
                full = lambda mask: functional.interpolate(mask[None, None].float(), size=(height, width), mode="bilinear", align_corners=False)[0, 0].cpu().numpy()
                def spool(index, mask):
                    path = Path(pending) / f"{index:08d}.png"
                    Image.fromarray(np.round(full(mask).clip(0, 1) * 255).astype(np.uint8)).save(path)
                    return str(path)
                if paint_mask:
                    seed_path = Path(pending) / f"{frame:08d}.png"
                    Image.fromarray(np.round(painted_source * 255).astype(np.uint8)).save(seed_path)
                    masks = {frame: str(seed_path)}
                else:
                    masks = {frame: spool(frame, initial[0])}
                if frame_count > 1:
                    if model is None:
                        raise ValueError("Select SAM3 to track the painted selection, or apply it to one frame.")
                    paths = []
                    if direction in ("forward", "both"):
                        paths.append(list(range(frame, last + 1)))
                    if direction in ("backward", "both"):
                        paths.append(list(range(frame, start_frame - 1, -1)))
                    for indices in paths:
                        seed = initial
                        for offset in range(0, max(0, len(indices) - 1), 31):
                            chunk = indices[offset:offset + 32]
                            if len(chunk) < 2:
                                continue
                            images = _frame_batch(description, chunk, space, 1024)
                            tracked = _native_masks(images, model, seed)
                            if len(tracked) != len(chunk):
                                raise ValueError("SAM3 returned the wrong number of tracked frames.")
                            for index, mask in zip(chunk[1:], tracked[1:]):
                                masks[index] = spool(index, mask)
                            seed = tracked[-1:]
            metadata = dict(frame=frame, direction=direction, positive_coords=points, negative_coords=negatives,
                            text=str(text)[:4000], base_revision=base)
            # Do not commit results for footage modified while inference was running.
            if source_identity(source, describe(source)) != identity:
                raise ValueError("The source footage changed while tracking. Reload it before applying this pass.")
            # Reselecting a subject is not an instruction to discard artist-painted
            # foreground protection in that section.
            summary = commit_mask_pass(project, identity, masks, operation, base, metadata, preserve_protection=True)
            seed = _mask_seed_response(project, _mask_manifest(project, summary['revision']))
            if seed:
                summary.update(seed_url=seed['url'], seed_frame=seed['frame'], seed_revision=seed['mask_revision'])
            return {"ui": {"zura_mask": [summary]}, "result": (mask_descriptor(project, summary["revision"]),)}



class ZuraPaintoutMaskSource:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"project": ("STRING", {"default": ""}), "revision": ("INT", {"default": -1, "min": -1})}}
    RETURN_TYPES = ("ZURA_MASK",)
    FUNCTION = "load"
    CATEGORY = "Zura/Paintout"

    def load(self, project, revision=-1):
        return (mask_descriptor(project, None if revision < 0 else revision),)


def _origin(request):
    from ..media_source import require_same_origin
    require_same_origin(request)


async def project_route(request):
    from aiohttp import web
    _origin(request)
    try:
        if request.content_length and request.content_length > _MAX_JSON:
            raise ValueError("The Paintout project is too large to save.")
        body = await request.json()
        document = await asyncio.to_thread(save_project, body.get("id"), body.get("data"), body.get("expected_revision"))
        return web.json_response(project_response(document), headers={"Cache-Control": "no-store"})
    except RevisionConflict as error:
        return web.json_response({"error": str(error)}, status=409)
    except (ValueError, OSError, TypeError) as error:
        return web.json_response({"error": str(error)}, status=400)


async def project_list_route(request):
    from aiohttp import web
    _origin(request)
    def listing():
        projects = []
        for path in project_root().glob('*/project.json'):
            try:
                document = _read(path.parent.name)
                draft = document.get('data', {}).get('draft', {})
                source = draft.get('source', '')
                if source:
                    projects.append(dict(id=document['id'], source=source, name=Path(source).name,
                                         updated=path.stat().st_mtime, frames=draft.get('frameCount')))
            except (ValueError, OSError, KeyError):
                continue
        return sorted(projects, key=lambda project: project['updated'], reverse=True)
    return web.json_response(await asyncio.to_thread(listing), headers={'Cache-Control': 'no-store'})


async def mask_select_route(request):
    from aiohttp import web
    _origin(request)
    try:
        body = await request.json()
        document = await asyncio.to_thread(select_mask_revision, body.get("project"), body.get("mask_revision"), body.get("expected_revision"))
        return web.json_response(project_response(document), headers={"Cache-Control": "no-store"})
    except RevisionConflict as error:
        return web.json_response({"error": str(error)}, status=409)
    except (ValueError, OSError, TypeError) as error:
        return web.json_response({"error": str(error)}, status=400)


async def mask_preview_route(request):
    from aiohttp import web
    _origin(request)
    try:
        mask = await asyncio.to_thread(read_project_mask, request.query.get("project"), int(request.query.get("frame", 0)),
            int(request.query["revision"]) if request.query.get("revision") else None, int(request.query.get("grow", 0)), int(request.query.get("feather", 0)))
        buffer = io.BytesIO()
        Image.fromarray(np.round(mask * 255).astype(np.uint8), mode="L").save(buffer, format="PNG")
        return web.Response(body=buffer.getvalue(), content_type="image/png", headers={"Cache-Control": "no-store"})
    except (ValueError, OSError, TypeError) as error:
        return web.json_response({"error": str(error)}, status=400)


def register_routes():
    from server import PromptServer
    server = getattr(PromptServer, "instance", None)
    if server is None:
        return
    existing = {(route.method, route.path) for route in server.routes}
    for method, path, handler in (("POST", "/zura/paintout/editor/project", project_route),
                                  ("GET", "/zura/paintout/editor/projects", project_list_route),
                                  ("POST", "/zura/paintout/editor/mask-select", mask_select_route),
                                  ("GET", "/zura/paintout/editor/mask-preview", mask_preview_route)):
        if (method, path) not in existing:
            getattr(server.routes, method.lower())(path)(handler)


from .paintout import ZuraPaintoutCrop


class ZuraPaintoutEditorCrop(ZuraPaintoutCrop):
    @classmethod
    def INPUT_TYPES(cls):
        schema = super().INPUT_TYPES()
        schema["required"]["mask_path"] = ("ZURA_MASK",)
        return schema

    def prepare(self, plate_path, mask_path, **kwargs):
        from .paintout import describe
        if not isinstance(mask_path, dict) or mask_path.get("source") != source_identity(plate_path, describe(plate_path)):
            raise ValueError("This mask belongs to different or modified footage. Reload the source and build its mask.")
        start, count = int(kwargs.get('start_frame', 0)), int(kwargs.get('frame_count', 1))
        covered = set(mask_path['covered_frames'])
        missing = [i for i in range(start, start + count) if i not in covered]
        if missing:
            raise ValueError(f'Track or mark absent the unreviewed mask section before rendering. First missing source frame: {missing[0]}.')
        return super().prepare(plate_path, mask_path, **kwargs)


NODE_CLASS_MAPPINGS = {"ZuraPaintoutMaskPass": ZuraPaintoutMaskPass, "ZuraPaintoutMaskSource": ZuraPaintoutMaskSource,
                       "ZuraPaintoutEditorCrop": ZuraPaintoutEditorCrop}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraPaintoutMaskPass": "Track Paintout Mask", "ZuraPaintoutMaskSource": "Load Paintout Mask Revision",
                              "ZuraPaintoutEditorCrop": "Prepare Paintout with Edited Mask"}
