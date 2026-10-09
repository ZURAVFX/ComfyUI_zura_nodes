import hashlib
import json
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

import folder_paths
from comfy_api.latest import InputImpl, Types


CATEGORY = "Zura/Artist Studio"


def ffmpeg(*args):
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("Install FFmpeg and add it to PATH, then restart ComfyUI.")
    result = subprocess.run([executable, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])


def root():
    path = Path(folder_paths.get_output_directory()) / "genj"
    path.mkdir(parents=True, exist_ok=True)
    return path


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def source_path(video):
    value = video.get_stream_source()
    if isinstance(value, str):
        return Path(value)
    path = root() / "scratch" / (hashlib.sha256(value.getbuffer()).hexdigest() + ".mp4")
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        path.write_bytes(value.getbuffer())
    return path


def encode_frames(path, frames, fps=24):
    h, w = frames.shape[1:3]
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=Fraction(str(fps)))
        stream.width, stream.height = w, h
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "16", "preset": "fast"}
        for i, tensor in enumerate(frames):
            data = (tensor.detach().cpu().clamp(0, 1).numpy() * 255).round().astype(np.uint8)
            frame = av.VideoFrame.from_ndarray(data, format="rgb24")
            frame.pts, frame.time_base = i, 1 / Fraction(str(fps))
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def fit_audio(audio, seconds):
    """Native AUDIO, including a valid silence tensor for silent source videos."""
    if audio is None:
        audio = {"sample_rate": 48000, "waveform": torch.zeros(1, 2, round(seconds * 48000))}
    rate = int(audio["sample_rate"])
    waveform = audio["waveform"].detach().cpu().float()
    if rate <= 0 or waveform.ndim != 3 or waveform.shape[0] != 1 or not torch.isfinite(waveform).all():
        raise ValueError("Choose one valid reference audio track.")
    samples = round(seconds * rate)
    return {"sample_rate": rate, "waveform": F.pad(waveform[..., :samples],
            (0, max(0, samples - waveform.shape[-1])))}


def reference_audio(details, audio, start):
    rate = int(audio["sample_rate"])
    if not np.isfinite(start) or start < 0 or start * rate >= audio["waveform"].shape[-1]:
        raise ValueError("The audio start must be within the reference track.")
    selected = fit_audio({**audio, "waveform": audio["waveform"][..., round(start * rate):]}, details["duration"])
    key = hashlib.sha256(selected["waveform"].numpy().tobytes() + str(rate).encode()).hexdigest()
    path = root() / "reference_audio" / (key + ".wav")
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        raw = path.with_suffix(".f32")
        selected["waveform"][0].numpy().T.copy().tofile(raw)
        try:
            ffmpeg("-f", "f32le", "-ar", rate, "-ac", selected["waveform"].shape[1], "-i", raw,
                   "-c:a", "pcm_f32le", path)
        finally:
            raw.unlink(missing_ok=True)
    return selected, {**details, "audio_source": str(path), "audio_hash": digest_file(path),
                      "audio_mode": "reference", "has_audio": True}


class GenjApplyReferenceAudio:
    """Thin adapter; native LoadAudio stays visible and editable in graph view."""
    CATEGORY = CATEGORY
    FUNCTION = "apply"
    RETURN_TYPES = ("VIDEO", "GENJ_CLIP")
    RETURN_NAMES = ("video_with_reference_audio", "clip_details")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"video": ("VIDEO",), "clip_details": ("GENJ_CLIP",),
                "audio_start_seconds": ("FLOAT", {"default": 0, "min": 0, "max": 86400, "step": .1})},
                "optional": {"audio": ("AUDIO",)}}

    def apply(self, video, clip_details, audio_start_seconds=0, audio=None):
        components = video.get_components()
        details = dict(clip_details)
        if audio is not None:
            audio, details = reference_audio(details, audio, audio_start_seconds)
        else:
            audio = fit_audio(components.audio, details["duration"])
        return InputImpl.VideoFromComponents(Types.VideoComponents(images=components.images,
            audio=audio, frame_rate=components.frame_rate)), details


