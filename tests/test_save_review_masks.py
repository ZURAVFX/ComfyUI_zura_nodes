"""The review saver keeps the genuine selection beside the combined edit mask."""
import hashlib
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

import v2_bootstrap


class _SavedVideo:
    def __init__(self, components):
        self.components = components

    def save_to(self, path):
        Path(path).write_bytes(b"guide-video")


class _LoadedVideo:
    def __init__(self, path):
        self.path = str(path)


class SaveReviewMaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        latest = types.ModuleType("comfy_api.latest")
        latest.InputImpl = types.SimpleNamespace(VideoFromComponents=_SavedVideo, VideoFromFile=_LoadedVideo)
        latest.Types = types.SimpleNamespace(VideoComponents=lambda **values: values)
        cls.namespace = {"__name__": "zura_review_mask_unit"}
        source = (v2_bootstrap.ROOT / "artist_studio" / "__init__.py").read_text(encoding="utf8")
        with patch.dict(sys.modules, {"comfy_api.latest": latest}):
            exec(compile(source.split("NODE_CLASS_MAPPINGS =")[0], "artist_studio/__init__.py", "exec"), cls.namespace)

    def save_fixture(self, output_root, performer_mask=None):
        output_root = Path(output_root)
        source = output_root / "source.mp4"
        source.write_bytes(b"source-video")
        source_frames = torch.zeros(3, 4, 6, 3)
        guide_frames = torch.full((3, 4, 6, 3), 0.25)
        combined = torch.zeros(3, 2, 3)
        combined[:, :, 1:] = 1
        audio = {"waveform": torch.ones(1, 1, 12), "sample_rate": 24000}
        details = {"selected_path": str(source), "source": str(source),
                   "source_hash": self.namespace["digest_file"](source), "start": 0,
                   "duration": 0.125, "frames": 3, "width": 6, "height": 4, "full_source": False}
        encoded = {}

        def encode(path, frames, fps=24):
            encoded[Path(path).name] = frames.detach().cpu().clone()
            Path(path).write_bytes(frames.detach().cpu().numpy().tobytes())

        with patch.dict(self.namespace, {"root": lambda: output_root, "encode_frames": encode}):
            result = self.namespace["GenjSaveReview"]().save(
                details, source_frames, combined, guide_frames, audio, performer_mask=performer_mask)
        return result["result"][0], output_root / "reviews" / result["result"][0], encoded, details, source_frames, combined, guide_frames, audio

    def test_text_review_saves_resized_genuine_mask_and_binds_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            genuine = torch.zeros(3, 8, 12)
            genuine[:, 2:6, 5:10] = 1
            genuine_before = genuine.clone()
            shot_id, directory, encoded, _, _, _, _, _ = self.save_fixture(tmp, genuine)
            manifest = json.loads((directory / "review.json").read_text(encoding="utf8"))
            self.assertIn("performer_mask.mp4", manifest["files"])
            self.assertEqual(manifest["files"]["performer_mask.mp4"], self.namespace["digest_file"](directory / "performer_mask.mp4"))
            saved = encoded["performer_mask.mp4"]
            self.assertEqual(tuple(saved.shape), (3, 4, 6, 3))
            self.assertTrue(torch.equal(saved[..., 0], saved[..., 1]))
            self.assertTrue(torch.equal(saved[..., 1], saved[..., 2]))
            self.assertTrue(torch.equal(genuine, genuine_before), "Saving must not mutate the incoming selection tensor")

            changed = genuine.clone()
            changed[:, 0:2, 0:2] = 1
            changed_id, *_ = self.save_fixture(tmp, changed)
            self.assertNotEqual(shot_id, changed_id, "Distinct genuine masks must never reuse a review identity")

    def test_legacy_review_identity_and_file_set_stay_unchanged_without_optional_mask(self):
        with tempfile.TemporaryDirectory() as tmp:
            shot_id, directory, _, details, _, combined, guide, audio = self.save_fixture(tmp)
            normalized = torch.nn.functional.interpolate(combined[:, None].float(), size=(4, 6), mode="nearest")[:, 0]
            normalized = (normalized >= 0.5).float()
            legacy = hashlib.sha256(json.dumps(details, sort_keys=True).encode())
            for frames in (normalized, guide):
                for frame in frames:
                    legacy.update(frame.numpy().tobytes())
            legacy.update(audio["waveform"].numpy().tobytes())
            legacy.update(str(audio["sample_rate"]).encode())
            self.assertEqual(shot_id, "shot_" + legacy.hexdigest()[:16])
            manifest = json.loads((directory / "review.json").read_text(encoding="utf8"))
            self.assertEqual(set(manifest["files"]), {"source.mp4", "mask.mp4", "guide.mp4", "mask_review.mp4", "opening_frame.png"})

    def test_genuine_mask_requires_matching_finite_nonempty_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.mp4"
            source.write_bytes(b"source-video")
            details = {"selected_path": str(source), "source_hash": "fixture"}
            frames = torch.zeros(3, 4, 6, 3)
            combined = torch.ones(3, 2, 3)
            guide = torch.zeros_like(frames)
            audio = {"waveform": torch.zeros(1, 1, 12), "sample_rate": 24000}
            saver = self.namespace["GenjSaveReview"]()
            for invalid in (torch.ones(2, 4, 6), torch.zeros(3, 4, 6),
                            torch.full((3, 4, 6), float("nan"))):
                with self.subTest(shape=tuple(invalid.shape)), self.assertRaises(ValueError):
                    saver.save(details, frames, combined, guide, audio, performer_mask=invalid)

    def test_loader_appends_genuine_mask_and_preserves_legacy_output_order(self):
        load_node = self.namespace["GenjLoadReviewedShot"]
        self.assertEqual(load_node.RETURN_TYPES, ("VIDEO", "VIDEO", "VIDEO", "GENJ_CLIP", "VIDEO"))
        self.assertEqual(load_node.RETURN_NAMES[:4], ("source_clip", "performer_mask", "seedance_guide", "clip_details"))
        self.assertEqual(load_node.RETURN_NAMES[4], "genuine_performer_mask")
        with tempfile.TemporaryDirectory() as tmp:
            genuine = torch.zeros(3, 8, 12)
            genuine[:, 2:6, 5:10] = 1
            shot_id, directory, *_ = self.save_fixture(tmp, genuine)
            with patch.dict(self.namespace, {"root": lambda: Path(tmp)}):
                outputs = load_node().load(shot_id, shot_id)
            self.assertEqual([Path(outputs[i].path).name for i in (0, 1, 2)],
                             ["source.mp4", "mask.mp4", "guide.mp4"])
            self.assertEqual(outputs[3]["review_shot_id"], shot_id)
            self.assertEqual(outputs[4].path, str(directory / "performer_mask.mp4"))

            legacy_id, legacy_directory, *_ = self.save_fixture(tmp)
            with patch.dict(self.namespace, {"root": lambda: Path(tmp)}):
                legacy_outputs = load_node().load(legacy_id, legacy_id)
            self.assertEqual([Path(legacy_outputs[i].path).name for i in (0, 1, 2)],
                             ["source.mp4", "mask.mp4", "guide.mp4"])
            self.assertEqual(legacy_outputs[3]["review_shot_id"], legacy_id)
            self.assertEqual(legacy_outputs[4].path, str(legacy_directory / "mask.mp4"))

    def test_high_resolution_preview_trims_genuine_mask_to_review_frame_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            genuine = torch.zeros(3, 8, 12)
            genuine[:, 2:6, 5:10] = 1
            shot_id, _, *_ = self.save_fixture(tmp, genuine)
            class Stream:
                width, height, frames = 640, 480, 1
            class Container:
                streams = types.SimpleNamespace(video=[Stream()])
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    return False
            ffmpeg_calls = []
            def fake_ffmpeg(*args):
                ffmpeg_calls.append(args)
                Path(args[-1]).write_bytes(b"rendered-video")
            with patch.dict(self.namespace, {"root": lambda: Path(tmp), "ffmpeg": fake_ffmpeg}), \
                    patch.object(self.namespace["av"], "open", return_value=Container()):
                outputs = self.namespace["GenjLoadReviewedShot"]().load(
                    shot_id, shot_id, render_long_edge=256, preview_seconds=0.05)
            self.assertEqual(outputs[3]["frames"], 1)
            self.assertEqual(Path(outputs[4].path).name, "genuine_performer_mask.mp4")
            preview_call = next(args for args in ffmpeg_calls if Path(args[-1]).name == "genuine_performer_mask.mp4")
            self.assertEqual(preview_call[preview_call.index("-frames:v") + 1], 1)


if __name__ == "__main__":
    unittest.main()
