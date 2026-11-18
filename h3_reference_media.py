"""Lightweight reference media preparation shipped with Zura Studio."""
import math
import torch


def reference_audio(audio, start, seconds):
    if audio is None:
        return None
    rate = int(audio["sample_rate"])
    wave = audio["waveform"]
    if rate <= 0 or wave.ndim != 3 or wave.shape[1] not in (1, 2):
        raise ValueError("Reference audio must be mono or stereo with a valid sample rate.")
    first = round(start * rate)
    wave = wave[..., first:first + round(seconds * rate)]
    if not wave.shape[-1]:
        raise ValueError("The selected reference audio interval is empty.")
    if wave.shape[1] == 1:
        wave = wave.repeat(1, 2, 1)
    return {**audio, "waveform": wave, "sample_rate": rate}


class H3ReferenceAudio:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio": ("AUDIO",), "max_seconds": ("FLOAT", {"default": 10.0, "min": 0.1, "max": 15.0})}}

    RETURN_TYPES = ("AUDIO",)
    FUNCTION = "prepare"
    CATEGORY = "Zura/Artist Studio/References"

    def prepare(self, audio, max_seconds):
        if not math.isfinite(max_seconds) or not 0 < max_seconds <= 15:
            raise ValueError("Reference audio duration must be between 0 and 15 seconds.")
        return (reference_audio(audio, 0, max_seconds),)


class H3ReferenceVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "frames": ("IMAGE",),
            "start_seconds": ("FLOAT", {"default": 0.0, "min": 0.0}),
            "seconds": ("FLOAT", {"default": 3.0, "min": 0.1, "max": 15.0}),
            "source_fps": ("FLOAT", {"default": 24.0, "min": 0.01}),
        }, "optional": {"audio": ("AUDIO",)}}

    RETURN_TYPES = ("IMAGE", "AUDIO")
    RETURN_NAMES = ("frames", "audio")
    FUNCTION = "prepare"
    CATEGORY = "Zura/Artist Studio/References"

    def prepare(self, frames, start_seconds, seconds, source_fps, audio=None):
        if not all(math.isfinite(x) for x in (start_seconds, seconds, source_fps)) or start_seconds < 0 or not 0 < seconds <= 15 or source_fps <= 0:
            raise ValueError("Choose a valid reference interval and source frame rate.")
        if frames.ndim != 4 or not frames.shape[0]:
            raise ValueError("Reference video has no decoded frames.")
        duration = min(seconds, frames.shape[0] / source_fps - start_seconds)
        count = math.floor(duration * 24 + 1e-6)
        if count < 5:
            raise ValueError("Reference video needs at least five frames at 24 fps.")
        indices = ((torch.arange(count, device=frames.device, dtype=torch.float64) / 24 + start_seconds) * source_fps).floor().long().clamp(max=frames.shape[0] - 1)
        return frames.index_select(0, indices), reference_audio(audio, start_seconds, count / 24)


NODE_CLASS_MAPPINGS = {"H3ReferenceVideo": H3ReferenceVideo, "H3ReferenceAudio": H3ReferenceAudio}
NODE_DISPLAY_NAME_MAPPINGS = {"H3ReferenceVideo": "Zura · Prepare H3 Reference Video", "H3ReferenceAudio": "Zura · Prepare H3 Reference Audio"}
