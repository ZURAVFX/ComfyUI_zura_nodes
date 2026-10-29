"""User-uploaded EXR sequences for the bounded LTX HDR preview."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

MAX_FILES = 2000
MAX_FILE_BYTES = 2 * 1024**3
MAX_TOTAL_BYTES = 20 * 1024**3
_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 _().-]{0,199}\.exr$', re.IGNORECASE)


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_manifest(manifest, expected_sha, start, count):
    """Validate manifest and selected frames again immediately before decode."""
    manifest = Path(manifest).resolve()
    import folder_paths
    root = (Path(folder_paths.get_input_directory()) / 'genj_studio').resolve()
    if not manifest.is_relative_to(root) or manifest.name != 'hdr_sequence.json' or _sha(manifest) != expected_sha:
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
        if path.parent != directory or not path.is_file() or _sha(path) != entry.get('sha256'):
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
            info = describe(str(frames))
            if info['count'] != len(entries):
                raise ValueError('The uploaded EXR sequence is incomplete.')
            manifest = directory / 'hdr_sequence.json'
            manifest.write_text(json.dumps({'frames':entries}, separators=(',',':')), encoding='utf8')
            asset = {'id':identity, 'kind':'asset', 'asset_kind':'hdr_sequence',
                     'file':f'genj_studio/{identity}/hdr_sequence.json', 'sha':_sha(manifest),
                     'name':f'{len(entries)} EXR frames', 'count':len(entries),
                     'width':info['width'], 'height':info['height']}
            studio.store.save(asset)
            return web.json_response(asset)
        except Exception:
            # Only the fresh UUID directory created above is disposable.
            if directory.parent == root and directory.name == identity:
                shutil.rmtree(directory, ignore_errors=True)
            raise
