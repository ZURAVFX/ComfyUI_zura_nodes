"""Contract checks for the user-approved Wan 2.1 chained relight route."""
import importlib
import unittest
from unittest.mock import patch

import test_artist_studio as fixture

studio = fixture.studio
wan21 = importlib.import_module(studio.__package__ + ".wan21_relight")


class Wan21RelightTests(unittest.TestCase):
    def test_lighting_image_readiness_needs_klein_and_not_h3(self):
        graph = studio.json.loads((studio.HERE / "graphs" / "01B_Design_Opening_Frame.json").read_text(encoding="utf-8"))
        mappings = {node["class_type"]: object() for node in graph.values()}
        result = studio.design_readiness(mappings, lambda folder, filename: filename)
        self.assertTrue(result["ready"])
        self.assertEqual({item["filename"] for item in result["model_files"]}, {
            "flux-2-klein-9b-fp8.safetensors", "qwen_3_8b_fp8mixed.safetensors",
            "full_encoder_small_decoder.safetensors"})
        self.assertFalse(studio.design_readiness(mappings, lambda folder, filename: None)["ready"])
        del mappings["ReferenceLatent"]
        missing = studio.design_readiness(mappings, lambda folder, filename: filename)
        self.assertFalse(missing["ready"])
        self.assertEqual(missing["missing_nodes"], ["ReferenceLatent"])

    def test_relight_defaults_and_legacy_h3_selection_migrate_to_wan21(self):
        for old in ({}, {"relight_engine": "h3"}, {"relight_engine": "wan21"}):
            config = studio.clean_config({"engine": "h3", "workflow_mode": "relight", **old})
            self.assertEqual(config["relight_engine"], "wan21")
            self.assertEqual(config["resolution"], 1280)
            self.assertFalse(config["preserve_identity"])

    def project(self):
        project = fixture.SharedEngineTests().project()
        project["config"] = studio.clean_config({
            "engine": "h3", "workflow_mode": "relight", "relight_engine": "wan21",
            "prompt": "Soft warm window light, with a cooler shadow side.", "seed": 123,
            "resolution": 1920, "delivery_mode": "enhanced1080",
            "preserve_identity": True, "remove_text": True,
        })
        project.update(review="shot_" + "b" * 16, approval="prepared", prepared_key="prepared",
                       opening_key="opening-sha", opening_approval="opening-sha",
                       opening_input={"file": "genj_studio/test/opening.png", "sha": "opening-sha"},
                       actions=[], id="b" * 32)
        return project

    def build(self, project=None):
        project = project or self.project()
        with patch.object(studio, "assert_approved"), patch.object(wan21, "_output_size", return_value=(1280, 704)):
            return wan21.build_studio_graph(project, lambda asset: asset["file"])

    def test_builds_original_performance_recipe_with_reviewed_frame_and_direction(self):
        graph = self.build()
        self.assertEqual(graph["wan21_reference"]["inputs"]["image"], "genj_studio/test/opening.png")
        self.assertEqual(graph["wan21_shot"]["inputs"]["shot_id"], "shot_" + "b" * 16)
        self.assertEqual(graph["wan21_shot"]["inputs"]["approved_shot_id"], graph["wan21_shot"]["inputs"]["shot_id"])
        self.assertNotEqual(graph["wan21_shot"]["inputs"]["approved_shot_id"], self.project()["approval"])
        self.assertEqual(graph["wan21_source_frames"]["inputs"]["video"], ["wan21_shot", 0])
        self.assertEqual(graph["272:407:89"]["inputs"]["width"], 1280)
        self.assertEqual(graph["272:407:89"]["inputs"]["height"], 704)
        self.assertEqual(graph["272:408:275:190"]["inputs"]["width"], 1280)
        self.assertEqual(graph["272:408:275:190"]["inputs"]["height"], 704)
        self.assertEqual(graph["272:407:277:19"]["inputs"]["noise_seed"], 123)
        self.assertIn("Soft warm window light", graph["272:408:274:3"]["inputs"]["text"])
        self.assertEqual(graph["wan21_export"]["class_type"], "GenjRestoreSoundtrack")
        self.assertEqual(graph["wan21_export"]["inputs"]["clip_details"], ["wan21_shot", 3])

    def test_recipe_links_are_closed_and_only_source_and_approved_frame_are_external(self):
        graph = self.build()
        for node in graph.values():
            for value in node.get("inputs", {}).values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    self.assertIn(value[0], graph, f"Dangling node link: {value}")
        raw = wan21.RECIPE.read_text(encoding="utf-8")
        for private in ("relight needed.mp4", "reference_image.png", "ComfyUI-Shared", "C:\\\\Users\\\\ellio", "data:image/"):
            self.assertNotIn(private, raw)

    def test_matching_loader_ids_do_not_skip_source_approval_checks(self):
        with patch.object(studio, "assert_approved", side_effect=ValueError("Source changed")):
            with self.assertRaisesRegex(ValueError, "Source changed"):
                wan21.build_studio_graph(self.project(), lambda asset: asset["file"])

    def test_fixed_recipe_ignores_h3_delivery_controls(self):
        config = self.project()["config"]
        self.assertEqual(config["resolution"], 1280)
        self.assertEqual(config["delivery_mode"], "native")
        self.assertFalse(config["preserve_identity"])
        self.assertFalse(config["remove_text"])

    def test_rejects_missing_direction_approval_or_unsupported_features(self):
        project = self.project()
        project["config"]["prompt"] = ""
        with patch.object(studio, "assert_approved"), self.assertRaisesRegex(ValueError, "lighting"):
            wan21.build_studio_graph(project, lambda asset: asset["file"])
        project = self.project()
        project["opening_approval"] = None
        with patch.object(studio, "assert_approved"), self.assertRaisesRegex(ValueError, "lighting frame"):
            wan21.build_studio_graph(project, lambda asset: asset["file"])
        project = self.project()
        project["config"]["remove_text"] = True
        with patch.object(studio, "assert_approved"), patch.object(wan21, "_output_size", return_value=(1280, 704)), self.assertRaisesRegex(ValueError, "Text removal"):
            wan21.build_studio_graph(project, lambda asset: asset["file"])

    def test_readiness_reports_exact_models_and_node_dependencies(self):
        result = wan21.readiness({name: object() for name in wan21.REQUIRED_NODES},
                                 lambda _folder, filename: filename)
        self.assertTrue(result["ready"])
        self.assertFalse(result["quality_verified_locally"])
        self.assertTrue(result["source_workflow_artist_confirmed"])
        self.assertEqual([item["filename"] for item in result["model_files"]],
                         [filename for _, filename in wan21.MODEL_FILES.values()])
        missing = wan21.readiness({}, lambda _folder, _filename: None)
        self.assertFalse(missing["ready"])
        self.assertEqual(missing["missing_nodes"], sorted(wan21.REQUIRED_NODES))
        self.assertTrue(all(not item["ready"] for item in missing["model_files"]))

    def test_editable_graph_routes_animate_to_selected_wan21_recipe(self):
        project = self.project()
        project["opening_approval"] = None
        with patch.object(studio, "build_graph", side_effect=lambda _p, stage, **_kw: {"stage": stage}):
            graph, stage = studio.editable_graph(project, "animate")
        self.assertEqual(stage, "wan21_relight")
        self.assertEqual(graph, {"stage": "wan21_relight"})
        self.assertIsNone(project["opening_approval"], "The live project is never modified")

    def test_direct_wan21_graph_export_approves_only_the_exported_snapshot(self):
        project = self.project()
        project["opening_approval"] = None
        with patch.object(studio, "build_graph", side_effect=lambda _p, stage, **_kw: {"stage": stage}):
            graph, stage = studio.editable_graph(project, "wan21_relight")
        self.assertEqual((graph, stage), ({"stage": "wan21_relight"}, "wan21_relight"))
        self.assertIsNone(project["opening_approval"])


if __name__ == "__main__":
    unittest.main()
