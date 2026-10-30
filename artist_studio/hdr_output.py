"""Resolve an explicitly selected local output video for HDR conversion."""
from pathlib import Path


def selected_output(root, ref):
    if not isinstance(ref, dict) or ref.get('type') != 'output':
        raise ValueError('Choose an available output video.')
    filename, subfolder = ref.get('filename'), ref.get('subfolder', '')
    if (not isinstance(filename, str) or not filename or Path(filename).name != filename
            or not isinstance(subfolder, str)):
        raise ValueError('Choose an available output video.')
    base = Path(root).resolve()
    path = (base / subfolder / filename).resolve()
    if not path.is_relative_to(base) or not path.is_file() or path.suffix.lower() not in ('.mp4', '.mov', '.mkv', '.webm'):
        raise ValueError('The selected output video is unavailable.')
    return path
