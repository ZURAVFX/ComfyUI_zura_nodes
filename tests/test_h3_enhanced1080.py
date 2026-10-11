"""H3 Enhanced 1080p routing and continuation safety; no inference is run."""
import hashlib
import importlib
import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import v2_bootstrap

NAME = "ComfyUI_zura_nodes.artist_studio"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[NAME] = package

studio = importlib.import_module(NAME + ".studio")
enhancement = importlib.import_module(NAME + ".enhancement")
h3 = importlib.import_module(NAME + ".h3")
artist_studio_package = sys.modules[NAME]
if not hasattr(artist_studio_package, "digest_file"):
    artist_studio_package.digest_file = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()


class VideoContainer:
    def __init__(self):
        self.streams = types.SimpleNamespace(video=[types.SimpleNamespace(width=720, height=1280)])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeQueue:
    def __init__(self, history=None, running=None, pending=None):
        self.history = history or {}
        self.running = running or []
        self.pending = pending or []

    def get_history(self, identity=None):
        if identity is None:
            return self.history
        return {identity: self.history[identity]} if identity in self.history else {}

    def get_current_queue_volatile(self):
        return self.running, self.pending


class EnhancedConfigAndCacheTests(unittest.TestCase):
    def test_h3_has_three_supported_delivery_choices_and_legacy_1920_stays_native(self):
        native = studio.clean_config({"engine": "h3", "resolution": 1920})
        enhanced = studio.clean_config({"engine": "h3", "resolution": 1920,
                                        "delivery_mode": "enhanced1080"})
        migrated = studio.clean_config({"engine": "h3", "resolution": 768,
                                        "delivery_mode": "enhanced1080"})
        other_engine = studio.clean_config({"engine": "local", "resolution": 1920,
                                            "delivery_mode": "enhanced1080"})
        self.assertEqual((native["resolution"], native["delivery_mode"]), (1920, "native"))
        self.assertEqual((enhanced["resolution"], enhanced["delivery_mode"]), (1920, "enhanced1080"))
        self.assertEqual((migrated["resolution"], migrated["delivery_mode"]), (1280, "native"))
        self.assertEqual(other_engine["delivery_mode"], "native")

    def test_enhanced_mode_reuses_only_the_same_720p_conditioning_key(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = {}
            for key in ("h3_text", "h3_video_vae", "h3_audio_vae"):
                path = Path(directory) / (key + ".safetensors")
                path.write_bytes(key.encode())
                paths[key] = path
            folders = {"qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors": "h3_text",
                       "minimax_h3_video_vae_int8_convrot.safetensors": "h3_video_vae",
                       "minimax_h3_audio_vae_fp32.safetensors": "h3_audio_vae"}
            get_model = lambda folder, name: str(paths[folders[name]])
            common = {"review": "shot_0123456789abcdef", "character": {"sha": "c" * 64},
                      "opening_key": "d" * 64,
                      "config": {"size": 512, "scope": "person", "prompt": "", "pitch": False,
                                 "audio_start": 0, "lip_sync": False}}
            enhanced = {**common, "config": {**common["config"], "resolution": 1920,
                                                "delivery_mode": "enhanced1080"}}
            base720 = {**common, "config": {**common["config"], "resolution": 1280,
                                              "delivery_mode": "native"}}
            native1080 = {**common, "config": {**common["config"], "resolution": 1920,
                                                "delivery_mode": "native"}}
            with patch("folder_paths.get_full_path", side_effect=get_model):
                self.assertEqual(h3.cache_key(enhanced), h3.cache_key(base720))
                self.assertNotEqual(h3.cache_key(enhanced), h3.cache_key(native1080))

    def test_diffusion_canvas_and_encoded_delivery_raster_are_recorded_separately(self):
        self.assertEqual(enhancement.h3_dimensions(720, 1280, 1280),
                         ((704, 1280), (720, 1280)))
        self.assertEqual(enhancement.h3_dimensions(1080, 1920, 1920),
                         ((1088, 1920), (1080, 1920)))

    def test_readiness_exposes_the_model_setup_command(self):
        folder_paths = types.ModuleType("folder_paths")
        folder_paths.get_full_path = lambda _folder, _name: None
        nodes = types.ModuleType("nodes")
        nodes.NODE_CLASS_MAPPINGS = {name: object() for name in enhancement.NATIVE_NODES}
        with patch.dict(sys.modules, {"folder_paths": folder_paths, "nodes": nodes}):
            status = enhancement.readiness()
        self.assertFalse(status["ready"])
        self.assertFalse(status["model_ready"])
        self.assertEqual(status["setup_command"], enhancement.SETUP_COMMAND)


class EnhancementFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "output"
        self.output.mkdir()
        self.input = Path(self.temp.name) / "input.mp4"
        self.input.write_bytes(b"source fixture")
        self.base_path = self.output / "genj" / "studio_intermediate" / "base.mp4"
        self.base_path.parent.mkdir(parents=True)
        self.base_path.write_bytes(b"720p base fixture")
        self.project = {
            "id": "a" * 32,
            "review": "shot_0123456789abcdef",
            "source": {"file": str(self.input), "sha": "b" * 64},
            "character": {"file": str(self.input), "sha": "c" * 64},
            "opening_input": {"file": str(self.input), "sha": "d" * 64},
            "prepared_key": "e" * 64,
            "opening_key": "d" * 64,
            "audio": None,
            "config": {"engine": "h3", "delivery_mode": "enhanced1080", "resolution": 1920,
                       "size": 512, "scope": "person", "prompt": "", "pitch": False,
                       "audio_start": 0, "lip_sync": False, "quality": "fast"},
        }
        self.project["config"] = studio.clean_config(self.project["config"])
        self.base = {
            "asset": {"filename": "base.mp4", "subfolder": "genj/studio_intermediate", "type": "output"},
            "sha256": hashlib.sha256(self.base_path.read_bytes()).hexdigest(),
            "generation_key": enhancement.generation_key(self.project),
            "generation_raster": {"width": 704, "height": 1280},
            "output_raster": {"width": 720, "height": 1280},
            "frames": 5, "audio_mode": "original", "audio_tracks": 1,
        }

    def patch_graph_dependencies(self):
        return (
            patch("folder_paths.get_output_directory", return_value=str(self.output), create=True),
            patch.object(enhancement, "readiness", return_value={"ready": True, "missing_nodes": [],
                                                                   "model_ready": True}),
            patch.object(studio, "assert_approved"),
            patch.object(studio, "check_asset", side_effect=lambda asset: Path(asset["file"])),
            patch.object(artist_studio_package, "digest_file", side_effect=lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()),
            patch.object(enhancement.av, "open", side_effect=lambda *args, **kwargs: VideoContainer()),
            patch.object(enhancement, "inspect_video", side_effect=self.fake_inspect),
        )

    @staticmethod
    def fake_inspect(path, **expected):
        return {"width": expected.get("expected_width") or 1280,
                "height": expected.get("expected_height") or 720,
                "frames": expected.get("expected_frames") or 5,
                "fps": expected.get("expected_fps") or 24,
                "audio_tracks": expected.get("expected_audio_tracks") or 1}

    def build_graph(self, project=None, base=None, run_id="test-run"):
        contexts = self.patch_graph_dependencies()
        for context in contexts:
            context.start()
        self.addCleanup(lambda: [context.stop() for context in reversed(contexts)])
        return enhancement.build_graph(project or self.project, base or self.base, run_id=run_id)


class EnhancementGraphTests(EnhancementFixture):
    def test_graph_is_the_tested_one_frame_native_vhs_upscale_with_direct_review_audio_restore(self):
        graph = self.build_graph()
        self.assertEqual(graph["h3_enhance_manager"]["inputs"]["frames_per_batch"], 1)
        self.assertEqual(graph["h3_enhance_model"]["inputs"]["model_name"], enhancement.UPSCALE_MODEL)
        self.assertEqual(graph["h3_enhance_lanczos"]["inputs"]["upscale_method"], "lanczos")
        self.assertEqual((graph["h3_enhance_lanczos"]["inputs"]["width"],
                          graph["h3_enhance_lanczos"]["inputs"]["height"]), (1080, 1920))
        self.assertNotIn("audio", graph["h3_enhance_vhs"]["inputs"])
        self.assertEqual(graph["h3_enhance_export"]["inputs"]["clip_details"], ["h3_enhance_review", 3])
        self.assertEqual(graph["h3_enhance_export"]["inputs"]["output_subfolder"], "final")
        self.assertEqual(graph["h3_enhance_review"]["inputs"]["render_long_edge"], 0)
        self.assertEqual(graph["h3_enhance_export"]["inputs"]["take_name"],
                         "studio_aaaaaaaa_h3_enhanced_test-run")
        self.assertFalse({"UNETLoader", "SamplerCustomAdvanced", "VAEEncode",
                          "MiniMaxH3ReferenceToVideo"} &
                         {node["class_type"] for node in graph.values()})

    def test_missing_upscaler_model_has_a_specific_readiness_error(self):
        contexts = self.patch_graph_dependencies()
        for context in contexts:
            context.start()
        self.addCleanup(lambda: [context.stop() for context in reversed(contexts)])
        with patch.object(enhancement, "readiness", return_value={"ready": False,
                                                                    "missing_nodes": [],
                                                                    "model_ready": False}):
            with self.assertRaisesRegex(ValueError, enhancement.UPSCALE_MODEL + ".*" + enhancement.SETUP_COMMAND):
                enhancement.build_graph(self.project, self.base, run_id="test")

    def test_incomplete_vhs_filenames_block_finalizer_until_the_closed_video_exists(self):
        class ExecutionBlocker:
            def __init__(self, value): self.value = value

        class InputImpl:
            @staticmethod
            def VideoFromFile(path): return ("video-from-file", path)

        comfy_api = types.ModuleType("comfy_api")
        comfy_api.__path__ = []
        latest = types.ModuleType("comfy_api.latest")
        latest.InputImpl = InputImpl
        comfy_execution = types.ModuleType("comfy_execution")
        comfy_execution.__path__ = []
        graph_utils = types.ModuleType("comfy_execution.graph_utils")
        graph_utils.ExecutionBlocker = ExecutionBlocker
        modules = {"comfy_api": comfy_api, "comfy_api.latest": latest,
                   "comfy_execution": comfy_execution, "comfy_execution.graph_utils": graph_utils}
        prefix = "genj/studio_h3_enhance/project/run"
        bridge = enhancement.GenjVHSVideoFromFilenames()
        with patch.dict(sys.modules, modules), \
             patch("folder_paths.get_output_directory", return_value=str(self.output), create=True):
            pending = bridge.load((True, []), prefix, 5, 1080, 1920)[0]
            self.assertIsInstance(pending, ExecutionBlocker)
            closed = self.output / "genj" / "studio_h3_enhance" / "project" / "run_00001.mp4"
            closed.parent.mkdir(parents=True)
            closed.write_bytes(b"closed video")
            with patch.object(enhancement, "inspect_video") as inspect:
                completed = bridge.load((True, [str(closed)]), prefix, 5, 1080, 1920)[0]
            self.assertEqual(completed, ("video-from-file", str(closed)))
            inspect.assert_called_once_with(closed, expected_frames=5, expected_width=1080,
                                            expected_height=1920, expected_fps=24,
                                            expected_audio_tracks=0)

            sibling = closed.with_name("runaway_00001.mp4")
            sibling.write_bytes(b"sibling prefix")
            with self.assertRaisesRegex(ValueError, "unexpected output path"):
                bridge.load((True, [str(sibling)]), prefix, 5, 1080, 1920)

            outside = self.output.parent / "outside" / "run_00001.mp4"
            outside.parent.mkdir(parents=True)
            outside.write_bytes(b"outside output folder")
            with self.assertRaisesRegex(ValueError, "outside the output folder"):
                bridge.load((True, [str(outside)]), prefix, 5, 1080, 1920)

            with self.assertRaisesRegex(ValueError, "prefix is invalid"):
                bridge.load((True, []), "../outside/run", 5, 1080, 1920)

    def test_wrong_base_key_or_folder_is_rejected(self):
        wrong_key = {**self.base, "generation_key": "0" * 64}
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            self.build_graph(base=wrong_key)
        wrong_folder = {**self.base, "asset": {**self.base["asset"], "subfolder": "genj/final"}}
        with self.assertRaisesRegex(ValueError, "unexpected output provenance"):
            self.build_graph(base=wrong_folder)

    def test_original_selected_and_silent_audio_modes_are_unambiguous(self):
        self.assertEqual(enhancement.audio_mode({"audio": {"sha": "f" * 64}}, {"has_audio": True}),
                         "selected_reference")
        self.assertEqual(enhancement.audio_mode({"audio": None}, {"has_audio": True}), "original")
        self.assertEqual(enhancement.audio_mode({"audio": None}, {"has_audio": False}), "silent")
        project = {**self.project, "audio": {"sha": "f" * 64, "file": str(self.input)}}
        graph = self.build_graph(project=project, base={**self.base, "generation_key": enhancement.generation_key(project),
                                                       "audio_mode": "selected_reference", "audio_tracks": 1})
        self.assertEqual(graph["h3_enhance_export"]["inputs"]["clip_details"], ["h3_enhance_review", 3])
        self.assertNotIn("audio", graph["h3_enhance_vhs"]["inputs"])

    def test_studio_graph_export_matches_the_same_api_builder(self):
        graph = self.build_graph(run_id="graph")
        with patch.object(enhancement, "readiness", return_value={"ready": True, "missing_nodes": [],
                                                                   "model_ready": True}), \
             patch.object(studio, "assert_approved"), \
             patch.object(studio, "check_asset", side_effect=lambda asset: Path(asset["file"])), \
             patch("folder_paths.get_output_directory", return_value=str(self.output), create=True), \
             patch.object(artist_studio_package, "digest_file", side_effect=lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()), \
             patch.object(enhancement.av, "open", side_effect=lambda *args, **kwargs: VideoContainer()), \
             patch.object(enhancement, "inspect_video", side_effect=self.fake_inspect):
            exported, stage = studio.editable_graph({**self.project, "h3_enhancement_base": self.base}, "h3_enhance")
        self.assertEqual(stage, "h3_enhance")
        self.assertEqual(exported, graph)


def tagged_record(prompt_id, action_id, state="success", output=None):
    return {"prompt": (0, prompt_id, {}, {"zura_studio_action": action_id}),
            "status": {"status_str": state}, "outputs": output or {}}


class ContinuationCollectorTests(EnhancementFixture):
    def setUp(self):
        super().setUp()
        self.final = self.output / "genj" / "final" / "studio_final_00001.mp4"
        self.final.parent.mkdir(parents=True)
        self.final.write_bytes(b"final fixture")
        self.action_id = "11111111-1111-4111-8111-111111111111"
        self.action = {"id": self.action_id, "stage": "h3_enhance", "state": "queued",
                       "expected_frames": 3, "generation_resolution": 1280,
                       "generation_raster": {"width": 704, "height": 1280},
                       "base_output_raster": {"width": 720, "height": 1280},
                       "output_raster": {"width": 1080, "height": 1920},
                       "take_name": "studio_final", "duration": 0.125, "quality": "fast",
                       "h3_preset": "take_fast"}
        self.project_record = {"id": "f" * 32, "phase": "working", "error": None,
                              "config": {"engine": "h3", "delivery_mode": "enhanced1080"},
                              "actions": [self.action], "results": [],
                              "h3_enhancement_base": {"audio_mode": "original"}}
        self.queue = FakeQueue()
        self.obj = studio.Studio.__new__(studio.Studio)
        self.obj.server = types.SimpleNamespace(prompt_queue=self.queue)
        self.obj.store = studio.Store(self.temp.name)

    def family(self, count=3, *, error_at=None, final_asset=None):
        records = {}
        asset = final_asset or {"filename": self.final.name, "subfolder": "genj/final", "type": "output"}
        for index in range(count):
            outputs = {}
            if index == count - 1 and final_asset is not False:
                outputs = {"h3_enhance_export": {"gifs": [asset]}}
            status = "error" if index == error_at else "success"
            records[f"child-{index}"] = tagged_record(f"child-{index}", self.action_id, status, outputs)
        return records

    def patch_collector(self):
        return patch.object(enhancement, "inspect_video", return_value={"width": 1080, "height": 1920,
                                                                          "frames": 3, "fps": 24,
                                                                          "audio_tracks": 1})

    def test_first_successful_prompt_is_not_a_finished_result_while_vhs_child_is_pending(self):
        self.queue.history = {"child-0": tagged_record("child-0", self.action_id)}
        self.queue.pending = [(1, "child-1", {}, {"zura_studio_action": self.action_id}, [], {})]
        result = self.obj._collect_h3_enhancement(self.project_record, self.action)
        self.assertEqual(result["phase"], "working")
        self.assertEqual(self.action["state"], "queued")
        self.assertEqual(self.project_record["results"], [])

    def test_full_family_records_one_result_once_with_delivered_raster(self):
        self.queue.history = self.family()
        with patch("folder_paths.get_output_directory", return_value=str(self.output), create=True), self.patch_collector():
            self.obj._collect_h3_enhancement(self.project_record, self.action)
            self.obj._collect_h3_enhancement(self.project_record, self.action)
        self.assertEqual(self.project_record["phase"], "done")
        self.assertEqual(len(self.project_record["results"]), 1)
        result = self.project_record["results"][0]
        self.assertEqual(result["label"], "Enhanced 1080p")
        self.assertEqual(result["output_raster"]["width"], 1080)
        self.assertEqual(result["generation_resolution"], 1280)
        self.assertEqual(result["audio_mode"], "original")

    def test_expected_120_frame_vhs_family_records_one_result(self):
        self.action["expected_frames"] = 120
        self.queue.history = self.family(count=120)
        with patch("folder_paths.get_output_directory", return_value=str(self.output), create=True), \
             patch.object(enhancement, "inspect_video", return_value={"width": 1080, "height": 1920,
                                                                         "frames": 120, "fps": 24,
                                                                         "audio_tracks": 1}):
            self.obj._collect_h3_enhancement(self.project_record, self.action)
        self.assertEqual(len(self.project_record["results"]), 1)
        self.assertEqual(self.project_record["results"][0]["output_raster"]["frames"], 120)

    def test_child_error_fails_without_replay(self):
        self.queue.history = self.family(error_at=1)
        self.obj._collect_h3_enhancement(self.project_record, self.action)
        self.assertEqual(self.action["state"], "failed")
        self.assertEqual(self.project_record["phase"], "error")
        self.assertFalse(self.queue.pending)
        self.assertEqual(self.project_record["results"], [])

    def test_absent_child_is_interrupted_then_fails_conservatively_without_replay(self):
        self.queue.history = {"child-0": tagged_record("child-0", self.action_id)}
        self.action["expected_frames"] = 2
        self.action["absent_since"] = 1
        self.obj._collect_h3_enhancement(self.project_record, self.action)
        self.assertEqual(self.action["state"], "failed")
        self.assertEqual(self.project_record["phase"], "error")
        self.assertFalse(self.queue.pending)

    def test_wrong_final_output_provenance_fails_instead_of_recording(self):
        self.queue.history = self.family(final_asset={"filename": "wrong.mp4",
                                                       "subfolder": "genj/studio_intermediate",
                                                       "type": "output"})
        with patch("folder_paths.get_output_directory", return_value=str(self.output), create=True):
            result = self.obj.collect(self.project_record)
        self.assertEqual(result["phase"], "error")
        self.assertEqual(result["results"], [])


class H3BaseRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.action_id = "22222222-2222-4222-8222-222222222222"
        self.project = {
            "id": "c" * 32, "phase": "working", "review": "shot_0123456789abcdef",
            "source": {"sha": "a" * 64}, "character": {"sha": "b" * 64},
            "prepared_key": "c" * 64, "opening_key": "d" * 64, "audio": None,
            "config": {"engine": "h3", "delivery_mode": "enhanced1080", "resolution": 1920},
        }
        self.action = {"id": self.action_id, "stage": "h3", "state": "complete",
                       "delivery_mode": "enhanced1080", "next_stage": "wan_cleanup",
                       "studio_action_tag": self.action_id, "server_address": "127.0.0.1:8188"}
        self.project["h3_enhancement_base"] = {
            "generation_key": enhancement.generation_key(self.project)}
        self.project["actions"] = [self.action]
        self.obj = studio.Studio.__new__(studio.Studio)
        self.obj.server_address = "127.0.0.1:8188"
        self.obj.resume_scheduled = set()
        self.obj.store = types.SimpleNamespace(save=Mock())
        self.obj.resume_text = AsyncMock()

    async def test_restart_recovers_only_the_tagged_enhanced_h3_handoff_once(self):
        self.obj._collect(self.project)
        self.obj._collect(self.project)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.obj.resume_text.assert_awaited_once_with(self.project["id"], self.action_id)

    async def test_completed_native_h3_does_not_autostart_enhancement_or_another_h3(self):
        self.action.update(delivery_mode="native", next_stage=None)
        self.action.pop("studio_action_tag")
        self.project["config"]["delivery_mode"] = "native"
        self.project.pop("h3_enhancement_base")
        self.obj._collect(self.project)
        await asyncio.sleep(0)
        self.obj.resume_text.assert_not_awaited()

    async def test_enhanced_h3_from_another_server_is_not_resumed(self):
        self.action["server_address"] = "127.0.0.1:8288"
        self.obj._collect(self.project)
        await asyncio.sleep(0)
        self.obj.resume_text.assert_not_awaited()

    async def test_wrong_next_stage_or_tag_is_failed_without_resuming(self):
        for field, value in (("next_stage", "h3"), ("studio_action_tag", "wrong")):
            with self.subTest(field=field):
                self.action.update(state="complete", next_stage="wan_cleanup",
                                   studio_action_tag=self.action_id)
                self.action[field] = value
                self.project["phase"] = "working"
                self.obj._collect(self.project)
                self.assertEqual(self.action["state"], "failed")
                self.assertEqual(self.project["phase"], "error")
                self.assertFalse(self.obj.resume_scheduled)


if __name__ == "__main__":
    unittest.main()
