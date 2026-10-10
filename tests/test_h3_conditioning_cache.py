"""H3 caches rebuild safely; no model inference, GPU, network or saved projects."""
import copy
import hashlib
import importlib
import math
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import v2_bootstrap
import torch

NAME = "ComfyUI_zura_nodes.artist_studio"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[NAME] = package
package = sys.modules[NAME]
studio = importlib.import_module(NAME + ".studio")
h3 = importlib.import_module(NAME + ".h3")

try:
    from comfy.nested_tensor import NestedTensor
except ImportError:
    class NestedTensor:
        def __init__(self, tensors):
            self.tensors = list(tensors)


class ConditioningCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "references.pt"
        self.key = "c" * 64
        self.paths = patch.object(h3, "cache_path", return_value=self.path)
        self.paths.start()
        self.addCleanup(self.paths.stop)
        # The standalone suite uses the native .tensors container contract if
        # ComfyUI is absent. Actual torch serialisation/validation is exercised.
        nested_module = types.ModuleType("comfy.nested_tensor")
        nested_module.NestedTensor = NestedTensor
        self.nested = patch.dict(sys.modules, {"comfy.nested_tensor": nested_module})
        self.nested.start()
        self.addCleanup(self.nested.stop)
        self.data = self.payload()

    @staticmethod
    def payload():
        picture = torch.zeros(1, 24, 1, 2, 2)
        audio = torch.zeros(1, 32, 2, 8)
        return {"version": 1,
                "positive": [[torch.zeros(1, 2, 5120), {
                    "minimax_token_tags": torch.zeros(2, dtype=torch.int64),
                    "minimax_refs": [
                        {"kind": "image", "latent_h": 2, "latent_w": 2, "latent": picture},
                        {"kind": "audio", "ref_audio_t": 8, "audio_latent": audio}],
                    "minimax_keyframes": [{"resolved_frame_index": 0, "latent": picture},
                                           {"resolved_frame_index": 0, "audio_latent": audio}]}]],
                "latent": {"samples": {"genj_h3_nested_tensors": [torch.zeros(1, 24, 37, 2, 2), torch.zeros(1, 32, 2, 207)]}}}

    def save(self, data=None):
        torch.save(self.data if data is None else data, self.path)

    def project(self):
        config = studio.clean_config({"engine": "h3", "quality": "fast", "duration": 2})
        return {"id": "a" * 32, "source": {"file": "source.mp4", "sha": "source", "duration": 2},
                "character": {"file": "character.png", "sha": "character"}, "config": config,
                "review": "shot_" + "a" * 16, "opening_key": "look", "opening_approval": "look",
                "opening_input": {"file": "opening.png", "sha": "look"}}

    def graph(self):
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                patch.object(h3, "cache_key", return_value=self.key), \
                patch.object(package, "verify_review", return_value=(None, {"clip": {"frames": 48}}), create=True):
            return h3.build_h3_graph(self.project())

    def test_genuine_native_cache_roundtrips_on_cpu_with_safe_loading(self):
        latent = {"samples": NestedTensor(self.data["latent"]["samples"]["genj_h3_nested_tensors"])}
        h3.GenjSaveH3Conditioning().save(self.data["positive"], latent, self.key)
        with patch.object(torch, "load", wraps=torch.load) as load:
            self.assertTrue(h3.cache_valid(self.key))
            positive, restored = h3.GenjLoadH3Conditioning().load(self.key)
        for call in load.call_args_list:
            self.assertEqual(call.kwargs["map_location"], "cpu")
            self.assertIs(call.kwargs["weights_only"], True)
        self.assertTrue(torch.equal(positive[0][0], self.data["positive"][0][0]))
        self.assertEqual(restored["samples"].tensors[0].shape, (1, 24, 37, 2, 2))
        self.assertEqual(restored["samples"].tensors[1].shape, (1, 32, 2, 207))
        self.assertEqual(restored["samples"].tensors[0].device.type, "cpu")

    def test_missing_empty_truncated_and_malformed_are_not_selected_or_deleted(self):
        self.assertFalse(h3.cache_valid(self.key))
        neighbour = Path(self.tmp.name) / "other_references.pt"
        neighbour.write_bytes(b"neighbour cache must stay untouched")
        for body in (b"", b"not a torch cache", b"PK\x03\x04truncated"):
            with self.subTest(body=body):
                self.path.write_bytes(body)
                self.assertFalse(h3.cache_valid(self.key))
                self.assertEqual(self.path.read_bytes(), body)
                self.assertEqual(neighbour.read_bytes(), b"neighbour cache must stay untouched")

    def test_wrong_version_and_positive_conditioning_are_rejected(self):
        cases = []
        for version in (2, True, None):
            data = copy.deepcopy(self.data)
            data["version"] = version
            cases.append(data)
        for positive in ([], [[torch.zeros(1, 5120), {}]], [[torch.zeros(1, 2, 8), {}]],
                         [[torch.zeros(1, 2, 5120), "bad metadata"]],
                         [[torch.full((1, 2, 5120), float("nan")), {}]]):
            data = copy.deepcopy(self.data)
            data["positive"] = positive
            cases.append(data)
        for data in cases:
            with self.subTest(version=data["version"], positive_type=type(data["positive"]).__name__):
                self.save(data)
                self.assertFalse(h3.cache_valid(self.key))

    def test_missing_wrong_channels_geometry_and_unpaired_timelines_are_rejected(self):
        cases = []
        for streams in ([torch.zeros(1, 24, 2, 2, 2)],
                        [torch.zeros(1, 32, 2, 2, 2), torch.zeros(1, 32, 2, 8)],
                        [torch.zeros(1, 24, 2, 2, 2), torch.zeros(1, 32, 3, 8)],
                        [torch.zeros(1, 24, 2, 2, 3), torch.zeros(1, 32, 2, 8)],
                        [torch.zeros(1, 24, 3, 2, 2), torch.zeros(1, 32, 2, 8)],
                        [torch.zeros(1, 24, 2, 2, 2), torch.zeros(1, 32, 2, 7)]):
            data = copy.deepcopy(self.data)
            data["latent"]["samples"]["genj_h3_nested_tensors"] = streams
            cases.append(data)
        cases.append({**self.data, "latent": {"samples": torch.zeros(1, 24, 2, 2, 2)}})
        for data in cases:
            self.save(data)
            self.assertFalse(h3.cache_valid(self.key))

    def test_damaged_native_reference_and_guide_metadata_are_rejected(self):
        for field, value in (("minimax_refs", "bad blocks"), ("minimax_refs", [{"kind": "alien"}]),
                             ("minimax_refs", [{"kind": "audio", "audio_latent": torch.zeros(1, 24, 2, 8)}]),
                             ("minimax_keyframes", [{"resolved_frame_index": -1, "latent": torch.zeros(1, 24, 1, 2, 2)}])):
            with self.subTest(field=field):
                data = copy.deepcopy(self.data)
                data["positive"][0][1][field] = value
                self.save(data)
                self.assertFalse(h3.cache_valid(self.key))

    def test_corrupt_cache_builds_existing_native_reference_rebuild(self):
        self.path.write_bytes(b"truncated references")
        graph = self.graph()
        self.assertNotIn("h3_cached", graph)
        self.assertIn("h3_references", graph)
        self.assertEqual(graph["h3_schedule"]["inputs"]["steps"], 8)
        self.assertEqual(graph["h3_sample"]["inputs"]["latent_image"], ["h3_locked_audio", 0])
        rebuilding = h3.reference_graph(graph, self.key)
        self.assertIn("h3_save_references", rebuilding)
        self.assertIn("h3_speech", rebuilding)
        self.assertNotIn("h3_sample", rebuilding)
        self.assertEqual(self.path.read_bytes(), b"truncated references")

    def test_healthy_short_context_rebuilds_for_current_take_without_deleting_cache(self):
        shorter = copy.deepcopy(self.data)
        shorter["latent"]["samples"]["genj_h3_nested_tensors"] = [
            torch.zeros(1, 24, 17, 2, 2), torch.zeros(1, 32, 2, 93)]
        self.save(shorter)
        before = self.path.read_bytes()
        self.assertTrue(h3.cache_valid(self.key), "The historical native payload remains valid data")
        self.assertTrue(h3.cache_valid(self.key, expected_frames=56))
        self.assertFalse(h3.cache_valid(self.key, expected_frames=124))
        graph = self.graph()
        self.assertNotIn("h3_cached", graph)
        self.assertIn("h3_references", graph)
        self.assertEqual(self.path.read_bytes(), before)

    def test_valid_cache_is_selected_with_content_fingerprint(self):
        self.save()
        graph = self.graph()
        self.assertNotIn("h3_references", graph)
        digest = graph["h3_cached"]["inputs"]["cache_digest"]
        self.assertEqual(digest, hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(graph["h3_preserve_background"]["inputs"]["latent"], ["h3_cached", 1])
        h3.GenjLoadH3Conditioning().load(self.key, digest)

    def test_runtime_corruption_or_valid_overwrite_stops_with_clear_recovery(self):
        for corrupt in (True, False):
            with self.subTest(corrupt=corrupt):
                self.save()
                digest = self.graph()["h3_cached"]["inputs"]["cache_digest"]
                if corrupt:
                    self.path.write_bytes(b"changed while waiting in the queue")
                else:
                    replacement = copy.deepcopy(self.data)
                    replacement["positive"][0][0].fill_(1)
                    self.save(replacement)
                with self.assertRaisesRegex(ValueError, "Generate this take again in Zura Studio"):
                    h3.GenjLoadH3Conditioning().load(self.key, digest)

    def test_missing_cache_loader_is_friendly_and_change_check_still_runs(self):
        with self.assertRaisesRegex(ValueError, "approved shot and character look are kept"):
            h3.GenjLoadH3Conditioning().load(self.key)
        with patch.object(package, "digest_file", side_effect=FileNotFoundError(), create=True):
            self.assertTrue(math.isnan(h3.GenjLoadH3Conditioning.IS_CHANGED(self.key)))


if __name__ == "__main__":
    unittest.main()
