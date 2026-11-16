"""CPU sparse painted-key controls for the native LTX 2.5 fluid IC-LoRA graph.

Key positions and nearest-neighbour flat-colour scaling follow the published
AInVFX ainvfx-fluid reference. The model and sampling remain native Comfy nodes.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms
import torch

MAX_TENSOR_BYTES = 512 * 1024 * 1024
MAX_KEYS = 33
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_PIXELS = 16 * 1024 * 1024
MAX_KEY_BYTES = 128 * 1024 * 1024
SUPPORTED_RATES = (24, 25, 50)


def key_slots(frames):
    return [0, *range(1, frames - 7, 8), frames - 1]


def _geometry(width, height, frames):
    if any(type(value) is not int or value < 256 or value > 1920 or value % 64 for value in (width, height)):
        raise ValueError('Paint VFX dimensions must use the 64-pixel grid from 256 to 1920 pixels.')
    if type(frames) is not int or not 9 <= frames <= 321 or (frames - 1) % 8:
        raise ValueError('Paint VFX needs 9–321 frames on the 8n+1 frame grid.')
    required = frames * height * width * 3 * 4
    if required > MAX_TENSOR_BYTES:
        raise ValueError('Paint VFX control video exceeds the 512 MiB CPU limit. Reduce its dimensions or frame count.')
    return required


def _path(name, root):
    if (not isinstance(name, str) or not name or len(name) > 1024 or any(c in name for c in ('\\', ':', '\0'))
            or name.startswith('/') or any(part in {'', '.', '..'} for part in name.split('/'))):
        raise ValueError('Choose a painted keyframe from ComfyUI input storage.')
    lexical = root / name
    path = lexical.resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
        raise ValueError('Choose a stored PNG, JPEG or WebP painted keyframe.')
    cursor = lexical
    while cursor != root:
        if cursor.is_symlink() or bool(getattr(cursor, 'is_junction', lambda: False)()):
            raise ValueError('Linked paths cannot be used as painted keyframes.')
        cursor = cursor.parent
    return path


def _image_bytes(path):
    before = path.stat()
    if not 1 <= before.st_size <= MAX_SOURCE_BYTES or before.st_nlink != 1:
        raise ValueError('Each painted keyframe must be an owned image smaller than 64 MB.')
    with path.open('rb') as stream:
        value = stream.read(MAX_SOURCE_BYTES + 1)
    after = path.stat()
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if len(value) != before.st_size or stamp(before) != stamp(after):
        raise ValueError('A painted keyframe changed while loading. Save it and try again.')
    return value


def _keys(width, height, frames, encoded, root):
    _geometry(width, height, frames)
    if not isinstance(encoded, str) or len(encoded.encode('utf-8')) > 128 * 1024:
        raise ValueError('Paint VFX keyframe descriptions are too large.')
    try:
        keys = json.loads(encoded)
    except (ValueError, TypeError):
        raise ValueError('Choose valid painted keyframes.') from None
    if not isinstance(keys, list) or not 2 <= len(keys) <= MAX_KEYS:
        raise ValueError('Paint between 2 and 33 keyframes, including the first and last frame.')
    allowed, seen, result, total_bytes = set(key_slots(frames)), set(), [], 0
    for key in keys:
        if not isinstance(key, dict) or set(key) != {'frame', 'image'} or type(key.get('frame')) is not int:
            raise ValueError('Each painted keyframe needs a frame number and stored image.')
        frame = key['frame']
        if frame not in allowed or frame in seen:
            raise ValueError('Place unique painted keyframes on the first, last or 8n+1 control slots.')
        seen.add(frame)
        path = _path(key['image'], root)
        data = _image_bytes(path)
        total_bytes += len(data)
        if total_bytes > MAX_KEY_BYTES:
            raise ValueError('Paint VFX keyframe files exceed the 128 MB combined input limit.')
        result.append((frame, key['image'], data))
    if 0 not in seen or frames - 1 not in seen:
        raise ValueError('Paint both the first and last frame before generating Paint VFX.')
    return sorted(result)


def _pixels(data, width, height):
    with Image.open(io.BytesIO(data)) as image:
        if (image.width < 1 or image.height < 1 or image.width * image.height > MAX_SOURCE_PIXELS
                or getattr(image, 'n_frames', 1) != 1 or image.getexif().get(274, 1) != 1):
            raise ValueError('Use a single oriented painted image up to 16 megapixels.')
        if image.mode not in {'RGB', 'RGBA', 'L'}:
            raise ValueError('Paint VFX controls must be 8-bit RGB images.')
        if 'A' in image.getbands() and image.getchannel('A').getextrema() != (255, 255):
            raise ValueError('Flatten the painted keyframe and its background before generating Paint VFX.')
        profile = image.info.get('icc_profile')
        image = image.convert('RGB')
        if profile:
            if len(profile) > 1024 * 1024:
                raise ValueError('The painted keyframe colour profile is too large.')
            try:
                image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(io.BytesIO(profile)), ImageCms.createProfile('sRGB'), outputMode='RGB')
            except Exception:
                raise ValueError('The painted keyframe colour profile could not be converted to sRGB.') from None
        if image.size != (width, height):
            # Explicit canvas geometry, with no fit/crop or smoothing of blobs.
            image = image.resize((width, height), Image.Resampling.NEAREST)
        return np.asarray(image, dtype=np.float32) / np.float32(255)


class ZuraPaintKeyframeVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'width': ('INT', {'default': 512, 'min': 256, 'max': 1920, 'step': 64}),
            'height': ('INT', {'default': 512, 'min': 256, 'max': 1920, 'step': 64}),
            'frames': ('INT', {'default': 121, 'min': 9, 'max': 321, 'step': 8}),
            'keys': ('STRING', {'default': '[]', 'multiline': True,
                                'tooltip': 'Painted input images at frame 0, the last frame, and optional 1+8n slots. Unpainted control frames stay black. 512 MiB CPU limit.'}),
        }}

    RETURN_TYPES = ('IMAGE',)
    RETURN_NAMES = ('keyframe_video',)
    FUNCTION = 'build'
    CATEGORY = 'Zura Studio/video'
    DESCRIPTION = 'Sparse flat-colour controls for native LTX 2.5 fluid IC-LoRA generation. Paint first and last frames; black frames between keys are intentional.'

    @classmethod
    def IS_CHANGED(cls, width, height, frames, keys):
        import folder_paths
        root = Path(folder_paths.get_input_directory()).resolve(strict=True)
        checked = _keys(width, height, frames, keys, root)
        digest = hashlib.sha256(json.dumps([width, height, frames], separators=(',', ':')).encode())
        for frame, name, data in checked:
            digest.update(json.dumps([frame, name], separators=(',', ':')).encode())
            digest.update(hashlib.sha256(data).digest())
        return digest.hexdigest()

    def build(self, width, height, frames, keys):
        import folder_paths
        root = Path(folder_paths.get_input_directory()).resolve(strict=True)
        checked = _keys(width, height, frames, keys, root)
        # Validate and decode every selected image before allocating the video.
        # Keys are bounded separately; retain encoded bytes rather than a stack
        # of full-resolution decoded frames alongside the final tensor.
        for _, _, data in checked:
            _pixels(data, width, height)
        video = torch.zeros((frames, height, width, 3), dtype=torch.float32, device='cpu')
        for frame, _, data in checked:
            video[frame] = torch.from_numpy(_pixels(data, width, height))
        return (video,)


NODE_CLASS_MAPPINGS = {'ZuraPaintKeyframeVideo': ZuraPaintKeyframeVideo}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraPaintKeyframeVideo': 'Zura Paint Keyframe Video'}
