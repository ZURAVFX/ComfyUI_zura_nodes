"""Adaptive hard-cut detection for decoded Zura frames.

The detector scores both raw change and brightness-normalised structure.  A
short flash produces a pair of large changes but quickly returns to its local
baseline, so those peaks are discarded before scene-gap suppression.
"""
from __future__ import annotations


def detect_cuts(frames, threshold: float = .2, downsample: int = 32) -> list[int]:
    import torch

    if frames is None or int(frames.shape[0]) < 2:
        return []
    x = frames.float()
    if x.ndim != 4:
        raise ValueError("frames must have shape [frames,height,width,channels]")
    if int(x.shape[-1]) < 1:
        raise ValueError("frames must have at least one channel")
    x = torch.nn.functional.interpolate(
        x.permute(0, 3, 1, 2), size=(int(downsample), int(downsample)), mode="area"
    ).permute(0, 2, 3, 1)
    if float(x.max()) > 1.5:
        x = x / 255.0
    x = x.clamp(0, 1)

    # Per-frame centring removes exposure/flicker changes from the structural
    # signal while the raw signal still catches a genuine black/white edit.
    mean = x.mean(dim=(1, 2, 3), keepdim=True)
    std = x.std(dim=(1, 2, 3), keepdim=True).clamp_min(1e-3)
    normal = (x - mean) / std
    raw = (x[1:] - x[:-1]).abs().mean(dim=(1, 2, 3))
    structural = (normal[1:] - normal[:-1]).abs().mean(dim=(1, 2, 3)).clamp_max(2) / 2
    score = .45 * raw + .55 * structural

    # A robust clip-level floor adapts to pans and handheld motion without imposing
    # a hard limit on the number of real edits in a long source clip.
    values = score.detach().cpu()
    median = float(values.median())
    mad = float((values - median).abs().median())
    floor = max(float(threshold), median + 4.0 * max(mad, 1e-3))
    candidates = []
    for transition, value in enumerate(values.tolist(), start=1):
        if value < floor:
            continue
        lo, hi = max(0, transition - 3), min(len(values), transition + 2)
        if value < float(values[lo:hi].max()):
            continue
        # Reject one/two-frame flashes when the signal returns to the frame
        # before the change.  Check both sides to catch the exit peak too.
        returned = False
        for back in (1, 2, 3):
            if transition - back < 0:
                continue
            for ahead in (1, 2):
                if transition + ahead >= x.shape[0]:
                    continue
                distance = (normal[transition + ahead] - normal[transition - back]).abs().mean()
                raw_distance = (x[transition + ahead] - x[transition - back]).abs().mean()
                # Permit exposure to differ: a strobe can be much brighter on
                # return while its normalised structure is unchanged.  Flat
                # synthetic scenes have no structure, so retain their clear
                # black/white edit signal.
                structure = normal[transition - back].std()
                if float(distance) < .30 and (float(raw_distance) < .10 or float(structure) > .03):
                    returned = True
                    break
            if returned:
                break
        if not returned:
            candidates.append((transition, value))

    # Keep the strongest local peak when edits are close together.  Twelve
    # frames is short enough for normal editorial cuts and avoids duplicate
    # peaks around a single transition.
    selected: list[tuple[int, float]] = []
    for transition, value in sorted(candidates, key=lambda item: item[1], reverse=True):
        if all(abs(transition - kept) >= 12 for kept, _ in selected):
            selected.append((transition, value))
    return sorted(transition for transition, _ in selected)
