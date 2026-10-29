"""CPU media checks for the unexposed long-outpaint assembly primitives."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('zura_outpaint_chunks', Path(__file__).parents[1] / 'artist_studio' / 'outpaint_chunks.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class WindowPlanning(unittest.TestCase):
    def test_windows_cover_exact_range_and_obey_limit(self):
        for length in (3, 120, 121, 240, 1000):
            parts = module.windows(24, length)
            self.assertEqual(parts[0].start, 24)
            self.assertEqual(parts[-1].start + parts[-1].count, 24 + length)
            self.assertTrue(all(3 <= p.count <= 120 for p in parts))
            for previous, following in zip(parts, parts[1:]):
                self.assertEqual(previous.start + previous.count - following.overlap, following.start)

    def test_invalid_windows_cannot_make_a_command(self):
        with self.assertRaises(ValueError):
            module.windows(0, 1)
        with self.assertRaises(ValueError):
            module.ffmpeg_assembly('ffmpeg', [module.Window(0, 10, 0), module.Window(20, 10, 2)], ['a', 'b'], 'c')

    def test_high_resolution_windows_fit_padded_pixel_frame_budget(self):
        parts = module.windows(0, 150, width=1152, height=640)
        self.assertGreater(len(parts), 2)
        self.assertEqual(parts[0].count, 49)
        self.assertEqual(sum(p.count-p.overlap for p in parts), 150)
        for part in parts:
            padded = max(9, 1 + 8 * ((part.count + 6) // 8))
            self.assertLessEqual(1152 * 640 * padded, module.MAX_PIXEL_FRAMES)
        with self.assertRaisesRegex(ValueError, 'processing windows'):
            module.windows(0, 1_000_000, width=1152, height=640)

    def test_real_overlap_assembly_and_one_original_audio_track(self):
        ffmpeg = os.environ.get('FFMPEG') or shutil.which('ffmpeg') or 'D:/ComfyUI/python_embeded/ffmpeg-bin/ffmpeg.exe'
        ffprobe = shutil.which('ffprobe')
        if not Path(ffmpeg).is_file() or not ffprobe:
            self.skipTest('FFmpeg and FFprobe are required for the media test.')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            parts = module.windows(0, 150)
            clips = []
            for index, part in enumerate(parts):
                path = root / f'part-{index}.mp4'
                colour = 'red' if index == 0 else 'blue'
                subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', f'color=c={colour}:s=128x128:r=24',
                                '-frames:v', str(part.count), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True)
                clips.append(path)
            source = root / 'audio.wav'
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=1000:duration=7', str(source)], check=True)
            output = root / 'result.mp4'
            subprocess.run(module.ffmpeg_assembly(ffmpeg, parts, clips, output, source=source), check=True)
            metadata = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-count_frames', '-show_entries',
                'stream=codec_type,nb_read_frames,duration', '-of', 'json', str(output)], text=True))
            streams = metadata['streams']
            self.assertEqual(int(next(s for s in streams if s['codec_type'] == 'video')['nb_read_frames']), 150)
            self.assertEqual(len([s for s in streams if s['codec_type'] == 'audio']), 1)
            self.assertAlmostEqual(float(next(s for s in streams if s['codec_type'] == 'audio')['duration']), 150 / 24, delta=.05)
            seam = subprocess.check_output([ffmpeg, '-v', 'error', '-i', str(output), '-vf',
                r'select=eq(n\,114),scale=1:1', '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
            self.assertEqual(len(seam), 3)
            self.assertGreater(seam[0], 60, 'Overlap should retain part of the earlier frame.')
            self.assertGreater(seam[2], 60, 'Overlap should include part of the later frame.')

    def test_real_four_window_single_frame_anchor_does_not_drop_frames(self):
        ffmpeg = os.environ.get('FFMPEG') or shutil.which('ffmpeg') or 'D:/ComfyUI/python_embeded/ffmpeg-bin/ffmpeg.exe'
        ffprobe = shutil.which('ffprobe')
        if not Path(ffmpeg).is_file() or not ffprobe:
            self.skipTest('FFmpeg and FFprobe are required for the media test.')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            parts = module.windows(0, 150, width=1152, height=640, overlap=1)
            clips = []
            for index, part in enumerate(parts):
                path = root / f'part-{index}.mp4'
                subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                    'color=blue:s=128x128:r=24', '-frames:v', str(part.count), str(path)], check=True)
                clips.append(path)
            output = root / 'result.mp4'
            subprocess.run(module.ffmpeg_assembly(ffmpeg, parts, clips, output), check=True)
            metadata = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-count_frames',
                '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_frames', '-of', 'json', str(output)], text=True))
            self.assertEqual(int(metadata['streams'][0]['nb_read_frames']), 150)

    def test_real_black_to_white_blend_hits_both_endpoints_without_wrap(self):
        ffmpeg = os.environ.get('FFMPEG') or shutil.which('ffmpeg') or 'D:/ComfyUI/python_embeded/ffmpeg-bin/ffmpeg.exe'
        if not Path(ffmpeg).is_file():
            self.skipTest('FFmpeg is required for this media test.')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            parts = module.windows(0, 150, overlap=12)
            clips = []
            for index, part in enumerate(parts):
                path = root / f'part-{index}.mp4'
                colour = 'black' if index == 0 else 'white'
                subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                    f'color={colour}:s=128x128:r=24', '-frames:v', str(part.count),
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True)
                clips.append(path)
            output = root / 'result.mp4'
            subprocess.run(module.ffmpeg_assembly(ffmpeg, parts, clips, output), check=True)
            pixels = subprocess.check_output([ffmpeg, '-v', 'error', '-i', str(output), '-vf',
                r'select=between(n\,108\,119),scale=1:1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
            self.assertEqual(len(pixels), 12 * 3)
            levels = [sum(pixels[i:i+3]) / 3 for i in range(0, len(pixels), 3)]
            self.assertLess(levels[0], 8, 'The overlap must start at the black endpoint.')
            self.assertGreater(levels[-1], 247, 'The overlap must end at the white endpoint.')
            self.assertTrue(all(a <= b + 2 for a, b in zip(levels, levels[1:])), levels)


if __name__ == '__main__':
    unittest.main()
