"""User-uploaded EXR sequences for the bounded LTX HDR preview."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import uuid
from pathlib import Path

MAX_FILES = 2000
MAX_FILE_BYTES = 2 * 1024**3
MAX_TOTAL_BYTES = 20 * 1024**3
_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 _().-]{0,199}\.exr$', re.IGNORECASE)


def native_input_colour(colour):
    """Resolve input interpretation separately from retained capture identity."""
    from ..comfylink import float_io
    from ..comfylink.display_view import _verified_ocio_source
    colour=float_io.validate_colour(colour)
    managed=colour.get('management')=='ocio'
    encoding=_verified_ocio_source(colour) if managed else colour['encoding']
    spaces={'acescg':'acescg','acescct':'acescct','scene_linear_rec709':'linear_rec709'}
    if encoding not in spaces:
        if managed:raise ValueError('The verified AE working space is not a supported native HDR input.')
        return None
    result={'encoding':encoding,'sceneLinear':encoding!='acescct',
        'source':'verified_ae_ocio' if managed else 'declared_exr',
        'sourceColourSha256':hashlib.sha256(float_io.canonical_manifest_bytes(colour)).hexdigest()}
    if managed:result['ocioConfigFileSha256']=colour['ocioConfigFileSha256']
    return result


def discover_colour(files,cancel=None):
    """Read embedded declarations from every header without rewriting a frame.

    Ordinary EXRs retain their existing explicit-interpretation behaviour. An
    embedded AE identity must be complete and identical throughout the sequence.
    """
    import OpenImageIO as oiio
    from ..comfylink import float_io
    found=[]
    for path in files:
        if cancel is not None and cancel.is_set():raise ValueError('EXR source inspection was cancelled.')
        reader=oiio.ImageInput.open(str(path))
        if reader is None:raise ValueError('An uploaded EXR header could not be read.')
        try:
            value=reader.spec().getattribute('comfylink:colour')
            if value is None:found.append(None);continue
            if not isinstance(value,str) or len(value.encode('utf-8'))>32768:raise ValueError('The embedded EXR colour identity is invalid or too large.')
            try:colour=json.loads(value,object_pairs_hook=float_io._json_pairs)
            except (ValueError,TypeError):raise ValueError('The embedded EXR colour identity is invalid.') from None
            found.append(float_io.validate_colour(colour))
        finally:reader.close()
    if not any(value is not None for value in found):return {}
    if any(value is None for value in found) or any(value!=found[0] for value in found):
        if any(value is not None and value.get('management')=='ocio' for value in found):
            raise ValueError('The embedded source colour identity differs between EXR frames.')
        return {}
    mapped=native_input_colour(found[0])
    if mapped is None:return {}
    return {'nativeInputColour':mapped,'resolved_colour':{'scene_linear_rec709':'linear_rec709'}.get(mapped['encoding'],mapped['encoding'])}


def _sha(path,cancel=None):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            if cancel is not None and cancel.is_set():raise ValueError('EXR source inspection was cancelled.')
            digest.update(block)
    return digest.hexdigest()


def validate_manifest(manifest, expected_sha, start, count,cancel=None):
    """Validate manifest and selected frames again immediately before decode."""
    manifest = Path(manifest).resolve()
    import folder_paths
    root = (Path(folder_paths.get_input_directory()) / 'genj_studio').resolve()
    if not manifest.is_relative_to(root) or manifest.name != 'hdr_sequence.json' or _sha(manifest,cancel) != expected_sha:
        raise ValueError('The EXR sequence manifest changed. Upload the sequence again.')
    data = json.loads(manifest.read_text(encoding='utf8'))
    entries = data.get('frames')
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_FILES or type(start) is not int or type(count) is not int or start < 0 or count < 1 or start + count > len(entries):
        raise ValueError('Choose a valid EXR frame range.')
    directory = (manifest.parent / 'frames').resolve()
    if directory.parent != manifest.parent:
        raise ValueError('Invalid EXR sequence location.')
    expected_names = [entry.get('name') if isinstance(entry, dict) else None for entry in entries]
    if any(not isinstance(name, str) or not _NAME.fullmatch(name) for name in expected_names) or len({name.casefold() for name in expected_names}) != len(expected_names):
        raise ValueError('Invalid EXR frame names.')
    actual_paths = list(directory.iterdir())
    actual_names = [path.name for path in actual_paths]
    if any(path.is_symlink() or not path.is_file() for path in actual_paths) or len(actual_names) != len(expected_names) or set(actual_names) != set(expected_names):
        raise ValueError('The EXR sequence changed. Upload it again.')
    for entry in entries[start:start + count]:
        name = entry.get('name') if isinstance(entry, dict) else None
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError('Invalid EXR frame name.')
        path = (directory / name).resolve()
        if path.parent != directory or not path.is_file() or _sha(path,cancel) != entry.get('sha256'):
            raise ValueError('An EXR frame changed. Upload the sequence again.')
    return directory, entries


def register(studio, routes, response):
    from aiohttp import web
    import folder_paths
    from ..paintout.paintout import describe, natural

    @routes.post('/zura/studio/hdr/exr-sequence')
    @routes.post('/genj/studio/hdr/exr-sequence')
    @response
    async def upload(request):
        from ..media_source import require_same_origin
        from .media_import import _request_fence,_request_work
        require_same_origin(request);cancel=threading.Event()
        reader = await request.multipart()
        identity = uuid.uuid4().hex
        root = (Path(folder_paths.get_input_directory()) / 'genj_studio').resolve()
        directory = root / identity
        frames = directory / 'frames'
        frames.mkdir(parents=True, exist_ok=False)
        entries, names, total = [], set(), 0
        try:
            while (part := await reader.next()) is not None:
                if not part.filename:
                    raise ValueError('Choose one or more EXR frames.')
                # Keep only a safe basename; never honour browser-provided paths.
                name = str(part.filename).replace('\\', '/').rsplit('/', 1)[-1]
                if not _NAME.fullmatch(name) or name.casefold() in names:
                    raise ValueError('EXR frame names must be unique and contain only letters, digits, spaces, dots, dashes or underscores.')
                if len(entries) >= MAX_FILES:
                    raise ValueError(f'Choose at most {MAX_FILES} EXR frames.')
                names.add(name.casefold()); file = frames / name; digest = hashlib.sha256(); size = 0
                with file.open('xb') as stream:
                    while chunk := await part.read_chunk(size=1024 * 1024):
                        _request_fence(request,cancel)
                        size += len(chunk); total += len(chunk)
                        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                            raise ValueError('The EXR sequence exceeds the upload size limit.')
                        digest.update(chunk); stream.write(chunk)
                with file.open('rb') as stream:
                    if stream.read(4) != b'\x76\x2f\x31\x01':
                        raise ValueError('One selected file is not a valid OpenEXR frame.')
                entries.append({'name': name, 'sha256': digest.hexdigest()})
            if not entries:
                raise ValueError('Choose one or more EXR frames.')
            entries.sort(key=lambda item: natural(item['name']))
            # Validate the first frame is decodable before accepting the asset.
            info = await _request_work(request,lambda:describe(str(frames),cancel=cancel),cancel)
            if info['count'] != len(entries):
                raise ValueError('The uploaded EXR sequence is incomplete.')
            colour=await _request_work(request,lambda:discover_colour([frames/entry['name'] for entry in entries],cancel),cancel)
            manifest = directory / 'hdr_sequence.json'
            manifest.write_text(json.dumps({'frames':entries}, separators=(',',':')), encoding='utf8')
            asset = {'id':identity, 'kind':'asset', 'asset_kind':'hdr_sequence',
                     'file':f'genj_studio/{identity}/hdr_sequence.json', 'sha':_sha(manifest),
                     'name':f'{len(entries)} EXR frames', 'count':len(entries),
                     'width':info['width'], 'height':info['height']}
            asset.update(colour)
            _request_fence(request,cancel)
            studio.store.save(asset)
            return web.json_response(asset)
        except BaseException:
            # Only the fresh UUID directory created above is disposable.
            if directory.parent == root and directory.name == identity:
                shutil.rmtree(directory, ignore_errors=True)
            raise
