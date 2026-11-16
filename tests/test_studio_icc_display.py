"""Actual linear ICC display pixels, with unchanged FLOAT masters."""
import hashlib
import importlib
import io
import struct
import unittest

import numpy as np
from PIL import Image, ImageCms

import v2_bootstrap

display = importlib.import_module('ComfyUI_zura_nodes.comfylink.display_view')
icc = importlib.import_module('ComfyUI_zura_nodes.comfylink.icc_display')


def linear_srgb_profile():
    """Retain the real LCMS sRGB XYZ matrix, replacing only the RGB TRCs."""
    original = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    count = struct.unpack('>I', original[128:132])[0]
    tags = []
    for index in range(count):
        name, offset, size = struct.unpack('>4sII', original[132 + index * 12:144 + index * 12])
        data = original[offset:offset + size]
        if name in (b'rTRC', b'gTRC', b'bTRC'):
            data = b'curv' + b'\0' * 8
        tags.append((name, data))
    result = bytearray(original[:128] + struct.pack('>I', count) + b'\0' * (12 * count))
    for index, (name, data) in enumerate(tags):
        result.extend(b'\0' * (-len(result) % 4))
        offset = len(result)
        result.extend(data)
        struct.pack_into('>4sII', result, 132 + index * 12, name, offset, len(data))
    struct.pack_into('>I', result, 0, len(result))
    return bytes(result)


class ICCDisplayTests(unittest.TestCase):
    def setUp(self):
        self.profile = linear_srgb_profile()
        self.pixels = np.array([[[-.25, .18, 4., 1.], [.03, .4, .8, .33333334]]], dtype=np.float32)
        self.colour = {'management': 'icc', 'encoding': 'ae_project_icc', 'sceneLinear': True,
                       'profileSha256': hashlib.sha256(self.profile).hexdigest()}
        self.manifest = {'width': 2, 'height': 1, 'sampleType': 'float32', 'sourceBitDepth': 32,
                         'alphaAssociation': 'straight', 'colour': self.colour}

    def test_actual_icc_conversion_matches_linear_srgb_and_keeps_float_bytes(self):
        before = self.pixels.tobytes()
        shown = display.render(before, self.manifest, profile=self.profile)
        expected = display.render(before, {**self.manifest, 'colour': {'encoding': 'scene_linear_rec709', 'sceneLinear': True}})
        actual = np.array(Image.open(io.BytesIO(shown)))
        reference = np.array(Image.open(io.BytesIO(expected)))
        self.assertLessEqual(np.max(np.abs(actual.astype(int) - reference.astype(int))), 1)
        self.assertEqual(actual[0, 0, 0], 0)
        self.assertEqual(actual[0, 0, 2], 255)
        self.assertEqual(actual[0, 1, 3], 85)
        self.assertEqual(self.pixels.tobytes(), before)
        self.assertEqual(self.manifest['sourceBitDepth'], 32)

    def test_actual_profile_matrix_changes_preview(self):
        changed = bytearray(self.profile)
        count = struct.unpack('>I', changed[128:132])[0]
        for index in range(count):
            name, offset, _ = struct.unpack('>4sII', changed[132 + index * 12:144 + index * 12])
            if name == b'rXYZ':
                value = struct.unpack('>i', changed[offset + 8:offset + 12])[0]
                struct.pack_into('>i', changed, offset + 8, round(value * .75))
        changed = bytes(changed)
        colour = {**self.colour, 'profileSha256': hashlib.sha256(changed).hexdigest()}
        a = display.render(self.pixels.tobytes(), self.manifest, profile=self.profile)
        b = display.render(self.pixels.tobytes(), {**self.manifest, 'colour': colour}, profile=changed)
        self.assertNotEqual(a, b, 'A profile name must never substitute for its actual matrix')

    def test_none_bypasses_every_colour_transform_but_keeps_lineage_and_float_samples(self):
        before = self.pixels.tobytes()
        shown = display.render(before, self.manifest, display='sRGB - Display', view='Raw', profile=self.profile)
        actual = np.array(Image.open(io.BytesIO(shown)))
        expected = np.rint(np.clip(self.pixels, 0, 1) * 255).astype(np.uint8)
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(actual[0, 0].tolist(), [0, 46, 255, 255])
        self.assertEqual(actual[0, 1, 3], 85)
        self.assertEqual(self.pixels.tobytes(), before)
        self.assertLess(self.pixels.min(), 0)
        self.assertGreater(self.pixels.max(), 1)
        with self.assertRaises(ValueError):
            display.render(before, self.manifest, view='Raw', profile=self.profile[:-1])
        with self.assertRaises(ValueError):
            display.render(before, self.manifest, view='None', profile=self.profile)
        with self.assertRaises(ValueError):
            display.render(before, self.manifest, display='Untrusted display', view='Raw', profile=self.profile)

    def test_profile_hash_missing_and_nonlinear_profiles_fail_closed(self):
        for profile in (None, self.profile[:-1], self.profile + b'\0'):
            with self.subTest(profile=type(profile).__name__), self.assertRaises(ValueError):
                display.render(self.pixels.tobytes(), self.manifest, profile=profile)
        nonlinear = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        colour = {**self.colour, 'profileSha256': hashlib.sha256(nonlinear).hexdigest()}
        with self.assertRaises(ValueError):
            display.render(self.pixels.tobytes(), {**self.manifest, 'colour': colour}, profile=nonlinear)
        with self.assertRaises(ValueError):
            icc.validate_linear_profile(self.profile, {**self.colour, 'sceneLinear': False})


if __name__ == '__main__':
    unittest.main()
