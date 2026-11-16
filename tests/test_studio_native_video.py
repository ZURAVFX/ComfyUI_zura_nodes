"""Native AE movie source admission uses the real codec and frame clock."""
import importlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import v2_bootstrap  # noqa: F401

studio = importlib.import_module('ComfyUI_zura_nodes.comfylink.studio_sessions')


class NativeMovieTests(unittest.TestCase):
    def test_real_prores4444_preserves_exact_frame_count(self):
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            self.skipTest('FFmpeg is unavailable')
        with tempfile.TemporaryDirectory() as directory:
            movie = Path(directory) / 'source.mov'
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc=size=64x48:rate=25', '-frames:v', '2',
                            '-c:v', 'prores_ks', '-profile:v', '4', '-pix_fmt',
                            'yuv444p10le', str(movie)], check=True)
            descriptor = {'width': 64, 'height': 48, 'frameCount': 2,
                          'frameRate': {'numerator': 25, 'denominator': 1}}
            studio.StudioSessions.validate_native_video(movie, descriptor)
            descriptor['frameCount'] = 3
            with self.assertRaisesRegex(ValueError, 'missing frames'):
                studio.StudioSessions.validate_native_video(movie, descriptor)


if __name__ == '__main__':
    unittest.main()
