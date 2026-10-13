"""Image-choice security, native graph inputs and the no-generation route."""
import copy
import asyncio
import hashlib
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

import test_artist_studio as fixture

studio = fixture.studio
appearance = importlib.import_module("ComfyUI_zura_nodes.artist_studio.appearance")


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        self.assets = {str(i): {"id": str(i), "kind": "asset", "asset_kind": "image",
                                 "file": f"reference_{i}.png", "sha": str(i) * 64}
                       for i in range(1, 5)}
        self.checked = []

    def resolve(self, body):
        return appearance.resolve_appearance(body, self.assets.__getitem__, self.checked.append)

    def test_legacy_single_image_migrates_without_changing_primary(self):
        result = self.resolve({"character": "1"})
        self.assertEqual(result["look_mode"], "build")
        self.assertEqual(result["references"], [self.assets["1"]])
        self.assertEqual(result["character"], self.assets["1"])

    def test_ready_frame_does_not_require_an_extra_character_image(self):
        result = self.resolve({"look_mode": "ready", "starting_image": "1", "references": []})
        self.assertEqual(result["starting_asset"], self.assets["1"])
        self.assertEqual(result["character"], self.assets["1"])

    def test_optional_primary_reference_is_separate_from_ready_frame(self):
        result = self.resolve({"look_mode": "ready", "starting_image": "1", "references": ["2", "3"]})
        self.assertEqual(result["starting_asset"], self.assets["1"])
        self.assertEqual(result["character"], self.assets["2"])
        self.assertEqual(len(self.checked), 3)

    def test_invalid_or_unverified_image_choices_are_rejected(self):
        for body in ({"look_mode": "unknown"}, {"references": []},
                     {"references": ["1"] * 10}, {"references": "1"},
                     {"references": [None]}):
            with self.assertRaises(ValueError):
                self.resolve(body)
        with self.assertRaisesRegex(ValueError, "match"):
            self.resolve({"references": ["1", "2"], "reference_roles": ["character"]})
        with self.assertRaisesRegex(ValueError, "valid role"):
            self.resolve({"references": ["1"], "reference_roles": ["building"]})
        self.assets["1"]["asset_kind"] = "video"
        with self.assertRaises(ValueError):
            self.resolve({"references": ["1"]})
        with self.assertRaisesRegex(ValueError, "changed"):
            appearance.resolve_appearance({"references": ["2"]}, self.assets.__getitem__,
                lambda asset: (_ for _ in ()).throw(ValueError("asset changed")))

    def test_multiple_native_references_reach_the_sampler_and_removal_drops_them(self):
        p = fixture.SharedEngineTests().project()
        p["references"] = list(self.assets.values())[:3]
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"):
            graph = studio.build_graph(p, "design")
            p["references"] = p["references"][:1]
            reduced = studio.build_graph(p, "design")
        self.assertEqual(graph["121"]["inputs"]["image"], "reference_1.png")
        self.assertEqual(graph["zura_reference_2"]["inputs"]["image"], "reference_2.png")
        self.assertEqual(graph["zura_reference_3"]["inputs"]["image"], "reference_3.png")
        self.assertEqual(graph["92:103"]["inputs"]["positive"], ["zura_reference_3_positive", 0])
        self.assertEqual(graph["zura_reference_3_positive"]["inputs"]["conditioning"], ["zura_reference_2_positive", 0])
        self.assertEqual(graph["zura_reference_2_positive"]["inputs"]["conditioning"], ["92:131", 0])
        self.assertEqual(graph["zura_reference_2_encode"]["class_type"], "VAEEncode")
        self.assertIn("Images 2 onwards", graph["127"]["inputs"]["value"])
        self.assertFalse(any(key.startswith("zura_reference_") for key in reduced))
        for node in graph.values():
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2:
                    self.assertIn(str(value[0]), graph)

    def test_ready_frame_graph_is_editable_and_contains_no_generation(self):
        p = fixture.SharedEngineTests().project()
        p.update(look_mode="ready", starting_asset=self.assets["1"])
        original = copy.deepcopy(p)
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"):
            graph, stage = studio.editable_graph(p, "design")
        self.assertEqual(p, original, "Export must not change saved approvals or inputs")
        self.assertEqual(graph["starting_frame"]["inputs"]["image"], "reference_1.png")
        self.assertEqual({n["class_type"] for n in graph.values()}, {"LoadImage", "PreviewImage"})

    def test_person_and_object_selections_share_the_reference_path(self):
        p = fixture.SharedEngineTests().project()
        p["references"] = [self.assets["1"], self.assets["2"]]
        p["config"] = studio.clean_config({**p["config"], "workflow_mode": "swap", "mask_method": "text", "mask_prompt": "chair"})
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"):
            graph = studio.build_graph(p, "design")
        self.assertIn("the area described as chair", graph["127"]["inputs"]["value"])
        self.assertIn("zura_reference_2", graph)

    def test_approving_selection_binds_ready_frame_without_queueing_design(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "genj_studio" / ("b" * 32) / "reference.png"
            path.parent.mkdir(parents=True)
            Image.new("RGB", (8, 6), (90, 120, 150)).save(path)
            asset = {"kind": "asset", "asset_kind": "image", "id": "b" * 32,
                "file": path.relative_to(root).as_posix(), "sha": hashlib.sha256(path.read_bytes()).hexdigest()}
            p = fixture.SharedEngineTests().project()
            p.update(look_mode="ready", starting_asset=asset, phase="review", approval=None,
                     opening_input=None, opening_key=None, opening_approval=None)
            p["prepared_key"] = studio.prep_key(p)
            controller = studio.Studio.__new__(studio.Studio)
            controller.collect = lambda project: project
            controller.store = MagicMock()
            with patch("ComfyUI_zura_nodes.artist_studio.verify_review", create=True), patch.object(studio, "assert_approved"), \
                 patch.object(studio, "check_asset", return_value=path), \
                 patch.object(studio.folder_paths, "get_input_directory", return_value=str(root)):
                result = asyncio.run(controller.action(p, "approve", {}))
            self.assertEqual(result["phase"], "opening")
            self.assertEqual(result["opening_key"], asset["sha"])
            self.assertEqual((root / result["opening_input"]["file"]).read_bytes(), path.read_bytes())
            self.assertEqual(result["actions"], [], "The ready route must not create a generation action")


if __name__ == "__main__":
    unittest.main()
