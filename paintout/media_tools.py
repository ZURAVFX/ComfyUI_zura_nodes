"""Find existing media tools, including a File Explorer-only portable setup."""
from pathlib import Path
import os
import shutil


def find_media_tool(name, comfy_root=None):
    if name not in ('ffmpeg', 'ffprobe'):
        raise ValueError('Unsupported media tool.')
    installed = shutil.which(name)
    if installed:
        return installed
    if comfy_root is None:
        import folder_paths
        comfy_root = folder_paths.base_path
    root = Path(comfy_root)
    filename = name + ('.exe' if os.name == 'nt' else '')
    for directory in (root / 'ffmpeg' / 'bin', root / 'ffmpeg', root / 'bin', root):
        candidate = directory / filename
        if candidate.is_file() and (os.name == 'nt' or os.access(candidate, os.X_OK)):
            return str(candidate)
    raise FileNotFoundError(
        f'{name} is missing. Copy ffmpeg and ffprobe from an FFmpeg build into '
        f'{root / "ffmpeg" / "bin"} using your file browser. '
        'No terminal or PATH change is required. See the Paintout setup guide.')
