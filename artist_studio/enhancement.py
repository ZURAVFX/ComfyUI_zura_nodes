"""Native, one-frame-at-a-time H3 720p delivery enhancement.

This module only builds a visible Comfy API graph and checks file provenance.
The actual upscaling is performed by installed Video Helper Suite and Comfy
upscale nodes; the small bridge node only turns a completed VHS file list into
a VIDEO after the full sequence has closed.
"""
import hashlib
import json
from pathlib import Path

import av


UPSCALE_MODEL = "2xNomosUni_esrgan_multijpg.pth"
SETUP_COMMAND = "Setup_H3_Enhancement_Windows.cmd"
NATIVE_NODES = ("VHS_BatchManager", "VHS_LoadVideoPath", "VHS_VideoCombine",
                "UpscaleModelLoader", "ImageUpscaleWithModel", "ImageScale")


def readiness():
    import folder_paths
    import nodes

    missing_nodes = [name for name in NATIVE_NODES if name not in nodes.NODE_CLASS_MAPPINGS]
    model = folder_paths.get_full_path("upscale_models", UPSCALE_MODEL)
    return {"ready": not missing_nodes and bool(model), "missing_nodes": missing_nodes,
            "model": UPSCALE_MODEL, "model_ready": bool(model), "setup_command": SETUP_COMMAND}


def generation_key(project):
    """Bind the private intermediate to the exact approved H3 configuration."""
    config = dict(project["config"])
    values = {
        "source": project["source"]["sha"],
        "character": (project.get("character") or {}).get("sha"),
        "review": project.get("review"),
        "prepared_key": project.get("prepared_key"),
        "opening": project.get("opening_key"),
        "audio": (project.get("audio") or {}).get("sha"),
        "config": config,
    }
    if config.get("workflow_mode") == "viewport" or project.get("viewport_render"):
        from .studio import _viewport_project
        values["viewport_references"] = [
            {"sha": asset.get("sha"), "role": asset.get("role"), "viewport_role": asset.get("viewport_role")}
            for asset in _viewport_project(project)["viewport_references"]]
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def target_dimensions(width, height, long_edge=1920):
    width, height, long_edge = int(width), int(height), int(long_edge)
    if min(width, height, long_edge) <= 0:
        raise ValueError("The source video dimensions are invalid.")
    scale = long_edge / max(width, height)
    return (max(2, round(width * scale / 2) * 2),
            max(2, round(height * scale / 2) * 2))


def h3_dimensions(width, height, long_edge):
    """Mirror GenjLoadReviewedShot's 64-pixel model canvas and export raster."""
    width, height, long_edge = int(width), int(height), int(long_edge)
    if min(width, height, long_edge) <= 0:
        raise ValueError("The source video dimensions are invalid.")
    scale = long_edge / max(width, height)
    model = (max(64, round(width * scale / 64) * 64),
             max(64, round(height * scale / 64) * 64))
    delivery = target_dimensions(width, height, long_edge)
    return model, delivery


def inspect_video(path, *, expected_frames=None, expected_width=None, expected_height=None,
                  expected_fps=24, expected_audio_tracks=None):
    """Read the actual encoded file; never infer delivery from graph settings."""
    path = Path(path)
    with av.open(str(path)) as container:
        videos = list(container.streams.video)
        audios = list(container.streams.audio)
        if len(videos) != 1:
            raise ValueError("The output must contain exactly one video stream.")
        stream = videos[0]
        width, height = int(stream.width), int(stream.height)
        fps = float(stream.average_rate or stream.base_rate or 0)
        frames = sum(1 for _ in container.decode(video=0))
    if expected_frames is not None and frames != int(expected_frames):
        raise ValueError("The output has an unexpected number of frames.")
    if expected_width is not None and width != int(expected_width):
        raise ValueError("The output has an unexpected raster width.")
    if expected_height is not None and height != int(expected_height):
        raise ValueError("The output has an unexpected raster height.")
    if expected_fps is not None and abs(fps - float(expected_fps)) > 0.01:
        raise ValueError("The output has an unexpected frame rate.")
    if expected_audio_tracks is not None and len(audios) != int(expected_audio_tracks):
        raise ValueError("The output has an unexpected soundtrack track count.")
    return {"width": width, "height": height, "frames": frames,
            "fps": fps, "audio_tracks": len(audios)}


