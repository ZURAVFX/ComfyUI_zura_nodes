"""Manual frame saves preserve other frames and bypass model inference entirely."""
import base64
import importlib
import io
import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
package = types.ModuleType('paintout_routes_test')
package.__path__ = []
sys.modules[package.__name__] = package
processing = types.ModuleType(package.__name__ + '.paintout')
processing.__path__ = [str(ROOT / 'paintout')]
sys.modules[processing.__name__] = processing
origin = types.ModuleType(package.__name__ + '.media_source')
origin.require_same_origin = lambda request: None
sys.modules[origin.__name__] = origin
browser = types.ModuleType(processing.__name__ + '.browser')
browser.checked_path = lambda value: pathlib.Path(value).resolve(strict=True)
browser.grant = lambda value: str(value)
sys.modules[browser.__name__] = browser
editor = importlib.import_module(processing.__name__ + '.editor_store')
routes = importlib.import_module(processing.__name__ + '.editor_routes')


def png(mask):
    stream = io.BytesIO()
    Image.fromarray(np.asarray(mask, dtype=np.uint8)).save(stream, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()


class PaintedFrameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.source = self.root / 'source.mp4'
        self.source.write_bytes(b'fixture')
        self.description = dict(width=5, height=4, count=6)
        self.patches = [patch.object(editor, 'project_root', return_value=self.root / 'projects'),
                        patch.object(routes, 'describe', return_value=self.description)]
        for item in self.patches:
            item.start()
        self.document = editor.save_project(data={'draft': {'source': str(self.source)}})
        self.project = self.document['id']
        self.identity = editor.source_identity(str(self.source), self.description)
        first = editor.commit_mask_pass(self.project, self.identity, {0: np.ones((4, 5)), 3: np.ones((4, 5))}, 'replace', 1)
        protect = np.zeros((4, 5));protect[:, 2] = 1
        editor.commit_mask_pass(self.project, self.identity, {0: protect, 3: protect}, 'protect', first['project_revision'])
        self.document = editor.load_project(self.project)
        self.body = dict(project=self.project, source=str(self.source), frame=3, colour_space='srgb_display',
                         expected_revision=self.document['revision'], expected_mask_revision=self.document['mask_revision'],
                         mask=png(np.full((4, 5), 255)))

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_save_changes_only_requested_frame_and_preserves_protection(self):
        before = editor.mask_descriptor(self.project)
        result = routes.save_painted_frame(self.body)
        after = editor.mask_descriptor(self.project)
        self.assertEqual(result['mask_coverage'], [0, 3])
        self.assertEqual(result['revision'], self.document['revision'] + 1)
        self.assertEqual(before['files'][0], after['files'][0])
        for frame in (0, 3):
            self.assertFalse(editor.read_project_mask(self.project, frame, grow=3)[:, 2].any())
            np.testing.assert_array_equal(editor._load_mask(before['protection_files'][frame], 5, 4),
                                          editor._load_mask(after['protection_files'][frame], 5, 4))
        self.assertEqual(result['mask_history'][-1]['start_frame'], 3)
        self.assertEqual(result['mask_history'][-1]['end_frame'], 3)
        self.assertTrue(result['mask_history'][-1]['metadata']['manual_correction'])

    def test_fully_erased_frame_is_saved_as_explicit_zero_coverage(self):
        result = routes.save_painted_frame({**self.body, 'frame': 2, 'mask': png(np.zeros((4, 5)))})
        self.assertIn(2, result['mask_coverage'])
        self.assertFalse(editor.read_project_mask(self.project, 2).any())

    def test_soft_values_are_thresholded_to_hard_binary_mask(self):
        pixels = np.array([[0, 64, 127, 128, 255]] * 4, np.uint8)
        routes.save_painted_frame({**self.body, 'frame': 2, 'mask': png(pixels)})
        np.testing.assert_array_equal(editor.read_project_mask(self.project, 2), pixels >= 128)

    def test_stale_project_or_mask_revision_cannot_overwrite(self):
        for change in ({'expected_revision': 1}, {'expected_mask_revision': -1}, {'expected_revision': None}):
            with self.assertRaises(editor.RevisionConflict):
                routes.save_painted_frame({**self.body, **change})
        self.assertEqual(editor.load_project(self.project), self.document)

    def test_modified_source_and_wrong_dimensions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'matching the original'):
            routes.save_painted_frame({**self.body, 'mask': png(np.zeros((3, 5)))})
        self.source.write_bytes(b'modified fixture')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            routes.save_painted_frame(self.body)
        self.assertEqual(editor.load_project(self.project), self.document)

    def test_unrelated_shot_and_out_of_range_frame_are_rejected(self):
        other = self.root / 'other.mp4';other.write_bytes(b'fixture')
        for change in ({'source': str(other)}, {'frame': -1}, {'frame': 6}):
            with self.assertRaises(ValueError):
                routes.save_painted_frame({**self.body, **change})


