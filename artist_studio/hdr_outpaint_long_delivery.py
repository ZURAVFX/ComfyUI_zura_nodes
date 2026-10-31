"""Private streaming delivery for a long HDR frame-extension job."""
import asyncio
from pathlib import Path

from .hdr_chunks import HDRChunk
from .hdr_chunk_store import HDRChunkCancelled


class HeldHDRStage:
    """Append the final composed frame to an 8n+1 delivery length."""
    def __init__(self, staged):
        if not staged.plan:
            raise ValueError('No HDR sections are available for delivery.')
        self.staged = staged
        self.width, self.height, self.cancelled = staged.width, staged.height, staged.cancelled
        self.original = staged.plan[-1].start + staged.plan[-1].count - staged.plan[0].start
        if self.original < 1:
            raise ValueError('Invalid HDR delivery length.')
        self.total = self.original + (1-self.original) % 8
        self.plan = [HDRChunk(0, self.total, 0)]

    def stitched(self):
        seen = 0
        last = None
        for batch in self.staged.stitched():
            if self.cancelled.is_set(): raise HDRChunkCancelled('HDR conversion cancelled.')
            if len(batch):
                seen += len(batch)
                last = batch[-1:].clone()
                yield batch
        if seen != self.original or last is None:
            raise ValueError('The stitched HDR sections have the wrong frame count.')
        if self.total > self.original:
            if self.cancelled.is_set(): raise HDRChunkCancelled('HDR conversion cancelled.')
            yield last.expand(self.total-self.original, *last.shape[1:])


async def export_long_hdr_outpaint(staged, output_root, prefix, *, source_path, has_audio,
                                   start_seconds, source_duration=None, ffmpeg=None):
    """Export HLG, ACEScg EXR and an SDR preview; publish only on success."""
    from .hdr_chunk_exr import export_exr_zip
    from .hdr_chunk_video import export_hlg_video
    from .hdr_chunk_preview import export_sdr_preview
    if type(has_audio) is not bool:
        raise ValueError('Audio selection must be explicit.')
    held = HeldHDRStage(staged)
    if source_duration is None: source_duration = held.original / 24.0
    paths = []
    async def publish(function, *args, **kwargs):
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        try:
            path = await asyncio.shield(task)
        except asyncio.CancelledError:
            staged.cancelled.set()
            try:
                path = await task
            except Exception:
                pass
            else:
                paths.append(path)
            raise
        paths.append(path)
    try:
        await publish(export_exr_zip, held, output_root, prefix)
        await publish(export_hlg_video, held, output_root, prefix,
            fps=24., audio_source=source_path if has_audio else None,
            audio_start_seconds=start_seconds, audio_duration_seconds=source_duration, ffmpeg=ffmpeg)
        await publish(export_sdr_preview, held, output_root, prefix,
            fps=24., audio_source=source_path if has_audio else None,
            audio_start_seconds=start_seconds, audio_duration_seconds=source_duration, ffmpeg=ffmpeg)
        if staged.cancelled.is_set(): raise HDRChunkCancelled('HDR conversion cancelled.')
        return {'files':[str(paths[0]),str(paths[1])], 'preview':str(paths[2]), 'frames':held.total, 'fps':24.}
    except BaseException:
        # Each exporter exclusively creates its result; remove only paths this
        # call successfully published, never a pre-existing file.
        for path in paths:
            Path(path).unlink(missing_ok=True)
        raise
