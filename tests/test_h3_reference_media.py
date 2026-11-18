import importlib.util
from pathlib import Path
import unittest
import torch

spec = importlib.util.spec_from_file_location("reference_media", Path(__file__).resolve().parents[1] / "h3_reference_media.py")
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)


class ReferenceMediaTests(unittest.TestCase):
    def test_resamples_selected_interval_to_24fps(self):
        frames = torch.arange(90).reshape(90, 1, 1, 1)
        result, audio = media.H3ReferenceVideo().prepare(frames, 1, 2, 30)
        self.assertEqual(result.shape[0], 48)
        self.assertEqual(result[0].item(), 30)
        self.assertEqual(result[-1].item(), 88)
        self.assertIsNone(audio)

    def test_short_source_never_indexes_beyond_end(self):
        frames = torch.zeros(12, 1, 1, 3)
        result, _ = media.H3ReferenceVideo().prepare(frames, 0, 3, 24)
        self.assertEqual(result.shape[0], 12)
        with self.assertRaises(ValueError):
            media.H3ReferenceVideo().prepare(frames, 2, 3, 24)

    def test_audio_window_and_stereo(self):
        source = {"sample_rate": 100, "waveform": torch.arange(400).reshape(1, 1, 400)}
        frames = torch.zeros(96, 1, 1, 3)
        _, audio = media.H3ReferenceVideo().prepare(frames, 1, 2, 24, source)
        self.assertEqual(tuple(audio["waveform"].shape), (1, 2, 200))
        self.assertEqual(audio["waveform"][0, 0, 0].item(), 100)
        self.assertEqual(source["waveform"].shape[1], 1)
        guarded, = media.H3ReferenceAudio().prepare(source, 1)
        self.assertEqual(tuple(guarded["waveform"].shape), (1, 2, 100))

    def test_invalid_timing(self):
        for fps in (0, float("nan"), -24):
            with self.assertRaises(ValueError):
                media.H3ReferenceVideo().prepare(torch.zeros(48, 1, 1, 3), 0, 2, fps)


if __name__ == "__main__":
    unittest.main()
