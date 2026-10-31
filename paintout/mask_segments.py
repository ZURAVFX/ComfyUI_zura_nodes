"""Independent, immutable mask sources with reversible timeline ranges."""
import copy
import secrets
import shutil
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


def segments_for(manifest):
    if not manifest:
        return []
    if 'segments' in manifest:
        return copy.deepcopy(manifest['segments'])
    files = manifest.get('files', {})
    if not files:
        return []
    frames = sorted(map(int, files))
    return [dict(id='legacy', name='Original mask', files=dict(files), start=frames[0],
                 end=frames[-1], available_start=frames[0], available_end=frames[-1], tracked=True)]


def _tracked_files(project, manifest, segment):
    """Recover old projects from immutable tracked passes, never a corrected union."""
    if 'tracked_files' in segment:
        return dict(segment['tracked_files'])
    baseline = {}
    if project and segment.get('tracked'):
        from . import editor_store as store
        for entry in reversed(store._read(project).get('mask_history', [])):
            if entry['revision'] > manifest['revision']:
                continue
            metadata = entry.get('metadata', {})
            same = metadata.get('segment_id') == segment['id']
            legacy = segment['id'] == 'legacy' and not metadata.get('segment_id')
            tracked = metadata.get('tracked') or (legacy and entry.get('end_frame', 0) > entry.get('start_frame', 0) and not metadata.get('manual_correction'))
            if not (same or legacy) or not tracked:
                continue
            old = store._mask_manifest(project, entry['revision'])
            previous = next((item for item in segments_for(old) if item['id'] == segment['id']), None)
            if previous:
                for key, path in previous['files'].items():
                    if entry['start_frame'] <= int(key) <= entry['end_frame']:
                        baseline.setdefault(key, path)
    # Old drafts with no original tracking pass cannot invent a recoverable edit.
    return baseline or dict(segment['files'])


def summaries(manifest, project=None):
    result = []
    for segment in segments_for(manifest):
        summary = {k: v for k, v in segment.items() if k not in ('files', 'tracked_files')}
        baseline = _tracked_files(project, manifest, segment)
        summary['correction_frames'] = sorted(int(key) for key, path in segment['files'].items()
                                              if segment.get('tracked') and key in baseline and path != baseline[key])
        result.append(summary)
    return result


def read_segment(project, segment_id, frame, revision=None, grow=0):
    from . import editor_store as store
    manifest = store._mask_manifest(project, revision)
    if manifest is None or not 0 <= frame < manifest['source_count']:
        raise ValueError('Choose a frame inside this mask project.')
    segment = next((s for s in segments_for(manifest) if s['id'] == segment_id), None)
    if segment is None:
        raise ValueError('This mask segment no longer exists. Select another bar.')
    path = segment['files'].get(str(frame)) if segment['start'] <= frame <= segment['end'] else None
    mask = store._load_mask(path, manifest['width'], manifest['height'])
    protected = store._load_mask(manifest.get('protection_files', {}).get(str(frame)), manifest['width'], manifest['height'])
    return store.effective_mask(mask, grow, 0, protected)


def read_other_segments(project, selected, frame, revision=None, grow=0):
    from . import editor_store as store
    manifest = store._mask_manifest(project, revision)
    if manifest is None or not 0 <= frame < manifest['source_count']:
        raise ValueError('Choose a frame inside this mask project.')
    union = np.zeros((manifest['height'], manifest['width']), np.float32)
    for segment in segments_for(manifest):
        if segment['id'] != selected and segment.get('tracked') and segment['start'] <= frame <= segment['end']:
            union = np.maximum(union, store._load_mask(segment['files'].get(str(frame)), manifest['width'], manifest['height']))
    protected = store._load_mask(manifest.get('protection_files', {}).get(str(frame)), manifest['width'], manifest['height'])
    return store.effective_mask(union, grow, 0, protected)


def _publish(project, manifest, segments, expected, metadata, seed_masks=None, affected=None):
    from . import editor_store as store
    # Include prior covered frames as explicit black frames after shortening/removing
    # a bar. This preserves render coverage without extending unknown footage.
    covered = set(manifest.get('files', {})) if manifest else set()
    for segment in segments:
        covered.update(segment['files'])
    if affected is not None:
        covered = set(map(str, affected))
    if not covered:
        raise ValueError('There are no mask frames to save.')
    identity = manifest['source']
    with tempfile.TemporaryDirectory(prefix='pending_union_', dir=store.project_dir(project)) as pending:
        combined = {}
        for key in sorted(covered, key=int):
            frame = int(key)
            union = np.zeros((identity['height'], identity['width']), np.float32)
            for segment in segments:
                if segment.get('tracked') and segment['start'] <= frame <= segment['end']:
                    union = np.maximum(union, store._load_mask(segment['files'].get(key), identity['width'], identity['height']))
            path = Path(pending) / (key + '.png')
            Image.fromarray(np.round(union.clip(0, 1) * 255).astype(np.uint8)).save(path)
            combined[frame] = str(path)
        return store.commit_mask_pass(project, identity, combined, 'replace', expected, metadata,
                                      preserve_protection=True, segments=segments, seed_masks=seed_masks)


