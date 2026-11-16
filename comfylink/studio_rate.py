"""Reinterpret an owned AE movie at a model clock without resampling frames."""
from fractions import Fraction
from pathlib import Path
import subprocess
import shutil


def tempo_filter(speed):
    speed=float(speed);filters=[]
    while speed < .5:filters.append('atempo=0.5');speed/=.5
    while speed > 2:filters.append('atempo=2');speed/=2
    filters.append(f'atempo={speed:.12g}')
    return ','.join(filters)


def reinterpret_movie(source, destination, source_rate, model_rate, frame_count):
    import av
    source, destination=Path(source),Path(destination)
    original=Fraction(source_rate['numerator'],source_rate['denominator']);working=Fraction(model_rate)
    if not 1<=original<=240 or not 1<=working<=240 or not 1<=frame_count<=10000:
        raise ValueError('Choose a supported source and model frame rate.')
    def count(path):
        with av.open(str(path)) as movie:
            if len(movie.streams.video)!=1:raise ValueError('The source needs one video track.')
            return sum(1 for packet in movie.demux(video=0) if packet.size)
    if count(source)!=frame_count:
        raise ValueError('The working movie must contain every frame of the selected AE range.')
    executable=shutil.which('ffmpeg')
    if not executable:raise ValueError('FFmpeg is needed to prepare the model frame rate.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_name(destination.stem+'.partial.mkv')
    duration=float(Fraction(frame_count)/working)
    command=[executable,'-v','error','-y','-itsscale',f'{float(original/working):.15g}','-i',str(source),
        '-i',str(source),'-map','0:v:0','-map','1:a?','-c:v','copy','-r',str(working),'-fps_mode','passthrough',
        '-c:a','pcm_s24le','-af',tempo_filter(working/original)+f',apad,atrim=duration={duration:.12f}',
        '-t',f'{duration:.12f}',str(temporary)]
    try:
        result=subprocess.run(command,capture_output=True,timeout=300)
        if result.returncode or count(temporary)!=frame_count:
            raise ValueError('Could not reinterpret every source frame at the model frame rate.')
        temporary.replace(destination)
        return destination
    finally:temporary.unlink(missing_ok=True)
