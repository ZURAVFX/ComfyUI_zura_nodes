"""The local H3 viewport route follows blockout video plus ordered look refs."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch

import torch

import v2_bootstrap

NAME = "ComfyUI_zura_nodes.artist_studio"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[NAME] = package
package = sys.modules[NAME]
studio = importlib.import_module(NAME + ".studio")
h3 = importlib.import_module(NAME + ".h3")


class Components:
    def __init__(self, count=120, height=36, width=64, fps=24):
        self.images = torch.zeros(count, height, width, 3)
        self.frame_rate = fps


class Video:
    def __init__(self, **kwargs):
        self.components = Components(**kwargs)

    def get_components(self):
        return self.components


class H3ViewportRenderTests(unittest.TestCase):
    def project(self):
        config = studio.clean_config({"workflow_mode": "viewport", "engine": "h3", "duration": 5, "resolution": 1280,
                                      "quality": "fast", "prompt": "Golden-hour anime train scene."})
        references = [
            {"file": f"train-reference-{i}.png", "sha": f"reference-{i}", "role": role}
            for i, role in enumerate(("environment", "character", "character", "environment", "detail"), 1)
        ]
        return {
            "id": "a" * 32,
            "viewport_render": True,
            "source": {"file": "train-blockout.mp4", "sha": "source"},
            "references": references,
            "viewport_references": references,
            "config": config,
        }

    @staticmethod
    def media_container(seconds):
        class Container:
            streams = types.SimpleNamespace(video=[types.SimpleNamespace(
                duration=seconds, time_base=1)])
            duration = seconds * 1_000_000

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False
        return Container()

    def test_viewport_frame_data_enforces_local_h3_frame_contract(self):
        data = h3.GenjH3ViewportFrameData()
        frames, width, height, length, real, crop_x, crop_y, crop_width, crop_height = data.prepare(Video())
        self.assertEqual(tuple(frames.shape), (120, 64, 64, 3))
        self.assertEqual((width, height, length, real), (64, 64, 124, 120))
        self.assertEqual((crop_x, crop_y, crop_width, crop_height), (0, 14, 64, 36))
        for options, message in [
            ({"fps": 30}, "24 fps"),
            ({"count": 121}, "0.21–5 seconds"),
        ]:
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, message):
                data.prepare(Video(**options))

    def test_graph_uses_one_source_video_and_ordered_look_reference_roles(self):
        project = self.project()
        with patch.object(studio, "assert_approved"), \
                patch.object(studio, "check_asset") as check, \
                patch("av.open", return_value=self.media_container(15)):
            graph = h3.build_h3_graph(project, use_cache=False)

        self.assertEqual(check.call_count, 6)
        self.assertEqual(graph["h3_viewport_source"]["class_type"], "LoadVideo")
        self.assertEqual(graph["h3_viewport_clip"]["inputs"]["video"], ["h3_viewport_source", 0])
        refs = graph["h3_references"]
        self.assertEqual(refs["class_type"], "MiniMaxH3ReferenceToVideo")
        inputs = refs["inputs"]
        self.assertEqual(inputs["ref_videos.ref_video_0"], ["h3_viewport_data", 0])
        self.assertEqual(graph["h3_viewport_data"]["inputs"]["video"], ["h3_viewport_clip", 0])
        self.assertEqual(inputs["ref_images.ref_image_0"], ["h3_viewport_image_1", 0])
        self.assertEqual(inputs["ref_images.ref_image_4"], ["h3_viewport_image_5", 0])
        self.assertIn("<Video 1> is the grey 3D viewport/blockout", inputs["prompt"])
        self.assertIn("<Picture 1> is the environment and scene design", inputs["prompt"])
        self.assertIn("<Picture 2> is the character appearance and identity", inputs["prompt"])
        self.assertIn("<Picture 3> is the character appearance and identity", inputs["prompt"])
        self.assertIn("<Picture 4> is the environment and scene design", inputs["prompt"])
        self.assertIn("<Picture 5> is a close-up detail to reproduce accurately", inputs["prompt"])
        self.assertIn("Golden-hour anime train scene.", inputs["prompt"])
        self.assertEqual(graph["h3_schedule"]["inputs"]["steps"], 8)
        self.assertEqual(graph["h3_turbo"]["inputs"]["lora_name"], h3.H3_MODELS["h3_turbo"][1])
        self.assertNotIn("GenjLoadReviewedShot", [node["class_type"] for node in graph.values()])
        self.assertNotIn("MinimaxHailuo03ReferenceNode", [node["class_type"] for node in graph.values()])
        self.assertEqual(graph["h3_export"]["inputs"]["clip_details"], ["h3_viewport_clip", 1])
        self.assertEqual(graph["h3_crop"]["inputs"]["width"], ["h3_viewport_data", 7])
        self.assertEqual(graph["h3_crop"]["inputs"]["height"], ["h3_viewport_data", 8])

    def test_original_length_over_five_seconds_is_rejected_before_queueing_video_nodes(self):
        project = self.project()
        project["config"]["length_mode"] = "original"
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                patch("av.open", return_value=self.media_container(15)):
            with self.assertRaisesRegex(ValueError, "0.21–5 seconds"):
                h3.build_h3_graph(project, use_cache=False)

    def test_legacy_mode_without_viewport_flag_still_uses_reviewed_shot(self):
        project = self.project()
        project.pop("viewport_render")
        project.pop("viewport_references")
        project.update({
            "character": {"file": "character.png", "sha": "character"},
            "opening_input": {"file": "opening.png", "sha": "opening"},
            "opening_key": "opening", "opening_approval": "opening",
            "review": "shot_" + "b" * 16,
        })
        package.verify_review = lambda _: (None, {"clip": {"frames": 120}})
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                patch.object(h3, "cache_key", return_value="c" * 64), \
                patch.object(h3, "cache_valid", return_value=False):
            graph = h3.build_h3_graph(project, use_cache=False)
        self.assertIn("h3_shot", graph)
        self.assertNotIn("h3_viewport_source", graph)

    def test_graph_view_exports_direct_h3_route_without_reviewed_shot_rewiring(self):
        project = self.project()
        project["approval"] = studio.prep_key(project)
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                patch("av.open", return_value=self.media_container(15)):
            graph, stage = studio.editable_graph(project, "auto")
        self.assertEqual(stage, "h3")
        self.assertIn("h3_viewport_source", graph)
        self.assertNotIn("zura_audio_selection", graph)
        self.assertNotIn("GenjLoadReviewedShot", [node["class_type"] for node in graph.values()])

    def test_viewport_action_skips_legacy_h3_reference_cache_handoff(self):
        project = self.project()
        self.assertFalse(studio._needs_h3_reference_stage(project, {"h3_export": {}}))

        project["config"]["workflow_mode"] = "motion"
        project["config"]["viewport_render"] = False
        project.pop("viewport_render")
        self.assertTrue(studio._needs_h3_reference_stage(project, {"h3_export": {}}))
        self.assertFalse(studio._needs_h3_reference_stage(project, {"h3_cached": {}}))

    def test_finished_scene_image_is_first_direct_h3_reference(self):
        project = self.project()
        project["look_mode"] = "ready"
        project["starting_asset"] = {"file": "finished-scene.png", "sha": "starting-frame"}
        routed = studio._viewport_project(project)
        self.assertEqual(routed["viewport_references"][0]["file"], "finished-scene.png")
        self.assertEqual(routed["viewport_references"][0]["viewport_role"], "starting_frame")
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                patch("av.open", return_value=self.media_container(15)):
            graph = h3.build_h3_graph(routed, use_cache=False)
        self.assertEqual(graph["h3_viewport_image_1"]["inputs"]["image"], "finished-scene.png")
        self.assertIn("finished scene image supplied by the artist", graph["h3_references"]["inputs"]["prompt"])


if __name__ == "__main__":
    unittest.main()