def verify_review(review_id):
    if not re.fullmatch(r"shot_[a-f0-9]{16}", review_id):
        raise ValueError("Prepare and review the shot in Zura Studio before generating.")
    directory = root() / "reviews" / review_id
    manifest = json.loads((directory / "review.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        if digest_file(directory / name) != expected:
            raise ValueError("This review has changed. Prepare the shot and inspect the new review.")
    if digest_file(manifest["clip"]["source"]) != manifest["clip"]["source_hash"]:
        raise ValueError("The original source changed. Prepare and review the shot again before generation.")
    if manifest["clip"].get("audio_source") and digest_file(manifest["clip"]["audio_source"]) != manifest["clip"]["audio_hash"]:
        raise ValueError("The reference audio changed. Prepare the shot again.")
    return directory, manifest


class GenjSelectClip:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video": ("VIDEO",),
            "start_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 86400.0, "step": 0.1}),
            "duration_seconds": ("FLOAT", {"default": 4.0, "min": 0.1, "max": 30.0, "step": 0.1}),
            "long_edge": ("INT", {"default": 768, "min": 256, "max": 1920, "step": 64}),
        }, "optional": {"audio": ("AUDIO",), "audio_start_seconds": ("FLOAT", {"default": 0, "min": 0, "max": 86400, "step": .1}),
                        "use_original_length": ("BOOLEAN", {"default": False, "tooltip": "Use the whole source video from the beginning."})}}

    RETURN_TYPES = ("VIDEO", "GENJ_CLIP", "STRING")
    RETURN_NAMES = ("selected_clip", "clip_details", "clip_summary")
    FUNCTION = "select"
    CATEGORY = CATEGORY

    def select(self, video, start_seconds, duration_seconds, long_edge, audio=None, audio_start_seconds=0, use_original_length=False):
        source = source_path(video)
        with av.open(str(source)) as c:
            stream = c.streams.video[0]
            available = float(stream.duration * stream.time_base) if stream.duration else float(c.duration / av.time_base)
            width, height = video.get_dimensions()
            has_audio = bool(c.streams.audio)
        if use_original_length:
            start_seconds, duration_seconds = 0.0, available
        if start_seconds >= available:
            raise ValueError("The start time is beyond the end of this video.")
        frames = max(1, int(min(duration_seconds, available - start_seconds) * 24 + 1e-6))
        duration = frames / 24
        scale = min(1.0, long_edge / max(width, height))
        w, h = max(64, round(width * scale / 64) * 64), max(64, round(height * scale / 64) * 64)
        details = {"source": str(source), "source_hash": digest_file(source), "start": start_seconds,
                   "duration": duration, "frames": frames, "fps": 24, "width": w, "height": h,
                   "full_source": start_seconds == 0 and abs(duration - available) <= 1 / 24, "has_audio": has_audio}
        if audio is not None:
            _, details = reference_audio(details, audio, audio_start_seconds)
        key = hashlib.sha256(json.dumps(details, sort_keys=True).encode()).hexdigest()[:16]
        path = root() / "clips" / (key + ".mp4")
        path.parent.mkdir(exist_ok=True)
        if not path.exists():
            audio_codec = ["-c:a", "copy"] if details["full_source"] and has_audio and audio is None else ["-c:a", "aac", "-b:a", "256k"]
            second = (["-i", details["audio_source"]] if audio is not None else
                      [] if has_audio else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"])
            ffmpeg("-ss", start_seconds, "-i", source, *second, "-t", duration, "-map", "0:v:0", "-map", "1:a:0" if second else "0:a:0",
                   "-vf", f"fps=24,scale={w}:{h}:flags=lanczos", "-frames:v", frames,
                   "-c:v", "libx264", "-crf", 16, "-pix_fmt", "yuv420p", *audio_codec, "-movflags", "+faststart", path)
        details["selected_path"] = str(path)
        return (InputImpl.VideoFromFile(str(path)), details, f"{duration:.3f}s from {start_seconds:.3f}s | {frames} frames | {w} x {h} | 24 fps")


class GenjChoosePerformer:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"masks": ("MASK",), "performer": ("INT", {"default": -1, "min": -1, "max": 63,
                "tooltip": "-1 selects the largest central detection. Otherwise use a zero-based detection index."})}}

    RETURN_TYPES = ("MASK", "STRING")
    RETURN_NAMES = ("initial_performer_mask", "selection")
    FUNCTION = "choose"
    CATEGORY = CATEGORY

    def choose(self, masks, performer):
        areas = masks.sum(dim=(-1, -2))
        valid = areas > 1
        if not bool(valid.any()):
            raise ValueError("No performer detected. Try 'person', lower the detection threshold, or select a clearer opening frame.")
        if performer == -1:
            h, w = masks.shape[-2:]
            ys = torch.arange(h, device=masks.device, dtype=masks.dtype)[None, :, None]
            xs = torch.arange(w, device=masks.device, dtype=masks.dtype)[None, None, :]
            cx = (masks * xs).sum((-1, -2)) / areas.clamp_min(1)
            cy = (masks * ys).sum((-1, -2)) / areas.clamp_min(1)
            distance = ((cx / w - 0.5) ** 2 + (cy / h - 0.5) ** 2)
            score = areas / (1 + 4 * distance)
            score[~valid] = -1
            performer = int(score.argmax())
        if performer >= len(masks):
            raise ValueError(f"Detected {len(masks)} objects. Select an index from 0 to {len(masks) - 1}.")
        if performer < 0 or not bool(valid[performer]):
            raise ValueError("The selected detection is empty. Select a visible performer.")
        return (masks[performer:performer + 1], f"Tracking detection {performer} of {len(masks)}")


