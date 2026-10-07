"""Exercise clean-render expansion and planning checks without loading models."""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

import torch
from multicam_test_support import prepare_comfy_imports

prepare_comfy_imports()
spec = importlib.util.spec_from_file_location(
    "multicam_v4_tested", Path(__file__).resolve().parents[1] / "multicam_v4_clean.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CleanMulticamTests(unittest.TestCase):
    def setUp(self):
        self.frames = torch.zeros((48, 16, 16, 3))
        self.plan = json.dumps({"frame_count": 48, "frames_per_shot": 24,
                                "shot_count": 2, "choices": [0, 1], "shot_prompts": ["", ""]})

    def test_look_off_passes_h3_frames_and_original_audio_without_models(self):
        renderer = mod.ZuraCleanMulticamV4()
        self.assertEqual(renderer.check_lazy_status(False, h3_frames=self.frames), [])
        result = renderer.render(self.frames, {}, self.plan, False, "", h3_frames=self.frames)
        self.assertIs(result["result"][0], self.frames)
        nodes = list(result["expand"].values())
        self.assertEqual([node["class_type"] for node in nodes], ["TrimAudioDuration"])
        self.assertEqual(nodes[0]["inputs"]["duration"], 2.0)

    def test_look_on_uses_pre_generation_control_and_preserves_shot_boundaries(self):
        inputs = {name: object() for name in mod.MODEL_INPUTS}
        result = mod.ZuraCleanMulticamV4().render(
            self.frames, {}, self.plan, True, "Grey photography studio",
            width=832, height=480, h3_frames=self.frames, **inputs)
        nodes = list(result["expand"].values())
        takes = [node["inputs"] for node in nodes if node["class_type"] == "WanVaceToVideo"]
        self.assertEqual([take["length"] for take in takes], [49, 25])
        self.assertEqual(sum(node["class_type"] == "ZuraMatchMouthMotion" for node in nodes), 1)
        self.assertEqual(sum(node["class_type"] == "ZuraIDV2VForegroundControl" for node in nodes), 2)
        self.assertFalse(any("Composite" in node["class_type"] for node in nodes))
        self.assertTrue(any(node["class_type"] == "ImageFromBatch" and
                            node["inputs"]["batch_index"] == 24 and node["inputs"]["length"] == 24
                            for node in nodes))

    def test_invalid_or_gapped_shots_are_rejected(self):
        bad = json.dumps({"frame_count": 48, "shots": [
            {"start": 0, "count": 24, "angle": 0}, {"start": 25, "count": 23, "angle": 1}]})
        with self.assertRaisesRegex(ValueError, "no gaps or overlaps"):
            mod.parse_shots(bad, 48)

    def test_seed_widgets_have_no_synthetic_control(self):
        schema = mod.ZuraCleanMulticamV4.INPUT_TYPES()["required"]
        self.assertIs(schema["seed"][1]["control_after_generate"], False)
        self.assertIs(schema["klein_seed"][1]["control_after_generate"], False)


if __name__ == "__main__":
    unittest.main()
