"""Sectioned ProRes 4444 delivery with unchanged working RGB samples."""
from pathlib import Path
from .hdr_prores import write_prores4444


def export_hlg_video(staged, output_root, prefix, *, fps, audio_source=None, audio_start_frame=0,
                     audio_start_seconds=None, audio_duration_seconds=None, ffmpeg=None, progress=None, linear_rgb=False, alpha_source=None):
    # The legacy function name is retained for old queued jobs and integrations.
    import math
    if isinstance(audio_start_frame,bool) or not isinstance(audio_start_frame,int) or audio_start_frame<0 or (audio_start_seconds is not None and (audio_start_frame!=0 or isinstance(audio_start_seconds,bool) or not isinstance(audio_start_seconds,(int,float)) or not math.isfinite(audio_start_seconds) or audio_start_seconds<0)):
        raise ValueError('Choose one valid source audio offset.')
    total=staged.plan[-1].start+staged.plan[-1].count-staged.plan[0].start
    destination=Path(output_root)/'genj'/'hdr'/(prefix+'.mov')
    start=audio_start_frame/float(fps) if audio_start_seconds is None else audio_start_seconds
    def frames():
        from .hdr_chunk_store import HDRChunkCancelled
        import numpy as np
        alphas=iter(alpha_source.frames(check_cancelled)) if alpha_source is not None else None
        for batch in staged.stitched():
            for frame in batch:
                if staged.cancelled.is_set():raise HDRChunkCancelled('HDR conversion cancelled.')
                if alphas is None:yield frame
                else:
                    try:alpha=next(alphas)
                    except StopIteration as exc:raise ValueError('The retained alpha ended before RGB.') from exc
                    yield np.concatenate([frame.detach().float().cpu().numpy(),alpha[...,None]],axis=-1)
        if alphas is not None:
            try:next(alphas)
            except StopIteration:pass
            else:raise ValueError('The retained alpha has more frames than RGB.')
    def check_cancelled():
        from .hdr_chunk_store import HDRChunkCancelled
        if staged.cancelled.is_set():raise HDRChunkCancelled('HDR conversion cancelled.')
        return False
    return write_prores4444(frames(),destination,
        width=staged.width,height=staged.height,count=total,fps=fps,
        source_space='acescg' if linear_rgb else 'acescct',audio_source=audio_source,
        audio_start=start,audio_duration=audio_duration_seconds,cancelled=check_cancelled,
        progress=progress,executable=ffmpeg,channels=4 if alpha_source is not None else 3)

export_prores_video=export_hlg_video
