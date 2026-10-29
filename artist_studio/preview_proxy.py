"""Browser-friendly playback copies; generation always reads the original asset."""
from pathlib import Path
from functools import lru_cache


def needs_proxy(codec_name):
    # ProRes is commonly readable by FFmpeg but not by the embedded browser.
    return str(codec_name or "").lower() == "prores"


@lru_cache(maxsize=64)
def _codec(path, mtime_ns, size):
    import av
    with av.open(str(path)) as video:
        return video.streams.video[0].codec_context.name if video.streams.video else ""


def describe_existing(asset, input_root):
    """Find ProRes in older saved projects that predate codec metadata."""
    if asset.get("asset_kind") != "video" or asset.get("preview_file") or Path(asset.get("file", "")).suffix.lower() != ".mov":
        return
    root = (Path(input_root) / "genj_studio").resolve()
    source = (Path(input_root) / asset["file"]).resolve()
    if not source.is_relative_to(root):
        return
    try:
        stat = source.stat()
        codec = asset.get("video_codec") or _codec(source, stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError):
        return
    if needs_proxy(codec):
        asset["video_codec"] = codec
        asset["preview_file"] = (Path(asset["file"]).parent / "preview.mp4").as_posix()


def build_proxy(source, target, ffmpeg):
    """Create a seekable, aspect-preserving H.264 copy without changing source media."""
    source, target = Path(source), Path(target)
    partial = target.with_name(target.stem + ".partial.mp4")
    try:
        ffmpeg("-i", source, "-map", "0:v:0", "-map", "0:a:0?",
               "-vf", "scale='min(1280,iw)':'min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
               "-c:v", "libx264", "-preset", "ultrafast", "-crf", 24, "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", partial)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
