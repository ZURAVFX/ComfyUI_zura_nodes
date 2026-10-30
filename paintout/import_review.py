"""Explicit, source-contained review of external guide edits."""
from __future__ import annotations
import asyncio
import base64
import hashlib
import io
import json
import re
import secrets
from pathlib import Path
import numpy as np
from PIL import Image
from . import paintout as core
from . import editor_store as store
from . import browser
from .frame_editor import decode_mask, validate_edit_orientation


def _integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f'{name} must be a whole number.')
    return value


def _asset(path):
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return dict(path=str(path), size=stat.st_size, modified=stat.st_mtime_ns, sha256=digest.hexdigest())


def _context(body):
    project = body['project']
    document = store.load_project(project)
    source = str(browser.checked_path(body['source']))
    if str(browser.checked_path(document.get('data', {}).get('draft', {}).get('source'))) != source:
        raise ValueError('Review the edited frame in its original shot project.')
    description = core.describe(source)
    frame = _integer(body['frame'], 'Frame')
    if not 0 <= frame < description['count']:
        raise ValueError('Choose a source frame inside the footage.')
    return document, source, description, frame, store.source_identity(source, description)


def _pixels(description, frame, imported, source_space, edit_space):
    validate_edit_orientation(imported)
    original = np.asarray(next(core.frames(description, frame, 1)))
    edited = np.asarray(core.read_image(str(imported)))
    shape = (description['height'], description['width'], 3)
    if original.shape != shape or edited.shape != shape:
        raise ValueError('The edited RGB frame must match the exact source dimensions.')
    if not np.isfinite(original).all() or not np.isfinite(edited).all():
        raise ValueError('Source and edited pixels must be finite.')
    if source_space != edit_space:
        import torch
        edited = core.from_linear(core.to_linear(torch.from_numpy(edited.copy()).float(), edit_space), source_space).cpu().numpy()
    if not np.isfinite(edited).all():
        raise ValueError('Colour conversion produced invalid pixels.')
    return original, edited


def _png(mask):
    stream = io.BytesIO()
    Image.fromarray(np.asarray(mask, dtype=np.uint8) * 255).save(stream, format='PNG')
    return stream.getvalue()


def _owned(project, value):
    path = browser.checked_path(value).resolve(strict=True)
    if not path.is_file() or not path.is_relative_to((store.project_dir(project) / 'imports').resolve()):
        raise ValueError('Import the edited image into this project first.')
    return path


def review_import(body):
    with store._LOCK:
        document, source, description, frame, identity = _context(body)
        imported = _owned(body['project'], body['file'])
        source_space = body['source_colour_space']
        edit_space = body['colour_space']
        if source_space not in core.COLOUR_SPACES or edit_space not in core.COLOUR_SPACES:
            raise ValueError('Choose valid source and edited image colour spaces.')
        source_space = core.selected_space(description, source_space)
        edit_space = core.selected_space(core.describe(str(imported)), edit_space)
        before = _asset(imported)
        original, edited = _pixels(description, frame, imported, source_space, edit_space)
        grow = _integer(body.get('grow', 0), 'Grow')
        revision = body.get('mask_revision')
        if revision != document['mask_revision']:
            raise store.RevisionConflict('The mask changed. Review the current repair again.')
        protection = None
        if revision is not None:
            _integer(revision, 'Mask revision')
            descriptor = store.mask_descriptor(body['project'], revision)
            if descriptor['source'] != identity:
                raise ValueError('The protection belongs to different or modified footage.')
            protection = core.protection_mask(descriptor, frame)
        mask = decode_mask(body['mask'], identity['width'], identity['height'])
        repair = store.effective_mask(mask, grow, 0, protection) > 0
        changed = np.any(np.abs(edited.astype(np.float64) - original) > 1e-5 * np.maximum(1, np.abs(original)), axis=2)
        outside = changed & ~repair
        expanded = repair | changed
        if protection is not None:
            expanded[np.asarray(protection) > .001] = False
        if before != _asset(imported) or identity != store.source_identity(source, core.describe(source)):
            raise ValueError('An image changed during review. Review it again.')
        token = secrets.token_hex(16)
        directory = store.project_dir(body['project']) / 'import_reviews' / token
        directory.mkdir(parents=True)
        created = []
        try:
            urls = {}
            for name, pixels in (('difference', outside), ('repair', repair), ('expanded', expanded)):
                target = directory / (name + '.png')
                created.append(target)
                target.write_bytes(_png(pixels))
                urls[name + '_url'] = f"/zura/paintout/editor/import-review-mask?project={body['project']}&token={token}&kind={name}"
                urls[name + '_file'] = str(target)
            manifest = dict(token=token, project=body['project'], source=identity, frame=frame,
                            imported=before, source_colour_space=source_space, colour_space=edit_space,
                            mask_revision=revision, project_revision=document['revision'], grow=grow,
                            masks={name: _asset(directory / (name + '.png')) for name in ('difference', 'repair', 'expanded')})
            store._atomic_json(directory / 'manifest.json', manifest)
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            (directory / 'manifest.json').unlink(missing_ok=True)
            directory.rmdir()
            raise
        return dict(token=token, frame=frame, width=identity['width'], height=identity['height'],
                    outside_pixels=int(outside.sum()), changed_pixels=int(changed.sum()), total_pixels=int(changed.size), **urls)


