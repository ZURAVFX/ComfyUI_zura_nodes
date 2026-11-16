"""Display-only ICC conversion of the authenticated, retained FLOAT source."""
from functools import lru_cache
import hashlib
from pathlib import Path
import struct
import tempfile


MAX_PROFILE_BYTES = 4 * 1024 * 1024


def validate_linear_profile(profile, colour):
    """Only actual linear RGB matrix profiles qualify; names grant no mapping."""
    if (not isinstance(profile, bytes) or not 132 <= len(profile) <= MAX_PROFILE_BYTES
            or colour.get('management') != 'icc' or colour.get('encoding') != 'ae_project_icc'
            or colour.get('sceneLinear') is not True
            or hashlib.sha256(profile).hexdigest() != colour.get('profileSha256')
            or struct.unpack('>I', profile[:4])[0] != len(profile)
            or profile[16:24] != b'RGB XYZ ' or profile[36:40] != b'acsp'):
        raise ValueError('The captured linear ICC profile is unavailable or changed')
    count = struct.unpack('>I', profile[128:132])[0]
    if not 1 <= count <= 128 or 132 + count * 12 > len(profile):
        raise ValueError('Invalid captured ICC tag table')
    tags, ranges = {}, []
    for index in range(count):
        signature, offset, size = struct.unpack('>4sII', profile[132 + index * 12:144 + index * 12])
        if (signature in tags or offset % 4 or offset < 132 + count * 12 or size < 8
                or offset + size > len(profile)
                or any(offset < end and start < offset + size and (offset, offset + size) != (start, end)
                       for start, end in ranges)):
            raise ValueError('Invalid captured ICC tag extent')
        tags[signature] = profile[offset:offset + size]
        ranges.append((offset, offset + size))
    if not {b'rXYZ', b'gXYZ', b'bXYZ', b'wtpt', b'rTRC', b'gTRC', b'bTRC'} <= set(tags):
        raise ValueError('Captured ICC is not a complete RGB matrix profile')
    if any(signature.startswith((b'A2B', b'B2A', b'D2B', b'B2D'))
           or payload[:4] in {b'mft1', b'mft2', b'mAB ', b'mBA '}
           for signature, payload in tags.items()):
        raise ValueError('LUT ICC profiles are not qualified for FLOAT preview')
    for key in (b'rXYZ', b'gXYZ', b'bXYZ', b'wtpt'):
        if len(tags[key]) != 20 or tags[key][:4] != b'XYZ ':
            raise ValueError('Invalid captured ICC matrix')
    for key in (b'rTRC', b'gTRC', b'bTRC'):
        curve = tags[key]
        linear = (len(curve) == 12 and curve[:4] == b'curv' and curve[8:12] == b'\0\0\0\0'
                  or len(curve) == 14 and curve[:4] == b'curv'
                  and curve[8:14] == b'\0\0\0\1\1\0'
                  or len(curve) == 16 and curve[:4] == b'para'
                  and curve[8:10] == b'\0\0' and curve[12:16] == b'\0\1\0\0')
        if not linear:
            raise ValueError('Scene-linear FLOAT preview requires actual linear ICC curves')
    return tags


def _ocio_profile(profile):
    # ICC permits a zero-entry identity curve; OCIO requires an explicit gamma.
    # Normalise only that mathematically identical representation in a temporary
    # copy. Source matrix/white/adaptation and every other tag stay byte-identical.
    tags = validate_linear_profile(profile, {'management': 'icc', 'encoding': 'ae_project_icc',
        'sceneLinear': True, 'profileSha256': hashlib.sha256(profile).hexdigest()})
    if not any(tags[key][:12] == b'curv' + b'\0' * 8 for key in (b'rTRC', b'gTRC', b'bTRC')):
        return profile
    result = bytearray(profile[:128] + struct.pack('>I', len(tags)) + b'\0' * (12 * len(tags)))
    for index, (name, data) in enumerate(tags.items()):
        if name in (b'rTRC', b'gTRC', b'bTRC') and data == b'curv' + b'\0' * 8:
            data = b'curv' + b'\0' * 4 + struct.pack('>IH', 1, 256)
        result.extend(b'\0' * (-len(result) % 4))
        offset = len(result)
        result.extend(data)
        struct.pack_into('>4sII', result, 132 + index * 12, name, offset, len(data))
    struct.pack_into('>I', result, 0, len(result))
    result[84:100] = b'\0' * 16  # The original ICC ID belongs only to its original bytes.
    return bytes(result)


@lru_cache(maxsize=8)
def processor(profile, config_name, display, view):
    from . import display_view
    ocio = display_view._ocio()
    config = display_view._config(config_name)
    space = config.getColorSpace('ACES2065-1') or config.getColorSpace('ACES - ACES2065-1')
    if space is None or display not in config.getDisplays() or view not in config.getViews(display):
        raise ValueError('The selected display configuration cannot show this ICC source')
    # OCIO's ICC INVERSE direction is device RGB -> XYZ D65 (FileFormatICC.cpp).
    # This applies the actual profile matrix/TRCs, never a description-name guess.
    with tempfile.TemporaryDirectory(prefix='zura-icc-display-') as temporary:
        path = Path(temporary) / 'source.icc'
        path.write_bytes(_ocio_profile(profile))
        group = ocio.GroupTransform([
            ocio.FileTransform(src=str(path), direction=ocio.TRANSFORM_DIR_INVERSE),
            ocio.BuiltinTransform(style='UTILITY - ACES-AP0_to_CIE-XYZ-D65_BFD',
                                  direction=ocio.TRANSFORM_DIR_INVERSE),
            ocio.DisplayViewTransform(src=space.getName(), display=display, view=view),
        ])
        try:
            return config.getProcessor(group).getDefaultCPUProcessor()
        except Exception:
            raise ValueError('The captured ICC profile cannot be compiled for FLOAT display') from None
