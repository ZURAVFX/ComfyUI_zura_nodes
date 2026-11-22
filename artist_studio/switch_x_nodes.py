"""ComfyUI adapters for the Zura SwitchX production pass."""

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import cv2
import av
import numpy as np
import torch
from .switch_x_graph import model_length
from .switch_x_structure import ZuraH3SourceStructure, ZuraSwitchXProtectedLatent
from .character_mask import editable_mask


from .switch_x_media import (
    alpha_image,
    canvas,
    fit,
    input_path,
    paired_frames,
    rgb,
    source_info,
    opened,
)


class SwitchGuide:
    RETURN_TYPES = ("IMAGE", "MASK", "IMAGE")
    RETURN_NAMES = ("source_at_render_size", "replace", "video_reference")
    FUNCTION = "prepare"
    CATEGORY = "Zura/Zura SwitchX"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source": ("STRING",),
                "matte": ("STRING",),
                "start": ("INT", {"min": 0}),
                "count": ("INT", {"min": 1}),
                "side": ("INT", {"min": 32}),
            },
            "optional": {
                "white_means": (["keep", "replace"],),
                "mask_channel": (["luma", "alpha"],),
            },
        }

    def prepare(self, source, matte, start, count, side, white_means="keep", mask_channel="luma"):
        from comfy_extras.nodes_minimax_h3 import adapt_canvas

        images = masks = reference = None
        read = 0
        with paired_frames(input_path(source), input_path(matte), start, count) as frames:
            for frame, mask in frames:
                dims = canvas(frame.width, frame.height, side)
                decoded = rgb(frame)
                source_frame = fit(decoded, dims)
                selected = fit(alpha_image(mask, mask_channel), dims)
                if images is None:
                    rw, rh = adapt_canvas(frame.width, frame.height)
                    if frame.width * frame.height <= rw * rh:
                        rw, rh = frame.width, frame.height
                    images = torch.empty(
                        (model_length(count), *source_frame.shape),
                        dtype=torch.float32,
                        device="cpu",
                    )
                    masks = torch.empty(
                        (model_length(count), *selected.shape), dtype=torch.float32, device="cpu"
                    )
                    reference = torch.empty(
                        (model_length(count), rh, rw, 3), dtype=torch.float32, device="cpu"
                    )
                # Feed native-resolution reference detail independently of the render canvas.
                # Bound memory for UHD footage at H3's own reference canvas size.
                if frame.format.name in {
                    "yuvj420p",
                    "yuvj422p",
                    "yuvj444p",
                    "rgb24",
                    "rgba",
                    "pal8",
                }:
                    ref_frame = frame.to_ndarray(format="rgb24").astype(np.float32) / 255.0
                else:
                    ref_frame = decoded
                if ref_frame.shape[:2] != (rh, rw):
                    ref_frame = cv2.resize(
                        ref_frame, (rw, rh), interpolation=cv2.INTER_LANCZOS4
                    ).clip(0, 1)
                reference[read].copy_(torch.from_numpy(ref_frame))
                images[read].copy_(torch.from_numpy(source_frame))
                masks[read].copy_(torch.from_numpy(editable_mask(selected, white_means)))
                read += 1
        if read != count or images is None:
            raise ValueError("The source ended before the selected range.")
        # Native Ref2VA rounds video references down to 17n+5. Holding the
        # terminal frame keeps the final real frames in its reference latent.
        images[count:] = images[count - 1]
        masks[count:] = masks[count - 1]
        reference[count:] = reference[count - 1]
        return images, masks, reference


class SwitchLookFrame:
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "prepare"
    CATEGORY = SwitchGuide.CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "source": ("STRING",),
                "frame": ("INT", {"min": 0}),
                "side": ("INT", {"min": 32}),
            },
        }

    def prepare(self, image, source, frame, side):
        width, height, count, _ = source_info(input_path(source))
        if frame >= count:
            raise ValueError("Choose a look frame inside the source clip.")
        shot = image[0, :, :, :3].detach().cpu().numpy()
        if abs(shot.shape[1] / shot.shape[0] / (width / height) - 1) > 0.015:
            raise ValueError("A pinned look frame must have the source aspect ratio.")
        dims = canvas(width, height, side)
        guide = fit(shot, dims)
        return (torch.from_numpy(guide)[None],)


