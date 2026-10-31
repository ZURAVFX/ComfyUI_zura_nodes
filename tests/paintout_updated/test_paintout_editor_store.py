import importlib
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
package = types.ModuleType("paintout_editor_test")
package.__path__ = [str(ROOT / "paintout")]
sys.modules[package.__name__] = package
editor = importlib.import_module(package.__name__ + ".editor_store")
core = importlib.import_module(package.__name__ + ".paintout")


class EditorStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.root_patch = patch.object(editor, "project_root", return_value=self.root)
        self.root_patch.start()
        self.project = editor.save_project(data={"source": "fixture"})
        self.project_id = self.project["id"]
        self.identity = dict(path="fixture", fingerprint="hash", width=5, height=5, count=8)

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def test_failed_revision_can_be_retried_without_orphan_directory(self):
        with self.assertRaises(ValueError):
            editor.commit_mask_pass(self.project_id, self.identity, {0: np.ones((5, 5)), 99: np.ones((5, 5))}, "replace", 1)
        self.assertFalse((editor.project_dir(self.project_id) / "masks" / "2").exists())
        self.assertFalse(list((editor.project_dir(self.project_id) / "masks").glob("pending_revision_*")))
        result = editor.commit_mask_pass(self.project_id, self.identity, {0: np.ones((5, 5))}, "replace", 1)
        self.assertEqual(result["revision"], 2)

    def test_untracked_is_distinct_from_explicit_absent_before_render(self):
        first = editor.commit_mask_pass(self.project_id, self.identity, {3: np.ones((5, 5))}, 'replace', 1)
        descriptor = editor.mask_descriptor(self.project_id, first['revision'])
        self.assertEqual(descriptor['covered_frames'], [3])
        with patch.object(editor, 'source_identity', return_value=self.identity), patch.object(core, 'describe', return_value={}):
            with self.assertRaisesRegex(ValueError, 'missing source frame: 0'):
                editor.ZuraPaintoutEditorCrop().prepare('fixture', descriptor, start_frame=0, frame_count=8)
        editor.commit_mask_pass(self.project_id, self.identity, {i: np.zeros((5, 5)) for i in range(8) if i != 3}, 'absent', first['project_revision'])
        covered = editor.mask_descriptor(self.project_id)['covered_frames']
        self.assertEqual(covered, list(range(8)))
        self.assertEqual(editor.project_response(editor.load_project(self.project_id))['mask_coverage'], covered)

    def test_protection_survives_growth_feather_add_and_descriptor_composite(self):
        initial = editor.commit_mask_pass(self.project_id, self.identity, {0: np.ones((5, 5))}, "replace", 1)
        protected = np.zeros((5, 5), np.float32)
        protected[:, 2] = 1
        result = editor.commit_mask_pass(self.project_id, self.identity, {0: protected}, "protect", initial["project_revision"])
        for grow, feather in ((2, 0), (0, 3), (2, 3)):
            preview = editor.read_project_mask(self.project_id, 0, result["revision"], grow, feather)
            self.assertFalse(preview[:, 2].any())
        added = editor.commit_mask_pass(self.project_id, self.identity, {0: np.ones((5, 5))}, "add", result["project_revision"])
        descriptor = editor.mask_descriptor(self.project_id, added["revision"])
        mask = next(core.mask_frames(descriptor, 0, 1))
        protection = core.protection_mask(descriptor, 0)
        original = np.random.default_rng(4).random((5, 5, 3), dtype=np.float32)
        combined, _ = core.composite_crop(original, np.ones_like(original), mask, 2, 3, False, protection=protection)
        np.testing.assert_array_equal(combined[:, 2], original[:, 2])
        self.assertFalse(editor.read_project_mask(self.project_id, 0, added["revision"], 2, 3)[:, 2].any())
        replacement = editor.commit_mask_pass(self.project_id, self.identity, {0: np.ones((5, 5))}, "replace", added["project_revision"])
        self.assertTrue(editor.read_project_mask(self.project_id, 0, replacement["revision"], 2, 3)[:, 2].all())
        # Undo restores both the removal mask and its immutable protection layer.
        editor.select_mask_revision(self.project_id, result["revision"], replacement["project_revision"])
        self.assertFalse(editor.read_project_mask(self.project_id, 0, grow=2, feather=3)[:, 2].any())

    def test_manual_seed_preserves_full_resolution_thin_stroke(self):
        import base64
        import io
        import torch
        from PIL import Image
        source = self.root / "manual.mp4"
        source.write_bytes(b"fixture")
        description = dict(width=2051, height=17, count=1, path=str(source), kind="video")
        mask = np.zeros((17, 2051), np.uint8)
        mask[1, 1] = 255
        encoded = io.BytesIO()
        Image.fromarray(mask).save(encoded, format="PNG")
        browser = types.ModuleType(package.__name__ + ".browser")
        browser.checked_path = lambda value: pathlib.Path(value)
        browser.grant = lambda value: '/seed/' + pathlib.Path(value).name
        with patch.dict(sys.modules, {package.__name__ + ".browser": browser}), \
             patch.object(core, "describe", return_value=description), \
             patch.object(core, "selected_space", return_value="srgb_display"), \
             patch.object(editor, "_frame_batch", return_value=torch.zeros((1, 8, 1024, 3))):
            editor.ZuraPaintoutMaskPass().run(str(source), self.project_id, 0, 0, 1, "auto", "replace",
                paint_mask="data:image/png;base64," + base64.b64encode(encoded.getvalue()).decode(), expected_revision=1)
        np.testing.assert_array_equal(editor.read_project_mask(self.project_id, 0), mask / 255)

    def test_project_save_rejects_stale_revision(self):
        updated = editor.save_project(self.project_id, {"source": "updated"}, 1)
        with self.assertRaises(editor.RevisionConflict):
            editor.save_project(self.project_id, {"source": "stale"}, 1)
        self.assertEqual(editor.load_project(self.project_id), updated)
        self.assertEqual(list(self.root.rglob("*.tmp")), [])

    def test_project_ids_cannot_escape_store(self):
        for value in ("../private", "C:/temp", "..", "a" * 64, None):
            with self.assertRaises(ValueError):
                editor.project_dir(value)

    def test_partial_correction_preserves_earlier_masks_and_undo(self):
        first = editor.commit_mask_pass(self.project_id, self.identity, {1: np.ones((5, 5)), 5: np.eye(5)}, "replace", 1)
        before = editor.mask_descriptor(self.project_id, first["revision"])
        original_bytes = pathlib.Path(before["files"][1]).read_bytes()
        second = editor.commit_mask_pass(self.project_id, self.identity, {5: np.ones((5, 5))}, "protect", first["project_revision"])
        after = editor.mask_descriptor(self.project_id, second["revision"])
        self.assertEqual(before["files"][1], after["files"][1])
        self.assertEqual(original_bytes, pathlib.Path(after["files"][1]).read_bytes())
        self.assertFalse(editor.read_project_mask(self.project_id, 5).any())
        restored = editor.select_mask_revision(self.project_id, first["revision"], second["project_revision"])
        np.testing.assert_array_equal(editor.read_project_mask(self.project_id, 5), np.eye(5))
        self.assertEqual(len(restored["mask_history"]), 2)
        self.assertEqual(len(after["files"]), 8)
        self.assertFalse(editor.read_project_mask(self.project_id, 0).any())

    def test_stale_pass_is_never_committed(self):
        editor.save_project(self.project_id, {"changed": True}, 1)
        with self.assertRaises(editor.RevisionConflict):
            editor.commit_mask_pass(self.project_id, self.identity, {1: np.ones((5, 5))}, "replace", 1)
        self.assertEqual(editor.load_project(self.project_id)["mask_history"], [])

    def test_source_fingerprint_change_rejects_old_masks(self):
        first = editor.commit_mask_pass(self.project_id, self.identity, {1: np.ones((5, 5))}, "replace", 1)
        with self.assertRaises(ValueError):
            editor.commit_mask_pass(self.project_id, {**self.identity, "fingerprint": "changed"}, {2: np.ones((5, 5))}, "add", first["project_revision"])

    def test_foreign_mask_revision_is_rejected(self):
        with self.assertRaises(ValueError):
            editor.select_mask_revision(self.project_id, 999, 1)

    def test_wrong_mask_dimensions_are_rejected(self):
        with self.assertRaises(ValueError):
            editor.commit_mask_pass(self.project_id, self.identity, {0: np.ones((4, 4))}, "replace", 1)

    def test_native_mask_descriptor_and_typed_crop_bridge(self):
        result = editor.commit_mask_pass(self.project_id, self.identity, {3: np.ones((5, 5))}, "replace", 1)
        descriptor = editor.ZuraPaintoutMaskSource().load(self.project_id, result["revision"])[0]
        self.assertEqual(descriptor["kind"], "painted_tracking")
        self.assertEqual(descriptor["start"], 0)
        self.assertEqual(descriptor["count"], 8)
        self.assertTrue(pathlib.Path(descriptor["files"][0]).is_file())
        self.assertEqual(editor.ZuraPaintoutEditorCrop.INPUT_TYPES()["required"]["mask_path"], ("ZURA_MASK",))
        self.assertEqual(core.ZuraPaintoutCrop.INPUT_TYPES()["required"]["mask_path"][0], "STRING")

    def test_bidirectional_tracking_maps_back_to_absolute_source_frames(self):
        import torch
        source = self.root / "source.mp4"
        source.write_bytes(b"fixture")
        browser = types.ModuleType(package.__name__ + ".browser")
        browser.checked_path = lambda value: pathlib.Path(value)
        browser.grant = lambda value: '/seed/' + pathlib.Path(value).name
        description = dict(width=5, height=5, count=8, path=str(source), kind="video")
        test = self

        class Detect:
            @classmethod
            def execute(cls, **kwargs):
                test.assertNotIn("conditioning", kwargs)
                return (torch.ones((1, 5, 5)),)

        fake_nodes = types.SimpleNamespace(NODE_CLASS_MAPPINGS={"SAM3_Detect": Detect})
        calls = []

        def frame_batch(description, indices, space, proxy):
            calls.append(list(indices))
            return torch.stack([torch.full((5, 5, 3), (index + 1) / 10) for index in indices])

        def track(images, model, seed):
            result = torch.zeros(images.shape[:3])
            for index, image in enumerate(images):
                result[index].flatten()[:round(float(image[0, 0, 0]) * 10)] = 1
            return result

        with patch.dict(sys.modules, {package.__name__ + ".browser": browser, "nodes": fake_nodes}), \
             patch.object(core, "describe", return_value=description), \
             patch.object(core, "selected_space", return_value="srgb_display"), \
             patch.object(editor, "_frame_batch", side_effect=frame_batch), \
             patch.object(editor, "_native_masks", side_effect=track):
            result = editor.ZuraPaintoutMaskPass().run(str(source), self.project_id, 3, 1, 5, "auto", "replace",
                positive_coords='[{"x": 2, "y": 2}]', text="ignored with points", model=object(), conditioning=object(), expected_revision=1)
        self.assertIn([3, 4, 5], calls)
        self.assertIn([3, 2, 1], calls)
        for index in (1, 2, 4, 5):
            self.assertEqual(float(editor.read_project_mask(self.project_id, index).sum()), index + 1)
        self.assertEqual(float(editor.read_project_mask(self.project_id, 3).mean()), 1)
        self.assertFalse(editor.read_project_mask(self.project_id, 0).any())
        self.assertEqual(result["ui"]["zura_mask"][0]["start_frame"], 1)


