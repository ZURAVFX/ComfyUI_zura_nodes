"""Broker-authorised SDR processing copies. Original float source stays intact."""
import copy
import hashlib

from . import float_io


def validate_processing_input(value, manifest):
    if value is None:
        return None
    required = {"schemaVersion", "precision", "conversion", "sourceManifestSha256", "sourceColour", "colour", "alphaAssociation"}
    if not isinstance(value, dict) or set(value) - required - {"sourceConfigSha256", "sourceEncoding"} or not required <= set(value):
        raise ValueError("Invalid processing input authority")
    if (type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1
            or type(value["precision"]) is not int or value["precision"] != 8
            or value["conversion"] not in {"verified_srgb_to_sdr8", "verified_ocio_to_sdr8"}
            or value["sourceManifestSha256"] != hashlib.sha256(float_io.canonical_manifest_bytes(manifest)).hexdigest()
            or value["sourceColour"] != manifest["colour"]
            or value["colour"] != {"encoding": "unknown", "sceneLinear": False}
            or value["alphaAssociation"] != "straight" or manifest["alphaAssociation"] != "straight"):
        raise ValueError("Processing input differs from the captured source")
    colour = manifest["colour"]
    if colour.get("management") == "ocio":
        from .display_view import _verified_ocio_source
        encoding = _verified_ocio_source(colour)
        if value.get("sourceConfigSha256") != colour.get("ocioConfigFileSha256"):
            raise ValueError("The model-input configuration differs from the captured source")
        if value['conversion'] == 'verified_srgb_to_sdr8':
            if encoding != 'srgb8' or 'sourceEncoding' in value:
                raise ValueError("SDR processing needs a verified display-sRGB working space")
        elif encoding not in {'acescg', 'acescct', 'scene_linear_rec709'} or value.get('sourceEncoding') != encoding:
            raise ValueError("The model-input colour space differs from the verified AE source")
    elif (colour != {"encoding": "unknown", "sceneLinear": False}
          or "sourceConfigSha256" in value or 'sourceEncoding' in value
          or value['conversion'] != 'verified_srgb_to_sdr8'):
        raise ValueError("SDR processing needs an unmanaged display-sRGB source")
    return copy.deepcopy(value)


def model_input_processor(processing):
    """A colour-space conversion only; viewport display choices never affect it."""
    if not processing or processing['conversion'] == 'verified_srgb_to_sdr8':
        return None
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
