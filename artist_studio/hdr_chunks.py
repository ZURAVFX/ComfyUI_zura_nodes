"""Frame-exact planning and linear-light blending for future HDR chunk runs.

This does not make long HDR generation available in Studio on its own. A
bounded, disk-backed executor and end-to-end render verification are required
before these helpers can be used for a user-facing export.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .hdr_source import MAX_FRAMES, MAX_PIXEL_FRAMES

MAX_TOTAL_FRAMES = 10_000


@dataclass(frozen=True)
class HDRChunk:
    start: int
    count: int
    overlap: int


def plan_chunks(start, count, width, height, overlap=8, max_frames=MAX_FRAMES):
    """Return overlapping source ranges that fit the *padded* LTX budget.

    All offsets are absolute source-frame indices. A padded 8n+1 guide must
    fit both bounds even for the final, possibly shorter chunk.
    """
    if type(start) is not int or start < 0 or type(count) is not int or not 1 <= count <= MAX_TOTAL_FRAMES:
        raise ValueError(f'Choose a non-negative start and 1–{MAX_TOTAL_FRAMES} frames.')
    if any(type(v) is not int or v < 32 or v > 2048 or v % 2 for v in (width, height)):
        raise ValueError('Use even source dimensions from 32 to 2048 pixels.')
    if type(overlap) is not int or overlap < 1:
        raise ValueError('Overlap must be a positive whole number.')
    if type(max_frames) is not int or not 9 <= max_frames <= MAX_FRAMES:
        raise ValueError('The per-chunk limit must be 9–121 frames.')
    pw=max(512, math.ceil(width / 64) * 64)
    ph=max(512, math.ceil(height / 64) * 64)
    budget=min(max_frames, MAX_PIXEL_FRAMES // (pw * ph))
    capacity=1 + 8 * ((budget - 1) // 8)
    if capacity < 9:
        raise ValueError('The padded source exceeds the per-chunk memory budget.')
    if count <= capacity:
        return [HDRChunk(start, count, 0)]
    # No frame may participate in more than two overlaps, including the last
    # chunk; using less overlap on short tails is safe and avoids a gap.
    overlap=min(overlap, (capacity - 1) // 2)
    chunks=[HDRChunk(start, capacity, 0)]
    end=start + count
    while chunks[-1].start + chunks[-1].count < end:
        next_start=chunks[-1].start + chunks[-1].count - overlap
        length=min(capacity, end - next_start)
        chunks.append(HDRChunk(next_start, length, overlap))
    return chunks


def blend_acescct_overlap(previous, following):
    """Blend equal-shape ACEScct overlap batches in linear ACEScg light.

    Inputs are model output tensors in [frames, height, width, RGB] order. No
    frame is added or removed; the caller owns placement and sequence writing.
    """
    import torch
    from ..paintout.paintout import decode_ct, encode_ct

    if not isinstance(previous, torch.Tensor) or not isinstance(following, torch.Tensor):
        raise ValueError('Expected ACEScct image tensors.')
    if previous.shape != following.shape or previous.ndim != 4 or previous.shape[-1] != 3 or not len(previous):
        raise ValueError('Overlap batches must have matching non-empty RGB shapes.')
    if previous.device != following.device or not torch.isfinite(previous).all() or not torch.isfinite(following).all():
        raise ValueError('Overlap frames must be finite and on the same device.')
    amount=torch.arange(1, len(previous)+1, device=previous.device, dtype=torch.float32)
    amount=(amount / (len(previous)+1)).reshape(-1, 1, 1, 1)
    return encode_ct(decode_ct(previous.float())*(1-amount) + decode_ct(following.float())*amount)


def choose_overlap_cut(previous, following, overlap):
    """Choose the least-discontinuous hard cut in two overlapping chunks.

    Scores adjacent output-frame luminance in a downscaled, tone-compressed
    linear view. This avoids blending different poses, but a cut may still
    expose motion or lighting jumps and therefore requires visual validation.
    """
    import torch
    import torch.nn.functional as F
    from ..paintout.paintout import decode_ct
    if (not isinstance(previous,torch.Tensor) or not isinstance(following,torch.Tensor)
            or previous.ndim!=4 or following.ndim!=4 or previous.shape[1:]!=following.shape[1:]
            or previous.shape[-1]!=3 or type(overlap) is not int or overlap<1
            or len(previous)<=overlap or len(following)<=overlap):
        raise ValueError('Two RGB chunks with unique frames are required for an overlap cut.')
    if not torch.isfinite(previous).all() or not torch.isfinite(following).all():
        raise ValueError('HDR overlap frames must be finite.')
    tail=previous[-overlap-1:];head=following[:overlap+1]
    def luminance(frames):
        linear=decode_ct(frames.float()).clamp_min(0)
        view=linear/(1+linear)
        view=(view[...,0]*.272229+view[...,1]*.674082+view[...,2]*.053689)
        return F.interpolate(view[:,None],size=(min(view.shape[1],96),min(view.shape[2],96)),mode='area')
    left=luminance(tail);right=luminance(head)
    scores=(left[:overlap+1]-right[:overlap+1]).abs().mean(dim=(1,2,3))
    return int(scores.argmin().item())


def stitch_acescct_batches(plan, batches, *, strategy='blend'):
    """Yield bounded output batches, retaining at most one chunk at a time.

    ``batches`` must supply each rendered chunk in plan order. The yielded
    batches cover the exact requested range; the executor should write each
    immediately rather than retaining the entire clip in memory. Source frame
    rate and original audio remain the caller's responsibility.
    """
    import torch
    if strategy not in ('blend','cut'):
        raise ValueError('Choose a supported HDR seam strategy.')
    if not plan:
        raise ValueError('No HDR chunks were planned.')
    iterator=iter(batches)
    pending=None
    previous=None
    for part in plan:
        try:
            batch=next(iterator)
        except StopIteration as exc:
            raise ValueError('A rendered HDR chunk is missing.') from exc
        if len(batch) != part.count:
            raise ValueError('A rendered HDR chunk has the wrong frame count.')
        if previous is None:
            if part.overlap != 0:
                raise ValueError('The first HDR chunk cannot overlap a previous chunk.')
            pending=batch
        else:
            if part.overlap < 1 or part.start != previous.start+previous.count-part.overlap:
                raise ValueError('The HDR chunk sequence has a gap or invalid overlap.')
            if part.overlap >= len(pending) or part.overlap >= len(batch):
                raise ValueError('HDR chunk overlap leaves no unique frames.')
            yield pending[:-part.overlap]
            if strategy=='cut':
                cut=choose_overlap_cut(pending,batch,part.overlap)
                yield torch.cat((pending[-part.overlap:][:cut],batch[:part.overlap][cut:]),dim=0)
            else:
                yield blend_acescct_overlap(pending[-part.overlap:],batch[:part.overlap])
            pending=batch[part.overlap:]
        previous=part
    if pending is not None:
        yield pending
    try:
        next(iterator)
    except StopIteration:
        return
    raise ValueError('Unexpected extra rendered HDR chunk.')