class MorphologyTests(unittest.TestCase):
    def test_square_growth_and_outward_feather(self):
        mask = np.zeros((11, 11)); mask[5, 5] = 1
        alpha = editor.effective_mask(mask, 1, 2)
        np.testing.assert_array_equal(alpha[4:7, 4:7], np.ones((3, 3)))
        self.assertEqual(alpha[5, 3], .5)
        self.assertEqual(alpha[5, 2], 0)

    def test_empty_mask_remains_empty(self):
        self.assertFalse(editor.effective_mask(np.zeros((9, 9)), 50, 100).any())

    def test_protection_never_adds_coverage(self):
        base = np.eye(6, dtype=np.float32)
        self.assertFalse(editor.merge_mask(base, np.ones((6, 6)), "protect").any())
        self.assertFalse(editor.merge_mask(base, np.ones((6, 6)), "absent").any())

    def test_preview_matches_existing_compositor_at_edges(self):
        mask = np.zeros((23, 31), np.float32); mask[:5, :6] = 1; mask[12:14, 18:21] = 1
        original = np.zeros((23, 31, 3), np.float32)
        result, _ = core.composite_crop(original, np.ones_like(original), mask, 2, 5, False)
        np.testing.assert_array_equal(result[..., 0], editor.effective_mask(mask, 2, 5))


if __name__ == "__main__":
    unittest.main()
