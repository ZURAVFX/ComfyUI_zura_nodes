"""Structural checks for the local Layout-to-Render route, without inference."""
import copy
import unittest

from test_ltx25_native_plan import inputs, plan_module


def viewport_inputs():
    project, kwargs = inputs("silent")
    project["config"]["viewport_render"] = True
    project.pop("character")  # A composed scene plate is sufficient.
    kwargs["models"] = dict(plan_module.VIEWPORT_MODELS)
    kwargs["model_pins"] = {name: {"sha": "b" * 64} for name in (*kwargs["models"], "text_encoder")}
    kwargs["timeline"].update(frames=360, width=1920, height=1080, has_audio=False)
    return project, kwargs


class ViewportPlanTests(unittest.TestCase):
    def test_native_guides_survive_both_stages_and_crop_before_cache(self):
        plan = plan_module.build_plan(*viewport_inputs()[:1], **viewport_inputs()[1])
        for phase in ("stage1", "refine"):
            graph = plan["phases"][phase]
            self.assertEqual(graph["layout_guide"]["inputs"]["frame_idx"], 0)
            self.assertEqual(graph["appearance_guide"]["inputs"]["frame_idx"], -1)
            self.assertEqual(graph["layout_adapter"]["inputs"]["lora_name"], plan_module.VIEWPORT_MODELS["union"])
            artifact = "stage1_video" if phase == "stage1" else "stage2_video"
            self.assertEqual(graph["save_" + artifact]["inputs"]["samples"], ["crop_guides", 2])
            self.assertIn("layout", plan["dependencies"][phase])
        all_types = {n["class_type"] for g in plan["phases"].values() for n in g.values()}
        self.assertNotIn("DWPreprocessor", all_types)
        self.assertNotIn("LTXVImgToVideoInplace", all_types)
        self.assertEqual(plan["appearance_reference_role"], "composed_scene_plate_at_rope_minus_one")
        self.assertEqual(plan["basis"]["route"], "viewport_layout_to_render")
        self.assertNotIn("VideoDepthAnythingProcess", all_types)
        self.assertNotIn("CannyEdgePreprocessor", all_types)

    def test_actual_delivery_uses_valid_source_interval_without_repeated_tail(self):
        project, kwargs = viewport_inputs()
        plan = plan_module.build_plan(project, **kwargs)
        self.assertEqual(plan["delivered_frames"], 353)
        self.assertEqual(plan["basis"]["timeline"]["frames"], 360)
        self.assertEqual(plan["basis"]["frames"], plan["delivered_frames"])
        self.assertEqual(plan["basis"]["base"], [960, 544])
        self.assertEqual(plan["basis"]["native"], [1920, 1088])
        self.assertEqual(plan["trimmed_tail_frames"], 7)
        self.assertEqual(plan["artifacts"]["layout"]["frames"], 353)
        self.assertEqual(plan["phases"]["decode"]["trim_frames"]["inputs"]["length"], 353)
        self.assertNotIn("audio", plan["phases"]["decode"]["create_video"]["inputs"])
        kwargs["timeline"]["frames"] = 121
        self.assertEqual(plan_module.build_plan(project, **kwargs)["trimmed_tail_frames"], 0)

    def test_wrong_adapter_and_unqualified_speech_fail_explicitly(self):
        project, kwargs = viewport_inputs()
        kwargs["scenario"] = "replacement"
        with self.assertRaisesRegex(ValueError, "Replacement speech is not qualified"):
            plan_module.build_plan(project, **kwargs)
        kwargs["scenario"] = "silent"
        kwargs["models"]["union"] = plan_module.QUALIFIED_MODELS["union"]
        with self.assertRaisesRegex(ValueError, "Layout-to-Render"):
            plan_module.build_plan(project, **kwargs)

    def test_scene_audio_and_fps_guards(self):
        project, kwargs = viewport_inputs()
        for change, message in (({"fps": 30}, "24 fps"), ({"frames": 361}, "fifteen seconds")):
            wrong = copy.deepcopy(kwargs)
            wrong["timeline"].update(change)
            with self.assertRaisesRegex(ValueError, message):
                plan_module.build_plan(project, **wrong)
        kwargs["scenario"] = "original"
        with self.assertRaisesRegex(ValueError, "no audio"):
            plan_module.build_plan(project, **kwargs)
        kwargs["timeline"]["has_audio"] = True
        plan = plan_module.build_plan(project, **kwargs)
        self.assertEqual(plan["generation_audio"], "zero")
        self.assertEqual(plan["delivery_audio"], "original")
        self.assertEqual(plan["phases"]["decode"]["trim_audio"]["inputs"]["duration"], 353 / 24)

if __name__ == "__main__":
    unittest.main()
