"""Inspect an exact Studio movie master before native After Effects return."""
from fractions import Fraction
from pathlib import Path
import hashlib
import json
import os
import secrets


def prepare_video_delivery(path, output_root, *, precision, width, height, frame_count, frame_rate):
    """Write an AE-timed ProRes 4444 MOV master; retain the model's original file."""
    import av
    from . import float_io

    path, output_root = Path(path), Path(output_root).absolute()
    if precision not in {'sdr8', 'prores12'}:
        raise ValueError('Unsupported native movie delivery precision')
    if not path.absolute().is_relative_to(output_root):
        raise ValueError('Movie master is outside the selected ComfyUI output folder')
    rate = Fraction(frame_rate['numerator'], frame_rate['denominator'])
    wanted = 'prores4444'
    try:
        info = inspect_video_master(path, width=width, height=height, frame_count=frame_count, frame_rate=frame_rate)
        if info['codec'] == wanted:
            return path
    except ValueError:
        pass
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    key = hashlib.sha256(json.dumps([source_hash, 'prores4444-v3-clock', precision, width, height, frame_count, frame_rate], sort_keys=True).encode()).hexdigest()
    folder = output_root / 'ComfyLink' / 'native-return' / key
    current = output_root
    for part in ('ComfyLink', 'native-return', key):
        with float_io._locked_parents(current):
            current = current / part
            current.mkdir(exist_ok=True)
    master = folder / 'master.mov'
    if master.exists():
        inspect_video_master(master, width=width, height=height, frame_count=frame_count, frame_rate=frame_rate)
        return master
    temporary = folder / (secrets.token_hex(16) + master.suffix)
    count = 0
    try:
        import shutil, subprocess
        executable=shutil.which('ffmpeg')
        if not executable:raise ValueError('FFmpeg is required for ProRes 4444 return')
        duration=frame_count/float(rate)
        from .studio_rate import tempo_filter
        with av.open(str(path)) as source_movie:
            source_rate=source_movie.streams.video[0].average_rate
        if not source_rate:raise ValueError('The generated movie frame rate is unavailable')
        audio_clock=tempo_filter(rate/source_rate)+',' if rate!=source_rate else ''
        command=[executable,'-v','error','-r',f'{rate.numerator}/{rate.denominator}','-i',str(path),
                 '-map','0:v:0','-map','0:a?','-frames:v',str(frame_count),'-t',str(duration),
                 '-c:v','prores_ks','-profile:v','4','-pix_fmt','yuv444p10le','-tag:v','ap4h',
                 '-c:a','pcm_s24le','-af',audio_clock+f'atrim=duration={duration:.9f},apad=whole_dur={duration:.9f},atrim=duration={duration:.9f}',
                 '-video_track_timescale',str(rate.numerator),'-movflags','+faststart+write_colr','-f','mov',str(temporary)]
        result=subprocess.run(command,capture_output=True,timeout=600)
        if result.returncode:raise ValueError('Could not prepare the ProRes 4444 movie for AE')
        inspect_video_master(temporary, width=width, height=height, frame_count=frame_count, frame_rate=frame_rate)
        if hashlib.sha256(path.read_bytes()).hexdigest() != source_hash:
            raise ValueError('Selected movie changed during delivery')
        with float_io._locked_parents(folder):
            os.replace(temporary, master)
        (folder / 'delivery.json').write_text(json.dumps({'sourceSha256':source_hash, 'precision':precision,
            'frameRate':frame_rate, 'frameCount':frame_count, 'modelPrecisionUnchanged':True}), encoding='utf8')
        return master
    finally:
        temporary.unlink(missing_ok=True)


def inspect_video_master(path, *, width, height, frame_count, frame_rate):
    import av

    path = Path(path)
    if path.suffix.lower() not in {'.mp4', '.mov'}:
        raise ValueError('Native return needs an MP4 or MOV master')
    expected_rate = Fraction(frame_rate['numerator'], frame_rate['denominator'])
    with av.open(str(path)) as movie:
        if len(movie.streams.video) != 1 or any(s.type not in {'video', 'audio'} for s in movie.streams):
            raise ValueError('Native return needs exactly one video track')
        video = movie.streams.video[0]
        codec = video.codec_context
        if video.average_rate != expected_rate or (video.width, video.height) != (width, height):
            raise ValueError('Native return clock or raster differs from the AE source')
        # These are the only opaque, directly importable contracts qualified for
        # this candidate. A ten-bit H.264 file keeps its actual precision label.
        if codec.name == 'h264' and path.suffix.lower() == '.mp4':
            formats = {'yuv420p': 8, 'yuv420p10le': 10}
            kind = 'h264'
        elif codec.name == 'prores' and path.suffix.lower() == '.mov' and codec.codec_tag in {'ap4h', 'ap4x'}:
            formats = {'yuv444p12le': 12}
            kind = 'prores4444'
        else:
            raise ValueError('Native return codec is unsupported')
        first, count, actual_format = None, 0, None
        for frame in movie.decode(video=0):
            if count >= frame_count or frame.format.name not in formats:
                raise ValueError('Native return has extra frames or unsupported precision/alpha')
            if (frame.width, frame.height) != (width, height):
                raise ValueError('Native return raster changes between frames')
            if type(frame.pts) is not int or frame.time_base is None:
                raise ValueError('Native return frame timestamp is unavailable')
            instant = frame.pts * frame.time_base
            if first is None:
                first = instant
            if instant != first + Fraction(count, 1) / expected_rate:
                raise ValueError('Native return cadence differs from the AE source')
            if actual_format is not None and actual_format != frame.format.name:
                raise ValueError('Native return precision changes between frames')
            actual_format = frame.format.name
            count += 1
        if count != frame_count:
            raise ValueError('Native return has missing frames')
        return {'codec': kind, 'pixelFormat': actual_format, 'bitDepth': formats[actual_format],
                'width': width, 'height': height, 'frameCount': count, 'frameRate': frame_rate,
                'hasAlpha': False}
