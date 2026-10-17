import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import v2_bootstrap

NAME = "ComfyUI_zura_nodes.artist_studio"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[NAME] = package
content = importlib.import_module(NAME + ".content")


class ContentAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source.mp4"
        self.source.write_bytes(b"private source")
        self.model = Path(self.temp.name) / "yolov10m.onnx"
        self.model.write_bytes(b"fake detector")
        with content._CACHE_LOCK:
            content._CACHE.clear()

    def frames(self, path, times):
        self.assertEqual(path, self.source)
        return iter([object() for _ in times])

    def analyze(self, rows, **kwargs):
        return content.analyze(self.source, self.model, runner=lambda frame: np.asarray(rows),
                               frame_reader=self.frames, **kwargs)

    def test_person_class_and_meaningful_box(self):
        result = self.analyze([[50, 20, 200, 400, .8, 0]])
        self.assertEqual(result["status"], "people")
        self.assertEqual(result["person_frames"], 5)
        self.assertEqual(result["confidence"], .8)
        self.assertTrue(result["advisory"])

    def test_false_positives_and_other_classes_are_ignored(self):
        result = self.analyze([[0, 0, 400, 400, .95, 1], [0, 0, 400, 400, .39, 0],
                               [0, 0, 1, 1, .99, 0], [100, 100, 0, 0, .99, 0]])
        self.assertEqual(result["status"], "objects")
        self.assertEqual(result["reason"], "No people found in sampled frames.")

    def test_empty_post_nms_output(self):
        self.assertEqual(content.person_scores(np.empty((1, 0, 6))), [])

    def test_unknown_output_formats(self):
        for output in (np.zeros((1, 84, 8400)), np.zeros((4,)), np.full((2, 6), np.nan)):
            with self.assertRaises(ValueError):
                content.person_scores(output)
        self.assertEqual(self.analyze(np.zeros((1, 84, 8400)))["status"], "unknown")

    def test_interval_is_bounded_and_samples_are_inside(self):
        times = content.sample_times(10, 3)
        self.assertEqual(len(times), 5)
        self.assertTrue(all(10 < time < 13 for time in times))
        for start, duration in ((-1, 5), (0, 0), (0, 31), (float("nan"), 5), (0, float("inf"))):
            with self.assertRaises(ValueError):
                content.interval(start, duration)

    def test_viewport_does_not_call_inference(self):
        def fail(*args):
            raise AssertionError("viewport must not run people inference")
        result = content.analyze(self.source, self.model, viewport=True, runner=fail, frame_reader=fail)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["sampled_frames"], 0)

    def test_partial_decode_is_unknown_even_with_people(self):
        result = content.analyze(self.source, self.model, runner=lambda frame: np.array([[0, 0, 500, 500, .9, 0]]),
                                 frame_reader=lambda path, times: iter([object()]))
        self.assertEqual(result["status"], "unknown")

    def test_missing_model_and_runtime_are_unknown(self):
        self.assertEqual(content.analyze(self.source, None)["status"], "unknown")
        with patch.object(content, "cpu_runner", side_effect=ImportError("runtime missing")):
            result = content.analyze(self.source, self.model)
        self.assertEqual(result["status"], "unknown")
        self.assertNotIn("runtime missing", result["reason"])

    def test_cache_key_invalidates_source_interval_and_model(self):
        sha = content.source_sha(self.source)
        first = content.analysis_key(sha, self.model, 0, 5)
        self.assertNotEqual(first, content.analysis_key(sha, self.model, 1, 5))
        self.assertNotEqual(first, content.analysis_key("another sha", self.model, 0, 5))
        self.model.write_bytes(b"different detector bytes")
        self.assertNotEqual(first, content.analysis_key(sha, self.model, 0, 5))

    def test_cache_is_bounded_and_does_not_share_mutable_results(self):
        result = content.analyze(self.source, None)
        result["status"] = "people"
        self.assertEqual(content.analyze(self.source, None)["status"], "unknown")
        for index in range(content.MAX_CACHE + 5):
            content.analyze(self.source, None, start=index)
        self.assertEqual(len(content._CACHE), content.MAX_CACHE)

    def test_cpu_session_uses_only_cpu_and_two_threads(self):
        from PIL import Image
        captured = {}
        class Options:
            pass
        class Session:
            def __init__(self, path, **kwargs):
                captured.update(kwargs)
            def get_inputs(self):
                return [types.SimpleNamespace(name="images", shape=[1, 3, 640, 640], type="tensor(float)")]
            def run(self, output, inputs):
                tensor = inputs["images"]
                self_outer.assertEqual(tensor.shape, (1, 3, 640, 640))
                self_outer.assertEqual(tensor.dtype, np.float32)
                self_outer.assertLessEqual(tensor.max(), 1)
                return [np.empty((1, 0, 6))]
        self_outer = self
        fake = types.SimpleNamespace(SessionOptions=Options, InferenceSession=Session)
        with patch.dict(sys.modules, {"onnxruntime": fake}):
            content.cpu_runner(self.model)(Image.new("RGB", (8, 8)))
        self.assertEqual(captured["providers"], ["CPUExecutionProvider"])
        self.assertEqual(captured["sess_options"].intra_op_num_threads, 2)


if __name__ == "__main__":
    unittest.main()
