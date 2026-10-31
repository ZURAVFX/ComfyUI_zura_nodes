"""Screened gradient-domain colour continuation for native HDR plates.

Operate in ACEScct so exposure/chroma offsets remain well behaved around
highlights. The original plate is a fixed boundary; generated detail supplies
the gradients outside it. A screened harmonic field removes the box-shaped
colour transition without an arbitrary outer falloff edge.
"""
from functools import lru_cache

import numpy as np
import torch

_DIRECT_LIMIT = 250_000


@lru_cache(maxsize=1)
def _system(height, width, selected_bytes, radius):
    from scipy.sparse import coo_matrix
    from scipy.sparse.linalg import splu, cg, LinearOperator

    selected = np.frombuffer(selected_bytes, dtype=np.bool_).reshape(height, width)
    y, x = np.nonzero(selected)
    ids = np.full((height, width), -1, dtype=np.int32)
    ids[y, x] = np.arange(len(y), dtype=np.int32)
    diagonal = np.full(len(y), 1.0 / radius**2, dtype=np.float64)
    rows, columns, values, boundaries = [], [], [], []
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        ny, nx = y + dy, x + dx
        valid = (ny >= 0) & (ny < height) & (nx >= 0) & (nx < width)
        row = np.flatnonzero(valid)
        ny, nx = ny[valid], nx[valid]
        diagonal[row] += 1
        neighbour = ids[ny, nx]
        unknown = neighbour >= 0
        rows.append(row[unknown]); columns.append(neighbour[unknown])
        values.append(-np.ones(int(unknown.sum())))
        boundaries.append((row[~unknown], ny[~unknown], nx[~unknown]))
    rows.append(np.arange(len(y))); columns.append(np.arange(len(y))); values.append(diagonal)
    matrix = coo_matrix((np.concatenate(values), (np.concatenate(rows), np.concatenate(columns))),
                        shape=(len(y), len(y))).tocsc()
    # Cache only the most recent mask. Moving masks cannot accumulate factors.
    if len(y) <= _DIRECT_LIMIT:
        solve = splu(matrix).solve
    else:
        # Large canvases use bounded sparse iteration instead of retaining a
        # potentially multi-GB factorisation. Never silently publish a failed
        # or partially converged correction.
        matrix = matrix.tocsr()
        inverse_diagonal = 1. / diagonal
        preconditioner = LinearOperator(matrix.shape, matvec=lambda v: inverse_diagonal * v)
        def solve(rhs):
            channels = []
            for channel in rhs.T:
                value, status = cg(matrix, channel, M=preconditioner, rtol=1e-6,
                                   atol=1e-9, maxiter=2000)
                if status != 0:
                    raise ValueError('HDR boundary correction did not converge.')
                channels.append(value)
            return np.stack(channels, axis=-1)
    return solve, y, x, boundaries


def refine_hdr_boundary(composited, source, mask, feather=16, strength=1.0, *, inplace=False):
    """Keep the native plate exact and smoothly continue its edge correction.

    Call after the ordinary linear-light composite. This final stage can also
    be evaluated on retained composite EXRs without rerunning diffusion.
    No temporal averaging crosses cuts or borrows reference pixels from a
    different frame. Only a single RGB frame and sparse boundary field are
    solved at a time.
    """
    if not strength or not feather:
        return composited
    result = composited if inplace else torch.empty_like(composited)
    radius = float(max(32, feather * 8))
    try:
        for index in range(len(composited)):
            # Only these single-frame CPU buffers are resident, regardless of
            # clip length or tensor precision/device. The production caller
            # owns a fresh composite and can reuse that output buffer in place.
            frame = composited[index].detach().float().cpu().numpy().copy()
            plate = source[index].detach().float().cpu().numpy()
            area = mask[index].detach().float().cpu().numpy().clip(0, 1)
            # A soft artist mask retains its ordinary linear-light composite.
            # Harmonic constraints require an unambiguous reviewed binary plate.
            if np.any((area > 0) & (area < 1)):
                if not inplace: result[index].copy_(composited[index])
                continue
            selected = np.ascontiguousarray(area >= .5)
            if selected.all():
                if not inplace: result[index].copy_(composited[index])
                continue
            if not selected.any():
                frame = plate if strength == 1.0 else frame + (plate-frame) * strength
            else:
                solve, y, x, boundaries = _system(*selected.shape, selected.tobytes(), radius)
                difference = plate - frame
                rhs = np.zeros((len(y), 3), dtype=np.float64)
                for row, by, bx in boundaries:
                    rhs[row] += difference[by, bx]
                correction = solve(rhs).astype(np.float32)
                frame[y, x] += correction * strength
                if strength == 1.0:
                    frame[~selected] = plate[~selected]
                else:
                    frame[~selected] += difference[~selected] * strength
            if not np.isfinite(frame).all():
                raise ValueError('HDR boundary correction produced non-finite pixels.')
            result[index].copy_(torch.from_numpy(frame).to(device=result.device, dtype=result.dtype))
    finally:
        # Reuse within a batch, but release factors between generation stages.
        _system.cache_clear()
    return result
