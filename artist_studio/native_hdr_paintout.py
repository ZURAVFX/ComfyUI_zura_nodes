"""Native LTX repair input from a verified Studio EXR-sequence asset."""
import json
import math
from pathlib import Path


def native_paintout_source_info(asset, validate, describe_media, *, colour_space='auto', fps=None):
    if asset.get('asset_kind') != 'hdr_sequence':
        raise ValueError('Choose an uploaded EXR sequence')
    manifest = Path(validate(asset))
    entries = json.loads(manifest.read_text(encoding='utf8')).get('frames', [])
    if not entries or len(entries) != asset.get('count'):
        raise ValueError('The HDR sequence is incomplete')
    frames = manifest.parent / 'frames'
    for entry in entries:
        name = entry.get('name', '')
        if not name or Path(name).name != name or '/' in name or '\\' in name or not (frames/name).is_file():
            raise ValueError('The HDR sequence has a missing frame')
    mapped = asset.get('nativeInputColour') or {}
    space = asset.get('resolved_colour') or mapped.get('encoding') if colour_space == 'auto' else colour_space
    space = {'scene_linear_rec709':'linear_rec709'}.get(space,space)
    if space not in {'acescg','acescct','linear_rec709'}:
        raise ValueError('Choose the actual colour space of this HDR EXR sequence')
    info = describe_media(str(frames))
    info.pop('colour_error',None)
    info.update(resolved_colour=space,colour_space=space,nativeInputColour=mapped)
    if fps is not None:
        if not isinstance(fps,(int,float)) or isinstance(fps,bool) or not math.isfinite(fps) or not 1 <= fps <= 240:
            raise ValueError('Choose a valid EXR sequence frame rate')
        info['fps']=fps
    return info
