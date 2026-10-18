"""Timed still guides bind to the delivered clip, independently of latent padding."""
import ast
import os
from pathlib import Path
import unittest
from test_ltx25_native_plan import inputs, plan_module
from test_ltx25_viewport_plan import viewport_inputs


class FinishedFrameTests(unittest.TestCase):
    def test_one_based_indices_and_last_excludes_padding(self):
        resolve = plan_module.resolve_finished_frame
        self.assertEqual(resolve({}, 120), 0)
        self.assertEqual(resolve({"finished_frame_position": "last"}, 120), 119)
        self.assertEqual(resolve({"finished_frame_position": "frame", "finished_frame_number": 92}, 120), 91)
        for number in (0, 121, True, 1.0, "2", None):
            with self.assertRaisesRegex(ValueError, "frame number"):
                resolve({"finished_frame_position": "frame", "finished_frame_number": number}, 120)
        for length in (0, -1, True, 120.0):
            with self.assertRaisesRegex(ValueError, "frame count"):
                resolve({}, length)
        with self.assertRaisesRegex(ValueError, "First frame"):
            resolve({"finished_frame_position": "garbage"}, 120)

    @staticmethod
    def ready(project, position, number=1):
        project.update(look_mode="ready", starting_asset={"file": "finished.png", "sha": "a" * 64})
        project["config"].update(finished_frame_position=position, finished_frame_number=number)

    def test_ordinary_mid_clip_guide_survives_both_sampling_stages(self):
        project, kwargs = inputs()
        self.ready(project, "frame", 92)
        plan = plan_module.build_plan(project, **kwargs)
        self.assertEqual(plan["basis"]["finished_frame_index"], 91)
        for phase in ("stage1", "refine"):
            graph = plan["phases"][phase]
            guide = graph["finished_frame"]
            self.assertEqual(guide["class_type"], "LTXVAddGuide")
            self.assertEqual(guide["inputs"]["frame_idx"], 91)
            self.assertEqual(guide["inputs"]["image"], ["preprocess", 0])
            self.assertEqual(graph["crop_guides"]["inputs"]["positive"],
                             ["guide" if phase == "stage1" else "finished_frame", 0])
            self.assertEqual(graph["save_stage1_video" if phase == "stage1" else "save_stage2_video"]["inputs"]["samples"], ["crop_guides", 2])
        self.assertNotIn("first_frame", plan["phases"]["stage1"])
        self.assertNotIn("first_frame", plan["phases"]["upscale"])
        self.assertEqual(plan["phases"]["stage1"]["guide"]["inputs"]["positive"], ["finished_frame", 0])
        self.assertEqual(plan["phases"]["refine"]["concat"]["inputs"]["video_latent"], ["finished_frame", 2])

    def test_default_first_retains_approved_inplace_recipe(self):
        project, kwargs = inputs()
        self.ready(project, "first")
        plan = plan_module.build_plan(project, **kwargs)
        for phase in ("stage1", "upscale"):
            self.assertEqual(plan["phases"][phase]["first_frame"]["class_type"], "LTXVImgToVideoInplace")
        self.assertNotIn("finished_frame", plan["phases"]["refine"])

    def test_viewport_first_last_and_custom_are_timed_in_both_stages(self):
        for position, number, expected in (("first", 1, 0), ("last", 1, 359), ("frame", 92, 91)):
            project, kwargs = viewport_inputs()
            self.ready(project, position, number)
            plan = plan_module.build_plan(project, **kwargs)
            self.assertEqual(plan["basis"]["finished_frame_index"], expected)
            for phase in ("stage1", "refine"):
                self.assertEqual(plan["phases"][phase]["appearance_guide"]["inputs"]["frame_idx"], expected)
            self.assertEqual(plan["appearance_reference_role"], "finished_frame_at_selected_time")

    def test_generated_appearance_stays_untimed_and_invalid_number_fails(self):
        project, kwargs = viewport_inputs()
        project["config"].update(finished_frame_position="frame", finished_frame_number=400)
        original = plan_module.build_plan(project, **kwargs)
        self.assertEqual(original["phases"]["stage1"]["appearance_guide"]["inputs"]["frame_idx"], -1)
        self.ready(project, "frame", 400)
        with self.assertRaisesRegex(ValueError, "1 to 360"):
            plan_module.build_plan(project, **kwargs)

    def test_installed_native_single_image_index_does_not_snap(self):
        root = os.environ.get("COMFYUI_ROOT")
        if not root:
            self.skipTest("Set COMFYUI_ROOT to check the installed native index resolver.")
        path = Path(root) / "comfy_extras" / "nodes_lt.py"
        source = ast.parse(path.read_text(encoding="utf-8"))
        node = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "LTXVAddGuide")
        method = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "get_latent_index")
        method.decorator_list = []
        namespace = {"get_keyframe_idxs": lambda *args: (None, 0)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
        resolve = namespace["get_latent_index"]
        # Arbitrary non-stride-aligned image coordinates remain unchanged.
        for frame in (0, 48, 91, 119):
            actual, latent = resolve(None, [], 16, 1, frame, (8, 32, 32))
            self.assertEqual(actual, frame)
            self.assertEqual(latent, (frame + 7) // 8)

    def test_anchor_time_is_content_keyed(self):
        project, kwargs = inputs()
        self.ready(project, "frame", 92)
        first = plan_module.build_plan(project, **kwargs)
        project["config"]["finished_frame_number"] = 93
        second = plan_module.build_plan(project, **kwargs)
        self.assertNotEqual(first["key"], second["key"])
        self.assertNotEqual(first["artifacts"]["stage1_video"]["key"], second["artifacts"]["stage1_video"]["key"])


if __name__ == "__main__":
    unittest.main()
