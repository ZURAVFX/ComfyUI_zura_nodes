"""Shot boundaries and mask assembly preserve native tracking data."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch

import v2_bootstrap
import torch

NAME = "ComfyUI_zura_nodes.artist_studio"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[NAME] = package
tracking = importlib.import_module(NAME + ".cut_tracking")


class CutTrackingTests(unittest.TestCase):
    def split(self, frames, cuts):
        with patch.object(tracking, "detect_cuts", return_value=cuts):
            return tracking.ZuraSplitTrackingShots().split(frames)

    def test_real_hard_cut_splits_native_views_and_all_frames_join_in_order(self):
        frames = torch.zeros(40, 8, 12, 3)
        frames[20:] = 1
        original = frames.clone()
        shots, firsts, manifest = tracking.ZuraSplitTrackingShots().split(frames)
        self.assertEqual(manifest["cuts"], [20])
        self.assertEqual([len(shot) for shot in shots], [20, 20])
        self.assertTrue(torch.equal(torch.cat(shots), frames))
        self.assertTrue(torch.equal(firsts[1], frames[20:21]))
        self.assertEqual(shots[0].untyped_storage().data_ptr(), frames.untyped_storage().data_ptr())
        masks = [torch.full((20, 8, 12), .6), torch.ones(20, 8, 12)]
        result, coverage = tracking.ZuraJoinTrackingMasks().join(masks, [manifest])
        self.assertTrue(torch.equal(result, torch.cat(masks)))
        self.assertTrue(torch.equal(frames, original))
        self.assertTrue(torch.all(masks[0] == .6))
        self.assertTrue(coverage["cut_reselection_requires_review"])
        self.assertEqual(coverage["near_empty_frames"], 0)

    def test_gradual_exposure_and_small_moving_object_do_not_split(self):
        frames = torch.zeros(60, 32, 32, 3)
        frames[:, :, :, :] = torch.linspace(.1, .5, 60)[:, None, None, None]
        for index in range(60):
            frames[index, 12:16, index % 24:index % 24 + 4] = .8
        _, _, manifest = tracking.ZuraSplitTrackingShots().split(frames)
        self.assertEqual(manifest["cuts"], [])

    def test_one_frame_is_one_native_batch(self):
        frames = torch.ones(1, 4, 5, 3)
        shots, firsts, manifest = tracking.ZuraSplitTrackingShots().split(frames)
        self.assertEqual(len(shots), 1)
        self.assertEqual(len(firsts), 1)
        result, _ = tracking.ZuraJoinTrackingMasks().join([torch.ones(1, 4, 5)], [manifest])
        self.assertEqual(tuple(result.shape), (1, 4, 5))

    def test_first_last_duplicate_or_unsorted_boundaries_rejected(self):
        for cuts in ([0], [20], [5, 5], [8, 4]):
            with self.subTest(cuts=cuts), self.assertRaisesRegex(ValueError, "boundaries"):
                self.split(torch.ones(20, 4, 5, 3), cuts)

    def test_missing_extra_or_wrong_length_native_outputs_rejected(self):
        _, _, manifest = self.split(torch.ones(30, 4, 5, 3), [15])
        for masks in ([torch.ones(30, 4, 5)], [torch.ones(15, 4, 5)] * 3,
                      [torch.ones(14, 4, 5), torch.ones(16, 4, 5)],
                      [torch.ones(15, 4, 6), torch.ones(15, 4, 6)]):
            with self.subTest(shapes=[tuple(m.shape) for m in masks]), self.assertRaises(ValueError):
                tracking.ZuraJoinTrackingMasks().join(masks, [manifest])

    def test_manifest_cannot_omit_repeat_or_reorder_frames(self):
        _, _, manifest = self.split(torch.ones(30, 4, 5, 3), [15])
        for key, value in (("start", 14), ("end", 29), ("frames", 16)):
            changed = {**manifest, "segments": [dict(s) for s in manifest["segments"]]}
            changed["segments"][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                tracking.ZuraJoinTrackingMasks().join([torch.ones(15, 4, 5)] * 2, [changed])
        with self.assertRaises(ValueError):
            tracking.ZuraJoinTrackingMasks().join([torch.ones(15, 4, 5)] * 2, [manifest, manifest])

    def test_brief_and_sustained_absence_preserved_with_exact_ranges(self):
        _, _, manifest = self.split(torch.ones(40, 32, 32, 3), [])
        mask = torch.ones(40, 32, 32)
        mask[10:21] = 0
        result, coverage = tracking.ZuraJoinTrackingMasks().join([mask], [manifest])
        self.assertTrue(torch.equal(result, mask))
        self.assertEqual(coverage["shots"][0]["near_empty_ranges"], [{"start": 10, "end": 21, "frames": 11}])
        mask[21] = 0
        result, coverage = tracking.ZuraJoinTrackingMasks().join([mask], [manifest])
        self.assertTrue(torch.equal(result, mask))
        self.assertEqual(coverage["shots"][0]["near_empty_ranges"], [{"start": 10, "end": 22, "frames": 12}])

    def test_empty_tail_and_tiny_remnants_are_reported_without_filling(self):
        _, _, manifest = self.split(torch.ones(40, 32, 32, 3), [35])
        result, coverage = tracking.ZuraJoinTrackingMasks().join([torch.ones(35, 32, 32), torch.zeros(5, 32, 32)], [manifest])
        self.assertFalse(result[35:].any())
        self.assertEqual(coverage["shots"][1]["near_empty_ranges"], [{"start": 35, "end": 40, "frames": 5}])
        _, _, manifest = self.split(torch.ones(20, 64, 64, 3), [])
        speck = torch.zeros(20, 64, 64)
        speck[:, 0, 0] = 1
        result, coverage = tracking.ZuraJoinTrackingMasks().join([speck], [manifest])
        self.assertTrue(torch.equal(result, speck))
        self.assertEqual(coverage["near_empty_frames"], 20)

    def test_entirely_empty_tracking_is_data_not_a_person_presence_claim(self):
        _, _, manifest = self.split(torch.ones(20, 4, 5, 3), [])
        mask = torch.zeros(20, 4, 5)
        result, coverage = tracking.ZuraJoinTrackingMasks().join([mask], [manifest])
        self.assertTrue(torch.equal(result, mask))
        self.assertEqual(coverage["near_empty_frames"], 20)
        self.assertFalse(coverage["cut_reselection_requires_review"])

    def test_bad_dtype_and_nonfinite_or_out_of_range_masks_rejected(self):
        _, _, manifest = self.split(torch.ones(30, 4, 5, 3), [15])
        with self.assertRaisesRegex(ValueError, "dtype"):
            tracking.ZuraJoinTrackingMasks().join([torch.ones(15, 4, 5), torch.ones(15, 4, 5, dtype=torch.float64)], [manifest])
        for value in (float("nan"), float("inf"), -.1, 1.1):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite values"):
                tracking.ZuraJoinTrackingMasks().join([torch.full((15, 4, 5), value), torch.ones(15, 4, 5)], [manifest])

    def test_empty_or_non_rgb_frames_rejected(self):
        for shape in ((0, 4, 5, 3), (1, 4, 5, 4), (1, 4, 5), (1, 0, 5, 3)):
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                tracking.ZuraSplitTrackingShots().split(torch.empty(shape))


if __name__ == "__main__":
    unittest.main()
