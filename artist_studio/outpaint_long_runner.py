"""Cancellable, sequential outpaint windows, kept private until verified.

The caller is responsible for storing and checking the full-range approval,
validating each returned media file, and publishing the assembled result only
after validating it. No GPU graph or shared Comfy queue is modified here.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from pathlib import Path

from .outpaint_chunks import FPS, ffmpeg_assembly, windows
from .outpaint_studio import plan


def plan_long(source, *, start, duration, mode, width, height, left=0, top=0,
              right=0, bottom=0, black_threshold=2/255, overlap=12, strategy=None):
    """Bind the whole source range and canvas, not just the first window."""
    if isinstance(start, bool) or isinstance(duration, bool):
        raise ValueError('Choose a valid start and duration.')
    start, duration = float(start), float(duration)
    if not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration <= 0:
        raise ValueError('Choose a valid start and duration.')
    frames = int(duration * FPS + 1e-6)
    if frames < 3 or start + frames/FPS > float(source.get('duration', 0)) + 1e-4:
        raise ValueError('Choose a valid range within the source video.')
    parts = windows(0, frames, width=width, height=height, overlap=overlap)
    if start + parts[-1].start / FPS > 86400:
        raise ValueError('This selection extends beyond the supported 24-hour source start limit. Trim the clip.')
    args = dict(mode=mode, width=width, height=height, left=left, top=top,
                right=right, bottom=bottom, black_threshold=black_threshold)
    # Reuse the production validator for every subrange and exact canvas.
    subplans = [plan(source, start=start + part.start/FPS,
                     duration=part.count/FPS, **args) for part in parts]
    if strategy is not None and (strategy != 'anchored_masked' or mode != 'expand' or overlap != 9):
        raise ValueError('The anchored long workflow requires canvas expansion and a nine-frame overlap.')
    values = {'source_sha': str(source['sha']), 'start': start, 'frames': frames, 'overlap': overlap, **args}
    if strategy is not None:
        values['strategy'] = strategy
    digest = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {**values, 'duration': frames/FPS, 'review_key': digest}, parts, subplans


async def run_windows(*, kind, source, selection, parts, subplans, submit, wait,
                      cancel, update, ffmpeg, output, source_audio=None, anchor=False):
    """Run bounded graphs one at a time; assemble only after every succeeds.

    ``submit`` receives (kind, source, subplan) and returns a job ID; ``wait``
    returns the validated local path for that job. Cancellation interrupts only
    the current child job and the executor's own FFmpeg process.
    """
    if kind not in ('review', 'render') or len(parts) != len(subplans) or not parts:
        raise ValueError('Invalid outpaint window execution.')
    identity = None
    process = None
    paths = []
    try:
        for index, subplan in enumerate(subplans):
            update('running', index, len(parts))
            # A cancellation at the submission boundary must not abandon a
            # prompt which has just entered Comfy's queue. Let submission
            # finish, capture its identity, then interrupt precisely that job.
            # The selected frame must represent the same source timestamp as
            # the next window's frame 0, even when several frames overlap.
            previous = (paths[-1], parts[index - 1].count - parts[index].overlap) if anchor and kind == 'render' and paths else None
            submission = asyncio.create_task(submit(kind, source, subplan, previous))
            try:
                identity = await asyncio.shield(submission)
            except asyncio.CancelledError:
                try:
                    identity = await submission
                except Exception:
                    pass  # A failed submission has no queued prompt to stop.
                raise
            paths.append(Path(await wait(identity)))
            identity = None
        update('assembling', len(parts), len(parts))
        command = ffmpeg_assembly(ffmpeg, parts, paths, output,
            source=source_audio if kind == 'render' else None,
            audio_start=selection['start'])
        process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE)
        _, stderr = await process.communicate()
        if process.returncode:
            raise RuntimeError('Could not assemble the outpaint windows: ' + stderr.decode(errors='replace')[-1000:])
        return Path(output)
    except asyncio.CancelledError:
        if identity is not None:
            await cancel(identity)
        if process is not None and process.returncode is None:
            process.terminate()
            await process.wait()
        raise
