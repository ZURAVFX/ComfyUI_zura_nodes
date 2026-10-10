"""Text panels stay removed through a shot without holding performer motion."""
import importlib
import sys
import types
import unittest

import v2_bootstrap
import torch

NAME = "ComfyUI_zura_nodes.artist_studio"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[NAME] = package
removal = importlib.import_module(NAME + ".text_removal")


class TextRemovalTests(unittest.TestCase):
    def masks(self, count=24, height=32, width=48):
        return torch.zeros(count, height, width), torch.zeros(count, height, width), [[] for _ in range(count)]

    def test_brief_title_remains_removed_after_long_detection_gap(self):
        body, text, boxes = self.masks()
        boxes[2] = [{"x": 4, "y": 3, "width": 18, "height": 5}]
        body[0, 20:25, 3:8] = 1
        body[-1, 20:25, 30:35] = 1
        original = body.clone()
        clip = {"frames": 24, "width": 48, "height": 32}
        result, details = removal.GenjTextRemovalMask().combine(body, text, boxes, clip, padding=0)
        self.assertTrue(torch.all(result[:, 3:8, 4:22] == 1))
        self.assertEqual(result[-1, 20:25, 3:8].count_nonzero(), 0)
        self.assertEqual(result[0, 20:25, 30:35].count_nonzero(), 0)
        self.assertTrue(torch.equal(body, original))
        self.assertNotIn("text_regions", clip)
        self.assertEqual(details["text_frames_detected"], 1)
        self.assertEqual(details["text_regions"], [{"x": 4, "y": 3, "width": 18, "height": 5}])
        self.assertTrue(details["text_regions_held"])

    def test_disabled_hold_retains_local_seven_frame_flicker_window(self):
        body, text, boxes = self.masks()
        text[10, 2:5, 4:8] = 1
        result, details = removal.GenjTextRemovalMask().combine(body, text, boxes, {}, padding=0, hold_regions=False)
        self.assertEqual([i for i in range(24) if result[i].any()], list(range(7, 14)))
        self.assertFalse(details["text_regions_held"])

    def test_mask_only_detection_is_held_and_records_complete_panel(self):
        body, text, boxes = self.masks()
        text[1, 3, 4:9] = 1
        text[1, 4:7, 4] = 1
        result, details = removal.GenjTextRemovalMask().combine(body, text, boxes, {}, padding=0)
        self.assertTrue(torch.all(result[:, 3:7, 4:9] == 1))
        self.assertEqual(details["text_boxes_detected"], 0)
        self.assertEqual(details["text_frames_detected"], 1)

    def test_regions_and_boxes_use_performer_review_resolution(self):
        body = torch.zeros(12, 32, 48)
        text = torch.zeros(12, 16, 24)
        boxes = [[] for _ in range(12)]
        boxes[0] = [{"x": 2, "y": 3, "width": 5, "height": 4}]
        result, details = removal.GenjTextRemovalMask().combine(body, text, boxes, {}, padding=0)
        self.assertEqual(details["text_regions_size"], [48, 32])
        self.assertEqual(details["text_regions"], [{"x": 4, "y": 6, "width": 10, "height": 8}])
        self.assertEqual(result[0].sum().item(), 80)

    def test_invalid_boxes_are_ignored_and_partial_boxes_clip_with_padding(self):
        body, text, boxes = self.masks()
        boxes[1] = [{}, None, "invalid", {"x": float("nan"), "y": 0, "width": 3, "height": 4},
                    {"x": 0, "y": 0, "width": -2, "height": 4},
                    {"x": 1.7e308, "y": 0, "width": 1.7e308, "height": 4},
                    {"x": 200, "y": 0, "width": 3, "height": 4},
                    {"x": -2, "y": -1, "width": 5, "height": 4}]
        result, details = removal.GenjTextRemovalMask().combine(body, text, boxes, {}, padding=1)
        self.assertEqual(details["text_boxes_detected"], 1)
        self.assertEqual(details["text_frames_detected"], 1)
        self.assertEqual(details["text_regions"], [{"x": 0, "y": 0, "width": 5, "height": 5}])
        self.assertEqual(result[0].sum().item(), 25)

    def test_many_glyph_detections_remain_bounded_and_all_covered(self):
        body, text, boxes = self.masks(height=96, width=144)
        text[2, 1::6, 1::6] = 1
        result, details = removal.GenjTextRemovalMask().combine(body, text, boxes, {}, padding=0)
        self.assertLessEqual(len(details["text_regions"]), 12)
        self.assertTrue(torch.all(result[-1][text[2].bool()] == 1))
        for region in details["text_regions"]:
            self.assertTrue(all(isinstance(value, int) for value in region.values()))
            self.assertGreater(region["width"], 0)
            self.assertLessEqual(region["x"] + region["width"], 144)
            self.assertLessEqual(region["y"] + region["height"], 96)

    def test_empty_text_does_not_union_the_performer(self):
        body, text, boxes = self.masks()
        body[4, 10:15, 20:25] = 1
        result, details = removal.GenjTextRemovalMask().combine(body, text, boxes, {}, padding=0)
        self.assertTrue(torch.equal(result, body))
        self.assertEqual(details["text_regions"], [])

    def test_frame_count_mismatch_fails_before_processing(self):
        body, text, boxes = self.masks()
        with self.assertRaisesRegex(ValueError, "same frames"):
            removal.GenjTextRemovalMask().combine(body, text[:-1], boxes, {})


if __name__ == "__main__":
    unittest.main()
