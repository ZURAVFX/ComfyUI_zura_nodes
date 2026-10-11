"""Native phase orchestration/receipt tests; no GPU or real queue submission."""
import asyncio
import copy
import importlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from PIL import Image
from unittest.mock import patch

import v2_bootstrap

NAME = "ComfyUI_zura_nodes.artist_studio"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[NAME] = package
package = sys.modules[NAME]
studio = importlib.import_module(NAME + ".studio")
ltx = importlib.import_module(NAME + ".ltx25")


def example():
    config = studio.clean_config({"engine": "local", "edit_area": "scene", "resolution": 1280,
                                  "duration": 2, "audio_id": "b" * 32, "lip_sync": True})
    asset = {"file": "genj_studio/example/image.png", "sha": "a" * 64}
    p = {"id": "a" * 32, "source": {**asset, "file": "genj_studio/example/video.mp4"},
         "character": asset, "opening_input": asset, "audio": {**asset, "file": "genj_studio/example/audio.wav"},
         "config": config, "review": "review-example", "opening_key": "a" * 64,
         "opening_approval": "a" * 64, "phase": "opening", "actions": [],
         "ltx25_run": {"namespace": "a" * 32}}
    p["approval"] = studio.prep_key(p)
    plan = ltx.build_plan(p, scenario="replacement", timeline={"frames": 48, "fps": 24,
        "width": 704, "height": 1280, "has_audio": True}, models=dict(ltx.QUALIFIED_MODELS),
        model_pins={name: {"stamp": "example"} for name in (*ltx.QUALIFIED_MODELS, "text_encoder")},
        text_encoder_inputs={"clip_name": "encoder.safetensors", "type": "ltxv", "device": "default"},
        approval_key=p["approval"], original_audio_sha="c" * 64)
    p["ltx25_run"].update(plan=plan, receipts={}, next_phase="text")
    return p, plan


class Queue:
    def __init__(self):
        self.mutex = threading.RLock()
        self.flags = {}
        self.running = []
        self.pending = []
        self.submitted = []
    def get_current_queue_volatile(self):
        return self.running, self.pending
    def set_flag(self, name, value):
        self.flags[name] = value
    def get_flags(self, reset=False):
        return self.flags
    def put(self, value):
        self.submitted.append(value)


