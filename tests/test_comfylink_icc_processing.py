"""Strict linear-sRGB ICC authority for a derived SDR model copy."""
import copy
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfylink import float_io
from comfylink.studio_processing import (validate_processing_input,
    verified_linear_srgb_icc, model_input_processor, encode_sdr8)


def linear_srgb_icc():
    tags = [(b'rXYZ', (.43603516, .22248840, .01391602)),
            (b'gXYZ', (.38511658, .71690369, .09707642)),
            (b'bXYZ', (.14305115, .06060791, .71391296)),
            (b'wtpt', (.95043945, 1., 1.08905029)),
            (b'rTRC', None), (b'gTRC', None), (b'bTRC', None)]
    data = bytearray(132 + len(tags)*12 + 4*20 + 3*14)
    struct.pack_into('>I', data, 0, len(data))
    data[8], data[12:16], data[16:20], data[20:24], data[36:40] = 2, b'mntr', b'RGB ', b'XYZ ', b'acsp'
    struct.pack_into('>I', data, 128, len(tags))
    position = 132 + len(tags)*12
    for index, (name, values) in enumerate(tags):
        entry = 132 + index*12
        data[entry:entry+4] = name
        length = 20 if values else 14
        struct.pack_into('>II', data, entry+4, position, length)
        if values:
            data[position:position+4] = b'XYZ '
            for channel, value in enumerate(values):
                struct.pack_into('>i', data, position+8+4*channel, round(value*65536))
        else:
            data[position:position+4] = b'curv'
            struct.pack_into('>I', data, position+8, 1)
            struct.pack_into('>H', data, position+12, 256)
        position += length
    return bytes(data)


class ICCProcessingTests(unittest.TestCase):
    def test_exact_linear_srgb_authority_and_physical_model_copy(self):
        profile = linear_srgb_icc()
        self.assertTrue(verified_linear_srgb_icc(profile))
        with tempfile.TemporaryDirectory() as temporary:
            colour = {'encoding': 'ae_project_icc', 'sceneLinear': True,
                      'management': 'icc', 'profileSha256': hashlib.sha256(profile).hexdigest()}
            pixels = np.array([[[[.25, .5, 1.5, 1.]]]], dtype=np.float32)
            _, manifest = float_io.write_transfer(Path(temporary), 'ComfyLink/'+'a'*32,
                pixels, colour=colour, frame_rate={'numerator': 30000, 'denominator': 1001})
            authority = {'schemaVersion': 1, 'precision': 8,
                         'conversion': 'verified_icc_to_sdr8',
                         'sourceManifestSha256': hashlib.sha256(float_io.canonical_manifest_bytes(manifest)).hexdigest(),
                         'sourceColour': copy.deepcopy(colour),
                         'sourceProfileSha256': colour['profileSha256'],
                         'sourceEncoding': 'scene_linear_rec709',
                         'colour': {'encoding': 'unknown', 'sceneLinear': False},
                         'alphaAssociation': 'straight'}
            self.assertEqual(validate_processing_input(authority, manifest), authority)
            model = encode_sdr8(pixels, derived=True, processor=model_input_processor(authority))
            self.assertEqual(model[0, 0, 0, 0], 137)
            self.assertEqual(model[0, 0, 0, 2], 255)
            transfer = np.array([-.1, 0., .002, .25, .5, 1.5], dtype=np.float32)
            model_input_processor(authority).applyRGB(transfer)
            np.testing.assert_array_equal(np.rint(np.clip(transfer, 0, 1)*255).astype(np.uint8), [0,0,7,137,188,255])
            np.testing.assert_array_equal(pixels[0, 0, 0], [.25, .5, 1.5, 1.])
            numeric = {**authority, 'conversion': 'verified_icc_numeric_to_sdr8'}
            self.assertEqual(validate_processing_input(numeric, manifest), numeric)
            self.assertIsNone(model_input_processor(numeric))
            preview = encode_sdr8(pixels, derived=True, processor=model_input_processor(numeric))
            np.testing.assert_array_equal(preview[0, 0, 0], [64, 128, 255, 255])
            np.testing.assert_array_equal(pixels[0, 0, 0], [.25, .5, 1.5, 1.])
            for changed in ({**authority, 'sourceProfileSha256': '0'*64},
                            {**authority, 'sourceEncoding': 'acescg'},
                            {**authority, 'conversion': 'verified_ocio_to_sdr8'}):
                with self.assertRaises(ValueError):
                    validate_processing_input(changed, manifest)
        altered = bytearray(profile)
        altered[-1] ^= 1
        with self.assertRaises(ValueError):
            verified_linear_srgb_icc(bytes(altered))


if __name__ == '__main__':
    unittest.main()
