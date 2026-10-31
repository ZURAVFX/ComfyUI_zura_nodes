"""Delivery contracts through the real FFmpeg audio mux, without inference."""
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest

import numpy as np
from scipy.signal import correlate, correlation_lags


package = types.ModuleType('zura_media_test')
package.__path__ = [str(Path(__file__).resolve().parents[2] / 'paintout')]
sys.modules.setdefault('zura_media_test', package)
media = importlib.import_module('zura_media_test.media')


def ffmpeg(*args):
    return subprocess.run(['ffmpeg', '-v', 'error', '-y', *map(str, args)],
                          check=True, capture_output=True).stdout


def probe(path, *options):
    result = subprocess.run(['ffprobe', '-v', 'error', *options, '-of', 'json', str(path)],
                            check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


class AudioDeliveryTests(unittest.TestCase):
    def test_fractional_nonzero_trim_aligns_audio_without_changing_video_packets(self):
        # 48 kHz / (24000/1001 fps) is exactly 2002 samples per source frame.
        rate, samples_per_frame, start, count = 48000, 2002, 7, 9
        time = np.arange(24 * samples_per_frame) / rate
        noise = np.random.default_rng(20).standard_normal(time.size)
        audio = (.18 * np.sin(2 * np.pi * (700 * time + 1100 * time * time))
                 + .05 * noise).astype('<f4')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sound, source, target = root / 'sound.f32', root / 'source.mov', root / 'target.mp4'
            sound.write_bytes(audio.tobytes())
            video_input = ['-f', 'lavfi', '-i', 'testsrc=size=125x73:rate=24000/1001']
            ffmpeg(*video_input, '-f', 'f32le', '-ar', rate, '-ac', 1, '-i', sound,
                   '-frames:v', 24, '-c:v', 'libx264', '-pix_fmt', 'yuv444p',
                   '-c:a', 'pcm_s16le', source)
            ffmpeg(*video_input, '-frames:v', count, '-c:v', 'libx264',
                   '-pix_fmt', 'yuv444p', target)
            packet_options = ('-select_streams', 'v:0', '-show_packets', '-show_data_hash',
                              'sha256', '-show_entries', 'packet=data_hash')
            before = probe(target, *packet_options)['packets']
            self.assertTrue(media.copy_source_audio(target, {
                'source': {'kind': 'video', 'path': str(source)},
                'start': start, 'count': count, 'fps': 24000 / 1001,
            }))
            self.assertEqual(before, probe(target, *packet_options)['packets'])
            video = probe(target, '-select_streams', 'v:0', '-count_frames',
                          '-show_entries', 'stream=width,height,avg_frame_rate,nb_read_frames')['streams'][0]
            self.assertEqual((video['width'], video['height'], video['avg_frame_rate'],
                              int(video['nb_read_frames'])), (125, 73, '24000/1001', count))
            decoded = np.frombuffer(ffmpeg('-i', target, '-map', '0:a:0', '-f', 'f32le',
                                          '-ar', rate, '-ac', 1, 'pipe:1'), dtype='<f4')
            expected = audio[start * samples_per_frame:(start + count) * samples_per_frame]
            self.assertGreaterEqual(len(decoded), len(expected))
            # AAC may add trailing codec padding. Check the selected audible range,
            # its alignment and similarity rather than claiming lossless audio.
            decoded = decoded[:len(expected)]
            correlation = correlate(decoded, expected, method='fft')
            lag = correlation_lags(len(decoded), len(expected))[int(np.argmax(correlation))]
            self.assertLessEqual(abs(int(lag)), 2)
            self.assertGreater(float(np.corrcoef(decoded, expected)[0, 1]), .8)


if __name__ == '__main__':
    unittest.main()
