"""Pure frame, audio-slice and latent-prefix helpers for bounded MiniMax H3 work.

This module does not run a model or decode media. Window plans use half-open
global frame intervals at 24 fps. A caller must provide cut starts that have
already been verified against the reviewed source.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

import torch


H3_CONTEXT_FRAMES = 124
H3_PREFIX_FRAMES = 5
H3_FPS = 24
H3_MIN_FINAL_PAYLOAD = 34


@dataclass(frozen=True)
class H3Window:
    """One model context and the exact source frames it owns on delivery."""

    index: int
    shot_index: int
    shot_start: int
    shot_end: int
    input_start: int
    valid_frames: int
    owned_start: int
    owned_end: int
    overlap_frames: int
    padded_frames: int
    carry_video_tokens: int | None

    @property
    def input_end(self) -> int:
        return self.input_start + self.valid_frames

    @property
    def owned_frames(self) -> int:
        return self.owned_end - self.owned_start

    @property
    def is_terminal(self) -> bool:
        return self.carry_video_tokens is None


@dataclass(frozen=True)
class H3VideoPrefix:
    """Two sampled native H3 video tokens, copied to CPU at a valid endpoint."""

    video_tokens: torch.Tensor
    valid_frames: int
    token_count: int


def _integer(value: object, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer.")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return value


def h3_video_token_count(valid_frames: int) -> int:
    """Return the native latent token count at a real 17k+5 frame endpoint."""

    valid_frames = _integer(valid_frames, "valid_frames", minimum=H3_PREFIX_FRAMES)
    if (valid_frames - H3_PREFIX_FRAMES) % 17:
        raise ValueError("A carried H3 window must end on the native 17k+5 frame grid.")
    return 2 + 5 * ((valid_frames - H3_PREFIX_FRAMES) // 17)


def _shot_windows(shot_index: int, shot_start: int, shot_end: int,
                  first_index: int) -> list[H3Window]:
    length = shot_end - shot_start
    if length <= 0:
        raise ValueError("Each verified shot must contain at least one frame.")

    parts: list[H3Window] = []
    owned_cursor = shot_start
    first = True

    while owned_cursor < shot_end:
        remaining = shot_end - owned_cursor
        if first and remaining <= H3_CONTEXT_FRAMES:
            valid = remaining
            input_start = owned_cursor
            overlap = 0
            owned_count = valid
            terminal = True
        elif not first and remaining <= H3_CONTEXT_FRAMES - H3_PREFIX_FRAMES:
            valid = H3_PREFIX_FRAMES + remaining
            input_start = owned_cursor - H3_PREFIX_FRAMES
            overlap = H3_PREFIX_FRAMES
            owned_count = remaining
            terminal = True
        elif first:
            # The first context owns its full valid span. Shorten it in 17-frame
            # blocks when a nearly empty final owner would otherwise remain.
            valid = H3_CONTEXT_FRAMES
            while 0 < remaining - valid < H3_MIN_FINAL_PAYLOAD:
                valid -= 17
            if valid < H3_PREFIX_FRAMES or (valid - H3_PREFIX_FRAMES) % 17:
                raise ValueError("Could not align the first H3 context for a safe tail.")
            input_start = owned_cursor
            overlap = 0
            owned_count = valid
            terminal = False
        else:
            # Subsequent contexts include five repeated frames. Their new
            # owned payload is valid-5, and their endpoint must stay on 17k+5.
            valid = H3_CONTEXT_FRAMES
            while 0 < remaining - (valid - H3_PREFIX_FRAMES) < H3_MIN_FINAL_PAYLOAD:
                valid -= 17
            if valid <= H3_PREFIX_FRAMES or (valid - H3_PREFIX_FRAMES) % 17:
                raise ValueError("Could not align an H3 continuation context for a safe tail.")
            input_start = owned_cursor - H3_PREFIX_FRAMES
            overlap = H3_PREFIX_FRAMES
            owned_count = valid - H3_PREFIX_FRAMES
            terminal = False

        owned_end = owned_cursor + owned_count
        if not (0 < owned_count <= remaining):
            raise ValueError("The H3 window plan made no forward progress.")
        if valid > H3_CONTEXT_FRAMES or valid < 1:
            raise ValueError("The H3 window does not fit its bounded model context.")
        if input_start < shot_start or input_start + valid != owned_end:
            raise ValueError("An H3 window crosses its shot or has inconsistent chronology.")
        if not terminal:
            h3_video_token_count(valid)
            if shot_end - owned_end < H3_MIN_FINAL_PAYLOAD:
                raise ValueError("A nonterminal H3 window leaves an undersized final payload.")

        parts.append(H3Window(
            index=first_index + len(parts),
            shot_index=shot_index,
            shot_start=shot_start,
            shot_end=shot_end,
            input_start=input_start,
            valid_frames=valid,
            owned_start=owned_cursor,
            owned_end=owned_end,
            overlap_frames=overlap,
            padded_frames=H3_CONTEXT_FRAMES - valid,
            carry_video_tokens=(2 if not terminal else None),
        ))
        owned_cursor = owned_end
        first = False

    return parts


def plan_h3_windows(total_frames: int,
                    verified_cut_starts: Sequence[int] = ()) -> tuple[H3Window, ...]:
    """Plan deterministic 124-frame contexts, resetting continuation at cuts.

    ``verified_cut_starts`` contains global indices of the first frame after a
    real, reviewed cut. Every cut is a hard shot boundary: no window or five
    frame continuation prefix may span it.
    """

    total_frames = _integer(total_frames, "total_frames", minimum=1)
    if (not isinstance(verified_cut_starts, Sequence)
            or isinstance(verified_cut_starts, (str, bytes))):
        raise ValueError("Verified cut starts must be a sequence of frame indices.")
    cuts = tuple(verified_cut_starts)
    previous = 0
    for cut in cuts:
        cut = _integer(cut, "verified cut start", minimum=1)
        if cut >= total_frames or cut <= previous:
            raise ValueError("Verified cut starts must be unique, increasing and inside the clip.")
        previous = cut

    boundaries = (0, *cuts, total_frames)
    result: list[H3Window] = []
    for shot_index, (shot_start, shot_end) in enumerate(zip(boundaries, boundaries[1:])):
        result.extend(_shot_windows(shot_index, shot_start, shot_end, len(result)))

    cursor = 0
    for part in result:
        if part.owned_start != cursor or part.owned_end <= part.owned_start:
            raise ValueError("H3 owned frame intervals must cover the clip exactly once.")
        if part.input_start < part.shot_start or part.input_end > part.shot_end:
            raise ValueError("H3 model input cannot cross a verified cut.")
        if part.overlap_frames not in (0, H3_PREFIX_FRAMES):
            raise ValueError("H3 continuation overlap must be zero or exactly five frames.")
        if part.overlap_frames and part.input_start + part.overlap_frames != part.owned_start:
            raise ValueError("The H3 repeated prefix does not meet the owned interval.")
        cursor = part.owned_end
    if cursor != total_frames:
        raise ValueError("H3 owned intervals do not reach the clip end.")
    return tuple(result)


def audio_sample_bounds(start_frame: int, end_frame: int,
                        sample_rate: int) -> tuple[int, int]:
    """Map global 24 fps frame boundaries to exact, independently floored samples."""

    start_frame = _integer(start_frame, "start_frame", minimum=0)
    end_frame = _integer(end_frame, "end_frame", minimum=0)
    sample_rate = _integer(sample_rate, "sample_rate", minimum=1)
    if end_frame < start_frame:
        raise ValueError("The audio end frame must not precede its start frame.")
    return (start_frame * sample_rate // H3_FPS,
            end_frame * sample_rate // H3_FPS)


def slice_audio_frames(waveform: torch.Tensor, start_frame: int, end_frame: int,
                       sample_rate: int) -> torch.Tensor:
    """Copy one global-timeline audio slice; never accumulate rounded offsets."""

    if (not isinstance(waveform, torch.Tensor) or waveform.layout != torch.strided
            or waveform.ndim < 1 or waveform.numel() == 0 or waveform.shape[-1] < 1
            or not waveform.is_floating_point() or waveform.device.type != "cpu"
            or not bool(torch.isfinite(waveform).all())):
        raise ValueError("Provide a non-empty finite floating-point audio waveform.")
    start, end = audio_sample_bounds(start_frame, end_frame, sample_rate)
    if end > waveform.shape[-1]:
        raise ValueError("The selected audio interval extends beyond the waveform.")
    return waveform[..., start:end].clone()


def _native_nested_type():
    try:
        from comfy.nested_tensor import NestedTensor
    except ImportError as exc:
        raise RuntimeError("MiniMax H3 continuation requires ComfyUI's native NestedTensor.") from exc
    return NestedTensor


def _h3_pair(latent: object, field: str):
    NestedTensor = _native_nested_type()
    if not isinstance(latent, dict):
        raise ValueError("Connect a MiniMax H3 latent dictionary.")
    pair = latent.get(field)
    if not isinstance(pair, NestedTensor) or len(pair.tensors) != 2:
        raise ValueError("Connect a MiniMax H3 latent with separate video and audio tensors.")
    video, audio = pair.tensors
    for value, expected, dims, name in (
        (video, (1, 24), 5, "video"),
        (audio, (1, 32, 2), 4, "audio"),
    ):
        if (not isinstance(value, torch.Tensor) or value.layout != torch.strided
                or value.ndim != dims or tuple(value.shape[:len(expected)]) != expected
                or value.shape[-1] < 1 or not value.is_floating_point()
                or not bool(torch.isfinite(value).all())):
            raise ValueError(f"The H3 {name} tensor has an invalid shape or values.")
        if value.device.type != "cpu":
            raise ValueError("H3 continuation prefix helpers accept CPU tensors only.")
    if video.shape[2] < 2 or min(video.shape[3:]) < 1:
        raise ValueError("The H3 video tensor must contain at least two spatially valid tokens.")
    return pair, video, audio


def extract_video_prefix(latent: dict, valid_frames: int) -> H3VideoPrefix:
    """Copy the final two sampled video tokens at a real, lattice-aligned end."""

    token_count = h3_video_token_count(valid_frames)
    _, video, _ = _h3_pair(latent, "samples")
    if token_count > video.shape[2]:
        raise ValueError("The valid H3 endpoint exceeds the sampled latent's video tokens.")
    prefix = video[:, :, token_count - 2:token_count].detach().clone()
    return H3VideoPrefix(prefix, valid_frames, token_count)


def apply_video_prefix(latent: dict, prefix: H3VideoPrefix) -> dict:
    """Copy a sampled two-token prefix into a native pair and freeze those masks.

    The target's audio sample and noise mask, background mask values outside
    the first two video tokens, and all other latent metadata are preserved.
    Inputs are never mutated.
    """

    if not isinstance(prefix, H3VideoPrefix):
        raise ValueError("Provide a sampled H3 video prefix.")
    expected_count = h3_video_token_count(prefix.valid_frames)
    if prefix.token_count != expected_count:
        raise ValueError("The H3 prefix endpoint and token count do not agree.")
    tokens = prefix.video_tokens
    if (not isinstance(tokens, torch.Tensor) or tokens.layout != torch.strided
            or tokens.ndim != 5 or tokens.shape[0:2] != (1, 24)
            or tokens.shape[2] != 2 or min(tokens.shape[3:]) < 1
            or not tokens.is_floating_point() or not bool(torch.isfinite(tokens).all())
            or tokens.device.type != "cpu"):
        raise ValueError("The H3 prefix must contain two finite CPU video tokens.")

    _, video, audio = _h3_pair(latent, "samples")
    _, video_mask, audio_mask = _h3_pair(latent, "noise_mask")
    if tokens.shape[3:] != video.shape[3:]:
        raise ValueError("The sampled H3 prefix does not match the target latent raster.")
    if tokens.dtype != video.dtype:
        raise ValueError("The sampled H3 prefix dtype does not match the target latent.")
    if video_mask.shape != video.shape or audio_mask.shape != audio.shape:
        raise ValueError("The H3 noise masks must match their corresponding latent tensors.")
    if (not video_mask.is_floating_point() or not audio_mask.is_floating_point()
            or not bool(torch.isfinite(video_mask).all())
            or not bool(torch.isfinite(audio_mask).all())
            or bool((video_mask < 0).any()) or bool((video_mask > 1).any())
            or bool((audio_mask < 0).any()) or bool((audio_mask > 1).any())):
        raise ValueError("The H3 noise masks must contain finite floating-point values.")

    new_video = video.clone()
    new_video[:, :, :2] = tokens
    new_video_mask = video_mask.clone()
    new_video_mask[:, :, :2] = 0
    NestedTensor = _native_nested_type()
    result = dict(latent)
    result["samples"] = NestedTensor((new_video, audio))
    result["noise_mask"] = NestedTensor((new_video_mask, audio_mask))
    return result
