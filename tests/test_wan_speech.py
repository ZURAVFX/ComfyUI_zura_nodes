"""Wan speech preparation contracts. Synthetic CPU assets; no downloads or GPU."""
import ast
import contextlib
import copy
import importlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import v2_bootstrap
import numpy as np
import torch
import torch.nn.functional as F

NAME = "ComfyUI_zura_nodes.artist_studio"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[NAME] = package
package = sys.modules[NAME]
speech = importlib.import_module(NAME + ".wan_speech")
wan = importlib.import_module(NAME + ".wan")
studio = importlib.import_module(NAME + ".studio")
adapters = importlib.import_module("ComfyUI_zura_nodes.wan_artist")
setup = importlib.import_module("setup_wan_speech")


def native_fit_audio():
    # Test the actual local AUDIO fitter without initialising Comfy's extension.
    tree = ast.parse((v2_bootstrap.ROOT / "artist_studio" / "__init__.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "fit_audio")
    namespace = {"torch": torch, "F": F}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "fit_audio", "exec"), namespace)
    return namespace["fit_audio"]


def pose(width, height, confidence=1, leading_foot=False):
    points = np.column_stack((np.linspace(.3, .7, 68), np.linspace(.2, .5, 68), np.full(68, confidence)))
    if leading_foot:
        points = np.vstack(([-1, -1, 0], points))
    return {"pose_metas_original": [{"width": width, "height": height, "keypoints_face": points}]}


