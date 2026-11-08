import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image
import torch


MODULE = Path(__file__).resolve().parents[1] / "artist_studio" / "alpha_video.py"
spec = importlib.util.spec_from_file_location("zura_test_alpha_video", MODULE)
alpha = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alpha)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and FFprobe required")
class AlphaVideoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.source = self.directory / "source.mkv"
        self.output = self.directory / "output"
        self.output.mkdir()
        self.folder_paths = types.SimpleNamespace(get_input_directory=lambda: str(self.directory), get_output_directory=lambda: str(self.output))
        self.modules = patch.dict(sys.modules, {"folder_paths": self.folder_paths})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        width, height, count = 117, 75, 12
        pixels = np.empty((count, height, width, 3), dtype=np.uint8)
        for index in range(count):
            pixels[index, :, :, 0] = 50 + index * 5
            pixels[index, :, :, 1] = np.arange(width, dtype=np.uint8)
            pixels[index, :, :, 2] = np.arange(height, dtype=np.uint8)[:, None] + 80
        self.pixels = pixels
        result = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
                                 "-r", "30000/1001", "-i", "pipe:0", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.4004",
                                 "-frames:v", str(count), "-c:v", "ffv1", "-pix_fmt", "bgr0", "-c:a", "pcm_s16le", "-shortest", str(self.source)],
                                input=pixels.tobytes(), capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf8", "replace"))

    def probe(self, path):
        result = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_streams", "-of", "json", str(path)], check=True, capture_output=True, text=True)
        return json.loads(result.stdout)["streams"]

    def test_prepare_holds_end_and_pads_without_stretching(self):
        images, info, width, height, count, fps = alpha.ZuraAlphaVideoInput().prepare(str(self.source), 3, 2, 1)
        self.assertEqual((width, height, count), (128, 96, 9))
        self.assertEqual(info["fps_rational"], "30000/1001")
        self.assertAlmostEqual(fps, 30000 / 1001)
        self.assertTrue(torch.equal(images[1], images[8]))
        self.assertTrue(torch.allclose(images[0, :75, :117], torch.tensor(self.pixels[3]).float() / 255, atol=1 / 255))
        self.assertTrue(torch.equal(images[0, :75, 116], images[0, :75, 127]))
        self.assertTrue(torch.equal(images[0, 74], images[0, 95]))

    def test_scaled_prepare_and_invalid_ranges(self):
        images, info, width, height, count, _ = alpha.ZuraAlphaVideoInput().prepare(str(self.source), 1, 9, .5)
        self.assertEqual((width, height, count), (64, 64, 9))
        self.assertEqual((info["content_width"], info["content_height"]), (58, 38))
        for start, count in [(11, 2), (0, 146), (-1, 2)]:
            with self.assertRaises(ValueError):
                alpha.ZuraAlphaVideoInput().prepare(str(self.source), start, count, 1)
        with self.assertRaisesRegex(ValueError, "Lower the processing"):
            alpha.processing_geometry(3840, 2160, 1)

    def test_source_matched_delivery_has_soft_alpha_correct_polarity_and_clock(self):
        images, info, *_ = alpha.ZuraAlphaVideoInput().prepare(str(self.source), 3, 2, .5)
        matte = torch.zeros_like(images)
        matte[:, :, 20:40] = .5
        matte[:, :, 40:] = 1
        result = alpha.ZuraAlphaVideoOutput().save(matte, info, "ZURA STUDIO/test")
        files = result["ui"]["images"]
        self.assertEqual({f["role"] for f in files}, {"matte", "preview", "alpha", "sequence"})
        paths = {f["role"]: self.output / f["subfolder"] / f["filename"] for f in files}
        streams = self.probe(paths["alpha"])
        video = next(s for s in streams if s["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"], int(video["nb_frames"])), (117, 75, 2))
        self.assertEqual(video["avg_frame_rate"], "30000/1001")
        self.assertTrue(video["pix_fmt"].startswith("yuva444"))
        self.assertTrue(any(s["codec_type"] == "audio" for s in streams))
        raw = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-i", str(paths["alpha"]), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba64le", "pipe:1"], check=True, capture_output=True).stdout
        decoded = np.frombuffer(raw, dtype="<u2").reshape(75, 117, 4)
        self.assertLess(int(decoded[35, 10, 3]), 100)
        self.assertLess(abs(int(decoded[35, 60, 3]) - 32768), 100)
        self.assertGreater(int(decoded[35, 110, 3]), 65400)
        with zipfile.ZipFile(paths["sequence"]) as archive:
            self.assertEqual(len([name for name in archive.namelist() if name.endswith(".png")]), 2)
            timing = json.loads(archive.read("timing.json"))
            self.assertEqual(timing["fps"], "30000/1001")
            png = Image.open(io.BytesIO(archive.read("000000.png")))
            self.assertEqual(png.size, (117, 75))
            self.assertEqual(int(np.asarray(png)[35, 60]), 32768)
        self.assertFalse(list(self.output.rglob("*.partial*")))

    def test_rejects_misalignment_changed_source_nonfinite_and_escaping_prefix(self):
        images, info, *_ = alpha.ZuraAlphaVideoInput().prepare(str(self.source), 0, 2, 1)
        with self.assertRaisesRegex(ValueError, "frame count"):
            alpha.ZuraAlphaVideoOutput().save(images[:2], info)
        broken = images.clone()
        broken[0, 5, 5, 0] = float("nan")
        with self.assertRaisesRegex(ValueError, "invalid pixels"):
            alpha.ZuraAlphaVideoOutput().save(broken, info)
        with self.assertRaisesRegex(ValueError, "inside"):
            alpha.ZuraAlphaVideoOutput().save(images, info, "../outside")
        with self.assertRaisesRegex(ValueError, "frame range"):
            alpha.ZuraAlphaVideoOutput().save(images, {**info, "frame_count": 10})
        self.assertFalse(list(self.output.rglob("*.partial*")))
        self.source.touch()
        with self.assertRaisesRegex(ValueError, "changed"):
            alpha.ZuraAlphaVideoOutput().save(images, info)

    def test_nine_frame_silent_delivery_preserves_exact_count(self):
        silent = self.directory / "silent.mkv"
        subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-i", str(self.source),
                        "-map", "0:v:0", "-c:v", "copy", "-an", str(silent)], check=True, capture_output=True)
        images, info, *_ = alpha.ZuraAlphaVideoInput().prepare(str(silent), 2, 9, 1)
        result = alpha.ZuraAlphaVideoOutput().save(torch.ones_like(images), info)
        for item in result["ui"]["images"]:
            if item["role"] == "sequence":
                continue
            streams = self.probe(self.output / item["subfolder"] / item["filename"])
            self.assertFalse(any(stream["codec_type"] == "audio" for stream in streams))
            video = next(stream for stream in streams if stream["codec_type"] == "video")
            self.assertEqual(int(video["nb_frames"]), 9)
            self.assertEqual(video["avg_frame_rate"], "30000/1001")

    def test_hdr_footage_is_rejected(self):
        base = {"streams": [{"codec_type": "video", "color_transfer": "smpte2084", "width": 1920, "height": 1080,
                              "avg_frame_rate": "24/1", "r_frame_rate": "24/1", "nb_frames": "9"}]}
        fake = types.SimpleNamespace(stdout=json.dumps(base))
        with patch.object(alpha, "_run", return_value=fake):
            with self.assertRaisesRegex(ValueError, "SDR"):
                alpha.probe_source(self.source)


if __name__ == "__main__":
    unittest.main()
