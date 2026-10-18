"""CPU checks for wrong-scenario and stale native phase handoffs."""
import copy
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from PIL import Image

_spec = importlib.util.spec_from_file_location("ltx25_plan", Path(__file__).parents[1] / "artist_studio" / "ltx25.py")
plan_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plan_module)


def inputs(scenario="replacement"):
    asset = {"file": "example.png", "sha": "a" * 64}
    project = {"source": {**asset, "file": "example.mp4"}, "character": asset,
               "opening_input": asset, "opening_key": "current-look", "opening_approval": "current-look",
               "approval": "current-selection", "review": "review-example",
               "audio": {**asset, "file": "example.wav"},
               "ltx25_run": {"namespace": "a" * 32},
               "config": {"edit_area": "scene", "resolution": 1920, "seed": 42}}
    names = ("model", "video_vae", "audio_vae", "union", "upscaler", "bbox_detector", "pose_estimator")
    kwargs = {"scenario": scenario, "timeline": {"frames": 120, "fps": 24, "width": 704, "height": 1280, "has_audio": True},
              "models": dict(plan_module.QUALIFIED_MODELS),
              "model_pins": {name: {"sha": "b" * 64} for name in (*names, "text_encoder")},
              "text_encoder_inputs": {"clip_name": "encoder.safetensors", "type": "ltxv", "device": "default"},
              "approval_key": "current-selection", "original_audio_sha": "c" * 64}
    return project, kwargs


