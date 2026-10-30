"""Construct an internal native-HDR multi-chunk Comfy conversion job.

No Studio route is registered until real multi-chunk colour, motion, audio,
and restart/cancellation behaviour have been checked end-to-end.
"""
from __future__ import annotations

import asyncio
import copy
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from .hdr_chunks import plan_chunks
from .hdr_chunk_comfy import ComfyHDRRenderer, staging_root, validated_client_id, validate_anchor_settings
from .hdr_chunk_exr import export_exr_zip
from .hdr_chunk_runner import HDRChunkRunner
from .hdr_chunk_store import HDRChunkCancelled, HDRChunkStore
from .hdr_chunk_video import export_hlg_video
from .hdr_native_studio import build_asset_graph


def create_native_job(server, asset, body, check_asset, output_root, *, ffmpeg=None, max_chunk_frames=121, overlap=8, anchor_strength=None, anchor_mode='guide', _graph_builder=None, _image_node='trim_raster', _prefix='native'):
    """Validate a whole selection and construct a bounded sequential job."""
    from ..paintout.paintout import describe
    manifest=check_asset(asset)
    start=body.get('start_frame',0);count=body.get('frame_count')
    client_id=validated_client_id(body.get('client_id'))
    validate_anchor_settings(anchor_strength,anchor_mode)
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
    builder=_graph_builder or build_asset_graph
    first_graph,details=builder(asset,chunk_body,check_asset)
    # Validate artist-selected LoRAs before starting a potentially expensive
    # job, and apply the same validated selection to every subsequent window.
    from .custom_loras import apply_installed_ltx_loras
    selections=body.get('custom_loras',[])
    if not isinstance(selections,list):raise ValueError('Choose a list of installed LTX LoRAs.')
    selections=copy.deepcopy(selections)
    apply_installed_ltx_loras(first_graph,selections)
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
        graph,_=builder(asset,dict(body,start_frame=part.start,frame_count=part.count),check_asset)
        return apply_installed_ltx_loras(graph,selections)
    renderer=ComfyHDRRenderer(server,store,make_graph,_image_node,anchor_strength,anchor_mode,client_id)

    async def export(staged):
        paths=[]
        try:
            if output in ('acescg_exr','hlg_and_exr'):
                paths.append(await asyncio.to_thread(export_exr_zip,staged,output_root,_prefix+'_'+identity))
            if output in ('hlg_video','hlg_and_exr'):
                paths.append(await asyncio.to_thread(export_hlg_video,staged,output_root,_prefix+'_'+identity,
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


def create_sdr_job(server, asset, body, check_asset, output_root, *, ffmpeg=None, max_chunk_frames=121, overlap=8, anchor_strength=None):
    """Private SDR-to-HDR chunk prototype; no Studio route is registered."""
    if asset.get('asset_kind')!='video':raise ValueError('Choose an SDR source video.')
    from .hdr_studio import build_asset_graph as build_sdr_graph
    return create_native_job(server,asset,body,check_asset,output_root,ffmpeg=ffmpeg,
        max_chunk_frames=max_chunk_frames,overlap=overlap,anchor_strength=anchor_strength,anchor_mode='i2v',_graph_builder=build_sdr_graph,
        _image_node='hdr_unpad_raster',_prefix='sdr')