class GenjColourDepth:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"depth": ("IMAGE",)}}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("coloured_depth",)
    FUNCTION = "colour"
    CATEGORY = CATEGORY

    def colour(self, depth):
        value = depth[..., :3].mean(-1)
        red = (1.5 - (4 * value - 3).abs()).clamp(0, 1)
        green = (1.5 - (4 * value - 2).abs()).clamp(0, 1)
        blue = (1.5 - (4 * value - 1).abs()).clamp(0, 1)
        return (torch.stack((red, green, blue), dim=-1),)


class GenjVoiceGuidance:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"original_audio": ("AUDIO",), "pitch_vocals": ("BOOLEAN", {"default": False}),
                             "semitones": ("FLOAT", {"default": 3.0, "min": -12.0, "max": 12.0, "step": 0.5})},
                "optional": {"isolated_vocals": ("AUDIO", {"lazy": True})}}

    RETURN_TYPES = ("AUDIO",)
    FUNCTION = "pitch"
    CATEGORY = CATEGORY

    def check_lazy_status(self, original_audio, pitch_vocals, semitones, isolated_vocals=None):
        return ["isolated_vocals"] if pitch_vocals and isolated_vocals is None else []

    def pitch(self, original_audio, pitch_vocals, semitones, isolated_vocals=None):
        if not pitch_vocals:
            return (original_audio,)
        if isolated_vocals is None:
            raise ValueError("Connect isolated vocals before enabling Pitch Vocals. This keeps music out of the pitch shift.")
        rate = isolated_vocals["sample_rate"]
        waveform = isolated_vocals["waveform"][0].detach().cpu().float().numpy()
        scratch = root() / "scratch"
        scratch.mkdir(exist_ok=True)
        key = hashlib.sha256(waveform.tobytes() + str((rate, semitones)).encode()).hexdigest()[:16]
        raw, changed = scratch / (key + ".f32"), scratch / (key + "_pitched.f32")
        waveform.T.tofile(raw)
        ffmpeg("-f", "f32le", "-ar", rate, "-ac", waveform.shape[0], "-i", raw,
               "-af", f"rubberband=pitch={2 ** (semitones / 12)}", "-f", "f32le", changed)
        data = np.fromfile(changed, np.float32).reshape(-1, waveform.shape[0]).T.copy()
        length = round(original_audio["waveform"].shape[-1] * rate / original_audio["sample_rate"])
        data = np.pad(data[:, :length], ((0, 0), (0, max(0, length - data.shape[-1]))))
        return ({"waveform": torch.from_numpy(data).unsqueeze(0), "sample_rate": rate},)


