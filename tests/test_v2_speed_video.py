"""Standalone tests for the Zura Wan 2.2 Turbo Switch and VIDEO assembly."""
from __future__ import annotations

import unittest

import v2_bootstrap  # noqa: F401
from ComfyUI_zura_nodes import speed, video

import torch
from fractions import Fraction


class SpeedTests(unittest.TestCase):
    def test_quality_does_not_request_acceleration_branch(self):
        node = speed.ZuraWan22TurboSwitch()
        base = object()
        self.assertEqual(node.check_lazy_status(turbo=False), ['base_model'])
        self.assertEqual(node.check_lazy_status(turbo=False, base_model=base), [])
        self.assertEqual(node.select(turbo=False, base_model=base), (base, 40, 5.0))

    def test_turbo_uses_visible_acceleration_branch(self):
        node = speed.ZuraWan22TurboSwitch()
        accelerated = object()
        self.assertEqual(node.check_lazy_status(turbo=True), ['accelerated_model'])
        self.assertEqual(node.check_lazy_status(turbo=True, accelerated_model=accelerated), [])
        for steps in (4, 6, 8):
            self.assertEqual(node.select(turbo=True, accelerated_steps=steps, accelerated_model=accelerated), (accelerated, steps, 1.0))

    def test_disconnected_branch_raises(self):
        with self.assertRaisesRegex(ValueError, "Connect the selected model branch"):
            speed.ZuraWan22TurboSwitch().select(turbo=True, accelerated_model=None)

    def test_node_is_named_after_wan_22(self):
        # The turbo/quality ratios are Wan 2.2 specific, so the node says so.
        self.assertIs(speed.NODE_CLASS_MAPPINGS["TrendStudioV2Speed"], speed.ZuraWan22TurboSwitch)
        self.assertEqual(speed.NODE_DISPLAY_NAME_MAPPINGS["TrendStudioV2Speed"], "Zura Wan 2.2 Turbo Switch")
        self.assertEqual(speed.ZuraWan22TurboSwitch.CATEGORY, "Zura")


class VideoAssemblyTests(unittest.TestCase):
    def test_components_trim_audio_to_frame_count(self):
        frames = torch.zeros((48, 8, 8, 3))
        audio = {"sample_rate": 32000, "waveform": torch.zeros((1, 2, 64000))}
        components = video.components_from_frames(frames, audio, 24)
        self.assertEqual(tuple(components["images"].shape), (48, 8, 8, 3))
        self.assertEqual(int(components["audio"]["waveform"].shape[-1]), 64000)
        self.assertEqual(components["frame_rate"], Fraction("24"))

    def test_components_reject_bad_shapes(self):
        with self.assertRaises(ValueError):
            video.components_from_frames(torch.zeros((4, 8, 8)))
        with self.assertRaises(ValueError):
            video.components_from_frames(torch.zeros((4, 8, 8, 3)), audio={"waveform": torch.zeros(1)})

    def test_video_output_falls_back_to_components_without_comfy(self):
        frames = torch.zeros((4, 8, 8, 3))
        out = video.video_output(frames, None, 24)
        if isinstance(out, dict):
            self.assertEqual(int(out["images"].shape[0]), 4)
        else:
            self.assertTrue(hasattr(out, "get_components"))


if __name__ == "__main__":
    unittest.main()
