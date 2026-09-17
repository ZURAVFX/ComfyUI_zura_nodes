"""Standalone tests for the Zura node naming convention.

Two nodes are general-purpose and say so with a plain name (``Zura Load Video``
loads any clip, ``Zura Mask`` masks any performer); the two that only make sense
with Wan 2.2 carry the model in the name.  Every class ID is kept from before
the Zura rename so graphs saved earlier still resolve.
"""
from __future__ import annotations

import importlib
import unittest

import v2_bootstrap  # noqa: F401

EXPECTED = {
    "driving_clip": ("TrendStudioV2DrivingClip", "Zura Load Video"),
    "mask_performer": ("TrendStudioV2MaskPerformer", "Zura Mask"),
    "render": ("TrendStudioV2Render", "Zura Wan 2.2 Looped Chunks Sampler"),
    "speed": ("TrendStudioV2Speed", "Zura Wan 2.2 Turbo Switch"),
}
# Nodes that only work with Wan 2.2 must name the model; the others must not
# pretend to be model specific.
WAN_SPECIFIC = {"render", "speed"}
GENERAL = {"driving_clip", "mask_performer"}


def node_module(name):
    return importlib.import_module(f"ComfyUI_zura_nodes.{name}")


def display_name(module_name):
    module = node_module(module_name)
    return next(iter(module.NODE_DISPLAY_NAME_MAPPINGS.values()))


class NamingTests(unittest.TestCase):
    def test_display_names_are_exact(self):
        for module_name, (class_id, display) in EXPECTED.items():
            module = node_module(module_name)
            self.assertEqual(list(module.NODE_CLASS_MAPPINGS), [class_id],
                             f"{module_name} must register exactly one node id")
            self.assertEqual(module.NODE_DISPLAY_NAME_MAPPINGS[class_id], display,
                             f"{module_name} display name drifted")
            self.assertTrue(display.startswith("Zura "), f"{display} must be a Zura node")

    def test_only_the_model_specific_nodes_name_the_model(self):
        for module_name in WAN_SPECIFIC:
            self.assertIn("Wan 2.2", display_name(module_name))
        for module_name in GENERAL:
            self.assertNotIn("Wan 2.2", display_name(module_name))

    def test_category_is_zura(self):
        for module_name, (class_id, _) in EXPECTED.items():
            cls = node_module(module_name).NODE_CLASS_MAPPINGS[class_id]
            self.assertEqual(cls.CATEGORY, "Zura")


if __name__ == "__main__":
    unittest.main()
