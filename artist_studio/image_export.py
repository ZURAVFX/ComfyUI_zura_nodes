"""Explicit SDR delivery files made from verified, immutable Studio images.

File storage depth is not dynamic range. These exports keep physical encoded
sRGB values; HDR reconstruction remains the separate completed LTX job route.
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
from aiohttp import web
from PIL import Image, ImageCms

MAX_PIXELS = 16 * 1024 * 1024
MAX_BYTES = 512 * 1024 * 1024
MAX_BODY = 16 * 1024
FORMATS = {
    'png8': ('image.png', 'uint8', 8),
    'png16': ('image.png', 'uint16', 16),
    'tiff16': ('image.tiff', 'uint16', 16),
    'exr_float': ('image.exr', 'float32', 32),
}
COLOUR = {'encoding': 'srgb_display', 'sceneLinear': False}
_TOKEN = re.compile(r'[a-f0-9]{32}\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_SRGB = {'srgb', 'srgb_display', 'srgb_rec709_scene', 'srgbencodedrec.709(srgb)', 'srgbencodedrec709(srgb)'}
_writer = threading.Lock()


class ExportBusy(ValueError):
    pass


def _json(raw):
    def pairs(values):
        result = {}
        for name, value in values:
            if name in result:
                raise ValueError('The image export receipt contains duplicate fields.')
            result[name] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Invalid receipt number.')))


def _identity(path):
    from .image_layers import _identity as identity
    return identity(path)


def _path(asset, output_root):
    from .display_view_routes import _file_ref
    if not isinstance(asset, dict) or set(asset) != {'filename', 'subfolder', 'type'} or asset['type'] != 'output':
        raise ValueError('Choose a finished Studio output image.')
    root = Path(output_root).resolve(strict=True)
    path, _ = _file_ref(asset, {'output': root})
    lexical = root / asset['subfolder'] / asset['filename']
    cursor = lexical
    while cursor != root:
        if cursor.is_symlink() or bool(getattr(cursor, 'is_junction', lambda: False)()):
            raise ValueError('Linked output images cannot be exported.')
        cursor = cursor.parent
    _identity(path)
    return path, root


def _relative_product(path, root, family):
    parts = path.relative_to(root).parts
    return len(parts) == 4 and parts[:2] == ('ZURA STUDIO', family) and bool(_TOKEN.fullmatch(parts[2]))


def _header(path, *, product_float=False, icc_input=False):
    import OpenImageIO as oiio
    reader = oiio.ImageInput.open(str(path))
    if reader is None:
        raise ValueError('This finished image could not be read.')
    try:
        # OIIO's live spec may change even when seek_subimage fails.
        spec = oiio.ImageSpec(reader.spec())
        names = [name.lower() for name in spec.channelnames]
        if (spec.deep or spec.depth != 1 or not 1 <= spec.width <= 16384 or not 1 <= spec.height <= 16384
                or spec.width * spec.height > MAX_PIXELS or spec.nchannels not in (3, 4)
                or set(names) not in ({'r', 'g', 'b'}, {'r', 'g', 'b', 'a'})
                or spec.get_int_attribute('Orientation', 1) != 1 or reader.seek_subimage(1, 0)):
            raise ValueError('Choose one finite, source-sized RGB image with its orientation applied.')
        formats = list(spec.channelformats) or [spec.format] * spec.nchannels
        allowed = [oiio.FLOAT] if product_float else [oiio.UINT8, oiio.UINT16]
        if any(not any(value == candidate for candidate in allowed) for value in formats) or len(set(map(str, formats))) != 1:
            raise ValueError('Use the verified SDR image-layer master for FLOAT export. HDR files need their completed HDR delivery.')
        for name in ('oiio:ColorSpace', 'colorSpace', 'colorInteropID', 'zura:encoding'):
            tag = str(spec.getattribute(name) or '').lower().replace(' ', '')
            # Conventional 8-bit ICC images can be physically transformed by
            # LCMS below. Explicit HDR/scene-linear metadata is never retagged.
            allow_profile = icc_input and formats[0] == oiio.UINT8 and not any(word in tag for word in ('aces', 'linear', 'pq', '2084', 'hlg', '2020'))
            if tag and tag not in _SRGB and not allow_profile:
                raise ValueError('This image is not a verified SDR sRGB output. Its original is retained.')
        if spec.get_int_attribute('acesImageContainerFlag', 0) or str(spec.getattribute('zura:dynamicRange') or '').upper() not in ('', 'SDR'):
            raise ValueError('Use the completed HDR master directly; this exporter only writes SDR images.')
        return spec.width, spec.height, 32 if formats[0] == oiio.FLOAT else 16 if formats[0] == oiio.UINT16 else 8
    finally:
        reader.close()


def _read_source(asset, output_root):
    from .display_view_routes import _image
    from ..comfylink.float_io import read_image_layer_exr
    path, root = _path(asset, output_root)
    identity = _identity(path)
    if _relative_product(path, root, 'image-layers'):
        if path.name not in {'master.exr', 'delivery.exr'}:
            raise ValueError('Choose the retained image-layer master, rather than its display preview.')
        rgba, proof = read_image_layer_exr(path, root)
        source_bits = 32
    elif _relative_product(path, root, 'image-exports'):
        receipt = _export_receipt(path, root)
        if receipt['dynamicRange'] != 'SDR':
            raise ValueError('Use the verified HDR master directly. This export does not silently tone-map HDR to SDR.')
        width, height, source_bits = _header(path, product_float=receipt['sampleType'] == 'float32')
        rgba = _image(path, convert_icc=False)
        proof = {'receiptSha256': hashlib.sha256((path.parent / 'image-export.json').read_bytes()).hexdigest()}
    else:
        from .output_settings import OutputSettings
        resolver = object.__new__(OutputSettings)
        resolver.source = root
        if resolver.source_file(asset) != path or path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff'}:
            raise ValueError('Choose a completed Studio SDR image, not a private working file or arbitrary EXR.')
        with Image.open(path) as image:
            profile = image.info.get('icc_profile')
            if profile is not None and (not isinstance(profile, bytes) or len(profile) > 1024 * 1024):
                raise ValueError('The embedded ICC profile exceeds the image export limit.')
        width, height, source_bits = _header(path, icc_input=bool(profile))
        # Inspect actual alpha before an ICC conversion, including palette/tRNS
        # PNGs. No transparent input is flattened or silently made opaque.
        rgba = _image(path, convert_icc=False)
        if np.any(rgba[..., 3] != 1):
            raise ValueError('Use the dedicated Alpha workflow for transparency; this image export is RGB only.')
        rgba = _image(path, convert_icc=True)
        proof = {}
    if rgba.ndim != 3 or rgba.shape[2] != 4 or rgba.shape[0] * rgba.shape[1] > MAX_PIXELS or not np.isfinite(rgba).all() or np.any(rgba[..., 3] != 1):
        raise ValueError('The SDR output must be finite, opaque RGB. The original image is retained.')
    if _identity(path) != identity:
        raise ValueError('The image changed while preparing its delivery. Try again after editing finishes.')
    return np.ascontiguousarray(rgba[..., :3], dtype=np.float32), source_bits, path, root, identity, proof


def _srgb_profile():
    return ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()


def _write(path, pixels, format):
    import OpenImageIO as oiio
    _, sample_type, bits = FORMATS[format]
    if sample_type == 'float32':
        encoded, storage, profile = pixels, oiio.FLOAT, b''
    else:
        maximum, storage = (255, oiio.UINT8) if bits == 8 else (65535, oiio.UINT16)
        encoded = np.round(np.clip(pixels, 0, 1) * maximum).astype(np.uint8 if bits == 8 else np.uint16)
        profile = _srgb_profile()
    spec = oiio.ImageSpec(pixels.shape[1], pixels.shape[0], 3, storage)
    spec.channelnames = ('R', 'G', 'B')
    spec.attribute('oiio:ColorSpace', 'sRGB')
    spec.attribute('zura:encoding', 'srgb_display')
    spec.attribute('zura:dynamicRange', 'SDR')
    if profile:
        # OIIO requires a byte buffer here; tuple/list values are ignored.
        spec.attribute('ICCProfile', oiio.TypeDesc(f'uint8[{len(profile)}]'), profile)
    if path.suffix == '.exr':
        spec.attribute('compression', 'zip')
    writer = oiio.ImageOutput.create(str(path))
    if writer is None or not writer.open(str(path), spec):
        raise ValueError('Could not create the selected image format.')
    try:
        if not writer.write_image(np.ascontiguousarray(encoded)):
            raise ValueError('Could not write the complete image delivery.')
    finally:
        writer.close()
    reader = oiio.ImageInput.open(str(path))
    if reader is None:
        raise ValueError('The written image could not be verified.')
    try:
        actual_spec = reader.spec()
        formats = list(actual_spec.channelformats) or [actual_spec.format] * actual_spec.nchannels
        actual = reader.read_image(format=storage)
        if (actual_spec.width != pixels.shape[1] or actual_spec.height != pixels.shape[0]
                or actual_spec.nchannels != 3 or tuple(actual_spec.channelnames) != ('R', 'G', 'B')
                or actual_spec.alpha_channel != -1 or any(value != storage for value in formats)
                or actual is None or not np.array_equal(actual, encoded)):
            raise ValueError('The image writer did not retain the selected RGB storage precision.')
    finally:
        reader.close()
    if profile:
        with Image.open(path) as image:
            if image.info.get('icc_profile') != profile:
                raise ValueError('The image writer did not retain its physical sRGB profile.')
    else:
        _header(path, product_float=True)
    return hashlib.sha256(profile).hexdigest() if profile else ''


def _export_receipt(path, root):
    if not _relative_product(path, root, 'image-exports'):
        raise ValueError('Choose a product-owned image delivery.')
    receipt_path = path.parent / 'image-export.json'
    receipt_identity = _identity(receipt_path)
    if receipt_identity[0][2] > MAX_BODY:
        raise ValueError('Invalid image-export receipt.')
    raw = receipt_path.read_bytes()
    value = _json(raw)
    if isinstance(value, dict) and value.get('owner') == 'zura_hdr_still_export':
        from .image_export_hdr import validate_hdr_receipt
        return validate_hdr_receipt(path, root, value, raw)
    keys = {'schemaVersion', 'owner', 'format', 'filename', 'sha256', 'byteLength', 'width', 'height',
            'colour', 'dynamicRange', 'sampleType', 'bitDepth', 'sourceBitDepth', 'hasAlpha',
            'source', 'iccSha256', 'precisionPolicy'}
    if (not isinstance(value, dict) or set(value) != keys or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1
            or value['owner'] != 'zura_image_export' or value['format'] not in FORMATS
            or value['colour'] != COLOUR or value['dynamicRange'] != 'SDR' or value['hasAlpha'] is not False
            or value['precisionPolicy'] != 'file_storage_only_no_precision_added'
            or value['sourceBitDepth'] not in (8, 16, 32)):
        raise ValueError('The image delivery has no valid SDR product receipt.')
    filename, sample_type, bits = FORMATS[value['format']]
    if (path.name != filename or value['filename'] != filename or value['sampleType'] != sample_type or value['bitDepth'] != bits
            or type(value['width']) is not int or type(value['height']) is not int
            or not 1 <= value['width'] <= 16384 or not 1 <= value['height'] <= 16384
            or value['width'] * value['height'] > MAX_PIXELS or not _SHA.fullmatch(value['sha256'])
            or type(value['byteLength']) is not int or not 1 <= value['byteLength'] <= MAX_BYTES
            or not isinstance(value['source'], dict) or set(value['source']) != {'asset', 'sha256', 'receiptSha256'}
            or not _SHA.fullmatch(value['source']['sha256'])):
        raise ValueError('The image delivery receipt changed.')
    before, digest = _identity(path)
    if digest != value['sha256'] or before[2] != value['byteLength']:
        raise ValueError('The image delivery changed after verification.')
    width, height, depth = _header(path, product_float=sample_type == 'float32')
    if (width, height, depth) != (value['width'], value['height'], bits):
        raise ValueError('The image delivery storage differs from its receipt.')
    if sample_type != 'float32':
        if not _SHA.fullmatch(value['iccSha256']):
            raise ValueError('The SDR delivery has no physical profile proof.')
        with Image.open(path) as image:
            profile = image.info.get('icc_profile') or b''
        if hashlib.sha256(profile).hexdigest() != value['iccSha256']:
            raise ValueError('The SDR delivery colour profile changed.')
    if receipt_path.read_bytes() != raw or _identity(receipt_path) != receipt_identity or _identity(path) != (before, digest):
        raise ValueError('The image delivery changed during verification.')
    return value


def verified_product_file(output_root, asset):
    """Narrow save-copy allowlist for receipted product-owned still files."""
    from ..comfylink.float_io import read_image_layer_exr
    path, root = _path(asset, output_root)
    if _relative_product(path, root, 'image-exports'):
        _export_receipt(path, root)
        return path
    if _relative_product(path, root, 'image-layers') and path.name in {'master.exr', 'delivery.exr', 'preview.png', 'delivery.png'}:
        master = path.with_name('delivery.exr' if path.name in {'delivery.exr', 'delivery.png'} else 'master.exr')
        read_image_layer_exr(master, root)
        return path
    raise ValueError('This image has no verified product-owned delivery.')


def export_image(body, output_root):
    if not isinstance(body, dict) or set(body) != {'asset', 'format'} or body['format'] not in FORMATS:
        raise ValueError('Choose PNG 8-bit, PNG 16-bit, TIFF 16-bit or SDR FLOAT EXR.')
    format = body['format']
    pixels, source_bits, source, root, identity, proof = _read_source(body['asset'], output_root)
    parent = root / 'ZURA STUDIO' / 'image-exports'
    for ancestor in (parent.parent, parent):
        if ancestor.exists() and (ancestor.is_symlink() or bool(getattr(ancestor, 'is_junction', lambda: False)())):
            raise ValueError('The image-export directory is redirected.')
    parent.mkdir(parents=True, exist_ok=True)
    if parent.resolve(strict=True) != parent or any(p.is_symlink() or bool(getattr(p, 'is_junction', lambda: False)()) for p in (parent, parent.parent)):
        raise ValueError('The image-export directory is redirected.')
    directory = parent / secrets.token_hex(16)
    directory.mkdir()
    path = directory / FORMATS[format][0]
    try:
        icc = _write(path, pixels, format)
        if _identity(source) != identity:
            raise ValueError('The original image changed before export completed. Try again after editing finishes.')
        stamp, digest = _identity(path)
        receipt = dict(schemaVersion=1, owner='zura_image_export', format=format, filename=path.name,
                       sha256=digest, byteLength=stamp[2], width=pixels.shape[1], height=pixels.shape[0],
                       colour=COLOUR.copy(), dynamicRange='SDR', sampleType=FORMATS[format][1], bitDepth=FORMATS[format][2],
                       sourceBitDepth=source_bits, hasAlpha=False, iccSha256=icc,
                       precisionPolicy='file_storage_only_no_precision_added',
                       source=dict(asset=body['asset'].copy(), sha256=identity[1], receiptSha256=proof.get('receiptSha256', '')))
        with (directory / 'image-export.json').open('x', encoding='utf-8') as file:
            json.dump(receipt, file, sort_keys=True, separators=(',', ':'))
        _export_receipt(path, root)
        return {key: value for key, value in receipt.items() if key not in {'owner', 'source', 'iccSha256', 'filename'}} | {
            'file': dict(filename=path.name, subfolder=path.parent.relative_to(root).as_posix(), type='output')}
    except BaseException:
        # Only these newly generated leaves belong to this operation. Retain an
        # unexpected entry instead of recursively removing anything unknown.
        for candidate in (path, directory / 'image-export.json'):
            if candidate.is_file() and not candidate.is_symlink():
                candidate.unlink()
        try:
            directory.rmdir()
        except OSError:
            pass
        raise


def _export_locked(body, root, hdr_service=None):
    if not _writer.acquire(blocking=False):
        raise ExportBusy('An image is already being prepared. Wait for that export to finish.')
    try:
        if isinstance(body, dict) and body.get('format') == 'hdr_exr':
            from .image_export_hdr import export_hdr_image
            return export_hdr_image(body, root, hdr_service)
        return export_image(body, root)
    finally:
        _writer.release()


def register(routes):
    @routes.post('/zura/studio/image-export')
    async def export_route(request):
        from ..media_source import require_same_origin
        import folder_paths
        require_same_origin(request)
        try:
            raw = bytearray()
            async for chunk in request.content.iter_chunked(4096):
                raw.extend(chunk)
                if len(raw) > MAX_BODY:
                    raise ValueError('The image-export request is too large.')
            from server import PromptServer
            service = getattr(PromptServer.instance, '_zura_hdr_long_preview', None)
            result = await asyncio.to_thread(_export_locked, _json(raw), folder_paths.get_output_directory(), service)
            return web.json_response(result, headers={'Cache-Control': 'no-store'})
        except ExportBusy as error:
            return web.json_response({'error': str(error)}, status=409)
        except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
            return web.json_response({'error': str(error)}, status=400)