def checked_output_path(asset, *, expected_subfolder=None):
    import folder_paths

    if (not isinstance(asset, dict) or asset.get("type") != "output"
            or asset.get("subfolder") not in ("genj/studio_intermediate", "genj/final")
            or (expected_subfolder is not None and asset.get("subfolder") != expected_subfolder)
            or not isinstance(asset.get("filename"), str)
            or Path(asset["filename"]).name != asset["filename"]):
        raise ValueError("The H3 base render has unexpected output provenance.")
    root = Path(folder_paths.get_output_directory()).resolve()
    path = (root / asset["subfolder"] / asset["filename"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("The H3 base render is missing from this ComfyUI output folder.")
    return path


def _video_from_vhs(filenames, output_root, filename_prefix):
    """Accept only the completed native VHS `(save_output, paths)` result.

    VHS places ``<prefix>_<counter>.mp4`` beside the prefix path, rather than
    creating a directory named after the prefix. Keep both its parent folder
    and generated filename constrained to the exact graph prefix.
    """
    if not (isinstance(filenames, (tuple, list)) and len(filenames) == 2
            and filenames[0] is True and isinstance(filenames[1], (tuple, list))):
        return None
    import re

    output_root = Path(output_root).resolve()
    prefix = str(filename_prefix).replace("\\", "/")
    parts = prefix.split("/")
    if (not prefix or prefix.startswith("/") or re.match(r"^[A-Za-z]:", prefix)
            or any(part in ("", ".", "..") for part in parts)):
        raise ValueError("The Video Helper Suite output prefix is invalid.")
    prefix_path = Path(*parts)
    expected_parent = (output_root / prefix_path.parent).resolve()
    if not expected_parent.is_relative_to(output_root):
        raise ValueError("The Video Helper Suite output prefix escapes the output folder.")
    expected_name = re.compile(re.escape(prefix_path.name) + r"_\d{5}\.mp4\Z", re.IGNORECASE)
    candidates = []
    for value in filenames[1]:
        if not isinstance(value, (str, Path)) or Path(value).suffix.lower() != ".mp4":
            continue
        path = Path(value).resolve()
        if not path.is_relative_to(output_root):
            raise ValueError("Video Helper Suite returned a file outside the output folder.")
        if path.parent != expected_parent or not expected_name.fullmatch(path.name):
            raise ValueError("Video Helper Suite returned an unexpected output path.")
        candidates.append(path)
    if len(candidates) > 1:
        raise ValueError("Video Helper Suite returned more than one completed delivery file.")
    return candidates[0] if candidates else None


class GenjVHSVideoFromFilenames:
    """Gate the finalizer until VHS closes and verifies the whole video."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "filenames": ("VHS_FILENAMES",),
            "filename_prefix": ("STRING", {"default": "genj/studio_h3_enhance"}),
            "expected_frames": ("INT", {"default": 120, "min": 5, "max": 124}),
            "expected_width": ("INT", {"default": 1080, "min": 2, "max": 7680}),
            "expected_height": ("INT", {"default": 1920, "min": 2, "max": 7680}),
        }}

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("completed_video",)
    FUNCTION = "load"
    CATEGORY = "Zura/Artist Studio"

    def load(self, filenames, filename_prefix, expected_frames, expected_width, expected_height):
        import folder_paths
        from comfy_api.latest import InputImpl

        path = _video_from_vhs(filenames, folder_paths.get_output_directory(), filename_prefix)
        if path is None:
            from comfy_execution.graph_utils import ExecutionBlocker
            return (ExecutionBlocker(None),)
        inspect_video(path, expected_frames=expected_frames, expected_width=expected_width,
                      expected_height=expected_height, expected_fps=24, expected_audio_tracks=0)
        return (InputImpl.VideoFromFile(str(path)),)


def build_graph(project, base_record, *, run_id=None):
    """Build the visible VHS → Nomos → Lanczos → guarded audio restore stage."""
    from . import digest_file
    from .studio import assert_approved, check_asset

    config = project["config"]
    if config.get("engine") != "h3" or config.get("delivery_mode") != "enhanced1080":
        raise ValueError("Choose H3 Enhanced 1080p before opening this stage.")
    status = readiness()
    if not status["ready"]:
        missing = ", ".join(status["missing_nodes"])
        if not status["model_ready"]:
            missing = (missing + ", " if missing else "") + UPSCALE_MODEL
        message = "H3 Enhanced 1080p needs its installed native video and upscale components: " + missing + "."
        if not status["model_ready"]:
            message += " Run " + status.get("setup_command", SETUP_COMMAND) + " and restart ComfyUI."
        raise ValueError(message)
    if not isinstance(base_record, dict) or base_record.get("generation_key") != generation_key(project):
        raise ValueError("The H3 base render no longer matches this approved shot and settings. Create a new take.")
    assert_approved(project)
    check_asset(project["source"])
    if config.get("workflow_mode") == "viewport" or project.get("viewport_render"):
        from .studio import _viewport_project
        references = _viewport_project(project)["viewport_references"]
        if not 1 <= len(references) <= 9:
            raise ValueError("H3 viewport enhancement needs the original one to nine appearance references.")
        for asset in references:
            check_asset(asset)
    else:
        if config.get("workflow_mode") != "relight" or project.get("character"):
            check_asset(project["character"])
        check_asset(project["opening_input"])
    base_path = checked_output_path(base_record.get("asset"), expected_subfolder="genj/studio_intermediate")
    if digest_file(base_path) != base_record.get("sha256"):
        raise ValueError("The H3 base render changed after it was prepared. Create a new take.")
    expected_base = base_record.get("output_raster", {})
    audio_mode = base_record.get("audio_mode")
    if audio_mode not in ("original", "selected_reference", "silent"):
        raise ValueError("The H3 base render has no verified soundtrack provenance.")
    expected_audio = 0 if audio_mode == "silent" else 1
    inspect_video(base_path, expected_frames=base_record.get("frames"),
                  expected_width=expected_base.get("width"), expected_height=expected_base.get("height"),
                  expected_fps=24, expected_audio_tracks=expected_audio)

    import av
    source_path = check_asset(project["source"])
    with av.open(str(source_path)) as source:
        source_stream = source.streams.video[0]
        width, height = int(source_stream.width), int(source_stream.height)
    output_width, output_height = target_dimensions(width, height, 1920)
    expected_frames = int(base_record["frames"])
    run_tag = re_safe(run_id or "graph")
    filename_prefix = f"genj/studio_h3_enhance/{project['id']}/{run_tag}"
    take_name = f"studio_{project['id'][:8]}_h3_enhanced_{run_tag}"
    graph = {
        "h3_enhance_manager": {"class_type": "VHS_BatchManager", "inputs": {"frames_per_batch": 1}},
        "h3_enhance_load": {"class_type": "VHS_LoadVideoPath", "inputs": {
            "video": str(base_path), "force_rate": 0, "custom_width": 0, "custom_height": 0,
            "frame_load_cap": 0, "skip_first_frames": 0, "select_every_nth": 1,
            "meta_batch": ["h3_enhance_manager", 0]}},
        "h3_enhance_model": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": UPSCALE_MODEL}},
        "h3_enhance_nomos": {"class_type": "ImageUpscaleWithModel", "inputs": {
            "upscale_model": ["h3_enhance_model", 0], "image": ["h3_enhance_load", 0]}},
        "h3_enhance_lanczos": {"class_type": "ImageScale", "inputs": {
            "image": ["h3_enhance_nomos", 0], "upscale_method": "lanczos",
            "width": output_width, "height": output_height, "crop": "disabled"}},
        "h3_enhance_vhs": {"class_type": "VHS_VideoCombine", "inputs": {
            "images": ["h3_enhance_lanczos", 0], "frame_rate": 24, "loop_count": 0,
            "filename_prefix": filename_prefix, "format": "video/h264-mp4", "pingpong": False,
            "save_output": True, "pix_fmt": "yuv420p", "crf": 16, "save_metadata": False,
            "trim_to_audio": False, "meta_batch": ["h3_enhance_manager", 0]}},
        "h3_enhance_complete": {"class_type": "GenjVHSVideoFromFilenames", "inputs": {
            "filenames": ["h3_enhance_vhs", 0], "filename_prefix": filename_prefix,
            "expected_frames": expected_frames, "expected_width": output_width,
            "expected_height": output_height}},
        "h3_enhance_review": {"class_type": "GenjLoadReviewedShot", "inputs": {
            "shot_id": project["review"], "approved_shot_id": project["review"],
            "render_long_edge": 0, "output_scale": 1, "preview_seconds": 0}},
        "h3_enhance_export": {"class_type": "GenjRestoreSoundtrack", "inputs": {
            "video": ["h3_enhance_complete", 0], "clip_details": ["h3_enhance_review", 3],
            "take_name": take_name, "output_subfolder": "final", "target_frames": expected_frames}},
    }
    return graph


def re_safe(value):
    import re
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(value))[:48]
    return safe or "graph"


def audio_mode(project, clip):
    if project.get("audio"):
        return "selected_reference"
    return "original" if clip.get("has_audio") else "silent"


NODE_CLASS_MAPPINGS = {GenjVHSVideoFromFilenames.__name__: GenjVHSVideoFromFilenames}
NODE_DISPLAY_NAME_MAPPINGS = {"GenjVHSVideoFromFilenames": "Zura · Verify Complete VHS Video"}
