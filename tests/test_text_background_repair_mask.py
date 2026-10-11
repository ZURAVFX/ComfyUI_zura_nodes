"""Background text cleanup stays inside reviewed pixels and away from people."""
import importlib
import sys
import types
import unittest

import torch

import v2_bootstrap

NAME = "ComfyUI_zura_nodes.artist_studio"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[NAME] = package
removal = importlib.import_module(NAME + ".text_removal")


class TextBackgroundRepairMaskTests(unittest.TestCase):
    def setUp(self):
        self.node = removal.ZuraTextBackgroundRepairMask()

    def details(self, regions, size=(48, 32)):
        return {"text_regions": regions, "text_regions_size": list(size)}

    def region(self, x=4, y=3, width=8, height=4):
        return {"x": x, "y": y, "width": width, "height": height}

    def test_background_panel_is_repaired_throughout_shot_without_freezing_performer_motion(self):
        combined = torch.zeros(6, 64, 48)
        performer = torch.zeros_like(combined)
        combined[:, 3:7, 4:12] = 1  # Held title panel from the reviewed mask.
        for frame, (y, x) in enumerate(((50, 3), (51, 5), (52, 7), (53, 9), (54, 11), (55, 13))):
            performer[frame, y:y + 2, x:x + 2] = 1
            combined[frame, y:y + 2, x:x + 2] = 1
        original = combined.clone()

        crop, generation, crop_w, crop_h, crop_x, crop_y, has_text = self.node.adapt(
            combined, performer, self.details([self.region()], size=(48, 64)), context=0)

        self.assertTrue(has_text)
        self.assertTrue(torch.equal(crop[:, 3:7, 4:12], torch.ones(6, 4, 8)))
        self.assertEqual(crop[:, 3:7, 4:12].sum().item(), 6 * 4 * 8)
        for frame, (y, x) in enumerate(((50, 3), (51, 5), (52, 7), (53, 9), (54, 11), (55, 13))):
            self.assertTrue(torch.all(generation[frame, y:y + 2, x:x + 2] == 1))
            self.assertFalse(torch.any(generation[frame, 3:7, 4:12]))
        self.assertEqual((crop_x, crop_y, crop_w, crop_h), (0, 0, 16, 8))
        self.assertTrue(torch.equal(combined, original))

    def test_region_touching_performer_in_late_frame_is_skipped_as_a_whole(self):
        combined = torch.zeros(4, 32, 48)
        performer = torch.zeros_like(combined)
        combined[:, 3:7, 4:12] = 1
        performer[-1, 6:10, 11:15] = 1

        crop, generation, _, _, _, _, has_text = self.node.adapt(
            combined, performer, self.details([self.region()]), context=0)

        self.assertFalse(has_text)
        self.assertEqual(crop.count_nonzero().item(), 0)
        self.assertIs(generation, combined)

    def test_region_within_32_pixels_of_performer_anywhere_is_skipped(self):
        combined = torch.zeros(3, 32, 64)
        performer = torch.zeros_like(combined)
        combined[:, 3:7, 4:12] = 1
        performer[1, 4:8, 40:44] = 1  # 28px from the panel, in only one frame.

        result = self.node.adapt(combined, performer, self.details([self.region()]), context=0)

        self.assertFalse(result[-1])
        self.assertIs(result[1], combined)

    def test_region_coordinates_scale_conservatively_to_mask_resolution(self):
        combined = torch.zeros(2, 32, 48)
        performer = torch.zeros_like(combined)
        combined[:, 4:10, 4:10] = 1
        region = self.region(x=2, y=2, width=3, height=3)

        crop, _, width, height, x, y, has_text = self.node.adapt(
            combined, performer, self.details([region], size=(24, 16)), context=0)

        self.assertTrue(has_text)
        self.assertEqual((x, y, width, height), (0, 0, 16, 16))
        self.assertTrue(torch.all(crop[:, 4:10, 4:10] == 1))

    def test_crop_uses_eight_pixel_alignment_and_clamps_at_canvas_edges(self):
        combined = torch.zeros(2, 32, 48)
        performer = torch.zeros_like(combined)
        combined[:, 26:32, 42:48] = 1

        crop, _, width, height, x, y, has_text = self.node.adapt(
            combined, performer, self.details([self.region(42, 26, 6, 6)]), context=8)

        self.assertTrue(has_text)
        self.assertEqual((x, y, width, height), (32, 16, 16, 16))
        self.assertEqual(tuple(crop.shape), (2, 16, 16))
        self.assertTrue(torch.all(crop[:, 10:16, 10:16] == 1))

    def test_no_text_returns_small_zero_crop_and_original_generation_mask(self):
        combined = torch.zeros(2, 5, 7, dtype=torch.float64)
        performer = torch.zeros_like(combined)
        combined[0, 1:3, 2:4] = 1

        crop, generation, width, height, x, y, has_text = self.node.adapt(
            combined, performer, self.details([]))

        self.assertFalse(has_text)
        self.assertIs(generation, combined)
        self.assertEqual((width, height, x, y), (7, 5, 0, 0))
        self.assertEqual(tuple(crop.shape), (2, 5, 7))
        self.assertEqual(crop.dtype, combined.dtype)
        self.assertEqual(crop.device, combined.device)

    def test_region_outside_approved_edit_mask_is_not_added(self):
        combined = torch.zeros(2, 32, 48)
        performer = torch.zeros_like(combined)
        combined[:, 20:24, 4:12] = 1

        crop, generation, _, _, _, _, has_text = self.node.adapt(
            combined, performer, self.details([self.region()]), context=0)

        self.assertFalse(has_text)
        self.assertIs(generation, combined)
        self.assertEqual(crop.count_nonzero().item(), 0)

    def test_nonfinite_masks_and_shape_mismatch_fail_without_mutation(self):
        combined = torch.zeros(2, 32, 48)
        performer = torch.zeros_like(combined)
        combined[0, 0, 0] = float("nan")
        original = combined.clone()
        with self.assertRaisesRegex(ValueError, "finite"):
            self.node.adapt(combined, performer, self.details([self.region()]))
        self.assertTrue(torch.equal(torch.nan_to_num(combined), torch.nan_to_num(original)))

        with self.assertRaisesRegex(ValueError, "matching frames"):
            self.node.adapt(torch.zeros(2, 32, 48), torch.zeros(2, 31, 48),
                            self.details([self.region()]))

    def test_mapping_exposes_the_artist_node(self):
        self.assertIs(removal.NODE_CLASS_MAPPINGS["ZuraTextBackgroundRepairMask"],
                      removal.ZuraTextBackgroundRepairMask)

    def test_whole_shot_guard_prevents_window_local_cleanup_near_future_performer(self):
        combined = torch.zeros(3, 128, 128)
        performer = torch.zeros_like(combined)
        performer[:, 110:114, 100:104] = 1
        combined[:, 110:114, 100:104] = 1
        combined[:, 3:7, 4:12] = 1
        details = self.details([self.region()], size=(128, 128))
        guard = (performer > 0.5).any(dim=0, keepdim=True).float()
        # The same performer approaches the panel later in this shot, outside
        # the present model window. That panel must keep its generation route.
        guard[:, 12:16, 10:14] = 1
        before = combined.clone(), performer.clone(), guard.clone()

        self.assertTrue(self.node.adapt(combined, performer, details, context=0)[-1])
        result = self.node.adapt(combined, performer, details, context=0, performer_guard=guard)

        self.assertFalse(result[-1])
        self.assertIs(result[1], combined)
        self.assertEqual(result[0].count_nonzero().item(), 0)
        self.assertTrue(all(torch.equal(a, b) for a, b in zip(before, (combined, performer, guard))))

    def test_shot_crop_and_repeated_frame_stay_equal_across_sparse_panel_windows(self):
        performer = torch.zeros(4, 128, 128)
        performer[:, 110:114, 100:104] = 1
        combined = performer.clone()
        combined[:3, 3:7, 4:12] = 1
        combined[3:, 9:13, 84:92] = 1
        details = self.details([self.region(), self.region(84, 9, 8, 4)], size=(128, 128))
        guard = (performer > 0.5).any(dim=0, keepdim=True).float()

        first = self.node.adapt(combined[:3], performer[:3], details, context=0, performer_guard=guard)
        second = self.node.adapt(combined[2:], performer[2:], details, context=0, performer_guard=guard)

        self.assertTrue(first[-1] and second[-1])
        self.assertEqual(first[2:6], second[2:6])
        self.assertEqual(first[2:6], (96, 16, 0, 0))
        self.assertTrue(torch.equal(first[0][-1], second[0][0]))
        self.assertTrue(torch.equal(first[1][-1], second[1][0]))
        # Stable crop geometry must not expand the actual editable pixels.
        self.assertEqual(first[0][:, 9:13, 84:92].count_nonzero().item(), 0)
        self.assertEqual(second[0][0, 9:13, 84:92].count_nonzero().item(), 0)
        self.assertTrue(torch.equal(first[1], performer[:3]))
        self.assertTrue(torch.equal(second[1], performer[2:]))

    def test_bad_or_incomplete_shot_guard_fails_before_cleanup(self):
        performer = torch.zeros(2, 64, 48)
        performer[:, 55, 40] = 1
        combined = performer.clone()
        combined[:, 3:7, 4:12] = 1
        details = self.details([self.region()], size=(48, 64))
        for guard, message in ((torch.zeros(2, 64, 48), "one mask"),
                               (torch.full((1, 64, 48), float("nan")), "finite"),
                               (torch.full((1, 64, 48), 1.1), "zero to one"),
                               (torch.zeros(1, 64, 48), "every genuine")):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.node.adapt(combined, performer, details, performer_guard=guard)
        self.assertTrue(torch.equal(combined[:, 3:7, 4:12], torch.ones(2, 4, 8)))


if __name__ == "__main__":
    unittest.main()
