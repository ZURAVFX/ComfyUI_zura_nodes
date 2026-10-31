"""Private bounded HDR conversion for an assembled frame-extension guide."""
import asyncio
import os
from pathlib import Path
import shutil
import uuid

from .hdr_chunk_comfy import ComfyHDRRenderer, staging_root, validated_client_id
from .hdr_chunk_runner import HDRChunkRunner
from .hdr_chunk_store import HDRChunkStore
from .hdr_outpaint_long_delivery import export_long_hdr_outpaint
from .hdr_outpaint_long_plan import plan_hdr_windows, long_plan_values, build_long_hdr_conversion_window


def create_long_hdr_conversion(server, source, selection, intermediate, *, review_key,
                               output_root, check_asset, client_id=None, ffmpeg=None):
    """Prepare one cancellable HDR conversion of a reviewed SDR intermediate.

    The input must be an owned, verified file under the Comfy output root.
    The caller owns the input and removes it after the returned job completes.
    This is an internal prototype and is not registered as a Studio route.
    """
    import av
    from .enhancement import inspect_video
    from .hdr_package import preflight_archive
    values=long_plan_values(selection)
    expected, parts, subplans = plan_hdr_windows(source, duration=selection['requested_duration'],
                                                  **values)
    if selection.get('review_key') != expected['review_key'] or review_key != expected['review_key']:
        raise ValueError('The full HDR selection changed. Review it again.')
    if len(parts) < 2:
        raise ValueError('Use the single-section HDR workflow for this range.')
    client_id = validated_client_id(client_id)
    root = Path(output_root).resolve()
    candidate = Path(intermediate)
    if candidate.is_symlink():
        raise ValueError('The HDR intermediate is unavailable.')
    path = candidate.resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() != '.mp4':
        raise ValueError('The HDR intermediate is unavailable.')
    total = expected['frames'] + (1-expected['frames']) % 8
    inspect_video(path, expected_frames=total, expected_width=expected['width'],
                  expected_height=expected['height'], expected_fps=24, expected_audio_tracks=0)
    native = Path(check_asset(source))
    with av.open(str(native)) as media:
        has_audio = bool(media.streams.audio)
    executable = ffmpeg or shutil.which('ffmpeg')
    if not executable:
        raise ValueError('FFmpeg is required for HDR output.')
    preflight_archive(root)
    staging = staging_root(); staging.mkdir(parents=True, exist_ok=True)
    destination = root/'genj'/'hdr'; destination.mkdir(parents=True, exist_ok=True)
    staged_bytes = sum(part.count for part in parts) * expected['width'] * expected['height'] * 12
    output_bytes = total * expected['width'] * expected['height'] * 10
    reserve = 512 * 1024**2
    if os.stat(staging).st_dev == os.stat(destination).st_dev:
        if shutil.disk_usage(staging).free < staged_bytes + output_bytes + reserve:
            raise ValueError('Not enough free disk space for HDR staging and delivery.')
    elif (shutil.disk_usage(staging).free < staged_bytes + reserve or
          shutil.disk_usage(destination).free < output_bytes + reserve):
        raise ValueError('Not enough free disk space for HDR staging and delivery.')
    identity=uuid.uuid4().hex
    store=HDRChunkStore(staging, identity, parts, expected['width'], expected['height'], create=True)
    by_start={part.start:sub for part,sub in zip(parts,subplans)}
    def build(part):
        return build_long_hdr_conversion_window(source, expected, by_start[part.start], str(path),
            review_key=review_key, prompt_start_frame=part.start, seed=42,
            prefix='hdr_outpaint_'+identity, check_asset=check_asset)
    renderer=ComfyHDRRenderer(server, store, build, 'final_hdr_composite',
                              anchor_strength=.75, anchor_mode='i2v', client_id=client_id)
    async def export(staged):
        # Recheck the asset before extracting its original soundtrack.
        checked = await asyncio.to_thread(check_asset, source)
        return await export_long_hdr_outpaint(staged, root, 'hdr_outpaint_'+identity,
            source_path=str(checked), has_audio=has_audio, start_seconds=expected['start'],
            source_duration=expected['requested_duration'], ffmpeg=executable)
    job=HDRChunkRunner(store, renderer.submit, export, renderer.cancel)
    return job, {'id':identity, 'frames':total, 'sections':len(parts), 'fps':24,
                 'width':expected['width'], 'height':expected['height'], 'has_audio':has_audio}
