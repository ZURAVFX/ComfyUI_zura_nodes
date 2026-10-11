"""Synthetic CPU tests for conservative enclosed-hole mask cleanup."""
import sys
import types
import unittest

import v2_bootstrap
import torch

NAME = "ComfyUI_zura_nodes.artist_studio"
package = sys.modules.setdefault(NAME, types.ModuleType(NAME))
package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
if str(v2_bootstrap.ROOT) not in sys.path:
    sys.path.insert(0, str(v2_bootstrap.ROOT))

import studio_mask_cleanup as cleanup


def _hole(mask, top, left, height, width, area):
    """Carve a connected, fully enclosed component with an exact pixel area."""
    mask[top:top + height, left:left + width] = 0.0
    excess = height * width - area
    for index in range(excess):
        y = top + 1 + index // max(1, width - 2)
        x = left + 1 + index % max(1, width - 2)
        mask[y, x] = 1.0


class SmallMaskHoleCleanupTests(unittest.TestCase):
    def test_fills_118_pixel_hole_but_preserves_269_pixel_limb_gap(self):
        mask = torch.ones(1, 48, 64, dtype=torch.float32)
        _hole(mask[0], 5, 5, 10, 12, 118)
        _hole(mask[0], 20, 5, 13, 21, 269)
        original = mask.clone()

        result, = cleanup.ZuraFillSmallMaskHoles().fill(mask)

        self.assertTrue(torch.all(result[0, 5:15, 5:17] == 1.0))
        self.assertEqual(int((result[0, 20:33, 5:26] == 0).sum()), 269)
        self.assertTrue(torch.equal(mask, original))
        self.assertIsNot(result, mask)

    def test_larger_enclosed_gap_and_border_connected_component_remain_open(self):
        mask = torch.ones(1, 64, 100, dtype=torch.float32)
        _hole(mask[0], 8, 8, 17, 28, 476)
        _hole(mask[0], 32, 10, 27, 62, 1659)
        mask[0, 0:12, 48:58] = 0.0  # 120 pixels connected to the image border.
        original = mask.clone()

        result, = cleanup.ZuraFillSmallMaskHoles().fill(mask)

        self.assertEqual(int((result[0, 8:25, 8:36] == 0).sum()), 476)
        self.assertEqual(int((result[0, 32:59, 10:72] == 0).sum()), 1659)
        self.assertTrue(torch.equal(result[0, 0:12, 48:58], original[0, 0:12, 48:58]))

    def test_soft_edges_and_every_pixel_outside_filled_holes_are_exact(self):
        mask = torch.ones(1, 32, 40, dtype=torch.float32)
        _hole(mask[0], 8, 8, 10, 12, 118)
        mask[0, 0, :] = torch.linspace(0.01, 0.49, 40)
        mask[0, 20, 4] = 0.63
        original = mask.clone()
        fill_region = torch.zeros_like(mask, dtype=torch.bool)
        fill_region[0, 8:18, 8:20] = (original[0, 8:18, 8:20] < 0.5)

        result, = cleanup.ZuraFillSmallMaskHoles().fill(mask)

        self.assertTrue(torch.equal(result[~fill_region], original[~fill_region]))
        self.assertTrue(torch.all(result[fill_region] == 1.0))

    def test_processes_each_batch_frame_without_mutating_input_and_preserves_dtype_device(self):
        node = cleanup.ZuraFillSmallMaskHoles()
        for dtype in (torch.float16, torch.float32, torch.float64, torch.bfloat16):
            with self.subTest(dtype=dtype):
                mask = torch.ones(2, 24, 32, dtype=dtype, device="cpu")
                _hole(mask[0], 5, 6, 10, 12, 118)
                original = mask.clone()
                result, = node.fill(mask)
                self.assertEqual(result.shape, mask.shape)
                self.assertEqual(result.dtype, dtype)
                self.assertEqual(result.device, mask.device)
                self.assertTrue(torch.all(result[0, 5:15, 6:18] == 1))
                self.assertTrue(torch.equal(result[1], mask[1]))
                self.assertTrue(torch.equal(mask, original))

    def test_zero_area_bypasses_cleanup_without_copying_the_mask(self):
        mask = torch.zeros(1, 16, 20, dtype=torch.float32)
        mask[:, 2:-2, 2:-2] = 1
        result, = cleanup.ZuraFillSmallMaskHoles().fill(mask, 0)
        self.assertIs(result, mask)
        self.assertTrue(torch.equal(result, mask))

    def test_four_connected_components_do_not_join_through_diagonal_touch(self):
        mask = torch.ones(1, 9, 9, dtype=torch.float32)
        # The one-pixel interior component touches the exterior diagonally only.
        mask[0, 3, 3] = 0
        mask[0, 2, 2] = 0
        mask[0, 1, 1] = 0
        mask[0, 0, 0] = 0
        result, = cleanup.ZuraFillSmallMaskHoles().fill(mask, 3)
        self.assertTrue(torch.all(result[0, 3, 3] == 1))

    def test_invalid_shapes_values_and_hole_caps_fail_closed(self):
        node = cleanup.ZuraFillSmallMaskHoles()
        for invalid in (torch.ones(8, 8), torch.ones(1, 8, 8, dtype=torch.int32),
                        torch.empty(1, 8193, 1, device="meta")):
            with self.subTest(shape=tuple(invalid.shape)), self.assertRaises(ValueError):
                node.fill(invalid)
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite"):
                node.fill(torch.full((1, 8, 8), value))
        for cap in (-1, True, 1.5, 257):
            with self.subTest(cap=cap), self.assertRaisesRegex(ValueError, "integer"):
                node.fill(torch.ones(1, 8, 8), cap)

    def test_artist_control_registration_is_small_and_bounded(self):
        required = cleanup.ZuraFillSmallMaskHoles.INPUT_TYPES()["required"]
        self.assertEqual(cleanup.ZuraFillSmallMaskHoles.RETURN_TYPES, ("MASK",))
        self.assertEqual(cleanup.NODE_CLASS_MAPPINGS,
                         {"ZuraFillSmallMaskHoles": cleanup.ZuraFillSmallMaskHoles})
        self.assertEqual(required["max_hole_area"][1]["default"], 128)
        self.assertEqual(required["max_hole_area"][1]["max"], 256)


if __name__ == "__main__":
    unittest.main()