class GenjSaveReview:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"clip_details": ("GENJ_CLIP",), "source_frames": ("IMAGE",),
                             "mask": ("MASK",), "guide_frames": ("IMAGE",), "guidance_audio": ("AUDIO",)}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("shot_id",)
    FUNCTION = "save"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def save(self, clip_details, source_frames, mask, guide_frames, guidance_audio):
        count, h, w = source_frames.shape[:3]
        if len(mask) != count or len(guide_frames) != count:
            raise ValueError("Source, mask and guidance must have the same number of frames.")
        mask = F.interpolate(mask[:, None].float(), size=(h, w), mode="nearest")[:, 0]
        mask = (mask >= 0.5).float()
        if not bool(mask.any()):
            raise ValueError("The performer mask is empty. Repair it before generation.")
        key = hashlib.sha256(json.dumps(clip_details, sort_keys=True).encode())
        for frames in (mask, guide_frames):
            for frame in frames:
                key.update(frame.detach().cpu().numpy().tobytes())
        key.update(guidance_audio["waveform"].detach().cpu().numpy().tobytes())
        key.update(str(guidance_audio["sample_rate"]).encode())
        shot_id = "shot_" + key.hexdigest()[:16]
        directory = root() / "reviews" / shot_id
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(clip_details["selected_path"], directory / "source.mp4")
        encode_frames(directory / "mask.mp4", mask[..., None].repeat(1, 1, 1, 3))
        guide_video = InputImpl.VideoFromComponents(Types.VideoComponents(images=guide_frames, audio=guidance_audio, frame_rate=Fraction(24)))
        guide_video.save_to(str(directory / "guide.mp4"))
        tint = torch.tensor([1.0, 0.35, 0.1], device=source_frames.device)
        overlay = source_frames * (1 - mask[..., None] * 0.5) + tint * mask[..., None] * 0.5
        encode_frames(directory / "mask_review.mp4", overlay)
        first = (source_frames[0].detach().cpu().clamp(0, 1).numpy() * 255).round().astype(np.uint8)
        Image.fromarray(first).save(directory / "opening_frame.png")
        files = {name: digest_file(directory / name) for name in
                 ["source.mp4", "mask.mp4", "guide.mp4", "mask_review.mp4", "opening_frame.png"]}
        manifest = {"shot_id": shot_id, "clip": clip_details, "files": files}
        (directory / "review.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        text = f"{shot_id}\nMask ready. Review the full mask and guidance previews in Zura Studio, then choose Use this mask. Zura Studio links this shot automatically."
        previews = [{"filename": name, "subfolder": f"genj/reviews/{shot_id}", "type": "output", "format": "video/mp4"}
                    for name in ["mask_review.mp4", "guide.mp4"]]
        return {"ui": {"text": [text], "gifs": previews}, "result": (shot_id,)}


class GenjLoadReviewedShot:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"shot_id": ("STRING", {"default": "", "multiline": False}),
                             "approved_shot_id": ("STRING", {"default": "", "multiline": False,
                             "tooltip": "Studio fills this automatically after review. Standalone graphs must use matching reviewed and approved IDs."})},
                "optional": {"render_long_edge": ("INT", {"default": 0, "min": 0, "max": 1920,
                    "tooltip": "0 uses the reviewed preview. Higher values reread the original footage and resize the approved mask."}),
                    "output_scale": ("INT", {"default": 1, "min": 1, "max": 2}),
                    "preview_seconds": ("FLOAT", {"default": 0, "min": 0, "max": 30})}}

    RETURN_TYPES = ("VIDEO", "VIDEO", "VIDEO", "GENJ_CLIP")
    RETURN_NAMES = ("source_clip", "performer_mask", "seedance_guide", "clip_details")
    FUNCTION = "load"
    CATEGORY = CATEGORY

    @classmethod
    def IS_CHANGED(cls, shot_id, approved_shot_id, render_long_edge=0, output_scale=1, preview_seconds=0):
        if shot_id and shot_id == approved_shot_id:
            directory, manifest = verify_review(shot_id)
            source_hash = digest_file(manifest["clip"]["source"]) if render_long_edge else ""
            return digest_file(directory / "review.json") + source_hash + str((render_long_edge, output_scale, preview_seconds))
        return float("nan")

    def load(self, shot_id, approved_shot_id, render_long_edge=0, output_scale=1, preview_seconds=0):
        if not shot_id or shot_id != approved_shot_id:
            raise ValueError("Approve the reviewed mask in Zura Studio before generation. Standalone graphs require matching reviewed and approved shot IDs.")
        directory, manifest = verify_review(shot_id)
        details = {**manifest["clip"], "review_shot_id": shot_id}
        if render_long_edge:
            source = Path(details["source"])
            if digest_file(source) != details["source_hash"]:
                raise ValueError("The original source changed after mask approval. Prepare the shot again.")
            if not 256 <= render_long_edge <= 1920:
                raise ValueError("Choose a render size between 256 and 1920 pixels.")
            with av.open(str(source)) as c:
                stream = c.streams.video[0]
                sw, sh = stream.width, stream.height
            scale = render_long_edge / max(sw, sh)
            if output_scale not in (1, 2):
                raise ValueError("Unsupported output scale.")
            w, h = max(64, round(sw * scale / output_scale / 64) * 64), max(64, round(sh * scale / output_scale / 64) * 64)
            target_w, target_h = max(2, round(sw * scale / 2) * 2), max(2, round(sh * scale / 2) * 2)
            if preview_seconds:
                details["frames"] = min(details["frames"], max(1, int(preview_seconds * 24)))
                details["duration"] = details["frames"] / 24
                details["full_source"] = False
            cache = directory / f"render_audio_v2_{render_long_edge}_x{output_scale}_{details['frames']}f"
            cache.mkdir(exist_ok=True)
            high_source, high_mask = cache / "source.mp4", cache / "mask.mp4"
            if not high_source.exists():
                # The reviewed clip already contains the selected reference or silence.
                # Reread full-resolution RGB, but preserve that exact audio selection.
                ffmpeg("-ss", details["start"], "-i", source, "-i", directory / "source.mp4",
                       "-t", details["duration"], "-map", "0:v:0", "-map", "1:a:0",
                       "-vf", f"fps=24,scale={w}:{h}:flags=lanczos", "-frames:v", details["frames"],
                       "-c:v", "libx264", "-crf", 16, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", high_source)
            if not high_mask.exists():
                ffmpeg("-i", directory / "mask.mp4", "-vf", "fps=24",
                       "-frames:v", details["frames"], "-an", "-c:v", "libx264", "-crf", 0, "-pix_fmt", "yuv420p", high_mask)
            details.update(width=w, height=h, export_width=target_w, export_height=target_h,
                           render_long_edge=render_long_edge, selected_path=str(high_source))
            guide = directory / "guide.mp4"
            if preview_seconds:
                guide = cache / "guide.mp4"
                if not guide.exists():
                    ffmpeg("-i", directory / "guide.mp4", "-t", details["duration"], "-frames:v", details["frames"],
                           "-c:v", "libx264", "-crf", 16, "-c:a", "aac", guide)
            return (InputImpl.VideoFromFile(str(high_source)), InputImpl.VideoFromFile(str(high_mask)),
                    InputImpl.VideoFromFile(str(guide)), details)
        return (*(InputImpl.VideoFromFile(str(directory / name)) for name in ["source.mp4", "mask.mp4", "guide.mp4"]), details)


class GenjLTXFramePad:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"video": ("VIDEO",)}}

    RETURN_TYPES = ("VIDEO",)
    FUNCTION = "pad"
    CATEGORY = CATEGORY

    def pad(self, video):
        components = video.get_components()
        images = components.images
        extra = (1 - len(images)) % 8
        if not extra and components.audio is not None:
            return (video,)
        if extra:
            images = torch.cat((images, images[-1:].expand(extra, -1, -1, -1)), dim=0)
        audio = fit_audio(components.audio, len(images) / float(components.frame_rate))
        return (InputImpl.VideoFromComponents(Types.VideoComponents(images=images, audio=audio, frame_rate=components.frame_rate)),)


