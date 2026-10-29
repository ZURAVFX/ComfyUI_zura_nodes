"""Package one completed LTX HDR EXR sequence for convenient download."""
from __future__ import annotations

import re
import uuid
import zipfile
from pathlib import Path

from .model_downloads import _publish_verified


def preflight_archive(output_root):
    """Check safe no-overwrite publication before running the model."""
    parent=Path(output_root)/'genj'/'hdr'
    parent.mkdir(parents=True,exist_ok=True)
    name=uuid.uuid4().hex
    source=parent/('.zura-hdr-'+name+'.probe')
    destination=parent/('.zura-hdr-'+name+'.probe-published')
    try:
        source.touch(exist_ok=False)
        _publish_verified(source,destination)
    except OSError as exc:
        raise ValueError('This output folder cannot safely save an EXR ZIP without overwriting. Choose another ComfyUI output folder.') from exc
    finally:
        source.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)


def package_sequence(output_root, prefix, count):
    if not isinstance(prefix, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', prefix):
        raise ValueError('Invalid HDR output name.')
    if type(count) is not int or not 1 <= count <= 121:
        raise ValueError('Invalid HDR sequence frame count.')
    parent=(Path(output_root)/'genj'/'hdr').resolve()
    directory=(parent/prefix).resolve()
    if directory.parent != parent or not directory.is_dir():
        raise ValueError('HDR sequence folder is missing or invalid.')
    files=[]
    for index in range(count):
        path=directory/f'frame_{index:05d}.exr'
        if path.is_symlink() or not path.is_file() or path.parent.resolve()!=directory:
            raise ValueError(f'HDR output frame {index} is missing.')
        files.append(path)
    destination=parent/(prefix+'.zip')
    temporary=parent/('.'+uuid.uuid4().hex+'.partial')
    try:
        with zipfile.ZipFile(temporary, mode='x', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for file in files: archive.write(file, arcname=file.name)
        # Refuse to replace any prior deliverable.
        _publish_verified(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


class ZuraHDRPackageEXR:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'images':('IMAGE',), 'prefix':('STRING',{'default':''})}}
    RETURN_TYPES=('STRING',)
    RETURN_NAMES=('archive',)
    OUTPUT_NODE=True
    FUNCTION='package'
    CATEGORY='Zura/Artist Studio'
    def package(self, images, prefix):
        import folder_paths
        path=package_sequence(folder_paths.get_output_directory(), prefix, len(images))
        return {'ui':{'files':[{'filename':path.name,'subfolder':'genj/hdr','type':'output'}]},
                'result':(str(path),)}


NODE_CLASS_MAPPINGS={'ZuraHDRPackageEXR':ZuraHDRPackageEXR}
NODE_DISPLAY_NAME_MAPPINGS={'ZuraHDRPackageEXR':'Zura · Package HDR EXR Sequence'}
