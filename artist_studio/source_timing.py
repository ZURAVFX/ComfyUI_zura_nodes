"""Keep original source cadence when a video-to-video recipe supports it."""
from fractions import Fraction
import math
from pathlib import Path

import av


def timeline(source, details):
    start = float(details.get('start', 0))
    requested = float(details.get('selected_duration', details['duration']))
    if not all(math.isfinite(value) for value in (start, requested)) or start < 0 or requested <= 0:
        raise ValueError('Choose a valid source interval.')
    with av.open(str(source)) as container:
        stream = container.streams.video[0]
        rate = Fraction(stream.average_rate or stream.base_rate or 0)
        available = (float(stream.duration * stream.time_base) if stream.duration is not None
                     else float((container.duration or 0) / av.time_base))
        count = stream.frames
    if rate <= 0 or rate > 240:
        raise ValueError('The original video has no supported frame rate.')
    duration = min(requested, available - start)
    if not math.isfinite(duration) or duration <= 0 or start < 0:
        raise ValueError('Choose a valid source interval.')
    full = start == 0 and abs(duration - available) < 1e-6
    frames = int(count) if full and count else max(1, math.ceil(duration * rate - 1e-6))
    return dict(frames=frames, fps=float(rate), fps_num=rate.numerator, fps_den=rate.denominator,
                duration=float(Fraction(frames, 1) / rate), selected_duration=duration, full_source=full)


def reload_review(directory, details, render_long_edge, output_scale, preserve_aspect, preview_seconds, ffmpeg):
    """Reread RGB from the original, never upsample the 24 fps review proxy."""
    source = Path(details['source'])
    if preview_seconds:
        details = dict(details, selected_duration=min(float(preview_seconds),
                       float(details.get('selected_duration', details['duration']))))
    timing = timeline(source, details)
    details = dict(details, **timing)
    rate = Fraction(timing['fps_num'], timing['fps_den'])
    with av.open(str(source)) as container:
        stream = container.streams.video[0]
        sw, sh = stream.width, stream.height
    if output_scale not in (1, 2) or not 256 <= render_long_edge <= 4096:
        raise ValueError('Choose a valid source render size and scale.')
    scale = render_long_edge / max(sw, sh)
    grid = 2 if preserve_aspect else 64
    w, h = (max(grid, round(side * scale / output_scale / grid) * grid) for side in (sw, sh))
    target_w, target_h = (max(2, round(side * scale / 2) * 2) for side in (sw, sh))
    cache = Path(directory) / (f"source_timing_v1_{render_long_edge}_x{output_scale}_{timing['frames']}f_"
                               f"{rate.numerator}_{rate.denominator}_{grid}")
    cache.mkdir(exist_ok=True)
    high_source = cache / 'source.mp4'
    if not high_source.exists():
        ffmpeg('-ss', details['start'], '-i', source, '-i', Path(directory) / 'source.mp4',
               '-map', '0:v:0', '-map', '1:a:0?', '-t', timing['duration'],
               '-vf', f'setpts=PTS-STARTPTS,fps={rate},scale={w}:{h}:flags=lanczos,tpad=stop_mode=clone:stop=1',
               '-frames:v', timing['frames'], '-c:v', 'libx264', '-crf', 16, '-pix_fmt', 'yuv420p',
               '-c:a', 'aac', '-b:a', '256k', high_source)
    with av.open(str(high_source)) as container:
        stream = container.streams.video[0]
        count = sum(1 for _ in container.decode(video=0))
        if count != timing['frames'] or stream.average_rate != rate:
            raise ValueError('The source reload does not match the original frame rate and selected frame count.')
    # Keep all returned VIDEO wires on the same timeline, even when this recipe
    # only consumes source_clip. The reviewed masks remain authoritative.
    paths = []
    for name in ('mask.mp4', 'guide.mp4', 'performer_mask.mp4'):
        original = Path(directory) / name
        if not original.exists():
            original = Path(directory) / 'mask.mp4'
        target = cache / name
        if not target.exists():
            ffmpeg('-i', original, '-map', '0:v:0', '-map', '0:a:0?', '-t', timing['duration'],
                   '-vf', f'fps={rate},tpad=stop_mode=clone:stop=2', '-frames:v', timing['frames'],
                   '-c:v', 'libx264', '-crf', 0 if 'mask' in name else 16,
                   '-pix_fmt', 'yuv420p', '-c:a', 'aac', target)
        paths.append(target)
    details.update(width=w, height=h, export_width=target_w, export_height=target_h,
                   render_long_edge=render_long_edge, selected_path=str(high_source))
    return high_source, paths[0], paths[1], details, paths[2]