class ImportedMaskVideoTests(unittest.TestCase):
    tearDown = PaintedFrameTests.tearDown

    def setUp(self):
        PaintedFrameTests.setUp(self)
        self.mask_source = self.root / 'mask.mp4'
        self.mask_source.write_bytes(b'mask fixture')
        self.plate = dict(self.description, kind='video', path=str(self.source), fps=23.976023976,
                          fps_rational='24000/1001')
        self.mask_info = dict(self.plate, path=str(self.mask_source))
        routes.describe.side_effect = lambda path: dict(self.mask_info if pathlib.Path(path) == self.mask_source else self.plate)
        self.import_body = dict(project=self.project, source=str(self.source), mask=str(self.mask_source),
                                expected_revision=self.document['revision'])

    def spool(self, description, directory):
        result = {}
        for frame in range(description['count']):
            path = pathlib.Path(directory) / f'{frame}.png'
            Image.fromarray(np.full((4, 5), 255 if frame % 2 else 0, np.uint8)).save(path)
            result[frame] = str(path)
        return result

    def test_full_mask_import_has_exact_coverage_and_preserves_protection(self):
        with patch.object(routes, '_spool_mask_video', side_effect=self.spool):
            result = routes.import_mask_video(self.import_body)
        self.assertEqual(result['mask_coverage'], list(range(6)))
        self.assertEqual(result['mask_history'][-1]['start_frame'], 0)
        self.assertEqual(result['mask_history'][-1]['end_frame'], 5)
        self.assertEqual(result['mask_history'][-1]['metadata']['method'], 'import')
        for frame in (0, 3):
            self.assertFalse(editor.read_project_mask(self.project, frame, grow=3)[:, 2].any())
        self.assertFalse(editor.read_project_mask(self.project, 2).any())
        self.assertTrue(editor.read_project_mask(self.project, 5).all())
        self.assertFalse(list(editor.project_dir(self.project).glob('pending_import_*')))

    def test_mismatched_dimensions_frame_count_and_rational_rate_are_rejected(self):
        for change, message in (({'width': 6}, 'dimensions'), ({'count': 7}, 'number of frames'),
                                ({'fps_rational': '24'}, 'frame rate'), ({'kind': 'sequence'}, 'mask video')):
            with self.subTest(change=change):
                previous = self.mask_info
                self.mask_info = dict(previous, **change)
                with self.assertRaisesRegex(ValueError, message):
                    routes.import_mask_video(self.import_body)
                self.mask_info = previous
        self.assertEqual(editor.load_project(self.project), self.document)

    def test_decode_failure_and_source_changes_leave_existing_revision_intact(self):
        def change_source(description, directory):
            result = self.spool(description, directory)
            self.mask_source.write_bytes(b'changed mask')
            return result
        for side_effect in (ValueError('broken video'), change_source):
            with patch.object(routes, '_spool_mask_video', side_effect=side_effect):
                with self.assertRaises(ValueError):
                    routes.import_mask_video(self.import_body)
            self.assertEqual(editor.load_project(self.project), self.document)
            self.assertFalse(list(editor.project_dir(self.project).glob('pending_import_*')))

    def test_stale_import_and_foreign_project_are_rejected_before_decode(self):
        with self.assertRaises(editor.RevisionConflict):
            routes.import_mask_video(dict(self.import_body, expected_revision=1))
        other = self.root / 'other.mp4';other.write_bytes(b'fixture')
        with self.assertRaisesRegex(ValueError, 'original shot'):
            routes.import_mask_video(dict(self.import_body, source=str(other)))

    def test_real_ffmpeg_import_matches_fractional_clock_and_binary_pixels(self):
        import subprocess
        core = importlib.import_module(processing.__name__ + '.paintout')
        for path, colour in ((self.source, 'blue'), (self.mask_source, 'white')):
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            f'color=c={colour}:size=20x12:rate=24000/1001', '-frames:v', '6',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True, capture_output=True)
        # New source pixels require a new shot project, as they should.
        document = editor.save_project(data={'draft': {'source': str(self.source)}})
        with patch.object(routes, 'describe', side_effect=core.describe):
            result = routes.import_mask_video(dict(self.import_body, project=document['id'], expected_revision=document['revision']))
        self.assertEqual(result['mask_coverage'], list(range(6)))
        self.assertEqual(editor.read_project_mask(document['id'], 4).shape, (12, 20))
        self.assertTrue(editor.read_project_mask(document['id'], 4).all())

    def test_spool_rejects_actual_short_or_extra_frames(self):
        import subprocess
        for frames, declared, message in ((2, 3, 'ended'), (4, 3, 'more frames')):
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=white:size=20x12:rate=24',
                            '-frames:v', str(frames), '-c:v', 'libx264', str(self.mask_source)], check=True, capture_output=True)
            with tempfile.TemporaryDirectory() as target:
                with self.assertRaisesRegex(ValueError, message):
                    routes._spool_mask_video(dict(path=str(self.mask_source), width=20, height=12, count=declared), target)


class LocalEditedFrameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.source = self.root / 'plate.mp4';self.source.write_bytes(b'fixture')
        self.original = self.root / 'external-edit.png'
        Image.new('RGB', (5, 4), color=(12, 34, 56)).save(self.original)
        self.root_patch = patch.object(editor, 'project_root', return_value=self.root / 'projects')
        self.describe_patch = patch.object(routes, 'describe', return_value=dict(width=5, height=4, count=6))
        self.root_patch.start();self.describe_patch.start()
        document = editor.save_project(data={'draft': {'source': str(self.source)}})
        self.project = document['id']
        self.body = dict(project=self.project, source=str(self.source), frame=3,
                         file=str(self.original), colour_space='srgb_display')

    def tearDown(self):
        self.describe_patch.stop();self.root_patch.stop();self.temp.cleanup()

    def imported_files(self):
        return list((editor.project_dir(self.project) / 'imports').glob('*'))

    def test_import_is_owned_immutable_copy_and_external_file_is_untouched(self):
        original = self.original.read_bytes()
        result = routes.import_local_image(self.body)
        target = pathlib.Path(result['file'])
        self.assertNotEqual(target, self.original)
        self.assertEqual(target.parent, editor.project_dir(self.project) / 'imports')
        self.assertEqual(result['frame'], 3)
        self.assertEqual((result['width'], result['height']), (5, 4))
        self.assertEqual(self.original.read_bytes(), original)
        self.assertEqual(target.read_bytes(), original)
        Image.new('RGB', (5, 4), color='red').save(self.original)
        self.assertEqual(target.read_bytes(), original)
        second = routes.import_local_image(self.body)
        self.assertNotEqual(second['file'], result['file'])
        self.assertEqual(target.read_bytes(), original)

    def test_invalid_dimensions_or_orientation_leave_no_imported_files(self):
        Image.new('RGB', (6, 4)).save(self.original)
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            routes.import_local_image(self.body)
        self.assertEqual(self.imported_files(), [])
        oriented = self.root / 'rotated.tif'
        Image.new('RGB', (5, 4)).save(oriented, tiffinfo={274: 6})
        with self.assertRaisesRegex(ValueError, 'normal orientation'):
            routes.import_local_image(dict(self.body, file=str(oriented)))
        self.assertEqual(self.imported_files(), [])
        self.assertTrue(oriented.exists())

    def test_nonfinite_pixels_and_invalid_colour_leave_no_imported_files(self):
        with patch.object(routes, 'read_image', return_value=np.full((4, 5, 3), np.nan)):
            with self.assertRaisesRegex(ValueError, 'invalid pixel'):
                routes.import_local_image(self.body)
        with self.assertRaisesRegex(ValueError, 'colour space'):
            routes.import_local_image(dict(self.body, colour_space='bad'))
        self.assertEqual(self.imported_files(), [])

    def test_wrong_shot_frame_extension_or_size_are_rejected_without_mutation(self):
        other = self.root / 'other.mp4';other.write_bytes(b'other')
        wrong = self.root / 'edited.jpg';Image.new('RGB', (5, 4)).save(wrong)
        for change in ({'source': str(other)}, {'frame': -1}, {'frame': 6}, {'file': str(wrong)}):
            with self.assertRaises(ValueError):
                routes.import_local_image(dict(self.body, **change))
        original = self.original.read_bytes()
        stat = self.original.stat()
        real_stat = pathlib.Path.stat
        with patch.object(pathlib.Path, 'stat', autospec=True, side_effect=lambda path, **kwargs: types.SimpleNamespace(st_size=101*1024*1024, st_mode=stat.st_mode) if path == self.original else real_stat(path, **kwargs)):
            with self.assertRaisesRegex(ValueError, '100 MB'):
                routes.import_local_image(self.body)
        self.assertEqual(self.original.read_bytes(), original)
        self.assertEqual(self.imported_files(), [])


class PaintedFrameRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_conflicts_are_http_409_and_bad_input_http_400(self):
        request = types.SimpleNamespace()
        async def body():
            return {}
        request.json = body
        bad = await routes.paint_mask(request)
        self.assertEqual(bad.status, 400)
        with patch.object(routes, 'save_painted_frame', side_effect=editor.RevisionConflict('reload')):
            conflict = await routes.paint_mask(request)
        self.assertEqual(conflict.status, 409)
        self.assertEqual(json.loads(conflict.text)['error'], 'reload')

    async def test_import_route_uses_same_origin_and_conflict_status(self):
        async def body():
            return {}
        request = types.SimpleNamespace(json=body)
        self.assertEqual((await routes.import_mask(request)).status, 400)
        with patch.object(routes, 'import_mask_video', side_effect=editor.RevisionConflict('reload')):
            self.assertEqual((await routes.import_mask(request)).status, 409)
        with patch.object(origin, 'require_same_origin', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                await routes.import_mask(request)

    async def test_local_import_route_has_guard_and_bad_input_status(self):
        async def body():
            return {}
        request = types.SimpleNamespace(json=body)
        self.assertEqual((await routes.import_local_frame(request)).status, 400)
        with patch.object(origin, 'require_same_origin', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                await routes.import_local_frame(request)

    async def test_same_origin_guard_runs_before_saving(self):
        with patch.object(origin, 'require_same_origin', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                await routes.paint_mask(types.SimpleNamespace())


if __name__ == '__main__':
    unittest.main()
