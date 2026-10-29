"""Contract checks for the user-approved Wan 2.1 chained relight route."""
import importlib
import unittest
from unittest.mock import patch

import test_artist_studio as fixture

studio = fixture.studio
wan21 = importlib.import_module(studio.__package__ + ".wan21_relight")


class Wan21RelightTests(unittest.TestCase):
    def test_wan21_image_preparation_has_no_sam_or_depth_model(self):
        project = self.project()
        with patch.object(studio, "check_asset"):
            graph = studio.build_graph(project, "prepare", use_cache=False)
        kinds = {node["class_type"] for node in graph.values()}
        self.assertFalse(any("SAM" in kind or "DepthAnything" in kind for kind in kinds))
        self.assertEqual(graph["20"]["inputs"]["guide_frames"], ["4", 0])

    def test_uploaded_lighting_image_skips_image_generation_and_prompt_requirement(self):
        project = self.project()
        project.update(look_mode="ready", starting_asset={"file": "finished-lighting.png"})
        project["config"].update(prompt="", image_prompt="")
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"):
            graph = studio.build_graph(project, "design", use_cache=False)
        self.assertEqual({node["class_type"] for node in graph.values()}, {"LoadImage", "PreviewImage"})
        self.assertEqual(graph["starting_frame"]["inputs"]["image"], "finished-lighting.png")

    def test_each_lighting_generator_edits_original_video_without_sam(self):
        for model in ("flux3", "klein9b", "qwen2511", "qwen21"):
            with self.subTest(model=model):
                project = self.project()
                project["config"]["opening_model"] = model
                with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"):
                    graph = studio.build_graph(project, "design", use_cache=False)
                self.assertEqual(graph["zura_original_video"]["inputs"]["file"], "source.mp4")
                self.assertEqual(graph["122"]["inputs"]["images"], ["zura_opening_original_resolution", 0])
                self.assertFalse(any("SAM" in node["class_type"] for node in graph.values()))
                for node in graph.values():
                    for value in node.get("inputs", {}).values():
                        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                            self.assertIn(value[0], graph)

    def test_qwen21_receives_all_nine_appearance_references(self):
        project = self.project()
        project["config"]["opening_model"] = "qwen21"
        project["references"] = [{"file": f"ref-{i}.png"} for i in range(9)]
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"):
            graph = studio.build_graph(project, "design", use_cache=False)
        self.assertEqual(len([key for key in graph["92:109"]["inputs"] if key.startswith("images.image_")]), 10)

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

    def test_selected_resolution_reaches_both_native_relight_inputs(self):
        project = self.project()
        project["config"].update(relight_width=720, relight_height=1280)
        graph = self.build(project)
        for key in ("272:407:89", "272:408:275:190"):
            self.assertEqual(graph[key]["inputs"]["width"], 720)
            self.assertEqual(graph[key]["inputs"]["height"], 1280)
            self.assertEqual(graph[key]["inputs"]["keep_proportion"], "crop")
        self.assertEqual(graph["wan21_export"]["inputs"]["output_width"], 720)
        self.assertEqual(graph["wan21_export"]["inputs"]["output_height"], 1280)

    def test_source_size_exports_original_even_resolution(self):
        project = self.project()
        project["config"].update(relight_shape="source_size", relight_width=1920, relight_height=1088)
        with patch.object(wan21, "_source_size", return_value=(1920, 1080)):
            graph = self.build(project)
        self.assertEqual(graph["272:407:89"]["inputs"]["height"], 1088)
        self.assertEqual(graph["wan21_export"]["inputs"]["output_width"], 1920)
        self.assertEqual(graph["wan21_export"]["inputs"]["output_height"], 1080)

    def test_opening_resolution_keeps_original_frame_and_final_source_size(self):
        for model in ("flux3", "klein9b", "qwen2511", "qwen21"):
            project = self.project()
            project["config"].update(opening_model=model, opening_width=1152, opening_height=640)
            with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"):
                graph = studio.build_graph(project, "design", use_cache=False)
            self.assertEqual(graph["92:111"]["inputs"]["image"], ["125", 0])
            self.assertEqual(graph["92:111"]["inputs"]["width"], 1152)
            self.assertEqual(graph["92:111"]["inputs"]["crop"], "center")
            self.assertEqual(graph["zura_opening_original_resolution"]["inputs"]["width"], ["zura_original_size", 0])

    def test_invalid_grid_and_pixel_budget_are_rejected_before_queueing(self):
        for sizes in ({"opening_width": 721, "opening_height": 1280},
                      {"relight_width": 2048, "relight_height": 2048},
                      {"opening_width": 2048, "opening_height": 2048},
                      {"relight_width": 720}):
            with self.subTest(sizes=sizes), self.assertRaises(ValueError):
                studio.clean_config({"engine": "h3", "workflow_mode": "relight", **sizes})

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
        self.assertEqual(graph["272:408:275:190"]["inputs"]["crop_position"], graph["272:407:89"]["inputs"]["crop_position"])
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

    def test_supplied_lighting_image_needs_no_written_direction(self):
        project = self.project()
        project["config"]["prompt"] = ""
        with patch.object(studio, "assert_approved"), patch.object(wan21, "_output_size", return_value=(1280, 704)):
            graph = wan21.build_studio_graph(project, lambda asset: asset["file"])
        self.assertIn("supplied lighting image", graph["272:408:274:3"]["inputs"]["text"])

    def test_rejects_missing_approval_or_unsupported_features(self):
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
