"""Frame planning for chunked Wan 2.2 Animate rendering.

Independent of ComfyUI so frame accounting and cut handling can be tested
without loading a model.
"""
from __future__ import annotations

from typing import NamedTuple


class ShotChunk(NamedTuple):
    """One sampling window of the chunked render.

    ``output_*`` is the slice of the finished clip this chunk is responsible
    for.  ``window_*`` is the span it actually samples: for a continuation
    chunk that window begins ``anchor_frames`` earlier, on the predecessor's
    real output tail.  Those frames are handed to the native node as
    ``continue_motion`` so the model continues from real pixels rather than
    re-inventing them, and its own rendition of those frames is the
    ``blend_frames`` head of the window, cross-faded against the predecessor's
    real pixels so the join has no step at either edge.
    """

    index: int
    shot_index: int
    output_start: int
    output_count: int
    continuation: bool
    # Frames of the predecessor's output used as continue_motion (0 for the
    # first chunk of a shot: continuation never crosses a cut).
    anchor_frames: int
    # Head of the window cross-faded with the predecessor's tail.  A chunk with
    # an in-shot successor leaves it to be both the successor's anchor and its
    # blend zone, so the two passes meet on identical pixels.
    blend_frames: int
    window_start: int = 0
    window_count: int = 0


def _validate(chunk_frames: int, overlap_frames: int):
    if chunk_frames < 5 or (chunk_frames - 1) % 4:
        raise ValueError("chunk_frames must be 4n+1 and at least 5")
    if overlap_frames < 1 or (overlap_frames - 1) % 4 or overlap_frames > chunk_frames - 4:
        raise ValueError("overlap_frames must be 4n+1 and leave at least four generated frames")
    # A continuation chunk samples its own output plus the anchor at the front
    # and hands its tail to the successor, so the window must be able to hold
    # both: a chunk generates chunk_frames - overlap frames, which has to be at
    # least the overlap it both receives and passes on.
    if overlap_frames * 2 > chunk_frames:
        raise ValueError("overlap_frames must be at most half of chunk_frames")


def parse_cut_frames(value: str | None, total_frames: int) -> list[int]:
    cuts = []
    for item in str(value or "").replace(";", ",").split(","):
        if not item.strip():
            continue
        try:
            cut = int(item.strip())
        except ValueError as exc:
            raise ValueError(f"cut_frames contains a non-integer value: {item.strip()!r}") from exc
        if not 0 < cut < total_frames:
            raise ValueError(f"cut frame {cut} must be between 1 and {total_frames - 1}")
        cuts.append(cut)
    return sorted(set(cuts))


def detect_cuts(frames, threshold: float = .2, downsample: int = 32) -> list[int]:
    """Adaptive structural cuts with flash rejection; manual cuts remain exact."""
    from .cut_detection import detect_cuts as find_cuts
    return find_cuts(frames, threshold, downsample)


def plan_chunks(total_frames: int, chunk_frames: int = 41, overlap_frames: int = 5,
                cuts: list[int] | None = None, continuation: bool = True) -> list[ShotChunk]:
    """Split the clip into per-shot sampling windows.

    ``cuts`` separate shots.  A window never spans a cut and continuation never
    reaches back past the start of its own shot, so every new shot begins with
    unconditioned frames: at a cut the join is a hard cut, exactly as the
    source has it.  Inside a shot, every chunk after the first samples a window
    that starts on the predecessor's real tail frames and passes them on as
    native ``continue_motion``.
    """
    total_frames = int(total_frames)
    if total_frames < 1:
        raise ValueError("total_frames must be positive")
    _validate(int(chunk_frames), int(overlap_frames))
    cuts = sorted(set(int(c) for c in (cuts or [])))
    invalid = [c for c in cuts if not 0 < c < total_frames]
    if invalid:
        raise ValueError(f"cut frames must be between 1 and {total_frames - 1}: {invalid}")
    bounds = [0] + cuts + [total_frames]
    result, index = [], 0
    for shot, (lo, hi) in enumerate(zip(bounds, bounds[1:])):
        start = lo
        first = True
        while start < hi:
            # Continuation only ever reaches back inside this shot, so the
            # window start is clamped to the shot and the anchor shrinks with
            # it; in practice it is always exactly ``overlap_frames``.
            anchor = 0 if (first or not continuation) else min(overlap_frames, start - lo)
            count = min(chunk_frames - anchor, hi - start)
            window_start = start - anchor
            window_count = min(chunk_frames, hi - window_start)
            # Any chunk with an in-shot successor leaves its tail behind: it is
            # the successor's continuation anchor and its cross-fade zone.
            blend = overlap_frames if (continuation and start + count < hi) else 0
            result.append(ShotChunk(index, shot, start, count, bool(anchor), anchor, blend,
                                    window_start, window_count))
            index += 1
            start += count
            first = False
    return result


def hold_last(value, count: int):
    import torch
    if value is None:
        return None
    if value.shape[0] >= count:
        return value[:count]
    if value.shape[0] == 0:
        raise ValueError("input contains no frames")
    return torch.cat((value, value[-1:].repeat((count - value.shape[0],) + (1,) * (value.ndim - 1))), dim=0)


def sampling_frames(part: ShotChunk) -> int:
    """Pad the sampled window to Wan's next 4n+1 boundary (minimum 5).

    For a full continuation chunk the window is already ``chunk_frames``
    frames, i.e. 4n+1, so the continuation anchor costs no extra sampling at
    all; only a truncated tail window needs padding.
    """
    return max(5, ((int(part.window_count) - 1 + 3) // 4) * 4 + 1)


def validate_plan(plan: list[ShotChunk], total_frames: int) -> None:
    """Assert that chunk output is contiguous, complete, and source-safe."""
    if not plan:
        raise ValueError("chunk plan is empty")
    expected = 0
    for part in plan:
        if part.output_start != expected:
            raise ValueError(f"chunk output has a gap/overlap at frame {expected}")
        if part.output_count < 1:
            raise ValueError(f"chunk {part.index} has an invalid frame count")
        if part.window_start != part.output_start - part.anchor_frames:
            raise ValueError(f"chunk {part.index} anchor does not line up with its window")
        if part.window_count < part.output_count:
            raise ValueError(f"chunk {part.index} window is smaller than its output")
        if part.anchor_frames != (part.window_count - part.output_count if part.continuation else 0):
            raise ValueError(f"chunk {part.index} has an inconsistent continuation anchor")
        if part.window_start < 0 or part.window_start + part.window_count > total_frames:
            raise ValueError(f"chunk {part.index} reads outside the source frames")
        expected += part.output_count
    if expected != total_frames:
        raise ValueError(f"chunk plan outputs {expected} frames for a {total_frames}-frame source")