class GuideTests(unittest.TestCase):
    def setUp(self):
        import soundfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.model_paths = {}
        required = {}
        for identity, (folder, name, loader, field, _) in speech.MODELS.items():
            path = self.base / "models" / folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(identity.encode())
            self.model_paths[(folder, name)] = str(path)
            required.setdefault(loader, {})[field] = ([name],)
        required["WanVideoModelLoader"].update(base_precision=(["fp16", "bf16"],), quantization=(["disabled"],),
                                             rms_norm_function=(["default"],))
        required["WanVideoVAELoader"].update(use_cpu_cache=("BOOLEAN",), verbose=("BOOLEAN",))
        classes = {}
        for name in speech.NATIVE_NODES:
            spec = {"required": required.get(name, {})}
            if name == "WanVideoModelLoader":
                spec["optional"] = {"attention_mode": (["sdpa"],)}
            if name == "WanVideoImageToVideoMultiTalk":
                spec["optional"] = {"mode": (["infinitetalk", "auto"],)}
            classes[name] = type(name, (), {"INPUT_TYPES": classmethod(lambda cls, value=spec: value)})
        self.classes = classes
        self.project = {"id": "a" * 32, "review": "shot_synthetic", "approval": "synthetic-approved-preparation",
            "audio": {"file": "voice.wav", "sha": ""},
            "opening_key": "approved", "opening_approval": "approved",
            "opening_input": {"file": "opening.png", "sha": "opening"},
            "character": {"file": "character.png", "sha": "character"},
            "config": {"engine": "wan", "lip_sync": True, "audio_start": .1, "seed": 123, "performer": -1,
                       "resolution": 720, "scope": "person", "quality": "fast", "background": "keep",
                       "prompt": "", "remove_text": False, "refine_lips": False}}
        self.wave = torch.cat((torch.zeros(2400), torch.linspace(-.25, .25, 2400)))[None]
        soundfile.write(str(self.base / "voice.wav"), self.wave.numpy().T, 24000, subtype="FLOAT")
        (self.base / "opening.png").write_bytes(b"synthetic approved image")
        self.project["audio"]["sha"] = speech.digest(self.base / "voice.wav")
        self.project["opening_input"]["sha"] = speech.digest(self.base / "opening.png")
        self.manifest = {"clip": {"frames": 120, "fps": 24, "start": .25, "source_hash": "source"},
                         "files": {"mask.mp4": "approved-performer-mask"}}
        native_audio = types.ModuleType("comfy_extras.nodes_audio")
        native_audio.load = lambda filename: (self.wave.clone(), 24000)
        fake_nodes = types.ModuleType("nodes")
        fake_nodes.NODE_CLASS_MAPPINGS = classes
        self.queue = types.SimpleNamespace(get_current_queue_volatile=lambda: ([], []), get_history=lambda identity: {})
        fake_server = types.ModuleType("server")
        fake_server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(prompt_queue=self.queue))
        self.enter(patch.dict(sys.modules, {"nodes": fake_nodes, "comfy_extras.nodes_audio": native_audio, "server": fake_server}))
        self.enter(patch.object(package, "verify_review", return_value=(self.base, self.manifest), create=True))
        self.enter(patch.object(package, "fit_audio", native_fit_audio(), create=True))
        self.enter(patch.object(studio, "assert_approved"))
        self.enter(patch.object(studio, "check_asset", side_effect=lambda asset: self.base / asset["file"]))
        import folder_paths
        self.enter(patch.object(folder_paths, "get_output_directory", return_value=str(self.base / "output"), create=True))
        self.enter(patch.object(folder_paths, "get_full_path", side_effect=lambda folder, name: self.model_paths.get((folder, name))))
        self.enter(patch.object(speech.shutil, "which", return_value="synthetic-tool"))

    def enter(self, context):
        value = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        return value

    def test_readiness_checks_optional_options_and_missing_pack_explicitly(self):
        self.assertTrue(speech.readiness()["ready"])
        del self.classes["WanVideoSampler"]
        state = speech.readiness()
        self.assertFalse(state["ready"])
        self.assertIn("WanVideoSampler", state["missing_nodes"])
        self.assertTrue(state["node_packs"])
        with self.assertRaisesRegex(ValueError, "Setup_Wan_Speech"):
            speech.build_graph(self.project)

    def test_upstream_misspelling_is_compatible_but_not_ambiguous(self):
        folder, canonical, loader, field, aliases = speech.MODELS["speech"]
        path = self.model_paths.pop((folder, canonical))
        self.model_paths[(folder, aliases[0])] = path
        self.classes[loader].INPUT_TYPES = classmethod(lambda cls: {"required": {field: (["upstream/" + aliases[0]],)}})
        self.model_paths[(folder, "upstream/" + aliases[0])] = path
        self.assertEqual(speech._resolve_model("speech")[0], "upstream/" + aliases[0])
        self.classes[loader].INPUT_TYPES = classmethod(lambda cls: {"required": {field: ([aliases[0], "upstream/" + aliases[0]],)}})
        with self.assertRaisesRegex(ValueError, "unambiguous"):
            speech._resolve_model("speech")

    def test_old_native_loader_defaults_report_setup_before_rendering(self):
        schema = copy.deepcopy(self.classes["WanVideoVAELoader"].INPUT_TYPES())
        del schema["required"]["use_cpu_cache"]
        self.classes["WanVideoVAELoader"].INPUT_TYPES = classmethod(lambda cls: schema)
        state = speech.readiness()
        self.assertFalse(state["ready"])
        self.assertIn("WanVideoVAELoader.use_cpu_cache", state["unsupported_options"])
        with self.assertRaisesRegex(ValueError, "Setup_Wan_Speech"):
            speech.build_graph(self.project)

    def test_audio_keeps_rate_channels_silence_and_selected_samples(self):
        selected = speech._selected_audio(self.project, speech._timeline(self.project))
        expected = torch.zeros(1, 1, 120000)
        expected[..., :2400] = self.wave[:, 2400:]
        self.assertEqual(selected, speech.audio_signature({"waveform": expected, "sample_rate": 24000}))
        self.assertEqual(selected["samples"], 120000)
        self.project["config"]["audio_start"] = 0
        leading = speech._selected_audio(self.project, speech._timeline(self.project))
        expected = torch.zeros(1, 1, 120000)
        expected[..., :4800] = self.wave
        self.assertEqual(leading, speech.audio_signature({"waveform": expected, "sample_rate": 24000}))
        for bad in (float("nan"), -.1, .2):
            self.project["config"]["audio_start"] = bad
            with self.assertRaises(ValueError):
                speech.guide_key(self.project)

    def test_key_tracks_approval_audio_seed_crop_source_and_model_not_final_quality(self):
        initial = speech.guide_key(self.project)
        for field, value in (("resolution", 1080), ("quality", "detailed")):
            self.project["config"][field] = value
            self.assertEqual(initial, speech.guide_key(self.project))
        for container, field, value in ((self.project["config"], "seed", 124),
                                        (self.project["config"], "audio_start", 0),
                                        (self.project["opening_input"], "sha", "new-opening"),
                                        (self.project, "approval", "changed-preparation-approval"),
                                        (self.manifest["files"], "mask.mp4", "other-mask"),
                                        (self.manifest["clip"], "frames", 119)):
            original = container[field]
            container[field] = value
            self.assertNotEqual(initial, speech.guide_key(self.project))
            container[field] = original
        path = Path(self.model_paths[(speech.MODELS["base"][0], speech.MODELS["base"][1])])
        path.write_bytes(b"changed model")
        self.assertNotEqual(initial, speech.guide_key(self.project))

    def test_fractional_timeline_pads_driver_only_and_uses_dedicated_wan21_stack(self):
        self.manifest["clip"]["frames"] = 61
        graph = speech.build_graph(self.project)
        self.assertEqual(graph["ws_trim"]["inputs"]["num_frames"], 64)
        self.assertEqual(graph["ws_audio_features"]["inputs"]["num_frames"], 81)
        self.assertAlmostEqual(graph["ws_driver_silence"]["inputs"]["duration"], 81 / 25 - 61 / 24 + .04)
        self.assertEqual(graph["ws_export"]["inputs"]["audio"], ["ws_components", 1])
        self.assertEqual(graph["ws_export"]["inputs"]["frame_rate"], 25)
        self.assertFalse(graph["ws_export"]["inputs"]["trim_to_audio"])
        self.assertFalse(graph["ws_export"]["inputs"]["save_metadata"])
        self.assertEqual(graph["ws_model"]["inputs"]["base_precision"], "fp16")
        self.assertEqual(graph["ws_model"]["inputs"]["attention_mode"], "sdpa")
        self.assertFalse(graph["ws_lora"]["inputs"]["merge_loras"])
        self.assertEqual(graph["ws_swap"]["inputs"]["blocks_to_swap"], 32)
        self.assertTrue(graph["ws_model"]["inputs"]["model"].startswith("Wan2_1-I2V"))
        self.assertNotIn("Wan2_2", json.dumps(graph))
        self.assertIn("ZuraWanSpeechSaveGuide", adapters.NODE_CLASS_MAPPINGS)

    def test_graph_provenance_survives_native_ids_and_lossless_hand_off(self):
        graph = speech.build_graph(self.project)
        expected = speech.graph_signature(graph, "ws_export")
        renamed = {}
        names = {name: str(index + 101) for index, name in enumerate(graph)}
        for name, node in graph.items():
            node = copy.deepcopy(node)
            for field, value in node["inputs"].items():
                if isinstance(value, list) and len(value) == 2 and value[0] in names:
                    node["inputs"][field] = [names[value[0]], value[1]]
            renamed[names[name]] = node
        self.assertEqual(expected, speech.graph_signature(renamed, names["ws_export"]))
        graph["packet"] = {"class_type": "ZuraStudioSignals", "inputs": {"keys": '["clean_audio"]', "value_0": ["ws_components", 1]}}
        graph["read"] = {"class_type": "ZuraStudioReadSignal", "inputs": {"stage_data": ["packet", 0], "key": "clean_audio"}}
        graph["ws_export"]["inputs"]["audio"] = ["read", 0]
        self.assertEqual(expected, speech.graph_signature(graph, "ws_export"))
        graph["ws_sample"]["inputs"]["seed"] += 1
        self.assertNotEqual(expected, speech.graph_signature(graph, "ws_export"))

    def test_graph_provenance_accepts_lossless_json_and_comfy_float_coercion(self):
        graph = speech.build_graph(self.project)
        expected = speech.graph_signature(graph, "ws_export")
        # JS JSON.stringify emits 0 for 0.0; native validation casts it to FLOAT.
        graph["ws_shot"]["inputs"]["preview_seconds"] = 0
        graph["ws_sample"]["inputs"]["cfg"] = 1
        self.assertEqual(expected, speech.graph_signature(graph, "ws_export"))
        graph["ws_shot"]["inputs"]["preview_seconds"] = 0.0
        graph["ws_sample"]["inputs"]["cfg"] = 1.0
        self.assertEqual(expected, speech.graph_signature(graph, "ws_export"))
        graph["ws_sample"]["inputs"]["cfg"] = 1.001
        self.assertNotEqual(expected, speech.graph_signature(graph, "ws_export"))

    def artifact(self, graph, frames=None, fps=25):
        import av
        from fractions import Fraction
        data = json.loads(graph["ws_save"]["inputs"]["recipe_json"])["key_data"]
        key = graph["ws_save"]["inputs"]["guide_key"]
        path = speech._root() / (key + "_00001-audio.mp4")
        path.parent.mkdir(parents=True, exist_ok=True)
        with av.open(str(path), "w") as container:
            stream = container.add_stream("libx264", rate=fps)
            stream.width, stream.height, stream.pix_fmt = 480, 640, "yuv420p"
            stream.options = {"preset": "ultrafast", "crf": "28"}
            frame_data = np.full((640, 480, 3), 128, np.uint8)
            for index in range(frames or data["source"]["guide_frames"]):
                frame = av.VideoFrame.from_ndarray(frame_data, format="rgb24")
                frame.pts, frame.time_base = index, Fraction(1, fps)
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        return path

    def crop_metadata(self, key):
        return {"recipe": speech.CROP_RECIPE, "guide_key": key, "crop_xywh": [100, 50, 180, 240],
            "opening_size": [400, 800], "source_mask_overlap": 1, "opening_mask_overlap": 1,
            "source_confidence": .95, "opening_confidence": .95}

    def save_and_history(self, graph_view=False):
        # Short real synthetic output; its timeline is still exact24 ->25fps.
        self.manifest["clip"]["frames"] = 24
        graph = speech.build_graph(self.project)
        path = self.artifact(graph)
        fields = graph["ws_save"]["inputs"]
        key = fields["guide_key"]
        if graph_view:
            names = ("filenames", "crop_metadata", "selected_audio")
            graph["handoff"] = {"class_type": "ZuraStudioSignals", "inputs": {
                "keys": json.dumps(names), **{"value_" + str(i): fields[name] for i, name in enumerate(names)}}}
            for name in names:
                graph["read_" + name] = {"class_type": "ZuraStudioReadSignal", "inputs": {
                    "stage_data": ["handoff", 0], "key": name}}
                fields[name] = ["read_" + name, 0]
        self.queue.get_current_queue_volatile = lambda: ([(1, "synthetic-job", graph, {}, ["ws_save"])], [])
        audio = torch.zeros(1, 1, 24000)
        audio[..., :2400] = self.wave[:, 2400:]
        silent = path.with_name(path.name.replace("-audio", ""))
        silent.write_bytes(b"native silent intermediate")
        result = speech.save_pending((True, [str(silent), str(path)]), json.dumps(self.crop_metadata(key)),
            {"waveform": audio, "sample_rate": 24000}, key, fields["recipe_json"], graph, "ws_save")
        self.assertEqual(result["result"], (key,))
        history = {"prompt": [1, "synthetic-job", graph, {}, ["ws_save"]], "status": {"status_str": "success", "completed": True},
            "outputs": {"ws_export": {"gifs": [{"filename": path.name, "subfolder": "genj/wan_speech_guides", "type": "output"}]}}}
        return graph, path, history

    def test_native_save_is_pending_until_successful_history_promotes_it(self):
        graph, path, history = self.save_and_history()
        self.assertFalse(speech.guide_ready(self.project))
        failed = copy.deepcopy(history)
        failed["status"]["status_str"] = "error"
        with self.assertRaisesRegex(ValueError, "successfully"):
            speech.record_guide(self.project, failed)
        self.queue.get_history = lambda identity: {"synthetic-job": history}
        self.assertTrue(speech.guide_ready(self.project))
        record = speech.load_guide(self.project)
        self.assertEqual(record["state"], "complete")
        self.assertEqual(record["path"], str(path.resolve()))
        self.assertEqual(record["video"]["frames"], 25)
        path.write_bytes(b"changed-video")
        self.assertFalse(speech.guide_ready(self.project))

    def test_internal_comfy_history_tuple_promotes_the_completed_guide(self):
        graph, path, history = self.save_and_history()
        history['prompt'] = tuple(history['prompt'])
        self.queue.get_history = lambda identity: {'synthetic-job': history}
        self.assertTrue(speech.guide_ready(self.project))
        self.assertEqual(speech.load_guide(self.project)['prompt_id'], 'synthetic-job')

    def test_graph_view_save_hand_off_promotes_only_its_successful_native_history(self):
        graph, path, history = self.save_and_history(graph_view=True)
        history["prompt"] = tuple(history["prompt"])
        self.assertFalse(speech.guide_ready(self.project))
        self.queue.get_history = lambda identity: {"synthetic-job": history}
        self.assertTrue(speech.guide_ready(self.project))
        self.assertEqual(speech.load_guide(self.project)["path"], str(path.resolve()))

    def test_failed_edited_foreign_and_audio_mismatched_jobs_cannot_warm_studio(self):
        graph, path, history = self.save_and_history()
        altered = copy.deepcopy(history)
        altered["prompt"][2]["ws_sample"]["inputs"]["steps"] = 4
        with self.assertRaisesRegex(ValueError, "recipe changed"):
            speech.record_guide(self.project, altered)
        altered = copy.deepcopy(history)
        altered["prompt"][1] = "foreign-job"
        with self.assertRaisesRegex(ValueError, "does not belong"):
            speech.record_guide(self.project, altered)
        altered = copy.deepcopy(history)
        altered["outputs"] = {}
        with self.assertRaisesRegex(ValueError, "did not export"):
            speech.record_guide(self.project, altered)
        fields = graph["ws_save"]["inputs"]
        audio = {"waveform": torch.zeros(1, 1, 24000), "sample_rate": 24000}
        with self.assertRaisesRegex(ValueError, "waveform"):
            speech.save_pending((True, [str(path)]), json.dumps(self.crop_metadata(fields["guide_key"])),
                audio, fields["guide_key"], fields["recipe_json"], graph, "ws_save")
        self.queue.get_current_queue_volatile = lambda: ([], [])
        with self.assertRaisesRegex(ValueError, "serial running"):
            speech.save_pending((True, [str(path)]), "{}", audio, fields["guide_key"], fields["recipe_json"], graph, "ws_save")

    def test_pending_endpoint_requires_actual_owner_and_noncached_provenance(self):
        graph, path, history = self.save_and_history()
        fields = graph["ws_save"]["inputs"]
        audio = torch.zeros(1, 1, 24000)
        audio[..., :2400] = self.wave[:, 2400:]
        arguments = ((True, [str(path)]), json.dumps(self.crop_metadata(fields["guide_key"])),
                     {"waveform": audio, "sample_rate": 24000}, fields["guide_key"], fields["recipe_json"])
        with self.assertRaisesRegex(ValueError, "not part"):
            speech.save_pending(*arguments, graph, "foreign-id")
        owner = copy.deepcopy(graph)
        owner["ws_save"]["inputs"]["guide_key"] = "b" * 64
        self.queue.get_current_queue_volatile = lambda: ([(1, "foreign-owner", owner)], [])
        with self.assertRaisesRegex(ValueError, "recorded running"):
            speech.save_pending(*arguments, graph, "ws_save")
        uncompleted = copy.deepcopy(history)
        uncompleted["status"]["completed"] = False
        with self.assertRaisesRegex(ValueError, "successfully"):
            speech.record_guide(self.project, uncompleted)
        self.assertTrue(np.isnan(adapters.ZuraWanSpeechSaveGuide.IS_CHANGED()))

    def test_short_wrong_rate_and_external_files_are_not_valid_guides(self):
        self.manifest["clip"]["frames"] = 24
        graph = speech.build_graph(self.project)
        data = json.loads(graph["ws_save"]["inputs"]["recipe_json"])["key_data"]
        path = self.artifact(graph, frames=24)
        with self.assertRaisesRegex(ValueError, "timeline"):
            speech._verified_artifact(path, data)
        path = self.artifact(graph, fps=24)
        with self.assertRaisesRegex(ValueError, "timeline"):
            speech._verified_artifact(path, data)
        with self.assertRaisesRegex(ValueError, "local output"):
            speech._verified_artifact(self.base / "outside.mp4", data)

    def test_original_mode_keeps_original_face_without_speech_models(self):
        self.project["audio"] = None
        self.project["config"]["lip_sync"] = False
        # Shared Wan detection models exist but InfiniteTalk and generic speech do not.
        for identity in ("base", "speech", "wav2vec"):
            self.model_paths.pop((speech.MODELS[identity][0], speech.MODELS[identity][1]))
        graph = wan.build_wan_graph(self.project)
        self.assertEqual(graph["wan_save"]["inputs"]["face"], ["wan_pose_detect", 1])
        self.assertNotIn("wan_speech_video", graph)
        self.assertFalse(speech.enabled(self.project))

    def test_warm_native_faces_keep_source_pose_and_exact24fps_count(self):
        graph, path, history = self.save_and_history()
        speech.record_guide(self.project, history)
        prepared = wan.build_wan_graph(self.project)
        loader = prepared["wan_speech_video"]["inputs"]
        self.assertEqual(loader["video"], str(path.resolve()))
        self.assertEqual(loader["force_rate"], 24)
        self.assertEqual(loader["frame_load_cap"], 24)
        self.assertEqual(loader["format"], "None")
        self.assertEqual(prepared["wan_save"]["inputs"]["face"], ["wan_speech_face_detect", 1])
        self.assertEqual(prepared["wan_pose_draw"]["inputs"]["pose_data"], ["wan_pose_detect", 0])
        self.assertNotIn("ZuraSpeechFaceGuide", json.dumps(prepared))
        initial = wan.cache_key(self.project)
        self.project["config"]["resolution"] = 1080
        self.assertNotEqual(initial, wan.cache_key(self.project))
        self.assertTrue(speech.guide_ready(self.project))


