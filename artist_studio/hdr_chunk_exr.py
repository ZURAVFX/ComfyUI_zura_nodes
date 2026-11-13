"""Stream staged HDR chunks to an atomic ACEScg EXR ZIP deliverable."""
from __future__ import annotations

import re
import hashlib
import json
import shutil
import uuid
import zipfile
from pathlib import Path

from .hdr_chunk_store import HDRChunkCancelled
from .model_downloads import _publish_verified


def export_rgba_exr_zip(staged,output_root,prefix,*,alpha_source,frame_rate,progress=None,linear_rgb=False):
    """Run colour conversion on RGB only; copy the pinned FLOAT alpha exactly."""
    import numpy as np
    import OpenImageIO as oiio
    from fractions import Fraction
    from ..paintout.paintout import decode_ct
    from .hdr_alpha import PROOF_NAME,alpha_hash
    if not isinstance(prefix,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',prefix):raise ValueError('Invalid HDR output name.')
    expected=staged.plan[-1].start+staged.plan[-1].count-staged.plan[0].start
    rate=Fraction(frame_rate)
    if (alpha_source.width,alpha_source.height,alpha_source.count,alpha_source.rate)!=(staged.width,staged.height,expected,rate):raise ValueError('HDR RGB and alpha must have identical dimensions, frame count and clock.')
    parent=(Path(output_root)/'genj'/'hdr').resolve();parent.mkdir(parents=True,exist_ok=True)
    temporary=parent/('.zura-hdr-'+uuid.uuid4().hex);temporary.mkdir(exist_ok=False)
    destination=parent/(prefix+'.zip');archive=temporary/'output.zip'
    proof={'schemaVersion':1,'kind':'rgba_hdr','colour':{'encoding':'acescg','sceneLinear':True},'alphaAssociation':'straight',
        'width':staged.width,'height':staged.height,'frameCount':expected,'frameRate':{'numerator':rate.numerator,'denominator':rate.denominator},
        'alphaSource':alpha_source.proof(),'frames':[]}
    if alpha_source.source_start is not None:proof['sourceStart']=alpha_source.source_start
    def check():
        if staged.cancelled.is_set():raise HDRChunkCancelled('HDR conversion cancelled.')
    try:
        if destination.exists():raise ValueError('An HDR deliverable with this name already exists.')
        alphas=iter(alpha_source.frames(check));total=0
        with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_STORED,allowZip64=True) as out:
            for batch in staged.stitched():
                for frame in batch:
                    check()
                    try:alpha=next(alphas)
                    except StopIteration as exc:raise ValueError('The retained alpha ended before the HDR RGB.') from exc
                    rgb=(frame.float() if linear_rgb else decode_ct(frame.float())).cpu().numpy()
                    rgba=np.ascontiguousarray(np.concatenate([rgb,alpha[...,None]],axis=-1),dtype=np.float32)
                    if not np.isfinite(rgba).all():raise ValueError('The HDR RGBA output contains non-finite samples.')
                    name=f'frame_{total:05d}.exr';path=temporary/name
                    spec=oiio.ImageSpec(staged.width,staged.height,4,oiio.FLOAT);spec.channelnames=['R','G','B','A'];spec.alpha_channel=3
                    spec.attribute('compression','zip');spec.attribute('oiio:UnassociatedAlpha',1);spec.attribute('oiio:ColorSpace','ACEScg')
                    spec.attribute('comfylink:alphaAssociation','straight')
                    spec.attribute('chromaticities',oiio.TypeDesc('float[8]'),(.713,.293,.165,.830,.128,.044,.32168,.33767))
                    spec.attribute('comfylink:colour',json.dumps(proof['colour'],sort_keys=True,separators=(',',':')))
                    writer=oiio.ImageOutput.create(str(path))
                    if writer is None or not writer.open(str(path),spec):raise ValueError('The HDR RGBA EXR could not be opened.')
                    try:
                        if not writer.write_image(rgba):raise ValueError('The HDR RGBA EXR could not be written.')
                    finally:writer.close()
                    check();digest=hashlib.sha256()
                    with path.open('rb') as stream:
                        for block in iter(lambda:stream.read(4*1024*1024),b''):digest.update(block)
                    proof['frames'].append({'filename':name,'sha256':digest.hexdigest(),'alphaSha256':alpha_hash(alpha)})
                    out.write(path,arcname=name);path.unlink();total+=1
                    if progress:progress(total,expected)
            try:next(alphas)
            except StopIteration:pass
            else:raise ValueError('The retained alpha has more frames than the HDR RGB.')
            if total!=expected:raise ValueError('The HDR RGBA output has the wrong frame count.')
            check();alpha_source.verify();out.writestr(PROOF_NAME,json.dumps(proof,sort_keys=True,separators=(',',':')))
        check();alpha_source.verify();_publish_verified(archive,destination);return destination
    finally:
        if temporary.parent==parent and temporary.name.startswith('.zura-hdr-'):shutil.rmtree(temporary,ignore_errors=True)


def export_exr_zip(staged, output_root, prefix, *, half_precision=True, progress=None, linear_rgb=False):
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
                    # Negative linear AP1 components are valid wide-gamut
                    # values, including the toe of ACEScct. Preserve them in
                    # the scene-linear EXR instead of clipping the gamut.
                    linear=frame.float() if linear_rgb else decode_ct(frame.float())
                    # Retain the legacy half path exactly; FLOAT is explicit and
                    # must reject invalid samples rather than clipping transport.
                    if half_precision and not linear_rgb:
                        linear=linear.clamp(max=1e4)
                    elif half_precision and bool((linear.abs()>65504).any()):
                        raise ValueError('The HDR master exceeds HALF range. Choose FLOAT32 EXR storage.')
                    if not linear.isfinite().all():
                        raise ValueError('The EXR output contains non-finite samples.')
                    linear=linear.cpu().numpy()
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
