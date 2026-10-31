"""Validate and collect completed native HDR LTX performance outputs.

This helper never submits work or turns an SDR render into an HDR result.
The caller must independently validate action/prompt ownership and obtain the
bound graph using ``ltx25.bind_phase`` and the completed upstream receipts.
"""
from __future__ import annotations

import copy
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile

from . import ltx25

_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_PREFIX = re.compile(r"performance_[a-f0-9]{32}\Z")
_OUTPUTS = {"hlg_video", "hlg_and_exr", "acescg_exr"}


def _expected_graph(plan, submitted):
    """Check the exact template and allow only the bound video-cache digest."""
    if (not isinstance(plan, dict) or plan.get("schema") != ltx25.SCHEMA or
            plan.get("key") != ltx25.digest(plan.get("basis")) or
            plan.get("scenario") != plan.get("basis", {}).get("scenario")):
        raise ValueError("The native HDR plan is stale or malformed.")
    template = copy.deepcopy(plan.get("phases", {}).get("decode"))
    if not isinstance(template, dict) or ltx25.digest(template) != plan.get("graph_hashes", {}).get("decode"):
        raise ValueError("The native HDR decode template changed.")
    if plan.get("dependencies", {}).get("decode") != ["stage2_video"]:
        raise ValueError("The native HDR decode dependency is unexpected.")
    if not isinstance(submitted, dict):
        raise ValueError("The submitted native HDR decode graph is missing.")
    try:
        inputs = template["load_stage2_video"]["inputs"]
        actual = submitted["load_stage2_video"]["inputs"]["cache_digest"]
        if (inputs["cache_digest"] != "__UNBOUND__" or
                template["load_stage2_video"]["class_type"] != "ZuraLoadVideoLatentData" or
                inputs["cache_key"] != plan["artifacts"]["stage2_video"]["key"] or
                not isinstance(actual, str) or not _DIGEST.fullmatch(actual)):
            raise ValueError
        inputs["cache_digest"] = actual
    except (KeyError, TypeError, ValueError):
        raise ValueError("The native HDR decode cache binding is invalid.") from None
    if template != submitted:
        raise ValueError("The submitted native HDR decode controls changed.")


def _source_ref(history, node, field, prefix, suffix, output_root, *, counter):
    """Resolve a unique native output inside its exact submitted prefix."""
    outputs = history.get("outputs")
    result = outputs.get(node) if isinstance(outputs, dict) else None
    values = result.get(field) if isinstance(result, dict) else None
    if not isinstance(values, list) or len(values) != 1:
        raise ValueError("The native HDR render returned no unique output for " + node + ".")
    asset = values[0]
    if not isinstance(asset, dict) or asset.get("type") != "output":
        raise ValueError("The native HDR render returned an invalid output reference.")
    folder, filename = asset.get("subfolder"), asset.get("filename")
    if not isinstance(folder, str) or not isinstance(filename, str):
        raise ValueError("The native HDR output location is invalid.")
    # ComfyUI on Windows may report subfolders using backslashes.
    folder = folder.replace("\\", "/")
    parts = PurePosixPath(folder)
    if (parts.is_absolute() or any(part in ("", ".", "..") for part in folder.split("/")) or
            re.match(r"^[A-Za-z]:", folder) or "/" in filename or "\\" in filename):
        raise ValueError("The native HDR output is outside its output folder.")
    wanted = PurePosixPath(prefix)
    if parts != wanted.parent:
        raise ValueError("The native HDR output does not match the submitted folder.")
    expected = re.escape(wanted.name) + (r"_\d+_" if counter else "") + re.escape(suffix)
    if not re.fullmatch(expected, filename):
        raise ValueError("The native HDR output does not match the submitted filename.")
    root = Path(output_root).resolve()
    raw = root.joinpath(*parts.parts, filename)
    path = raw.resolve()
    if (raw.is_symlink() or not path.is_relative_to(root) or
            path.parent != root.joinpath(*wanted.parent.parts).resolve() or not path.is_file()):
        raise ValueError("The native HDR output is missing or outside its output folder.")
    return {"filename": filename, "subfolder": parts.as_posix(), "type": "output"}, path


