"""Physical single-EXR proof for a completed, server-owned LTX still job.

An extension, browser colour label or successful HTTP response is not proof of
HDR. The coordinator owns the job and source binding; OIIO checks the artifact.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import zipfile

import numpy as np

from .image_export import MAX_BYTES, MAX_BODY, MAX_PIXELS, _TOKEN, _SHA, _identity, _json, _path, _relative_product

COLOUR = {'encoding': 'acescg', 'sceneLinear': True}
_AP1 = (.713, .293, .165, .830, .128, .044, .32168, .33767)


def _clean(ref):
    if not isinstance(ref, dict):
        raise ValueError('The completed HDR job has no image source binding.')
    return dict(filename=ref.get('filename'), subfolder=ref.get('subfolder', ''), type=ref.get('type'))


def capture_still_source(body, output_root):
    """Called by the trusted coordinator before resolving its model input."""
    if body.get('source_kind') != 'output_image':
        return None
    asset = _clean(body.get('output_ref'))
    path, _ = _path(asset, output_root)
    stamp, digest = _identity(path)
    return dict(asset=asset, sha256=digest, byteLength=stamp[2])


def verify_still_source(pin, output_root):
    if (not isinstance(pin, dict) or set(pin) != {'asset', 'sha256', 'byteLength'}
            or not isinstance(pin['sha256'], str) or not _SHA.fullmatch(pin['sha256'])
            or type(pin['byteLength']) is not int or not 1 <= pin['byteLength'] <= MAX_BYTES):
        raise ValueError('This older HDR job has no server-verified source fingerprint. Its SDR original is retained.')
    path, _ = _path(pin['asset'], output_root)
    stamp, digest = _identity(path)
    if (digest, stamp[2]) != (pin['sha256'], pin['byteLength']):
        raise ValueError('The SDR source changed after HDR admission. The old HDR result cannot be attached to this image.')
    return path


def verify_model_input(pin, output_root):
    """Resolve only the private immutable still consumed by the queued graph."""
    from .image_export import _header as sdr_header
    if (not isinstance(pin, dict) or set(pin) != {'asset', 'sha256', 'byteLength', 'sourceMasterSha256', 'width', 'height', 'storageBitDepth'}
            or not isinstance(pin['sourceMasterSha256'], str) or not _SHA.fullmatch(pin['sourceMasterSha256'])
            or not isinstance(pin['sha256'], str) or not _SHA.fullmatch(pin['sha256'])
            or type(pin['byteLength']) is not int or not 1 <= pin['byteLength'] <= MAX_BYTES):
        raise ValueError('The HDR still has no owned model-input snapshot.')
    path, root = _path(pin['asset'], output_root)
    if not _relative_product(path, root, 'hdr-model-inputs') or path.name not in {'source.png', 'source.tif', 'source.tiff'}:
        raise ValueError('The HDR model input is not private job media.')
    record_path = path.parent / 'hdr-model-input.json'
    record_identity = _identity(record_path)
    if record_identity[0][2] > MAX_BODY:
        raise ValueError('The HDR model-input proof is too large.')
    raw = record_path.read_bytes()
    record = _json(raw)
    if record != {'schemaVersion': 1, 'owner': 'zura_hdr_model_input', **pin}:
        raise ValueError('The HDR model-input proof changed.')
    stamp, digest = _identity(path)
    if (digest, stamp[2]) != (pin['sha256'], pin['byteLength']) or path.stat().st_mode & stat.S_IWRITE:
        raise ValueError('The owned HDR model input changed or is writable.')
    if sdr_header(path, icc_input=True) != (pin['width'], pin['height'], pin['storageBitDepth']):
        raise ValueError('The HDR model-input raster or actual file depth changed.')
    if _identity(path) != (stamp, digest) or _identity(record_path) != record_identity or record_path.read_bytes() != raw:
        raise ValueError('The owned HDR model input changed during verification.')
    return path


def snapshot_still_model(asset, check_asset, admitted_source, output_root):
    """Copy the resolved PNG/TIFF without decoding, quantising or retagging it."""
    from ..comfylink.float_io import _locked_parents
    from .image_export import _header as sdr_header
    verify_still_source(admitted_source, output_root)
    root = Path(output_root).resolve(strict=True)
    model_source = Path(check_asset(asset)).resolve(strict=True)
    if not model_source.is_relative_to(root) or model_source.suffix.lower() not in {'.png', '.tif', '.tiff'}:
        raise ValueError('The still HDR model needs a verified stored PNG or TIFF input.')
    relative = model_source.relative_to(root)
    model_source, _ = _path(dict(filename=relative.name, subfolder=relative.parent.as_posix(), type='output'), root)
    identity = _identity(model_source)
    width, height, depth = sdr_header(model_source, icc_input=True)
    parent = root / 'ZURA STUDIO'
    with _locked_parents(root):
        if parent.exists() and (parent.is_symlink() or bool(getattr(parent, 'is_junction', lambda: False)())):
            raise ValueError('The HDR model-input parent is redirected.')
        parent.mkdir(exist_ok=True)
    container = parent / 'hdr-model-inputs'
    with _locked_parents(parent):
        if container.exists() and (container.is_symlink() or bool(getattr(container, 'is_junction', lambda: False)())):
            raise ValueError('The HDR model-input directory is redirected.')
        container.mkdir(exist_ok=True)
    directory = container / secrets.token_hex(16)
    with _locked_parents(container):
        directory.mkdir()
    destination = directory / ('source' + model_source.suffix.lower())
    receipt_path = directory / 'hdr-model-input.json'
    try:
        with _locked_parents(directory):
            total = 0
            with model_source.open('rb') as reader, destination.open('xb') as writer:
                for chunk in iter(lambda: reader.read(1024 * 1024), b''):
                    total += len(chunk)
                    if total > identity[0][2] or total > MAX_BYTES:
                        raise ValueError('The HDR model input changed during snapshotting.')
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            stamp, digest = _identity(destination)
            if (total, digest) != (identity[0][2], identity[1]) or _identity(model_source) != identity:
                raise ValueError('The HDR model input changed during snapshotting.')
            verify_still_source(admitted_source, root)
            reference = dict(filename=destination.name, subfolder=destination.parent.relative_to(root).as_posix(), type='output')
            pin = dict(asset=reference, sha256=digest, byteLength=stamp[2], sourceMasterSha256=admitted_source['sha256'],
                       width=width, height=height, storageBitDepth=depth)
            with receipt_path.open('x', encoding='utf-8') as writer:
                json.dump({'schemaVersion': 1, 'owner': 'zura_hdr_model_input', **pin}, writer, sort_keys=True, separators=(',', ':'))
                writer.flush()
                os.fsync(writer.fileno())
            os.chmod(destination, stat.S_IREAD)
            os.chmod(receipt_path, stat.S_IREAD)
        verify_model_input(pin, root)
        return pin
    except BaseException:
        for path in (destination, receipt_path):
            if path.is_file() and not path.is_symlink():
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
                path.unlink()
        try:
            directory.rmdir()
        except OSError:
            pass
        raise


def discard_model_input(pin, output_root):
    """Only an unqueued producer may discard its exact private input pair."""
    path = verify_model_input(pin, output_root)
    receipt = path.parent / 'hdr-model-input.json'
    for owned in (path, receipt):
        os.chmod(owned, stat.S_IREAD | stat.S_IWRITE)
        owned.unlink()
    path.parent.rmdir()


def _header(path):
    import OpenImageIO as oiio
    reader = oiio.ImageInput.open(str(path))
    if reader is None:
        raise ValueError('The completed HDR EXR could not be read.')
    try:
        spec = oiio.ImageSpec(reader.spec())
        formats = list(spec.channelformats) or [spec.format] * spec.nchannels
        colour_aliases = [spec.getattribute(name) for name in ('oiio:ColorSpace', 'colorSpace', 'colorInteropID')
                          if spec.getattribute(name) is not None]
        valid_colour = bool(colour_aliases) and all(
            isinstance(value, str) and value.lower().replace(' ', '') in {'acescg', 'aces-acescg', 'lin_ap1', 'lin_ap1_scene'}
            for value in colour_aliases)
        chroma = spec.getattribute('chromaticities')
        if (spec.deep or spec.depth != 1 or not 1 <= spec.width <= 16384 or not 1 <= spec.height <= 16384
                or spec.width * spec.height > MAX_PIXELS or spec.nchannels != 3 or set(spec.channelnames) != {'R', 'G', 'B'}
                or spec.alpha_channel != -1 or not formats or len(set(map(str, formats))) != 1
                or not (formats[0] == oiio.HALF or formats[0] == oiio.FLOAT) or not valid_colour
                or chroma is None or len(chroma) != 8 or any(not np.isfinite(float(a)) or abs(float(a) - b) > 1e-5 for a, b in zip(chroma, _AP1))
                or any('icc' in item.name.lower() or 'profile' in item.name.lower() for item in spec.extra_attribs)
                or spec.get_int_attribute('Orientation', 1) != 1 or reader.seek_subimage(1, 0)):
            raise ValueError('The HDR result is not a verified RGB HALF/FLOAT ACEScg EXR. Its SDR original is retained.')
        pixels = reader.read_image(format=oiio.FLOAT)
        if pixels is None or pixels.shape != (spec.height, spec.width, 3) or not np.isfinite(pixels).all():
            raise ValueError('The HDR EXR contains invalid or incomplete pixels.')
        bits = 32 if formats[0] == oiio.FLOAT else 16
        return spec.width, spec.height, bits
    finally:
        reader.close()


def validate_hdr_receipt(path, root, value=None, raw=None):
    if not _relative_product(path, root, 'image-exports') or path.name != 'image.exr':
        raise ValueError('Choose a verified HDR still export.')
    receipt_path = path.parent / 'image-export.json'
    stamp = _identity(receipt_path)
    if stamp[0][2] > MAX_BODY:
        raise ValueError('Invalid HDR image receipt.')
    raw = receipt_path.read_bytes() if raw is None else raw
    value = _json(raw) if value is None else value
    keys = {'schemaVersion', 'owner', 'format', 'filename', 'sha256', 'byteLength', 'width', 'height', 'colour',
            'dynamicRange', 'sampleType', 'bitDepth', 'sourceBitDepth', 'hasAlpha', 'verifiedHDR', 'hdrJobId',
            'sourceMasterSha256', 'modelInputSha256', 'source', 'archive', 'archiveSha256'}
    if (not isinstance(value, dict) or set(value) != keys or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1
            or value['owner'] != 'zura_hdr_still_export' or value['format'] != 'hdr_exr' or value['filename'] != 'image.exr'
            or value['colour'] != COLOUR or value['dynamicRange'] != 'HDR' or value['hasAlpha'] is not False or value['verifiedHDR'] is not True
            or value['bitDepth'] not in (16, 32) or value['sourceBitDepth'] != value['bitDepth']
            or value['sampleType'] != ('float32' if value['bitDepth'] == 32 else 'float16')
            or type(value['width']) is not int or type(value['height']) is not int
            or not isinstance(value['hdrJobId'], str) or not _TOKEN.fullmatch(value['hdrJobId'])
            or not isinstance(value['sha256'], str) or not _SHA.fullmatch(value['sha256'])
            or not isinstance(value['archiveSha256'], str) or not _SHA.fullmatch(value['archiveSha256'])
            or not isinstance(value['sourceMasterSha256'], str) or not _SHA.fullmatch(value['sourceMasterSha256'])
            or not isinstance(value['modelInputSha256'], str) or not _SHA.fullmatch(value['modelInputSha256'])
            or type(value['byteLength']) is not int or not 1 <= value['byteLength'] <= MAX_BYTES):
        raise ValueError('The image has no complete physical HDR proof.')
    before, digest = _identity(path)
    if digest != value['sha256'] or before[2] != value['byteLength']:
        raise ValueError('The verified HDR still changed.')
    if _header(path) != (value['width'], value['height'], value['bitDepth']):
        raise ValueError('The HDR still differs from its recorded geometry or precision.')
    if _identity(path) != (before, digest) or _identity(receipt_path) != stamp or receipt_path.read_bytes() != raw:
        raise ValueError('The HDR proof changed during verification.')
    return value


def _authoritative_job(service, body, root):
    identity = body['jobId']
    if service is None or not isinstance(identity, str) or not _TOKEN.fullmatch(identity):
        raise ValueError('The original HDR job is unavailable. It was not restarted; keep the SDR master or reconnect to its running engine.')
    snapshot = service.jobs.status(identity)
    job, _ = service.jobs.jobs[identity]
    plan = job.store.plan
    if (snapshot.get('state') != 'complete' or snapshot.get('frames') != 1 or snapshot.get('result', {}).get('frames') != 1
            or getattr(job.store, 'planning_mode', None) != 'sdr' or len(plan) != 1 or plan[0].count != 1
            or snapshot['result'].get('alphaAssociation') is not None or snapshot['result'].get('layout') == 'RGBA'):
        raise ValueError('Wait for this one-frame RGB HDR reconstruction to complete. Its SDR original is retained.')
    requests = []
    for record in service._requests.values():
        if record.get('id') == identity:
            try:
                requests.append(json.loads(record['fingerprint']))
            except (ValueError, KeyError, TypeError):
                continue
    source = body['source']
    pin = snapshot.get('sourceMaster')
    verify_still_source(pin, root)
    if pin['asset'] != source:
        raise ValueError('This HDR result belongs to a different original source image.')
    model_input = snapshot.get('modelInput')
    verify_model_input(model_input, root)
    if model_input['sourceMasterSha256'] != pin['sha256']:
        raise ValueError('The HDR model input does not match its admitted SDR master.')
    if not any(request.get('mode') == 'sdr' and request.get('source_kind') == 'output_image' and request.get('frame_count') == 1
               and _clean(request.get('output_ref')) == source for request in requests):
        raise ValueError('This HDR result does not belong to the selected SDR image.')
    path, _ = _path(body['asset'], root)
    outputs = snapshot['result'].get('files', [])
    if not any(Path(value).resolve() == path for value in outputs if isinstance(value, str)):
        raise ValueError('The selected file is not an output of this completed HDR job.')
    if path.suffix.lower() != '.zip' or path.parent != root / 'genj' / 'hdr':
        raise ValueError('Choose the completed native HDR EXR archive.')
    return snapshot, path


def export_hdr_image(body, output_root, service):
    if not isinstance(body, dict) or set(body) != {'asset', 'format', 'jobId', 'source'} or body['format'] != 'hdr_exr':
        raise ValueError('Choose a completed one-frame HDR image and its original job.')
    asset, root = _path(body['asset'], output_root)
    source, _ = _path(body['source'], root)
    source_identity = _identity(source)
    # A physical proof already published by this server remains independently
    # verifiable after a backend restart. Unknown old jobs never get resubmitted.
    if _relative_product(asset, root, 'image-exports'):
        receipt = validate_hdr_receipt(asset, root)
        if receipt['hdrJobId'] != body['jobId'] or receipt['source'] != body['source'] or receipt['sourceMasterSha256'] != source_identity[1]:
            raise ValueError('This verified HDR still belongs to a different original image.')
        return {key: value for key, value in receipt.items() if key not in {'owner', 'filename', 'source', 'archive', 'archiveSha256'}} | {'file': body['asset'].copy()}
    snapshot, archive = _authoritative_job(service, body, root)
    archive_identity = _identity(archive)
    parent = root / 'ZURA STUDIO' / 'image-exports'
    for ancestor in (parent.parent, parent):
        if ancestor.exists() and (ancestor.is_symlink() or bool(getattr(ancestor, 'is_junction', lambda: False)())):
            raise ValueError('The image-export directory is redirected.')
    parent.mkdir(parents=True, exist_ok=True)
    directory = parent / secrets.token_hex(16)
    directory.mkdir()
    destination = directory / 'image.exr'
    try:
        try:
            with zipfile.ZipFile(archive) as zipped:
                entries = zipped.infolist()
                if len(entries) != 1:
                    raise ValueError('The still HDR archive must contain exactly one EXR and no extra files.')
                entry = entries[0]
                mode = (entry.external_attr >> 16) & 0xFFFF
                if (entry.filename != 'frame_00000.exr' or entry.is_dir() or entry.flag_bits & 1
                        or stat.S_ISLNK(mode) or mode and not stat.S_ISREG(mode) and stat.S_IFMT(mode) != 0
                        or not 1 <= entry.file_size <= MAX_BYTES or not 1 <= entry.compress_size <= MAX_BYTES):
                    raise ValueError('The HDR archive has an invalid or oversized single-frame entry.')
                count = 0
                with zipped.open(entry) as reader, destination.open('xb') as writer:
                    for chunk in iter(lambda: reader.read(1024 * 1024), b''):
                        count += len(chunk)
                        if count > entry.file_size or count > MAX_BYTES:
                            raise ValueError('The HDR still exceeds its declared storage limit.')
                        writer.write(chunk)
                if count != entry.file_size:
                    raise ValueError('The HDR still is incomplete.')
        except zipfile.BadZipFile as error:
            raise ValueError('The completed HDR archive is damaged. Its SDR original is retained.') from error
        width, height, depth = _header(destination)
        expected_bits = 32 if snapshot.get('exr_storage') == 'float32' else 16
        if (width, height) != (snapshot.get('width'), snapshot.get('height')) or depth != expected_bits:
            raise ValueError('The HDR still geometry or actual storage differs from its completed job.')
        if _identity(archive) != archive_identity or _identity(source) != source_identity or service.jobs.status(body['jobId']).get('state') != 'complete':
            raise ValueError('The HDR job, original or archive changed during verification.')
        verify_still_source(snapshot['sourceMaster'], root)
        verify_model_input(snapshot['modelInput'], root)
        stamp, digest = _identity(destination)
        receipt = dict(schemaVersion=1, owner='zura_hdr_still_export', format='hdr_exr', filename='image.exr',
                       sha256=digest, byteLength=stamp[2], width=width, height=height, colour=COLOUR.copy(),
                       dynamicRange='HDR', sampleType='float32' if depth == 32 else 'float16', bitDepth=depth,
                       sourceBitDepth=depth, hasAlpha=False, verifiedHDR=True, hdrJobId=body['jobId'],
                       sourceMasterSha256=source_identity[1], modelInputSha256=snapshot['modelInput']['sha256'],
                       source=body['source'].copy(), archive=body['asset'].copy(), archiveSha256=archive_identity[1])
        with (directory / 'image-export.json').open('x', encoding='utf-8') as writer:
            json.dump(receipt, writer, sort_keys=True, separators=(',', ':'))
        validate_hdr_receipt(destination, root)
        return {key: value for key, value in receipt.items() if key not in {'owner', 'filename', 'source', 'archive', 'archiveSha256'}} | {
            'file': dict(filename=destination.name, subfolder=destination.parent.relative_to(root).as_posix(), type='output')}
    except BaseException:
        for path in (destination, directory / 'image-export.json'):
            if path.is_file() and not path.is_symlink():
                path.unlink()
        try:
            directory.rmdir()
        except OSError:
            pass
        raise
