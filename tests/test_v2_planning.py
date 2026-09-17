"""Standalone tests for the v2 chunk planner and cut detector."""
from __future__ import annotations

import unittest

import v2_bootstrap  # noqa: F401  (path + stub setup)
from ComfyUI_zura_nodes import planning

import torch


class PlanningTests(unittest.TestCase):
    def test_plan_shots_never_crosses_cut_and_has_five_frame_overlap(self):
        plan = planning.plan_chunks(100, 41, 5, [50])
        self.assertEqual(sum(p.output_count for p in plan), 100)
        self.assertTrue(all((p.shot_index == 0 and p.window_start < 50) or (p.shot_index == 1 and p.window_start >= 50)
                            for p in plan))
        self.assertEqual([(p.output_start, p.output_count, p.anchor_frames) for p in plan],
                         [(0, 41, 0), (41, 9, 5), (50, 41, 0), (91, 9, 5)])
        # Continuation windows begin on the predecessor's real tail: the shared
        # frames are the native continue_motion anchor and the blend zone.
        self.assertEqual([(p.window_start, p.window_count, p.blend_frames) for p in plan],
                         [(0, 41, 5), (36, 14, 0), (50, 41, 5), (86, 14, 0)])
        planning.validate_plan(plan, 100)

    def test_continuation_never_reaches_across_a_shot_boundary(self):
        # The first chunk of every shot starts unconditioned: at a cut the join
        # is a hard cut, exactly as the source has it.
        plan = planning.plan_chunks(200, 41, 5, [60, 120])
        self.assertEqual([p.anchor_frames for p in plan if p.output_start in (0, 60, 120)], [0, 0, 0])
        self.assertEqual([p.anchor_frames for p in plan if p.output_start not in (0, 60, 120)], [5] * 4)
        shot_starts = (0, 60, 120)
        for part in plan:
            # No window may reach back before the start of its own shot.
            self.assertGreaterEqual(part.window_start, shot_starts[part.shot_index])
            self.assertLess(part.window_start, 120 if part.shot_index == 1 else (60 if part.shot_index == 0 else 200))

    def test_overlap_larger_than_half_a_chunk_is_rejected(self):
        # A continuation chunk both receives and hands on ``overlap`` frames, so
        # its generated span must be at least that long or its blend zone and
        # its output would overlap.
        with self.assertRaisesRegex(ValueError, "at most half of chunk_frames"):
            planning.plan_chunks(100, 13, 9)

    def test_tail_is_padded_inside_shot(self):
        p = planning.plan_chunks(42, 41, 5)[-1]
        self.assertEqual((p.output_start, p.output_count, p.window_start, p.window_count), (41, 1, 36, 6))
        self.assertEqual(p.anchor_frames, 5)
        self.assertEqual(planning.sampling_frames(p), 9)

    def test_ten_seconds_needs_seven_continuous_loops(self):
        plan = planning.plan_chunks(240, 41, 5)
        self.assertEqual(len(plan), 7)
        self.assertEqual(sum(p.output_count for p in plan), 240)
        self.assertEqual(planning.sampling_frames(plan[-1]), 25)

    def test_invalid_chunk_geometry_is_rejected(self):
        with self.assertRaises(ValueError):
            planning.plan_chunks(100, 40, 5)
        with self.assertRaises(ValueError):
            planning.plan_chunks(100, 41, 3)

    def test_cut_parsing_is_strict_and_deduplicated(self):
        self.assertEqual(planning.parse_cut_frames("5, 5", 10), [5])
        self.assertEqual(planning.parse_cut_frames("3;7", 10), [3, 7])
        self.assertEqual(planning.parse_cut_frames("", 10), [])
        with self.assertRaisesRegex(ValueError, "non-integer"):
            planning.parse_cut_frames("4,abc", 10)
        with self.assertRaisesRegex(ValueError, "between 1 and 9"):
            planning.parse_cut_frames("0,99", 10)
        with self.assertRaisesRegex(ValueError, "between 1 and 9"):
            planning.plan_chunks(10, 41, 5, cuts=[-1, 10])

    def test_detect_cuts_finds_a_hard_edit(self):
        x = torch.zeros((10, 8, 8, 3))
        x[5:] = 1
        self.assertIn(5, planning.detect_cuts(x, .2))

    def test_hold_last_pads_by_repeating_the_final_frame(self):
        value = torch.arange(6, dtype=torch.float32).view(6, 1, 1, 1)
        held = planning.hold_last(value[:4], 6)
        self.assertEqual(tuple(held.shape), (6, 1, 1, 1))
        self.assertTrue(torch.equal(held[4], held[3]))


if __name__ == "__main__":
    unittest.main()
