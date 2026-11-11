import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from comfylink.preflight import inspect_graph, inspect_requirements
from comfylink.presets import catalogue, preset_by_id
from comfylink.routes import register


class CatalogueTest(unittest.TestCase):
    def test_native_graph_and_roles_are_preserved(self):
        old = preset_by_id("zura-character-mask-video")
        new = preset_by_id("zura-character-matte-video")
        self.assertEqual(old["outputRole"], "replacement")
        self.assertEqual(new["outputRole"], "matte")
        self.assertEqual(old["revision"], "legacy-1")
        self.assertEqual(new["revision"], "1")
        self.assertEqual(old["workflow"], new["workflow"])
        graph = old["workflow"]
        self.assertEqual(graph["1"]["class_type"], "LoadVideo")
        self.assertEqual(graph["2"]["class_type"], "SaveVideo")
        self.assertEqual(graph["2"]["inputs"]["format.codec"], "auto")
        self.assertEqual(graph["6"]["inputs"]["audio"], ["7", 1])
        self.assertEqual(graph["6"]["inputs"]["fps"], ["7", 2])
        self.assertEqual(graph["1"]["inputs"]["file"], "placeholder.mp4")
        self.assertEqual(old["workflowHash"], "febc6614b44c3c0d4116dfce1ee4e095176d15fc6af6f0adc995d9d5dba6f5f3")
        self.assertEqual(len({p["id"] for p in catalogue()}), len(catalogue()))

    def test_preflight_detects_missing_and_disconnected_nodes(self):
        preset = preset_by_id("native-video-roundtrip")
        graph = preset["workflow"]
        result = inspect_graph(graph, preset["input"], preset["output"], {"LoadVideo"})
        self.assertEqual(result["missing_nodes"], ["SaveVideo"])
        graph["2"]["inputs"]["video"] = ["99", 0]
        result = inspect_graph(graph, preset["input"], preset["output"], {"LoadVideo", "SaveVideo"})
        self.assertFalse(result["ready"])
        self.assertTrue(any("missing node" in error for error in result["errors"]))
        self.assertFalse(inspect_graph(graph, {"node": [], "field": "file"}, preset["output"], {})["ready"])

    def test_runtime_model_resolution_and_unknown_custom_requirements(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "sub").mkdir()
            (root / "sub" / "model.onnx").write_bytes(b"fixture")
            missing_root = root / "disconnected"
            class Folders:
                models_dir = str(root)
                def get_folder_paths(self, category):
                    return [str(root), str(missing_root)]
                def get_full_path(self, category, name):
                    if category == "custom_alias" and name == "sub/model.onnx":
                        return str(root / name)
                    return None
            result = inspect_requirements({}, {}, Folders(), declared=[
                {"category": "custom_alias", "name": "sub/model.onnx"},
                {"category": "detection", "name": "missing.onnx"},
            ])
            self.assertEqual(result["model_requirements"], "unknown")
            self.assertEqual([m["status"] for m in result["models"]], ["resolved", "not_resolvable"])
            self.assertEqual(result["models"][0]["available_roots"], 1)
            self.assertEqual(result["models"][0]["unavailable_roots"], 1)
            self.assertNotIn(str(root), json.dumps(result))
            with patch("builtins.open", side_effect=PermissionError("denied")):
                unreadable = inspect_requirements({}, {}, Folders(), declared=[{"category": "custom_alias", "name": "sub/model.onnx"}])
            self.assertEqual(unreadable["models"][0]["status"], "unreadable")
            invalid = inspect_requirements({}, {}, Folders(), declared=[{"category": "detection", "name": "../secret"}])
            self.assertTrue(invalid["errors"])

    def test_mask_uses_loaded_node_model_contract_and_default_fallback(self):
        global MODEL_NAME
        MODEL_NAME = "fixture-segment.pt"
        def detect():
            pass
        def pose():
            return helper("fixture-pose.onnx", "fixture-yolo.onnx")
        def helper(*args):
            return args
        def prepare():
            return detect(), pose()
        # Real Zura's prepare looks these functions up in module globals.
        prepare.__globals__["detect"] = detect
        prepare.__globals__["_run_pose_face"] = pose
        ZuraMask = type("ZuraMask", (), {"prepare": prepare})
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / "ultralytics" / "segm").mkdir(parents=True)
                (root / "ultralytics" / "segm" / MODEL_NAME).write_bytes(b"fixture")
                (root / "fixture-pose.onnx").write_bytes(b"fixture")
                class Folders:
                    models_dir = str(root)
                    def get_folder_paths(self, category):
                        return [str(root)]
                    def get_full_path(self, category, name):
                        path = root / name
                        return str(path) if category == "detection" and path.is_file() else None
                available = {"TrendStudioV2MaskPerformer": ZuraMask,
                             "OnnxDetectionModelLoader": object(), "PoseAndFaceDetection": object(), "DrawViTPose": object()}
                with patch("comfylink.preflight.importlib.util.find_spec", return_value=object()):
                    mask_graph = {"3": {"class_type": "TrendStudioV2MaskPerformer", "inputs": {}}}
                    result = inspect_requirements(mask_graph, available, Folders(), preset_id="zura-character-matte-video", canonical_match=True)
                self.assertEqual(result["model_requirements"], "complete")
                self.assertEqual([m["status"] for m in result["models"]], ["resolved", "resolved", "not_resolvable"])
                self.assertEqual(result["models"][0]["resolution"], "default_model_fallback")
                self.assertEqual(result["missing_dependencies"], [])
                with patch("comfylink.preflight.importlib.util.find_spec", return_value=object()):
                    custom = inspect_requirements(mask_graph, available, Folders())
                self.assertEqual(custom["model_requirements"], "unknown")
                self.assertEqual(custom["models"][2]["status"], "not_resolvable")
        finally:
            del prepare.__globals__["detect"]
            del prepare.__globals__["_run_pose_face"]
            del MODEL_NAME


class RoutesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {"COMFYLINK_TOKEN": "test-private-token", "COMFYLINK_INSTANCE_ID": "test-session", "COMFYLINK_CONFIG_FINGERPRINT": "test-fingerprint"})
        self.env.start()
        self.modules = patch.dict(sys.modules, {
            "nodes": types.SimpleNamespace(NODE_CLASS_MAPPINGS={"LoadVideo": object(), "SaveVideo": object()}),
            "folder_paths": types.SimpleNamespace(base_path=str(ROOT),
                get_input_directory=lambda: str(ROOT / "input"),
                get_output_directory=lambda: str(ROOT / "output")),
        })
        self.modules.start()
        holder = types.SimpleNamespace(routes=web.RouteTableDef())
        register(holder, "test-version")
        count = len(holder.routes)
        register(holder, "test-version")
        self.assertEqual(len(holder.routes), count)
        app = web.Application()
        app.add_routes(holder.routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.modules.stop()
        self.env.stop()

    async def test_discovery_is_redacted_and_identity_is_authenticated(self):
        response = await self.client.get("/zura/comfylink/v1/capabilities")
        self.assertEqual(response.status, 200)
        body = await response.text()
        self.assertNotIn("test-private-token", body)
        self.assertNotIn("test-fingerprint", body)
        self.assertNotIn("test-session", body)
        self.assertEqual((await self.client.get("/zura/comfylink/v1/identity")).status, 403)
        response = await self.client.get("/zura/comfylink/v1/identity", headers={"Authorization": "Bearer test-private-token"})
        self.assertEqual(response.status, 200)
        identity = await response.json()
        self.assertEqual(identity["protocol_version"], "1")
        self.assertEqual(identity["pid"], os.getpid())
        self.assertEqual(identity["instance_id"], "test-session")
        self.assertEqual(Path(identity["installation_path"]), ROOT)

    async def test_cross_origin_and_foreign_host_are_rejected(self):
        url = "/zura/comfylink/v1/capabilities"
        self.assertEqual((await self.client.get(url, headers={"Origin": "https://attacker.invalid"})).status, 403)
        self.assertEqual((await self.client.get(url, headers={"Host": "attacker.invalid"})).status, 403)
        self.assertEqual((await self.client.get(url, headers={"Host": "localhost.attacker.invalid"})).status, 403)

    async def test_slow_model_lookup_keeps_capabilities_responsive(self):
        entered, release = threading.Event(), threading.Event()
        timed_out = []
        def held_lookup(*args, **kwargs):
            entered.set()
            timed_out.append(not release.wait(3))
            return inspect_requirements(*args, **kwargs)

        with patch("comfylink.routes.inspect_requirements", side_effect=held_lookup):
            pending = asyncio.create_task(self.client.post(
                "/zura/comfylink/v1/preflight",
                headers={"Authorization": "Bearer test-private-token"},
                json={"preset_id": "native-video-roundtrip"}))
            try:
                self.assertTrue(await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), 2.5))
                response = await asyncio.wait_for(self.client.get("/zura/comfylink/v1/capabilities"), 1)
                self.assertEqual(response.status, 200)
                self.assertFalse(pending.done())
            finally:
                release.set()
                await asyncio.wait_for(pending, 4)
            self.assertEqual(timed_out, [False])

    async def test_preflight_and_catalogue_require_token(self):
        path = "/zura/comfylink/v1/"
        self.assertEqual((await self.client.get(path + "presets")).status, 403)
        headers = {"Authorization": "Bearer test-private-token"}
        response = await self.client.get(path + "presets", headers=headers)
        self.assertEqual(response.status, 200)
        presets = (await response.json())["presets"]
        self.assertTrue(any(item["id"] == "native-video-roundtrip" for item in presets))
        response = await self.client.post(path + "preflight", headers=headers, json={"preset_id": "native-video-roundtrip"})
        result = await response.json()
        self.assertTrue(result["ready"])
        self.assertEqual(result["execution_ready"], "ready")
        preset = preset_by_id("native-video-roundtrip")
        custom = {"workflow": preset["workflow"], "input": preset["input"], "output": preset["output"]}
        exact = {**custom, "preset_id": preset["id"]}
        response = await self.client.post(path + "preflight", headers=headers, json=exact)
        self.assertEqual((await response.json())["execution_ready"], "ready")
        changed = {**exact, "workflow": {**preset["workflow"], "99": {"class_type": "MissingSnapshotNode", "inputs": {}}}}
        response = await self.client.post(path + "preflight", headers=headers, json=changed)
        actual = await response.json()
        self.assertEqual(actual["execution_ready"], "blocked")
        self.assertIn("MissingSnapshotNode", actual["missing_nodes"])
        changed = {**exact, "workflow": {**preset["workflow"], "2": {**preset["workflow"]["2"], "inputs": {**preset["workflow"]["2"]["inputs"], "codec": "h264"}}}}
        response = await self.client.post(path + "preflight", headers=headers, json=changed)
        self.assertEqual((await response.json())["execution_ready"], "unknown")
        response = await self.client.post(path + "preflight", headers=headers, json=custom)
        result = await response.json()
        self.assertTrue(result["graph_ready"])
        self.assertEqual(result["execution_ready"], "unknown")
        self.assertFalse(result["ready"])
        custom["required_models"] = [{"category": "detection", "name": "../private"}]
        response = await self.client.post(path + "preflight", headers=headers, json=custom)
        self.assertEqual((await response.json())["execution_ready"], "blocked")
        response = await self.client.post(path + "preflight", headers=headers, data=b"x" * (16 * 1024 * 1024 + 1))
        self.assertEqual(response.status, 413)

    async def test_unpaired_sensitive_routes_fail_closed(self):
        with patch.dict(os.environ, {"COMFYLINK_TOKEN": ""}):
            holder = types.SimpleNamespace(routes=web.RouteTableDef())
            register(holder, "test-version")
        app = web.Application()
        app.add_routes(holder.routes)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.get("/zura/comfylink/v1/identity", headers={"Authorization": "Bearer test-private-token"})
            self.assertEqual(response.status, 403)
        finally:
            await client.close()

    async def test_custom_mask_checks_actual_missing_models(self):
        global MODEL_NAME
        MODEL_NAME = "missing-segment.pt"
        def detect():
            pass
        def pose():
            return helper("missing-pose.onnx", "missing-yolo.onnx")
        def helper(*args):
            return args
        def prepare():
            return detect(), pose()
        prepare.__globals__["detect"] = detect
        prepare.__globals__["_run_pose_face"] = pose
        try:
            available = sys.modules["nodes"].NODE_CLASS_MAPPINGS
            available.update({"TrendStudioV2MaskPerformer": type("ZuraMask", (), {"prepare": prepare}),
                              "OnnxDetectionModelLoader": object(), "PoseAndFaceDetection": object(), "DrawViTPose": object()})
            folders = sys.modules["folder_paths"]
            folders.get_folder_paths = lambda category: []
            folders.get_full_path = lambda category, name: None
            with tempfile.TemporaryDirectory() as temp:
                folders.models_dir = temp
                preset = preset_by_id("native-video-roundtrip")
                graph = {**preset["workflow"], "3": {"class_type": "TrendStudioV2MaskPerformer", "inputs": {}}}
                payload = {"preset_id": "custom-mask", "workflow": graph, "input": preset["input"], "output": preset["output"]}
                with patch("comfylink.preflight.importlib.util.find_spec", return_value=object()):
                    response = await self.client.post("/zura/comfylink/v1/preflight", headers={"Authorization": "Bearer test-private-token"}, json=payload)
                result = await response.json()
                self.assertEqual(result["execution_ready"], "blocked")
                self.assertEqual(result["model_requirements"], "unknown")
                self.assertEqual([m["status"] for m in result["models"]], ["not_resolvable"] * 3)
                self.assertEqual(result["inference"], "not_run")
        finally:
            del prepare.__globals__["detect"]
            del prepare.__globals__["_run_pose_face"]
            del MODEL_NAME


if __name__ == "__main__":
    unittest.main()