def commit_segment(project, identity, frame_masks, operation, expected, metadata):
    from . import editor_store as store
    segment_id = metadata.get('segment_id')
    if segment_id != 'legacy' and (not isinstance(segment_id, str) or not store._ID.fullmatch(segment_id)):
        raise ValueError('Choose a valid mask segment.')
    if not frame_masks:
        raise ValueError('The mask segment has no frames.')
    with store._LOCK:
        document = store._read(project)
        store._expect(document, expected)
        manifest = store._mask_manifest(project)
        if manifest and manifest['source'] != identity:
            raise ValueError('The source changed. Reload the shot before editing masks.')
        segments = segments_for(manifest)
        segment = next((s for s in segments if s['id'] == segment_id), None)
        if segment is None:
            if segment_id == 'legacy':
                raise ValueError('The original mask no longer exists.')
            segment = dict(id=segment_id, name=f'Mask {len(segments)+1}', files={}, tracked=False)
            segments.append(segment)
        segment['tracked_files'] = _tracked_files(project, manifest, segment) if manifest else {}
        # Raw incoming sources are retained separately from the union forever.
        owned = store.project_dir(project) / 'segment_sources' / secrets.token_hex(12)
        owned.mkdir(parents=True)
        try:
            for frame, mask in sorted(frame_masks.items()):
                if segment.get('tracked') and not segment['start'] <= frame <= segment['end']:
                    raise ValueError('Move inside this mask bar before correcting it.')
                if isinstance(frame, bool) or not isinstance(frame, int) or not 0 <= frame < identity['count']:
                    raise ValueError('A mask frame is outside the source footage.')
                incoming = store._load_mask(mask, identity['width'], identity['height']) if isinstance(mask, (str, Path)) else np.asarray(mask)
                previous = store._load_mask(segment['files'].get(str(frame)), identity['width'], identity['height'])
                # Adding a new segment adds its union to the shot, never unions
                # the selected object's seed with another object's mask.
                value = store.merge_mask(previous, incoming, 'replace' if operation == 'add' else operation)
                path = owned / f'{frame:08d}.png'
                Image.fromarray(np.round(value * 255).astype(np.uint8)).save(path)
                segment['files'][str(frame)] = str(path)
                if metadata.get('tracked'):
                    segment['tracked_files'][str(frame)] = str(path)
            available = sorted(map(int, segment['files']))
            segment.update(available_start=available[0], available_end=available[-1])
            if (metadata.get('tracked') and not segment['tracked']) or 'start' not in segment:
                segment.update(start=available[0], end=available[-1])
            segment['tracked'] = segment['tracked'] or bool(metadata.get('tracked'))
            base = manifest or dict(source=identity, files={})
            summary = _publish(project, base, segments, expected, metadata, seed_masks=frame_masks, affected=frame_masks)
            summary['segment_id'] = segment_id
            return summary
        except BaseException:
            shutil.rmtree(owned, ignore_errors=True)
            raise


def edit_segment(body):
    from . import editor_store as store
    project, segment_id = body['project'], body['segment_id']
    with store._LOCK:
        document = store._read(project)
        expected = body.get('expected_revision')
        if expected is None or isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ValueError('Save the mask range with its current project revision.')
        store._expect(document, expected)
        manifest = store._mask_manifest(project)
        if not manifest:
            raise ValueError('Track a mask before trimming it.')
        from .browser import checked_path
        from .paintout import describe
        source = checked_path(manifest['source']['path'])
        if store.source_identity(str(source), describe(str(source))) != manifest['source']:
            raise ValueError('The source changed. Reload the shot before trimming masks.')
        segments = segments_for(manifest)
        segment = next((s for s in segments if s['id'] == segment_id), None)
        if segment is None:
            raise ValueError('This mask segment no longer exists.')
        if body.get('delete') is True:
            segments.remove(segment)
        elif 'reset_frame' in body:
            frame = body['reset_frame']
            if isinstance(frame, bool) or not isinstance(frame, int) or not segment.get('tracked') or not segment['start'] <= frame <= segment['end']:
                raise ValueError('Choose an edited frame inside this tracked mask.')
            baseline = _tracked_files(project, manifest, segment)
            key = str(frame)
            if key not in baseline or segment['files'].get(key) == baseline[key]:
                raise ValueError('This frame has no saved correction to reset.')
            segment['tracked_files'] = baseline
            segment['files'][key] = baseline[key]
        else:
            start, end = body.get('start'), body.get('end')
            if any(isinstance(v, bool) or not isinstance(v, int) for v in (start, end)) or not segment['available_start'] <= start <= end <= segment['available_end']:
                raise ValueError('Trim inside the tracked frames. Extend tracking to cover new frames.')
            segment.update(start=start, end=end)
        _publish(project, manifest, segments, expected, {'method': 'segment_range', 'segment_id': segment_id}, affected=segment['files'])
        return store.project_response(store._read(project))