class CropTests(unittest.TestCase):
    def crop(self, source_box=(75, 50, 125, 100), opening_box=(150, 100, 250, 200), source_pose=None, opening_pose=None, mask=None):
        return adapters.ZuraWanSpeechReferenceCrop().crop(torch.full((1, 800, 400, 3), .5),
            torch.full((1, 400, 200, 3), .25), torch.ones(1, 400, 200) if mask is None else mask,
            source_pose or pose(200, 400, leading_foot=True), [source_box],
            opening_pose or pose(400, 800), [opening_box], "a" * 64)

    def test_different_detector_size_maps_to_original_approved_crop_without_stretch(self):
        result = self.crop(opening_box=(75, 50, 125, 100), opening_pose=pose(200, 400))
        portrait, metadata = result["result"]
        metadata = json.loads(metadata)
        self.assertEqual(metadata["opening_face_xyxy"], [150, 100, 250, 200])
        self.assertEqual(portrait.shape[2] * 4, portrait.shape[1] * 3)
        self.assertTrue(torch.equal(portrait, torch.full_like(portrait, .5)))
        x, y, w, h = metadata["crop_xywh"]
        self.assertLessEqual(x, 150)
        self.assertLessEqual(y, 100)
        self.assertGreaterEqual(x + w, 250)
        self.assertGreaterEqual(y + h, 200)

    def test_edge_crop_stays_inside_and_covers_whole_face(self):
        result = self.crop(source_box=(0, 0, 25, 30), opening_box=(0, 0, 50, 60))
        metadata = json.loads(result["result"][1])
        self.assertEqual(metadata["crop_xywh"][:2], [0, 0])
        speech._validate_crop(metadata, "a" * 64)

    def test_fallback_face_low_confidence_and_wrong_performer_rejected(self):
        for kwargs in ({"source_pose": pose(200, 400, confidence=.01)},
                       {"opening_pose": pose(400, 800, confidence=.01)},
                       {"mask": torch.zeros(1, 400, 200)},
                       {"opening_box": (0, 500, 50, 600)}):
            with self.assertRaises(ValueError):
                self.crop(**kwargs)
        collapsed = pose(200, 400)
        collapsed["pose_metas_original"][0]["keypoints_face"][:, :2] = .5
        with self.assertRaisesRegex(ValueError, "collapsed"):
            self.crop(source_pose=collapsed)
        invalid = self.crop()["result"][1]
        invalid = json.loads(invalid)
        invalid["source_confidence"] = float("nan")
        with self.assertRaises(ValueError):
            speech._validate_crop(invalid, "a" * 64)


