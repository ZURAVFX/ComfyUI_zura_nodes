"""Zura nodes · Zura Load Video.

One minimal video loader: a local file or a direct URL, trimmed to a start time
and duration, decoded at 24 fps.  Outputs an ordinary ``VIDEO`` wire (frames
plus original audio) that any ComfyUI video node understands, alongside the
decoded frames, so the source can be previewed, combined or fed to Zura Mask.
"""
from __future__ import annotations

from pathlib import Path

import folder_paths

from . import media_source
from .video import video_output


VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".wmv")


def _video_choices(limit=500):
    """Video files a user can pick, newest-name-last, deduplicated.

    ComfyUI core has no ``videos`` model category, so uploaded clips land in the
    input directory (that is where ``/upload/image`` writes them).  Any custom
    node that *does* register a ``videos`` category is included too.
    """
    names = set()
    try:
        names.update(folder_paths.get_filename_list("videos"))
    except KeyError:
        pass
    try:
        input_dir = Path(folder_paths.get_input_directory())
    except Exception:
        input_dir = None
    if input_dir and input_dir.is_dir():
        for path in sorted(input_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES:
                names.add(path.relative_to(input_dir).as_posix())
            if len(names) >= limit:
                break
    return sorted(names)


class ZuraLoadVideo:
    CATEGORY = "Zura"
    FUNCTION = "load"
    RETURN_TYPES = ("VIDEO", "IMAGE")
    RETURN_NAMES = ("video", "frames")
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "clip": (_video_choices(), {
                "tooltip": "Uploaded clips (and any videos already in the input folder). "
                           "Use the Choose local video button below, or pick from this list."}),
            "video_url": ("STRING", {"default": "", "multiline": False,
                                     "tooltip": "Optional direct video URL (YouTube, direct MP4...). "
                                                "Leave empty to use the uploaded clip."}),
            "start_seconds": ("FLOAT", {"default": 0, "min": 0, "max": 86400, "step": 0.1}),
            "duration_seconds": ("FLOAT", {"default": 10, "min": 1, "max": 120, "step": 0.1,
                                           "tooltip": "Length of the driving clip. Every second is 24 rendered frames."}),
            "keep_source_audio": ("BOOLEAN", {"default": True, "label_on": "Keep source audio", "label_off": "Mute audio"}),
            "source_max_side": ("INT", {"default": 1280, "min": 256, "max": 1920, "step": 64,
                                        "tooltip": "Decode bound for the driving frames. Lower this for fast previews."}),
        }}

    @classmethod
    def VALIDATE_INPUTS(cls, clip):
        if clip and not folder_paths.exists_annotated_filepath(clip):
            return f"Invalid video file: {clip}"
        return True

    @classmethod
    def IS_CHANGED(cls, clip="", video_url="", start_seconds=0, duration_seconds=10,
                   keep_source_audio=True, source_max_side=1280):
        # Include every decode-affecting input. Returning only the path leaves
        # ComfyUI's cache stale when the user changes the trim, audio, or size.
        if str(video_url or "").strip():
            return float("nan")
        path = folder_paths.get_annotated_filepath(clip) if clip else ""
        if not path:
            return float("nan")
        try:
            stat = Path(path).stat()
            fingerprint = (str(Path(path).resolve()), stat.st_mtime_ns, stat.st_size)
        except OSError:
            fingerprint = (str(path), None, None)
        return fingerprint + (float(start_seconds), float(duration_seconds),
                              bool(keep_source_audio), int(source_max_side))

    def load(self, clip="", video_url="", start_seconds=0, duration_seconds=10,
             keep_source_audio=True, source_max_side=1280):
        url = str(video_url or "").strip()
        path = media_source.download_video(url) if url else media_source.local_path(clip)
        max_side = media_source.source_max_side(source_max_side)
        frames, audio, info = media_source.decode_clip(path, start_seconds, duration_seconds, max_side)
        keep_audio = bool(keep_source_audio) and audio is not None
        # A plain VIDEO wire carries everything downstream nodes need (frames,
        # frame rate and the original audio), so no custom payload is emitted.
        return video_output(frames, audio if keep_audio else None, info["fps"]), frames


# Class IDs are the workflow contract: these keys are kept from the pack's
# previous name so graphs saved before the Zura rename still load.
NODE_CLASS_MAPPINGS = {"TrendStudioV2DrivingClip": ZuraLoadVideo}
NODE_DISPLAY_NAME_MAPPINGS = {"TrendStudioV2DrivingClip": "Zura Load Video"}
