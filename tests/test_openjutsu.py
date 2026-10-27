"""Optional OpenJutsu recipe validation without models or a GPU."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("openjutsu", Path(__file__).parents[1] / "artist_studio" / "openjutsu.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OpenJutsuTests(unittest.TestCase):
    def project(self):
        return {"id": "test123", "source": {"file": "source.mp4", "duration": 10},
                "character": {"file": "character.png"}, "references": [{"file": "character.png"}],
                "config": {"engine": "h3", "workflow_mode": "swap", "duration": 5,
                           "start": 3, "seed": 42, "openjutsu_resolution": "480"}}

    def test_no_anchor_has_no_dangling_inputs_and_keeps_native_mask(self):
        p = self.project()
        checked = []
        graph = module.build_graph(p, checked.append)
        self.assertEqual(checked, [p["source"], p["character"]])
        self.assertFalse(graph["803"]["inputs"]["use_anchor"])
        self.assertTrue(graph["803"]["inputs"]["use_mask"])
        self.assertNotIn("anchor", graph["803"]["inputs"])
        self.assertEqual(graph["trim"]["inputs"]["start_time"], 3)
        for node in graph.values():
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2:
                    self.assertIn(value[0], graph)

    def test_existing_starting_frame_is_used_without_paid_api(self):
        p = self.project()
        p["opening_input"] = {"file": "approved.png"}
        g = module.build_graph(p)
        self.assertTrue(g["803"]["inputs"]["use_anchor"])
        self.assertEqual(g["anchor_image"]["inputs"]["image"], "approved.png")
        self.assertEqual(g["801"]["inputs"]["steps"], 8)
        self.assertFalse(any("API" in n["class_type"] for n in g.values()))

    def test_unsupported_tasks_are_rejected(self):
        for key, value in (("duration", 6), ("scope", "head"), ("performer", 2),
                           ("audio_id", "track"), ("remove_text", True), ("engine", "wan"),
                           ("openjutsu_resolution", "1080"), ("start", float("nan")),
                           ("finished_frame_position", "last"), ("subject_mode", "objects"), ("mask_method", "points")):
            p = self.project()
            p["config"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                module.build_graph(p)

    def test_background_replacement_uses_native_unmasked_branch_and_scene_anchor(self):
        p = self.project()
        p['config']['openjutsu_background'] = 'replace'
        with self.assertRaisesRegex(ValueError, 'starting frame'):
            module.build_graph(p)
        p['opening_input'] = {'file': 'new_scene.png'}
        g = module.build_graph(p)
        self.assertFalse(g['803']['inputs']['use_mask'])
        self.assertTrue(g['803']['inputs']['use_anchor'])
        self.assertNotIn('body_mask', g['803']['inputs'])
        self.assertFalse(any('SAM3' in n['class_type'] for n in g.values()))
        self.assertIn('<Picture 2>', g['801']['inputs']['prompt'])
        for node in g.values():
            for value in node['inputs'].values():
                if isinstance(value, list) and len(value) == 2:
                    self.assertIn(value[0], g)

    def test_direct_character_route_ignores_previous_generated_frame(self):
        p = self.project()
        p['config']['openjutsu_direct'] = True
        p['opening_input'] = {'file': 'stale_generation.png'}
        g = module.build_graph(p)
        self.assertFalse(g['803']['inputs']['use_anchor'])
        self.assertTrue(g['803']['inputs']['use_mask'])

    def test_uploaded_frame_is_honoured_even_if_direct_flag_was_remembered(self):
        p = self.project()
        p['look_mode'] = 'ready'
        p['config']['openjutsu_direct'] = True
        p['opening_input'] = {'file': 'uploaded.png'}
        g = module.build_graph(p)
        self.assertTrue(g['803']['inputs']['use_anchor'])
        self.assertEqual(g['anchor_image']['inputs']['image'], 'uploaded.png')

    def test_dependency_diagnostic_identifies_optional_nodes(self):
        g = module.build_graph(self.project())
        r = module.readiness(g, {})
        self.assertFalse(r["ready"])
        self.assertIn("H3CharacterSwapController", r["missing"])


if __name__ == "__main__":
    unittest.main()
