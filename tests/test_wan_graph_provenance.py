"""Editable native Wan speech graphs reject mismatched inputs before inference."""
import copy
import hashlib
import json
import math
import sys
import unittest
from unittest.mock import patch

import test_wan_speech as fixtures
import torch

speech, wan, adapters = fixtures.speech, fixtures.wan, fixtures.adapters


class EditableSpeechTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.GuideTests("test_audio_keeps_rate_channels_silence_and_selected_samples")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.project = f.project
        self.source = f.base / "source.mp4"
        self.source.write_bytes(b"synthetic reviewed source, not a learned render")
        f.manifest["clip"]["source_hash"] = speech.digest(self.source)
        graph, self.path, history = f.save_and_history()
        self.record = speech.record_guide(self.project, history)
        self.key = self.record["guide_key"]
        self.opening = torch.full((1, 8, 8, 3), .5)
        images = torch.full((24, 8, 8, 3), .25)
        self.audio = {"waveform": torch.zeros(1, 1, 24000), "sample_rate": 24000}
        self.audio["waveform"][..., :2400] = f.wave[:, 2400:]
        self.soundtrack = f.base / "selected.wav"
        import soundfile
        soundfile.write(str(self.soundtrack), self.audio["waveform"][0].numpy().T, 24000, subtype="FLOAT")
        self.details = {"review_shot_id": self.project["review"], "source": str(self.source),
            "source_hash": speech.digest(self.source), "start": .25, "duration": 1,
            "frames": 24, "fps": 24, "audio_mode": "reference", "audio_source": str(self.soundtrack),
            "audio_hash": speech.digest(self.soundtrack)}
        self.video = {"images": images, "audio": self.audio, "frame_rate": 24}
        self.inputs = dict(frames=images, mask=torch.ones(24, 8, 8), pose=images.clone(), face=images.clone(),
            reference=self.opening, scope="person", speech_guide_key=self.key, speech_guide_sha=self.record["sha"])
        self.footage = adapters.ZuraWanPackPreparation().pack(**self.inputs)[0]
        import folder_paths
        f.enter(patch.object(folder_paths, "get_annotated_filepath", side_effect=lambda filename: str(f.base / filename)))
        native_nodes = sys.modules["nodes"]
        f.enter(patch.object(native_nodes, "LoadImage", lambda: type("ImageLoader", (), {
            "load_image": lambda _, filename: (self.opening.clone(), None)})(), create=True))
        original_load = sys.modules["comfy_extras.nodes_audio"].load
        f.enter(patch.object(sys.modules["comfy_extras.nodes_audio"], "load", side_effect=lambda filename:
            (self.audio["waveform"][0].clone(), 24000) if filename == str(self.soundtrack) else original_load(filename)))

    def verify(self, **overrides):
        values = dict(footage=self.footage, selected_video=self.video, clip_details=self.details, opening=self.opening,
            approved_opening_file="opening.png", seed=123, guide_key=self.key)
        values.update(overrides)
        return adapters.ZuraWanSpeechGuard().verify(**values)

    def assert_stale(self, reason, **overrides):
        with self.assertRaisesRegex(ValueError, reason) as error:
            self.verify(**overrides)
        self.assertIn("regenerate the facial performance", str(error.exception))
        self.assertIn("reopen the animation graph", str(error.exception))

    def test_matching_inputs_pass_through_without_changing_tensors_or_seed(self):
        footage, opening, seed = self.verify()
        self.assertIs(footage, self.footage)
        self.assertIs(opening, self.opening)
        self.assertEqual(seed, 123)
        self.assertTrue(math.isnan(adapters.ZuraWanSpeechGuard.IS_CHANGED()))

    def test_changed_selected_waveform_and_audio_offset_are_rejected(self):
        for waveform in (torch.ones(1, 1, 24000), torch.roll(self.audio["waveform"], 1200, -1)):
            video = {**self.video, "audio": {"waveform": waveform, "sample_rate": 24000}}
            self.assert_stale("selected audio or its start", selected_video=video)

    def test_changed_seed_and_opening_connection_are_rejected(self):
        self.assert_stale("performance seed changed", seed=124)
        self.assert_stale("connected character opening", opening=self.opening + .1)
        (self.fixture.base / "opening.png").write_bytes(b"changed approved image")
        self.assert_stale("approved character opening changed")

    def test_cached_or_native_pack_must_name_the_exact_verified_guide(self):
        footage = copy.deepcopy(self.footage)
        footage.pop("speech_provenance")
        self.assert_stale("prepared face motion belongs", footage=footage)
        footage["speech_provenance"] = {"guide_key": self.key, "guide_sha": "a" * 64}
        self.assert_stale("prepared face motion belongs", footage=footage)
        with self.assertRaisesRegex(ValueError, "verified native speech guide"):
            adapters.ZuraWanPackPreparation().pack(**{**self.inputs, "speech_guide_sha": ""})

    def test_actual_source_frames_source_file_and_reviewed_mask_are_rechecked(self):
        self.assert_stale("actual selected frames", selected_video={**self.video, "images": self.video["images"] + .1})
        for field, value in (("review_shot_id", "another-review"), ("start", .3), ("frames", 23), ("fps", 25)):
            self.assert_stale("selected shot or timing", clip_details={**self.details, field: value})
        self.fixture.manifest["files"]["mask.mp4"] = "different-mask"
        self.assert_stale("reviewed performer mask changed")
        self.fixture.manifest["files"]["mask.mp4"] = "approved-performer-mask"
        self.source.write_bytes(b"different source")
        self.assert_stale("source footage changed")

    def test_actual_guide_and_recipe_are_rechecked_even_with_cached_footage(self):
        manifest = speech._manifest_path(self.key)
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["key_data"]["seed"] = 456
        manifest.write_text(json.dumps(data), encoding="utf-8")
        self.assert_stale("saved facial-performance recipe changed")
        manifest.write_text(json.dumps(self.record), encoding="utf-8")
        self.path.write_bytes(b"changed MP4")
        self.assert_stale("cannot be decoded")

    def test_export_cannot_use_another_track_while_video_has_matching_speech(self):
        self.assert_stale("soundtrack no longer uses", clip_details={**self.details, "audio_mode": "original"})
        self.assert_stale("soundtrack changed on disk", clip_details={**self.details, "audio_hash": "b" * 64})
        with patch.object(sys.modules["comfy_extras.nodes_audio"], "load", return_value=(torch.ones(1, 24000), 24000)):
            self.assert_stale("final soundtrack differs")

    def test_save_and_load_preserve_reference_provenance_original_stays_unchanged(self):
        cache = "c" * 64
        result = adapters.ZuraWanSavePreparation().save(**self.inputs, cache_key=cache)
        self.assertEqual(result["result"], (cache,))
        loaded = adapters.ZuraWanLoadPreparation().load(cache)[0]
        self.assertEqual(loaded["speech_provenance"], self.footage["speech_provenance"])
        original = {k: v for k, v in self.inputs.items() if not k.startswith("speech_")}
        packed = adapters.ZuraWanPackPreparation().pack(**original)[0]
        self.assertNotIn("speech_provenance", packed)

    def test_editable_reference_graph_has_one_clean_audio_selection_and_one_seed(self):
        graph = wan.build_wan_graph(self.project, use_cache=False)
        self.assertEqual(graph["wan_reference_audio"]["inputs"]["audio"], "voice.wav")
        self.assertEqual(graph["wan_audio_selection"]["inputs"]["audio_start_seconds"], .1)
        self.assertEqual(graph["wan_speech_guard"]["inputs"]["selected_video"], ["wan_audio_selection", 0])
        self.assertEqual(graph["wan_speech_guard"]["inputs"]["clip_details"], ["wan_audio_selection", 1])
        self.assertEqual(graph["wan_render"]["inputs"]["footage"], ["wan_speech_guard", 0])
        self.assertEqual(graph["wan_render"]["inputs"]["seed"], ["wan_speech_guard", 2])
        self.assertEqual(graph["wan_opening_size"]["inputs"]["image"], ["wan_speech_guard", 1])
        self.assertEqual(graph["wan_export"]["inputs"]["clip_details"], ["wan_audio_selection", 1])
        self.assertEqual(sum(n["class_type"] == "LoadAudio" for n in graph.values()), 1)
        self.assertEqual(sum(n.get("_meta", {}).get("title") == "Performance seed" for n in graph.values()), 1)
        self.assertEqual(graph["wan_speech_guard"]["inputs"]["seed"], ["wan_performance_seed", 0])
        self.assertEqual(graph["wan_render"]["inputs"]["steps"], ["wan_steps", 0])
        self.assertEqual(graph["wan_steps"]["inputs"]["value"], 6)
        self.assertEqual(graph["wan_render"]["inputs"]["cfg"], ["wan_cfg", 0])
        self.assertEqual(graph["wan_cfg"]["inputs"]["value"], 1.0)
        self.assertEqual(graph["wan_cached"]["inputs"]["speech_guide_key"], self.key)
        self.assertEqual(graph["wan_cached"]["inputs"]["speech_guide_sha"], self.record["sha"])
        # The native bounded coordinator reads the confined review manifest,
        # unlike the legacy in-memory branch exercised above.
        from pathlib import Path
        import folder_paths
        review = Path(folder_paths.get_output_directory()) / "genj" / "reviews" / self.project["review"]
        review.mkdir(parents=True, exist_ok=True)
        (review / "review.json").write_text(json.dumps(self.fixture.manifest), encoding="utf-8")
        with patch.object(fixtures.package, "verify_review", return_value=(review, self.fixture.manifest)):
            cold = wan.build_wan_graph(self.project)
        self.assertEqual(cold["wan_save"]["inputs"]["speech_guide_sha"], self.record["sha"])
        self.assertEqual(cold["wan_save"]["class_type"], "ZuraWanSavePreparationPart")
        self.assertEqual(cold["wan_frames"]["inputs"]["frame_count"], 24)
        self.assertNotIn("wan_render", cold)

    def test_original_and_soundtrack_only_keep_source_face_without_guide(self):
        self.project["config"]["lip_sync"] = False
        for external in (False, True):
            self.project["audio"] = self.fixture.project["audio"] if external else None
            if external:
                self.project["audio"] = {"file": "voice.wav", "sha": speech.digest(self.fixture.base / "voice.wav")}
            graph = wan.build_wan_graph(self.project, use_cache=False)
            self.assertNotIn("wan_speech_guard", graph)
            self.assertNotIn("wan_performance_seed", graph)
            self.assertNotIn("wan_speech_video", graph)
            self.assertEqual(graph["wan_cached"]["inputs"]["face"], ["wan_pose_detect", 1])
            self.assertNotIn("speech_guide_key", graph["wan_cached"]["inputs"])
            self.assertEqual(sum(n["class_type"] == "LoadAudio" for n in graph.values()), int(external))
            self.assertEqual(graph["wan_export"]["inputs"]["clip_details"], ["wan_audio_selection", 1] if external else ["wan_shot", 3])
            # Original cache identity remains exactly v1.3.6's v5 recipe.
            stamps = {}
            for identity in ("wan_pose", "wan_detector"):
                folder, name = wan.WAN_MODELS[identity]
                path = self.fixture.model_paths[(folder, name)]
                from pathlib import Path
                stat = Path(path).stat()
                stamps[identity] = [name, stat.st_size, stat.st_mtime_ns]
            expected = {"version": 5, "review": self.project["review"], "character": "character", "resolution": 720,
                "scope": "person", "models": stamps, "performance_mode": "original"}
            self.assertEqual(wan.cache_key(self.project), hashlib.sha256(fixtures.studio.canonical(expected).encode()).hexdigest())

    def test_optional_lip_refinement_uses_the_same_clean_selected_video(self):
        self.project["config"]["refine_lips"] = True
        graph = wan.build_wan_graph(self.project, use_cache=False)
        self.assertEqual(graph["zura_speech_reference"]["inputs"]["video"], ["wan_audio_selection", 0])
        self.assertEqual(graph["zura_speech_0video"]["inputs"]["reference_video"], ["wan_audio_selection", 0])


if __name__ == "__main__":
    unittest.main()
