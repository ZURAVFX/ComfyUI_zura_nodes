import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import av

spec = importlib.util.spec_from_file_location("preview_proxy", Path(__file__).parents[1] / "artist_studio" / "preview_proxy.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class ProResPlayback(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is not on PATH")
    def test_prores_and_pcm_generate_seekable_proxy_without_changing_original(self):
        with tempfile.TemporaryDirectory() as folder:
            shot = Path(folder) / "genj_studio" / "a"
            shot.mkdir(parents=True)
            source, target = shot / "source.mov", shot / "preview.mp4"
            exe = shutil.which("ffmpeg")
            subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=192x108:rate=24:duration=1", "-f", "lavfi", "-i", "sine=duration=1", "-c:v", "prores_ks", "-profile:v", "2", "-c:a", "pcm_s16le", "-shortest", str(source)], check=True)
            original = source.read_bytes()
            old_asset = {"asset_kind": "video", "file": "genj_studio/a/source.mov"}
            preview.describe_existing(old_asset, folder)
            self.assertEqual(old_asset["preview_file"], "genj_studio/a/preview.mp4")
            def ffmpeg(*args):
                subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], check=True)
            preview.build_proxy(source, target, ffmpeg)
            self.assertEqual(source.read_bytes(), original)
            with av.open(str(target)) as result:
                self.assertEqual(result.streams.video[0].codec_context.name, "h264")
                self.assertEqual((result.streams.video[0].width, result.streams.video[0].height), (192, 108))
                self.assertEqual(result.streams.audio[0].codec_context.name, "aac")
                self.assertEqual(len(list(result.decode(video=0))), 24)
            self.assertFalse(target.with_name("preview.partial.mp4").exists())

    def test_editing_codecs_need_a_separate_browser_proxy(self):
        self.assertTrue(preview.needs_proxy("prores"))
        self.assertTrue(preview.needs_proxy("ffv1"))
        self.assertFalse(preview.needs_proxy("h264"))

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is not on PATH")
    def test_ffv1_keeps_lossless_master_and_17_frame_clock_separate_from_browser_copy(self):
        import numpy as np
        from fractions import Fraction
        with tempfile.TemporaryDirectory() as folder:
            shot = Path(folder) / 'genj_studio' / 'numeric'; shot.mkdir(parents=True)
            source, target = shot / 'reference.mkv', shot / 'preview.mp4'
            rate = Fraction(30000, 1001)
            with av.open(str(source), 'w') as container:
                stream = container.add_stream('ffv1', rate=rate)
                stream.width, stream.height, stream.pix_fmt = 64, 48, 'bgra'
                stream.codec_context.colorspace = 0
                stream.codec_context.color_range = 2
                for index in range(17):
                    rgba = np.full((48, 64, 4), (50 + index, 100, 150 - index, 255), dtype=np.uint8)
                    frame = av.VideoFrame.from_ndarray(rgba, format='rgba')
                    frame.pts, frame.time_base = index, 1 / rate
                    for packet in stream.encode(frame): container.mux(packet)
                for packet in stream.encode(): container.mux(packet)
            original = source.read_bytes()
            asset = {'asset_kind': 'video', 'file': 'genj_studio/numeric/reference.mkv'}
            preview.describe_existing(asset, folder)
            self.assertEqual(asset['preview_file'], 'genj_studio/numeric/preview.mp4')
            exe = shutil.which('ffmpeg')
            def ffmpeg(*args):
                subprocess.run([exe, '-hide_banner', '-loglevel', 'error', '-y', *map(str, args)], check=True)
            preview.build_proxy(source, target, ffmpeg)
            self.assertEqual(source.read_bytes(), original)
            with av.open(str(target)) as media:
                self.assertEqual(media.streams.video[0].codec_context.name, 'h264')
                self.assertEqual(media.streams.video[0].pix_fmt, 'yuv420p')
                self.assertNotEqual(media.streams.video[0].codec_context.colorspace, 0,
                                    'A YUV browser proxy cannot retain an RGB packing label')
                self.assertEqual(media.streams.video[0].average_rate, rate)
                self.assertEqual(len(list(media.decode(video=0))), 17)
            with av.open(str(source)) as media:
                self.assertEqual(media.streams.video[0].codec_context.name, 'ffv1')


if __name__ == "__main__":
    unittest.main()
