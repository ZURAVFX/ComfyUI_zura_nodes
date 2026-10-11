"""Synthetic CPU contracts for point and whole-scene artist selection."""
import importlib
import json
import sys
import types
import unittest

import v2_bootstrap
import torch

NAME = "ComfyUI_zura_nodes.artist_studio"
package = sys.modules.setdefault(NAME, types.ModuleType(NAME))
package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
selection = importlib.import_module(NAME + ".mask_selection")


class MaskSelectionTests(unittest.TestCase):
    def setUp(self):
        self.image = torch.zeros(1, 120, 200, 3)
        self.points = selection.ZuraMaskPoints()

    def convert(self, points, image=None):
        positive, negative = self.points.coordinates(self.image if image is None else image, json.dumps(points))
        return json.loads(positive), json.loads(negative)

    def test_non_square_corners_and_edge_one_remain_inside_actual_image(self):
        positive, negative = self.convert([{"x": 0, "y": 0, "include": True},
            {"x": 1, "y": 1, "include": True}, {"x": .75, "y": .5, "include": True}])
        self.assertEqual(positive, [{"x": 0, "y": 0}, {"x": 199, "y": 119}, {"x": 150, "y": 60}])
        self.assertEqual(negative, [])

    def test_display_letterbox_is_removed_before_normalized_mapping(self):
        # A 200x120 image fitted inside 640x640 has a 640x384 image rectangle.
        # The artist clicks (160, 416), corresponding to (.25, .75) in the image.
        displayed_x, displayed_y = 160, 416
        normalized = {"x": displayed_x / 640, "y": (displayed_y - 128) / 384, "include": True}
        positive, _ = self.convert([normalized])
        self.assertEqual(positive, [{"x": 50, "y": 90}])
        # The same normalized selection uses the real resolution of another image.
        positive, _ = self.convert([normalized], torch.zeros(1, 240, 400, 3))
        self.assertEqual(positive, [{"x": 100, "y": 180}])

    def test_exclusions_are_separate_native_sam_json_point_arrays(self):
        positive, negative = self.convert([{"x": .1, "y": .2, "include": True},
            {"x": .8, "y": .9, "include": False}, {"x": 1, "y": 0, "include": False}])
        self.assertEqual(positive, [{"x": 20, "y": 24}])
        self.assertEqual(negative, [{"x": 160, "y": 108}, {"x": 199, "y": 0}])

    def test_all_32_points_and_single_pixel_image_are_supported(self):
        points = [{"x": i / 31, "y": i / 31, "include": True} for i in range(32)]
        positive, _ = self.convert(points)
        self.assertEqual(len(positive), 32)
        positive, _ = self.convert([{"x": 1, "y": 1, "include": True}], torch.zeros(1, 1, 1, 3))
        self.assertEqual(positive, [{"x": 0, "y": 0}])

    def test_malformed_shapes_empty_oversize_and_unknown_fields_fail(self):
        invalid = ([], {}, {"x": .5, "y": .5, "include": True}, ["point"],
            [[.5, .5]], [{"x": .5, "y": .5}], [{"x": .5, "y": .5, "include": True, "z": 0}],
            [{"x": .5, "y": .5, "include": True}] * 33)
        for points in invalid:
            with self.subTest(points=points), self.assertRaises(ValueError):
                self.convert(points)
        for text in ("not points", "[", " " * (selection.MAX_POINT_TEXT + 1), None):
            with self.subTest(text_type=type(text)), self.assertRaises(ValueError):
                self.points.coordinates(self.image, text)
        with self.assertRaisesRegex(ValueError, "one position"):
            self.points.coordinates(self.image, '[{"x":0,"x":1,"y":0,"include":true}]')

    def test_numbers_must_be_finite_normalized_and_not_booleans(self):
        for field in ("x", "y"):
            for value in (True, False, None, ".5", float("nan"), float("inf"), float("-inf"), -.1, 1.1, 10**400):
                point = {"x": .5, "y": .5, "include": True, field: value}
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.convert([point])

    def test_include_is_boolean_and_at_least_one_positive_is_required(self):
        for value in (1, 0, None, "true", "false"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "include or exclude"):
                self.convert([{"x": .5, "y": .5, "include": value}])
        with self.assertRaisesRegex(ValueError, "at least one point"):
            self.convert([{"x": .5, "y": .5, "include": False}])

    def test_whole_scene_selects_every_frame_as_float32_on_the_same_device(self):
        images = torch.zeros(3, 17, 31, 3, dtype=torch.float64)
        mask, = selection.ZuraWholeSceneMask().select(images)
        self.assertEqual(mask.shape, (3, 17, 31))
        self.assertEqual(mask.dtype, torch.float32)
        self.assertEqual(mask.device, images.device)
        self.assertTrue(torch.isfinite(mask).all())
        self.assertTrue((mask == 1).all())
        self.assertTrue((images == 0).all())

    def test_invalid_image_shapes_fail_and_points_require_one_opening_frame(self):
        for image in (None, torch.zeros(2, 3), torch.zeros(1, 4, 4, 4), torch.zeros(0, 4, 4, 3),
                      torch.zeros(1, 0, 4, 3), torch.zeros(1, 4, 4, 3, dtype=torch.int32)):
            with self.subTest(shape=getattr(image, "shape", None)), self.assertRaises(ValueError):
                selection.ZuraWholeSceneMask().select(image)
        with self.assertRaisesRegex(ValueError, "one opening frame"):
            self.convert([{"x": .5, "y": .5, "include": True}], torch.zeros(2, 4, 4, 3))

    def test_native_types_and_zura_registration_are_explicit(self):
        self.assertEqual(selection.ZuraMaskPoints.RETURN_TYPES, ("STRING", "STRING"))
        self.assertEqual(selection.ZuraWholeSceneMask.RETURN_TYPES, ("MASK",))
        self.assertEqual(set(selection.NODE_CLASS_MAPPINGS), {"ZuraMaskPoints", "ZuraWholeSceneMask"})
        self.assertTrue(all(label.startswith("Zura") for label in selection.NODE_DISPLAY_NAME_MAPPINGS.values()))

    def test_saved_config_can_be_empty_or_negative_while_artist_is_selecting(self):
        self.assertEqual(selection.clean_points([]), [])
        negative = [{"x": .25, "y": .75, "include": False}]
        self.assertEqual(selection.clean_points(negative), negative)
        with self.assertRaisesRegex(ValueError, "at least one point"):
            selection.clean_points([], require_positive=True)
        with self.assertRaisesRegex(ValueError, "at least one point"):
            selection.clean_points(negative, require_positive=True)
        with self.assertRaises(ValueError):
            selection.clean_points([{**negative[0], "x": float("nan")}])
        with self.assertRaises(ValueError):
            selection.clean_points(negative * 33)

    def test_clean_points_returns_independent_normalized_copies_without_rounding(self):
        original = [{"x": .123456789, "y": 1, "include": True}]
        cleaned = selection.clean_points(original, require_positive=True)
        self.assertEqual(cleaned, original)
        self.assertIsNot(cleaned, original)
        self.assertIsNot(cleaned[0], original[0])
        cleaned[0]["x"] = 0
        self.assertEqual(original[0]["x"], .123456789)

    def test_excessive_nesting_and_integer_text_get_plain_selection_errors(self):
        for text in ("[" * 2000 + "0" + "]" * 2000,
                     '[{"x":' + "9" * 5000 + ',"y":0,"include":true}]'):
            with self.subTest(length=len(text)), self.assertRaisesRegex(ValueError, "selection point"):
                self.points.coordinates(self.image, text)


if __name__ == "__main__":
    unittest.main()