def _colour_metadata(path):
    """Read encoded pixel format and actual video colour tags."""
    import av
    with av.open(str(path)) as container:
        videos = list(container.streams.video)
        if len(videos) != 1:
            raise ValueError("The native HDR output needs exactly one video stream.")
        codec = videos[0].codec_context
        return {"pixel_format": getattr(codec.format, "name", ""),
                "transfer": int(codec.color_trc or 2),
                "primaries": int(codec.color_primaries or 2),
                "matrix": int(codec.colorspace or 2)}


def _check_archive(path, frames, width, height):
    """Validate a complete bounded ZIP without extracting user-controlled paths."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            expected = [f"frame_{index:05d}.exr" for index in range(frames)]
            if len(infos) != frames or sorted(item.filename for item in infos) != expected:
                raise ValueError("The HDR EXR archive has missing, duplicate or unexpected frames.")
            # Our native writer uses stored ZIP entries. This bounds each EXR
            # and prevents path traversal, compressed bombs and ZIP links.
            limit = width * height * 32 + 8 * 1024 * 1024
            # Decode one bounded frame at a time. Reading to EOF checks ZIP
            # CRCs; an OIIO decode checks the actual image, not its extension.
            import numpy as np
            import OpenImageIO as oiio
            from ..paintout.paintout import _exr_auto_space
            with tempfile.TemporaryDirectory(prefix='zura-hdr-check-') as temporary:
                frame = Path(temporary) / 'frame.exr'
                for item in infos:
                    if (item.is_dir() or item.compress_type != zipfile.ZIP_STORED or
                            item.file_size <= 0 or item.file_size > limit or
                            item.compress_size != item.file_size or
                            ((item.external_attr >> 16) & 0o170000) == 0o120000):
                        raise ValueError("The HDR EXR archive contains an invalid or oversized entry.")
                    with archive.open(item) as source, frame.open('wb') as destination:
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
                    reader = oiio.ImageInput.open(str(frame))
                    if reader is None:
                        oiio.geterror()
                        raise ValueError('The HDR EXR archive contains an unreadable image.')
                    try:
                        spec = reader.spec()
                        if (spec.width != width or spec.height != height or spec.depth != 1 or spec.deep
                                or spec.nchannels != 3 or set(spec.channelnames) != {'R', 'G', 'B'}
                                or not (spec.format == oiio.HALF or spec.format == oiio.FLOAT)):
                            raise ValueError('The HDR EXR archive has the wrong image raster or channels.')
                        chroma = spec.getattribute('chromaticities')
                        ap1 = (.713, .293, .165, .830, .128, .044, .32168, .33767)
                        if (chroma is None or len(chroma) != 8 or
                                not all(abs(float(a) - b) < .002 for a, b in zip(chroma, ap1))
                                or _exr_auto_space(str(frame)) != 'acescg'):
                            raise ValueError('The HDR EXR archive must contain scene-linear ACEScg/AP1 images.')
                        pixels = reader.read_image(format=oiio.FLOAT)
                        if pixels is None or pixels.shape != (height, width, 3) or not np.isfinite(pixels).all():
                            raise ValueError('The HDR EXR archive contains damaged or non-finite pixels.')
                        del pixels
                    finally:
                        reader.close()
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ValueError("The HDR EXR archive is missing or invalid.") from exc


def collect_native_delivery(plan, submitted_graph, frozen_history, output_directory):
    """Return a verified SDR proxy and native HDR masters from one decode.

    The exact successfully submitted graph and the plan's decode template are
    checked here. The enclosing Studio action still owns prompt-id/receipt
    validation and must rebind the graph from its verified upstream receipts.
    """
    _expected_graph(plan, submitted_graph)
    status = frozen_history.get("status", {}) if isinstance(frozen_history, dict) else {}
    prompt = frozen_history.get("prompt", []) if isinstance(frozen_history, dict) else []
    if (not isinstance(status, dict) or status.get("status_str") != "success" or status.get("completed") is not True or
            not isinstance(prompt, (list, tuple)) or len(prompt) < 3 or
            not isinstance(prompt[1], str) or not prompt[1] or prompt[2] != submitted_graph):
        raise ValueError("The native HDR decode did not complete with the submitted graph.")
    info = plan.get("hdr_delivery", {})
    output, prefix = info.get("output"), info.get("prefix")
    basis = plan["basis"]
    if (output not in _OUTPUTS or not isinstance(prefix, str) or not _PREFIX.fullmatch(prefix) or
            prefix != "performance_" + plan["key"][:32] or
            basis.get("native_hdr", {}).get("output") != output or
            info.get("preview_node") != "save_preview" or
            info.get("video_node") != ("zura_hdr_save_video" if output != "acescg_exr" else None) or
            info.get("archive_node") != ("zura_hdr_archive" if output != "hlg_video" else None)):
        raise ValueError("The native HDR delivery does not match the approved plan.")
    size, frames, fps = basis.get("delivery"), basis.get("frames"), basis.get("timeline", {}).get("fps")
    if (not isinstance(size, list) or len(size) != 2 or
            any(type(value) is not int or value < 2 for value in size) or
            type(frames) is not int or not 1 <= frames <= 120 or fps != 24 or
            plan.get("scenario") not in ("original", "replacement", "silent")):
        raise ValueError("The native HDR delivery dimensions or duration are invalid.")
    audio_count = 0 if plan["scenario"] == "silent" else 1
    from .enhancement import inspect_video
    inspect = {"expected_frames": frames, "expected_width": size[0],
               "expected_height": size[1], "expected_fps": 24,
               "expected_audio_tracks": audio_count}
    expected_preview = "genj/hdr/" + prefix + "_preview"
    preview_node = submitted_graph["save_preview"]
    if (preview_node.get("class_type") != "ZuraHDRSaveExactRate" or
            preview_node.get("inputs", {}).get("filename_prefix") != expected_preview):
        raise ValueError("The native HDR preview prefix changed.")
    asset, preview = _source_ref(frozen_history, "save_preview", "images", expected_preview,
                                 ".mp4", output_directory, counter=True)
    raster = inspect_video(preview, **inspect)
    preview_colour = _colour_metadata(preview)
    if (preview_colour["pixel_format"] not in ("yuv420p", "yuvj420p") or
            preview_colour["transfer"] not in (1, 13)):
        raise ValueError("The HDR viewing preview is not an SDR video.")
    files = []
    if info["video_node"]:
        video_node = submitted_graph["zura_hdr_save_video"]
        video_prefix = "genj/hdr/" + prefix
        if (video_node.get("class_type") != "ZuraHDRSaveExactRate" or
                video_node.get("inputs", {}).get("filename_prefix") != video_prefix):
            raise ValueError("The native HDR video prefix changed.")
        reference, path = _source_ref(frozen_history, "zura_hdr_save_video", "images",
                                      video_prefix, ".mp4", output_directory, counter=True)
        inspect_video(path, **inspect)
        colour = _colour_metadata(path)
        if (colour["pixel_format"] not in ("yuv420p10le", "yuv422p10le", "yuv444p10le") or
                (colour["transfer"], colour["primaries"], colour["matrix"]) != (18, 9, 9)):
            raise ValueError("The delivered HDR video is not 10-bit BT.2020 HLG.")
        files.append({**reference, "label": "HDR video"})
    if info["archive_node"]:
        archive_node = submitted_graph["zura_hdr_archive"]
        if (archive_node.get("class_type") != "ZuraHDRPackageACEScct" or
                archive_node.get("inputs", {}).get("prefix") != prefix):
            raise ValueError("The native HDR archive prefix changed.")
        reference, path = _source_ref(frozen_history, "zura_hdr_archive", "files",
                                      "genj/hdr/" + prefix, ".zip", output_directory, counter=False)
        _check_archive(path, frames, *size)
        files.append({**reference, "label": "ACEScg EXR sequence"})
    return {"asset": asset, "hdr_files": files, "output_raster": raster,
            "sha256": ltx25.file_digest(preview), "native_hdr": True, "hdr_output": output}
