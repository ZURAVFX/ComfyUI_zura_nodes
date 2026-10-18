"""Small, CPU-only advisory analysis of uploaded source clips.

Detection never changes a model route or proves that a scene has no people.
No media or inference requests leave this machine.
"""
import asyncio
from collections import OrderedDict
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import threading

RECIPE = "yolov10-person-cpu-v1"
MAX_SAMPLES = 5
_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()
MAX_CACHE = 32


def interval(start, duration):
    start, duration = float(start), float(duration)
    if not math.isfinite(start) or not math.isfinite(duration) or not 0 <= start <= 86400 or not 0.1 <= duration <= 30:
        raise ValueError("Choose a finite clip start and a duration between 0.1 and 30 seconds.")
    return start, duration


def sample_times(start, duration):
    start, duration = interval(start, duration)
    # Stay inside the interval, including for clips ending exactly at EOF.
    return [start + duration * (i + 0.5) / MAX_SAMPLES for i in range(MAX_SAMPLES)]


def source_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analysis_key(sha, model_path, start, duration, viewport=False):
    start, duration = interval(start, duration)
    model = Path(model_path) if model_path else None
    stamp = None
    if model and model.is_file():
        stat = model.stat()
        stamp = [str(model.resolve()), stat.st_size, stat.st_mtime_ns]
    value = [RECIPE, sha, start, duration, bool(viewport), stamp]
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


def person_scores(output):
    """Only accept YOLOv10 post-NMS xyxy, confidence, class-id rows."""
    import numpy as np
    rows = np.asarray(output)
    if rows.ndim == 3 and rows.shape[0] == 1:
        rows = rows[0]
    if rows.ndim != 2 or rows.shape[1] != 6 or not np.isfinite(rows).all():
        raise ValueError("The installed detector output is unsupported.")
    found = []
    for x1, y1, x2, y2, score, class_id in rows:
        if class_id != 0 or not 0.4 <= score <= 1:
            continue
        # Reject tiny, inverted or substantially out-of-raster boxes.
        x1, y1, x2, y2 = [max(0., min(640., float(v))) for v in (x1, y1, x2, y2)]
        if x2 - x1 >= 8 and y2 - y1 >= 8 and (x2 - x1) * (y2 - y1) >= 640 * 640 * 0.001:
            found.append(float(score))
    return found


def read_frames(path, times):
    """Seek independently; retain just one decoded frame at a time."""
    import av
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError("The source has no video track.")
        stream = container.streams.video[0]
        stream.thread_count = 2
        origin = float((stream.start_time or 0) * stream.time_base)
        for target in times:
            container.seek(int((target + origin) / stream.time_base), stream=stream, backward=True)
            for frame in container.decode(stream):
                if frame.pts is not None and float(frame.pts * stream.time_base) + 1e-6 >= target + origin:
                    yield frame.to_image()
                    break


def cpu_runner(model_path):
    import numpy as np
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
    inputs = session.get_inputs()
    if len(inputs) != 1 or inputs[0].shape != [1, 3, 640, 640] or inputs[0].type != "tensor(float)":
        raise ValueError("The installed detector input is unsupported.")
    def run(image):
        from PIL import Image
        rgb = image.convert("RGB").resize((640, 640), Image.Resampling.BILINEAR)
        tensor = np.asarray(rgb, dtype=np.float32).transpose(2, 0, 1)[None] / 255.
        outputs = session.run(None, {inputs[0].name: tensor})
        if len(outputs) != 1:
            raise ValueError("The installed detector output is unsupported.")
        return outputs[0]
    return run


def analyze(path, model_path, start=0., duration=5., *, viewport=False, runner=None, frame_reader=None):
    start, duration = interval(start, duration)
    sha = source_sha(path)
    key = analysis_key(sha, model_path, start, duration, viewport)
    injected = runner is not None or frame_reader is not None
    if not injected:
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached is not None:
                _CACHE.move_to_end(key)
                return copy.deepcopy(cached)
    result = {"status": "unknown", "reason": "People detection is unavailable.", "key": key,
              "recipe": RECIPE, "source_sha": sha, "start": start, "duration": duration,
              "sampled_frames": 0, "person_frames": 0, "confidence": None, "advisory": True}
    if viewport:
        result["reason"] = "Grey viewport figures cannot be reliably recognised. Native layout guidance is used."
    elif not runner and (not model_path or not Path(model_path).is_file()):
        result["reason"] = "Optional people detector is not installed."
    else:
        try:
            inference = runner or cpu_runner(model_path)
            scores = []
            for index, frame in enumerate((frame_reader or read_frames)(path, sample_times(start, duration))):
                if index >= MAX_SAMPLES:
                    break
                detections = person_scores(inference(frame))
                result["sampled_frames"] += 1
                if detections:
                    result["person_frames"] += 1
                    scores.extend(detections)
            if result["sampled_frames"] != MAX_SAMPLES:
                result["reason"] = "The selected interval could not be fully sampled."
            elif scores:
                result.update(status="people", reason="People found in sampled frames.", confidence=max(scores))
            else:
                result.update(status="objects", reason="No people found in sampled frames.")
        except Exception:
            # Unsupported exports and absent optional runtime packages are advisory failures.
            result.update(status="unknown", reason="People detection could not be completed.", confidence=None)
    if not injected:
        with _CACHE_LOCK:
            _CACHE[key] = copy.deepcopy(result)
            _CACHE.move_to_end(key)
            while len(_CACHE) > MAX_CACHE:
                _CACHE.popitem(last=False)
    return result


def detector_path():
    import folder_paths
    try:
        found = folder_paths.get_full_path("detection", "yolov10m.onnx")
        if found and Path(found).is_file():
            return Path(found)
    except (KeyError, ValueError):
        pass
    # Supports existing installations without adding a package or downloading weights.
    for root in folder_paths.get_folder_paths("custom_nodes"):
        for relative in ("ComfyUI-WanAnimatePreprocess/models/yolov10m.onnx",
                         "ComfyUI-WanAnimatePreprocess/models/detection/yolov10m.onnx"):
            candidate = Path(root) / relative
            if candidate.is_file():
                return candidate
    return None


def register(studio, routes, response):
    from aiohttp import web

    @routes.post("/zura/studio/content")
    @routes.post("/genj/studio/content")
    @response
    async def inspect_content(request):
        from .studio import check_asset
        body = await request.json()
        identity = body.get("asset_id")
        if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("Upload a source video first.")
        start, duration = interval(body.get("start", 0), body.get("duration", 5))
        viewport = body.get("viewport", False)
        if type(viewport) is not bool:
            raise ValueError("Choose a valid viewport setting.")
        async with studio.lock:
            asset = studio.store.load(identity)
            if asset.get("id") != identity or asset.get("kind") != "asset" or asset.get("asset_kind") != "video":
                raise ValueError("Choose an uploaded source video.")
            length = float(asset.get("duration", 0))
            if not math.isfinite(length) or length <= 0 or start + duration > length + 0.05:
                raise ValueError("Choose a clip interval inside the uploaded source video.")
            path = await asyncio.to_thread(check_asset, asset)
        result = await asyncio.to_thread(analyze, path, detector_path(), start, duration, viewport=viewport)
        async with studio.lock:
            current = studio.store.load(identity)
            await asyncio.to_thread(check_asset, current)
            if current.get("sha") != result["source_sha"]:
                raise ValueError("The source changed during analysis. Upload it again.")
            current["content_analysis"] = result
            studio.store.save(current)
        return web.json_response(result)
