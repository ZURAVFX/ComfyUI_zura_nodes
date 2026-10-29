"""Bounded streaming HLG delivery for internally staged LTX HDR chunks."""
from __future__ import annotations

import math
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import numpy as np

from .hdr_chunk_store import HDRChunkCancelled
from .model_downloads import _publish_verified


def export_hlg_video(staged, output_root, prefix, *, fps, audio_source=None, audio_start_frame=0,
                     ffmpeg=None, progress=None):
    """Encode 10-bit Rec.2020 HLG and restore one source soundtrack.

    LTX ACEScct is transformed using Comfy's same ImageColorSpace operation as
    the official graph. Frames are sent to FFmpeg one at a time; only a
    completed, uncancelled file is published. Callers must validate the audio
    source against the original Studio asset before invoking this function.
    """
    from ..paintout.paintout import native_colour

    if not isinstance(prefix,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',prefix):
        raise ValueError('Invalid HDR output name.')
    if isinstance(fps,bool) or not isinstance(fps,(int,float)) or not math.isfinite(fps) or not 1<=fps<=120:
        raise ValueError('Choose a valid HDR frame rate.')
    if staged.width%2 or staged.height%2:
        raise ValueError('HLG video requires even source dimensions.')
    if type(audio_start_frame) is not int or audio_start_frame<0:
        raise ValueError('Invalid source audio offset.')
    executable=ffmpeg or shutil.which('ffmpeg')
    if not executable:raise ValueError('FFmpeg is required to export HDR video.')
    total=staged.plan[-1].start+staged.plan[-1].count-staged.plan[0].start
    duration=total/float(fps)
    parent=(Path(output_root)/'genj'/'hdr').resolve();parent.mkdir(parents=True,exist_ok=True)
    temporary=parent/('.zura-hlg-'+uuid.uuid4().hex);temporary.mkdir(exist_ok=False)
    output=temporary/'video.mp4';destination=parent/(prefix+'.mp4')
    process=None
    try:
        if destination.exists():raise ValueError('An HDR video with this name already exists.')
        command=[str(executable),'-hide_banner','-loglevel','error','-f','rawvideo','-pixel_format','rgb48le',
            '-video_size',f'{staged.width}x{staged.height}','-framerate',str(float(fps)),'-i','pipe:0']
        if audio_source is not None:
            command+=['-ss',str(audio_start_frame/float(fps)),'-i',str(audio_source),
                '-map','0:v:0','-map','1:a:0','-af',f'apad=whole_dur={duration:.9f},atrim=duration={duration:.9f}',
                '-c:a','aac','-ar','48000']
        else:command+=['-map','0:v:0','-an']
        command+=['-frames:v',str(total),'-t',str(duration),'-vf',
            'scale=in_range=full:out_range=tv:out_color_matrix=bt2020',
            '-c:v','libx265','-x265-params','log-level=error:pools=1:frame-threads=1:colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc',
            '-pix_fmt','yuv420p10le','-color_range','tv','-colorspace','bt2020nc',
            '-color_primaries','bt2020','-color_trc','arib-std-b67','-tag:v','hvc1','-f','mp4',str(output)]
        with (temporary/'ffmpeg.log').open('wb') as log:
            process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log)
            written=0
            try:
                for batch in staged.stitched():
                    for frame in batch:
                        if staged.cancelled.is_set():raise HDRChunkCancelled('HDR conversion cancelled.')
                        hlg=native_colour(frame[None].float(),'HDR ACEScct','HDR')[0].clamp(0,1)
                        packed=(hlg.cpu().numpy()*65535.0).round().astype('<u2',copy=False)
                        process.stdin.write(np.ascontiguousarray(packed).tobytes())
                        written+=1
                        if progress:progress(written,total)
                if written!=total:raise ValueError('The HDR output has the wrong frame count.')
                process.stdin.close();process.stdin=None
                if process.wait(timeout=120)!=0:raise RuntimeError('FFmpeg could not encode the HDR video.')
            finally:
                if process.poll() is None:
                    process.kill();process.wait()
                if process.stdin is not None:
                    try:process.stdin.close()
                    except OSError:pass
        if staged.cancelled.is_set():raise HDRChunkCancelled('HDR conversion cancelled.')
        _publish_verified(output,destination)
        return destination
    finally:
        if temporary.parent==parent and temporary.name.startswith('.zura-hlg-'):
            shutil.rmtree(temporary,ignore_errors=True)
