import importlib.util
import unittest
from pathlib import Path

import torch

MODULE = Path(__file__).resolve().parents[1] / "artist_studio" / "image_edit_area.py"
spec = importlib.util.spec_from_file_location("zura_test_image_edit_area", MODULE)
area = importlib.util.module_from_spec(spec)
spec.loader.exec_module(area)


class ImageEditAreaTests(unittest.TestCase):
    def setUp(self):
        self.source = torch.rand((1, 79, 133, 3))
        self.mask = torch.zeros((1, 40, 67, 3))
        self.mask[:, 8:32, 10:57, :] = 1
        self.mask[:, 18:23, 28:37, :] = 0  # Artist deliberately protected this island.

    def test_painted_luminance_resizes_to_odd_source_and_preserves_island(self):
        raw, blend = area.ZuraImageEditMask().prepare(self.source, self.mask, 6)
        self.assertEqual(tuple(raw.shape), (1, 79, 133))
        self.assertTrue(torch.equal(raw == 0, blend == 0))
        self.assertGreater(float(blend.max()), .9)
        self.assertTrue(torch.all(blend <= raw))
        self.assertEqual(float(raw[0, 40, 64]), 0)
        self.assertEqual(float(blend[0, 40, 64]), 0)
        self.assertGreater(float(raw[0, 20, 30]), 0)

    def test_feather_is_inward_only_and_zero_feather_matches_paint(self):
        raw, hard = area.ZuraImageEditMask().prepare(self.source, self.mask, 0)
        self.assertTrue(torch.equal(raw, hard))
        _, soft = area.ZuraImageEditMask().prepare(self.source, self.mask, 12)
        self.assertTrue(torch.equal(soft[raw == 0], torch.zeros_like(soft[raw == 0])))
        self.assertTrue(torch.any((soft > 0) & (soft < raw)))

    def test_drawn_guide_refines_a_region_not_just_the_coloured_strokes(self):
        mask=torch.zeros((1,79,133,3));mask[:,25:28,50:53,:]=1;mask[:,45:48,70:73,:]=1
        raw,blend=area.ZuraImageEditMask().prepare(self.source,mask,6,drawing_region=True)
        self.assertEqual(float(mask[0,35,60,0]),0)
        self.assertEqual(float(raw[0,35,60]),1)
        self.assertGreater(float(blend[0,35,60]),.9)
        self.assertEqual(float(blend[0,0,0]),0)

    def test_empty_invalid_and_wrong_shape_are_rejected(self):
        node = area.ZuraImageEditMask()
        with self.assertRaisesRegex(ValueError, "Paint an edit area"):
            node.prepare(self.source, torch.zeros_like(self.mask), 8)
        with self.assertRaisesRegex(ValueError, "does not match"):
            node.prepare(self.source, torch.ones((1, 40, 40, 3)), 8)
        bad = self.mask.clone()
        bad[0, 0, 0, 0] = float('nan')
        with self.assertRaisesRegex(ValueError, "invalid pixels"):
            node.prepare(self.source, bad, 8)

    def test_crop_result_allows_small_rounding_and_strips_alpha(self):
        node = area.ZuraImageEditCropResult()
        reference = torch.rand((1, 512, 768, 3))
        output = node.validate(torch.rand((1, 500, 750, 4)), reference)[0]
        self.assertEqual(tuple(output.shape), (1, 500, 750, 3))
        with self.assertRaisesRegex(ValueError, "different crop shape"):
            node.validate(torch.rand((1, 512, 512, 3)), reference)

    def test_narrow_crop_processing_keeps_both_axes_supported(self):
        node = area.ZuraImageEditResolution()
        crop = torch.zeros((1, 256, 8192, 3))
        actual = node.clamp(crop, .0625, 16)[0]
        self.assertEqual(actual, 2)
        self.assertAlmostEqual(node.clamp(crop, 16, 16)[0], 2)

    def test_auto_raises_small_crop_and_retains_larger_native_crop(self):
        node = area.ZuraImageEditResolution()
        self.assertEqual(node.clamp(torch.zeros((1, 656, 400, 3)), 0, 16)[0], 1)
        self.assertEqual(node.clamp(torch.zeros((1, 1024, 2048, 3)), 0, 16)[0], 2)
        self.assertEqual(node.clamp(torch.zeros((1, 656, 400, 3)), .5, 16)[0], .5)
        for invalid in [-1, .001, 17, float('nan')]:
            with self.assertRaises(ValueError):
                node.clamp(self.source, invalid, 16)


if __name__ == '__main__':
    unittest.main()
