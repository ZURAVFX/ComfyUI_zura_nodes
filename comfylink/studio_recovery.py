"""Find retained single-image results for the exact captured AE source.

History and asset labels convey no authority. Both staged source transfers are
verified from their private files before an output is offered for review.
Nothing here queues a prompt, transfers a result or modifies an original.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
from fractions import Fraction
import zlib

from PIL import Image

from . import float_io
from .frame_contract import normalise_frame_contract

MAX_HISTORY = 100
MAX_CANDIDATES = 8
MAX_SOURCE_CHECKS = 8
MAX_IMAGE_BYTES = 128 * 1024 * 1024
MAX_SCAN_ENTRIES_PER_ROOT = 8192
MAX_SCAN_DIRECTORIES = 64
MAX_SCAN_DEPTH = 3
MAX_METADATA_READS = 32
MAX_PROMPT_BYTES = 1024 * 1024
MAX_PNG_CHUNKS = 4096
_IMAGE_ROOTS = ('zura_images', 'ZURA STUDIO/images')
_SESSION = re.compile(r"[a-f0-9]{32}\Z")


def _source_matches_contract(manifest, contract):
    return (contract['frameCount'] == contract['modelFrames'] == contract['trimFrames'] == 1
            and contract['width'] == manifest['width'] and contract['height'] == manifest['height']
            and Fraction(contract['frameRate']['numerator'], contract['frameRate']['denominator'])
            == Fraction(manifest['frameRate']['numerator'], manifest['frameRate']['denominator']))


def _image_contract(entry):
    if not isinstance(entry, dict):
        return None
    status, prompt = entry.get('status'), entry.get('prompt')
    if (not isinstance(status, dict) or status.get('completed') is not True
            or status.get('status_str') != 'success' or not isinstance(prompt, (list, tuple))
            or len(prompt) < 4 or not isinstance(prompt[2], dict) or len(prompt[2]) > 256
            or not isinstance(prompt[3], dict) or prompt[3].get('zura_image') is not True
            or 'ae_intermediate_image' in prompt[3]):
        return None
    raw = prompt[3].get('ae_frame_contract')
    if not isinstance(raw, dict) or 'ae_intermediate_image' in raw:
        return None
    return _graph_contract(prompt[2], raw)


def _graph_contract(graph, expected=None):
    """Inspect a native final-image guard; PNG metadata is only a locator."""
    if not isinstance(graph, dict) or not 1 <= len(graph) <= 256:
        return None
    # Native Image's actual final SaveImage must go through its AE frame guard.
    # Other graph branches and edited video guides are not final image results.
    save = graph.get('save')
    if (not isinstance(save, dict) or save.get('class_type') != 'SaveImage'
            or isinstance(save.get('_meta'), dict) and 'ae_intermediate_image' in save['_meta']):
        return None
    saver_inputs = save.get('inputs')
    if not isinstance(saver_inputs, dict):
        return None
    edge = saver_inputs.get('images')
    if not isinstance(edge, (list, tuple)) or len(edge) != 2 or type(edge[1]) is not int or edge[1] != 0 or not isinstance(edge[0], str):
        return None
    guard = graph.get(edge[0])
    if not isinstance(guard, dict) or guard.get('class_type') != 'ZuraComfyLinkMatchFrames':
        return None
    inputs = guard.get('inputs')
    if not isinstance(inputs, dict) or type(inputs.get('frame_count')) is not int or inputs['frame_count'] != 1:
        return None
    metadata = inputs.get('metadata')
    if not isinstance(metadata, str) or len(metadata) > 4096:
        return None
    try:
        decoded = json.loads(metadata, object_pairs_hook=float_io._json_pairs)
        if not isinstance(decoded, dict) or 'ae_intermediate_image' in decoded:
            return None
        contract = normalise_frame_contract(decoded)
        if (expected is not None and normalise_frame_contract(expected) != contract
                or contract['frameCount'] != contract['modelFrames'] or contract['frameCount'] != 1
                or type(inputs.get('width')) is not int or inputs['width'] != contract['width']
                or type(inputs.get('height')) is not int or inputs['height'] != contract['height']):
            return None
    except (ValueError, TypeError, KeyError, RecursionError):
        return None
    return contract


def _png_prompt(path, expected_stamp):
    """Read only bounded, uncompressed native SaveImage prompt JSON.

    Do not use Pillow's text decoder for discovery: compressed metadata can
    expand independently of the encoded file size. Native SaveImage uses tEXt.
    Full PNG/container/pixel checks still run before a candidate is published.
    """
    with float_io._locked_parents(path.parent):
        before = float_io._safe_stat(path)
        if _stamp(before) != expected_stamp or not 0 < before.st_size <= MAX_IMAGE_BYTES:
            raise ValueError('Saved PNG changed before metadata inspection')
        prompt = None
        with path.open('rb') as stream:
            if stream.read(8) != b'\x89PNG\r\n\x1a\n':
                raise ValueError('Not a native PNG')
            for _ in range(MAX_PNG_CHUNKS):
                header = stream.read(8)
                if len(header) != 8:
                    raise ValueError('Truncated PNG metadata')
                length, kind = int.from_bytes(header[:4], 'big'), header[4:]
                start = stream.tell()
                if start + length + 4 > before.st_size:
                    raise ValueError('PNG chunk exceeds file')
                if kind in (b'tEXt', b'zTXt', b'iTXt'):
                    key = stream.read(min(length, 80)).split(b'\0', 1)[0]
                    if key == b'prompt':
                        if kind != b'tEXt' or prompt is not None or not 7 < length <= MAX_PROMPT_BYTES + 7:
                            raise ValueError('Unsupported or oversized saved prompt')
                        stream.seek(start)
                        encoded = stream.read(length)
                        crc = stream.read(4)
                        if len(encoded) != length or len(crc) != 4 or zlib.crc32(kind+encoded) & 0xffffffff != int.from_bytes(crc, 'big'):
                            raise ValueError('Saved prompt checksum differs')
                        if not encoded.startswith(b'prompt\0'):
                            raise ValueError('Invalid saved prompt')
                        prompt = json.loads(encoded[7:].decode('utf-8'), object_pairs_hook=float_io._json_pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite saved prompt')))
                stream.seek(start + length + 4)
                if kind == b'IEND':
                    if length != 0 or stream.tell() != before.st_size:
                        raise ValueError('Invalid PNG end')
                    break
            else:
                raise ValueError('Too many PNG chunks')
        if _stamp(float_io._safe_stat(path)) != expected_stamp:
            raise ValueError('Saved PNG changed during metadata inspection')
        return prompt


def _matches_saver_prefix(graph, ref):
    prefix = graph.get('save', {}).get('inputs', {}).get('filename_prefix')
    if (not isinstance(prefix, str) or not 1 <= len(prefix) <= 255 or prefix.startswith('/')
            or any(c in prefix for c in '\\:\0%') or any(part in ('', '.', '..') for part in prefix.split('/'))):
        return False
    parent, separator, basename = prefix.rpartition('/')
    if not separator or parent != ref['subfolder'] or not any(parent == root or parent.startswith(root+'/') for root in _IMAGE_ROOTS):
        return False
    return re.fullmatch(re.escape(basename)+r'_[0-9]{5,10}_\.png', ref['filename']) is not None


def _saved_png_entries(output_root):
    """Bound directory enumeration and inspect only the newest native images."""
    root = Path(output_root).absolute()
    newest = []
    for native in _IMAGE_ROOTS:
        pending, directories, examined = [(root/native, 0)], 0, 0
        while pending and directories < MAX_SCAN_DIRECTORIES and examined < MAX_SCAN_ENTRIES_PER_ROOT:
            folder, depth = pending.pop(0); directories += 1
            try:
                with float_io._locked_parents(folder):
                    float_io._safe_stat(folder, True)
                    with os.scandir(folder) as entries:
                        for entry in entries:
                            if examined >= MAX_SCAN_ENTRIES_PER_ROOT:
                                break
                            examined += 1
                            path = Path(entry.path)
                            if entry.is_dir(follow_symlinks=False):
                                if depth < MAX_SCAN_DEPTH:
                                    try:
                                        float_io._safe_stat(path, True)
                                        pending.append((path, depth+1))
                                    except (ValueError, OSError):
                                        pass
                            elif path.suffix.lower() == '.png':
                                try:
                                    stat = float_io._safe_stat(path)
                                    if 0 < stat.st_size <= MAX_IMAGE_BYTES:
                                        newest.append((stat.st_mtime_ns, path, _stamp(stat)))
                                except (ValueError, OSError):
                                    pass
            except (ValueError, OSError):
                continue
    newest.sort(key=lambda item:item[0], reverse=True)
    for _, path, stamp in newest[:MAX_METADATA_READS]:
        try:
            graph = _png_prompt(path, stamp)
            contract = _graph_contract(graph)
            ref = {'filename': path.name, 'subfolder': path.parent.relative_to(root).as_posix(), 'type': 'output'}
            if contract is not None and _matches_saver_prefix(graph, ref):
                yield contract, ref, stamp
        except (ValueError, OSError, UnicodeError, RecursionError):
            continue


def _stamp(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _retained_png(record, manifest, resolve_master, inspect_png, expected_stamp=None):
    if not isinstance(record, dict) or record.get('type') != 'output':
        raise ValueError('Expected an output image')
    # ComfyUI 0.45 adds asset ID and display metadata. Never forward those as
    # transfer authority, and do not mutate the history record containing them.
    ref = {key: record.get(key, '') for key in ('filename', 'subfolder', 'type')}
    if not isinstance(ref['filename'], str) or Path(ref['filename']).suffix.lower() != '.png':
        raise ValueError('Only native PNG image results can be recovered here')
    path = resolve_master(ref)
    with float_io._locked_parents(path.parent):
        before = float_io._safe_stat(path)
        if expected_stamp is not None and _stamp(before) != expected_stamp:
            raise ValueError('Saved PNG changed after its source locator was read')
        if not 0 < before.st_size <= MAX_IMAGE_BYTES:
            raise ValueError('Retained image exceeds its bounded size')
        inspect_png(path)
        with Image.open(path) as image:
            if (image.format != 'PNG' or image.size != (manifest['width'], manifest['height'])
                    or image.mode not in {'RGB', 'RGBA', 'P', 'L', 'LA'} or getattr(image, 'n_frames', 1) != 1):
                raise ValueError('Retained image does not match the captured raster')
            image.verify()
        sha = hashlib.sha256()
        size = 0
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                size += len(chunk)
                if size > before.st_size or size > MAX_IMAGE_BYTES:
                    raise ValueError('Retained image changed during inspection')
                sha.update(chunk)
        if size != before.st_size or _stamp(float_io._safe_stat(path)) != _stamp(before):
            raise ValueError('Retained image changed during inspection')
    return ref, sha.hexdigest()


def retained_images(input_root, session_id, source_manifest, history, resolve_master, inspect_png, output_root=None):
    """Return at most eight reviewed candidates, newest first, without writes."""
    if not isinstance(session_id, str) or not _SESSION.fullmatch(session_id):
        raise ValueError('Invalid current source identity')
    source = float_io.validate_manifest(source_manifest)
    if len(source['frames']) != 1:
        return []
    current_path = 'ComfyLink/' + session_id + '/manifest.json'
    current = float_io.verify_transfer(input_root, current_path)
    canonical = float_io.canonical_manifest_bytes(source)
    if float_io.canonical_manifest_bytes(current) != canonical:
        raise ValueError('Current staged source differs from the authenticated capture')
    source_sha = hashlib.sha256(canonical).hexdigest()
    if not isinstance(history, dict):
        return []
    entries = list(history.items())[-MAX_HISTORY:]

    def order(pair):
        item = pair[1]
        prompt = item.get('prompt') if isinstance(item, dict) else None
        value = prompt[0] if isinstance(prompt, (list, tuple)) and prompt else -1
        return value if type(value) in (int, float) and math.isfinite(value) else -1

    entries.sort(key=order, reverse=True)
    verified = {session_id: True}
    checked, results, seen = 0, [], set()
    located = []
    for prompt_id, entry in entries:
        if not isinstance(prompt_id, str) or not 1 <= len(prompt_id) <= 128:
            continue
        contract = _image_contract(entry)
        if contract is None or not _source_matches_contract(source, contract):
            continue
        outputs = entry.get('outputs')
        images = outputs.get('save', {}).get('images') if isinstance(outputs, dict) and isinstance(outputs.get('save'), dict) else None
        if isinstance(images, list) and len(images) == 1:
            located.append((contract, images[0], None))
    # A restarted Comfy server has no execution history. A complete native PNG
    # can locate its old source, but cannot replace source-byte verification or
    # the user's separate review and Send action. Known failed history is never
    # promoted through this fallback.
    if not entries and output_root is not None:
        located = _saved_png_entries(output_root)
    for contract, record, expected_stamp in located:
        if not _source_matches_contract(source, contract):
            continue
        old_id = contract['sessionId']
        if not _SESSION.fullmatch(old_id):
            continue
        if old_id not in verified:
            verified[old_id] = False
            relative = 'ComfyLink/' + old_id + '/manifest.json'
            try:
                metadata = float_io.read_manifest(input_root, relative)
                if float_io.canonical_manifest_bytes(metadata) != canonical:
                    continue
                if checked >= MAX_SOURCE_CHECKS:
                    continue
                checked += 1
                old = float_io.verify_transfer(input_root, relative)
                verified[old_id] = float_io.canonical_manifest_bytes(old) == canonical
            except (ValueError, OSError):
                continue
        if not verified[old_id]:
            continue
        try:
            ref, image_sha = _retained_png(record, source, resolve_master, inspect_png, expected_stamp)
        except (ValueError, OSError, Image.DecompressionBombError):
            continue
        key = (ref['subfolder'], ref['filename'])
        if key in seen:
            continue
        seen.add(key)
        identity = hashlib.sha256(float_io.canonical_manifest_bytes({'file': ref,
            'imageSha256': image_sha, 'sourceManifestSha256': source_sha})).hexdigest()
        results.append({'id': identity, 'kind': 'image', 'master': ref, 'width': source['width'],
                        'height': source['height'], 'frameRate': source['frameRate'],
                        'sourceManifestSha256': source_sha, 'imageSha256': image_sha})
        if len(results) >= MAX_CANDIDATES:
            break
    # The matched source is still the same at publication time.
    if float_io.canonical_manifest_bytes(float_io.read_manifest(input_root, current_path)) != canonical:
        raise ValueError('The captured source changed during recovery inspection')
    return results
