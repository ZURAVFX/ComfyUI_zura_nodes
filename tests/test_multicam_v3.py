"""Fast structural tests; no diffusion models or GPU are needed."""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

import torch
from multicam_test_support import prepare_comfy_imports


prepare_comfy_imports()
MODULE = Path(__file__).resolve().parents[1] / "multicam_v3.py"
spec = importlib.util.spec_from_file_location("multicam_v3_tested", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class MulticamV3Tests(unittest.TestCase):
    def setUp(self):
        self.frames = torch.zeros((96, 32, 48, 3), dtype=torch.float32)
        self.frames[48] = 0.25
        self.frames[-1] = 0.75

    def test_four_shots_are_exact_and_source_sensitive(self):
        plan = mod._plan("show", self.frames, 24, "0,6,0,4")
        self.assertEqual((plan["shot_count"], plan["choices"]), (4, [0, 6, 0, 4]))
        result = mod.ZuraAssembleMulticamV3().assemble(
            self.frames, json.dumps(plan), angle_6=torch.ones_like(self.frames),
            angle_4=torch.ones_like(self.frames) * 0.5)[0]
        self.assertEqual(len(result), 96)
        self.assertEqual(result[18, 0, 0, 0].item(), 0)
        self.assertEqual(result[30, 0, 0, 0].item(), 1)
        self.assertEqual(result[48, 0, 0, 0].item(), .25)
        self.assertEqual(result[80, 0, 0, 0].item(), .5)
        changed = self.frames.clone()
        changed[-1] = 0.5
        with self.assertRaisesRegex(ValueError, "source"):
            mod.ZuraAssembleMulticamV3().assemble(changed, json.dumps(plan))

    def test_plan_mode_requests_only_candidates_and_blocks_h3(self):
        gallery = mod.ZuraAngleGalleryV3()
        self.assertEqual(gallery.check_lazy_status("1 · Plan angles"),
                         [f"candidate_{i}" for i in range(1, 10)])
        self.assertEqual(gallery.check_lazy_status("2 · Render multicam"), [])
        plan = mod._plan("show", self.frames, 24, "0,6,0,4")
        director = mod.ZuraH3MulticamV3()
        self.assertEqual(director.check_lazy_status("1 · Plan angles", json.dumps(plan)), [])
        result = director.render(self.frames, {}, json.dumps(plan), "1 · Plan angles", 42, 8, "test")
        self.assertEqual(type(result[0]).__name__, "ExecutionBlocker")

    def test_render_expands_native_chains_only_for_used_angles(self):
        plan = mod._plan("show", self.frames, 24, "0,6,0,4")
        director = mod.ZuraH3MulticamV3()
        expanded = director.render(
            self.frames, {}, json.dumps(plan), "2 · Render multicam", 42, 8, "test",
            reference_video=self.frames, moge_geometry=object(), model=object(),
            clip=object(), video_vae=object(), audio_vae=object())
        classes = [v["class_type"] for v in expanded["expand"].values()]
        self.assertEqual(classes.count("MiniMaxH3ReferenceToVideo"), 2)
        self.assertEqual(classes.count("CrossViewWarp"), 2)
        self.assertEqual(classes.count("ZuraSavedAngleV3"), 2)
        self.assertEqual(classes.count("ZuraAssembleMulticamV3"), 1)
        self.assertEqual(classes.count("TrimAudioDuration"), 1)
        warps = [v["inputs"] for v in expanded["expand"].values()
                 if v["class_type"] == "CrossViewWarp"]
        self.assertTrue(all(v["distance"] == 1.0 and v["keep_source_aim"] for v in warps))
        self.assertTrue(all(v["vertical_shift"] == 0.04 for v in warps))

    def test_safe_prompt_requires_uncropped_head(self):
        prompt = mod.ZuraSafeAnglePromptV3().build(
            "<sks> front view eye-level shot close-up", "close")[0]
        self.assertIn("medium close-up", prompt)
        self.assertIn("entire head and hair", prompt)
        self.assertNotIn("shot close-up", prompt)

    def test_repeatable_seed_has_no_positional_frontend_control(self):
        schema = mod.ZuraH3MulticamV3.INPUT_TYPES()
        self.assertIs(schema["required"]["seed"][1]["control_after_generate"], False)
        plan = mod._plan("show", self.frames, 24, "0,1,0,1")
        expanded = mod.ZuraH3MulticamV3().render(
            self.frames, {}, json.dumps(plan), "2 · Render multicam", (1 << 64) - 1, 8, "test",
            reference_video=self.frames, moge_geometry=object(), model=object(),
            clip=object(), video_vae=object(), audio_vae=object())
        noise = next(v["inputs"]["noise_seed"] for v in expanded["expand"].values()
                     if v["class_type"] == "RandomNoise")
        self.assertEqual(noise, 0)

    def test_close_angle_uses_safe_native_crop(self):
        plan = mod._plan("show", self.frames, 24, "8,8,8,8")
        expanded = mod.ZuraH3MulticamV3().render(
            self.frames, {}, json.dumps(plan), "2 · Render multicam", 42, 8, "test",
            reference_video=self.frames, moge_geometry=object(), model=object(),
            clip=object(), video_vae=object(), audio_vae=object())
        nodes = list(expanded["expand"].values())
        crop = next(v["inputs"] for v in nodes if v["class_type"] == "ImageCrop")
        self.assertEqual((crop["width"], crop["height"], crop["y"]), (40, 27, 1))
        self.assertEqual(sum(v["class_type"] == "ImageScale" for v in nodes), 1)

    def test_one_prompted_shot_renders_only_its_interval(self):
        plan = mod._plan("show", self.frames, 24, "0,6,0,6",
                         shot_prompts=json.dumps(["", "quick handheld zoom", "", ""]))
        expanded = mod.ZuraH3MulticamV3().render(
            self.frames, {}, json.dumps(plan), "2 · Render multicam", 42, 8, "base",
            reference_video=self.frames, moge_geometry=object(), model=object(),
            clip=object(), video_vae=object(), audio_vae=object())
        nodes = list(expanded["expand"].values())
        conditions = [v["inputs"] for v in nodes if v["class_type"] == "MiniMaxH3ReferenceToVideo"]
        self.assertEqual(len(conditions), 2)
        self.assertEqual(sum("quick handheld zoom" in v["prompt"] for v in conditions), 1)
        slices = [v["inputs"] for v in nodes if v["class_type"] == "GetImageRangeFromBatch"]
        self.assertEqual(len(slices), 2)
        self.assertTrue(all(v["start_index"] == 24 and v["num_frames"] == 24 for v in slices))
        segments = {"shot_2": torch.ones((24, 32, 48, 3)),
                    "angle_6": torch.full_like(self.frames, 0.5)}
        assembled = mod.ZuraAssembleMulticamV3().assemble(self.frames, json.dumps(plan), **segments)[0]
        self.assertEqual((assembled[30, 0, 0, 0].item(), assembled[80, 0, 0, 0].item()), (1, .5))

    def test_source_shot_cannot_have_motion_prompt(self):
        plan = mod._plan("show", self.frames, 24, "0,6,0,4",
                         shot_prompts=json.dumps(["zoom", "", "", ""]))
        with self.assertRaisesRegex(ValueError, "Select a generated angle"):
            mod.ZuraH3MulticamV3().render(
                self.frames, {}, json.dumps(plan), "2 · Render multicam", 42, 8, "base",
                reference_video=self.frames, moge_geometry=object(), model=object(),
                clip=object(), video_vae=object(), audio_vae=object())

    def test_plan_only_image_gate_blocks_render_previews(self):
        gate = mod.ZuraPlanOnlyImageV3()
        self.assertEqual(gate.check_lazy_status("1 · Plan angles"), ["image"])
        self.assertEqual(gate.check_lazy_status("2 · Render multicam"), [])
        self.assertEqual(gate.select("1 · Plan angles", self.frames)[0].shape, self.frames.shape)
        self.assertEqual(type(gate.select("2 · Render multicam")[0]).__name__, "ExecutionBlocker")

    def test_v3_rejects_scene_swap_and_v4_anchors_full_scene(self):
        plan = mod._plan("show", self.frames, 24, "5,8,5,8",
                         shot_prompts=json.dumps(["", "steady camera", "", ""]))
        with self.assertRaisesRegex(ValueError, "V3 preserves the source environment"):
            mod.ZuraH3MulticamV3().render(
                self.frames, {}, json.dumps(plan), "2 · Render multicam", 42, 8, "base",
                reference_video=self.frames, moge_geometry=object(), model=object(),
                clip=object(), video_vae=object(), audio_vae=object(),
                look_enabled=True, background_mode="Custom environment")
        expanded = mod.ZuraH3MulticamV4().render(
            self.frames, {}, json.dumps(plan), "2 · Render multicam", 42, 8, "base",
            reference_video=self.frames, moge_geometry=object(), model=object(),
            clip=object(), video_vae=object(), audio_vae=object(),
            pose_video=self.frames, model_patch=object(),
            look_enabled=True, background_mode="Custom environment")
        condition = next(v["inputs"] for v in expanded["expand"].values()
                         if v["class_type"] == "MiniMaxH3ImageToVideo"
                         and "steady camera" in v["inputs"]["prompt"])
        self.assertIn("same physical set", condition["prompt"])
        self.assertIn("steady camera", condition["prompt"])
        self.assertEqual(condition["length"], 39)
        self.assertIn("first_frame", condition)
        self.assertIn("last_frame", condition)
        self.assertFalse(any(v["class_type"] == "CrossViewWarp"
                             for v in expanded["expand"].values()))
        self.assertTrue(any(v["class_type"] == "MiniMaxH3FunControlNetApply"
                            for v in expanded["expand"].values()))
        control = next(v["inputs"] for v in expanded["expand"].values()
                       if v["class_type"] == "MiniMaxH3FunControlNetApply")
        self.assertEqual((control["strength"], control["end_percent"]), (.45, .55))
        guide = next(v["inputs"] for v in expanded["expand"].values()
                     if v["class_type"] == "MiniMaxH3AddGuide")
        self.assertIn("audio", guide)
        self.assertNotIn("image", guide)
        assembled = next(v["inputs"] for v in expanded["expand"].values()
                         if v["class_type"] == "ZuraAssembleMulticamV3")
        self.assertNotIn("scene_frames", assembled)


if __name__ == "__main__":
    unittest.main()
