"""Structural regression checks for the one-camera H3 adapter."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "h3_single_angle_test", Path(__file__).resolve().parents[1] / "h3_single_angle.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TestH3SingleAngle(unittest.TestCase):
    def test_padding_and_chunk_boundaries(self):
        self.assertEqual(MODULE._valid_length(96), 107)
        self.assertEqual(MODULE._valid_length(124), 124)
        self.assertEqual(MODULE._chunks(96), [(0, 96)])
        self.assertEqual(MODULE._chunks(130), [(0, 108), (108, 22)])

    def test_native_expansion_keeps_source_audio_and_frame_count(self):
        calls = []

        class FakeNode:
            def __init__(self, index):
                self.index = index

            def out(self, slot):
                return (self.index, slot)

        class FakeGraph:
            def node(self, name, **kwargs):
                calls.append((name, kwargs))
                return FakeNode(len(calls))

            def finalize(self):
                return calls

        fake_utils = types.ModuleType("comfy_execution.graph_utils")
        fake_utils.GraphBuilder = FakeGraph

        class Frames:
            shape = (96, 352, 640, 3)

        with patch.dict(sys.modules, {
            "comfy_execution": types.ModuleType("comfy_execution"),
            "comfy_execution.graph_utils": fake_utils,
        }):
            result = MODULE.ZuraH3SingleAngle().render(
                Frames(), "speech", ["still"], "model", "clip",
                "video-vae", "audio-vae", 42, 16,
                "<Picture 1> <Video 1>")

        self.assertEqual(result["result"][1], (len(calls), 0))
        h3 = [kwargs for name, kwargs in calls
              if name == "MiniMaxH3ReferenceToVideo"]
        self.assertEqual(len(h3), 1)
        self.assertEqual(h3[0]["length"], 107)
        self.assertTrue(h3[0]["ref_video_audios.ref_video_audio_0"])
        self.assertTrue(any(name == "MiniMaxH3AddGuide" and "audio" in kwargs
                            for name, kwargs in calls))
        self.assertTrue(any(name == "GetImageRangeFromBatch"
                            and kwargs["num_frames"] == 96
                            for name, kwargs in calls))
        self.assertEqual(calls[-1][0], "TrimAudioDuration")
        self.assertEqual(calls[-1][1]["duration"], 4.0)


if __name__ == "__main__":
    unittest.main()
