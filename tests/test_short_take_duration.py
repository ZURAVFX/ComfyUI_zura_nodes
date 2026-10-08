"""Guard the short-take workflow against silent truncation and frame drift."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

from multicam_test_support import prepare_comfy_imports


prepare_comfy_imports()
spec = importlib.util.spec_from_file_location(
    "short_take_duration_tested", Path(__file__).resolve().parents[1] / "multicam_v3.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ShortTakeDurationTests(unittest.TestCase):
    def test_frame_exact_default_and_safe_boundaries(self):
        node = mod.ZuraShortTakeDuration()
        for seconds, frames in ((0.5, 12), (4, 96), (5, 120)):
            with self.subTest(seconds=seconds):
                self.assertEqual(node.duration(seconds), (seconds, frames))

    def test_fractional_duration_rounds_to_a_whole_source_frame(self):
        seconds, frames = mod.ZuraShortTakeDuration().duration(1.1)
        self.assertEqual(frames, 26)
        self.assertEqual(seconds * 24, frames)

    def test_invalid_or_unsupported_lengths_fail_explicitly(self):
        for value in (0, 0.49, 5.01, float("nan"), float("inf"), "bad", None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "0.5 to 5 seconds"):
                mod.ZuraShortTakeDuration().duration(value)

    def test_registered_schema_matches_workflow_connections(self):
        node_class = mod.NODE_CLASS_MAPPINGS["ZuraShortTakeDuration"]
        self.assertIs(node_class, mod.ZuraShortTakeDuration)
        self.assertEqual(node_class.RETURN_TYPES, ("FLOAT", "INT"))
        kind, settings = node_class.INPUT_TYPES()["required"]["seconds"]
        self.assertEqual((kind, settings["default"], settings["min"], settings["max"]),
                         ("FLOAT", 4.0, 0.5, 5.0))


if __name__ == "__main__":
    unittest.main()
