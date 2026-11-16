"""Broker-authorised SDR processing copies. Original float source stays intact."""
import copy
import hashlib
import struct

from . import float_io


def verified_linear_srgb_icc(data):
    """Check physical ICC colourants and gamma-1 curves, not its description."""
    if (not isinstance(data, bytes) or not 132 <= len(data) <= 1 << 20
            or struct.unpack_from('>I', data)[0] != len(data) or data[8] != 2
            or data[12:16] != b'mntr' or data[16:20] != b'RGB '
            or data[20:24] != b'XYZ ' or data[36:40] != b'acsp'):
        raise ValueError('AE ICC is not the qualified linear-sRGB matrix profile')
    count = struct.unpack_from('>I', data, 128)[0]
    if not 7 <= count <= 9 or count > (len(data)-132)//12:
        raise ValueError('AE ICC tag table is unsupported')
    expected = {b'rXYZ': (.43603516, .22248840, .01391602),
                b'gXYZ': (.38511658, .71690369, .09707642),
                b'bXYZ': (.14305115, .06060791, .71391296),
                b'wtpt': (.95043945, 1., 1.08905029)}
    seen = set()
    for index in range(count):
        entry = 132 + 12*index
        name = data[entry:entry+4]
        start, length = struct.unpack_from('>II', data, entry+4)
        if name in seen or start < 132 + count*12 or length < 12 or start+length > len(data):
            raise ValueError('AE ICC tag is invalid')
        seen.add(name)
        tag = data[start:start+length]
        if name in expected:
            if length != 20 or tag[:4] != b'XYZ ':
                raise ValueError('AE ICC colourant is not an XYZ matrix')
            values = [struct.unpack_from('>i', tag, 8+4*n)[0]/65536 for n in range(3)]
            if any(abs(got-want) > 4/65536 for got, want in zip(values, expected[name])):
                raise ValueError('AE ICC gamut or white point differs from linear sRGB')
        elif name in (b'rTRC', b'gTRC', b'bTRC'):
            if (length != 14 or tag[:4] != b'curv' or struct.unpack_from('>I', tag, 8)[0] != 1
                    or struct.unpack_from('>H', tag, 12)[0] != 256):
                raise ValueError('AE ICC transfer curve is not linear')
        elif name not in (b'cprt', b'desc'):
            raise ValueError('AE ICC includes an unsupported colour transform')
    if not set(expected).union((b'rTRC', b'gTRC', b'bTRC')) <= seen:
        raise ValueError('AE ICC is missing linear-sRGB colour tags')
    return True


class _LinearSRGBICCToModel:
    """IEC 61966-2-1 OETF for the strictly verified linear-sRGB ICC only."""
    def applyRGB(self, rgb):
        import numpy as np
        values = np.asarray(rgb, dtype=np.float32)
        low = values <= np.float32(.0031308)
        result = np.empty_like(values)
        result[low] = values[low] * np.float32(12.92)
        positive = values[~low]
        result[~low] = np.float32(1.055) * np.power(positive, np.float32(1/2.4)) - np.float32(.055)
        rgb[...] = result


