"""Real FFmpeg media verifies outpaint preserves cadence through source selection."""
import hashlib
import importlib
from fractions import Fraction
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import av
import test_artist_studio  # sets up the standalone package fixture

module = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_studio')
chunks = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_chunks')
parent = sys.modules['ComfyUI_zura_nodes.artist_studio']


class NativeRateSelectionTests(unittest.TestCase):
    def test_native_video_selection_preserves_exact_frame_count_and_rate(self):
        for numerator, denominator in ((30, 1), (30000, 1001)):
            with self.subTest(rate=(numerator, denominator)), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                source = directory / 'source.mp4'
                rate = f'{numerator}/{denominator}'
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'testsrc2=s=128x128:r={rate}',
                    '-f', 'lavfi', '-i', 'sine=frequency=500:sample_rate=48000', '-frames:v', '20',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], check=True, capture_output=True)
                def run_ffmpeg(*args):
                    subprocess.run(['ffmpeg', '-v', 'error', '-y', *map(str, args)], check=True, capture_output=True)
                fake = types.ModuleType('comfy_api.latest')
                fake.InputImpl = types.SimpleNamespace(VideoFromFile=lambda filename: filename)
                dependencies = {'source_path': lambda video: source, 'root': lambda: directory,
                    'ffmpeg': run_ffmpeg, 'digest_file': lambda path: hashlib.sha256(path.read_bytes()).hexdigest()}
                with patch.dict(parent.__dict__, dependencies), patch.dict(sys.modules, {'comfy_api.latest': fake}):
                    result = module.ZuraOutpaintSelectClip().select(object(), 0, 17 * denominator/numerator,
                        1920, numerator, denominator, 17)[0]
                with av.open(result) as video:
                    stream = video.streams.video[0]
                    self.assertEqual(stream.average_rate, Fraction(numerator, denominator))
                    self.assertEqual(sum(1 for _ in video.decode(video=0)), 17)
                    self.assertTrue(video.streams.audio)

    def test_join_retains_fractional_rate_and_exact_section_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            sources = []
            for index in range(2):
                clip = directory / f'{index}.mp4'
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=s=128x128:r=30000/1001', '-frames:v', '17', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', str(clip)], check=True, capture_output=True)
                sources.append(clip)
            parts = [chunks.Window(0, 17, 0), chunks.Window(8, 17, 9)]
            output = directory / 'joined.mp4'
            command = chunks.ffmpeg_assembly('ffmpeg', parts, sources, output, fps=Fraction(30000, 1001))
            subprocess.run(command, check=True, capture_output=True)
            with av.open(str(output)) as video:
                self.assertEqual(video.streams.video[0].average_rate, Fraction(30000, 1001))
                self.assertEqual(sum(1 for _ in video.decode(video=0)), 25)


if __name__ == '__main__':
    unittest.main()
