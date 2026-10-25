"""Progress is estimated from action-scoped native node updates only."""
import unittest
import importlib.util
from pathlib import Path
from types import SimpleNamespace

_module_path = Path(__file__).parents[1] / "artist_studio" / "progress.py"
_spec = importlib.util.spec_from_file_location("zura_studio_progress", _module_path)
_progress = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_progress)
NativeProgressAdapter = _progress.NativeProgressAdapter
ProgressEstimator = _progress.ProgressEstimator


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class ProgressEstimatorTests(unittest.TestCase):
    def test_eta_requires_two_positive_measured_intervals(self):
        clock = Clock()
        estimator = ProgressEstimator(clock=clock)
        def advance(value):
            return estimator.update("comfy-a", "prompt-a", "node-1", "Generating video",
                                    value, 100)

        first = advance(10)
        self.assertIsNone(first["stage_remaining_seconds"])
        self.assertEqual(first["eta_confidence"], "estimating")
        clock.now = 2
        second = advance(20)
        self.assertIsNone(second["stage_remaining_seconds"])
        clock.now = 4
        third = advance(30)
        self.assertEqual(third["eta_confidence"], "measured")
        self.assertAlmostEqual(third["stage_remaining_seconds"], 14)
        self.assertEqual(third["stage_percent"], 30)
        self.assertEqual(third["stage_elapsed_seconds"], 4)

    def test_slow_first_step_is_excluded_from_eta_rate(self):
        clock = Clock()
        estimator = ProgressEstimator(clock=clock)
        def advance(value):
            return estimator.update("comfy", "slow-start", "node", "Generating video", value, 100)

        advance(0)
        clock.now = 90  # Model initialization before the first useful step.
        self.assertIsNone(advance(1)["stage_remaining_seconds"])
        clock.now = 91
        self.assertIsNone(advance(2)["stage_remaining_seconds"])
        clock.now = 92
        result = advance(3)
        self.assertEqual(result["eta_confidence"], "measured")
        self.assertAlmostEqual(result["stage_remaining_seconds"], 97)
        self.assertEqual(result["stage_elapsed_seconds"], 92)

    def test_default_single_step_loader_is_indeterminate_but_elapsed_advances(self):
        clock = Clock()
        estimator = ProgressEstimator(clock=clock)
        def loading():
            return estimator.update("comfy", "loader", "node", "LoadImage", 0, 1)

        first = loading()
        self.assertEqual(first["state"], "preparing")
        self.assertEqual(first["stage_label"], "Loading")
        self.assertIsNone(first["stage_percent"])
        self.assertIsNone(first["step"])
        self.assertIsNone(first["total_steps"])
        self.assertIsNone(first["stage_remaining_seconds"])
        clock.now = 3.5
        second = loading()
        self.assertEqual(second["stage_elapsed_seconds"], 3.5)

    def test_comfy_loader_labels_name_slow_h3_initialization_steps(self):
        self.assertEqual(_progress._friendly_node("UNETLoader"), "Loading H3 video model")
        self.assertEqual(_progress._friendly_node("CLIPLoader"), "Loading H3 text encoder")
        self.assertEqual(_progress._friendly_node("VAELoader"), "Loading H3 decoder")
        self.assertEqual(_progress._friendly_node("DepthAnythingV2Preprocessor"), "Building depth guidance")

    def test_rewind_node_change_and_maximum_change_reset_eta(self):
        clock = Clock()
        estimator = ProgressEstimator(clock=clock)
        def update(value, node="node-1", maximum=100):
            return estimator.update("server", "action", node, "Working", value, maximum)

        update(5)
        clock.now = 1
        update(10)
        clock.now = 2
        self.assertEqual(update(20)["eta_confidence"], "measured")
        clock.now = 3
        self.assertEqual(update(3)["eta_confidence"], "estimating")
        clock.now = 4
        self.assertEqual(update(4, node="node-2")["eta_confidence"], "estimating")
        clock.now = 5
        self.assertEqual(update(5, node="node-2", maximum=200)["eta_confidence"], "estimating")

    def test_rewind_uses_rewound_value_as_new_baseline_and_resets_elapsed(self):
        clock = Clock()
        estimator = ProgressEstimator(clock=clock)
        def update(value):
            return estimator.update("server", "rewind", "node", "Working", value, 100)

        update(10)
        clock.now = 1
        update(20)
        clock.now = 2
        self.assertEqual(update(30)["eta_confidence"], "measured")
        clock.now = 3
        rewound = update(4)
        self.assertEqual(rewound["eta_confidence"], "estimating")
        self.assertEqual(rewound["stage_elapsed_seconds"], 0)
        clock.now = 4
        self.assertEqual(update(5)["eta_confidence"], "estimating")
        clock.now = 5
        self.assertEqual(update(6)["eta_confidence"], "measured")

    def test_progress_is_isolated_by_server_and_action(self):
        clock = Clock()
        estimator = ProgressEstimator(clock=clock)
        estimator.update("server-a", "action-a", "node", "Working", 5, 10)
        clock.now = 3
        result = estimator.update("server-b", "action-a", "node", "Working", 9, 10)
        self.assertEqual(result["eta_confidence"], "estimating")
        clock.now = 4
        result = estimator.update("server-a", "action-b", "node", "Working", 9, 10)
        self.assertEqual(result["eta_confidence"], "estimating")