class RuntimeTests(unittest.TestCase):
    def controller(self):
        queue = Queue()
        controller = studio.Studio.__new__(studio.Studio)
        controller.server_address = "test-server"
        controller.server = types.SimpleNamespace(prompt_queue=queue, number=0,
            trigger_on_prompt=lambda value: value,
            node_replace_manager=types.SimpleNamespace(apply_replacements=lambda graph: None))
        controller.store = types.SimpleNamespace(save=lambda p: None)
        controller.resumed = []
        controller.schedule_resume = lambda identity, action: controller.resumed.append((identity, action))
        controller.start_watcher = lambda: None
        return controller

    def roots(self, directory):
        output = Path(directory) / "output"
        input_root = Path(directory) / "input"
        output.mkdir()
        input_root.mkdir()
        return output, input_root

    def produce(self, controller, p, phase, output, input_root, mutate=None):
        plan = p["ltx25_run"]["plan"]
        graph = ltx.bind_phase(plan, phase, p["ltx25_run"]["receipts"],
                              output_directory=output, input_directory=input_root)
        action = {"id": "prompt-" + phase, "stage": "ltx25_" + phase, "graph": graph,
                  "ltx25_plan_key": plan["key"], "resolution": 1280, "quality": "fast", "state": "running"}
        p["actions"].append(action)
        history = {"prompt": [0, action["id"], graph], "status": {"status_str": "success", "completed": True}, "outputs": {}}
        for name, spec in plan["artifacts"].items():
            if spec["phase"] != phase:
                continue
            if spec["kind"] == "images":
                prefix = Path(spec["prefix"])
                directory = output / prefix.parent
                directory.mkdir(parents=True)
                assets = []
                for index in range(spec["frames"]):
                    filename = prefix.name + f"_{index + 1:05}_.png"
                    Image.new("RGB", tuple(spec["raster"]), "black").save(directory / filename)
                    assets.append({"filename": filename, "subfolder": str(prefix.parent), "type": "output"})
                history["outputs"][spec["node"]] = {"images": assets}
                continue
            if spec["kind"] == "audio":
                prefix = Path(graph[spec["node"]]["inputs"]["filename_prefix"])
                relative = prefix.parent / (prefix.name + "_00001_.latent")
                history["outputs"][spec["node"]] = {"latents": [{"filename": relative.name,
                    "subfolder": str(relative.parent), "type": "output"}]}
            else:
                relative = (Path("genj/text_cache") / (spec["key"] + ".pt") if spec["kind"] == "text" else
                            Path("zura/latent_data") / (spec["key"] + ".safetensors"))
            path = output / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("synthetic data receipt " + name).encode())
        if mutate:
            mutate(history, graph)
        with patch.object(studio, "ltx25_native_plan", return_value=plan):
            controller._collect_ltx25_phase(p, action, history)
        return history, action

    def test_native_receipts_advance_five_phases_and_copy_only_conditioning_audio(self):
        p, plan = example()
        controller = self.controller()
        with tempfile.TemporaryDirectory() as directory:
            output, input_root = self.roots(directory)
            with patch.object(studio.folder_paths, "get_output_directory", return_value=str(output), create=True), \
                    patch.object(studio.folder_paths, "get_input_directory", return_value=str(input_root)):
                for phase in ltx.PHASES[:-1]:
                    self.produce(controller, p, phase, output, input_root)
                    self.assertEqual(p["actions"][-1]["state"], "complete")
                self.assertEqual(p["ltx25_run"]["next_phase"], "decode")
                audio = p["ltx25_run"]["receipts"]["audio"]
                self.assertEqual(Path(audio["input_path"]).read_bytes(), Path(audio["path"]).read_bytes())
                self.assertEqual(len(list(input_root.glob("*.latent"))), 1)
                self.assertEqual(len(controller.resumed), 5)
                self.assertEqual(audio["submitted_graph"]["save_audio"]["inputs"]["samples"], ["encode_audio", 0])

    def test_wrong_native_history_never_advances(self):
        p, plan = example()
        controller = self.controller()
        action = {"id": "expected-prompt", "stage": "ltx25_text", "graph": plan["phases"]["text"], "ltx25_plan_key": plan["key"]}
        for status, identity in (("success", "different-prompt"), ("error", "expected-prompt")):
            history = {"prompt": [0, identity, action["graph"]], "status": {"status_str": status, "completed": True}}
            with self.assertRaisesRegex(ValueError, "different or incomplete"):
                controller._collect_ltx25_phase(p, action, history)
        self.assertEqual(p["ltx25_run"]["receipts"], {})
        self.assertEqual(controller.resumed, [])

    def test_motion_sequence_validation_prevents_audio_copy_and_stage1_handoff(self):
        for mutation in ("missing", "extra", "reordered", "different_prefix", "duplicate"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                p, plan = example()
                controller = self.controller()
                output, input_root = self.roots(directory)
                def corrupt(history, graph):
                    assets = history["outputs"]["save_pose"]["images"]
                    path = output / assets[0]["subfolder"] / assets[0]["filename"]
                    if mutation == "missing":
                        path.unlink()
                    elif mutation == "extra":
                        (path.parent / "unexpected.png").write_bytes(path.read_bytes())
                    elif mutation == "reordered":
                        assets.reverse()
                    elif mutation == "duplicate":
                        assets[-1] = copy.deepcopy(assets[0])
                    else:
                        assets[0]["subfolder"] = "unrelated"
                with patch.object(studio.folder_paths, "get_output_directory", return_value=str(output), create=True), \
                        patch.object(studio.folder_paths, "get_input_directory", return_value=str(input_root)):
                    with self.assertRaises(ValueError):
                        self.produce(controller, p, "motion", output, input_root, mutate=corrupt)
                self.assertEqual(p["ltx25_run"]["receipts"], {})
                self.assertEqual(p["ltx25_run"]["next_phase"], "text")
                self.assertEqual(controller.resumed, [])
                self.assertEqual(list(input_root.iterdir()), [])

    def test_stale_audio_copy_or_scenario_blocks_refinement(self):
        p, plan = example()
        controller = self.controller()
        with tempfile.TemporaryDirectory() as directory:
            output, input_root = self.roots(directory)
            with patch.object(studio.folder_paths, "get_output_directory", return_value=str(output), create=True), \
                    patch.object(studio.folder_paths, "get_input_directory", return_value=str(input_root)):
                for phase in ("text", "motion", "stage1", "upscale"):
                    self.produce(controller, p, phase, output, input_root)
                receipt = p["ltx25_run"]["receipts"]["audio"]
                receipt["scenario"] = "silent"
                with self.assertRaisesRegex(ValueError, "another plan or scenario"):
                    ltx.bind_phase(plan, "refine", p["ltx25_run"]["receipts"], output_directory=output, input_directory=input_root)
                receipt["scenario"] = "replacement"
                Path(receipt["input_path"]).write_bytes(b"unrelated latent")
                with self.assertRaisesRegex(ValueError, "byte-identical"):
                    ltx.bind_phase(plan, "refine", p["ltx25_run"]["receipts"], output_directory=output, input_directory=input_root)

    def test_cleanup_waits_for_idle_worker_and_consumed_release_flags(self):
        p, plan = example()
        controller = self.controller()
        p["actions"] = [{"id": "cleanup", "stage": "ltx25_cleanup", "state": "waiting",
                         "graph": {"ack": {}}, "output_nodes": ["ack"]}]
        queue = controller.server.prompt_queue
        queue.running = [(0, "someone-elses-job")]
        controller.advance_wan_cleanup(p)
        self.assertEqual(queue.flags, {})
        queue.running = []
        controller.advance_wan_cleanup(p)
        self.assertEqual(queue.flags, {"unload_models": True, "free_memory": True})
        controller.advance_wan_cleanup(p)
        self.assertEqual(queue.submitted, [])
        queue.flags = {}
        controller.advance_wan_cleanup(p)
        self.assertEqual(len(queue.submitted), 1)
        self.assertEqual(queue.submitted[0][1], "cleanup")

    def test_scene_start_uses_private_plan_cleanup_without_queuing_a_gpu_job(self):
        p, plan = example()
        controller = self.controller()
        controller.collect = lambda value: value
        async def validate(*args):
            return True, None, ["ack"], {}
        fake_execution = types.SimpleNamespace(validate_prompt=validate)
        with patch.dict(sys.modules, {"execution": fake_execution}), \
                patch.object(studio, "ltx25_native_plan", return_value=plan):
            asyncio.run(controller.action(p, "animate", {"request_key": "12345678-1234-1234-1234-123456789abc"}))
        action = p["actions"][-1]
        self.assertEqual((action["stage"], action["state"], action["next_stage"]), ("ltx25_cleanup", "waiting", "ltx25_text"))
        self.assertEqual(controller.server.prompt_queue.submitted, [])

    def test_new_render_gets_fresh_files_after_completed_request_deduplication(self):
        p, plan = example()
        controller = self.controller()
        controller.collect = lambda value: value
        basis = plan["basis"]
        def replan(project):
            return ltx.build_plan(project, scenario=plan["scenario"], timeline=basis["timeline"],
                models=basis["models"], model_pins=basis["model_pins"], text_encoder_inputs=basis["encoder"],
                approval_key=p["approval"])
        async def validate(*args):
            return True, None, ["ack"], {}
        first_key = "12345678-1234-1234-1234-123456789abc"
        second_key = "22345678-1234-1234-1234-123456789abc"
        with patch.dict(sys.modules, {"execution": types.SimpleNamespace(validate_prompt=validate)}), \
                patch.object(studio, "ltx25_native_plan", side_effect=replan) as builder:
            asyncio.run(controller.action(p, "animate", {"request_key": first_key}))
            first_run = copy.deepcopy(p["ltx25_run"])
            p["actions"][-1]["state"] = "complete"
            asyncio.run(controller.action(p, "animate", {"request_key": first_key}))
            self.assertEqual(p["ltx25_run"], first_run)
            self.assertEqual(builder.call_count, 1)
            asyncio.run(controller.action(p, "animate", {"request_key": second_key}))
            second_run = copy.deepcopy(p["ltx25_run"])
            self.assertNotEqual(first_run["namespace"], second_run["namespace"])
            self.assertNotEqual(first_run["plan"]["artifacts"]["pose"]["prefix"],
                                second_run["plan"]["artifacts"]["pose"]["prefix"])
            self.assertEqual(replan(p)["key"], second_run["plan"]["key"])
            p["actions"][-1]["state"] = "complete"
            asyncio.run(controller.action(p, "animate", {"request_key": first_key}))
            self.assertEqual(p["ltx25_run"], second_run)
            self.assertEqual(builder.call_count, 2)
        self.assertEqual(len(p["actions"]), 2)
        self.assertEqual(controller.server.prompt_queue.submitted, [])

    def test_graph_export_creates_namespace_only_in_unapproved_snapshot(self):
        p, plan = example()
        p.pop("ltx25_run")
        p["opening_approval"] = None
        original = copy.deepcopy(p)
        basis = plan["basis"]
        def replan(project):
            return ltx.build_plan(project, scenario=plan["scenario"], timeline=basis["timeline"],
                models=basis["models"], model_pins=basis["model_pins"], text_encoder_inputs=basis["encoder"],
                approval_key=p["approval"])
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(studio, "ltx25_native_plan", side_effect=replan), \
                patch.object(studio.folder_paths, "get_output_directory", return_value=directory, create=True), \
                patch.object(studio.folder_paths, "get_input_directory", return_value=directory):
            first, first_stage = studio.editable_graph(p, "animate")
            second, second_stage = studio.editable_graph(p, "animate")
        self.assertEqual(p, original)
        self.assertEqual((first_stage, second_stage), ("ltx25_text", "ltx25_text"))
        self.assertNotEqual(first["save_text"]["inputs"]["cache_key"], second["save_text"]["inputs"]["cache_key"])

    def test_masked_route_preserved_and_private_run_excluded_from_public_project(self):
        p, plan = example()
        self.assertTrue(studio.ltx25_scene_route(p, "restyle"))
        p["config"]["edit_area"] = "mask"
        self.assertFalse(studio.ltx25_scene_route(p, "background"))
        self.assertFalse(studio.ltx25_scene_route(p, "restyle"))
        public = studio.public_project(p)
        self.assertNotIn("ltx25_run", public)
        self.assertIn("ltx25_run", p)

    def test_verified_no_audio_selects_silent_even_if_review_has_silence_stream(self):
        p, plan = example()
        p["audio"] = None
        p["config"]["lip_sync"] = False
        p["approval"] = studio.prep_key(p)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.mp4").write_bytes(b"reviewed silent video")
            union = root / "union.safetensors"
            header = json.dumps({"__metadata__": {"reference_downscale_factor": "2"}}).encode()
            union.write_bytes(len(header).to_bytes(8, "little") + header)
            detector_roots = root / "custom"
            for relative in ("comfyui_controlnet_aux/ckpts/yzd-v/DWPose/yolox_l.onnx",
                    "comfyui_controlnet_aux/ckpts/hr16/DWPose-TorchScript-BatchSize5/dw-ll_ucoco_384_bs5.torchscript.pt"):
                path = detector_roots / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"detector")
            manifest = {"clip": {"frames": 48, "fps": 24, "start": 0, "has_audio": False}}
            container = types.SimpleNamespace(streams=types.SimpleNamespace(video=[types.SimpleNamespace(width=704, height=1280)]))
            class Context:
                def __enter__(self): return container
                def __exit__(self, *args): return None
            with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset", return_value=root / "source.mp4"), \
                    patch.object(package, "verify_review", return_value=(root, manifest), create=True), \
                    patch.object(studio.av, "open", return_value=Context()), \
                    patch.object(studio.folder_paths, "get_full_path", return_value=str(union)), \
                    patch.object(studio.folder_paths, "get_folder_paths", return_value=[str(detector_roots)], create=True):
                actual = studio.ltx25_native_plan(p)
                p["audio"] = {"file": "genj_studio/example/soundtrack.wav", "sha": "d" * 64}
                p["approval"] = studio.prep_key(p)
                manifest["clip"]["has_audio"] = True
                soundtrack = studio.ltx25_native_plan(p)
                self.assertEqual(soundtrack["scenario"], "original")
                self.assertEqual((soundtrack["generation_audio"], soundtrack["delivery_audio"]), ("zero", "selected_soundtrack"))
                self.assertEqual(soundtrack["phases"]["motion"]["pose"]["inputs"]["detect_face"], "enable")
                container.streams.audio = [types.SimpleNamespace()]
                with_original = studio.ltx25_native_plan(p)
                self.assertEqual(with_original["generation_audio"], "raw_original")
                self.assertEqual(with_original["phases"]["motion"]["original_audio"]["inputs"]["audio"], p["source"]["file"])
            self.assertEqual(actual["scenario"], "silent")
            self.assertNotIn("audio", actual["phases"]["decode"]["create_video"]["inputs"])

    def test_final_delivery_is_verified_and_collected_once(self):
        p, plan = example()
        controller = self.controller()
        enhancement = importlib.import_module(NAME + ".enhancement")
        with tempfile.TemporaryDirectory() as directory:
            output, input_root = self.roots(directory)
            with patch.object(studio.folder_paths, "get_output_directory", return_value=str(output), create=True), \
                    patch.object(studio.folder_paths, "get_input_directory", return_value=str(input_root)):
                for phase in ltx.PHASES[:-1]:
                    self.produce(controller, p, phase, output, input_root)
                graph = ltx.bind_phase(plan, "decode", p["ltx25_run"]["receipts"], output_directory=output, input_directory=input_root)
                action = {"id": "decode-prompt", "stage": "ltx25_decode", "graph": graph,
                          "ltx25_plan_key": plan["key"], "resolution": 1280, "quality": "fast", "state": "running"}
                p["actions"].append(action)
                prefix = Path(graph["save_video"]["inputs"]["filename_prefix"])
                path = output / prefix.parent / (prefix.name + "_00001_.mp4")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic final-video receipt")
                history = {"prompt": [0, action["id"], graph], "status": {"status_str": "success", "completed": True},
                           "outputs": {"save_video": {"images": [{"filename": path.name, "subfolder": str(prefix.parent), "type": "output"}]}}}
                actual = {"frames": 48, "fps": 24, "width": 704, "height": 1280, "audio_tracks": 1}
                with patch.object(studio, "ltx25_native_plan", return_value=plan), \
                        patch.object(enhancement, "inspect_video", return_value=actual) as inspector:
                    controller._collect_ltx25_phase(p, action, history)
                    controller._collect_ltx25_phase(p, action, history)
                self.assertEqual(len(p["results"]), 1)
                self.assertEqual(p["phase"], "done")
                self.assertEqual(inspector.call_args.kwargs, {"expected_frames": 48, "expected_width": 704,
                    "expected_height": 1280, "expected_fps": 24, "expected_audio_tracks": 1})

    def test_files_changing_during_successful_phase_are_not_accepted(self):
        p, plan = example()
        controller = self.controller()
        action = {"id": "text-prompt", "stage": "ltx25_text", "graph": plan["phases"]["text"], "ltx25_plan_key": plan["key"]}
        history = {"prompt": [0, action["id"], action["graph"]], "status": {"status_str": "success", "completed": True}}
        with patch.object(studio, "ltx25_native_plan", return_value={"key": "changed"}):
            with self.assertRaisesRegex(ValueError, "changed during this phase"):
                controller._collect_ltx25_phase(p, action, history)
        self.assertEqual(p["ltx25_run"]["receipts"], {})


if __name__ == "__main__":
    unittest.main()
