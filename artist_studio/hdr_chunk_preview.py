"""Stream a tone-mapped SDR review copy of a staged HDR conversion."""
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


def export_sdr_preview(staged, output_root, prefix, *, fps, audio_source=None,
                       audio_start_frame=0, audio_start_seconds=None, audio_duration_seconds=None, ffmpeg=None, progress=None):
    from ..paintout.paintout import decode_ct, _encode_original
    if not isinstance(prefix,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',prefix):
        raise ValueError('Invalid HDR preview name.')
    if isinstance(fps,bool) or not isinstance(fps,(int,float)) or not math.isfinite(fps) or not 1<=fps<=120:
        raise ValueError('Choose a valid HDR frame rate.')
    if staged.width%2 or staged.height%2 or type(audio_start_frame) is not int or audio_start_frame<0:
        raise ValueError('Invalid HDR preview dimensions or audio offset.')
    if audio_start_seconds is not None and (isinstance(audio_start_seconds, bool) or
            not isinstance(audio_start_seconds, (int,float)) or not math.isfinite(audio_start_seconds) or
            audio_start_seconds < 0 or audio_start_frame != 0):
        raise ValueError('Choose one valid source audio offset.')
    audio_offset=audio_start_frame/float(fps) if audio_start_seconds is None else float(audio_start_seconds)
    executable=ffmpeg or shutil.which('ffmpeg')
    if not executable:raise ValueError('FFmpeg is required to make the HDR preview.')
    total=staged.plan[-1].start+staged.plan[-1].count-staged.plan[0].start
    duration=total/float(fps)
    if audio_duration_seconds is not None and (isinstance(audio_duration_seconds, bool) or
            not isinstance(audio_duration_seconds, (int, float)) or not math.isfinite(audio_duration_seconds) or
            not 0 < audio_duration_seconds <= duration + 1e-6):
        raise ValueError('Choose a valid source audio duration.')
    audio_duration = duration if audio_duration_seconds is None else float(audio_duration_seconds)
    parent=(Path(output_root)/'genj'/'hdr').resolve();parent.mkdir(parents=True,exist_ok=True)
    temporary=parent/('.zura-preview-'+uuid.uuid4().hex);temporary.mkdir(exist_ok=False)
    output=temporary/'preview.mp4';destination=parent/(prefix+'_preview.mp4')
    process=None
    try:
        if destination.exists():raise ValueError('An HDR preview with this name already exists.')
        command=[str(executable),'-hide_banner','-loglevel','error','-f','rawvideo','-pixel_format','rgb24',
                 '-video_size',f'{staged.width}x{staged.height}','-framerate',str(float(fps)),'-i','pipe:0']
        if audio_source is not None:
            command+=['-ss',str(audio_offset),'-i',str(audio_source),'-map','0:v:0','-map','1:a:0',
                      '-af',f'atrim=duration={audio_duration:.9f},apad=whole_dur={duration:.9f},atrim=duration={duration:.9f}','-c:a','aac','-ar','48000']
        else:command+=['-map','0:v:0','-an']
        command+=['-frames:v',str(total),'-t',str(duration),'-c:v','libx264','-pix_fmt','yuv420p',
                  '-movflags','+faststart','-f','mp4',str(output)]
        with (temporary/'ffmpeg.log').open('wb') as log:
            process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log)
            written=0
            try:
                for batch in staged.stitched():
                    for frame in batch:
                        if staged.cancelled.is_set():raise HDRChunkCancelled('HDR conversion cancelled.')
                        linear=decode_ct(frame.float()).clamp_min(0)
                        # Match the LTX node's neutral, zero-exposure preview.
                        preview=_encode_original(linear/(1+linear),'srgb_display').clamp(0,1)
                        packed=(preview.cpu().numpy()*255).round().astype('u1',copy=False)
                        process.stdin.write(np.ascontiguousarray(packed).tobytes());written+=1
                        if progress:progress(written,total)
                if written!=total:raise ValueError('The HDR preview has the wrong frame count.')
                process.stdin.close();process.stdin=None
                if process.wait(timeout=120)!=0:raise RuntimeError('FFmpeg could not encode the HDR preview.')
            finally:
                if process.poll() is None:process.kill();process.wait()
                if process.stdin is not None:
                    try:process.stdin.close()
                    except OSError:pass
        if staged.cancelled.is_set():raise HDRChunkCancelled('HDR conversion cancelled.')
        _publish_verified(output,destination)
        return destination
    finally:
        if temporary.parent==parent and temporary.name.startswith('.zura-preview-'):
            shutil.rmtree(temporary,ignore_errors=True)