class NativePlanTests(unittest.TestCase):
    def test_objects_use_native_edges_without_people_detectors(self):
        project, kwargs = inputs("silent")
        project["config"]["subject_mode"] = "objects"
        for name in ("bbox_detector", "pose_estimator"):
            kwargs["models"].pop(name)
            kwargs["model_pins"].pop(name)
        plan = plan_module.build_plan(project, **kwargs)
        guide = plan["phases"]["motion"]["pose"]
        self.assertEqual(guide, {"class_type": "Canny", "inputs": {
            "image": ["source_components", 0], "low_threshold": .1, "high_threshold": .2}})
        self.assertEqual(plan["basis"]["guide_type"], "canny_objects")
        self.assertEqual(set(plan["basis"]["models"]), {
            "model", "video_vae", "audio_vae", "union", "upscaler"})
        self.assertNotIn("facial", plan["basis"]["positive"])
        self.assertNotIn("anatomy", plan["basis"]["negative"])
        self.assertFalse(any(n["class_type"] == "DWPreprocessor"
                             for g in plan["phases"].values() for n in g.values()))

    def test_auto_and_people_preserve_approved_graphs(self):
        project, kwargs = inputs()
        original = plan_module.build_plan(project, **kwargs)
        for mode in ("auto", "people"):
            project["config"]["subject_mode"] = mode
            self.assertEqual(original, plan_module.build_plan(project, **kwargs))

    def test_missing_audio_and_wrong_silent_selection(self):
        project, kwargs = inputs()
        project.pop("audio")
        with self.assertRaisesRegex(ValueError, "replacement audio"):
            plan_module.build_plan(project, **kwargs)
        kwargs["scenario"] = "original"
        kwargs["timeline"]["has_audio"] = False
        with self.assertRaisesRegex(ValueError, "no audio"):
            plan_module.build_plan(project, **kwargs)
        kwargs["scenario"] = "silent"
        plan = plan_module.build_plan(project, **kwargs)
        self.assertEqual(plan["phases"]["motion"]["zero_audio"]["class_type"], "LTXVEmptyLatentAudio")
        self.assertNotIn("audio", plan["phases"]["decode"]["create_video"]["inputs"])
        self.assertNotIn("encode_audio", plan["phases"]["motion"])

    def test_stale_approval_mask_scope_and_long_interval(self):
        project, kwargs = inputs()
        project["approval"] = "old"
        with self.assertRaisesRegex(ValueError, "current source"):
            plan_module.build_plan(project, **kwargs)
        project["approval"] = "current-selection"
        project["config"]["edit_area"] = "mask"
        with self.assertRaisesRegex(ValueError, "background preservation"):
            plan_module.build_plan(project, **kwargs)
        project["config"]["edit_area"] = "scene"
        kwargs["timeline"]["frames"] = 121
        with self.assertRaisesRegex(ValueError, "five seconds"):
            plan_module.build_plan(project, **kwargs)

    def test_scenarios_have_distinct_keys_and_no_replacement_face(self):
        plans = {mode: plan_module.build_plan(*inputs(mode)[:1], **inputs(mode)[1]) for mode in ("original", "replacement", "silent")}
        self.assertEqual(len({plan["key"] for plan in plans.values()}), 3)
        self.assertEqual(plans["replacement"]["phases"]["motion"]["pose"]["inputs"]["detect_face"], "disable")
        self.assertEqual(plans["original"]["phases"]["motion"]["pose"]["inputs"]["detect_face"], "enable")
        self.assertEqual(plans["silent"]["basis"]["audio"], {"kind": "zero_latent", "delivered_audio": False})
        for plan in plans.values():
            for phase in ("stage1", "refine"):
                classes = {node["class_type"] for node in plan["phases"][phase].values()}
                self.assertIn("SamplerCustomAdvanced", classes)
                if phase == "refine":
                    self.assertNotIn("VAELoader", classes)
            self.assertNotIn("save_initial_video", plan["phases"]["stage1"])
            self.assertNotIn("save_guided_text", plan["phases"]["stage1"])
            self.assertNotIn("union", plan["phases"]["refine"])

    def test_resolution_drives_delivery_and_native_rounding(self):
        project, kwargs = inputs()
        plan = plan_module.build_plan(project, **kwargs)
        self.assertEqual(plan["basis"]["delivery"], [1056, 1920])
        self.assertEqual(plan["basis"]["native"], [1024, 1920])
        self.assertEqual(plan["basis"]["padded"], 121)
        project["config"]["resolution"] = 1280
        smaller = plan_module.build_plan(project, **kwargs)
        self.assertNotEqual(plan["key"], smaller["key"])
        self.assertEqual(smaller["basis"]["delivery"], [704, 1280])

    def test_rejects_resolution_below_reviewed_source_loader_minimum(self):
        project, kwargs = inputs()
        project["config"]["resolution"] = 256
        with self.assertRaisesRegex(ValueError, "at least 512"):
            plan_module.build_plan(project, **kwargs)

    def text_receipt(self, plan, directory):
        spec = plan["artifacts"]["text"]
        path = Path(directory) / "genj" / "text_cache" / (spec["key"] + ".pt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic conditioning receipt")
        graph = plan["phases"]["text"]
        return {"plan_key": plan["key"], "scenario": plan["scenario"], "artifact": "text",
                "producer_phase": "text", "template_graph_sha256": plan["graph_hashes"]["text"],
                "submitted_graph": copy.deepcopy(graph), "producer_graph_sha256": plan_module.digest(graph),
                "prompt_id": "test-prompt", "history": {"prompt": [0, "test-prompt", copy.deepcopy(graph)],
                "status": {"status_str": "success", "completed": True}}, "path": str(path),
                "sha256": plan_module.file_digest(path), "cache_key": spec["key"]}

    def motion_receipts(self, plan, directory):
        graph = plan["phases"]["motion"]
        history = {"prompt": [0, "motion-prompt", graph],
                   "status": {"status_str": "success", "completed": True}, "outputs": {}}
        spec = plan["artifacts"]["pose"]
        prefix = Path(spec["prefix"])
        target = Path(directory) / prefix.parent
        target.mkdir(parents=True)
        buffer = io.BytesIO()
        Image.new("RGB", tuple(spec["raster"]), "black").save(buffer, format="PNG")
        assets = []
        for index in range(spec["frames"]):
            filename = prefix.name + f"_{index + 1:05}_.png"
            (target / filename).write_bytes(buffer.getvalue())
            assets.append({"filename": filename, "subfolder": str(prefix.parent), "type": "output"})
        history["outputs"][spec["node"]] = {"images": assets}
        audio_spec = plan["artifacts"]["audio"]
        prefix = Path(graph[audio_spec["node"]]["inputs"]["filename_prefix"])
        audio = Path(directory) / prefix.parent / (prefix.name + "_00001_.latent")
        audio.write_bytes(b"synthetic conditioning audio")
        copied = Path(directory) / "conditioning.latent"
        copied.write_bytes(audio.read_bytes())
        history["outputs"][audio_spec["node"]] = {"latents": [{"filename": audio.name,
            "subfolder": str(prefix.parent), "type": "output"}]}
        common = {"plan_key": plan["key"], "scenario": plan["scenario"], "producer_phase": "motion",
            "template_graph_sha256": plan["graph_hashes"]["motion"], "submitted_graph": graph,
            "producer_graph_sha256": plan_module.digest(graph), "prompt_id": "motion-prompt", "history": history}
        return {"pose": {**common, "artifact": "pose",
                          **plan_module.image_sequence_receipt(spec, history, output_directory=directory)},
                "audio": {**common, "artifact": "audio", "path": str(audio),
                    "sha256": plan_module.file_digest(audio), "input_filename": copied.name, "input_path": str(copied)}}

    def test_receipt_rejects_wrong_scenario_failure_and_changed_file(self):
        project, kwargs = inputs()
        plan = plan_module.build_plan(project, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            receipt = self.text_receipt(plan, directory)
            roots = {"output_directory": directory, "input_directory": directory}
            receipts = {"text": receipt, **self.motion_receipts(plan, directory)}
            self.assertEqual(plan_module.bind_phase(plan, "stage1", receipts, **roots)["load_text"], plan["phases"]["stage1"]["load_text"])
            wrong = copy.deepcopy(receipt)
            wrong["scenario"] = "silent"
            with self.assertRaisesRegex(ValueError, "another plan or scenario"):
                plan_module.bind_phase(plan, "stage1", {"text": wrong}, **roots)
            wrong = copy.deepcopy(receipt)
            wrong["history"]["status"]["status_str"] = "error"
            with self.assertRaisesRegex(ValueError, "successful native producer"):
                plan_module.bind_phase(plan, "stage1", {"text": wrong}, **roots)
            Path(receipt["path"]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "missing or changed"):
                plan_module.bind_phase(plan, "stage1", {"text": receipt}, **roots)

    def test_receipt_cannot_claim_template_for_different_native_controls(self):
        project, kwargs = inputs()
        plan = plan_module.build_plan(project, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            receipt = self.text_receipt(plan, directory)
            receipt["submitted_graph"]["positive"]["inputs"]["text"] = "changed direction"
            receipt["producer_graph_sha256"] = plan_module.digest(receipt["submitted_graph"])
            receipt["history"]["prompt"][2] = copy.deepcopy(receipt["submitted_graph"])
            with self.assertRaisesRegex(ValueError, "native controls"):
                plan_module.bind_phase(plan, "stage1", {"text": receipt}, output_directory=directory, input_directory=directory)

    def test_cropped_video_receipt_has_exact_native_binding_and_digest(self):
        project, kwargs = inputs()
        plan = plan_module.build_plan(project, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            roots = {"output_directory": directory, "input_directory": directory}
            receipts = {"text": self.text_receipt(plan, directory), **self.motion_receipts(plan, directory)}
            graph = plan_module.bind_phase(plan, "stage1", receipts, **roots)
            spec = plan["artifacts"]["stage1_video"]
            path = Path(directory) / "zura" / "latent_data" / (spec["key"] + ".safetensors")
            path.parent.mkdir(parents=True)
            path.write_bytes(b"synthetic video receipt; data node validates tensors at runtime")
            receipts["stage1_video"] = {
                "plan_key": plan["key"], "scenario": plan["scenario"], "artifact": "stage1_video",
                "producer_phase": "stage1", "template_graph_sha256": plan["graph_hashes"]["stage1"],
                "submitted_graph": graph, "producer_graph_sha256": plan_module.digest(graph),
                "prompt_id": "video-prompt", "history": {"prompt": [0, "video-prompt", graph],
                "status": {"status_str": "success", "completed": True}}, "path": str(path),
                "sha256": plan_module.file_digest(path), "cache_key": spec["key"],
            }
            bound = plan_module.bind_phase(plan, "upscale", receipts, **roots)
            self.assertEqual(bound["load_stage1_video"]["inputs"]["cache_digest"], plan_module.file_digest(path))
            receipts["stage1_video"]["history"]["prompt"][1] = "different-prompt"
            with self.assertRaisesRegex(ValueError, "successful native producer"):
                plan_module.bind_phase(plan, "upscale", receipts, **roots)

    def test_combined_stage1_has_no_dangling_cache_references(self):
        project, kwargs = inputs()
        plan = plan_module.build_plan(project, **kwargs)
        for phase, graph in plan["phases"].items():
            def check(value):
                if isinstance(value, dict):
                    for child in value.values():
                        check(child)
                elif isinstance(value, list):
                    if len(value) == 2 and isinstance(value[0], str) and type(value[1]) is int:
                        self.assertIn(value[0], graph, (phase, value))
                    else:
                        for child in value:
                            check(child)
            check(graph)
        self.assertEqual(plan["phases"]["stage1"]["concat"]["inputs"]["video_latent"], ["guide", 2])
        self.assertEqual(plan["phases"]["stage1"]["save_stage1_video"]["inputs"]["samples"], ["crop_guides", 2])

    def test_motion_boundary_preserves_native_signed_guides_and_sampling_recipe(self):
        project, kwargs = inputs()
        plan = plan_module.build_plan(project, **kwargs)
        stage1, motion = plan["phases"]["stage1"], plan["phases"]["motion"]
        self.assertEqual(tuple(plan["phases"]), ("text", "motion", "stage1", "upscale", "refine", "decode"))
        self.assertEqual(plan["schema"], "zura.ltx25.native-plan/2")
        self.assertNotIn("UNETLoader", {n["class_type"] for n in motion.values()})
        for removed in ("DWPreprocessor", "GenjLoadReviewedShot", "LoadAudio", "LTXVAudioVAEEncode"):
            self.assertNotIn(removed, {n["class_type"] for n in stage1.values()})
        self.assertEqual(motion["save_audio"]["inputs"]["samples"], ["encode_audio", 0])
        self.assertEqual(motion["save_pose"]["inputs"]["images"], ["pose_fit", 0])
        self.assertEqual(stage1["load_pose"]["inputs"]["image_load_cap"], 120)
        self.assertEqual(stage1["pose_tail"]["inputs"]["image"], ["load_pose", 0])
        self.assertEqual(stage1["frozen_audio"]["inputs"]["samples"], ["load_audio", 0])
        self.assertEqual(stage1["guide"]["inputs"]["latent"], ["first_frame", 0])
        self.assertEqual(stage1["first_frame"]["inputs"]["strength"], .7)
        self.assertEqual(stage1["guide"]["inputs"]["strength"], 1)
        self.assertEqual(stage1["guide"]["inputs"]["latent_downscale_factor"], 2)
        self.assertEqual(stage1["guider"]["inputs"]["positive"], ["guide", 0])
        self.assertEqual(stage1["guider"]["inputs"]["cfg"], 1)
        self.assertEqual(stage1["noise"]["inputs"]["noise_seed"], 42)
        self.assertEqual(stage1["sampler"]["inputs"]["sampler_name"], "euler_ancestral")
        self.assertEqual(stage1["sigmas"]["inputs"]["sigmas"], plan_module.STAGE1_SIGMAS)
        self.assertEqual(plan["phases"]["refine"]["sigmas"]["inputs"]["sigmas"], plan_module.STAGE2_SIGMAS)

    def test_pose_receipts_reject_missing_extra_changed_and_reordered_files(self):
        project, kwargs = inputs()
        project["config"]["resolution"] = 512
        plan = plan_module.build_plan(project, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            receipts = {"text": self.text_receipt(plan, directory), **self.motion_receipts(plan, directory)}
            roots = {"output_directory": directory, "input_directory": directory}
            bound = plan_module.bind_phase(plan, "stage1", receipts, **roots)
            receipt = receipts["pose"]
            self.assertEqual(bound["load_pose"]["inputs"]["directory"], receipt["directory"])
            frame = Path(receipt["directory"]) / receipt["files"][0]["filename"]
            original = frame.read_bytes()
            for mutation in ("missing", "extra", "changed", "reordered", "wrong_scenario", "wrong_save"):
                with self.subTest(mutation=mutation):
                    altered = copy.deepcopy(receipts)
                    extra = frame.parent / "unrelated.png"
                    try:
                        if mutation == "missing":
                            frame.unlink()
                        elif mutation == "extra":
                            extra.write_bytes(original)
                        elif mutation == "changed":
                            Image.new("RGB", tuple(plan["artifacts"]["pose"]["raster"]), "white").save(frame)
                        elif mutation == "reordered":
                            altered["pose"]["files"].reverse()
                        elif mutation == "wrong_scenario":
                            altered["pose"]["scenario"] = "original"
                        else:
                            altered["pose"]["history"]["outputs"]["save_pose"]["images"][0]["subfolder"] = "unrelated"
                        with self.assertRaises(ValueError):
                            plan_module.bind_phase(plan, "stage1", altered, **roots)
                    finally:
                        frame.write_bytes(original)
                        extra.unlink(missing_ok=True)
            reversed_history = copy.deepcopy(receipt["history"])
            reversed_history["outputs"]["save_pose"]["images"].reverse()
            with self.assertRaisesRegex(ValueError, "reordered"):
                plan_module.image_sequence_receipt(plan["artifacts"]["pose"], reversed_history, output_directory=directory)
            wrong_size = plan["artifacts"]["pose"]["raster"]
            Image.new("RGB", (wrong_size[0] + 1, wrong_size[1]), "black").save(frame)
            with self.assertRaisesRegex(ValueError, "dimensions"):
                plan_module.bind_phase(plan, "stage1", receipts, **roots)

    def test_old_inline_preparation_schema_cannot_be_adopted(self):
        project, kwargs = inputs()
        plan = plan_module.build_plan(project, **kwargs)
        plan["schema"] = "zura.ltx25.native-plan/1"
        with self.assertRaisesRegex(ValueError, "stale or malformed"):
            plan_module.bind_phase(plan, "motion", {}, output_directory="unused", input_directory="unused")

    def test_new_render_namespace_is_fresh_but_persisted_run_is_stable(self):
        project, kwargs = inputs()
        first = plan_module.build_plan(project, **kwargs)
        same = plan_module.build_plan(copy.deepcopy(project), **kwargs)
        self.assertEqual(first, same)
        project["ltx25_run"]["namespace"] = "b" * 32
        second = plan_module.build_plan(project, **kwargs)
        self.assertNotEqual(first["key"], second["key"])
        self.assertNotEqual(first["artifacts"]["pose"]["prefix"], second["artifacts"]["pose"]["prefix"])
        project["ltx25_run"]["namespace"] = "../invalid"
        with self.assertRaisesRegex(ValueError, "new LTX render"):
            plan_module.build_plan(project, **kwargs)

    def test_soundtrack_only_uses_raw_original_conditioning_and_selected_delivery(self):
        project, kwargs = inputs("original")
        kwargs["timeline"].update(source_has_audio=True, start=3.5)
        project["config"]["audio_start"] = .75
        plan = plan_module.build_plan(project, **kwargs)
        stage1, decode = plan["phases"]["motion"], plan["phases"]["decode"]
        self.assertEqual(stage1["original_audio"]["inputs"]["audio"], project["source"]["file"])
        self.assertEqual(stage1["original_audio_interval"]["inputs"]["start_index"], 3.5)
        self.assertNotIn("selected_audio", stage1)
        self.assertEqual(stage1["pose"]["inputs"]["detect_face"], "enable")
        self.assertEqual(decode["selected_audio"]["inputs"]["audio"], project["audio"]["file"])
        self.assertEqual(decode["apply_audio"]["inputs"]["audio_start_seconds"], .75)
        self.assertEqual((plan["generation_audio"], plan["delivery_audio"]), ("raw_original", "selected_soundtrack"))
        project["audio"]["sha"] = "d" * 64
        self.assertNotEqual(plan["key"], plan_module.build_plan(project, **kwargs)["key"])
        project["audio"]["sha"] = "a" * 64
        kwargs["timeline"]["start"] = 4.5
        self.assertNotEqual(plan["key"], plan_module.build_plan(project, **kwargs)["key"])

    def test_soundtrack_only_silent_raw_source_freezes_zero_but_retains_face_guide(self):
        project, kwargs = inputs("original")
        kwargs["timeline"].update(source_has_audio=False, has_audio=True)
        plan = plan_module.build_plan(project, **kwargs)
        self.assertEqual(plan["scenario"], "original")
        self.assertIn("zero_audio", plan["phases"]["motion"])
        self.assertNotIn("encode_audio", plan["phases"]["motion"])
        self.assertNotIn("original_audio", plan["phases"]["motion"])
        self.assertEqual(plan["phases"]["motion"]["pose"]["inputs"]["detect_face"], "enable")
        self.assertEqual((plan["generation_audio"], plan["delivery_audio"]), ("zero", "selected_soundtrack"))
        self.assertIn("audio", plan["phases"]["decode"]["create_video"]["inputs"])
        kwargs["timeline"]["source_has_audio"] = True
        self.assertNotEqual(plan["key"], plan_module.build_plan(project, **kwargs)["key"])


if __name__ == "__main__":
    unittest.main()
