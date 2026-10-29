"""Stream staged HDR chunks to an atomic ACEScg EXR ZIP deliverable."""
from __future__ import annotations

import re
import shutil
import uuid
import zipfile
from pathlib import Path

from .hdr_chunk_store import HDRChunkCancelled
from .model_downloads import _publish_verified


def export_exr_zip(staged, output_root, prefix, *, half_precision=True, progress=None):
    """Publish only a complete ZIP; source audio belongs to a video export.

    Frames are converted from LTX's ACEScct encoding to linear ACEScg and
    written one at a time. Cancellation or an error removes only this run's
    private temporary directory and never touches previous deliverables.
    """
    import numpy as np
    from ..paintout.paintout import decode_ct, save_exr

    if not isinstance(prefix,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',prefix):
        raise ValueError('Invalid HDR output name.')
    parent=(Path(output_root)/'genj'/'hdr').resolve()
    parent.mkdir(parents=True,exist_ok=True)
    temporary=parent/('.zura-hdr-'+uuid.uuid4().hex)
    temporary.mkdir(exist_ok=False)
    destination=parent/(prefix+'.zip')
    archive=temporary/'output.zip'
    expected=staged.plan[-1].start+staged.plan[-1].count-staged.plan[0].start
    try:
        if destination.exists(): raise ValueError('An HDR deliverable with this name already exists.')
        total=0
        with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_STORED,allowZip64=True) as out:
            for batch in staged.stitched():
                for frame in batch:
                    if staged.cancelled.is_set(): raise HDRChunkCancelled('HDR conversion cancelled.')
                    name=f'frame_{total:05d}.exr'
                    path=temporary/name
                    linear=decode_ct(frame.float()).clamp(0,1e4).cpu().numpy()
                    save_exr(path,np.ascontiguousarray(linear),'acescg',half_precision)
                    out.write(path,arcname=name)
                    path.unlink()
                    total+=1
                    if progress:progress(total,expected)
        if total!=expected:raise ValueError('The HDR output did not contain the requested number of frames.')
        if staged.cancelled.is_set():raise HDRChunkCancelled('HDR conversion cancelled.')
        _publish_verified(archive,destination)
        return destination
    finally:
        # Only the newly created UUID staging directory may be removed.
        if temporary.parent==parent and temporary.name.startswith('.zura-hdr-'):
            shutil.rmtree(temporary,ignore_errors=True)
