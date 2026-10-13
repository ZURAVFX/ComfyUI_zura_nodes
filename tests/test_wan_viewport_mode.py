"""Wan viewport-to-scene graph contract; builds only, never samples."""
import unittest
from unittest.mock import patch

import test_artist_studio as fixture

studio = fixture.studio
wan = fixture.wan


class WanViewportModeTests(unittest.TestCase):
    def test_viewport_requests_reject_before_approval_assets_or_preparation(self):
        for flag in ("project", "config", "workflow_mode"):
            for use_cache in (False, True):
                with self.subTest(flag=flag, use_cache=use_cache):
                    project = fixture.SharedEngineTests().project()
                    if flag == "project":
                        project["viewport_render"] = True
                    elif flag == "config":
                        project["config"]["viewport_render"] = True
                    else:
                        project["config"]["workflow_mode"] = "viewport"
                    with patch.object(studio, "assert_approved") as approval, \
                            patch.object(studio, "check_asset") as asset, \
                            patch.object(wan, "cache_key") as preparation:
                        with self.assertRaisesRegex(ValueError, "Choose H3.*LTX.*experimental"):
                            wan.build_wan_graph(project, use_cache=use_cache,
                                                cache_key_override="a" * 64)
                    approval.assert_not_called()
                    asset.assert_not_called()
                    preparation.assert_not_called()

    def test_explicit_objects_reject_before_model_lookup(self):
        project = fixture.SharedEngineTests().project()
        project["config"]["subject_mode"] = "objects"
        with self.assertRaisesRegex(ValueError, "human performance"):
            wan.build_wan_graph(project)
        with self.assertRaisesRegex(ValueError, "human performance"):
            wan.cache_key(project)

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

    def test_legacy_full_scene_restyle_still_routes_to_ltx(self):
        project = fixture.SharedEngineTests().project()
        project["config"]["background"] = "restyle"
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"):
            with self.assertRaisesRegex(ValueError, "Choose LTX for scene restyling"):
                wan.build_wan_graph(project, use_cache=False)

    def test_viewport_cache_key_rejects_before_preparation_model_lookup(self):
        project = fixture.SharedEngineTests().project()
        project["viewport_render"] = True
        import folder_paths
        with patch.object(folder_paths, "get_full_path") as model_lookup:
            with self.assertRaisesRegex(ValueError, "Wan is not available for viewport-to-final"):
                wan.cache_key(project)
        model_lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
