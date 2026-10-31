"""CPU regressions for fractional-rate decoding and source-size processing."""
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('paintout_decode_test')
package.__path__ = [str(ROOT/'paintout')]
sys.modules.setdefault(package.__name__, package)
native = importlib.import_module(package.__name__+'.paintout')


class PaintoutDecodeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Requires FFmpeg')
    def test_fractional_60fps_preserves_every_frame_and_nonzero_range(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root/'fractional.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=64x64:rate=60000/1001', '-frames:v', '30',
                            '-c:v', 'ffv1', str(video)], check=True, capture_output=True)
            data = native.describe(video)
            with patch.object(native.tempfile, 'gettempdir', return_value=temporary):
                all_frames = list(native.frames(data, 0, 30))
                selected = list(native.frames(data, 3, 12))
                self.assertEqual(len(all_frames), 30)
                self.assertEqual(len(selected), 12)
                np.testing.assert_array_equal(selected, all_frames[3:15])
                # A genuine short decode reports counts and leaves no partial cache.
                with self.assertRaisesRegex(ValueError, 'Decoded 30 of 31'):
                    list(native.frames(data, 0, 31))
                self.assertEqual(list((root/'zura_paintout_rgb').glob('*.part')), [])

    def test_source_resolution_only_pads_without_resampling(self):
        reported = []
        pixels = np.random.default_rng(42).random((66, 70, 3), dtype=np.float32)
        data = dict(kind='sequence', width=70, height=66, count=1, files=['frame.png'])
        mask = dict(kind='rectangle', width=70, height=66, count=1, rect=[0, 0, 70, 66])
        with patch.object(native, 'describe', return_value=data), \
             patch.object(native, 'frames', return_value=iter([pixels])), \
             patch.object(native, 'working', side_effect=lambda image, *args: image), \
             patch.object(native, 'frame_progress', return_value=reported.append), \
             patch.object(native, 'resize', side_effect=AssertionError('Must not resize')), \
             patch.object(native, 'resize_fullframe', side_effect=AssertionError('Must not resize')):
            result = native.ZuraPaintoutCrop().prepare(
                'frame.png', mask, 'srgb_display', 0, 1, 25, 128, 768, 0, 0,
                'SDR (sRGB)', 'Source resolution (pad, no resize)', 128, 128)
        image, _, plate, width, height, *_ = result
        self.assertEqual((width, height), (128, 128))
        self.assertEqual(plate['resized'], [66, 70])
        self.assertEqual(plate['rect'], [0, 0, 70, 66])
        self.assertEqual(reported, [1])
        torch.testing.assert_close(image[0, :66, :70], torch.from_numpy(pixels), rtol=0, atol=0)


if __name__ == '__main__':
    unittest.main()