def validate_processing_input(value, manifest):
    if value is None:
        return None
    required = {"schemaVersion", "precision", "conversion", "sourceManifestSha256", "sourceColour", "colour", "alphaAssociation"}
    if not isinstance(value, dict) or set(value) - required - {"sourceConfigSha256", "sourceProfileSha256", "sourceEncoding", "sourceProcessingPrecision", "samplePolicy", "colourAssignment"} or not required <= set(value):
        raise ValueError("Invalid processing input authority")
    if (type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1
            or type(value["precision"]) is not int or value["precision"] != 8
            or value["conversion"] not in {"verified_srgb_to_sdr8", "verified_ocio_to_sdr8", "verified_icc_to_sdr8", "verified_icc_numeric_to_sdr8", "raw_numeric_to_sdr8"}
            or value["sourceManifestSha256"] != hashlib.sha256(float_io.canonical_manifest_bytes(manifest)).hexdigest()
            or value["sourceColour"] != manifest["colour"]
            or value["colour"] != {"encoding": "srgb_display" if value["conversion"] == "raw_numeric_to_sdr8" else "unknown", "sceneLinear": False}
            or value["alphaAssociation"] != "straight" or manifest["alphaAssociation"] != "straight"):
        raise ValueError("Processing input differs from the captured source")
    colour = manifest["colour"]
    if value['conversion'] == 'raw_numeric_to_sdr8':
        # This authority comes only from the authenticated broker after an
        # explicit 8-bit transfer choice. It changes numeric precision, never
        # colour space, gamma or viewport appearance. Keep the working master
        # and its original colour identity separate from the normal RGB asset.
        if (manifest.get('sampleType') != 'float32' or manifest.get('sourceBitDepth') != 32
                or value.get('sourceProcessingPrecision') != 'sdr8'
                or value.get('samplePolicy') != 'clamp_round_unorm8'
                or value.get('colourAssignment') != 'numeric_sdr8_code_values'
                or 'sourceConfigSha256' in value or 'sourceProfileSha256' in value or 'sourceEncoding' in value):
            raise ValueError('Raw numeric input requires an explicit eight-bit source authority')
        return copy.deepcopy(value)
    if 'sourceProcessingPrecision' in value or 'samplePolicy' in value or 'colourAssignment' in value:
        raise ValueError('Unexpected numeric transfer authority')
    if colour.get("management") == "ocio":
        from .display_view import _verified_ocio_source
        encoding = _verified_ocio_source(colour)
        if value.get("sourceConfigSha256") != colour.get("ocioConfigFileSha256") or 'sourceProfileSha256' in value:
            raise ValueError("The model-input configuration differs from the captured source")
        if value['conversion'] == 'verified_srgb_to_sdr8':
            if encoding != 'srgb8' or 'sourceEncoding' in value:
                raise ValueError("SDR processing needs a verified display-sRGB working space")
        elif value['conversion'] != 'verified_ocio_to_sdr8' or encoding not in {'acescg', 'acescct', 'scene_linear_rec709'} or value.get('sourceEncoding') != encoding:
            raise ValueError("The model-input colour space differs from the verified AE source")
    elif colour.get('management') == 'icc':
        if (value['conversion'] not in {'verified_icc_to_sdr8', 'verified_icc_numeric_to_sdr8'} or colour.get('encoding') != 'ae_project_icc'
                or colour.get('sceneLinear') is not True or manifest.get('sourceBitDepth') != 32
                or value.get('sourceProfileSha256') != colour.get('profileSha256')
                or value.get('sourceEncoding') != 'scene_linear_rec709'
                or 'sourceConfigSha256' in value):
            raise ValueError('SDR processing needs the verified linear-sRGB AE ICC profile')
    elif (colour != {"encoding": "unknown", "sceneLinear": False}
          or "sourceConfigSha256" in value or 'sourceProfileSha256' in value or 'sourceEncoding' in value
          or value['conversion'] != 'verified_srgb_to_sdr8'):
        raise ValueError("SDR processing needs an unmanaged display-sRGB source")
    return copy.deepcopy(value)


def model_input_processor(processing):
    """A colour-space conversion only; viewport display choices never affect it."""
    if not processing or processing['conversion'] in {'verified_srgb_to_sdr8', 'raw_numeric_to_sdr8', 'verified_icc_numeric_to_sdr8'}:
        return None
    if processing['conversion'] == 'verified_icc_to_sdr8':
        return _LinearSRGBICCToModel()
    from .display_view import _config, _source, DEFAULT_CONFIG
    encoding = processing.get('sourceEncoding')
    if encoding not in {'acescg', 'acescct', 'scene_linear_rec709'}:
        raise ValueError('The model-input colour space is not verified')
    config = _config(DEFAULT_CONFIG)
    return config.getProcessor(_source(config, {'encoding': encoding}, 32),
                               _source(config, {'encoding': 'srgb8'}, 8)).getDefaultCPUProcessor()


def encode_sdr8(rgba, *, derived=False, processor=None):
    import numpy as np
    if not np.isfinite(rgba).all():
        raise ValueError("Source has non-finite samples")
    if derived:
        if np.any(rgba[..., 3] < 0) or np.any(rgba[..., 3] > 1):
            raise ValueError("Source alpha is outside its supported range")
        # Eight-bit image models receive a bounded SDR copy. The captured
        # FLOAT frame and its manifest are retained without changing samples.
        pixels = np.array(rgba, dtype=np.float32, order='C', copy=True)
        if processor is not None:
            rgb = np.ascontiguousarray(pixels[..., :3])
            processor.applyRGB(rgb)
            if not np.isfinite(rgb).all():
                raise ValueError('The model-input colour conversion returned invalid samples')
            pixels[..., :3] = rgb
        return np.rint(np.clip(pixels, 0, 1) * 255).astype(np.uint8)
    if np.any(rgba < 0) or np.any(rgba > 1):
        raise ValueError("Source exceeds SDR range. Choose 32-bit FLOAT; no samples were clipped")
    encoded = np.rint(rgba * 255).astype(np.uint8)
    if not derived and not np.array_equal(rgba, encoded.astype(np.float32) / np.float32(255)):
        raise ValueError("Source samples are not eight-bit levels")
    return encoded
