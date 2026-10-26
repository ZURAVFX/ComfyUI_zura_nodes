import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from test_paintout_editor_store import editor


class MaskReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.patcher = patch.object(editor, 'project_root', return_value=self.root)
        self.patcher.start()
        self.project = editor.save_project(data={'draft': {'source': 'fixture'}})
        self.identity = dict(path='fixture', fingerprint='hash', width=40, height=40, count=12)
        self.mask = np.zeros((40, 40), np.float32)
        self.mask[10:20, 10:20] = 1

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def commit(self, masks, operation='replace', preserve_protection=False):
        doc = editor.load_project(self.project['id'])
        return editor.commit_mask_pass(self.project['id'], self.identity, masks, operation, doc['revision'], preserve_protection=preserve_protection)

    def response(self):
        return editor.project_response(editor.load_project(self.project['id']))

    def test_stable_and_small_area_fluctuations_do_not_flag_or_change_pixels(self):
        masks = {i: self.mask.copy() for i in range(4)}
        masks[2][10, 10] = 0
        self.commit(masks)
        self.assertEqual(self.response()['mask_review_ranges'], [])
        self.assertEqual(self.response()['mask_coverage'], [0, 1, 2, 3])
        for frame, mask in masks.items():
            np.testing.assert_array_equal(editor.read_project_mask(self.project['id'], frame), mask)

    def test_unmarked_empty_run_and_reappearance_have_source_frame_ranges(self):
        self.commit({2: self.mask, 3: np.zeros_like(self.mask), 4: np.zeros_like(self.mask), 5: self.mask})
        ranges = self.response()['mask_review_ranges']
        self.assertEqual([(r['start_frame'], r['end_frame'], r['reason']) for r in ranges],
                         [(3, 4, 'empty_after_visible'), (5, 5, 'reappeared')])
        self.assertTrue(all(r['status'] == 'needs_review' and r['label'] for r in ranges))
        self.assertEqual(self.response()['mask_coverage'], [2, 3, 4, 5])
        self.assertFalse(editor.read_project_mask(self.project['id'], 3).any())

    def test_sharp_nonempty_area_change_requires_ratio_and_pixel_delta(self):
        large = self.mask.copy()
        large[20:40, 10:20] = 1
        self.commit({0: self.mask, 1: large, 2: large})
        self.assertEqual([(r['start_frame'], r['reason']) for r in self.response()['mask_review_ranges']], [(1, 'area_change')])
        self.assertEqual(editor._mask_review_ranges({'0': 1, '1': 3}, [], 1600), [])
        self.assertEqual(editor._mask_review_ranges({'0': 100, '1': 200}, [], 1600), [])

    def test_explicit_absence_suppresses_gap_and_reappearance_warnings(self):
        self.commit({0: self.mask, 1: self.mask, 2: self.mask, 3: self.mask})
        self.commit({1: np.zeros_like(self.mask), 2: np.zeros_like(self.mask)}, 'absent')
        self.assertEqual(self.response()['mask_review_ranges'], [])
        manifest = editor._mask_manifest(self.project['id'])
        self.assertEqual(manifest['absent_frames'], [1, 2])
        self.commit({2: np.zeros_like(self.mask)}, 'replace')
        # An artist replaced the absent frame, so it is no longer explicitly absent.
        self.assertEqual(editor._mask_manifest(self.project['id'])['absent_frames'], [1])

    def test_partial_correction_recomputes_boundaries_and_undo_restores_review(self):
        first = self.commit({0: self.mask, 1: np.zeros_like(self.mask), 2: self.mask})
        before = self.response()['mask_review_ranges']
        paths = editor._mask_manifest(self.project['id'])['files']
        unchanged = pathlib.Path(paths['0']).read_bytes()
        self.commit({1: self.mask})
        self.assertEqual(self.response()['mask_review_ranges'], [])
        self.assertEqual(pathlib.Path(paths['0']).read_bytes(), unchanged)
        doc = editor.load_project(self.project['id'])
        editor.select_mask_revision(self.project['id'], first['revision'], doc['revision'])
        self.assertEqual(self.response()['mask_review_ranges'], before)

    def test_stats_use_quantised_saved_mask_after_preserved_protection(self):
        self.commit({0: self.mask, 1: self.mask})
        self.commit({1: self.mask}, 'protect')
        manifest = editor._mask_manifest(self.project['id'])
        self.assertEqual(manifest['area_counts']['1'], 0)
        self.commit({1: self.mask}, preserve_protection=True)
        self.assertEqual(editor._mask_manifest(self.project['id'])['area_counts']['1'], 0)
        tiny = self.mask * .0001
        self.commit({1: tiny})
        self.assertEqual(editor._mask_manifest(self.project['id'])['area_counts']['1'], 0)
        self.assertFalse(editor.read_project_mask(self.project['id'], 1).any())

    def test_gaps_in_untracked_coverage_are_not_inferred_as_empty_masks(self):
        self.commit({0: self.mask, 5: np.zeros_like(self.mask), 6: self.mask})
        self.assertEqual(self.response()['mask_review_ranges'], [])
        self.assertEqual(self.response()['mask_coverage'], [0, 5, 6])

    def test_legacy_manifest_is_upgraded_without_changing_existing_masks(self):
        self.commit({0: self.mask, 1: np.zeros_like(self.mask)})
        manifest = editor._mask_manifest(self.project['id'])
        path = editor.project_dir(self.project['id']) / 'masks' / str(manifest['revision']) / 'manifest.json'
        for key in ('area_counts', 'absent_frames', 'review_ranges'):
            manifest.pop(key)
        path.write_text(json.dumps(manifest), encoding='utf-8')
        self.commit({2: self.mask})
        self.assertEqual(editor._mask_manifest(self.project['id'])['area_counts'], {'0': 100, '1': 0, '2': 100})
        self.assertEqual(len(self.response()['mask_review_ranges']), 2)
        np.testing.assert_array_equal(editor.read_project_mask(self.project['id'], 0), self.mask)


if __name__ == '__main__':
    unittest.main()
