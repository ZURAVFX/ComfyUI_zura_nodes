"""Bounded CPU input and source-matched delivery for LTX Alpha Gen.

Inference stays in the native LTX nodes. These adapters only pad/decode source
frames and package the predicted matte with the original beauty pass.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile

import numpy as np
from PIL import Image
import torch


CATEGORY = "Zura Studio/video"
SCHEMA = "zura.alpha-video/1"
MAX_FRAMES = 145
MAX_PIXELS = 1920 * 1088


def _tool(name):
    installed = shutil.which(name)
    if installed:
        return installed
    # Portable installs need no PATH modification.
    import folder_paths
    root = Path(folder_paths.base_path)
    for directory in (root / "ffmpeg" / "bin", root / "ffmpeg", root / "bin", root):
        for suffix in (".exe", ""):
            candidate = directory / (name + suffix)
            if candidate.is_file():
                return str(candidate)
    raise FileNotFoundError(f"{name} is missing. Install FFmpeg and FFprobe in ComfyUI's ffmpeg/bin folder.")


def _run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, **kwargs)
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace") if isinstance(result.stderr, bytes) else result.stderr
        raise RuntimeError("Alpha video processing stopped: " + (detail or "FFmpeg failed.")[-1800:])
    return result


def _pin(path):
    stat = path.stat()
    with path.open("rb") as stream:
        prefix = hashlib.sha256(stream.read(1024 * 1024)).hexdigest()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "prefix_sha256": prefix}


def _source(path):
    if not isinstance(path, str) or not path.strip() or "\0" in path:
        raise ValueError("Choose a source video.")
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        import folder_paths
        resolved = Path(folder_paths.get_input_directory()) / resolved
    resolved = resolved.resolve()
    if not resolved.is_file():
        raise ValueError("The source video is no longer available. Choose it again.")
    return resolved


def probe_source(path):
    """Verify the constant source clock and unrotated SDR raster."""
    result = _run([_tool("ffprobe"), "-v", "error", "-show_streams", "-of", "json", str(path)], text=True)
    streams = json.loads(result.stdout).get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        raise ValueError("The source has no video stream.")
    rotations = [video.get("tags", {}).get("rotate", 0)] + [x.get("rotation", 0) for x in video.get("side_data_list", [])]
    if any(abs(float(rotation) % 360) > .01 for rotation in rotations):
        raise ValueError("Bake the video rotation into its pixels before generating alpha.")
    if video.get("color_transfer") in ("smpte2084", "arib-std-b67", "linear") or video.get("color_primaries") in ("bt2020", "smpte432"):
        raise ValueError("Generate alpha currently supports SDR footage. Convert an HDR viewing copy to SDR first.")
    try:
        rate = Fraction(video.get("avg_frame_rate", "0/1"))
        nominal = Fraction(video.get("r_frame_rate", "0/1"))
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError("The source frame rate could not be read.") from error
    if not 0 < rate <= 1000 or nominal <= 0 or abs(float(rate - nominal)) > .02:
        raise ValueError("Use constant-frame-rate footage to keep the matte aligned with the source.")
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    if min(width, height) < 1 or max(width, height) > 8192 or width * height > 64 * 1024 * 1024:
        raise ValueError("Choose source footage no larger than 8192 pixels per side and 64 MP.")
    count = video.get("nb_frames")
    if count in (None, "N/A", ""):
        result = _run([_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries", "stream=nb_read_frames", "-of", "json", str(path)], text=True)
        count = json.loads(result.stdout)["streams"][0].get("nb_read_frames", 0)
    if int(count) < 1:
        raise ValueError("The source contains no decodable frames.")
    return {"source_path": str(path), "width": width, "height": height, "fps_rational": str(rate),
            "fps": float(rate), "source_frames": int(count), "has_audio": any(s.get("codec_type") == "audio" for s in streams),
            "primaries": video.get("color_primaries"), "transfer": video.get("color_transfer"),
            "matrix": video.get("color_space"), "range": video.get("color_range")}


def processing_geometry(width, height, scale):
    if type(scale) not in (int, float) or not math.isfinite(scale) or not .25 <= scale <= 1:
        raise ValueError("Choose a processing scale from 25% to 100%.")
    content_width, content_height = max(1, round(width * scale)), max(1, round(height * scale))
    padded_width, padded_height = math.ceil(content_width / 32) * 32, math.ceil(content_height / 32) * 32
    if (min(padded_width, padded_height) < 32 or max(padded_width, padded_height) > 1920 or
            min(padded_width, padded_height) > 1088 or padded_width * padded_height > MAX_PIXELS):
        raise ValueError("Alpha Gen supports up to 1920 × 1088 processing pixels. Lower the processing resolution.")
    return content_width, content_height, padded_width, padded_height


def _progress(total):
    try:
        from comfy.utils import ProgressBar
        return ProgressBar(total).update_absolute
    except ImportError:
        return lambda value: None


def _read_exact(stream, count):
    data = bytearray()
    while len(data) < count:
        block = stream.read(count - len(data))
        if not block:
            break
        data.extend(block)
    return bytes(data)


class ZuraAlphaVideoInput:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "source_path": ("STRING", {"default": ""}),
            "start_frame": ("INT", {"default": 0, "min": 0, "max": 10000000}),
            "frame_count": ("INT", {"default": 49, "min": 1, "max": MAX_FRAMES}),
            "processing_scale": ("FLOAT", {"default": .5, "min": .25, "max": 1, "step": .25}),
        }}

    RETURN_TYPES = ("IMAGE", "ZURA_ALPHA_INFO", "INT", "INT", "INT", "FLOAT")
    RETURN_NAMES = ("images", "info", "width", "height", "frames", "fps")
    FUNCTION = "prepare"
    CATEGORY = CATEGORY

    @classmethod
    def IS_CHANGED(cls, source_path, **kwargs):
        try:
            return json.dumps(_pin(_source(source_path)), sort_keys=True)
        except (ValueError, OSError):
            return float("nan")

    def prepare(self, source_path, start_frame, frame_count, processing_scale):
        if type(start_frame) is not int or start_frame < 0 or type(frame_count) is not int or not 1 <= frame_count <= MAX_FRAMES:
            raise ValueError("Choose a frame range of 1 to 145 frames.")
        path = _source(source_path)
        pin = _pin(path)
        info = probe_source(path)
        if start_frame + frame_count > info["source_frames"]:
            raise ValueError("The selected range extends past the source video. Trim the clip again.")
        cw, ch, pw, ph = processing_geometry(info["width"], info["height"], processing_scale)
        padded_frames = max(9, math.ceil((frame_count - 1) / 8) * 8 + 1)
        vf = f"trim=start_frame={start_frame}:end_frame={start_frame + frame_count},setpts=PTS-STARTPTS,scale={cw}:{ch}:flags=lanczos,setsar=1,pad={pw}:{ph}:0:0:color=black,fillborders=right={pw-cw}:bottom={ph-ch}:mode=smear"
        command = [_tool("ffmpeg"), "-v", "error", "-i", str(path), "-vf", vf, "-an", "-sn", "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
        # Scale in FFmpeg, before decoded frames enter Python memory.
        images = torch.empty((padded_frames, ph, pw, 3), dtype=torch.float32)
        update = _progress(frame_count)
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
            try:
                for index in range(frame_count):
                    raw = _read_exact(process.stdout, pw * ph * 3)
                    if len(raw) != pw * ph * 3:
                        raise ValueError(f"Decoded only {index} of {frame_count} selected frames. Check the source footage.")
                    pixels = np.frombuffer(raw, dtype=np.uint8).reshape(ph, pw, 3)
                    images[index].copy_(torch.from_numpy(pixels.copy()).float().div_(255))
                    update(index + 1)
                if process.stdout.read(1):
                    raise ValueError("The source decoder returned an unexpected number of frames.")
                if process.wait() != 0:
                    errors.seek(0)
                    raise RuntimeError("Could not decode the selected video: " + errors.read().decode("utf8", "replace")[-1000:])
            finally:
                process.stdout.close()
                if process.poll() is None:
                    process.kill()
                process.wait()
        if _pin(path) != pin:
            raise ValueError("The source video changed during preparation. Choose it again.")
        if padded_frames > frame_count:
            images[frame_count:] = images[frame_count - 1]
        info.update({"schema": SCHEMA, "source_pin": pin, "start_frame": start_frame, "frame_count": frame_count,
                     "content_width": cw, "content_height": ch, "working_width": pw, "working_height": ph,
                     "padded_frames": padded_frames, "processing_scale": float(processing_scale)})
        return images, info, pw, ph, padded_frames, info["fps"]


def _validate_info(info, images):
    if not isinstance(info, dict) or info.get("schema") != SCHEMA:
        raise ValueError("Prepare the source video again before saving its alpha.")
    required = ("width", "height", "content_width", "content_height", "working_width", "working_height", "frame_count", "padded_frames")
    if any(type(info.get(k)) is not int or info[k] < 1 for k in required):
        raise ValueError("The alpha preparation metadata is incomplete.")
    if not 1 <= info["frame_count"] <= MAX_FRAMES or not 9 <= info["padded_frames"] <= MAX_FRAMES or (info["padded_frames"] - 1) % 8:
        raise ValueError("The alpha preparation frame range is invalid.")
    expected_frames = max(9, math.ceil((info["frame_count"] - 1) / 8) * 8 + 1)
    if info["padded_frames"] != expected_frames or type(info.get("start_frame")) is not int or info["start_frame"] < 0:
        raise ValueError("The alpha preparation frame range is invalid.")
    if max(info["width"], info["height"]) > 8192 or info["width"] * info["height"] > 64 * 1024 * 1024:
        raise ValueError("The alpha source dimensions are invalid.")
    if (info["working_width"] % 32 or info["working_height"] % 32 or
            max(info["working_width"], info["working_height"]) > 1920 or
            min(info["working_width"], info["working_height"]) > 1088 or
            info["working_width"] * info["working_height"] > MAX_PIXELS):
        raise ValueError("The alpha working dimensions are invalid.")
    if images.ndim != 4 or images.shape[0] != info["padded_frames"] or tuple(images.shape[1:3]) != (info["working_height"], info["working_width"]) or images.shape[3] not in (1, 3, 4):
        raise ValueError("The generated matte does not match the prepared frame count or dimensions.")
    if info["content_width"] > info["working_width"] or info["content_height"] > info["working_height"]:
        raise ValueError("The alpha crop dimensions are invalid.")
    path = _source(info.get("source_path"))
    if _pin(path) != info.get("source_pin"):
        raise ValueError("The source video changed after preparation. Generate its alpha again.")
    return path


def _target_folder(prefix):
    import folder_paths
    if not isinstance(prefix, str) or not prefix.strip() or "\0" in prefix:
        raise ValueError("Choose a valid alpha output name.")
    normal = prefix.replace("\\", "/")
    if Path(normal).is_absolute() or re.match(r"^[a-zA-Z]:", normal) or any(part in (".", "..", "") for part in normal.split("/")):
        raise ValueError("Alpha output names must stay inside the ComfyUI output folder.")
    output = Path(folder_paths.get_output_directory()).resolve()
    target = output.joinpath(*normal.split("/"))
    if not target.resolve().is_relative_to(output):
        raise ValueError("Alpha output names must stay inside the ComfyUI output folder.")
    target.parent.mkdir(parents=True, exist_ok=True)
    return output, target.parent / (target.name + "_" + uuid.uuid4().hex[:12])


def _colour_arguments(info):
    args = []
    for key, option, allowed in (
        ("primaries", "-color_primaries", {"bt709", "bt470bg", "smpte170m", "smpte240m", "bt470m"}),
        ("transfer", "-color_trc", {"bt709", "iec61966-2-1", "gamma22", "gamma28", "smpte170m", "smpte240m"}),
        ("matrix", "-colorspace", {"bt709", "bt470bg", "smpte170m", "smpte240m"}),
    ):
        if info.get(key) in allowed:
            args.extend([option, info[key]])
    if info.get("matrix") == "gbr":
        args.extend(["-colorspace", "bt709"])
    return args


class ZuraAlphaVideoOutput:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "info": ("ZURA_ALPHA_INFO",),
                             "filename_prefix": ("STRING", {"default": "ZURA STUDIO/alpha"})},
                "optional": {"ae_frame_contract": ("STRING", {"default": ""})}}

    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = CATEGORY

    def save(self, images, info, filename_prefix="ZURA STUDIO/alpha", ae_frame_contract=""):
        source = _validate_info(info, images)
        if ae_frame_contract:
            from ..comfylink.frame_contract import validate_interval
            validate_interval(json.loads(ae_frame_contract), frames=info['frame_count'],
                fps=Fraction(info['fps_rational']), width=info['width'], height=info['height'])
        output, target = _target_folder(filename_prefix)
        rate = Fraction(info["fps_rational"])
        if not 0 < rate <= 1000:
            raise ValueError("The source frame rate is invalid.")
        fps = str(rate)
        count, width, height = info["frame_count"], info["width"], info["height"]
        names = {"alpha": target.with_name(target.name + "_alpha.mov"),
                 "matte": target.with_name(target.name + "_matte.mp4"),
                 "preview": target.with_name(target.name + "_preview.mp4"),
                 "sequence": target.with_name(target.name + "_matte_png16.zip")}
        temporary_outputs = {role: path.with_name(path.stem + ".partial" + path.suffix) for role, path in names.items()}
        update = _progress(count + 3)
        try:
            with tempfile.TemporaryDirectory(prefix="zura_alpha_") as temporary:
                folder = Path(temporary)
                sequence = folder / "%06d.png"
                with zipfile.ZipFile(temporary_outputs["sequence"], "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                    for index in range(count):
                        frame = images[index, :info["content_height"], :info["content_width"], :3].detach().to(device="cpu", dtype=torch.float32)
                        if not torch.isfinite(frame).all():
                            raise ValueError("The generated matte contains invalid pixels.")
                        # A conventional matte is white foreground. Comfy MASK
                        # inversion conventions do not apply to these RGB pixels.
                        alpha = frame.mean(dim=-1).clamp(0, 1).numpy()
                        matte = Image.fromarray(np.rint(alpha * 65535).astype(np.uint16))
                        if matte.size != (width, height):
                            matte = matte.resize((width, height), Image.Resampling.BILINEAR)
                        frame_path = folder / f"{index:06d}.png"
                        matte.save(frame_path)
                        archive.write(frame_path, frame_path.name)
                        update(index + 1)
                    archive.writestr("timing.json", json.dumps({"fps": fps, "start_frame": info["start_frame"], "frames": count,
                                                               "width": width, "height": height, "white_is_foreground": True}, indent=2))
                # Decode original source pixels only in FFmpeg, keeping Python's
                # memory bounded to one full-size matte rather than RGBA video.
                common = [_tool("ffmpeg"), "-v", "error", "-y", "-i", str(source), "-framerate", fps, "-start_number", "0", "-i", str(sequence)]
                trim = f"trim=start_frame={info['start_frame']}:end_frame={info['start_frame']+count},setpts=PTS-STARTPTS,setsar=1"
                # ProRes stores YUV, so an RGB source needs a matching matrix
                # conversion/tag rather than retaining an impossible GBR tag.
                rgb_matrix = ",scale=out_color_matrix=bt709:out_range=tv" if info.get("matrix") == "gbr" else ""
                # alphamerge negotiates an 8-bit grey input on common FFmpeg
                # builds. Merge matching 10-bit YUV planes instead. Restore
                # the matte's full 0..1023 range after its YUV conversion so
                # black is transparent, not a lifted 64/1023 alpha value.
                merge = "mergeplanes=map0s=0:map0p=0:map1s=0:map1p=1:map2s=0:map2p=2:map3s=1:map3p=0:format=yuva444p10le"
                filters = f"[0:v:0]{trim}{rgb_matrix},format=yuv444p10le[beauty];[1:v:0]setsar=1,scale=in_range=pc:out_range=tv,format=yuv444p10le,lutyuv=y='clip((val-64)*1023/876,0,1023)'[matte];[beauty][matte]{merge}[rgba]"
                audio = []
                if info.get("has_audio"):
                    start = Fraction(info["start_frame"], 1) / rate
                    end = Fraction(info["start_frame"] + count, 1) / rate
                    filters += f";[0:a:0]atrim=start={float(start):.12f}:end={float(end):.12f},asetpts=PTS-STARTPTS[audio]"
                    audio = ["-map", "[audio]", "-c:a", "pcm_s24le"]
                _run(common + ["-filter_complex", filters, "-map", "[rgba]", *audio, "-frames:v", str(count), "-r", fps,
                               "-fps_mode", "cfr", "-c:v", "prores_ks", "-profile:v", "4", "-alpha_bits", "16", "-pix_fmt", "yuva444p10le",
                               "-video_track_timescale", str(rate.numerator), *_colour_arguments(info), str(temporary_outputs["alpha"])])
                update(count + 1)
                # H.264 previews use even dimensions for browser compatibility;
                # the MOV and PNG sequence retain the exact source raster.
                _run([_tool("ffmpeg"), "-v", "error", "-y", "-framerate", fps, "-start_number", "0", "-i", str(sequence),
                      "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0:color=black", "-frames:v", str(count), "-an", "-c:v", "libx264",
                      "-preset", "fast", "-crf", "10", "-pix_fmt", "yuv420p", "-video_track_timescale", str(rate.numerator), "-movflags", "+faststart", str(temporary_outputs["matte"])])
                update(count + 2)
                checker = np.full((height, width), 96, dtype=np.uint8)
                yy, xx = np.ogrid[:height, :width]
                checker[(xx // 24 + yy // 24) % 2 == 0] = 160
                checker_path = folder / "checker.png"
                Image.fromarray(checker).save(checker_path)
                preview_filters = "[1:v:0][0:v:0]overlay=shortest=1:format=auto,pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0:color=black,format=yuv420p[preview]"
                _run([_tool("ffmpeg"), "-v", "error", "-y", "-i", str(temporary_outputs["alpha"]), "-loop", "1", "-framerate", fps, "-i", str(checker_path),
                      "-filter_complex", preview_filters, "-map", "[preview]", "-frames:v", str(count), "-r", fps, "-fps_mode", "cfr",
                               "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                               "-video_track_timescale", str(rate.numerator), "-movflags", "+faststart", str(temporary_outputs["preview"])])
                update(count + 3)
            if _pin(source) != info["source_pin"]:
                raise ValueError("The source changed while saving. Generate its alpha again.")
            for role, file in temporary_outputs.items():
                file.replace(names[role])
        except BaseException:
            for file in temporary_outputs.values():
                file.unlink(missing_ok=True)
            for file in names.values():
                file.unlink(missing_ok=True)
            raise
        files = []
        for role in ("preview", "matte", "alpha", "sequence"):
            relative = names[role].relative_to(output)
            files.append({"filename": relative.name, "subfolder": relative.parent.as_posix(), "type": "output", "role": role})
        return {"ui": {"images": files, "animated": (True,)}}


NODE_CLASS_MAPPINGS = {"ZuraAlphaVideoInput": ZuraAlphaVideoInput, "ZuraAlphaVideoOutput": ZuraAlphaVideoOutput}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraAlphaVideoInput": "Prepare source for Alpha Gen", "ZuraAlphaVideoOutput": "Save source-matched alpha"}
