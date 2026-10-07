"""Check the released camera graphs without needing downloaded model weights."""
import json
import unittest
from pathlib import Path


WORKFLOWS = Path(__file__).resolve().parents[1] / "workflows"


def workflow(name):
    return json.loads((WORKFLOWS / name).read_text(encoding="utf-8"))


class TestCameraWorkflows(unittest.TestCase):
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
