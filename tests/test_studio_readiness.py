"""Readiness follows the actual layout and H3 graph dependencies, without inference."""
import asyncio
import json
import sys
import types
import unittest
from unittest.mock import patch

from test_artist_studio import studio, h3
from ComfyUI_zura_nodes.artist_studio import ltx25, enhancement, speech, wan_speech
import nodes


class StudioReadinessTests(unittest.TestCase):
    def layout_nodes(self):
        # An empty map asks the real checker for every required node.
        with patch.object(studio.folder_paths, "get_full_path", return_value="installed"):
            return set(studio.ltx25_viewport_readiness({})["missing_nodes"])

    def test_layout_adapter_is_required_even_when_union_is_installed(self):
        adapter = ltx25.VIEWPORT_MODELS["union"]
        def lookup(folder, name):
            return None if name == adapter else "installed"
        with patch.object(studio.folder_paths, "get_full_path", side_effect=lookup):
            result = studio.ltx25_viewport_readiness(dict.fromkeys(self.layout_nodes()))
        self.assertFalse(result["ready"])
        self.assertEqual([item["filename"] for item in result["model_files"] if not item["ready"]], [adapter])

    def test_layout_does_not_require_union_or_body_detectors(self):
        required = self.layout_nodes()
        self.assertNotIn("DWPreprocessor", required)
        self.assertIn("LTXAddVideoICLoRAGuide", required)
        self.assertNotIn("LTXAddVideoICLoRAGuideAdvanced", required)
        with patch.object(studio.folder_paths, "get_full_path", return_value="installed") as lookup:
            result = studio.ltx25_viewport_readiness(dict.fromkeys(required))
        self.assertTrue(result["ready"])
        requested = {call.args[1] for call in lookup.call_args_list}
        self.assertNotIn(ltx25.QUALIFIED_MODELS["union"], requested)
        self.assertNotIn(ltx25.QUALIFIED_MODELS["bbox_detector"], requested)
        self.assertEqual(requested, set(ltx25.VIEWPORT_MODELS.values()) |
                         {"gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors"})

    def test_missing_layout_native_node_prevents_ready(self):
        available = self.layout_nodes() - {"LTXAddVideoICLoRAGuide"}
        with patch.object(studio.folder_paths, "get_full_path", return_value="installed"):
            result = studio.ltx25_viewport_readiness(dict.fromkeys(available))
        self.assertFalse(result["ready"])
        self.assertEqual(result["missing_nodes"], ["LTXAddVideoICLoRAGuide"])

    def test_h3_regular_and_viewport_separate_depth_control_requirements(self):
        self.assertIn("DepthAnythingV2Preprocessor", h3.H3_NATIVE_NODES)
        self.assertIn("GetImageRangeFromBatch", h3.H3_NATIVE_NODES)
        self.assertNotIn("DepthAnythingV2Preprocessor", h3.H3_VIEWPORT_NATIVE_NODES)
        self.assertNotIn("MiniMaxH3FunControlNetApply", h3.H3_VIEWPORT_NATIVE_NODES)
        self.assertNotIn("h3_control", h3.H3_VIEWPORT_MODELS)
        self.assertIn("GetImageRangeFromBatch", h3.H3_VIEWPORT_NATIVE_NODES)

    def test_status_exposes_separate_routes_and_preserves_existing_fields(self):
        server = types.SimpleNamespace(routes=studio.web.RouteTableDef(), last_prompt_id=None,
                                       prompt_queue=types.SimpleNamespace(get_current_queue_volatile=lambda: ([], [])))
        module = types.ModuleType("server")
        module.PromptServer = types.SimpleNamespace(instance=server)
        available = dict.fromkeys(self.layout_nodes() | set(h3.H3_VIEWPORT_NATIVE_NODES))
        with patch.dict(sys.modules, {"server": module}), patch.object(studio, "Studio"), \
                patch.object(nodes, "NODE_CLASS_MAPPINGS", available), \
                patch.object(studio.folder_paths, "get_full_path", return_value="installed"), \
                patch.object(studio, "ltx25_detector_paths", return_value={"bbox_detector": None, "pose_estimator": None}), \
                patch.object(enhancement, "readiness", return_value={"ready": True}), \
                patch.object(speech, "readiness", return_value={}), \
                patch.object(wan_speech, "readiness", return_value={}):
            studio.register()
            route = next(item for item in server.routes if item.path == "/zura/studio/status")
            result = json.loads(asyncio.run(route.handler(types.SimpleNamespace(headers={}, host="local"))).text)
        self.assertTrue(result["engine_ready"]["local_viewport"])
        self.assertTrue(result["engine_ready"]["h3_viewport"])
        self.assertFalse(result["engine_ready"]["local_scene"])
        self.assertFalse(result["engine_ready"]["h3"])
        self.assertIn("DepthAnythingV2Preprocessor", result["missing_h3_nodes"])
        for legacy in ("local", "local_scene", "h3", "wan", "h3_enhanced1080"):
            self.assertIn(legacy, result["engine_ready"])
        self.assertEqual(result["missing_ltx_viewport_nodes"], [])
        self.assertEqual(result["missing_h3_viewport_nodes"], [])
        self.assertEqual({item["filename"] for item in result["model_files"]["h3_viewport"]},
                         {name for _, name in h3.H3_VIEWPORT_MODELS.values()})


if __name__ == "__main__":
    unittest.main()