class NativeAdapterTests(unittest.TestCase):
    def test_design_sampler_reports_image_without_changing_video_actions(self):
        registry = self.registry("image", {"sampler": {"state": "running", "value": 2, "max": 4}})
        adapter = NativeProgressAdapter(registry_getter=lambda: registry)
        result = adapter.project_progress(None, "server", {"id": "image", "state": "running", "stage": "design"})
        self.assertEqual(result["stage_label"], "Generating image")
        self.assertEqual(_progress._friendly_node("UNETLoader", "design"), "Loading image model")
        self.assertEqual(_progress._friendly_node("VAEDecode", "design"), "Decoding image")
        self.assertEqual(_progress._friendly_node("KSampler", "h3"), "Generating video")

    @staticmethod
    def registry(prompt_id, nodes, class_type="KSampler"):
        return SimpleNamespace(prompt_id=prompt_id, nodes=nodes,
                               dynprompt=SimpleNamespace(get_node=lambda _id: {"class_type": class_type}))

    def test_only_matching_running_action_uses_registry_and_label(self):
        registry = self.registry("prompt-a", {"node-1": {"state": "running", "value": 4, "max": 8}})
        adapter = NativeProgressAdapter(registry_getter=lambda: registry)
        action = {"id": "prompt-a", "state": "running", "stage": "h3"}
        result = adapter.project_progress(None, "server", action)
        self.assertEqual(result["stage_label"], "Generating video")
        self.assertEqual(result["step"], 4)
        self.assertIsNone(result["stage_remaining_seconds"])

        action["id"] = "foreign-prompt"
        result = adapter.project_progress(None, "server", action)
        self.assertEqual(result["state"], "preparing")
        self.assertEqual(result["stage_label"], "Generating video")

    def test_queued_complete_and_unsupported_snapshot_are_indeterminate(self):
        adapter = NativeProgressAdapter(registry_getter=lambda: None)
        queued = adapter.project_progress(None, "server", {"id": "a", "state": "queued", "stage": "h3"}, 2)
        self.assertEqual(queued["state"], "queued")
        self.assertEqual(queued["queue_position"], 2)
        self.assertIsNone(queued["stage_percent"])
        complete = adapter.project_progress(None, "server", {"id": "a", "state": "complete"})
        self.assertEqual(complete["state"], "complete")
        self.assertEqual(complete["stage_percent"], 100)
        unsupported = adapter.project_progress(None, "server", {"id": "b", "state": "running", "stage": "ltx25_stage1"})
        self.assertEqual(unsupported["eta_confidence"], "estimating")
        self.assertIsNone(unsupported["stage_remaining_seconds"])
        self.assertIn("LTX 2.5", unsupported["stage_label"])


if __name__ == "__main__":
    unittest.main()
