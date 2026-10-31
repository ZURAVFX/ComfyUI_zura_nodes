"""Artist-controlled EXR layers for an already-completed HDR frame extension.

The source is the delivered, *composited* master, not retained raw model
output. Its reviewed generated area and an inward overlap are exported as a
straight-alpha border, alongside the original native HDR plate and a matte.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from contextlib import closing
from fractions import Fraction
from pathlib import Path

import numpy as np
import torch

from .hdr_chunk_store import HDRChunkCancelled
from .model_downloads import _publish_verified

_PREFIX = re.compile(r'[A-Za-z0-9_-]{1,100}\Z')
_AP1 = (.713, .293, .165, .830, .128, .044, .32168, .33767)
_FEATHER = 16


def _checked_selection(selection):
    if not isinstance(selection, dict):
        raise ValueError('The reviewed frame-extension selection is unavailable.')
    integers = ('width', 'height', 'frames', 'left', 'top', 'right', 'bottom')
    if any(type(selection.get(k)) is not int for k in integers):
        raise ValueError('The reviewed frame-extension geometry is invalid.')
    width, height, frames = (selection[k] for k in ('width', 'height', 'frames'))
    if not 1 <= frames <= 10000 or not 1 <= width <= 4096 or not 1 <= height <= 4096:
        raise ValueError('The reviewed frame-extension dimensions or frame count are invalid.')
    if any(selection[k] < 0 for k in ('left', 'top', 'right', 'bottom')):
        raise ValueError('Frame-extension margins must be non-negative.')
    start, threshold = selection.get('start'), selection.get('black_threshold', 2 / 255)
    if (isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(start) or start < 0 or
        isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0 <= threshold <= .1):
        raise ValueError('The reviewed frame-extension timing or threshold is invalid.')
    if selection.get('mode') not in ('expand', 'black') or selection.get('colour_space') not in ('auto','hlg_rec2020','pq_rec2020','pq_display_p3'):
        raise ValueError('The reviewed HDR source or frame-extension mode is invalid.')
    if selection['mode'] == 'black' and any(selection[k] for k in ('left','top','right','bottom')):
        raise ValueError('Black-area footage does not use canvas margins.')
    if width-selection['left']-selection['right'] <= 0 or height-selection['top']-selection['bottom'] <= 0:
        raise ValueError('The reviewed frame-extension margins are invalid.')
    return width, height, frames


def _cancelled(event):
    if event is not None and event.is_set():
        raise HDRChunkCancelled('Stopped preparing the HDR compositing layers.')


def _write_rgba(path, rgb, alpha):
    import OpenImageIO as oiio
    height, width = alpha.shape
    rgba = np.concatenate((rgb, alpha[..., None]), axis=-1).astype(np.float32, copy=False)
    if rgba.shape != (height, width, 4) or not np.isfinite(rgba).all():
        raise ValueError('A compositing layer contains invalid pixels.')
    spec = oiio.ImageSpec(width, height, 4, oiio.FLOAT)
    spec.channelnames = ('R', 'G', 'B', 'A')
    spec.alpha_channel = 3
    spec.attribute('oiio:ColorSpace', 'ACEScg')
    spec.attribute('oiio:UnassociatedAlpha', 1)
    spec.attribute('chromaticities', oiio.TypeDesc('float[8]'), _AP1)
    spec.attribute('compression', 'zip')
    output = oiio.ImageOutput.create(str(path))
    if output is None or not output.open(str(path), spec):
        raise ValueError('Could not create the HDR compositing layer.')
    try:
        if not output.write_image(np.ascontiguousarray(rgba)):
            raise ValueError('Could not write the HDR compositing layer.')
    finally:
        output.close()


def _read_linear(path, width, height):
    import OpenImageIO as oiio
    image = oiio.ImageInput.open(str(path))
    if image is None:
        raise ValueError('A frame in the HDR master is not a readable EXR.')
    try:
        spec = image.spec()
        if (spec.width, spec.height, spec.nchannels) != (width, height, 3):
            raise ValueError('An HDR master frame does not match the reviewed output.')
        pixels = image.read_image(format=oiio.FLOAT)
    finally:
        image.close()
    if pixels is None or pixels.shape != (height, width, 3) or not np.isfinite(pixels).all():
        raise ValueError('An HDR master frame contains invalid pixels.')
    return pixels


def _border_alpha(mask, feather=_FEATHER):
    """Opaque generated area with a smooth overlap *inside* the source plate."""
    from scipy.ndimage import distance_transform_edt
    area = np.asarray(mask, dtype=np.bool_)
    if area.all():
        return np.ones(area.shape, dtype=np.float32)
    if not area.any():
        return np.zeros(area.shape, dtype=np.float32)
    distance = distance_transform_edt(~area)
    t = np.clip(distance / float(feather), 0, 1)
    alpha = 1 - (t * t * (3 - 2 * t))
    alpha[area] = 1
    return alpha.astype(np.float32)


def _owned_directory(root):
    base = Path(root).resolve()
    directory = base / 'genj' / 'hdr'
    directory.mkdir(parents=True, exist_ok=True)
    resolved = directory.resolve()
    if not resolved.is_relative_to(base) or resolved != directory:
        raise ValueError('The HDR output folder is unavailable.')
    return resolved


def _native_frame_stream(source, selection, info, directory, cancelled):
    """Read the reviewed CFR selection once, with the HDR loader's transforms.

    Restarting FFmpeg for separate batches can move the sampling phase for
    fractional-rate source footage. One continuous stream matches the reviewed
    timeline without retaining the entire decoded video in memory.
    """
    from .hdr_native_source import HDR_VIDEO_SPACES
    from ..paintout.paintout import find_media_tool, selected_space, working

    if info.get('kind') != 'video':
        raise ValueError('Original HDR source video is required for compositing layers.')
    selected = selected_space(info, selection['colour_space'])
    if selected not in HDR_VIDEO_SPACES or info.get('transfer') in ('bt709', 'iec61966-2-1'):
        raise ValueError('Choose a supported HDR source video.')
    if selection['colour_space'] == 'pq_display_p3' and (info.get('transfer') != 'smpte2084' or info.get('primaries') != 'smpte432'):
        raise ValueError('Display-P3 PQ requires matching source transfer and primaries tags.')
    try:
        rate = Fraction(info['fps_rational'])
        available = Fraction(info['count'], 1) / rate
    except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
        raise ValueError('Could not read the original HDR source timeline.') from exc
    start = Fraction(str(selection['start']))
    if not 1 <= rate <= 120 or start + Fraction(selection['frames']-1, 24) >= available:
        raise ValueError('The reviewed selection extends past the HDR source.')
    width, height = info['width'], info['height']
    frame_size = width * height * 3 * 2
    vf = 'setpts=PTS-STARTPTS,fps=24.0'
    matrix = {'bt2020nc':'bt2020', 'bt2020c':'bt2020', 'bt709':'bt709', 'smpte170m':'bt601'}.get(info.get('matrix'))
    if matrix:
        vf += f',scale=in_color_matrix={matrix}:in_range={"pc" if info.get("range") == "pc" else "tv"}:out_range=pc'
    vf += ',tpad=stop_mode=clone:stop=1'
    command = [find_media_tool('ffmpeg'), '-v','error', '-ss',str(selection['start']), '-i',str(source),
               '-vf',vf, '-frames:v',str(selection['frames']), '-an','-sn','-fps_mode','passthrough',
               '-f','rawvideo','-pix_fmt','rgb48le','pipe:1']
    with (Path(directory)/'source-decode.log').open('wb') as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log)
        try:
            for _ in range(selection['frames']):
                _cancelled(cancelled)
                buffer = bytearray(frame_size)
                view = memoryview(buffer)
                offset = 0
                while offset < frame_size:
                    read = process.stdout.readinto(view[offset:])
                    if not read:
                        raise ValueError('The HDR source ended before the reviewed frame range.')
                    offset += read
                rgb = np.frombuffer(buffer, dtype='<u2').reshape(height, width, 3).astype(np.float32) / 65535.
                converted = working(torch.from_numpy(rgb)[None], selected, 'HDR (ACEScct)')
                if not torch.isfinite(converted).all():
                    raise ValueError('The HDR source produced non-finite pixels.')
                yield converted
            process.stdout.close()
            if process.wait(timeout=120) != 0:
                raise ValueError('Could not decode the original HDR source.')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdout is not None:
                process.stdout.close()


def _canvas_frame(native, selection, padded_width, padded_height):
    """Match the reviewed canvas, including a temporarily empty black mask.

    The generation graph prepares a batch at a time and permits an individual
    frame's black-area mask to be empty/full when another frame is mixed. This
    exporter streams single frames, so preserve those legitimate per-frame
    masks rather than treating them as an invalid one-frame selection.
    """
    import torch.nn.functional as F
    from .ltx_outpaint import prepare_hdr_canvas
    from ..paintout.paintout import decode_ct, encode_ct

    threshold = float(selection.get('black_threshold', 2/255))
    if selection['mode'] == 'black':
        linear = decode_ct(native)
        mask = (linear.amax(dim=-1) <= threshold).to(dtype=linear.dtype)
        if not bool(mask.any()) or bool(mask.all()):
            height, width = linear.shape[1:3]
            if not (0 <= padded_width-width < 64 and 0 <= padded_height-height < 64):
                raise ValueError('Black-padded footage must match the reviewed dimensions.')
            if width != padded_width or height != padded_height:
                linear = F.pad(linear.permute(0,3,1,2), (0,padded_width-width,0,padded_height-height)).permute(0,2,3,1)
                mask = F.pad(mask, (0,padded_width-width,0,padded_height-height), value=1)
            return encode_ct(linear), mask
    return prepare_hdr_canvas(native, selection['mode'], padded_width, padded_height,
                              *(selection[k] for k in ('left','top','right','bottom')), threshold)


def export_hdr_outpaint_layers(archive_path, source_path, selection, output_root, prefix,
                               *, cancelled=None, progress=None):
    """Publish a straight-alpha ACEScg layer ZIP without video generation.

    Frame filenames start at zero and match the delivered master. Source frames
    beyond the selected duration hold the final frame exactly like the master.
    ``cancelled`` may be a threading.Event, and ``progress(done, total)`` is
    invoked after each complete frame. Only the exporter-owned temporary folder
    is removed on failure or cancellation; existing deliverables are untouched.
    """
    from PIL import Image
    from ..paintout.paintout import decode_ct, describe

    width, height, frames = _checked_selection(selection)
    if not isinstance(prefix, str) or not _PREFIX.fullmatch(prefix):
        raise ValueError('Choose a valid HDR output name.')
    master, source = Path(archive_path), Path(source_path)
    if master.is_symlink() or not master.is_file() or master.suffix.lower() != '.zip':
        raise ValueError('The completed HDR EXR master is unavailable.')
    if not source.is_file():
        raise ValueError('The original HDR source is unavailable.')
    _cancelled(cancelled)
    total = max(9, frames + (1 - frames) % 8)
    parent = _owned_directory(output_root)
    destination = parent / (prefix + '_layers.zip')
    if destination.exists():
        raise ValueError('An HDR compositing-layer archive with this name already exists.')
    # ZIP_STORED of float EXRs can require up to two RGBA layers plus matte per
    # frame, with an additional pair of temporary frames during publication.
    needed = width * height * (total * 33 + 32) + total * 8192 + 16 * 1024**2
    if shutil.disk_usage(parent).free < needed:
        raise ValueError('Not enough free disk space for HDR compositing layers.')
    try:
        incoming = zipfile.ZipFile(master, 'r')
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError('The HDR EXR master could not be opened.') from exc
    with incoming:
        expected = [f'frame_{index:05d}.exr' for index in range(total)]
        # Exact names reject traversal, duplicate names, extra files and gaps.
        infos = incoming.infolist()
        if (sorted(info.filename for info in infos) != expected or
            any(info.is_dir() or info.file_size <= 0 or info.file_size > width*height*24+4*1024**2 for info in infos)):
            raise ValueError('The HDR master does not contain the expected safe EXR sequence.')
        info = describe(str(source))
        source_pixels = info['width'] * info['height']
        from .hdr_source import MAX_PIXEL_FRAMES
        if source_pixels > MAX_PIXEL_FRAMES:
            raise ValueError('The source frame exceeds the HDR memory budget.')
        temp_prefix = '.zura-layers-' + uuid.uuid4().hex + '-'
        with tempfile.TemporaryDirectory(prefix=temp_prefix, dir=parent) as directory:
            working = Path(directory)
            uncompressed = working / 'input.exr'
            plate_file, border_file, matte_file = (working/'plate.exr', working/'border.exr', working/'matte.png')
            temporary = working / 'layers.zip'
            stream = _native_frame_stream(source, selection, info, working, cancelled)
            with closing(stream), zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_STORED, allowZip64=True) as out:
                last_plate = last_mask = None
                padded_width, padded_height = ((width+63)//64)*64, ((height+63)//64)*64
                for index, name in enumerate(expected):
                    _cancelled(cancelled)
                    if index < frames:
                        try:
                            native = next(stream)
                        except StopIteration as exc:
                            raise ValueError('The HDR source ended before the reviewed frame range.') from exc
                        plate, mask = _canvas_frame(native, selection, padded_width, padded_height)
                        last_plate = decode_ct(plate[0,:height,:width].float()).cpu().numpy().copy()
                        last_mask = mask[0,:height,:width].cpu().numpy().copy()
                        del native, plate, mask
                    if last_plate is None or last_mask is None or last_plate.shape != (height,width,3):
                        raise ValueError('The original HDR plate does not match the reviewed output.')
                    with incoming.open(name, 'r') as entry, uncompressed.open('wb') as target:
                        shutil.copyfileobj(entry, target, length=1024*1024)
                    composite = _read_linear(uncompressed, width, height)
                    generated_mask = last_mask >= .5
                    plate_alpha = (~generated_mask).astype(np.float32)
                    border_alpha = _border_alpha(generated_mask)
                    _write_rgba(plate_file, last_plate, plate_alpha)
                    _write_rgba(border_file, composite, border_alpha)
                    Image.fromarray(np.rint(border_alpha*65535).astype(np.uint16)).save(matte_file)
                    out.write(plate_file, f'original_plate/frame_{index:05d}.exr')
                    out.write(border_file, f'generated_border/frame_{index:05d}.exr')
                    out.write(matte_file, f'border_matte/frame_{index:05d}.png')
                    if progress:
                        progress(index+1, total)
                # Advancing once more lets the streaming reader verify FFmpeg
                # exited successfully before the archive can be published.
                if next(stream, None) is not None:
                    raise ValueError('The HDR source returned too many frames.')
                manifest = {'version':1, 'fps':24, 'source_start_seconds':selection['start'],
                    'source_frames':frames, 'delivered_frames':total, 'held_tail_frames':total-frames,
                    'frame_numbering':'zero-based, matching the delivered master',
                    'width':width, 'height':height, 'mode':selection['mode'],
                    'margins':{k:selection[k] for k in ('left','top','right','bottom')},
                    'source_colour':selection['colour_space'], 'black_threshold':selection.get('black_threshold',2/255),
                    'working_space':'linear ACEScg/AP1', 'alpha':'straight / unassociated', 'border_feather_pixels':_FEATHER,
                    'contents':{'original_plate':'Original HDR footage positioned on the output canvas; transparent outside its kept area.',
                        'generated_border':'Delivered HDR master in the generated area plus a feathered overlap; this is not raw model output.',
                        'border_matte':'16-bit PNG of the border alpha, white is the generated area.'}}
                out.writestr('manifest.json', json.dumps(manifest, indent=2))
                out.writestr('README.txt',
                    'HDR frame-extension compositing layers\n\n'
                    'Import original_plate and generated_border as matching 24 fps EXR sequences.\n'
                    'Place generated_border over original_plate. Both use scene-linear ACEScg/AP1.\n'
                    'Interpret alpha as straight (unassociated). The border alpha has a 16-pixel\n'
                    'inward overlap; adjust its levels and feather in your compositor.\n'
                    'The border comes from the finished, colour-matched master; raw model pixels\n'
                    'inside the source area were not retained. border_matte is the same alpha.\n'
                    'The final held frames and zero-based filenames match the delivered video.\n')
            _cancelled(cancelled)
            try:
                _publish_verified(temporary, destination)
            except FileExistsError as exc:
                raise ValueError('An HDR compositing-layer archive with this name already exists.') from exc
    return destination
