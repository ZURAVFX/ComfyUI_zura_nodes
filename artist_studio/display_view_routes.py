"""Bounded, display-only OCIO previews of original Studio media."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import hashlib
import io
import json
import math
from pathlib import Path
import re
import secrets
import time
import threading
from fractions import Fraction
from urllib.parse import parse_qs, urlsplit

import numpy as np
from aiohttp import web
from PIL import Image

from ..comfylink import display_view, float_io

MAX_PIXELS = 16 * 1024 * 1024
MAX_SIDE = 1280
MAX_FRAMES = 10000
SOURCE_TTL = 2 * 60 * 60
_sources = OrderedDict()
_source_lock = threading.RLock()
_SPACES = {
    'srgb_display': ('sRGB Encoded Rec.709 (sRGB)', 'srgb_tx', 'sRGB - Texture'),
    'rec709_oetf': ('Camera Rec.709',),
    'rec709_gamma24': ('Gamma 2.4 Encoded Rec.709', 'Rec.1886 Rec.709 - Display'),
    'linear_rec709': ('Linear Rec.709 (sRGB)', 'lin_rec709_srgb', 'Utility - Linear - sRGB'),
    'acescg': ('ACEScg', 'lin_ap1', 'ACES - ACEScg'),
    'acescct': ('ACEScct', 'acescct_ap1', 'ACES - ACEScct'),
    'hlg_rec2020': ('Rec.2100-HLG - Display',),
    'pq_rec2020': ('Rec.2100-PQ - Display',),
    'pq_display_p3': ('ST2084-P3-D65 - Display',),
}
_IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.exr', '.hdr'}
_VIDEO_SUFFIXES = {'.mp4', '.mov', '.mkv', '.webm', '.mxf', '.avi'}


def _stamp(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _cleanup():
    with _source_lock:
        now = time.monotonic()
        for token, value in list(_sources.items()):
            if value['expires'] < now:
                _sources.pop(token, None)
        while len(_sources) > 64 or sum(len(value['files']) for value in _sources.values()) > 20000:
            _sources.popitem(last=False)


def grant_source(path, colour='auto'):
    """Called only by the existing native media inspector after selection."""
    from ..paintout.browser import checked_path
    from ..paintout.paintout import natural
    path = checked_path(str(path))
    files = ([path] if path.is_file() else sorted(
        (entry for entry in path.iterdir() if entry.suffix.lower() in _IMAGE_SUFFIXES), key=natural))
    if not files or len(files) > MAX_FRAMES or any(not item.is_file() or item.is_symlink() for item in files):
        raise ValueError('This selected source exceeds the display preview limit.')
    _cleanup()
    token = secrets.token_urlsafe(24)
    record = {'path': path, 'stamp': _stamp(path), 'files': [(p, _stamp(p)) for p in files],
              'colour': colour, 'expires': time.monotonic() + SOURCE_TTL}
    with _source_lock:
        _sources[token] = record
        _cleanup()
    return token


def _source_token(token, frame):
    _cleanup()
    with _source_lock:
        value = _sources.get(token) if isinstance(token, str) else None
    if not value or value['expires'] < time.monotonic():
        raise ValueError('Reload the selected media to refresh its display preview.')
    path = value['path']
    if path.resolve(strict=True) != path or _stamp(path) != value['stamp']:
        raise ValueError('The selected media changed. Reload it before previewing.')
    if path.is_dir():
        if frame >= len(value['files']):
            raise ValueError('The preview frame is outside the selected sequence.')
        selected, stamp = value['files'][frame]
        if selected.resolve(strict=True) != selected or _stamp(selected) != stamp:
            raise ValueError('The selected frame changed. Reload the sequence.')
        return selected, 0, value['colour']
    return path, frame, value['colour']


def _file_ref(ref, roots):
    if not isinstance(ref, dict) or set(ref) - {'filename', 'subfolder', 'type'}:
        raise ValueError('Choose a stored Studio source or result.')
    name, folder, kind = ref.get('filename'), ref.get('subfolder', ''), ref.get('type')
    if (kind not in roots or not isinstance(name, str) or not name or name in {'.', '..'}
            or Path(name).name != name or any(c in name for c in ('/', '\\', ':', '\0'))
            or not isinstance(folder, str) or any(c in folder for c in ('\\', ':', '\0'))
            or folder.startswith('/') or any(part in {'.', '..'} for part in folder.split('/'))):
        raise ValueError('Choose a valid stored media reference.')
    root = Path(roots[kind]).resolve()
    lexical = root / folder / name
    path = lexical.resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file() or lexical.is_symlink():
        raise ValueError('The selected media is outside Studio storage.')
    if path.suffix.lower()=='.zip' and kind!='output':
        raise ValueError('Choose a completed native HDR output archive.')
    if path.suffix.lower() not in _IMAGE_SUFFIXES | _VIDEO_SUFFIXES | {'.zip'} and name != 'manifest.json':
        raise ValueError('This master format does not yet expose original pixels to the display viewer.')
    return path, root


def _resolve(selector, frame, store, check_asset, roots,cancel=None):
    if (not isinstance(selector, dict) or not selector
            or len(selector) != 1 and set(selector) != {'asset_id','frame_time'}):
        raise ValueError('Choose one display source.')
    if 'imported_frame' in selector:
        if frame!=0:raise ValueError('An imported image is bound to one selected original frame.')
        from .media_import import resolve_imported_frame
        selected,colour=resolve_imported_frame(selector['imported_frame'],store,check_asset,roots,cancel=cancel)
        path,index,_,root=_resolve(selected,0,store,check_asset,roots,cancel=cancel)
        return path,index,colour,root
    if 'source_token' in selector:
        path, index, colour = _source_token(selector['source_token'], frame)
        return path, index, colour, None
    if 'file' in selector:
        path, root = _file_ref(selector['file'], roots)
        return path, frame, 'auto', root
    if 'asset_id' in selector:
        identity = selector['asset_id']
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{32}', identity):
            raise ValueError('Choose a registered Studio asset.')
        asset = store.load(identity)
        path = Path(check_asset(asset)).resolve(strict=True)
        if asset.get('asset_kind') == 'hdr_sequence':
            if 'frame_time' in selector: raise ValueError('Choose an actual EXR sequence frame.')
            from .hdr_sequence import validate_manifest
            directory, entries = validate_manifest(path, asset.get('sha', ''), frame, 1,cancel=cancel)
            return directory / entries[frame]['name'], 0, 'auto', None
        if asset.get('asset_kind') not in {'video', 'image'} or path.suffix.lower() not in _IMAGE_SUFFIXES | _VIDEO_SUFFIXES:
            raise ValueError('Choose an image or video asset.')
        if 'frame_time' in selector:
            value = selector['frame_time']
            if type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= 86400 or frame != 0 or asset.get('asset_kind') != 'video':
                raise ValueError('Choose a valid original video frame.')
            from ..paintout.paintout import describe
            info = describe(str(path),cancel=cancel); rate = Fraction(info['fps_rational']); position = float(value*rate)
            frame = round(position)
            if abs(position-frame) > 1e-4 or frame >= info['count']:
                raise ValueError('The original image does not map to an exact video frame.')
        return path, frame, 'auto', None
    if 'media_url' in selector:
        from ..paintout.browser import _media_grants, checked_path
        value = selector['media_url']
        if not isinstance(value,str) or len(value)>4096:raise ValueError('Choose a selected local media preview.')
        url = urlsplit(value)
        query = parse_qs(url.query, strict_parsing=True)
        if url.scheme or url.netloc or url.path != '/zura/paintout/media' or set(query) != {'token'} or len(query['token']) != 1:
            raise ValueError('Choose a selected local media preview.')
        value = _media_grants.get(query['token'][0])
        if not value or value[1] < time.monotonic() or checked_path(str(value[0])) != value[0]:
            raise ValueError('Reload this media to refresh its display preview.')
        return value[0], frame, 'auto', None
    raise ValueError('Choose a registered Studio source or result.')


def _image(path, *, convert_icc=False):
    import OpenImageIO as oiio
    options = oiio.ImageSpec(); options.attribute('oiio:UnassociatedAlpha', 1)
    reader = oiio.ImageInput.open(str(path), options)
    if reader is None:
        raise ValueError('The original image could not be read.')
    try:
        spec = reader.spec(); names = [name.lower() for name in spec.channelnames]
        if spec.deep or spec.depth != 1 or spec.width * spec.height > MAX_PIXELS or spec.width < 1 or spec.height < 1:
            raise ValueError('This original image exceeds the display preview limit.')
        if convert_icc and path.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.tif','.tiff'}:
            with Image.open(path) as original:
                profile = original.info.get('icc_profile')
                if profile:
                    if len(profile) > 1024*1024 or spec.format != oiio.UINT8 or any(value != oiio.UINT8 for value in spec.channelformats):
                        raise ValueError('This embedded ICC source needs an explicit high-depth colour interpretation.')
                    try:
                        from PIL import ImageCms
                        converted = ImageCms.profileToProfile(original.convert('RGB'), ImageCms.ImageCmsProfile(io.BytesIO(profile)), ImageCms.createProfile('sRGB'), outputMode='RGB')
                    except Exception:
                        raise ValueError('The embedded ICC profile could not be converted for display.') from None
                    rgba = np.ones((spec.height,spec.width,4),dtype=np.float32)
                    rgba[...,:3] = np.asarray(converted,dtype=np.float32)/np.float32(255)
                    if 'A' in original.getbands():rgba[...,3] = np.asarray(original.getchannel('A'),dtype=np.float32)/np.float32(255)
                    return rgba
        if not all(name in names for name in ('r', 'g', 'b')):
            raise ValueError('Choose an original image with named RGB channels for colour preview.')
        channels = [names.index(name) for name in ('r', 'g', 'b')]
        alpha = names.index('a') if 'a' in names else None
        selected = channels + ([alpha] if alpha is not None else [])
        # Read only the needed channel span, rather than all EXR utility layers.
        first, last = min(selected), max(selected) + 1
        if last - first > 16:
            raise ValueError('Select a compact RGB beauty layer for display preview.')
        raw = np.asarray(reader.read_image(0, 0, first, last, oiio.FLOAT), dtype=np.float32)
        if raw.ndim != 3:
            raise ValueError('The original image has no readable RGB pixels.')
        rgba = np.ones((spec.height, spec.width, 4), dtype=np.float32)
        rgba[..., :3] = raw[..., [index-first for index in channels]]
        if alpha is not None: rgba[..., 3] = raw[..., alpha-first]
        return rgba
    finally:
        reader.close()


def resolve_original(selector, store, check_asset, roots, *, archive_metadata=None,cancel=None):
    """Resolve one authorised original and keep a revalidation closure for jobs.

    Paths in this descriptor stay server-side. Browser callers supply only the
    scoped selector, never a path to read from the filesystem.
    """
    path, _, detected, root = _resolve(selector, 0, store, check_asset, roots,cancel=cancel)
    identity_path = path
    files = None
    grant = None
    if 'source_token' in selector:
        with _source_lock: grant = _sources.get(selector['source_token'])
        if grant is None: raise ValueError('The original source selection expired.')
        identity_path = grant['path']
        if identity_path.is_dir(): files = [entry[0] for entry in grant['files']]
    elif 'asset_id' in selector:
        asset = store.load(selector['asset_id'])
        if asset.get('asset_kind') == 'hdr_sequence':
            from .hdr_sequence import validate_manifest
            identity_path = Path(check_asset(asset)).resolve(strict=True)
            directory, entries = validate_manifest(identity_path, asset.get('sha', ''), 0, 1,cancel=cancel)
            files = [directory / entry['name'] for entry in entries]
    stamp = _stamp(identity_path)
    expected_archive=None
    if path.suffix.lower()=='.zip':
        from .hdr_archive_display import describe_archive
        expected_archive=archive_metadata(path) if archive_metadata else None
        metadata=describe_archive(path,expected_archive)
    elif path.name == 'manifest.json':
        manifest = float_io.read_manifest(root, path.relative_to(root).as_posix())
        metadata = {'kind': 'float_sequence', 'frame_count': len(manifest['frames']),
                    'frame_rate': manifest['frameRate'], 'source_colour': manifest['colour'],
                    'source_bit_depth': manifest['sourceBitDepth'], 'alpha_association': manifest['alphaAssociation'], 'manifest': manifest}
        files = [path.parent / frame['filename'] for frame in manifest['frames']]
    elif files is not None:
        metadata = {'kind': 'sequence', 'frame_count': len(files), 'frame_rate': None}
    elif path.suffix.lower() in _VIDEO_SUFFIXES:
        from ..paintout.paintout import describe
        info = describe(str(path),cancel=cancel)
        rate = Fraction(info['fps_rational'])
        metadata = {'kind': 'video', 'frame_count': 1 if 'frame_time' in selector or 'imported_frame' in selector else info['count'],
                    'frame_rate': {'numerator': rate.numerator, 'denominator': rate.denominator}, 'info': info}
    else:
        metadata = {'kind': 'image', 'frame_count': 1, 'frame_rate': None}

    def revalidate(full=True):
        current, _, _, _ = _resolve(selector, 0, store, check_asset, roots,cancel=cancel)
        if current != path or _stamp(identity_path) != stamp:
            raise ValueError('The original media changed during the operation.')
        if grant is not None:
            with _source_lock: current_grant = _sources.get(selector['source_token'])
            if current_grant is not grant:
                raise ValueError('The original source selection expired.')
            if full and any(_stamp(file) != saved for file, saved in grant['files']):
                raise ValueError('The original source frames changed during the operation.')

    return {'path': identity_path, 'frame_path': path, 'files': files,
            'detectedColour': detected, 'stamp': stamp, 'root': root,
            'metadata': metadata, 'archive_metadata':expected_archive,'revalidate': revalidate}


def _float_frame(root, path, index):
    relative = path.relative_to(root).as_posix()
    manifest = float_io.read_manifest(root, relative)
    if index >= len(manifest['frames']): raise ValueError('The preview frame is outside the result.')
    frame = manifest['frames'][index]
    with float_io._locked_parents(path.parent):
        payload = float_io._read_private(path.parent/frame['filename'], frame['byteLength'], frame['byteLength'])
    if hashlib.sha256(payload).hexdigest() != frame['sha256']:
        raise ValueError('The original FLOAT result changed.')
    return payload, manifest


def read_original(selector, frame, store, check_asset, roots, colour_space='auto', *, archive_metadata=None):
    """Read one verified original frame in bounded memory, without a view LUT."""
    if type(frame) is not int or not 0 <= frame < MAX_FRAMES:
        raise ValueError('Choose a valid original frame.')
    resolved = resolve_original(selector, store, check_asset, roots,archive_metadata=archive_metadata)
    metadata = dict(resolved['metadata'])
    if frame >= metadata['frame_count']:
        raise ValueError('The frame is outside the original source interval.')
    path, local_frame, detected, root = _resolve(selector, frame, store, check_asset, roots)
    before = _stamp(path)
    if path.suffix.lower()=='.zip':
        if colour_space not in ('auto','acescg'):raise ValueError('Native HDR archives declare scene-linear ACEScg.')
        from .hdr_archive_display import read_archive_frame
        rgba,metadata=read_archive_frame(path,local_frame,resolved['archive_metadata']);space='acescg'
    elif path.name == 'manifest.json':
        payload, manifest = _float_frame(root, path, local_frame)
        dtype = '<f4' if manifest['sampleType'] == 'float32' else '<u2'
        rgba = np.frombuffer(payload, dtype=dtype).reshape(manifest['height'], manifest['width'], 4).astype(np.float32)
        if manifest['sampleType'] == 'uint16_ae': rgba /= np.float32(32768)
        source = manifest['colour']
        encoding = display_view._verified_ocio_source(source) if source.get('management') == 'ocio' else source['encoding']
        space = {'srgb8': 'srgb_display', 'scene_linear_rec709': 'linear_rec709'}.get(encoding, encoding)
        if space == 'unknown':
            space = 'srgb_display' if manifest['sourceBitDepth'] == 8 else colour_space
    elif path.suffix.lower() in _IMAGE_SUFFIXES:
        from ..paintout.paintout import _exr_auto_space
        rgba = _image(path, convert_icc=colour_space == 'auto')
        space = (colour_space if colour_space != 'auto' else detected if detected != 'auto'
                 else _exr_auto_space(str(path)) if path.suffix.lower() == '.exr'
                 else 'linear_rec709' if path.suffix.lower() == '.hdr' else 'srgb_display')
    else:
        from ..paintout.paintout import describe, selected_space
        info = metadata.get('info') or describe(str(path))
        if info['width']*info['height'] > MAX_PIXELS: raise ValueError('The source exceeds the display frame limit.')
        space = selected_space(info, colour_space if colour_space != 'auto' else detected)
        # Read the actual decoded alpha, including ProRes 4444 transparency.
        # This bounded float copy is display-only; original bytes stay untouched.
        from .model_view import _video_frames
        reader = _video_frames(info, local_frame, 1, None)
        try:rgba = next(reader)
        finally:reader.close()
    if space not in _SPACES or not np.isfinite(rgba).all():
        raise ValueError('Choose a mapped actual source colour space for the original pixels.')
    if _stamp(path) != before: raise ValueError('The original media changed during frame decoding.')
    resolved['revalidate'](False)
    metadata.setdefault('alpha_association','straight')
    metadata.update(width=rgba.shape[1], height=rgba.shape[0], opaque=bool(np.all(rgba[..., 3] == 1)))
    return rgba, space, metadata


def render_pixels(rgba, colour, config='', display='', view='', *, alpha_association='straight'):
    """Apply the real OCIO viewing processor to a bounded copy, never a master."""
    info = display_view.describe(config)
    config = display_view._config(info['config'])
    display, view = display or info['display'], view or info['view']
    if display not in config.getDisplays() or view not in config.getViews(display):
        raise ValueError('Choose an available OCIO display and view.')
    names = _SPACES.get(colour)
    source = next((config.getColorSpace(name).getName() for name in names or () if config.getColorSpace(name)), None)
    if source is None: raise ValueError('The actual source colour space is not mapped in this OCIO configuration.')
    if rgba.ndim != 3 or rgba.shape[-1] != 4 or rgba.shape[0]*rgba.shape[1] > MAX_PIXELS or not np.isfinite(rgba).all():
        raise ValueError('The original pixels are invalid or too large for display preview.')
    scale = max(1, int(np.ceil(max(rgba.shape[:2])/MAX_SIDE)))
    sample = rgba[::scale, ::scale]
    rgb = np.array(sample[..., :3], dtype=np.float32, order='C')
    if alpha_association not in {'straight','premultiplied'}:raise ValueError('The source alpha interpretation is unknown.')
    if alpha_association == 'premultiplied':
        np.divide(rgb,sample[...,3,None],out=rgb,where=sample[...,3,None]>0)
    transform = display_view._ocio().DisplayViewTransform(src=source, display=display, view=view)
    config.getProcessor(transform).getDefaultCPUProcessor().applyRGB(rgb)
    if not np.isfinite(rgb).all(): raise ValueError('The display transform returned invalid pixels.')
    shown = np.empty((*rgb.shape[:2], 4), dtype=np.uint8)
    shown[..., :3] = np.rint(np.clip(rgb, 0, 1)*255).astype(np.uint8)
    shown[..., 3] = np.rint(np.clip(sample[..., 3], 0, 1)*255).astype(np.uint8)
    buffer = io.BytesIO(); Image.fromarray(shown, 'RGBA').save(buffer, format='PNG')
    return buffer.getvalue()


def preview(body, store, check_asset, roots, *, return_metadata=False,archive_metadata=None):
    if not isinstance(body, dict) or set(body) - {'source', 'frame', 'colour_space', 'config', 'display', 'view'}:
        raise ValueError('Choose valid display preview settings.')
    frame = body.get('frame', 0)
    if type(frame) is not int or not 0 <= frame < MAX_FRAMES:
        raise ValueError('Choose a valid display frame.')
    for name in ('config', 'display', 'view'):
        if not isinstance(body.get(name, ''), str) or len(body.get(name, '')) > 256:
            raise ValueError('Choose a valid OCIO display setting.')
    colour = body.get('colour_space', 'auto')
    if colour != 'auto' and colour not in _SPACES:
        raise ValueError('Choose the actual source colour space.')
    rgba, source_space, metadata = read_original(body.get('source'), frame, store, check_asset, roots, colour,archive_metadata=archive_metadata)
    shown = render_pixels(rgba, source_space, body.get('config', ''), body.get('display', ''), body.get('view', ''),alpha_association=metadata['alpha_association'])
    return (shown, source_space, metadata) if return_metadata else (shown, source_space)


def source_info(body, store, check_asset, roots, *, archive_metadata=None):
    """Return bounded original timing without decoding or changing pixels."""
    if not isinstance(body, dict) or set(body) != {'source'}:
        raise ValueError('Choose one display source.')
    resolved = resolve_original(body['source'], store, check_asset, roots, archive_metadata=archive_metadata)
    metadata = resolved['metadata']
    count = metadata.get('frame_count')
    if type(count) is not int or not 1 <= count <= MAX_FRAMES:
        raise ValueError('The original source has no valid frame count.')
    rate = metadata.get('frame_rate')
    if rate is not None:
        if isinstance(rate, dict):
            numerator, denominator = rate.get('numerator'), rate.get('denominator')
        elif type(rate) in (int, float) and math.isfinite(rate) and rate > 0:
            exact = Fraction(str(rate)).limit_denominator(1000000)
            numerator, denominator = exact.numerator, exact.denominator
        else:
            numerator = denominator = None
        if type(numerator) is not int or type(denominator) is not int or numerator < 1 or denominator < 1:
            raise ValueError('The original source has no valid frame rate.')
        rate = {'numerator': numerator, 'denominator': denominator}
    return {'kind': metadata.get('kind', 'source'), 'frame_count': count, 'frame_rate': rate}


def native_archive_metadata(studio,path,output_root):
    """Prefer completed server-side delivery records; never infer ZIP cadence."""
    def metadata(value):
        result={key:value[key] for key in ('width','height','exr_storage') if key in value}
        if 'frames' in value:result['frame_count']=value['frames']
        rate=value.get('frame_rate')
        if rate is not None:result['frame_rate']=rate
        else:
            fps=value.get('fps')
            if type(fps) in (int,float) and math.isfinite(fps) and fps>0:
                exact=Fraction(str(fps)).limit_denominator(1000000)
                result['frame_rate']={'numerator':exact.numerator,'denominator':exact.denominator}
        return result
    service=getattr(getattr(studio,'server',None),'_zura_hdr_long_preview',None)
    for job,details in list(getattr(getattr(service,'jobs',None),'jobs',{}).values()):
        result=getattr(job,'result',None)
        if getattr(job,'state',None)=='complete' and isinstance(result,dict) and any(isinstance(name,str) and Path(name).resolve()==path for name in result.get('files',[])):
            return metadata({**details,**result})
    root=Path(output_root).resolve()
    for _stamp_value,record in list(getattr(studio.store,'_records',{}).values())[-128:]:
        for result in record.get('results',[])[-30:]:
            if result.get('native_hdr') is not True:continue
            files=result.get('hdr_files',[])
            if not any(isinstance(ref,dict) and ref.get('type')=='output' and (root/ref.get('subfolder','')/ref.get('filename','')).resolve()==path for ref in files):continue
            return metadata({**result.get('output_raster',{}),**({'exr_storage':result['exr_storage']} if 'exr_storage' in result else {})})
    return None


def register(studio, routes, response, check_asset):
    from .route_aliases import require_studio_alias_paths
    require_studio_alias_paths(routes,(('GET','display/config'),('POST','display/frame'),('POST','display/info')))
    import folder_paths
    limit = asyncio.Semaphore(2)

    @routes.get('/zura/studio/display/config')
    @routes.get('/genj/studio/display/config')
    @response
    async def config(request):
        from ..media_source import require_same_origin
        require_same_origin(request)
        return web.json_response(display_view.describe(request.query.get('config', '')),
                                 headers={'Cache-Control': 'no-store'})

    @routes.post('/zura/studio/display/frame')
    @routes.post('/genj/studio/display/frame')
    @response
    async def frame(request):
        from ..media_source import require_same_origin
        require_same_origin(request)
        if request.content_length is not None and request.content_length > 16384:
            raise ValueError('The display request is too large.')
        parts, size = [], 0
        async for part in request.content.iter_chunked(4096):
            size += len(part)
            if size > 16384: raise ValueError('The display request is too large.')
            parts.append(part)
        body = json.loads(b''.join(parts))
        roots = {'input': folder_paths.get_input_directory(), 'output': folder_paths.get_output_directory(),
                 'temp': folder_paths.get_temp_directory()}
        async with limit:
            encoded, space, metadata = await asyncio.to_thread(preview, body, studio.store, check_asset, roots, return_metadata=True,
                archive_metadata=lambda path:native_archive_metadata(studio,path,roots['output']))
        return web.Response(body=encoded, content_type='image/png', headers={
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'X-Zura-Display-Source': space, 'X-Zura-Display-Frames': str(metadata['frame_count']),
            'X-Zura-Preview-Only': '1'})

    @routes.post('/zura/studio/display/info')
    @routes.post('/genj/studio/display/info')
    @response
    async def info(request):
        from ..media_source import require_same_origin
        require_same_origin(request)
        if request.content_length is not None and request.content_length > 4096:
            raise ValueError('The display metadata request is too large.')
        parts, size = [], 0
        async for part in request.content.iter_chunked(4096):
            size += len(part)
            if size > 4096:
                raise ValueError('The display metadata request is too large.')
            parts.append(part)
        body = json.loads(b''.join(parts))
        roots = {'input': folder_paths.get_input_directory(), 'output': folder_paths.get_output_directory(),
                 'temp': folder_paths.get_temp_directory()}
        result = await asyncio.to_thread(source_info, body, studio.store, check_asset, roots,
            archive_metadata=lambda path: native_archive_metadata(studio, path, roots['output']))
        return web.json_response(result, headers={'Cache-Control': 'no-store'})
