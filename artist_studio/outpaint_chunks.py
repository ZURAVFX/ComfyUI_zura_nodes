"""Bounded outpaint window planning and frame-exact SDR assembly.

These helpers do not enable longer jobs by themselves. A complete executor
must bind review to the whole range, render and validate each window, support
cancellation, and verify temporal quality before exposing long clips.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

FPS = 24
WINDOW_FRAMES = 120
MAX_PIXEL_FRAMES = 40_000_000
MAX_WINDOWS = 3600


@dataclass(frozen=True)
class Window:
    start: int
    count: int
    overlap: int


def windows(start, count, *, width=None, height=None, overlap=12):
    """Plan overlapping 24 fps windows, using absolute source frame offsets."""
    if any(type(x) is not int for x in (start, count, overlap)):
        raise ValueError('Frame positions and overlap must be whole numbers.')
    if start < 0 or count < 3 or not 1 <= overlap <= (WINDOW_FRAMES - 1) // 2:
        raise ValueError('Choose a valid frame range and overlap.')
    capacity = WINDOW_FRAMES
    if width is not None or height is not None:
        if any(type(n) is not int or n <= 0 for n in (width, height)):
            raise ValueError('Choose valid output dimensions.')
        padded_width, padded_height = math.ceil(width / 64) * 64, math.ceil(height / 64) * 64
        budget = min(121, MAX_PIXEL_FRAMES // (padded_width * padded_height))
        capacity = min(WINDOW_FRAMES, 1 + 8 * ((budget - 1) // 8))
        if capacity < 9:
            raise ValueError('This resolution exceeds the outpaint window memory budget.')
        overlap = min(overlap, (capacity - 1) // 2)
    end = start + count
    number = 1 + max(0, math.ceil((count - capacity) / (capacity - overlap)))
    if number > MAX_WINDOWS:
        raise ValueError(f'This selection requires more than {MAX_WINDOWS} processing windows. Trim the clip or use a smaller output resolution.')
    parts = [Window(start, min(count, capacity), 0)]
    while parts[-1].start + parts[-1].count < end:
        next_start = parts[-1].start + parts[-1].count - overlap
        parts.append(Window(next_start, min(capacity, end - next_start), overlap))
    return parts


def disk_requirements(width, height, parts, *, anchor=False):
    """Conservative scratch estimates for chunk files, assembly and anchors."""
    if any(type(n) is not int or n <= 0 for n in (width, height)) or not parts:
        raise ValueError('Choose valid output dimensions and windows.')
    # Two raw RGB equivalents cover encoded child files and the assembled
    # file even for poorly compressible footage, plus reserved working space.
    rgb = width * height * 3
    output = 2 * rgb * sum(part.count for part in parts) + 512 * 1024**2
    anchors = (rgb * max(0, len(parts) - 1) if anchor else 0) + 256 * 1024**2
    return output, anchors


def ffmpeg_assembly(ffmpeg, parts, rendered, output, *, source=None, audio_start=0):
    """Construct a non-shell FFmpeg command to overlap/blend SDR windows.

    Each input must already be verified to contain exactly its window's frame
    count, dimensions and frame rate. The original source audio is attached
    once, not copied from each generation window. Caller owns subprocess
    cancellation, output verification and cleanup of partial files.
    """
    if not parts or len(parts) != len(rendered) or parts[0].overlap:
        raise ValueError('Choose matching rendered windows.')
    for i, part in enumerate(parts):
        if part.count < 3 or part.count > WINDOW_FRAMES or part.start < 0:
            raise ValueError('Invalid outpaint window.')
        if i and (part.overlap < 1 or part.overlap >= part.count or
                  part.start != parts[i-1].start + parts[i-1].count - part.overlap):
            raise ValueError('Outpaint windows must overlap without gaps.')
        next_overlap = parts[i+1].overlap if i + 1 < len(parts) else 0
        if part.overlap + next_overlap >= part.count:
            raise ValueError('Outpaint overlaps cannot cross.')
    if (not isinstance(audio_start, (int, float)) or isinstance(audio_start, bool)
            or not math.isfinite(audio_start) or audio_start < 0):
        raise ValueError('Invalid source-audio start.')
    command = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y']
    for file in rendered:
        command += ['-i', str(file)]
    if source is not None:
        command += ['-i', str(source)]
    filters, segments = [], []
    # A standalone one-frame filter segment has zero duration in FFmpeg's
    # concat filter and may be dropped. With a single shared frame, keep the
    # previous window's last frame and skip the next window's duplicate; each
    # concat segment then contains a normal multi-frame span.
    single_overlap = len(parts) > 1 and all(part.overlap == 1 for part in parts[1:])
    if single_overlap:
        for i, part in enumerate(parts):
            before = part.overlap
            filters.append(f'[{i}:v]trim=start_frame={before}:end_frame={part.count},setpts=PTS-STARTPTS[body{i}]')
            segments.append(f'[body{i}]')
    else:
        if any(part.overlap == 1 for part in parts[1:]):
            raise ValueError('Do not mix single-frame and blended overlaps.')
    for i, part in enumerate(parts if not single_overlap else []):
        before = part.overlap
        after = parts[i+1].overlap if i + 1 < len(parts) else 0
        branches = 1 + (before > 0) + (after > 0)
        outputs = ''.join(f'[v{i}_{j}]' for j in range(branches))
        filters.append(f'[{i}:v]setpts=PTS-STARTPTS,split={branches}{outputs}' if branches > 1 else
                       f'[{i}:v]setpts=PTS-STARTPTS[v{i}_0]')
        branch = 0
        if before:
            filters.append(f'[v{i}_{branch}]trim=start_frame=0:end_frame={before},setpts=PTS-STARTPTS[head{i}]')
            branch += 1
        filters.append(f'[v{i}_{branch}]trim=start_frame={before}:end_frame={part.count-after},setpts=PTS-STARTPTS[body{i}]')
        branch += 1
        if after:
            filters.append(f'[v{i}_{branch}]trim=start_frame={part.count-after}:end_frame={part.count},setpts=PTS-STARTPTS[tail{i}]')
        if before:
            denom = max(1, before - 1)
            # FFmpeg blend's N starts at one. Clamp to [0, 1] so the first
            # and last overlap frames are the respective input endpoints,
            # without extrapolating and wrapping pixel values.
            weight = f'clip((N-1)/{denom}\\,0\\,1)'
            filters.append(f'[tail{i-1}][head{i}]blend=all_expr=\'A*(1-{weight})+B*{weight}\':shortest=1[blend{i}]')
            segments.append(f'[blend{i}]')
        if part.count - before - after:
            segments.append(f'[body{i}]')
    filters.append(''.join(segments) + f'concat=n={len(segments)}:v=1:a=0[outv]')
    total = parts[-1].start + parts[-1].count - parts[0].start
    command += ['-filter_complex', ';'.join(filters), '-map', '[outv]']
    if source is not None:
        command += ['-map', f'{len(parts)}:a:0?', '-af', f'atrim=start={float(audio_start):.9f}:duration={total/FPS:.9f},asetpts=PTS-STARTPTS', '-c:a', 'aac']
    command += ['-frames:v', str(total), '-r', str(FPS), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart', str(Path(output))]
    return command
