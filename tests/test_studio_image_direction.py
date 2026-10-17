"""Separate image direction and approved H3 viewport opening contracts, no GPU."""
import copy
import tempfile
import unittest
from unittest.mock import patch

import test_artist_studio as fixture
import test_h3_frame_anchors as anchors

studio = fixture.studio


class ImageDirectionTests(unittest.TestCase):
    def test_image_direction_is_trimmed_bounded_and_legacy_defaults_empty(self):
        self.assertEqual(studio.clean_config({})["image_prompt"], "")
        self.assertEqual(studio.clean_config({"image_prompt": "  painted scene  "})["image_prompt"], "painted scene")
        self.assertEqual(len(studio.clean_config({"image_prompt": "x" * 6000})["image_prompt"]), 5000)

    def test_design_uses_image_direction_with_legacy_video_prompt_fallback(self):
        project = fixture.SharedEngineTests().project()
        project["config"] = studio.clean_config({"engine": "h3", "workflow_mode": "viewport",
                                                "prompt": "Video motion only.", "image_prompt": "Warm painted materials."})
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"):
            graph = studio.build_graph(project, "design", use_cache=False)
            project["config"]["image_prompt"] = ""
            legacy = studio.build_graph(project, "design", use_cache=False)
        self.assertIn("Additional appearance direction: Warm painted materials.", graph["127"]["inputs"]["value"])
        self.assertNotIn("Video motion only.", graph["127"]["inputs"]["value"])
        self.assertIn("Additional appearance direction: Video motion only.", legacy["127"]["inputs"]["value"])

    def test_changing_image_direction_invalidates_generated_opening_preserves_selection(self):
        project = fixture.SharedEngineTests().project()
        project["approval"] = studio.prep_key(project)
        project["prepared_key"] = project["approval"]
        with tempfile.TemporaryDirectory() as temporary:
            controller = studio.Studio.__new__(studio.Studio)
            controller.store = studio.Store(temporary)
            controller.collect = lambda project: project
            controller.configure(project, {**project["config"], "image_prompt": "New materials."})
        self.assertIsNone(project["opening_input"])
        self.assertIsNone(project["opening_approval"])
        self.assertEqual(project["review"], "shot_" + "a" * 16)
        self.assertEqual(project["approval"], project["prepared_key"])
        self.assertEqual(project["phase"], "approved")

    def test_video_motion_change_preserves_opening_with_explicit_image_direction(self):
        project = fixture.SharedEngineTests().project()
        project["config"]["image_prompt"] = "Keep these materials."
        project["approval"] = studio.prep_key(project)
        project["prepared_key"] = project["approval"]
        prior_opening = copy.deepcopy(project["opening_input"])
        with tempfile.TemporaryDirectory() as temporary:
            controller = studio.Studio.__new__(studio.Studio)
            controller.store = studio.Store(temporary)
            controller.collect = lambda project: project
            controller.configure(project, {**project["config"], "prompt": "Camera moves left."})
        self.assertEqual(project["opening_input"], prior_opening)

    def test_auto_graph_view_opens_image_generation_before_h3_animation(self):
        project = fixture.SharedEngineTests().project()
        project["config"] = studio.clean_config({"engine": "h3", "workflow_mode": "viewport"})
        project["approval"] = studio.prep_key(project)
        project["opening_input"] = None
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"):
            graph, stage = studio.editable_graph(project, "auto")
        self.assertEqual(stage, "design")
        self.assertIn("127", graph)


class H3GeneratedOpeningTests(unittest.TestCase):
    def project(self):
        project = anchors.H3FinishedFrameAnchorTests().viewport_project(ready=False, position="last")
        project.update(look_mode="build", opening_input={"file": "generated.png", "sha": "generated"},
                       opening_key="generated", opening_approval="generated")
        return project

    def test_approved_generated_opening_is_native_first_frame_without_mutating_saved_project(self):
        project = self.project()
        saved = copy.deepcopy(project)
        routed = studio._viewport_project(project)
        self.assertEqual(project, saved)
        self.assertEqual(project["look_mode"], "build")
        self.assertEqual(routed["look_mode"], "ready")
        self.assertEqual(routed["config"]["finished_frame_position"], "first")
        self.assertEqual(routed["config"]["finished_frame_number"], 1)
        self.assertEqual(routed["viewport_references"][0]["file"], "generated.png")
        self.assertEqual(routed["viewport_references"][1:], project["references"])
        graph = anchors.H3FinishedFrameAnchorTests().build_viewport(routed)
        self.assertEqual(graph["h3_finished_frame"]["class_type"], "MiniMaxH3AddGuide")
        self.assertEqual(graph["h3_finished_frame"]["inputs"]["frame_idx"], 0)
        self.assertEqual(graph["h3_finished_frame"]["inputs"]["image"], ["h3_viewport_image_1", 0])
        self.assertIn("ref_videos.ref_video_0", graph["h3_references"]["inputs"])

    def test_stale_unapproved_or_missing_opening_keeps_direct_references(self):
        for changes in ({"opening_approval": None}, {"opening_approval": "old"}, {"opening_key": None}, {"opening_input": None}):
            with self.subTest(changes=changes):
                project = self.project()
                project.update(changes)
                routed = studio._viewport_project(project)
                self.assertEqual(routed["look_mode"], "build")
                self.assertEqual(routed["viewport_references"], project["references"])

    def test_uploaded_last_anchor_keeps_explicit_frame_choice(self):
        project = self.project()
        project.update(look_mode="ready", starting_asset={"file": "uploaded.png", "sha": "uploaded"})
        routed = studio._viewport_project(project)
        self.assertEqual(routed["starting_asset"]["file"], "uploaded.png")
        self.assertEqual(routed["config"]["finished_frame_position"], "last")

    def test_generated_opening_respects_nine_image_limit(self):
        project = self.project()
        project["references"] = [{"file": f"ref-{i}.png", "sha": str(i)} for i in range(9)]
        with self.assertRaisesRegex(ValueError, "eight extra"):
            studio._viewport_project(project)


if __name__ == "__main__":
    unittest.main()
