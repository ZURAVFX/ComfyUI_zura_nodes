"""Pure unit tests for Zura's optional Klein edit controls."""
from __future__ import annotations

import importlib
import unittest

import v2_bootstrap  # noqa: F401


nodes = importlib.import_module("ComfyUI_zura_nodes.klein_look")


class KleinLookTests(unittest.TestCase):
    def test_default_preserves_source_scene_and_identity(self):
        prompt, enabled, background = nodes.ZuraKleinLookPresets.build()
        self.assertFalse(enabled)
        self.assertEqual(background, "Keep source background")
        self.assertIn("Preserve the exact person", prompt)
        self.assertIn("Keep the original lighting", prompt)
        self.assertIn("Keep the original background", prompt)

    def test_white_studio_and_edge_light_are_independent(self):
        prompt, enabled, _ = nodes.ZuraKleinLookPresets.build(
            enable_edit=True, lighting="Soft studio", edge_light=True,
            background="Clean white studio",
        )
        self.assertTrue(enabled)
        self.assertIn("soft frontal studio key light", prompt)
        self.assertIn("subtle rim light", prompt)
        self.assertIn("seamless matte white studio", prompt)

    def test_solid_and_gradient_colours(self):
        solid, _, _ = nodes.ZuraKleinLookPresets.build(
            enable_edit=True, background="Solid colour", background_colour="dusty blue"
        )
        gradient, _, _ = nodes.ZuraKleinLookPresets.build(
            enable_edit=True, background="Two-colour gradient",
            background_colour="cream", gradient_end_colour="slate",
        )
        self.assertIn("dusty blue studio backdrop", solid)
        self.assertIn("from cream to slate", gradient)

    def test_custom_environment_requires_description(self):
        with self.assertRaisesRegex(ValueError, "custom environment"):
            nodes.ZuraKleinLookPresets.build(enable_edit=True, background="Custom environment")
        prompt, enabled, _ = nodes.ZuraKleinLookPresets.build(background="Custom environment")
        self.assertFalse(enabled)
        self.assertIn("Keep the original background", prompt)

    def test_studio_camera_and_complete_environment_swap(self):
        studio, _, _ = nodes.ZuraKleinLookPresets.build(
            enable_edit=True, lighting="Three-point studio",
            background="Neutral grey studio", camera_finish="Clean studio camera")
        self.assertIn("soft key light 45 degrees", studio)
        self.assertIn("professional studio-camera", studio)
        self.assertIn("neutral-grey studio cyclorama", studio)
        swapped, _, _ = nodes.ZuraKleinLookPresets.build(
            enable_edit=True, lighting="Match new environment",
            background="Custom environment", custom_environment="a sunlit modern gallery",
            camera_finish="Editorial portrait camera")
        self.assertIn("entire original room", swapped)
        self.assertIn("sunlit modern gallery", swapped)
        self.assertIn("light interaction", swapped)

    def test_switch_is_lazy_and_returns_selected_image(self):
        node = nodes.ZuraOptionalImageEdit()
        self.assertEqual(node.check_lazy_status(enable_edit=False), ["original"])
        self.assertEqual(node.check_lazy_status(enable_edit=True), ["edited"])
        self.assertEqual(node.check_lazy_status(enable_edit=False, original="source"), [])
        self.assertEqual(node.select(enable_edit=False, original="source"), ("source",))
        self.assertEqual(node.select(enable_edit=True, edited="modified"), ("modified",))
        with self.assertRaisesRegex(ValueError, "selected image branch"):
            node.select(enable_edit=True, original="source")


if __name__ == "__main__":
    unittest.main()
