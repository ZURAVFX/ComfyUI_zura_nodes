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

    def test_only_prores_needs_this_proxy(self):
        self.assertTrue(preview.needs_proxy("prores"))
        self.assertFalse(preview.needs_proxy("h264"))


if __name__ == "__main__":
    unittest.main()
