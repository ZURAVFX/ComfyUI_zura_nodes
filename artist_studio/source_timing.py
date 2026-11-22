"""Keep original source cadence when a video-to-video recipe supports it."""
from fractions import Fraction
import math
from pathlib import Path
from uuid import uuid4

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
        count = stream.frames or sum(1 for _ in container.decode(stream))
    if rate <= 0 or rate > 240:
        raise ValueError('The original video has no supported frame rate.')
    duration = min(requested, available - start)
    if not math.isfinite(duration) or duration <= 0 or start < 0:
        raise ValueError('Choose a valid source interval.')
    full = start == 0 and abs(duration - available) < 1e-6
    frames = int(count) if full and count else max(1, math.ceil(duration * rate - 1e-6))
    return dict(frames=frames, fps=float(rate), fps_num=rate.numerator, fps_den=rate.denominator,
                duration=float(Fraction(frames, 1) / rate), selected_duration=duration, full_source=full)


def reload_review(directory, details, render_long_edge, output_scale, preserve_aspect, preview_seconds, ffmpeg, model_fps=0):
    """Reread RGB from the original, never upsample the 24 fps review proxy."""
    source = Path(details['source'])
    if preview_seconds:
        details = dict(details, selected_duration=min(float(preview_seconds),
                       float(details.get('selected_duration', details['duration']))))
    timing = timeline(source, details)
    details = dict(details, **timing)
    rate = Fraction(timing['fps_num'], timing['fps_den'])
    if model_fps:
        start_frame = round(Fraction(str(details['start'])) * rate)
        details['start'] = float(start_frame / rate)
        details['model_fps'] = model_fps
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
    if model_fps:
        cache = cache.with_name(cache.name + f'_start{start_frame}_model{model_fps}')
    cache.mkdir(exist_ok=True)
    high_source = cache / 'source.mp4'
    if model_fps:
        # Reinterpret each captured frame on the model clock. The fps filter
        # would resample the timeline and delete or repeat source frames.
        if not high_source.exists():
            pending = high_source.with_name(f'.source-{uuid4().hex}.mp4')
            try:
                ffmpeg('-i', source, '-map', '0:v:0', '-an',
                       '-vf', f'trim=start_frame={start_frame}:end_frame={start_frame + timing["frames"]},'
                              f'settb=1/{model_fps},setpts=N,scale={w}:{h}:flags=lanczos',
                       '-fps_mode', 'cfr', '-r', model_fps, '-enc_time_base', f'1/{model_fps}',
                       '-c:v', 'libx264', '-crf', 16, '-pix_fmt', 'yuv420p', pending)
                verify_frame_clock(pending, timing['frames'], Fraction(model_fps), w, h)
                pending.replace(high_source)
            finally:
                pending.unlink(missing_ok=True)
        # Wan consumes only the source VIDEO and clip details; retain the
        # approved review paths for the unused mask and guide outputs.
        details.update(width=w, height=h, export_width=target_w, export_height=target_h,
                       render_long_edge=render_long_edge, selected_path=str(high_source))
        mask = Path(directory) / 'mask.mp4'
        performer = Path(directory) / 'performer_mask.mp4'
        return high_source, mask, Path(directory) / 'guide.mp4', details, performer if performer.exists() else mask
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


def verify_frame_clock(path, count, rate, width, height):
    with av.open(str(path)) as media:
        stream = media.streams.video[0]
        if (stream.width, stream.height, stream.average_rate) != (width, height, rate):
            raise ValueError(f'Expected {width} × {height} at {rate} fps in the delivered video.')
        index = -1
        for index, frame in enumerate(media.decode(stream)):
            if frame.pts is None or frame.pts * frame.time_base != Fraction(index, 1) / rate:
                raise ValueError(f'Frame {index} does not match the required video clock.')
        if index + 1 != count:
            raise ValueError(f'Expected {count} video frames but decoded {index + 1}.')


def save_relight_frames(video, details, destination, width, height):
    import cv2
    from comfy.model_management import throw_exception_if_processing_interrupted
    from .hdr_prores import write_prores4444

    frames = video.get_components().images
    count = details['frames']
    rate = Fraction(details['fps_num'], details['fps_den'])
    if len(frames) < count:
        raise ValueError(f'The model produced {len(frames)} of {count} source frames. Re-render the shot.')
    source = details['source']
    with av.open(str(source)) as media:
        has_audio = bool(media.streams.audio)
    width = width or frames.shape[2]
    height = height or frames.shape[1]

    def restored_frames():
        for frame in frames[:count]:
            throw_exception_if_processing_interrupted()
            rgb = frame[..., :3].detach().float().cpu().numpy()
            if rgb.shape[:2] != (height, width):
                rgb = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_LANCZOS4)
            yield rgb

    write_prores4444(restored_frames(), destination, width=width, height=height,
                     count=count, fps=rate, source_space='srgb_display',
                     audio_source=source if has_audio else None, audio_start=details['start'],
                     audio_duration=float(count / rate))
    try:
        verify_frame_clock(destination, count, rate, width, height)
    except BaseException:
        destination.unlink(missing_ok=True)
        destination.with_suffix('.mov.json').unlink(missing_ok=True)
        raise
