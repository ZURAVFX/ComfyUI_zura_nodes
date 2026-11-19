import importlib
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
from test_paintout_editor_store import package

browser = types.ModuleType(package.__name__ + '.browser')
browser.checked_path = lambda value: pathlib.Path(value).resolve(strict=True)
browser.grant = lambda value: '/fixture/' + pathlib.Path(value).name
with patch.dict(sys.modules, {package.__name__ + '.browser': browser}):
    routes = importlib.import_module(package.__name__ + '.editor_routes')


class EditedFrameImportFormats(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        self.source = self.root / 'source.mov'
        self.source.write_bytes(b'fixture source identity')
        description = dict(width=16, height=10, count=17)
        for name, value in {
            'load_project': lambda _: dict(data=dict(draft=dict(source=str(self.source)))),
            'project_dir': lambda _: self.project,
            'describe': lambda _: description,
            'checked_path': browser.checked_path,
            'grant': browser.grant,
        }.items():
            context = patch.object(routes, name, value)
            context.start()
            self.addCleanup(context.stop)

    def request(self, file, frame=7):
        return routes.import_local_image(dict(project='owned', source=str(self.source), frame=frame, file=str(file), colour_space='srgb_display'))

    def test_png_jpg_and_jpeg_use_real_reader_and_owned_original_raster(self):
        for suffix in ('.png', '.jpg', '.jpeg'):
            with self.subTest(suffix=suffix):
                original = self.root / ('external' + suffix)
                Image.fromarray(np.full((10, 16, 3), (80, 120, 170), np.uint8)).save(original)
                before = original.read_bytes()
                result = self.request(original)
                self.assertEqual((result['width'], result['height'], result['frame']), (16, 10, 7))
                self.assertEqual(result['colour_space'], 'srgb_display')
                owned = pathlib.Path(result['file'])
                self.assertEqual(owned.parent, self.project / 'imports')
                self.assertEqual(owned.read_bytes(), before)
                original.write_bytes(b'changed externally')
                self.assertEqual(owned.read_bytes(), before, 'External changes cannot replace an accepted import')

    def test_wrong_original_dimensions_or_frame_are_rejected_without_a_partial_import(self):
        wrong = self.root / 'wrong.jpg'
        Image.fromarray(np.zeros((10, 17, 3), np.uint8)).save(wrong)
        with self.assertRaisesRegex(ValueError, 'dimensions must match'):
            self.request(wrong)
        self.assertEqual(list((self.project / 'imports').iterdir()), [])
        with self.assertRaisesRegex(ValueError, 'inside the original source'):
            self.request(wrong, 17)

    def test_rotated_jpeg_is_rejected_instead_of_silently_moving_pixels(self):
        rotated = self.root / 'rotated.jpeg'
        image = Image.fromarray(np.zeros((10, 16, 3), np.uint8))
        exif = Image.Exif()
        exif[274] = 6
        image.save(rotated, exif=exif)
        with self.assertRaisesRegex(ValueError, 'orientation|Orientation|rotat'):
            self.request(rotated)
        self.assertEqual(list((self.project / 'imports').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
