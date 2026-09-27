"""Package-level V4 checks without GPU inference or a ComfyUI checkout."""
from __future__ import annotations

import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch

import v2_bootstrap  # noqa: F401


module = importlib.import_module("ComfyUI_zura_nodes.multicam_v4_clean")


class Frames:
    ndim = 4

    def __len__(self):
        return 25


class FakeNode:
    def __init__(self, key):
        self.key = key

    def out(self, slot):
        return [self.key, slot]


class FakeGraphBuilder:
    def __init__(self):
        self.nodes = {}

    def node(self, class_type, **inputs):
        key = str(len(self.nodes) + 1)
        self.nodes[key] = {"class_type": class_type, "inputs": inputs}
        return FakeNode(key)

    def finalize(self):
        return self.nodes


def graph_stubs():
    package = types.ModuleType("comfy_execution")
    package.__path__ = []
    child = types.ModuleType("comfy_execution.graph_utils")
    child.GraphBuilder = FakeGraphBuilder
    child.ExecutionBlocker = type("ExecutionBlocker", (), {"__init__": lambda self, value=None: None})
    return {"comfy_execution": package, "comfy_execution.graph_utils": child}


class MulticamV4ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.frames = Frames()
        self.plan = json.dumps({"frame_count": 25, "frames_per_shot": 12,
                                "choices": [0, 1, 0], "shot_prompts": ["", "", ""]})

    def args(self, **overrides):
        values = dict(source_frames=self.frames, source_audio=object(),
                      h3_frames=self.frames, shot_plan=self.plan,
                      look_enabled=True, look_prompt="Grey studio",
                      **{name: object() for name in module.MODEL_INPUTS})
        values.update(overrides)
        return values

    def test_shot_plan_covers_source_without_gaps(self):
        _, shots = module.parse_shots(self.plan, 25)
        self.assertEqual([(s["start"], s["count"], s["angle"]) for s in shots],
                         [(0, 12, 0), (12, 12, 1), (24, 1, 0)])
        with self.assertRaisesRegex(ValueError, "frame count"):
            module.parse_shots(self.plan, 24)

    def test_look_off_is_lazy_and_keeps_original_audio(self):
        node = module.ZuraCleanMulticamV4()
        self.assertEqual(node.check_lazy_status(False, h3_frames=self.frames), [])
        with patch.dict(sys.modules, graph_stubs()):
            output = node.render(**self.args(look_enabled=False,
                                             **{name: None for name in module.MODEL_INPUTS}))
        self.assertIs(output["result"][0], self.frames)
        self.assertEqual([item["class_type"] for item in output["expand"].values()],
                         ["TrimAudioDuration"])

    def test_look_on_expands_alignment_and_native_generation(self):
        node = module.ZuraCleanMulticamV4()
        with patch.dict(sys.modules, graph_stubs()):
            output = node.render(**self.args())
        classes = [item["class_type"] for item in output["expand"].values()]
        for required in ("ZuraMatchMouthMotion", "ZuraIDV2VForegroundControl",
                         "WanVaceToVideo", "SamplerCustom", "TrimAudioDuration"):
            self.assertIn(required, classes)
        self.assertEqual(classes.count("ZuraMatchMouthMotion"), 1)
        self.assertEqual(classes.count("SamplerCustom"), 2)

    def test_missing_models_fail_before_expansion(self):
        node = module.ZuraCleanMulticamV4()
        with patch.dict(sys.modules, graph_stubs()):
            with self.assertRaisesRegex(ValueError, "prepared Wan IDV2V"):
                node.render(**self.args(wan_model=None))


if __name__ == "__main__":
    unittest.main()
