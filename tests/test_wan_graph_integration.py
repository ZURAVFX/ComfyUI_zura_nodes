"""Read-only Graph export/HTTP transitions and manual render controls, CPU only."""
import asyncio
import copy
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_wan_graph as fixtures

studio = fixtures.studio
planner = fixtures.planner
wan = fixtures.importlib.import_module(fixtures.NAME + ".wan")

# Registering the Studio routes loads Paintout's native NumPy/SciPy helpers.
# Load them before the per-test sys.modules snapshot so C extensions are not
# removed and imported a second time after a route registration.
if "ComfyUI_zura_nodes.paintout" not in sys.modules:
    paintout_package = types.ModuleType("ComfyUI_zura_nodes.paintout")
    paintout_package.__path__ = [str(Path(__file__).resolve().parents[1] / "paintout")]
    sys.modules[paintout_package.__name__] = paintout_package
fixtures.importlib.import_module("ComfyUI_zura_nodes.paintout.paintout")


class WanGraphIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WanGraphTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.project = self.fixture.project
        self.project["config"] = studio.clean_config(self.project["config"])

    def test_export_seeds_guard_without_saving_project_or_creating_cache(self):
        self.project["opening_approval"] = None
        before = copy.deepcopy(self.project)
        existing_files = sorted(str(path) for path in self.fixture.root.rglob("*"))
        with patch.object(studio, "editable_graph", return_value=(self.fixture.graph, "wan_prepare")):
            result = studio.graph_export_payload(self.project, "animate")
        self.assertEqual(result["stage"], "wan_prepare")
        self.assertEqual(result["project_id"], self.project["id"])
        self.assertEqual(result["action"], "prepare")
        self.assertIn(result["guard"]["semantic_id"], result["graph"])
        self.assertEqual(result["context"]["project_pins"]["opening_approval"], before["opening_key"])
        self.assertEqual(self.project, before)
        self.assertEqual(sorted(str(path) for path in self.fixture.root.rglob("*")), existing_files)

    def test_manual_next_preserves_artist_edits_and_project(self):
        exported = studio.wan_graph_plan_payload(self.project,
            {"action": "next", "context": None, "prompt": self.fixture.graph})
        prompt = copy.deepcopy(exported["graph"])
        prompt["pose_draw"]["inputs"]["body_stick_width"] = 5
        before = copy.deepcopy(self.project)
        result = studio.wan_graph_plan_payload(self.project,
            {"action": "next", "context": exported["context"], "prompt": prompt})
        self.assertTrue(result["progress"]["recipe_forked"])
        self.assertEqual(result["graph"]["pose_draw"]["inputs"]["body_stick_width"], 5)
        self.assertEqual(result["progress"]["next_start"], 0)
        self.assertEqual(self.project, before)

    def test_edit_motion_uses_cold_bounded_template_and_seeds_guard(self):
        before = copy.deepcopy(self.project)
        with patch.object(wan, "build_wan_graph", return_value=self.fixture.graph) as builder:
            result = studio.wan_graph_plan_payload(self.project, {"action": "edit_motion"})
        self.assertEqual(result["action"], "prepare")
        self.assertTrue(builder.call_args.kwargs["use_cache"])
        self.assertRegex(builder.call_args.kwargs["cache_key_override"], r"^[a-f0-9]{64}$")
        self.assertEqual(self.project, before)

    def test_completed_manual_render_uses_graph_size_scope_and_original_approval(self):
        before = copy.deepcopy(self.project)
        initial = self.fixture.plan()
        key = initial["context"]["context_key"]
        path = wan.cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"completed native cache fixture")
        stat = path.stat()
        plan = {"action": "render", "context": copy.deepcopy(initial["context"]),
                "render_request": {"cache_key_override": key, "require_streamed_sampler": True,
                "cache_stamp": {"path": str(path), "size": stat.st_size, "mtime_ns": str(stat.st_mtime_ns)}}}
        plan["context"]["project_pins"].update(resolution=1920, scope="head")
        with patch.object(studio, "assert_approved") as approved, patch.object(studio, "check_asset"):
            result = studio._materialise_wan_graph_plan(self.project, plan)
        approved.assert_called_once_with(self.project)
        graph = result["graph"]
        self.assertEqual(graph["wan_shot"]["inputs"]["render_long_edge"], 1920)
        self.assertEqual(graph["wan_cached"]["inputs"]["max_window_frames"], 41)
        self.assertEqual(graph["wan_render"]["inputs"]["chunk_frames"], 41)
        self.assertEqual(graph["wan_render"]["inputs"]["max_side"], 1920)
        self.assertEqual(graph["wan_export"]["inputs"]["video"], ["wan_render", 0])
        self.assertEqual(self.project, before)

    def test_cache_changed_after_plan_cannot_open_render(self):
        initial = self.fixture.plan()
        key = initial["context"]["context_key"]
        path = wan.cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"changed")
        plan = {"action": "render", "context": initial["context"],
                "render_request": {"cache_key_override": key, "require_streamed_sampler": True,
                "cache_stamp": {"path": str(path), "size": 1, "mtime_ns": path.stat().st_mtime_ns}}}
        with patch.object(wan, "build_wan_graph") as builder, self.assertRaisesRegex(ValueError, "changed"):
            studio._materialise_wan_graph_plan(self.project, plan)
        builder.assert_not_called()

    def test_warm_default_merge_waits_and_then_opens_strict_render(self):
        before = copy.deepcopy(self.project)
        merge = {"finish": {"class_type": "ZuraWanMergePreparation", "inputs": {}}}
        render = {"motion": {"class_type": "ZuraWanLoadWindowPreparation", "inputs": {}},
                  "sample": {"class_type": "ZuraWan22StreamedSampler", "inputs": {}}}
        with patch.object(wan, "build_wan_graph", side_effect=[merge, render]) as builder:
            pending = studio.wan_graph_plan_payload(self.project, {"action": "render", "context": None})
            ready = studio.wan_graph_plan_payload(self.project, {"action": "render", "context": None})
        self.assertEqual((pending["action"], ready["action"]), ("merge", "render"))
        self.assertIsNone(pending["context"])
        self.assertIsNone(ready["context"])
        self.assertTrue(all(call.kwargs == {"use_cache": True} for call in builder.call_args_list))
        self.assertEqual(self.project, before)

    def test_warm_default_cannot_skip_unfinished_preparation(self):
        with patch.object(wan, "build_wan_graph", return_value=self.fixture.graph), \
                self.assertRaisesRegex(ValueError, "finish.*motion preparation"):
            studio.wan_graph_plan_payload(self.project, {"action": "render", "context": None})

    def test_invalid_planning_actions_reject_before_builder(self):
        for body in (None, [], {"action": "queue"}, {"action": "next", "prompt": {}}):
            with self.subTest(body=body), patch.object(wan, "build_wan_graph") as builder, self.assertRaises(ValueError):
                studio.wan_graph_plan_payload(self.project, body)
            builder.assert_not_called()

    def registered_handler(self, controller):
        server = types.SimpleNamespace(routes=studio.web.RouteTableDef())
        module = types.ModuleType("server")
        module.PromptServer = types.SimpleNamespace(instance=server)
        with patch.dict(sys.modules, {"server": module}), patch.object(studio, "Studio", return_value=controller):
            studio.register()
        return next(route.handler for route in server.routes
                    if route.method == "POST" and route.path == "/zura/studio/projects/{identity}/wan-graph/plan")

    def test_http_planning_only_loads_snapshot_never_saves_or_enqueues(self):
        async def run():
            controller = types.SimpleNamespace(lock=asyncio.Lock(), start_watcher=Mock(),
                store=Mock(), enqueue=Mock())
            controller.store.load.return_value = self.project
            handler = self.registered_handler(controller)
            async def body():
                return {"action": "next", "prompt": self.fixture.graph}
            request = types.SimpleNamespace(headers={"Origin": "http://localhost:8188"}, host="localhost:8188",
                match_info={"identity": self.project["id"]}, json=body)
            response = await handler(request)
            payload = json.loads(response.text)
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["action"], "prepare")
            controller.store.load.assert_called_once_with(self.project["id"])
            controller.store.save.assert_not_called()
            controller.enqueue.assert_not_called()
        asyncio.run(run())

    def test_http_foreign_origin_rejects_before_planning(self):
        controller = types.SimpleNamespace(start_watcher=Mock(), store=Mock())
        handler = self.registered_handler(controller)
        request = types.SimpleNamespace(headers={"Origin": "https://another.example"}, host="localhost:8188")
        with self.assertRaises(studio.web.HTTPForbidden):
            asyncio.run(handler(request))
        controller.start_watcher.assert_not_called()


if __name__ == "__main__":
    unittest.main()
