import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import torch

PATH = Path(__file__).parents[1] / 'artist_studio' / 'ltx_outpaint.py'
spec = importlib.util.spec_from_file_location('ltx_outpaint_test', PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OutpaintCanvasTests(unittest.TestCase):
    def test_enlarged_source_crops_the_same_centre_without_stretching(self):
        images = torch.rand((2, 64, 256, 3))
        canvas, mask = module.prepare_canvas(images, 'expand', 128, 128, -64, 32, -64, 32)
        self.assertTrue(torch.allclose(canvas[:, 32:96], images[:, :, 64:192], atol=1e-6))
        self.assertTrue((mask[:, 32:96] == 0).all())
        self.assertTrue((mask[:, :32] == 1).all())
        self.assertTrue((canvas[:, :32] == 0).all())

    def test_extreme_zoom_samples_only_the_visible_area(self):
        images = torch.full((1, 32, 64, 3), .5)
        with patch.object(module.F, 'interpolate', side_effect=AssertionError('Oversized intermediate')):
            canvas, mask = module.prepare_canvas(images, 'expand', 128, 256, -6336, 32, -6336, -6176)
        self.assertEqual(canvas.shape, (1, 256, 128, 3))
        self.assertTrue(torch.allclose(canvas[:, 32:], torch.full_like(canvas[:, 32:], .5)))
        self.assertTrue((mask[:, :32] == 1).all())
        self.assertTrue((mask[:, 32:] == 0).all())

    def test_zoom_still_requires_an_area_to_extend_and_visible_source(self):
        images = torch.ones((1, 64, 64, 3))
        with self.assertRaisesRegex(ValueError, 'Expand the canvas'):
            module.prepare_canvas(images, 'expand', 128, 128, -64, -64, -64, -64)
        with self.assertRaisesRegex(ValueError, 'inside'):
            module.prepare_canvas(images, 'expand', 128, 128, 128, 0, -256, 0)

    def test_expand_keeps_source_aspect_and_mask_is_aligned_for_each_frame(self):
        images = torch.stack([torch.full((32, 64, 3), .3), torch.full((32, 64, 3), .7)])
        canvas, mask = module.prepare_canvas(images, 'expand', 128, 128, 32, 16, 32, 16)
        self.assertEqual(tuple(canvas.shape), (2, 128, 128, 3))
        self.assertEqual(tuple(mask.shape), (2, 128, 128))
        self.assertTrue(torch.equal(canvas[:, 48:80, 32:96], images))
        self.assertTrue((mask[:, 48:80, 32:96] == 0).all())
        self.assertEqual(int((mask[0] == 0).sum()), 32 * 64)
        self.assertTrue((canvas[:, :48] == 0).all())

    def test_black_mode_is_explicit_and_mask_varies_per_frame(self):
        images = torch.ones((2, 64, 64, 3))
        images[0, :10] = 0
        images[1, :, :12] = .005
        output, mask = module.prepare_canvas(images, 'black', 64, 64)
        self.assertTrue(torch.equal(output, images))
        self.assertEqual(int(mask[0].sum()), 640)
        self.assertEqual(int(mask[1].sum()), 768)

    def test_invalid_geometry_and_empty_black_masks_are_rejected(self):
        images = torch.ones((1, 64, 64, 3))
        for args in [('expand', 128, 64, 64, 0, 64, 0), ('expand', 100, 64), ('black', 64, 64), ('black', 128, 64)]:
            with self.assertRaises(ValueError):
                module.prepare_canvas(images, *args)

    def test_native_graph_uses_mask_before_sampling_and_same_mask_to_blend(self):
        graph = module.build_test_graph('source.mp4', 'outpaint/test', 25, 24, 768, 448,
                                        left=192, right=192, top=116, bottom=116)
        self.assertEqual(graph['inpaint']['inputs']['mask'], ['low_mask', 0])
        self.assertEqual(graph['guide']['inputs']['image'], ['inpaint', 0])
        self.assertEqual(graph['blend_high']['inputs']['mask'], ['canvas', 1])
        self.assertEqual(graph['assemble']['inputs']['audio'], ['components', 1])
        self.assertEqual(graph['empty']['inputs']['length'], 25)
        with self.assertRaises(ValueError):
            module.build_test_graph('source.mp4', 'outpaint/test', 24, 24, 768, 448)


if __name__ == '__main__':
    unittest.main()
