import base64
import importlib
import json
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch
import numpy as np
from test_paintout_editor_store import editor, core, package

browser = types.ModuleType(package.__name__ + '.browser')
browser.checked_path = lambda value: pathlib.Path(value).resolve(strict=True)
browser.grant = lambda value: '/fixture/' + pathlib.Path(value).name
with patch.dict('sys.modules', {package.__name__ + '.browser': browser}):
    review = importlib.import_module(package.__name__ + '.import_review')


class ImportReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.source = self.root / 'source.exr'
        self.source.write_bytes(b'source')
        self.description = dict(kind='image', path=str(self.source), width=3, height=2, count=2)
        self.original = np.array([[[-2., 5., .2], [3., -4., 2.], [1., 2., 3.]], [[.1, .2, .3], [7., -8., 9.], [-9., 10., 12.]]], dtype=np.float32)
        self.edited = self.original.copy()
        self.edited[0, 0] += 1
        self.edited[1, 2] += 2
        self.saved = []
        def save(path, pixels, space, half):
            self.saved.append((pixels.copy(), space, half))
            pathlib.Path(path).write_bytes(b'exr')
        self.patches = [patch.object(editor, 'project_root', return_value=self.root / 'projects'),
                        patch.object(core, 'describe', return_value=self.description),
                        patch.object(core, 'frames', side_effect=lambda *args: iter([self.original])),
                        patch.object(core, 'read_image', side_effect=lambda *args: self.edited),
                        patch.object(core, 'save_exr', side_effect=save),
                        patch.object(review, 'validate_edit_orientation')]
        for item in self.patches:
            item.start()
        self.project = editor.save_project(data={'draft': {'source': str(self.source)}})
        self.id = self.project['id']
        self.imported = editor.project_dir(self.id) / 'imports' / 'edited.exr'
        self.imported.parent.mkdir(parents=True)
        self.imported.write_bytes(b'edit')
        self.mask = np.zeros((2, 3), bool)
        self.mask[0, 0] = True
        self.body = dict(project=self.id, source=str(self.source), frame=1, file=str(self.imported), source_colour_space='acescg', colour_space='acescg', grow=0, mask='data:image/png;base64,' + base64.b64encode(review._png(self.mask)).decode())

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def accept(self, result, scope='current', **updates):
        body = dict(project=self.id, source=str(self.source), frame=1, token=result['token'], scope=scope, expected_revision=editor.load_project(self.id)['revision'])
        body.update(updates)
        return review.accept_import_review(body)

    def test_current_exact_exterior_negative_hdr_and_include(self):
        before = editor.load_project(self.id)
        original = self.original.copy()
        result = review.review_import(self.body)
        self.assertEqual(result['outside_pixels'], 1)
        self.assertEqual(result['changed_pixels'], 2)
        row = self.accept(result)
        np.testing.assert_array_equal(self.saved[-1][0][~self.mask], original[~self.mask])
        np.testing.assert_array_equal(self.saved[-1][0][self.mask], self.edited[self.mask])
        self.assertEqual(row['colour_space'], 'acescg')
        self.assertFalse(self.saved[-1][2])
        self.accept(result, 'include')
        np.testing.assert_array_equal(self.saved[-1][0], self.edited)
        np.testing.assert_array_equal(self.original, original)
        self.assertEqual(editor.load_project(self.id), before)

    def test_metadata_snapshot_and_source_import_staleness(self):
        result = review.review_import(self.body)
        manifest = json.loads((editor.project_dir(self.id) / 'import_reviews' / result['token'] / 'manifest.json').read_text())
        self.assertEqual(manifest['source_colour_space'], 'acescg')
        self.assertEqual(manifest['frame'], 1)
        self.assertEqual(manifest['project_revision'], 1)
        self.assertIn('sha256', manifest['imported'])
        self.imported.write_bytes(b'changed')
        with self.assertRaises(ValueError): self.accept(result)
        self.imported.write_bytes(b'edit')
        fresh = review.review_import(self.body)
        self.source.write_bytes(b'changed source')
        with self.assertRaises(ValueError): self.accept(fresh)
        self.assertEqual(len(self.saved), 0)

    def test_persistent_full_resolution_mask_exact_bytes_and_validation(self):
        import io
        from PIL import Image
        result = review.review_import(self.body)
        self.assertIn('/import-review-mask?project=' + self.id, result['difference_url'])
        for kind in ('difference', 'repair', 'expanded'):
            payload = review.import_review_mask(self.id, result['token'], kind)
            self.assertEqual(payload, pathlib.Path(result[kind + '_file']).read_bytes())
            with Image.open(io.BytesIO(payload)) as image:
                self.assertEqual(image.size, (3, 2))
                self.assertLessEqual(set(np.unique(np.asarray(image))), {0, 255})
        for project, token, kind in ((self.id, '../escape', 'repair'), (self.id, result['token'], '../source'), ('../escape', result['token'], 'repair')):
            with self.assertRaises(ValueError): review.import_review_mask(project, token, kind)
        manifest_path = pathlib.Path(result['repair_file']).parent / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['masks']['repair']['path'] = str(self.source)
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError): review.import_review_mask(self.id, result['token'], 'repair')
        manifest['project'] = 'other'
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError): review.import_review_mask(self.id, result['token'], 'difference')

    def test_pending_review_autosave_accepts_current_revision_only(self):
        result = review.review_import(self.body)
        document = editor.load_project(self.id)
        data = dict(document['data'])
        data['pendingReview'] = {'token': result['token'], 'frame': 1}
        saved = editor.save_project(self.id, data, document['revision'])
        with self.assertRaises(editor.RevisionConflict):
            self.accept(result, expected_revision=document['revision'])
        row = self.accept(result, expected_revision=saved['revision'])
        self.assertEqual(row['review_token'], result['token'])
        self.assertEqual(editor.load_project(self.id), saved)

    def test_protection_kept_for_include(self):
        identity = editor.source_identity(str(self.source), self.description)
        protected = np.zeros((2, 3), np.float32)
        protected[1, 2] = 1
        committed = editor.commit_mask_pass(self.id, identity, {1: protected}, 'protect', 1)
        result = review.review_import({**self.body, 'mask_revision': committed['revision']})
        self.accept(result, 'include')
        np.testing.assert_array_equal(self.saved[-1][0][1, 2], self.original[1, 2])
        editor.commit_mask_pass(self.id, identity, {1: self.mask}, 'add', committed['project_revision'])
        with self.assertRaises(editor.RevisionConflict): self.accept(result)

    def test_wrong_frame_cross_shot_path_and_revision_blocked(self):
        result = review.review_import(self.body)
        for updates in ({'frame': 0}, {'frame': True}, {'token': '../escape'}, {'expected_revision': 0}, {'expected_revision': -1}):
            with self.assertRaises(ValueError): self.accept(result, **updates)
        other = self.root / 'other.exr'; other.write_bytes(b'other')
        with self.assertRaises(ValueError): self.accept(result, source=str(other))
        with self.assertRaises(ValueError): review.review_import({**self.body, 'file': str(self.source)})

    def test_finite_dimensions_orientation_and_integer_validation(self):
        for bad in (np.full((2, 3, 3), np.nan), np.zeros((3, 2, 3)), np.full((2, 3, 3), np.inf)):
            self.edited = bad
            with self.assertRaises(ValueError): review.review_import(self.body)
        self.edited = self.original.copy()
        for changes in ({'frame': 1.0}, {'frame': 2}, {'grow': True}, {'source_colour_space': 'invalid'}):
            with self.assertRaises(ValueError): review.review_import({**self.body, **changes})
        with patch.object(review, 'validate_edit_orientation', side_effect=ValueError('orientation')):
            with self.assertRaises(ValueError): review.review_import(self.body)
        self.assertIsNone(editor.load_project(self.id)['mask_revision'])

    def test_hdr_container_preserves_encoded_values_and_metadata(self):
        from unittest.mock import MagicMock
        writer = MagicMock()
        writer.open.return_value = True
        writer.write_image.return_value = True
        spec = MagicMock()
        oiio = types.SimpleNamespace(FLOAT='float', ImageSpec=lambda *args: spec,
                                     ImageOutput=types.SimpleNamespace(create=lambda path: writer),
                                     TypeDesc=lambda value: value)
        with patch.dict('sys.modules', {'OpenImageIO': oiio}):
            review._save_master(self.root / 'hdr.exr', self.original, 'hlg_rec2020')
        np.testing.assert_array_equal(writer.write_image.call_args.args[0], self.original)
        self.assertIn(unittest.mock.call('zura:colour_space', 'hlg_rec2020'), spec.attribute.call_args_list)
        self.assertIn(unittest.mock.call('oiio:ColorSpace', 'Rec.2100 HLG'), spec.attribute.call_args_list)
        writer.close.assert_called_once()

    def test_changed_review_mask_and_failed_save_do_not_accept(self):
        result = review.review_import(self.body)
        mask_path = pathlib.Path(result['repair_file'])
        original_bytes = mask_path.read_bytes()
        mask_path.write_bytes(review._png(np.ones((2, 3), bool)))
        with self.assertRaises(ValueError): self.accept(result)
        mask_path.write_bytes(original_bytes)
        # Regenerate so the immutable asset stat matches the new snapshot.
        result = review.review_import(self.body)
        before = set(self.imported.parent.iterdir())
        def fail(path, pixels, space, half):
            pathlib.Path(path).write_bytes(b'partial')
            raise ValueError('write failed')
        with patch.object(core, 'save_exr', side_effect=fail):
            with self.assertRaises(ValueError): self.accept(result)
        self.assertEqual(set(self.imported.parent.iterdir()), before)
        self.assertEqual(editor.load_project(self.id)['revision'], 1)

    def test_conversion_only_when_spaces_differ(self):
        with patch.object(core, 'to_linear', side_effect=lambda x, space: x + 2) as to, patch.object(core, 'from_linear', side_effect=lambda x, space: x - 1) as convert:
            result = review.review_import({**self.body, 'colour_space': 'linear_rec709'})
            self.accept(result)
            self.assertEqual(to.call_count, 2)
            self.assertEqual(convert.call_count, 2)
            np.testing.assert_array_equal(self.saved[-1][0][self.mask], self.edited[self.mask] + 1)
        with patch.object(core, 'to_linear', side_effect=AssertionError('unexpected conversion')):
            review.review_import(self.body)

if __name__ == '__main__': unittest.main()
