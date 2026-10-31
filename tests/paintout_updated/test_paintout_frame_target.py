"""Named removal preserves other objects within broad painted search bounds."""
import importlib.util
import sys
import unittest
from unittest.mock import patch as mock_patch
import numpy as np
import torch
from test_paintout_frame_editor import editor, ROOT

spec = importlib.util.spec_from_file_location('zura_frame_test.frame_target', ROOT/'paintout/frame_target.py')
target = importlib.util.module_from_spec(spec); sys.modules[spec.name] = target; spec.loader.exec_module(target)


class NamedTargetTests(unittest.TestCase):
    def fixture(self, width=192, height=128, max_side=256, protect=False):
        image = np.full((height, width, 3), .2, np.float32)
        image[30:65, 35:65] = [1, .3, 0]
        image[30:65, 90:120] = [.7, .7, .7]
        mask = np.zeros((height, width), np.float32); mask[25:70, 30:125] = 1
        protection = np.zeros_like(mask)
        if protect: protection[40:45, 100:105] = 1
        crop, matte, patch = editor.prepare_plate_patch(image, mask, 13, 0, 30, max_side, protection)
        chosen = np.zeros_like(patch['mask']); chosen[30:65, 90:120] = 1
        # Shared plate processing can differ from source dimensions.
        chosen = target._resize_mask((image[:, :, 0] == .7).astype(np.float32), *patch['mask'].shape)
        detections = torch.from_numpy(target._model_mask(chosen, patch))[None]
        return image, crop, patch, detections

    def test_only_named_subject_replaced_within_broad_paint(self):
        original, crop, patch, masks = self.fixture()
        erased, refined = target.refine_target(patch, crop, masks, 'silver car')
        final = editor.composite_patch(refined, torch.ones_like(erased), False)
        support = refined['delivery_mask'] > .001
        np.testing.assert_array_equal(final[~support], original[~support])
        np.testing.assert_array_equal(final[30:65, 35:65], original[30:65, 35:65])
        self.assertEqual(refined['delivery_grow'], 0)
        self.assertEqual(refined['grow'], 0)
        self.assertEqual(refined['target_name'], 'silver car')
        self.assertEqual(editor.decode_mask(refined['target_mask'], original.shape[1], original.shape[0]).shape, original.shape[:2])
        self.assertEqual(patch['delivery_grow'], 13)

    def test_protected_pixels_unchanged(self):
        original, crop, patch, masks = self.fixture(protect=True)
        erased, refined = target.refine_target(patch, crop, masks, 'silver car')
        final = editor.composite_patch(refined, torch.ones_like(erased), False)
        np.testing.assert_array_equal(final[40:45, 100:105], original[40:45, 100:105])

    def test_ambiguous_and_missing_fail_clearly(self):
        _, crop, patch, masks = self.fixture()
        with self.assertRaisesRegex(ValueError, 'more than one'):
            target.refine_target(patch, crop, torch.cat([masks, masks]), 'car')
        with self.assertRaisesRegex(ValueError, 'Could not find'):
            target.refine_target(patch, crop, torch.zeros_like(masks), 'car')
        with self.assertRaisesRegex(ValueError, 'invalid mask'):
            target.refine_target(patch, crop, torch.zeros(1, 4, 4), 'car')

    def test_subject_touching_source_edge_has_no_padding_offset(self):
        original = np.full((91, 157, 3), .2, np.float32)
        mask = np.zeros((91, 157), np.float32); mask[15:60, 130:] = 1
        crop, matte, patch = editor.prepare_plate_patch(original, mask, 9, 0, 20, 64)
        erased, refined = target.refine_target(patch, crop, matte, 'edge object')
        self.assertTrue(np.any(refined['delivery_mask'][:, -1]))
        final = editor.composite_patch(refined, torch.ones_like(erased), False)
        np.testing.assert_array_equal(final[refined['delivery_mask'] == 0], original[refined['delivery_mask'] == 0])
        self.assertEqual(erased.shape, crop.shape)

    def test_odd_shared_plate_downsize_and_hdr_untouched(self):
        original, crop, patch, masks = self.fixture(317, 181, 64)
        patch.update(hdr_original=original*12-1, hdr_source_space='acescg')
        erased, refined = target.refine_target(patch, crop, masks, 'silver car')
        with mock_patch.object(editor, 'unworking', side_effect=lambda image, *args: image):
            final = editor.composite_patch(refined, torch.ones_like(erased), False)
        outside = refined['delivery_mask'] <= .001
        np.testing.assert_array_equal(final[outside], patch['hdr_original'][outside])
        self.assertEqual(final.shape, original.shape)


if __name__ == '__main__': unittest.main()