class SetupTests(unittest.TestCase):
    def test_offline_check_does_not_install_or_download(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(setup.subprocess, "run") as install, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(setup.main(["--check", "--models-directory", directory]), 1)
            install.assert_not_called()
        self.assertEqual(len(setup.MODELS), 9)
        self.assertTrue(all(len(spec[3]) == 40 and len(spec[6]) == 64 for spec in setup.MODELS))

    def test_desktop_discovery_reads_only_bounded_instance_model_yaml(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(setup.os.environ, {"APPDATA": directory}):
            base = Path(directory) / "Comfy Desktop" / "instance-model-paths"
            base.mkdir(parents=True)
            model_config = base / "inst-1.yaml"
            model_config.write_text("shared: {base_path: 'D:/models', diffusion_models: 'diffusion_models/'}")
            (base / "credentials.json").write_text("not read")
            self.assertEqual(setup.desktop_configs(), [model_config])
            for i in range(2, 66):
                (base / ("inst-" + str(i) + ".yaml")).write_text("{}")
            with self.assertRaisesRegex(ValueError, "Select one"):
                setup.desktop_configs()

    def test_explicit_extra_configs_and_shared_existing_models_are_reused(self):
        import folder_paths
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "folder_paths.py").write_text("# synthetic installed Comfy layout")
            extra = base / "external-model-paths.yaml"
            extra.write_text("# external model config")
            shared = base / "shared" / "diffusion_models"
            shared.mkdir(parents=True)
            paths = {}
            def load(filename):
                self.assertEqual(Path(filename), extra.resolve())
                paths["diffusion_models"] = ([str(shared)], {".safetensors"})
            config_module = types.ModuleType("utils.extra_config")
            config_module.load_extra_path_config = load
            with patch.object(folder_paths, "folder_names_and_paths", paths, create=True), \
                    patch.dict(sys.modules, {"utils.extra_config": config_module}), \
                    patch.object(setup, "desktop_configs", side_effect=AssertionError("Explicit configuration must win")):
                locations = setup.directories(base, extra_configs=[extra])
            self.assertEqual(locations["diffusion_models"], [shared, base / "models" / "diffusion_models"])
            model = shared / "Wan2_1-InfiniTetalk-Single_fp16.safetensors"
            model.write_bytes(b"existing shared model")
            spec = ("diffusion_models", "Wan2_1-InfiniteTalk-Single_fp16.safetensors", "repo", "revision", "file",
                    model.stat().st_size, setup.digest(model))
            self.assertEqual(setup.existing(spec, locations, verify=True), model)

    def test_download_verifies_and_never_overwrites_existing_model(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            fixture = base / "download.bin"
            fixture.write_bytes(b"verified synthetic weights")
            spec = ("diffusion_models", "speech.bin", "synthetic/repo", "r" * 40, "upstream.bin",
                    fixture.stat().st_size, setup.digest(fixture))
            locations = {"diffusion_models": [base / "models"]}
            calls = []
            download = lambda **args: calls.append(args) or fixture
            path = setup.install(spec, locations, download)
            self.assertEqual(path.read_bytes(), fixture.read_bytes())
            self.assertEqual(calls[0]["revision"], "r" * 40)
            with self.assertRaisesRegex(ValueError, "existing model"):
                setup.install(spec, locations, download)
            self.assertEqual(path.read_bytes(), fixture.read_bytes())
            wrong = list(spec)
            wrong[6] = "0" * 64
            with self.assertRaisesRegex(ValueError, "failed verification"):
                setup.install(tuple(wrong), locations, download)


if __name__ == "__main__":
    unittest.main()