def accept_import_review(body):
    token = body['token']
    if not isinstance(token, str) or not re.fullmatch('[a-f0-9]{32}', token):
        raise ValueError('Choose a valid imported-frame review.')
    if body.get('scope') not in ('current', 'include'):
        raise ValueError('Choose the current repair or include the intended changes.')
    with store._LOCK:
        document, source, description, frame, identity = _context(body)
        expected = body.get('expected_revision')
        _integer(expected, 'Project revision')
        if expected < 0:
            raise store.RevisionConflict('Accept with the current project revision.')
        store._expect(document, expected)
        directory = store.project_dir(body['project']) / 'import_reviews' / token
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        if manifest['project'] != body['project'] or manifest['token'] != token or manifest['source'] != identity or manifest['frame'] != frame:
            raise ValueError('This review belongs to different footage or a different source frame.')
        if document['mask_revision'] != manifest['mask_revision']:
            raise store.RevisionConflict('The project changed after review. Review the imported frame again.')
        imported = _owned(body['project'], manifest['imported']['path'])
        if _asset(imported) != manifest['imported']:
            raise ValueError('The imported image changed after review.')
        original, edited = _pixels(description, frame, imported, manifest['source_colour_space'], manifest['colour_space'])
        mask_path = directory / ('repair.png' if body['scope'] == 'current' else 'expanded.png')
        if _asset(mask_path) != manifest['masks']['repair' if body['scope'] == 'current' else 'expanded']:
            raise ValueError('The saved review mask changed. Review the image again.')
        with Image.open(mask_path) as image:
            if image.size != (identity['width'], identity['height']):
                raise ValueError('The saved review mask has invalid dimensions.')
            mask = np.asarray(image.convert('L')) > 0
        result = original.copy()
        result[mask] = edited[mask]
        if identity != store.source_identity(source, core.describe(source)) or _asset(imported) != manifest['imported']:
            raise ValueError('An image changed during acceptance. Review it again.')
        target = store.project_dir(body['project']) / 'imports' / ('reviewed_' + secrets.token_hex(16) + '.exr')
        try:
            _save_master(target, result.astype(np.float32), manifest['source_colour_space'])
            url = browser.grant(target)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return dict(file=str(target), url=url, frame=frame, width=identity['width'], height=identity['height'],
                    colour_space=manifest['source_colour_space'], mask='data:image/png;base64,' + base64.b64encode(_png(mask)).decode(),
                    method='manual', review_token=token, scope=body['scope'])


