"""CPU-only metadata planning and queue-guard tests for editable Wan graphs."""
import copy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

import v2_bootstrap

NAME = "ComfyUI_zura_nodes.artist_studio"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[NAME] = package
studio = importlib.import_module(NAME + ".studio")
planner = importlib.import_module(NAME + ".wan_graph")
guard_module = importlib.import_module(NAME + ".wan_graph_guard")
runtime = importlib.import_module("ComfyUI_zura_nodes.wan_preparation_runtime")


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def javascript_json_roundtrip(value):
    node = shutil.which("node") or r"C:\nvm4w\nodejs\node.exe"
    if not Path(node).is_file():
        raise unittest.SkipTest("Node.js is unavailable for the browser JSON round-trip check.")
    script = "const fs=require('fs');process.stdout.write(JSON.stringify(JSON.parse(fs.readFileSync(0,'utf8'))));"
    completed = subprocess.run([node, "-e", script], input=json.dumps(value),
                               text=True, capture_output=True, timeout=10, check=True)
    return json.loads(completed.stdout)


class WanGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.review_id = "shot_0123456789abcdef"
        self.review_dir = self.root / "genj" / "reviews" / self.review_id
        self.review_dir.mkdir(parents=True)
        self.source_sha = digest("approved original shot")
        self.mask_sha = digest("approved review mask")
        self.mask_review = {
            "shot_id": self.review_id,
            "clip": {"source_hash": self.source_sha, "frames": 100, "fps": 24,
                     "width": 720, "height": 1280, "start": 0.0,
                     "duration": 100 / 24, "full_source": False},
            "files": {"mask.mp4": self.mask_sha},
        }
        (self.review_dir / "review.json").write_text(json.dumps(self.mask_review), encoding="utf-8")
        self.project = {
            "id": "a" * 32,
            "review": self.review_id,
            "source": {"file": "source.mp4", "sha": self.source_sha},
            "character": {"file": "character.png", "sha": digest("character ref")},
            "opening_input": {"file": "opening.png", "sha": digest("opening ref")},
            "opening_key": digest("opening approval"),
            "opening_approval": digest("opening approval"),
            "config": {"engine": "wan", "background": "keep", "scope": "person",
                       "edit_area": "mask", "mask_method": "auto", "resolution": 1280,
                       "start": 0.0, "duration": 4.17, "length_mode": "custom",
                       "size": 512, "performer": -1,
                       "margin": 20, "pitch": False, "quality": "detailed",
                       "audio_start": 0.0, "lip_sync": False, "seed": 41,
                       "prompt": "Keep the movement"},
            "audio": None,
        }
        self.project["approval"] = studio.prep_key(self.project)
        studio_dir = self.root / "genj" / "studio"
        studio_dir.mkdir(parents=True)
        saved_project = copy.deepcopy(self.project)
        saved_project["opening_approval"] = None
        (studio_dir / (self.project["id"] + ".json")).write_text(
            json.dumps(saved_project), encoding="utf-8")
        self.graph = self.make_graph()
        self.folder_paths = sys.modules["folder_paths"]
        self.output_patch = patch.object(self.folder_paths, "get_output_directory",
                                         return_value=str(self.root), create=True)
        self.output_patch.start()
        self.addCleanup(self.output_patch.stop)

    def make_graph(self):
        shot, window, model, detector = "source", "window", "onnx", "pose"
        block, carry, draw, char, save = "mask_block", "pose_carry", "pose_draw", "char_ref", "part_save"
        return {
            shot: {"class_type": "GenjLoadReviewedShot", "inputs": {
                "shot_id": self.review_id, "approved_shot_id": self.review_id,
                "render_long_edge": self.project["config"]["resolution"],
                "output_scale": 1, "preview_seconds": 0}},
            window: {"class_type": "ZuraWanPreparationWindow", "inputs": {
                "source": [shot, 0], "mask_video": [shot, 1], "clip_details": [shot, 3],
                "start_frame": 0, "frame_count": 81}},
            model: {"class_type": "OnnxDetectionModelLoader", "inputs": {
                "vitpose_model": "vitpose-l-wholebody.onnx", "yolo_model": "yolov10m.onnx",
                "onnx_device": "CPUExecutionProvider"}},
            detector: {"class_type": "PoseAndFaceDetection", "inputs": {
                "model": [model, 0], "images": [window, 0], "width": [window, 2],
                "height": [window, 3], "face_padding": 0}},
            block: {"class_type": "BlockifyMask", "inputs": {
                "masks": [window, 1], "block_size": 32, "device": "cpu"}},
            carry: {"class_type": "ZuraWanCarryPoseWindow", "inputs": {
                "pose_data": [detector, 0], "window": [window, 4], "clip_details": [shot, 3],
                "reference": [char, 0], "cache_key": "1" * 64, "scope": "person"}},
            draw: {"class_type": "DrawViTPose", "inputs": {
                "pose_data": [carry, 0], "width": [window, 2], "height": [window, 3],
                "retarget_padding": 0, "body_stick_width": -1, "hand_stick_width": -1,
                "draw_head": True}},
            char: {"class_type": "LoadImage", "inputs": {"image": "character.png"}},
            save: {"class_type": "ZuraWanSavePreparationPart", "inputs": {
                "frames": [window, 0], "mask": [block, 0], "pose": [draw, 0],
                "face": [detector, 1], "reference": [char, 0], "window": [window, 4],
                "carry_state": [carry, 1], "clip_details": [shot, 3],
                "cache_key": "1" * 64, "scope": "person"}},
        }

    def plan(self, graph=None, project=None, context=None):
        return planner.plan_wan_graph(project or self.project, graph or self.graph,
                                      context, output_root=self.root)

    def test_comfy_runtime_is_changed_markers_do_not_change_graph_context(self):
        baseline = self.plan()
        graph = copy.deepcopy(baseline["graph"])
        guard_id = baseline["guard"]["semantic_id"]
        # Comfy's IsChangedCache stores callback results on the runtime node;
        # always-refresh nodes can return NaN, while other callbacks can return
        # booleans or strings. These are cache markers, not artist settings.
        graph[guard_id]["is_changed"] = [float("nan")]
        graph["part_save"]["is_changed"] = False
        graph["pose_carry"]["is_changed"] = "refresh-marker"
        result = self.plan(graph, context=baseline["context"])

        self.assertEqual(result["context"]["context_key"], baseline["context"]["context_key"])
        self.assertEqual(result["context"]["recipe_sha256"], baseline["context"]["recipe_sha256"])
        self.assertEqual(result["guard"]["plan_json"], baseline["guard"]["plan_json"])
        self.assertNotIn("is_changed", result["graph"][guard_id])
        self.assertNotIn("is_changed", result["graph"]["part_save"])
        self.assertNotIn("is_changed", result["graph"]["pose_carry"])
        self.assertEqual(
            guard_module.ZuraWanGraphQueueGuard().validate(
                baseline["guard"]["plan_json"], graph, guard_id),
            (baseline["context"]["context_key"], 0, 81, 0.0))
        # Normalisation is copy-based and leaves the caller's dynamic prompt intact.
        self.assertTrue(math.isnan(graph[guard_id]["is_changed"][0]))

    def test_runtime_field_normalisation_preserves_inputs_and_metadata(self):
        graph = {"artist_node": {
            "class_type": "ArtistFixtureNode",
            "inputs": {"is_changed": "artist-authored value", "strength": 0.5},
            "is_changed": [float("nan")],
            "_meta": {"title": "Artist control", "custom": "keep"},
            "properties": {"authoring_hint": "keep"},
        }}
        normalised = planner._normalise_prompt(graph)
        self.assertNotIn("is_changed", normalised["artist_node"])
        self.assertEqual(normalised["artist_node"]["inputs"]["is_changed"], "artist-authored value")
        self.assertEqual(normalised["artist_node"]["_meta"], graph["artist_node"]["_meta"])
        self.assertEqual(normalised["artist_node"]["properties"], graph["artist_node"]["properties"])

    def test_nonfinite_values_in_real_graph_inputs_or_metadata_still_fail_closed(self):
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value):
                graph = copy.deepcopy(self.graph)
                graph["pose_draw"]["inputs"]["artist_value"] = value
                with self.assertRaisesRegex(planner.WanGraphPlanError, "not serialisable JSON"):
                    planner._normalise_prompt(graph)
        metadata_graph = copy.deepcopy(self.graph)
        metadata_graph["pose_draw"]["_meta"] = {"title": "Pose", "scale": float("nan")}
        with self.assertRaisesRegex(planner.WanGraphPlanError, "not serialisable JSON"):
            planner._normalise_prompt(metadata_graph)

    def test_runtime_is_changed_marker_still_counts_toward_graph_size_limit(self):
        graph = copy.deepcopy(self.graph)
        base_size = len(planner.canonical(graph).encode("utf-8"))
        graph["part_save"]["is_changed"] = ["x" * 512]
        with patch.object(planner, "MAX_GRAPH_BYTES", base_size + 32):
            with self.assertRaisesRegex(planner.WanGraphPlanError, "exceeds its metadata limit"):
                planner._normalise_prompt(graph)

    def test_native_import_empty_optional_widgets_preserve_recipe_and_guard(self):
        graph = copy.deepcopy(self.graph)
        # Native Comfy graph import exposes empty point-prompt widgets absent
        # from the API builder. Keep this SAM node in the reference ancestry.
        graph["character_detect"] = {"class_type": "SAM3_Detect", "inputs": {
            "image": ["char_ref", 0], "threshold": 0.3}}
        graph["pose_carry"]["inputs"]["reference"] = ["character_detect", 0]
        graph["part_save"]["inputs"]["reference"] = ["character_detect", 0]
        baseline = self.plan(graph)
        imported = copy.deepcopy(baseline["graph"])
        for identity in ("character_detect", "pose_carry", "part_save"):
            for field in planner.EMPTY_OPTIONAL_INPUTS[imported[identity]["class_type"]]:
                imported[identity]["inputs"][field] = ""
        # Native validation also coerces a FLOAT widget's integer zero.
        imported["source"]["inputs"]["preview_seconds"] = 0.0
        guard_id = baseline["guard"]["semantic_id"]
        imported[guard_id]["is_changed"] = [float("nan")]
        self.assertEqual(planner.preparation_fingerprint(imported),
                         baseline["context"]["recipe_sha256"])
        self.assertEqual(guard_module.ZuraWanGraphQueueGuard().validate(
            baseline["guard"]["plan_json"], imported, guard_id),
            (baseline["context"]["context_key"], 0, 81, 0.0))
        next_plan = self.plan(imported, context=baseline["context"])
        self.assertEqual(next_plan["context"]["context_key"], baseline["context"]["context_key"])
        for identity in ("character_detect", "pose_carry", "part_save"):
            for field in planner.EMPTY_OPTIONAL_INPUTS[imported[identity]["class_type"]]:
                with self.subTest(identity=identity, field=field):
                    changed = copy.deepcopy(imported)
                    changed[identity]["inputs"][field] = "artist-edited"
                    self.assertNotEqual(planner.preparation_fingerprint(changed),
                                        baseline["context"]["recipe_sha256"])
                    with self.assertRaises(ValueError):
                        guard_module.ZuraWanGraphQueueGuard().validate(
                            baseline["guard"]["plan_json"], changed, guard_id)

    def test_optional_empty_normalisation_is_class_field_and_type_specific(self):
        baseline = planner.preparation_fingerprint(self.graph)
        for value in (None, False, 0, []):
            graph = copy.deepcopy(self.graph)
            graph["pose_carry"]["inputs"]["speech_guide_key"] = value
            self.assertNotEqual(planner.preparation_fingerprint(graph), baseline)
        for identity, field in (("char_ref", "positive_coords"),
                                ("pose_carry", "artist_field")):
            graph = copy.deepcopy(self.graph)
            graph[identity]["inputs"][field] = ""
            self.assertNotEqual(planner.preparation_fingerprint(graph), baseline)

    def make_speech_guide(self):
        """Build a tiny approved guide fixture without loading or decoding media."""
        self.mask_review["clip"].update({"frames": 84, "duration": 84 / 24})
        (self.review_dir / "review.json").write_text(json.dumps(self.mask_review), encoding="utf-8")
        project = copy.deepcopy(self.project)
        project["audio"] = {"file": "speech.wav", "sha": digest("approved speech")}
        project["config"]["audio_id"] = "b" * 32
        project["config"]["lip_sync"] = True
        project["config"]["audio_start"] = 0.5
        project["approval"] = studio.prep_key(project)
        project_path = self.root / "genj" / "studio" / (project["id"] + ".json")
        saved_project = copy.deepcopy(project)
        saved_project["opening_approval"] = None
        project_path.write_text(json.dumps(saved_project), encoding="utf-8")

        key_data = {
            "preparation_approval": project["approval"],
            "opening_sha": project["opening_input"]["sha"],
            "opening_approval": project["opening_approval"],
            "source": {"review": self.review_id, "source_sha": self.source_sha,
                       "frames": 84, "guide_frames": 88},
            "audio_sha": project["audio"]["sha"],
            "audio_start": 0.5,
        }
        guide_key = hashlib.sha256(planner.canonical(key_data).encode("utf-8")).hexdigest()
        guide_sha = digest("approved generated guide")
        guide_dir = self.root / "genj" / "wan_speech_guides"
        guide_dir.mkdir(parents=True, exist_ok=True)
        guide_file = guide_dir / (guide_key + "_test.mp4")
        guide_file.write_bytes(b"metadata-only fixture; never decoded")
        record = {"state": "complete", "guide_key": guide_key, "sha": guide_sha,
                  "key_data": key_data, "path": str(guide_file)}
        manifest = guide_dir / (guide_key + ".json")
        manifest.write_text(json.dumps(record), encoding="utf-8")

        graph = copy.deepcopy(self.graph)
        graph["pose_carry"]["inputs"].update({"speech_guide_key": guide_key,
                                                "speech_guide_sha": guide_sha})
        graph["part_save"]["inputs"].update({"speech_guide_key": guide_key,
                                               "speech_guide_sha": guide_sha})
        guide_loader_id = "81:guide:loader"
        graph[guide_loader_id] = {"class_type": "VHS_LoadVideoFFmpegPath", "inputs": {
            "video": str(guide_file), "force_rate": 24.0, "custom_width": 0,
            "custom_height": 0, "frame_load_cap": 81, "start_time": 0.0, "format": "None"}}
        graph["guide_size"] = {"class_type": "GetImageSizeAndCount", "inputs": {
            "image": [guide_loader_id, 0]}}
        graph["guide_face"] = {"class_type": "PoseAndFaceDetection", "inputs": {
            "model": ["onnx", 0], "images": [guide_loader_id, 0],
            "width": ["guide_size", 1], "height": ["guide_size", 2], "face_padding": 0}}
        graph["part_save"]["inputs"]["face"] = ["guide_face", 1]
        return project, graph

    def test_initial_plan_seeds_guard_before_graph_import_and_preserves_inputs(self):
        original_project, original_graph = copy.deepcopy(self.project), copy.deepcopy(self.graph)
        result = self.plan()
        self.assertEqual(result["action"], "prepare")
        self.assertEqual(result["progress"]["next_start"], 0)
        self.assertEqual(result["progress"]["next_count"], 81)
        self.assertEqual(result["graph"]["window"]["inputs"]["start_frame"], [result["guard"]["semantic_id"], 1])
        self.assertEqual(result["graph"]["window"]["inputs"]["frame_count"], [result["guard"]["semantic_id"], 2])
        self.assertEqual(result["graph"]["pose_carry"]["inputs"]["cache_key"], [result["guard"]["semantic_id"], 0])
        self.assertEqual(result["graph"]["part_save"]["inputs"]["cache_key"], [result["guard"]["semantic_id"], 0])
        self.assertEqual(result["guard"]["node_id"], result["guard"]["semantic_id"])
        self.assertEqual(result["guard"]["role_id"], "zura.wan.guard")
        self.assertTrue(all("node_id" in item and "class_type" in item for item in result["patches"]))
        self.assertFalse(any(item["class_type"] == "ZuraWanGraphQueueGuard" for item in result["patches"]))
        window_patch = next(item for item in result["patches"] if item["role_id"] == "zura.wan.window")
        self.assertNotIn("inputs", window_patch)
        self.assertEqual(window_patch["connections"]["start_frame"],
                         {"source_role": "zura.wan.guard", "output": 1})
        guard = result["graph"][result["guard"]["semantic_id"]]
        self.assertEqual(guard["class_type"], "ZuraWanGraphQueueGuard")
        self.assertEqual(guard["inputs"]["plan_json"], result["guard"]["plan_json"])
        self.assertEqual(self.project, original_project)
        self.assertEqual(self.graph, original_graph)
        self.assertEqual(result["graph"]["pose_draw"]["inputs"], original_graph["pose_draw"]["inputs"])
        self.assertEqual(result["role_ids"]["window"], "zura.wan.window")

    def test_existing_colon_qualified_guard_identity_is_reused_exactly(self):
        first = self.plan()
        colon_id = "12:34:56"
        graph = copy.deepcopy(first["graph"])
        graph[colon_id] = graph.pop(first["guard"]["semantic_id"])
        for node in graph.values():
            for key, value in list(node["inputs"].items()):
                if type(value) is list and len(value) == 2 and value[0] == first["guard"]["semantic_id"]:
                    node["inputs"][key] = [colon_id, value[1]]
        result = self.plan(graph, context=first["context"])
        self.assertEqual(result["guard"]["semantic_id"], colon_id)
        self.assertEqual(result["guard"]["node_id"], colon_id)
        self.assertEqual(result["graph"]["window"]["inputs"]["start_frame"], [colon_id, 1])

    def test_queue_guard_checks_real_prompt_recipe_and_receipt_cursor(self):
        result = self.plan()
        guard_id = result["guard"]["semantic_id"]
        node = guard_module.ZuraWanGraphQueueGuard()
        self.assertEqual(node.validate(result["guard"]["plan_json"], result["graph"], guard_id),
                         (result["context"]["context_key"], 0, 81, 0.0))
        changed = copy.deepcopy(result["graph"])
        changed["pose_draw"]["inputs"]["retarget_padding"] = 2
        with self.assertRaisesRegex(ValueError, "Update section before queuing.*settings changed"):
            node.validate(result["guard"]["plan_json"], changed, guard_id)

    def test_selected_speech_guide_tracks_full_81_frame_and_three_frame_tail(self):
        project, graph = self.make_speech_guide()
        first = self.plan(graph, project)
        guide_patch = next(item for item in first["patches"]
                           if item["role_id"] == "zura.wan.guide_loader")
        guard_id = first["guard"]["semantic_id"]
        self.assertEqual(guide_patch["node_id"], "81:guide:loader")
        self.assertEqual(guide_patch["class_type"], "VHS_LoadVideoFFmpegPath")
        self.assertNotIn("inputs", guide_patch)
        self.assertEqual(guide_patch["connections"], {
            "frame_load_cap": {"source_role": "zura.wan.guard", "output": 2},
            "start_time": {"source_role": "zura.wan.guard", "output": 3},
        })
        self.assertEqual(first["graph"]["81:guide:loader"]["inputs"]["frame_load_cap"], [guard_id, 2])
        self.assertEqual(first["graph"]["81:guide:loader"]["inputs"]["start_time"], [guard_id, 3])
        self.assertEqual(first["graph"]["81:guide:loader"]["inputs"]["force_rate"], 24.0)
        self.assertEqual(first["progress"]["next_count"], 81)

        resumed_cold_graph = copy.deepcopy(graph)
        resumed_cold_graph["window"]["inputs"].update(start_frame=81, frame_count=3)
        resumed_cold_graph["81:guide:loader"]["inputs"].update(frame_load_cap=3, start_time=81 / 24.0)
        with patch.object(runtime, "scan_parts", return_value=([], [], 81)):
            second = self.plan(resumed_cold_graph, project, first["context"])
        self.assertEqual(second["progress"]["next_start"], 81)
        self.assertEqual(second["progress"]["next_count"], 3)
        self.assertEqual(second["context"]["context_key"], first["context"]["context_key"])
        self.assertEqual(second["graph"]["81:guide:loader"]["inputs"]["frame_load_cap"],
                         [guard_id, 2])
        self.assertEqual(second["graph"]["81:guide:loader"]["inputs"]["start_time"],
                         [guard_id, 3])
        with patch.object(runtime, "scan_parts", return_value=([], [], 81)):
            guarded = guard_module.ZuraWanGraphQueueGuard().validate(
                second["guard"]["plan_json"], second["graph"], guard_id)
        self.assertEqual(guarded, (first["context"]["context_key"], 81, 3, 81 / 24.0))

    def test_queue_guard_rejects_wrong_selected_guide_cursor_edges(self):
        project, graph = self.make_speech_guide()
        result = self.plan(graph, project)
        guard_id = result["guard"]["semantic_id"]
        for field, wrong_output in (("frame_load_cap", 3), ("start_time", 2)):
            with self.subTest(field=field):
                changed = copy.deepcopy(result["graph"])
                changed["81:guide:loader"]["inputs"][field] = [guard_id, wrong_output]
                with self.assertRaisesRegex(ValueError, "selected facial guide timeline"):
                    guard_module.ZuraWanGraphQueueGuard().validate(
                        result["guard"]["plan_json"], changed, guard_id)

    def test_next_section_rejects_changed_selected_guide_file_stamp(self):
        project, graph = self.make_speech_guide()
        first = self.plan(graph, project)
        guide_file = Path(graph["81:guide:loader"]["inputs"]["video"])
        stat = guide_file.stat()
        os.utime(guide_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        with self.assertRaisesRegex(ValueError, "selected facial guide file changed"):
            self.plan(first["graph"], project, first["context"])

    def test_selected_guide_rate_and_literal_timeline_must_match_approval(self):
        project, graph = self.make_speech_guide()
        wrong_rate = copy.deepcopy(graph)
        wrong_rate["81:guide:loader"]["inputs"]["force_rate"] = 25
        with self.assertRaisesRegex(ValueError, "24 fps"):
            self.plan(wrong_rate, project)
        wrong_count = copy.deepcopy(graph)
        wrong_count["81:guide:loader"]["inputs"]["frame_load_cap"] = 83
        with self.assertRaisesRegex(ValueError, "match the bounded window"):
            self.plan(wrong_count, project)

        first = self.plan(graph, project)
        edited = copy.deepcopy(first["graph"])
        edited["81:guide:loader"]["inputs"]["custom_width"] = 640
        fork = self.plan(edited, project, first["context"])
        self.assertTrue(fork["progress"]["recipe_forked"])
        self.assertEqual(fork["progress"]["next_start"], 0)

    def test_vhs_cursor_hash_exclusion_is_limited_to_selected_guide_node(self):
        graph = {
            "video": {"class_type": "VHS_LoadVideoFFmpegPath", "inputs": {
                "video": "artist-source.mp4", "force_rate": 24,
                "frame_load_cap": 81, "start_time": 0.0}},
            "save": {"class_type": "ZuraWanSavePreparationPart", "inputs": {
                "frames": ["video", 0]}},
        }
        first = planner.preparation_fingerprint(graph, saver_id="save")
        changed = copy.deepcopy(graph)
        changed["video"]["inputs"]["start_time"] = 3.375
        self.assertNotEqual(first, planner.preparation_fingerprint(changed, saver_id="save"))

    def test_queue_guard_rejects_new_receipts_after_plan_without_reading_parts(self):
        result = self.plan()
        with patch.object(runtime, "scan_parts", return_value=([], [], 81)):
            with self.assertRaisesRegex(ValueError, "Update section before queuing.*progress changed"):
                guard_module.ZuraWanGraphQueueGuard().validate(
                    result["guard"]["plan_json"], result["graph"], result["guard"]["semantic_id"])

    def test_queue_guard_rechecks_current_saved_approval_record(self):
        result = self.plan()
        project_path = self.root / "genj" / "studio" / (self.project["id"] + ".json")
        saved = json.loads(project_path.read_text(encoding="utf-8"))
        saved["config"]["duration"] = 3.0
        project_path.write_text(json.dumps(saved), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Update section before queuing.*mask approval is stale"):
            guard_module.ZuraWanGraphQueueGuard().validate(
                result["guard"]["plan_json"], result["graph"], result["guard"]["semantic_id"])

    def test_queue_guard_allows_unsaved_visible_opening_approval_only_for_exact_image(self):
        result = self.plan()
        project_path = self.root / "genj" / "studio" / (self.project["id"] + ".json")
        saved = json.loads(project_path.read_text(encoding="utf-8"))
        self.assertIsNone(saved["opening_approval"])
        self.assertEqual(guard_module.ZuraWanGraphQueueGuard().validate(
            result["guard"]["plan_json"], result["graph"], result["guard"]["semantic_id"]),
            (result["context"]["context_key"], 0, 81, 0.0))
        saved["opening_input"]["sha"] = digest("different visible opening")
        project_path.write_text(json.dumps(saved), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Update section before queuing.*opening appearance changed"):
            guard_module.ZuraWanGraphQueueGuard().validate(
                result["guard"]["plan_json"], result["graph"], result["guard"]["semantic_id"])

    def test_actual_browser_json_roundtrip_preserves_context_key_and_nanosecond_stamps(self):
        project, graph = self.make_speech_guide()
        paths = planner._render_cache_paths(self.root, self.review_id, 1280, 84)
        for index, value in enumerate(paths.values()):
            path = Path(value)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"metadata-only render cache fixture")
            timestamp = 1_700_000_000_123_456_700 + index * 100
            os.utime(path, ns=(timestamp, timestamp))

        result = self.plan(graph, project)
        expected_source_stamp = Path(paths["source"]).stat().st_mtime_ns
        expected_mask_stamp = Path(paths["mask"]).stat().st_mtime_ns
        context = copy.deepcopy(result["context"])
        self.assertEqual(context["render_cache_stamps"]["source"]["mtime_ns"],
                         str(expected_source_stamp))
        self.assertEqual(context["render_cache_stamps"]["mask"]["mtime_ns"],
                         str(expected_mask_stamp))
        self.assertEqual(context["key_payload"]["project_pins"]["start"], 0.0)
        guide_path = Path(graph["81:guide:loader"]["inputs"]["video"])
        self.assertEqual(context["guide_pin"]["mtime_ns"], str(guide_path.stat().st_mtime_ns))

        large_stamp = 1_800_000_000_123_456_789
        context["merge_cache_stamp"] = planner._browser_file_pin({"path": "cache.pt", "mtime_ns": large_stamp})
        roundtripped_context = javascript_json_roundtrip(context)
        roundtripped_graph = javascript_json_roundtrip(result["graph"])
        self.assertEqual(roundtripped_context["render_cache_stamps"]["source"]["mtime_ns"],
                         str(expected_source_stamp))
        self.assertEqual(roundtripped_context["guide_pin"]["mtime_ns"], str(guide_path.stat().st_mtime_ns))
        self.assertEqual(roundtripped_context["merge_cache_stamp"]["mtime_ns"], str(large_stamp))
        self.assertEqual(roundtripped_context["key_payload"]["project_pins"]["start"], 0)

        next_result = self.plan(roundtripped_graph, project, roundtripped_context)
        self.assertEqual(next_result["context"]["context_key"], context["context_key"])

    def test_recipe_edit_forks_context_while_render_only_edits_reuse_motion(self):
        first = self.plan()
        edited_recipe = copy.deepcopy(first["graph"])
        edited_recipe["pose_draw"]["inputs"]["retarget_padding"] = 3
        fork = self.plan(edited_recipe, context=first["context"])
        self.assertTrue(fork["progress"]["recipe_forked"])
        self.assertNotEqual(fork["context"]["context_key"], first["context"]["context_key"])
        self.assertEqual(fork["progress"]["next_start"], 0)
        render_edit = copy.deepcopy(first["graph"])
        render_edit["render_seed"] = {"class_type": "PrimitiveInt", "inputs": {"value": 999}}
        project_edit = copy.deepcopy(self.project)
        project_edit["config"]["seed"] = 999
        project_edit["config"]["prompt"] = "Different prompt for the render"
        reused = self.plan(render_edit, project_edit, first["context"])
        self.assertEqual(reused["context"]["context_key"], first["context"]["context_key"])
        self.assertFalse(reused["progress"]["recipe_forked"])

    def test_graph_resolution_change_forks_motion_without_reapproving_mask(self):
        first = self.plan()
        graph = copy.deepcopy(first["graph"])
        graph["source"]["inputs"]["render_long_edge"] = 1920
        graph["window"]["inputs"].update(start_frame=0, frame_count=41)
        result = self.plan(graph, context=first["context"])
        self.assertEqual(result["progress"]["section_limit"], 41)
        self.assertEqual(result["progress"]["next_count"], 41)
        self.assertEqual(result["context"]["project_pins"]["resolution"], 1920)
        self.assertNotEqual(result["context"]["context_key"], first["context"]["context_key"])

    def test_512_resolution_is_guarded_with_81_frame_section(self):
        graph = copy.deepcopy(self.graph)
        graph["source"]["inputs"]["render_long_edge"] = 512
        result = self.plan(graph)
        self.assertEqual(result["context"]["project_pins"]["resolution"], 512)
        self.assertEqual(result["progress"]["section_limit"], 81)
        self.assertEqual(guard_module.ZuraWanGraphQueueGuard().validate(
            result["guard"]["plan_json"], result["graph"], result["guard"]["semantic_id"]),
            (result["context"]["context_key"], 0, 81, 0.0))

    def test_all_studio_resolutions_are_accepted_and_use_the_bounded_limit(self):
        for resolution in planner.RESOLUTIONS:
            with self.subTest(resolution=resolution):
                graph = copy.deepcopy(self.graph)
                graph["source"]["inputs"]["render_long_edge"] = resolution
                graph["window"]["inputs"]["frame_count"] = 41 if resolution == 1920 else 81
                result = self.plan(graph)
                expected_limit = 41 if resolution == 1920 else 81
                self.assertEqual(result["progress"]["section_limit"], expected_limit)
                self.assertEqual(result["context"]["project_pins"]["resolution"], resolution)

    def test_head_scope_change_forks_recipe_without_reapproving_same_review(self):
        first = self.plan()
        graph = copy.deepcopy(first["graph"])
        graph["pose_carry"]["inputs"]["scope"] = "head"
        graph["part_save"]["inputs"]["scope"] = "head"
        result = self.plan(graph, context=first["context"])
        self.assertTrue(result["progress"]["recipe_forked"])
        self.assertEqual(result["context"]["project_pins"]["scope"], "head")
        self.assertNotEqual(result["context"]["context_key"], first["context"]["context_key"])
        self.assertEqual(guard_module.ZuraWanGraphQueueGuard().validate(
            result["guard"]["plan_json"], result["graph"], result["guard"]["semantic_id"]),
            (result["context"]["context_key"], 0, 81, 0.0))

    def test_saved_project_scope_change_without_new_approval_is_rejected(self):
        result = self.plan()
        project_path = self.root / "genj" / "studio" / (self.project["id"] + ".json")
        saved = json.loads(project_path.read_text(encoding="utf-8"))
        saved["config"]["scope"] = "head"
        project_path.write_text(json.dumps(saved), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Update section before queuing.*mask approval is stale"):
            guard_module.ZuraWanGraphQueueGuard().validate(
                result["guard"]["plan_json"], result["graph"], result["guard"]["semantic_id"])

    def test_changed_review_approval_source_and_loader_resolution_fail_closed(self):
        first = self.plan()
        changed_project = copy.deepcopy(self.project)
        changed_project["source"]["sha"] = digest("another source")
        with self.assertRaisesRegex(ValueError, "mask approval is stale"):
            self.plan(project=changed_project, context=first["context"])
        (self.review_dir / "review.json").write_text(json.dumps({
            **self.mask_review, "files": {"mask.mp4": digest("different reviewed mask")}}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "approved review changed"):
            self.plan(context=first["context"])
        (self.review_dir / "review.json").write_text(json.dumps(self.mask_review), encoding="utf-8")
        wrong_loader = copy.deepcopy(first["graph"])
        wrong_loader["source"]["inputs"]["render_long_edge"] = 1000
        with self.assertRaisesRegex(ValueError, "Choose a supported source resolution"):
            self.plan(wrong_loader, context=first["context"])

    def test_new_approved_source_interval_cannot_reuse_prior_motion_context(self):
        first = self.plan()
        new_review = "shot_fedcba9876543210"
        new_review_dir = self.root / "genj" / "reviews" / new_review
        new_review_dir.mkdir(parents=True)
        changed_project = copy.deepcopy(self.project)
        changed_project["review"] = new_review
        changed_project["config"]["start"] = 0.25
        changed_project["config"]["duration"] = 2.0
        changed_project["approval"] = studio.prep_key(changed_project)
        changed_review = copy.deepcopy(self.mask_review)
        changed_review["shot_id"] = new_review
        changed_review["clip"].update({"start": 0.25, "duration": 2.0, "frames": 48})
        (new_review_dir / "review.json").write_text(json.dumps(changed_review), encoding="utf-8")
        graph = copy.deepcopy(first["graph"])
        graph["source"]["inputs"]["shot_id"] = new_review
        graph["source"]["inputs"]["approved_shot_id"] = new_review
        with self.assertRaisesRegex(ValueError, "source, review or appearance changed"):
            self.plan(graph, changed_project, first["context"])

    def test_old_full_image_route_and_malformed_graph_rejected(self):
        bad = copy.deepcopy(self.graph)
        bad["old_frames"] = {"class_type": "ZuraWanReviewedFrames", "inputs": {}}
        with self.assertRaisesRegex(ValueError, "old full-frame IMAGE"):
            self.plan(bad)
        bad = copy.deepcopy(self.graph)
        bad["window"]["inputs"]["frame_count"] = ["missing", 0]
        with self.assertRaisesRegex(ValueError, "cursor is not a literal or guarded"):
            self.plan(bad)

    def test_signal_expansion_preserves_literal_pairs_and_expands_real_readers(self):
        graph = {
            "source": {"class_type": "PrimitiveInt", "inputs": {"value": 5}},
            "signals": {"class_type": "ZuraStudioSignals", "inputs": {
                "keys": '["count"]', "value_0": 41}},
            "reader": {"class_type": "ZuraStudioReadSignal", "inputs": {
                "stage_data": ["signals", 0], "key": "count"}},
            "consumer": {"class_type": "PrimitiveInt", "inputs": {
                "signal": ["reader", 0], "literal": ["source", "two"]}},
        }
        expanded = planner.expand_stage_signals(graph)
        self.assertNotIn("signals", expanded)
        self.assertNotIn("reader", expanded)
        self.assertEqual(expanded["consumer"]["inputs"]["signal"], 41)
        self.assertEqual(expanded["consumer"]["inputs"]["literal"], ["source", "two"])
        cycle = copy.deepcopy(graph)
        cycle["signals"]["inputs"]["value_0"] = ["reader", 0]
        with self.assertRaisesRegex(ValueError, "cycle"):
            planner.expand_stage_signals(cycle)

    def test_finish_is_one_node_and_render_uses_explicit_cache_key_override(self):
        first = self.plan()
        metadata = runtime.metadata_for_scope("person")
        fake_paths = [str(self.root / "genj" / "wan_preparation_parts" / "a" / "part.json")]
        with patch.object(runtime, "scan_parts", return_value=(fake_paths, [{}] * 2, 100)):
            finish = self.plan(first["graph"], context=first["context"])
        self.assertEqual(finish["action"], "merge")
        self.assertEqual(len(finish["graph"]), 1)
        self.assertEqual(next(iter(finish["graph"].values()))["class_type"], "ZuraWanMergePreparation")
        key = first["context"]["context_key"]
        cache_path = self.root / "genj" / "wan_conditioning" / (key + ".pt")
        cache_path.parent.mkdir(parents=True)
        cache_path.write_bytes(b"metadata-only test sentinel; never loaded")
        with patch.object(runtime, "scan_parts", return_value=(fake_paths, [{}] * 2, 100)):
            render = self.plan(first["graph"], context=first["context"])
        self.assertEqual(render["action"], "render")
        self.assertEqual(render["render_request"]["cache_key_override"], key)
        self.assertTrue(render["render_request"]["require_streamed_sampler"])


if __name__ == "__main__":
    unittest.main()
