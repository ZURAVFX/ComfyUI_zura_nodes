"""Validate the owned files of a bounded HDR outpaint before publication."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import zipfile

from .enhancement import inspect_video


def _owned_file(root, ref, subfolder, filename_pattern):
    if not isinstance(ref, dict) or ref.get('type') != 'output':
        raise ValueError('The HDR render did not return an output file.')
    name, folder = ref.get('filename'), ref.get('subfolder', '')
    if (not isinstance(name, str) or Path(name).name != name or
            not isinstance(folder, str) or folder.replace('\\', '/') != subfolder or
            not re.fullmatch(filename_pattern, name)):
        raise ValueError('The HDR render returned an unexpected output path.')
    base = Path(root).resolve()
    candidate = base / subfolder / name
    if candidate.is_symlink():
        raise ValueError('The HDR render returned an unexpected output path.')
    path = candidate.resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError('The HDR render output is unavailable.')
    return path


def checked_stage(root, ref, identity, *, width, height, frames):
    if not isinstance(identity, str) or not identity.isalnum() or len(identity) > 64:
        raise ValueError('Invalid HDR outpaint job identity.')
    path = _owned_file(root, ref, 'genj/hdr_outpaint', re.escape(identity) + r'_\d{5}_\.mp4')
    inspect_video(path, expected_width=width, expected_height=height, expected_frames=frames, expected_fps=24)
    return path


def checked_delivery(root, outputs, identity, *, width, height, frames, has_audio):
    if not isinstance(identity, str) or not identity.isalnum() or len(identity) > 64:
        raise ValueError('Invalid HDR outpaint job identity.')
    if type(has_audio) is not bool or not isinstance(outputs, dict):
        raise ValueError('Invalid HDR delivery metadata.')
    prefix = 'hdr_outpaint_' + identity
    def ref(node, kind):
        entries = outputs.get(node, {}).get(kind, [])
        if not isinstance(entries, list) or len(entries) != 1:
            raise ValueError('The HDR render did not return its expected deliverables.')
        return entries[0]
    hlg = _owned_file(root, ref('zura_hdr_save_video', 'images'), 'genj/hdr', re.escape(prefix) + r'_\d{5}_\.mp4')
    preview = _owned_file(root, ref('zura_hdr_save_preview', 'images'), 'genj/hdr', re.escape(prefix) + r'_preview_\d{5}_\.mp4')
    archive = _owned_file(root, ref('zura_hdr_archive', 'files'), 'genj/hdr', re.escape(prefix) + r'\.zip')
    _check_media(hlg, preview, archive, width=width, height=height, frames=frames, has_audio=has_audio)
    return {'hlg': hlg, 'preview': preview, 'exr': archive}


def checked_long_delivery(root, result, identity, *, width, height, frames, has_audio):
    """Verify all files belong to the conversion and match the reviewed delivery."""
    if not isinstance(identity, str) or not identity.isalnum() or len(identity) > 64:
        raise ValueError('Invalid HDR outpaint job identity.')
    if type(has_audio) is not bool or not isinstance(result, dict):
        raise ValueError('Invalid HDR delivery metadata.')
    prefix = 'hdr_outpaint_' + identity
    files, preview_path = result.get('files'), result.get('preview')
    if not isinstance(files, list) or len(files) != 2 or not isinstance(preview_path, str):
        raise ValueError('The long HDR render did not return its expected deliverables.')
    root_path = Path(root).resolve()
    def owned(path, expected):
        if not isinstance(path, str):
            raise ValueError('The HDR render returned an unexpected output path.')
        candidate = Path(path)
        if candidate.is_symlink() or candidate.name != expected or candidate.parent.resolve() != root_path / 'genj' / 'hdr':
            raise ValueError('The HDR render returned an unexpected output path.')
        return _owned_file(root_path, {'type': 'output', 'subfolder': 'genj/hdr', 'filename': expected},
                           'genj/hdr', re.escape(expected))
    exr = owned(files[0], prefix + '.zip')
    hlg = owned(files[1], prefix + '.mp4')
    preview = owned(preview_path, prefix + '_preview.mp4')
    _check_media(hlg, preview, exr, width=width, height=height, frames=frames, has_audio=has_audio)
    return {'hlg': hlg, 'preview': preview, 'exr': exr}


def _check_media(hlg, preview, archive, *, width, height, frames, has_audio):
    for path in (hlg, preview):
        inspect_video(path, expected_width=width, expected_height=height, expected_frames=frames,
                      expected_fps=24, expected_audio_tracks=int(has_audio))
    executable = shutil.which('ffprobe')
    if not executable:
        raise ValueError('FFprobe is required to verify the HDR video.')
    try:
        result = subprocess.run([executable, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
            'stream=pix_fmt,color_space,color_transfer,color_primaries', '-of', 'json', str(hlg)],
            capture_output=True, text=True, check=True, timeout=30)
        streams = json.loads(result.stdout)['streams']
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        raise ValueError('Could not verify the HDR video colour metadata.') from exc
    if len(streams) != 1 or streams[0].get('color_transfer') != 'arib-std-b67' or streams[0].get('color_primaries') != 'bt2020' or streams[0].get('color_space') != 'bt2020nc' or '10' not in streams[0].get('pix_fmt', ''):
        raise ValueError('The video is not tagged as 10-bit Rec.2020 HLG.')
    try:
        with zipfile.ZipFile(archive) as z:
            expected = [f'frame_{i:05d}.exr' for i in range(frames)]
            if sorted(z.namelist()) != expected or any(item.file_size <= 0 for item in z.infolist()):
                raise ValueError('The HDR EXR archive has an unexpected frame sequence.')
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError('The HDR EXR archive could not be read.') from exc
