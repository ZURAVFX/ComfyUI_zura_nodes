"""Check the released camera graphs without needing downloaded model weights."""
import json
import unittest
from pathlib import Path


WORKFLOWS = Path(__file__).resolve().parents[1] / "workflows"


def workflow(name):
    return json.loads((WORKFLOWS / name).read_text(encoding="utf-8"))


def incoming(graph, node, input_name):
    """Return the origin node and output socket of a named root input."""
    socket = next(item for item in node["inputs"] if item["name"] == input_name)
    link = next(item for item in graph["links"] if item[0] == socket["link"])
    origin = next(item for item in graph["nodes"] if item["id"] == link[1])
    return origin, origin["outputs"][link[2]]["name"]


def reachable_nodes(graph):
    """Expand only instantiated native subgraphs; unused definitions are inert."""
    definitions = {stage["id"]: stage for stage in graph["definitions"]["subgraphs"]}
    pending = list(graph["nodes"])
    expanded = set()
    while pending:
        node = pending.pop()
        yield node
        if node["type"] in definitions and node["type"] not in expanded:
            expanded.add(node["type"])
            pending.extend(definitions[node["type"]]["nodes"])


class TestCameraWorkflows(unittest.TestCase):
    def test_classic_single_camera_has_one_whole_clip_selection(self):
        graph = workflow("Zura_H3_Single_Camera.json")
        nodes = graph["nodes"]
        self.assertEqual(sum(node["type"] == "VHS_LoadVideo" for node in nodes), 1)
        gallery = next(node for node in nodes if node["type"] == "ZuraAngleGalleryV3")
        self.assertIs(gallery["properties"]["zura_single_camera"], True)
        loader, output = incoming(graph, gallery, "frames_per_shot")
        self.assertEqual((loader["type"], output), ("VHS_LoadVideo", "frame_count"))
        duration = next(node for node in nodes if node["type"] == "ZuraShortTakeDuration")
        self.assertEqual(duration["widgets_values"], [4.0])
        preparation, socket = incoming(graph, loader, "frame_load_cap")
        seconds, output = incoming(graph, preparation, "values.a")
        self.assertEqual((seconds["id"], output), (duration["id"], "seconds"))

    def test_classic_renderer_preserves_warp_and_original_audio_route(self):
        graph = workflow("Zura_H3_Single_Camera.json")
        render = next(node for node in graph["nodes"] if node["type"] == "ZuraH3MulticamV3")
        settings = render["properties"]["zura_widget_values"]
        self.assertEqual(settings["steps"], 16)
        self.assertIs(settings["use_camera_warp_guide"], True)
        self.assertIs(settings["render_selected_intervals_only"], True)
        self.assertIs(settings["look_enabled"], False)
        self.assertEqual(settings["background_mode"], "Keep source background")
        self.assertIn("crossview", settings["prompt"])
        loader, output = incoming(graph, render, "source_audio")
        self.assertEqual((loader["type"], output), ("VHS_LoadVideo", "audio"))
        delivery = next(node for node in graph["nodes"] if node["type"] == "VHS_VideoCombine")
        audio_origin, output = incoming(graph, delivery, "audio")
        self.assertEqual((audio_origin["id"], output), (render["id"], "original_audio"))
        self.assertEqual(delivery["widgets_values"]["frame_rate"], 24)
        self.assertLess(next(node for node in graph["nodes"]
                             if node["type"] == "ZuraAngleGalleryV3")["pos"][0], render["pos"][0])

    def test_classic_root_widgets_are_canonical_without_seed_control_drift(self):
        graph = workflow("Zura_H3_Single_Camera.json")
        for node in graph["nodes"]:
            settings = node.get("properties", {}).get("zura_widget_values")
            if settings:
                with self.subTest(node=node["type"]):
                    self.assertEqual(node["widgets_values_named"], settings)
                    names = [item["widget"]["name"] for item in node["inputs"]
                             if item.get("widget")]
                    self.assertEqual(dict(zip(names, node["widgets_values"])), settings)
                    self.assertEqual(len(node["widgets_values"]), len(names))

    def test_classic_uses_approved_local_preview_and_h3_recipe(self):
        graph = workflow("Zura_H3_Single_Camera.json")
        advanced = workflow("Zura_H3_Multicam_Advanced.json")
        by_name = {stage["name"]: stage for stage in advanced["definitions"]["subgraphs"]}
        active = list(reachable_nodes(graph))
        classes = {node["type"] for node in active}
        self.assertFalse(classes & {"AnyAngleStudioT8", "TextEncodeQwenImage21",
                                    "ZuraH3SingleAngle", "ZuraKleinLookPresets",
                                    "ZuraOptionalImageEdit", "ZuraCleanRelightMulticamV4"})
        self.assertFalse(any("Wan" in kind or "Klein" in kind for kind in classes))
        values = json.dumps([node.get("widgets_values") for node in active])
        self.assertIn("qwen_image_edit_2511", values)
        self.assertIn("Lightning-4steps", values)
        self.assertIn("multiple-angles-lora", values)
        self.assertIn("CrossView-Warp", values)
        self.assertNotIn("qwen_image_2_1", values.lower())
        for stage in graph["definitions"]["subgraphs"]:
            if stage["name"] in ("Generate camera-reference image", "Nine camera previews · Plan pass",
                                  "Prepare performance and camera guide", "Depth Estimation (MoGe)",
                                  "Prepare 3D camera warp", "H3 camera-render models"):
                with self.subTest(stage=stage["name"]):
                    expected = by_name[stage["name"]]
                    recipe = lambda definition: [(node["id"], node["type"], node.get("widgets_values"))
                                                 for node in definition["nodes"]]
                    self.assertEqual(recipe(stage), recipe(expected))
                    self.assertEqual(stage["links"], expected["links"])

    def test_single_angle_render_controls_survive_frontend_reload(self):
        graph = workflow("Zura_H3_AnyAngle_Single_Camera.json")
        render = next(node for node in graph["nodes"]
                      if node["type"] == "ZuraH3SingleAngle")
        # The seed schema explicitly disables the extra seed-control widget.
        # ComfyUI reloads positional values before preparing an API prompt;
        # stale "fixed" here shifts steps into a string and prompt into an int.
        expected_names = ("seed", "steps", "prompt")
        positional = render["widgets_values"]
        self.assertEqual(len(positional), len(expected_names))
        self.assertEqual(dict(zip(expected_names, positional)),
                         render["widgets_values_named"])
        self.assertIs(type(positional[0]), int)
        self.assertIs(type(positional[1]), int)
        self.assertGreaterEqual(positional[1], 1)
        self.assertLessEqual(positional[1], 60)
        self.assertIsInstance(positional[2], str)

    def test_single_angle_has_one_source_and_correct_qwen_sockets(self):
        graph = workflow("Zura_H3_AnyAngle_Single_Camera.json")
        root_types = [node["type"] for node in graph["nodes"]]
        self.assertEqual(root_types.count("VHS_LoadVideo"), 1)
        self.assertEqual(root_types.count("AnyAngleStudioT8"), 1)
        self.assertEqual(root_types.count("ZuraH3SingleAngle"), 1)

        stages = {stage["name"]: stage for stage in graph["definitions"]["subgraphs"]}
        self.assertIn("Prepare camera target", stages)
        qwen = next(node for node in stages["Prepare camera target"]["nodes"]
                    if node["type"] == "TextEncodeQwenImage21")
        sockets = {item["name"]: item.get("link") for item in qwen["inputs"]}
        self.assertIsNotNone(sockets["images.image_2"])
        self.assertIsNotNone(sockets["vae"])
        self.assertIsNotNone(sockets["prompt"])
        self.assertIsNone(sockets["resolution"])
        self.assertEqual(qwen["widgets_values_named"]["resolution"], 1024)

    def test_advanced_graph_has_a_planning_stage_before_rendering(self):
        graph = workflow("Zura_H3_Multicam_Advanced.json")
        nodes = graph["nodes"]
        by_type = {node["type"]: node for node in nodes}
        self.assertEqual(sum(node["type"] == "VHS_LoadVideo" for node in nodes), 1)
        self.assertLess(by_type["ZuraAngleGalleryV3"]["pos"][0],
                        by_type["ZuraH3MulticamV3"]["pos"][0])
        self.assertLess(by_type["ZuraH3MulticamV3"]["pos"][0],
                        by_type["VHS_VideoCombine"]["pos"][0])
        names = [stage["name"] for stage in graph["definitions"]["subgraphs"]]
        self.assertNotIn("New Subgraph", names)
        stages = {stage["name"]: stage for stage in graph["definitions"]["subgraphs"]}
        # A previous frontend export retained the outer geometry socket but
        # silently erased the links inside these two nested native stages.
        self.assertEqual(len(stages["Depth Estimation (MoGe)"]["links"]), 22)
        warp = stages["Prepare 3D camera warp"]
        self.assertEqual(len(warp["links"]), 4)
        self.assertTrue(all(output["linkIds"] for output in warp["outputs"]))


if __name__ == "__main__":
    unittest.main()
