"""Construct an internal native-HDR multi-chunk Comfy conversion job.

No Studio route is registered until real multi-chunk colour, motion, audio,
and restart/cancellation behaviour have been checked end-to-end.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from .hdr_chunks import plan_chunks
from .hdr_chunk_comfy import ComfyHDRRenderer, staging_root
from .hdr_chunk_exr import export_exr_zip
from .hdr_chunk_runner import HDRChunkRunner
from .hdr_chunk_store import HDRChunkCancelled, HDRChunkStore
from .hdr_chunk_video import export_hlg_video
from .hdr_native_studio import build_asset_graph


def create_native_job(server, asset, body, check_asset, output_root, *, ffmpeg=None, max_chunk_frames=121, overlap=8, anchor_strength=None, anchor_mode='guide'):
    """Validate a whole selection and construct a bounded sequential job."""
    from ..paintout.paintout import describe
    manifest=check_asset(asset)
    start=body.get('start_frame',0);count=body.get('frame_count')
    if type(start) is not int or start<0 or type(count) is not int or count<1:
        raise ValueError('Choose a valid HDR source range.')
    sequence=asset.get('asset_kind')=='hdr_sequence'
    if sequence:
        from .hdr_sequence import validate_manifest
        source,_=validate_manifest(manifest,asset['sha'],start,count)
    elif asset.get('asset_kind')=='video':source=manifest
    else:raise ValueError('Choose HDR video or an EXR sequence.')
    info=describe(str(source))
    if start+count>info['count']:raise ValueError('The selected range extends past the source.')
    plan=plan_chunks(start,count,info['width'],info['height'],overlap=overlap,max_frames=max_chunk_frames)
    chunk_body=dict(body,start_frame=plan[0].start,frame_count=plan[0].count)
    _,details=build_asset_graph(asset,chunk_body,check_asset)
    output=details['output']
    # Fail before running the expensive GPU graph if the final outputs cannot
    # be encoded or safely published. The staged float32 size is predictable;
    # leave room for one EXR copy and the compressed deliverable as well.
    from .hdr_package import preflight_archive
    preflight_archive(output_root)
    staging=staging_root()
    staging.mkdir(parents=True,exist_ok=True)
    staged_bytes=sum(part.count for part in plan)*details['width']*details['height']*12
    output_dir=Path(output_root)/'genj'/'hdr'
    # Conservative estimate for an uncompressed half-float EXR sequence,
    # encoded video and one temporary frame. Actual codec sizes can vary.
    output_bytes=count*details['width']*details['height']*(8 if output!='hlg_video' else 2)
    reserve=64*1024*1024
    same_device=os.stat(staging).st_dev==os.stat(output_dir).st_dev
    if shutil.disk_usage(staging).free < staged_bytes + (output_bytes if same_device else 0) + reserve:
        raise ValueError('Not enough free temporary disk space for the HDR chunks.')
    if not same_device and shutil.disk_usage(output_dir).free < output_bytes+reserve:
        raise ValueError('Not enough free output disk space for the HDR deliverables.')
    if output in ('hlg_video','hlg_and_exr'):
        executable=ffmpeg or shutil.which('ffmpeg')
        if not executable:raise ValueError('FFmpeg is required to export HDR video.')
        try:
            result=subprocess.run([str(executable),'-hide_banner','-encoders'],capture_output=True,text=True,timeout=30)
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise ValueError('FFmpeg could not be checked before HDR rendering.') from exc
        if result.returncode or 'libx265' not in result.stdout:
            raise ValueError('FFmpeg needs a 10-bit HEVC encoder for HDR video.')
        ffmpeg=str(executable)
    identity=uuid.uuid4().hex
    store=HDRChunkStore(staging,identity,plan,details['width'],details['height'],create=True)

    def make_graph(part):
        graph,_=build_asset_graph(asset,dict(body,start_frame=part.start,frame_count=part.count),check_asset)
        return graph
    renderer=ComfyHDRRenderer(server,store,make_graph,'trim_raster',anchor_strength,anchor_mode)

    async def export(staged):
        paths=[]
        try:
            if output in ('acescg_exr','hlg_and_exr'):
                paths.append(await asyncio.to_thread(export_exr_zip,staged,output_root,'native_'+identity))
            if output in ('hlg_video','hlg_and_exr'):
                paths.append(await asyncio.to_thread(export_hlg_video,staged,output_root,'native_'+identity,
                    fps=details['fps'],audio_source=str(source) if details['has_audio'] else None,
                    audio_start_frame=start,ffmpeg=ffmpeg))
            if staged.cancelled.is_set():raise HDRChunkCancelled('HDR conversion cancelled.')
            return {'files':[str(path) for path in paths],'frames':count,'fps':details['fps']}
        except Exception:
            # Both paths were created exclusively by this call. Never touch a
            # pre-existing deliverable if a subsequent export fails.
            for path in paths:Path(path).unlink(missing_ok=True)
            raise

    job=HDRChunkRunner(store,renderer.submit,export,renderer.cancel)
    return job,{'id':identity,'chunks':len(plan),'frames':count,'fps':details['fps'],
                'width':details['width'],'height':details['height'],'output':output}
