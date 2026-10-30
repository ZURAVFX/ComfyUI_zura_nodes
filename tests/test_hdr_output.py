import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('hdr_output_test', Path(__file__).resolve().parents[1] / 'artist_studio' / 'hdr_output.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HDROutputTests(unittest.TestCase):
    def test_only_existing_output_video_inside_output_root_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'output'
            folder = root / 'zura' / 'takes'
            folder.mkdir(parents=True)
            video = folder / 'result.mp4'
            video.write_bytes(b'video')
            ref = {'type': 'output', 'subfolder': 'zura/takes', 'filename': 'result.mp4'}
            self.assertEqual(module.selected_output(root, ref), video.resolve())
            for bad in ({**ref, 'type': 'input'}, {**ref, 'filename': '../result.mp4'},
                        {**ref, 'subfolder': '../../outside'}, {**ref, 'filename': 'missing.mp4'},
                        {**ref, 'filename': 'result.png'}, None):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    module.selected_output(root, bad)
