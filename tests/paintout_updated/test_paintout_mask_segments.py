"""Overlap, reversible trims, correction isolation and immutable mask history."""
import importlib
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
package = types.ModuleType('segment_test')
package.__path__ = [str(ROOT / 'paintout')]
sys.modules[package.__name__] = package
store = importlib.import_module('segment_test.editor_store')
segments = importlib.import_module('segment_test.mask_segments')


class MaskSegmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.patch = patch.object(store, 'project_root', return_value=self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.source = self.root / 'shot.mkv'
        self.source.write_bytes(b'fixture')
        self.description = dict(width=8, height=6, count=8)
        self.identity = store.source_identity(str(self.source), self.description)
        self.project = store.save_project(data={'draft': {'source': str(self.source)}})['id']
        self.a = np.zeros((6, 8), np.float32)
        self.a[1:4, 1:4] = 1
        self.b = np.zeros_like(self.a)
        self.b[2:5, 3:6] = 1

    def commit(self, name, mask, start=0, end=7, tracked=True):
        return store.commit_mask_pass(self.project, self.identity, {f: mask for f in range(start, end+1)},
                                      'replace', store._read(self.project)['revision'],
                                      {'segment_id': name*24, 'frame': start, 'tracked': tracked})

    def edit(self, name, **change):
        browser = types.ModuleType('segment_test.browser')
        browser.checked_path = pathlib.Path
        with patch.dict(sys.modules, {'segment_test.browser': browser}), patch('segment_test.paintout.describe', return_value=self.description), patch.object(store, 'project_response', side_effect=lambda doc: doc):
            return segments.edit_segment(dict(project=self.project, segment_id=name*24,
                                              expected_revision=store._read(self.project)['revision'], **change))

    def test_overlapping_masks_trim_restore_delete_and_undo(self):
        original = self.commit('a', self.a)
        second = self.commit('b', self.b)
        union = np.maximum(self.a, self.b)
        np.testing.assert_array_equal(store.read_project_mask(self.project, 1), union)
        np.testing.assert_array_equal(segments.read_other_segments(self.project, 'a'*24, 1), self.b)
        self.edit('a', start=2, end=5)
        np.testing.assert_array_equal(store.read_project_mask(self.project, 1), self.b)
        np.testing.assert_array_equal(store.read_project_mask(self.project, 3), union)
        self.edit('a', start=0, end=7)
        np.testing.assert_array_equal(store.read_project_mask(self.project, 1), union)
        self.edit('a', delete=True)
        np.testing.assert_array_equal(store.read_project_mask(self.project, 3), self.b)
        store.select_mask_revision(self.project, second['revision'], store._read(self.project)['revision'])
        self.assertEqual(len(segments.segments_for(store._mask_manifest(self.project))), 2)
        np.testing.assert_array_equal(store.read_project_mask(self.project, 1), union)
        np.testing.assert_array_equal(store.read_project_mask(self.project, 1, original['revision']), self.a)

    def test_erasing_selected_frame_preserves_other_segment_and_neighbours(self):
        self.commit('a', self.a)
        self.commit('b', self.b)
        self.commit('a', np.zeros_like(self.a), 3, 3, False)
        np.testing.assert_array_equal(store.read_project_mask(self.project, 3), self.b)
        np.testing.assert_array_equal(store.read_project_mask(self.project, 2), np.maximum(self.a, self.b))
        np.testing.assert_array_equal(segments.read_segment(self.project, 'a'*24, 3), np.zeros_like(self.a))

    def test_tracking_after_trim_preserves_trim_and_prior_frames(self):
        self.commit('a', self.a)
        self.edit('a', start=2, end=6)
        self.commit('a', self.b, 4, 6)
        mask = segments.segments_for(store._mask_manifest(self.project))[0]
        self.assertEqual((mask['start'], mask['end']), (2, 6))
        np.testing.assert_array_equal(store.read_project_mask(self.project, 2), self.a)
        np.testing.assert_array_equal(store.read_project_mask(self.project, 4), self.b)
        np.testing.assert_array_equal(store.read_project_mask(self.project, 0), np.zeros_like(self.a))

    def test_single_preview_remains_draft_until_tracked(self):
        self.commit('a', self.a, 3, 3, False)
        self.assertFalse(segments.summaries(store._mask_manifest(self.project))[0]['tracked'])
        self.assertFalse(store.read_project_mask(self.project, 3).any())
        self.commit('a', self.a)
        self.assertTrue(segments.summaries(store._mask_manifest(self.project))[0]['tracked'])

    def test_legacy_masks_migrate_without_changing_pixels(self):
        store.commit_mask_pass(self.project, self.identity, {f: self.a for f in range(8)}, 'replace', 1)
        self.commit('b', self.b)
        self.assertEqual(segments.summaries(store._mask_manifest(self.project))[0]['id'], 'legacy')
        self.edit('b', delete=True)
        np.testing.assert_array_equal(store.read_project_mask(self.project, 2), self.a)

    def test_invalid_trim_and_stale_update_are_atomic(self):
        self.commit('a', self.a, 2, 5)
        revision = store._read(self.project)['revision']
        for change in ({'start': 1, 'end': 5}, {'start': 4, 'end': 3}, {'start': True, 'end': 5}):
            with self.assertRaises(ValueError):
                self.edit('a', **change)
            self.assertEqual(store._read(self.project)['revision'], revision)
        with self.assertRaises(store.RevisionConflict):
            segments.edit_segment(dict(project=self.project, segment_id='a'*24, expected_revision=1, start=2, end=3))

    def test_removing_last_mask_leaves_explicit_black_coverage(self):
        self.commit('a', self.a)
        self.edit('a', delete=True)
        manifest = store._mask_manifest(self.project)
        self.assertEqual(segments.summaries(manifest), [])
        self.assertEqual(len(manifest['files']), 8)
        self.assertFalse(store.read_project_mask(self.project, 4).any())

    def test_reset_correction_restores_tracked_frame_and_keeps_other_objects(self):
        original = self.commit('a', self.a)
        self.commit('b', self.b)
        self.commit('a', np.zeros_like(self.a), 3, 3, False)
        self.commit('a', np.ones_like(self.a), 4, 4, False)
        summary = segments.summaries(store._mask_manifest(self.project), self.project)[0]
        self.assertEqual(summary['correction_frames'], [3, 4])
        self.assertNotIn('tracked_files', summary)
        self.edit('a', reset_frame=3)
        np.testing.assert_array_equal(store.read_project_mask(self.project, 3), np.maximum(self.a, self.b))
        np.testing.assert_array_equal(segments.read_segment(self.project, 'a'*24, 4), np.ones_like(self.a))
        np.testing.assert_array_equal(segments.read_segment(self.project, 'a'*24, 2), self.a)
        np.testing.assert_array_equal(store.read_project_mask(self.project, 3, original['revision']), self.a)
        self.assertEqual(segments.summaries(store._mask_manifest(self.project), self.project)[0]['correction_frames'], [4])

    def test_retracking_replaces_baseline_for_reset(self):
        self.commit('a', self.a)
        self.commit('a', self.b, 3, 5, True)
        self.commit('a', np.zeros_like(self.a), 4, 4, False)
        self.edit('a', reset_frame=4)
        np.testing.assert_array_equal(segments.read_segment(self.project, 'a'*24, 4), self.b)

    def test_reset_rejects_unchanged_invalid_and_draft_frames_atomically(self):
        self.commit('a', self.a)
        self.commit('b', self.b, 3, 3, False)
        revision = store._read(self.project)['revision']
        for frame in (True, -1, 8, 2, '3'):
            with self.assertRaises(ValueError):
                self.edit('a', reset_frame=frame)
            self.assertEqual(store._read(self.project)['revision'], revision)
        with self.assertRaises(ValueError):
            self.edit('b', reset_frame=3)

    def test_old_project_correction_is_recovered_from_immutable_history(self):
        self.commit('a', self.a)
        self.commit('a', np.zeros_like(self.a), 3, 3, False)
        manifest = store._mask_manifest(self.project)
        for segment in manifest['segments']:
            segment.pop('tracked_files', None)
        path = store.project_dir(self.project) / 'masks' / str(manifest['revision']) / 'manifest.json'
        store._atomic_json(path, manifest)
        self.assertEqual(segments.summaries(manifest, self.project)[0]['correction_frames'], [3])
        self.edit('a', reset_frame=3)
        np.testing.assert_array_equal(segments.read_segment(self.project, 'a'*24, 3), self.a)

    def test_bad_mask_cannot_leave_orphan_or_modify_revision(self):
        self.commit('a', self.a)
        revision = store._read(self.project)['revision']
        count = len(list((store.project_dir(self.project)/'segment_sources').iterdir()))
        with self.assertRaises(ValueError):
            self.commit('b', np.ones((4, 4)))
        self.assertEqual(store._read(self.project)['revision'], revision)
        self.assertEqual(len(list((store.project_dir(self.project)/'segment_sources').iterdir())), count)


if __name__ == '__main__':
    unittest.main()