def text_cache_path(cache_key):
    if not re.fullmatch(r"[a-f0-9]{64}", cache_key):
        raise ValueError("Invalid local prompt cache key.")
    directory = root() / "text_cache"
    directory.mkdir(exist_ok=True)
    return directory / (cache_key + ".pt")


class GenjSaveTextConditioning:
    """Thin tensor adapter. Text encoding remains in native CLIPTextEncode."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"positive": ("CONDITIONING",), "negative": ("CONDITIONING",),
                             "cache_key": ("STRING", {"default": ""})}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "save"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def save(self, positive, negative, cache_key):
        def cpu(value):
            if isinstance(value, torch.Tensor): return value.detach().cpu()
            if isinstance(value, dict): return {k: cpu(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)): return [cpu(v) for v in value]
            if value is None or isinstance(value, (str, bool, int, float)): return value
            raise ValueError("The native encoder returned an unsupported cache value.")
        path = text_cache_path(cache_key)
        temporary = path.with_suffix(".tmp")
        torch.save({"positive": cpu(positive), "negative": cpu(negative)}, temporary)
        temporary.replace(path)
        return {"ui": {"text": ["Local video prompt ready."]}, "result": (cache_key,)}


class GenjLoadTextConditioning:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cache_key": ("STRING", {"default": ""})}}
    RETURN_TYPES = ("CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("positive", "negative")
    FUNCTION = "load"
    CATEGORY = CATEGORY

    @classmethod
    def IS_CHANGED(cls, cache_key):
        return digest_file(text_cache_path(cache_key))

    def load(self, cache_key):
        # weights_only excludes arbitrary pickle code from this local tensor cache.
        data = torch.load(text_cache_path(cache_key), map_location="cpu", weights_only=True)
        return data["positive"], data["negative"]


class GenjApproveDraft:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"draft_task_id": ("STRING", {"default": ""}),
                             "accepted_draft_id": ("STRING", {"default": ""}), "clip_details": ("GENJ_CLIP",)}}

    RETURN_TYPES = ("STRING",)
    FUNCTION = "approve"
    CATEGORY = CATEGORY

    def approve(self, draft_task_id, accepted_draft_id, clip_details):
        if not draft_task_id.strip() or draft_task_id != accepted_draft_id:
            raise ValueError("Watch the draft first, then paste its task ID into both fields to authorise the separately billed 1080p final.")
        record = root() / "drafts" / (hashlib.sha256(draft_task_id.encode()).hexdigest() + ".json")
        if not record.exists() or json.loads(record.read_text(encoding="utf8"))["shot_id"] != clip_details["review_shot_id"]:
            raise ValueError("This draft does not belong to the approved shot. Use the source shot ID recorded when the draft completed.")
        return (draft_task_id,)


class GenjRecordDraft:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"draft_task_id": ("STRING", {"forceInput": True}), "clip_details": ("GENJ_CLIP",)}}

    RETURN_TYPES = ("STRING",)
    FUNCTION = "record"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def record(self, draft_task_id, clip_details):
        if not draft_task_id.strip():
            raise ValueError("Seedance did not return a draft task ID.")
        folder = root() / "drafts"
        folder.mkdir(exist_ok=True)
        record = {"draft_task_id": draft_task_id, "shot_id": clip_details["review_shot_id"]}
        path = folder / (hashlib.sha256(draft_task_id.encode()).hexdigest() + ".json")
        path.write_text(json.dumps(record, indent=2), encoding="utf8")
        return {"ui": {"text": [f"Draft task ID: {draft_task_id}\nSource shot: {record['shot_id']}\nInspect the draft before authorising a final render."]}, "result": (draft_task_id,)}


class GenjRestoreSoundtrack:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"video": ("VIDEO",), "clip_details": ("GENJ_CLIP",),
                             "take_name": ("STRING", {"default": "replacement", "multiline": False})}}

    RETURN_TYPES = ("VIDEO",)
    FUNCTION = "restore"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def restore(self, video, clip_details, take_name):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", take_name):
            raise ValueError("Take name can contain letters, numbers, underscores and hyphens.")
        source = Path(clip_details["source"])
        if digest_file(source) != clip_details["source_hash"]:
            raise ValueError("The original source changed after review. Prepare and review the shot again.")
        generated = source_path(video)
        with av.open(str(generated)) as c:
            vs = c.streams.video[0]
            duration = float(vs.duration * vs.time_base) if vs.duration else float(c.duration / av.time_base)
        target_duration = clip_details["duration"]
        if duration + 1 / 24 < target_duration:
            raise ValueError(f"Generated video is too short ({duration:.3f}s for {target_duration:.3f}s). The source soundtrack will not be shortened to hide this.")
        destination = root() / "final"
        destination.mkdir(exist_ok=True)
        existing = list(destination.glob(take_name + "_*.mp4"))
        number = max([int(p.stem.rsplit("_", 1)[1]) for p in existing if p.stem.rsplit("_", 1)[1].isdigit()], default=0) + 1
        path = destination / f"{take_name}_{number:05d}.mp4"
        external = clip_details.get("audio_source")
        if external and digest_file(external) != clip_details["audio_hash"]:
            raise ValueError("The reference audio changed after review.")
        soundtrack = external or source
        offset = 0 if external else clip_details["start"]
        audio = ["-c:a", "copy"] if clip_details["full_source"] and not external else ["-c:a", "aac", "-b:a", "256k"]
        vf = "fps=24"
        if clip_details.get("export_width") and clip_details.get("export_height"):
            vf += f",scale={clip_details['export_width']}:{clip_details['export_height']}:flags=lanczos"
        ffmpeg("-i", generated, "-ss", offset, "-i", soundtrack, "-map", "0:v:0", "-map", "1:a:0?",
               "-t", target_duration, "-vf", vf, "-frames:v", clip_details["frames"],
               "-c:v", "libx264", "-crf", 16, "-pix_fmt", "yuv420p", *audio, "-movflags", "+faststart", path)
        preview = {"filename": path.name, "subfolder": "genj/final", "type": "output", "format": "video/mp4"}
        return {"ui": {"gifs": [preview], "text": [f"Saved {path.name} with the selected soundtrack."]},
                "result": (InputImpl.VideoFromFile(str(path)),)}


NODE_CLASS_MAPPINGS = {cls.__name__: cls for cls in [GenjSelectClip, GenjChoosePerformer, GenjColourDepth,
    GenjVoiceGuidance, GenjSaveReview, GenjLoadReviewedShot, GenjLTXFramePad, GenjApproveDraft, GenjRecordDraft,
    GenjRestoreSoundtrack, GenjSaveTextConditioning, GenjLoadTextConditioning, GenjApplyReferenceAudio]}
NODE_DISPLAY_NAME_MAPPINGS = {"GenjSelectClip": "Choose Clip", "GenjChoosePerformer": "Choose Performer",
    "GenjColourDepth": "Colour Depth for Seedance", "GenjVoiceGuidance": "Voice Guidance",
    "GenjSaveReview": "Save Guidance Review", "GenjLoadReviewedShot": "Load Reviewed Shot",
    "GenjRestoreSoundtrack": "Zura · Save with Selected Audio", "GenjApplyReferenceAudio": "Zura · Reference Audio (Optional)", "GenjLTXFramePad": "LTX Frame Padding",
    "GenjApproveDraft": "Accept Draft for Final"}
NODE_DISPLAY_NAME_MAPPINGS["GenjRecordDraft"] = "Record Draft and Source Shot"
NODE_DISPLAY_NAME_MAPPINGS.update({"GenjSaveTextConditioning": "Cache Video Prompt",
    "GenjLoadTextConditioning": "Load Video Prompt"})

from .h3 import NODE_CLASS_MAPPINGS as H3_NODES, NODE_DISPLAY_NAME_MAPPINGS as H3_NAMES
NODE_CLASS_MAPPINGS.update(H3_NODES)
NODE_DISPLAY_NAME_MAPPINGS.update(H3_NAMES)
from .text_removal import NODE_CLASS_MAPPINGS as TEXT_NODES, NODE_DISPLAY_NAME_MAPPINGS as TEXT_NAMES
NODE_CLASS_MAPPINGS.update(TEXT_NODES)
NODE_DISPLAY_NAME_MAPPINGS.update(TEXT_NAMES)

# The artist interface uses native inference nodes through ComfyUI's queue.
WEB_DIRECTORY = "./web"
from .studio import register
register()