def render_master(source, images, side, directory, lossless, audio_file=None, mute=False):
    """Encode the single H3 decode. Source media provides raster, timestamps and audio."""
    w, h, n, rate = source_info(source)
    fw, fh, gw, gh = canvas(w, h, side)
    x, y = (gw - fw) // 2, (gh - fh) // 2
    stem = "Switch-X-" + uuid.uuid4().hex[:12]
    master = directory / (stem + (".mkv" if lossless else ".mov"))
    preview = directory / (stem + "-preview.mp4")
    directory.mkdir(exist_ok=True, parents=True)
    if len(images) < n or tuple(images.shape[1:]) != (gh, gw, 3):
        raise ValueError("The H3 decode does not cover the source frame count and canvas.")
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        silent = Path(tmp) / ("video" + master.suffix)
        with av.open(str(silent), "w") as dst, opened(source) as original:
            stream = dst.add_stream("ffv1" if lossless else "prores_ks", rate=rate)
            stream.width, stream.height = w, h
            stream.pix_fmt = "gbrp16le" if lossless else "yuv444p10le"
            if not lossless:
                stream.options = {"profile": "4"}
                stream.codec_context.colorspace = 1
                stream.codec_context.color_primaries = 1
                stream.codec_context.color_trc = 1

            for index, plate in enumerate(original.decode(video=0)):
                from comfy.model_management import throw_exception_if_processing_interrupted

                throw_exception_if_processing_interrupted()
                frame = (
                    images[index, y : y + fh, x : x + fw, :3]
                    .detach()
                    .to(dtype=torch.float32, device="cpu")
                    .numpy()
                )
                merged = (
                    cv2.resize(frame, (w, h), interpolation=cv2.INTER_LANCZOS4)
                    if (fw, fh) != (w, h)
                    else frame
                )
                output = av.VideoFrame.from_ndarray(
                    (merged.clip(0, 1) * 65535.0).round().astype(np.uint16), format="rgb48le"
                )
                if index == 0:
                    first_pts = plate.pts
                    stream.codec_context.time_base = plate.time_base
                if not lossless:
                    output = output.reformat(format="yuv444p10le", dst_colorspace="ITU709")
                output.pts, output.time_base = plate.pts - first_pts, plate.time_base
                if plate.duration:
                    output.duration = plate.duration
                for packet in stream.encode(output):
                    dst.mux(packet)
            for packet in stream.encode():
                dst.mux(packet)
        if index + 1 != n:
            raise ValueError("The source frame count changed before delivery.")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise ValueError("Zura SwitchX requires ffmpeg on PATH.")
        finished = Path(tmp) / master.name

        def encode(args):
            run = subprocess.run(
                [ffmpeg, "-nostdin", "-v", "error", *map(str, args)], capture_output=True
            )
            if run.returncode:
                raise RuntimeError(run.stderr.decode(errors="replace")[-1500:])

        if mute:
            encode(["-i", silent, "-map", "0:v:0", "-c:v", "copy", "-an", finished])
        elif audio_file is not None:
            encode(
                [
                    "-i",
                    silent,
                    "-i",
                    audio_file,
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "copy",
                    "-af",
                    "apad",
                    "-shortest",
                    "-c:a",
                    "pcm_s24le",
                    finished,
                ]
            )
        else:
            encode(
                [
                    "-i",
                    silent,
                    "-i",
                    source,
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a?",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "pcm_s24le",
                    finished,
                ]
            )
        proxy = Path(tmp) / preview.name
        encode(
            [
                "-i",
                finished,
                "-vf",
                "scale='min(1280,iw)':-2:force_divisible_by=2,pad=ceil(iw/2)*2:ceil(ih/2)*2",
                "-c:v",
                "libx264",
                "-crf",
                "17",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                proxy,
            ]
        )
        finished.replace(master)
        proxy.replace(preview)
    return master, preview


class SwitchDeliver:
    OUTPUT_NODE = True
    RETURN_TYPES = ()
    FUNCTION = "finish"
    CATEGORY = SwitchGuide.CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "source": ("STRING",),
                "side": ("INT", {"min": 32}),
                "lossless": ("BOOLEAN",),
            },
            "optional": {"audio_file": ("STRING",), "mute": ("BOOLEAN", {"default": False})},
        }

    def finish(self, images, source, side, lossless, audio_file="", mute=False):
        import folder_paths

        master, preview = render_master(
            input_path(source),
            images,
            side,
            Path(folder_paths.get_output_directory()) / "Zura SwitchX",
            lossless,
            input_path(audio_file) if audio_file else None,
            mute,
        )

        def asset(path):
            return {"filename": path.name, "type": "output", "subfolder": "Zura SwitchX"}

        return {"ui": {"master": [asset(master)], "videos": [asset(preview)]}}


NODE_CLASS_MAPPINGS = {
    "ZuraSwitchXProtectedLatent": ZuraSwitchXProtectedLatent,
    "ZuraH3SourceStructure": ZuraH3SourceStructure,
    "ZuraSwitchXGuide": SwitchGuide,
    "ZuraSwitchXLookFrame": SwitchLookFrame,
    "ZuraSwitchXDeliver": SwitchDeliver,
}
