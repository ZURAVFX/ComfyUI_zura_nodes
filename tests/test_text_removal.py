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

    def tracking_segments(self):
        return {"version": 1, "frames": 24, "height": 40, "width": 60, "cuts": [12],
                "segments": [{"start": 0, "end": 12, "frames": 12},
                             {"start": 12, "end": 24, "frames": 12}]}

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
        self.assertNotIn("text_regions_by_shot", details)

    def test_disabled_hold_retains_local_seven_frame_flicker_window(self):
        body, text, boxes = self.masks()
        text[10, 2:5, 4:8] = 1
        result, details = removal.GenjTextRemovalMask().combine(body, text, boxes, {}, padding=0, hold_regions=False)
        self.assertEqual([i for i in range(24) if result[i].any()], list(range(7, 14)))
        self.assertFalse(details["text_regions_held"])

    def test_disabled_hold_fills_only_local_component_bounds_for_seven_frames(self):
        body, text, boxes = self.masks(height=40, width=60)
        text[10, 5, 5:10] = 1
        text[10, 6:10, 5] = 1
        text[10, 5:7, 30:33] = 1
        body[0, 25:29, 5:9] = 1
        body[-1, 25:29, 45:49] = 1
        original_body, original_text = body.clone(), text.clone()

        result, details = removal.GenjTextRemovalMask().combine(
            body, text, boxes, {}, padding=0, hold_regions=False)

        self.assertTrue(torch.all(result[7:14, 5:10, 5:10] == 1))
        self.assertTrue(torch.all(result[7:14, 5:7, 30:33] == 1))
        self.assertFalse(result[[6, 14], 5:10, 5:10].any())
        self.assertFalse(result[[6, 14], 5:7, 30:33].any())
        self.assertFalse(result[:, 5:10, 15:30].any())
        self.assertTrue(torch.equal(result[0, 25:29, 5:9], body[0, 25:29, 5:9]))
        self.assertTrue(torch.equal(result[-1, 25:29, 45:49], body[-1, 25:29, 45:49]))
        self.assertFalse(result[-1, 25:29, 5:9].any())
        self.assertFalse(result[0, 25:29, 45:49].any())
        self.assertTrue(torch.equal(body, original_body))
        self.assertTrue(torch.equal(text, original_text))
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

    def test_compacted_regions_do_not_fill_sparse_gaps_or_moving_text_path(self):
        body, text, boxes = self.masks(count=24, height=240, width=420)
        for row in range(4):
            for column in range(10):
                x, y = 8 + column * 40, 8 + row * 45
                text[3, y:y + 2, x:x + 3] = 1
        # The same panel is detected at opposite ends of the shot. Holding both
        # locations must not fill the background between them.
        text[0, 200:206, 8:16] = 1
        text[-1, 200:206, 400:408] = 1
        original_body, original_text = body.clone(), text.clone()

        result, details = removal.GenjTextRemovalMask().combine(body, text, boxes, {}, padding=0)

        self.assertLessEqual(len(details["text_regions"]), 12)
        self.assertTrue(any(region["width"] > 300 for region in details["text_regions"]))
        self.assertTrue(torch.all(result[:, text[3].bool()] == 1))
        self.assertTrue(torch.all(result[:, 8:10, 8:11] == 1))
        self.assertTrue(torch.all(result[:, 200:206, 8:16] == 1))
        self.assertTrue(torch.all(result[:, 200:206, 400:408] == 1))
        self.assertFalse(result[:, 8:10, 16:48].any())
        self.assertFalse(result[:, 200:206, 16:400].any())
        self.assertTrue(torch.equal(body, original_body))
        self.assertTrue(torch.equal(text, original_text))

    def test_tracking_segments_hold_each_shot_without_cross_contamination(self):
        for hold_regions in (True, False):
            with self.subTest(hold_regions=hold_regions):
                body, text, boxes = self.masks(count=24, height=40, width=60)
                text[10, 4, 4:9] = 1
                text[10, 5:9, 4] = 1
                text[14, 4, 40:45] = 1
                text[14, 5:9, 40] = 1
                body[0, 25:28, 5:8] = 1
                body[-1, 25:28, 52:55] = 1
                original_body, original_text = body.clone(), text.clone()

                result, details = removal.GenjTextRemovalMask().combine(
                    body, text, boxes, {}, padding=0, hold_regions=hold_regions,
                    tracking_segments=self.tracking_segments())

                if hold_regions:
                    first_frames, second_frames = range(0, 12), range(12, 24)
                else:
                    first_frames, second_frames = range(7, 12), range(12, 18)
                self.assertTrue(torch.all(result[list(first_frames), 4:9, 4:9] == 1))
                self.assertTrue(torch.all(result[list(second_frames), 4:9, 40:45] == 1))
                self.assertFalse(result[:, 4:9, 4:9][list(second_frames)].any())
                self.assertFalse(result[:, 4:9, 40:45][list(first_frames)].any())
                self.assertFalse(result[12:, 4:9, 4:9].any())
                self.assertFalse(result[:12, 4:9, 40:45].any())
                self.assertTrue(torch.equal(result[0, 25:28, 5:8], body[0, 25:28, 5:8]))
                self.assertTrue(torch.equal(result[-1, 25:28, 52:55], body[-1, 25:28, 52:55]))
                self.assertFalse(result[-1, 25:28, 5:8].any())
                self.assertFalse(result[0, 25:28, 52:55].any())
                self.assertEqual(details["text_regions"], [
                    {"x": 4, "y": 4, "width": 5, "height": 5},
                    {"x": 40, "y": 4, "width": 5, "height": 5}])
                self.assertEqual(details["text_regions_by_shot"], [
                    {"start": 0, "end": 12,
                     "regions": [{"x": 4, "y": 4, "width": 5, "height": 5}]},
                    {"start": 12, "end": 24,
                     "regions": [{"x": 40, "y": 4, "width": 5, "height": 5}]}])
                self.assertEqual(details["text_regions_held"], hold_regions)
                self.assertTrue(torch.equal(body, original_body))
                self.assertTrue(torch.equal(text, original_text))

    def test_tracking_segment_metadata_rejects_zero_cuts_and_length_or_raster_mismatch(self):
        body, text, boxes = self.masks(count=24, height=40, width=60)
        invalid = []

        zero_cut = self.tracking_segments()
        zero_cut["cuts"] = [0]
        invalid.append((zero_cut, "cuts do not match"))

        wrong_length = self.tracking_segments()
        wrong_length["frames"] = 25
        invalid.append((wrong_length, "cover all source frames"))

        gap = self.tracking_segments()
        gap["cuts"] = [13]
        gap["segments"][1] = {"start": 13, "end": 24, "frames": 11}
        invalid.append((gap, "cover the source once"))

        wrong_raster = self.tracking_segments()
        wrong_raster["width"] = 61
        invalid.append((wrong_raster, "frame count and raster"))

        wrong_input_count = {"version": 1, "frames": 25, "height": 40, "width": 60,
                             "cuts": [12],
                             "segments": [{"start": 0, "end": 12, "frames": 12},
                                          {"start": 12, "end": 25, "frames": 13}]}
        invalid.append((wrong_input_count, "frame count and raster"))

        for metadata, message in invalid:
            with self.subTest(metadata=metadata):
                with self.assertRaisesRegex(ValueError, message):
                    removal.GenjTextRemovalMask().combine(
                        body, text, boxes, {}, padding=0, tracking_segments=metadata)

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