def _save_master(path, pixels, space):
    # Encoded HDR samples stay encoded; this is a float container, not a grade.
    if space not in ('hlg_rec2020', 'pq_rec2020', 'pq_display_p3'):
        return core.save_exr(str(path), pixels, space, False)
    import OpenImageIO as oiio
    spec = oiio.ImageSpec(pixels.shape[1], pixels.shape[0], 3, oiio.FLOAT)
    spec.channelnames = ('R', 'G', 'B')
    label = {'hlg_rec2020': 'Rec.2100 HLG', 'pq_rec2020': 'Rec.2100 PQ', 'pq_display_p3': 'Display P3 PQ'}[space]
    spec.attribute('oiio:ColorSpace', label)
    spec.attribute('zura:colour_space', space)
    spec.attribute('compression', 'zip')
    primaries = (.680, .320, .265, .690, .150, .060, .3127, .3290) if space == 'pq_display_p3' else (.708, .292, .170, .797, .131, .046, .3127, .3290)
    spec.attribute('chromaticities', oiio.TypeDesc('float[8]'), primaries)
    writer = oiio.ImageOutput.create(str(path))
    if not writer:
        raise ValueError('Could not create the reviewed EXR.')
    try:
        if not writer.open(str(path), spec) or not writer.write_image(np.ascontiguousarray(pixels)):
            raise ValueError('Could not save the reviewed EXR.')
    finally:
        writer.close()


async def _route(request, operation):
    from aiohttp import web
    from ..media_source import require_same_origin
    require_same_origin(request)
    try:
        body = await request.json()
        result = await asyncio.to_thread(operation, body)
        return web.json_response(result, headers={'Cache-Control': 'no-store'})
    except store.RevisionConflict as error:
        return web.json_response({'error': str(error)}, status=409)
    except (ValueError, KeyError, TypeError, OSError) as error:
        return web.json_response({'error': str(error)}, status=400)


def import_review_mask(project, token, kind):
    if not isinstance(token, str) or not re.fullmatch('[a-f0-9]{32}', token):
        raise ValueError('Choose a valid imported-frame review.')
    if kind not in ('difference', 'repair', 'expanded'):
        raise ValueError('Choose a review mask.')
    directory = store.project_dir(project) / 'import_reviews' / token
    store.load_project(project)
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('project') != project or manifest.get('token') != token:
        raise ValueError('This review belongs to a different project.')
    path = directory / (kind + '.png')
    if not path.resolve(strict=True).is_relative_to(directory.resolve(strict=True)):
        raise ValueError('The review mask must belong to this review.')
    if _asset(path) != manifest['masks'][kind]:
        raise ValueError('The saved review mask changed. Review the image again.')
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != manifest['masks'][kind]['sha256']:
        raise ValueError('The saved review mask changed while loading.')
    return payload


async def import_review_mask_route(request):
    from aiohttp import web
    from ..media_source import require_same_origin
    require_same_origin(request)
    try:
        payload = await asyncio.to_thread(import_review_mask, request.query.get('project'),
                                          request.query.get('token'), request.query.get('kind'))
        return web.Response(body=payload, content_type='image/png', headers={'Cache-Control': 'no-store'})
    except (ValueError, KeyError, TypeError, OSError) as error:
        return web.json_response({'error': str(error)}, status=400)


async def review_import_route(request):
    return await _route(request, review_import)


async def accept_import_review_route(request):
    return await _route(request, accept_import_review)


def register_routes():
    from server import PromptServer
    server = getattr(PromptServer, 'instance', None)
    if server is None:
        return
    existing = {(route.method, route.path) for route in server.routes}
    mask_route = '/zura/paintout/editor/import-review-mask'
    if ('GET', mask_route) not in existing:
        server.routes.get(mask_route)(import_review_mask_route)
    for suffix, handler in (('review-import', review_import_route), ('accept-import-review', accept_import_review_route)):
        path = '/zura/paintout/editor/' + suffix
        if ('POST', path) not in existing:
            server.routes.post(path)(handler)
