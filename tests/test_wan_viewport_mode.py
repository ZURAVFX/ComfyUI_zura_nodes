"""Wan viewport-to-scene graph contract; builds only, never samples."""
import importlib
import unittest
from unittest.mock import patch

import test_artist_studio as fixture

studio = fixture.studio
wan = fixture.wan


class WanViewportModeTests(unittest.TestCase):
    def test_viewport_mode_uses_approved_scene_look_and_whole_frame_route(self):
        project = fixture.SharedEngineTests().project()
        project["viewport_render"] = True
        project["viewport_references"] = [
            {"file": f"train_ref_{index}.png", "sha": str(index) * 64}
            for index in range(1, 6)
        ]

        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                patch.object(wan, "cache_key", return_value="a" * 64):
            graph = wan.build_wan_graph(project, use_cache=False)

        self.assertEqual(graph["wan_character"]["inputs"]["image"], "opening.png")
        self.assertNotIn("wan_sam", graph)
        self.assertEqual(graph["wan_cached"]["inputs"]["reference"], ["wan_character", 0])
        self.assertTrue(graph["wan_render"]["inputs"]["viewport_render"])
        prompt = graph["wan_render"]["inputs"]["prompt"]
        self.assertIn("entire grey 3D viewport/blockout", prompt)
        self.assertIn("exact camera path", prompt)
        self.assertIn("source camera movement, parallax", prompt)
        self.assertIn("approved opening image as the single consolidated appearance reference", prompt)

    def test_legacy_wan_graph_does_not_enable_viewport_conditioning(self):
        project = fixture.SharedEngineTests().project()
        project["config"]["edit_area"] = "mask"
        project["config"]["viewport_render"] = False
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                patch.object(wan, "cache_key", return_value="a" * 64):
            graph = wan.build_wan_graph(project, use_cache=False)
        self.assertFalse(graph["wan_render"]["inputs"]["viewport_render"])
        self.assertEqual(graph["wan_character"]["inputs"]["image"], "character.png")
        self.assertIn("wan_character_crop", graph)

    def test_viewport_cache_key_tracks_approved_scene_opening(self):
        project = fixture.SharedEngineTests().project()
        project["viewport_render"] = True
        with fixture.tempfile.TemporaryDirectory() as temp:
            pose = fixture.Path(temp) / "pose.onnx"
            detector = fixture.Path(temp) / "detector.onnx"
            pose.write_bytes(b"pose")
            detector.write_bytes(b"detector")
            import folder_paths
            original = folder_paths.get_full_path

            def model_path(folder, name):
                if name == wan.WAN_MODELS["wan_pose"][1]:
                    return str(pose)
                if name == wan.WAN_MODELS["wan_detector"][1]:
                    return str(detector)
                return original(folder, name)

            with patch.object(folder_paths, "get_full_path", side_effect=model_path):
                first = wan.cache_key(project)
                project["opening_input"]["sha"] = "changed approved scene"
                second = wan.cache_key(project)
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
