"""Wan high-resolution chunk policy; builder-only checks with synthetic paths."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_artist_studio as fixtures

studio, wan = fixtures.studio, fixtures.wan


class WanHighResolutionChunkTests(unittest.TestCase):
    def test_only_1920_uses_shorter_chunks(self):
        for resolution in (256, 512, 768, 960, 1280):
            with self.subTest(resolution=resolution):
                self.assertEqual(wan._chunk_frames_for_resolution(resolution), 81)
        self.assertEqual(wan._chunk_frames_for_resolution(1920), 41)

    def test_inline_and_cached_builds_use_same_policy_without_changing_cache_identity(self):
        import folder_paths

        for resolution, expected_chunk in ((1280, 81), (1920, 41)):
            with self.subTest(resolution=resolution), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                model_paths = {}
                for identity in ("wan_pose", "wan_detector"):
                    _, filename = wan.WAN_MODELS[identity]
                    path = root / filename
                    path.write_bytes(filename.encode("utf-8"))
                    model_paths[filename] = path

                cache_file = root / "conditioning.pt"
                project = fixtures.SharedEngineTests().project()
                project["config"] = studio.clean_config({
                    **project["config"], "engine": "wan", "resolution": resolution,
                })
                original_config = copy.deepcopy(project["config"])

                def model_path(_folder, filename):
                    return str(model_paths[filename])

                with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                        patch.object(folder_paths, "get_full_path", side_effect=model_path), \
                        patch.object(wan, "cache_path", return_value=cache_file):
                    key_before = wan.cache_key(project)
                    inline = wan.build_wan_graph(project, use_cache=False)
                    cache_file.touch()
                    cached = wan.build_wan_graph(project, use_cache=True)
                    key_after = wan.cache_key(project)

                self.assertEqual(key_before, key_after)
                self.assertEqual(project["config"], original_config)
                for graph in (inline, cached):
                    render = graph["wan_render"]["inputs"]
                    self.assertEqual(render["chunk_frames"], expected_chunk)
                    self.assertEqual(render["overlap_frames"], 5)
                    self.assertEqual(render["max_side"], resolution)
                self.assertEqual(inline["wan_cached"]["class_type"], "ZuraWanPackPreparation")
                self.assertEqual(cached["wan_cached"]["class_type"], "ZuraWanLoadWindowPreparation")
                self.assertEqual(cached["wan_cached"]["inputs"]["max_window_frames"], expected_chunk)
                self.assertEqual(cached["wan_cached"]["inputs"]["cache_key"], key_before)
                self.assertEqual(cached["wan_render"]["class_type"], "ZuraWan22StreamedSampler")
                self.assertEqual(cached["wan_export"]["inputs"]["video"], ["wan_render", 0])
                self.assertEqual(inline["wan_export"]["inputs"]["video"], ["wan_render", 1])
                self.assertEqual(len(cached["wan_render"]["inputs"]["delivery_key"]), 64)


if __name__ == "__main__":
    unittest.main()
