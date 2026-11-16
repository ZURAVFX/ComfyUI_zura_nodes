"""Bounded, reversible SDR image layers over an immutable Studio model view.

Float EXR storage preserves compositing values. It does not turn an SDR image
model's output into an HDR generation or replace a retained native HDR source.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading

import numpy as np
from PIL import Image
from aiohttp import web

MAX_PIXELS = 16 * 1024 * 1024
MAX_BYTES = 512 * 1024 * 1024
MAX_BODY = 1024 * 1024
_writer = threading.Lock()
_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.exr'}


class ComposeBusy(ValueError):
    pass


def _linked(path):
    return path.is_symlink() or bool(getattr(path, 'is_junction', lambda: False)())


def _identity(path):
    before = path.stat()
    if not path.is_file() or _linked(path) or before.st_nlink != 1 or not 1 <= before.st_size <= MAX_BYTES:
        raise ValueError('Choose an unchanged image inside ComfyUI storage.')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    after = path.stat()
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if stamp(before) != stamp(after):
        raise ValueError('An image changed while composing. The previous result is retained.')
    return stamp(after), digest.hexdigest()


def _ref(ref, roots):
    from .display_view_routes import _file_ref
    path, root = _file_ref(ref, {key: value for key, value in roots.items() if key in {'input', 'output'}})
    if path.suffix.lower() not in _SUFFIXES:
        raise ValueError('Choose a stored PNG, JPEG, WebP, TIFF or sRGB EXR image.')
    # Reject redirected ancestors even if their resolved target remains inside
    # the root, so an editable link cannot substitute a different layer later.
    lexical = Path(roots[ref['type']]) / ref.get('subfolder', '') / ref['filename']
    cursor = lexical
    while cursor != Path(roots[ref['type']]):
        if _linked(cursor):
            raise ValueError('Linked image paths cannot be used as editable layers.')
        cursor = cursor.parent
    return path, _identity(path)


def _pixels(path, shape, *, mask=False):
    import OpenImageIO as oiio
    from .display_view_routes import _image
    reader = oiio.ImageInput.open(str(path))
    if reader is None:
        raise ValueError('A layer image is unreadable. The previous result is retained.')
    try:
        spec = reader.spec()
        if spec.deep or spec.depth != 1 or (spec.height, spec.width) != shape or spec.width * spec.height > MAX_PIXELS:
            raise ValueError('Each image and selection must match the original image dimensions.')
        if spec.get_int_attribute('Orientation', 1) != 1:
            raise ValueError('Apply image orientation before using editable layers.')
        if reader.seek_subimage(1, 0):
            raise ValueError('Choose a single image, not a multi-page or layered file.')
        if mask:
            if path.suffix.lower() != '.png':
                raise ValueError('Use a source-sized PNG selection mask.')
        elif path.suffix.lower() == '.exr':
            space = str(spec.getattribute('oiio:ColorSpace') or '').lower().replace(' ', '')
            if space not in {'srgb', 'srgb_display', 'srgb_rec709_scene', 'srgbencodedrec.709(srgb)'}:
                raise ValueError('Use the verified SDR model view for image layers. The original HDR master is retained.')
    finally:
        reader.close()
    if mask:
        with Image.open(path) as image:
            if image.mode not in {'L', 'RGB', 'RGBA'}:
                raise ValueError('Use an 8-bit source-sized PNG selection mask.')
            values = np.asarray(image.convert('RGB'), dtype=np.float32)[..., 0] / np.float32(255)
        return values.copy()
    rgba = _image(path, convert_icc=not mask)
    if rgba.shape != (*shape, 4) or not np.isfinite(rgba).all():
        raise ValueError('A layer contains invalid pixels. The previous result is retained.')
    if np.any(rgba[..., 3] != 1):
        raise ValueError('Image-edit layers need opaque images. Use the dedicated Alpha mode for transparency.')
    return rgba[..., :3].copy()


def _write_master(path, pixels):
    import OpenImageIO as oiio
    spec = oiio.ImageSpec(pixels.shape[1], pixels.shape[0], 3, oiio.FLOAT)
    spec.channelnames = ('R', 'G', 'B')
    spec.attribute('oiio:ColorSpace', 'sRGB')
    spec.attribute('zura:encoding', 'srgb_display')
    spec.attribute('zura:dynamicRange', 'SDR')
    spec.attribute('compression', 'zip')
    writer = oiio.ImageOutput.create(str(path))
    if writer is None or not writer.open(str(path), spec):
        raise ValueError('Could not save the image-layer master.')
    try:
        if not writer.write_image(np.ascontiguousarray(pixels, dtype=np.float32)):
            raise ValueError('Could not save the complete image-layer master.')
    finally:
        writer.close()


def _resize(pixels, width, height):
    import OpenImageIO as oiio
    source = oiio.ImageBuf(np.ascontiguousarray(pixels))
    target = oiio.ImageBuf(oiio.ImageSpec(width, height, 3, oiio.FLOAT))
    if not oiio.ImageBufAlgo.resize(target, source, 'lanczos3'):
        raise ValueError('Could not resize the finished image-layer composite.')
    values = np.asarray(target.get_pixels(oiio.FLOAT), dtype=np.float32)
    if values.shape != (height, width, 3) or not np.isfinite(values).all():
        raise ValueError('The resized image-layer result is invalid.')
    return values


def compose(body, roots):
    from ..paintout.frame_layers import compose_pixels, validate_opacity, validate_expand_pixels, validate_blend_pixels, validate_brightness_ev
    if not isinstance(body, dict) or body.get('schemaVersion') != 1 or body.get('source_colour') != 'srgb_display':
        raise ValueError('Use a verified SDR image model view to compose image layers.')
    width, height = body.get('width'), body.get('height')
    if type(width) is not int or type(height) is not int or min(width, height) < 1 or width * height > MAX_PIXELS:
        raise ValueError('Image layers support an original image up to 16 megapixels.')
    layers = body.get('layers')
    if not isinstance(layers, list) or len(layers) > 32:
        raise ValueError('Compose up to 32 independent image layers.')
    allowed = {'schemaVersion', 'source', 'source_colour', 'width', 'height', 'layers', 'expected_source_sha256', 'delivery'}
    if set(body) - allowed:
        raise ValueError('Unsupported image-layer request fields.')
    delivery = body.get('delivery', {'width': width, 'height': height})
    if not isinstance(delivery, dict) or set(delivery) != {'width', 'height'}:
        raise ValueError('Choose the finished image output dimensions.')
    dw, dh = delivery['width'], delivery['height']
    if type(dw) is not int or type(dh) is not int or min(dw, dh) < 1 or dw * dh > MAX_PIXELS or abs((dw/dh)/(width/height)-1) > .01:
        raise ValueError('Output dimensions must preserve the original image aspect and stay within 16 megapixels.')
    source, source_identity = _ref(body.get('source'), roots)
    expected = body.get('expected_source_sha256')
    if expected is not None and (not isinstance(expected, str) or not _SHA.fullmatch(expected) or expected != source_identity[1]):
        raise ValueError('The original image changed. Reload it before editing its layers.')
    original = _pixels(source, (height, width))
    identities = [(source, source_identity)]
    prepared, applied, seen = [], [], set()
    for layer in layers:
        if not isinstance(layer, dict) or set(layer) - {'id', 'file', 'mask', 'colour_space', 'enabled', 'opacity', 'expand_pixels', 'blend_pixels', 'brightness_ev'}:
            raise ValueError('Choose valid independent image layers.')
        identity = layer.get('id')
        if not isinstance(identity, str) or not _ID.fullmatch(identity) or identity in seen:
            raise ValueError('Each image layer needs a unique identity.')
        seen.add(identity)
        if layer.get('colour_space') != 'srgb_display' or type(layer.get('enabled', True)) is not bool:
            raise ValueError('Choose SDR image layers with an explicit visibility state.')
        controls = dict(id=identity, enabled=layer.get('enabled', True), opacity=validate_opacity(layer.get('opacity', 1)),
                        expand_pixels=validate_expand_pixels(layer.get('expand_pixels', 0)), blend_pixels=validate_blend_pixels(layer.get('blend_pixels', 0)),
                        brightness_ev=validate_brightness_ev(layer.get('brightness_ev', 0)))
        file, stamp = _ref(layer.get('file'), roots)
        identities.append((file, stamp))
        mask_ref = layer.get('mask')
        mask_path = None
        if mask_ref is not None:
            mask_path, stamp = _ref(mask_ref, roots)
            identities.append((mask_path, stamp))
        prepared.append((file, mask_path, controls))
        applied.append(controls)
    def raster_layers():
        for file, mask, controls in prepared:
            if not controls['enabled']:
                continue
            pixels = _pixels(file, (height, width))
            selection = _pixels(mask, (height, width), mask=True) if mask else np.ones((height, width), dtype=np.float32)
            yield pixels, selection, controls['blend_pixels'], controls['brightness_ev'], controls['opacity'], controls['expand_pixels']
    result = compose_pixels(original, raster_layers(), linear=False)
    if not np.isfinite(result).all():
        raise ValueError('Image-layer controls produced invalid samples. The previous result is retained.')
    for path, identity in identities:
        if _identity(path) != identity:
            raise ValueError('An image or selection changed while composing. The previous result is retained.')
    root = Path(roots['output']).resolve(strict=True)
    directory = root / 'ZURA STUDIO' / 'image-layers'
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve() != directory or any(_linked(parent) for parent in (directory, directory.parent)):
        raise ValueError('Image-layer output storage is redirected.')
    directory = directory / secrets.token_hex(16)
    directory.mkdir()
    master, preview = directory / 'master.exr', directory / 'preview.png'
    files = [master, preview]
    try:
        _write_master(master, result)
        shown = np.round(np.clip(result, 0, 1) * 255).astype(np.uint8)
        Image.fromarray(shown).save(preview, format='PNG')
        # Re-read the master, including its colour tag and alpha, before exposing
        # it to Save, Download or Send to AE. Preview is a separate SDR8 asset.
        if not np.array_equal(_pixels(master, (height, width)), result):
            raise ValueError('The saved image-layer master did not preserve its working pixels.')
        master_hash, preview_hash = _identity(master)[1], _identity(preview)[1]
        canonical_master, canonical_preview = master, preview
        canonical_hash, canonical_preview_hash = master_hash, preview_hash
        if (dw, dh) != (width, height):
            finished = _resize(result, dw, dh)
            master, preview = directory / 'delivery.exr', directory / 'delivery.png'
            files.extend((master, preview))
            _write_master(master, finished)
            Image.fromarray(np.round(np.clip(finished, 0, 1)*255).astype(np.uint8)).save(preview, format='PNG')
            if not np.array_equal(_pixels(master, (dh, dw)), finished):
                raise ValueError('The resized master did not preserve its working pixels.')
            master_hash, preview_hash = _identity(master)[1], _identity(preview)[1]
        for path, identity in identities:
            if _identity(path) != identity:
                raise ValueError('An image changed before the composite was published. The previous result is retained.')
        # This product receipt is required for the SDR-float AE return. The
        # browser's colour label alone can never authorise an arbitrary EXR.
        artifacts = {}
        for path, role, aw, ah in ((canonical_master, 'canonical_master', width, height), (canonical_preview, 'canonical_preview', width, height), (master, 'master', dw, dh), (preview, 'preview', dw, dh)):
            artifacts[path.name] = dict(filename=path.name, role=role, sha256=_identity(path)[1], byteLength=path.stat().st_size, width=aw, height=ah)
        receipt = directory / 'image-layers.json'; files.append(receipt)
        receipt.write_text(json.dumps(dict(schemaVersion=1, owner='zura_image_layers', source=dict(sha256=source_identity[1], width=width, height=height), colour={'encoding':'srgb_display','sceneLinear':False}, sampleType='float32', channels=['R','G','B'], hasAlpha=False, controls=applied, artifacts=list(artifacts.values())), sort_keys=True, separators=(',',':')), encoding='utf-8')

    except Exception:
        for file in files:
            file.unlink(missing_ok=True)
        directory.rmdir()
        raise
    ref = lambda path: {'filename': path.name, 'subfolder': path.parent.relative_to(root).as_posix(), 'type': 'output'}
    return dict(schemaVersion=1, master={**ref(master), 'role': 'composite_master', 'sha256': master_hash},
                preview={**ref(preview), 'role': 'preview', 'sha256': preview_hash}, width=dw, height=dh,
                canonicalMaster={**ref(canonical_master), 'role': 'composite_master', 'sha256': canonical_hash},
                canonicalPreview={**ref(canonical_preview), 'role': 'preview', 'sha256': canonical_preview_hash}, sourceWidth=width, sourceHeight=height,
                colour={'encoding': 'srgb_display', 'sceneLinear': False}, sampleType='float32', hasAlpha=False,
                dynamicRange='SDR', previewBitDepth=8, source_sha256=source_identity[1], applied=applied)


def _compose_locked(body, roots):
    # The worker owns the lock until disk IO finishes, even if its HTTP awaiter
    # disconnects or is cancelled. Releasing from the async caller would admit
    # another full-raster composition while the first thread was still running.
    if not _writer.acquire(blocking=False):
        raise ComposeBusy('Image layers are still updating. Try again shortly.')
    try:
        return compose(body, roots)
    finally:
        _writer.release()


def register(routes):
    @routes.post('/zura/studio/image-layers/compose')
    async def compose_route(request):
        from ..media_source import require_same_origin
        import folder_paths
        require_same_origin(request)
        try:
            raw = bytearray()
            async for chunk in request.content.iter_chunked(64 * 1024):
                raw.extend(chunk)
                if len(raw) > MAX_BODY:
                    raise ValueError('The image-layer request is too large.')
            body = json.loads(raw)
            roots = {'input': folder_paths.get_input_directory(), 'output': folder_paths.get_output_directory()}
            result = await asyncio.to_thread(_compose_locked, body, roots)
            return web.json_response(result, headers={'Cache-Control': 'no-store'})
        except ComposeBusy as error:
            return web.json_response({'error': str(error)}, status=409)
        except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
            return web.json_response({'error': str(error)}, status=400)
