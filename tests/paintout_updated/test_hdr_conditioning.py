"""HDR scene embeddings must load without locally modified LTX nodes."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import torch
from safetensors.torch import save_file

spec = importlib.util.spec_from_file_location("paintout_hdr_conditioning_test", Path(__file__).resolve().parents[2] / "paintout/hdr_conditioning.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HDRConditioningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "scene.safetensors"

    def write(self, **tensors):
        save_file(tensors, str(self.path))

    def test_official_and_alias_keys_concatenate_native_av_channels(self):
        for video_key, audio_key in (("video_context", "audio_context"), ("video_prompt_embeds", "audio_prompt_embeds")):
            video = torch.full((3, 4096), 2, dtype=torch.bfloat16)
            audio = torch.full((3, 2048), 3, dtype=torch.bfloat16)
            self.write(**{video_key: video, audio_key: audio})
            result = module.load_hdr_conditioning(self.path)
            self.assertEqual(result[0][1], {})
            tensor = result[0][0]
            self.assertEqual(tuple(tensor.shape), (1, 3, 6144))
            self.assertEqual(tensor.dtype, video.dtype)
            self.assertTrue(torch.equal(tensor[..., :4096], video[None]))
            self.assertTrue(torch.equal(tensor[..., 4096:], audio[None]))

    def test_preconcatenated_context_retains_batch_and_values(self):
        video = torch.randn(2, 4, 6144)
        self.write(video_context=video)
        self.assertTrue(torch.equal(module.load_hdr_conditioning(self.path)[0][0], video))

    def test_invalid_layouts_and_values_are_rejected(self):
        valid = torch.ones(1, 3, 4096)
        cases = [
            {"other": valid},
            {"video_context": valid},
            {"video_context": torch.ones(3, 4000)},
            {"video_context": torch.ones(6144)},
            {"video_context": torch.ones(0, 3, 6144)},
            {"video_context": torch.ones(3, 6144, dtype=torch.int32)},
            {"video_context": torch.full((3, 6144), float("nan"))},
            {"video_context": valid, "audio_context": torch.ones(1, 2, 2048)},
            {"video_context": valid, "audio_context": torch.ones(1, 3, 2047)},
            {"video_context": valid, "audio_context": torch.ones(1, 3, 2048, dtype=torch.bfloat16)},
            {"video_context": valid, "audio_context": torch.full((1, 3, 2048), float("inf"))},
        ]
        for data in cases:
            self.write(**data)
            with self.subTest(shapes={k: tuple(v.shape) for k, v in data.items()}):
                with self.assertRaises(ValueError):
                    module.load_hdr_conditioning(self.path)

    def test_node_uses_registered_folder_and_fingerprints_changes(self):
        paths = types.SimpleNamespace(get_full_path=lambda folder, name: str(self.path) if name == "scene.safetensors" else None,
                                      get_filename_list=lambda folder: ["scene.safetensors", "irrelevant.pt"])
        self.write(video_context=torch.ones(3, 6144))
        with patch.dict(sys.modules, {"folder_paths": paths}):
            node = module.ZuraPaintoutHDRConditioning()
            self.assertEqual(node.INPUT_TYPES()["required"]["file_name"][0], ["scene.safetensors"])
            first = node.IS_CHANGED("scene.safetensors")
            self.assertEqual(tuple(node.load("scene.safetensors")[0][0][0].shape), (1, 3, 6144))
            self.write(video_context=torch.zeros(3, 6144))
            self.assertNotEqual(first, node.IS_CHANGED("scene.safetensors"))
            with self.assertRaises(FileNotFoundError):
                node.load("missing.safetensors")

    def test_installed_official_scene_embedding_when_available(self):
        comfy = Path(sys.executable).resolve().parents[2]
        path = Path(os.environ.get("ZURA_HDR_EMBEDDING_TEST_FILE", str(comfy / "models/embeddings/ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors")))
        if not path.is_file():
            self.skipTest("Official scene embedding is not installed.")
        tensor = module.load_hdr_conditioning(path)[0][0]
        self.assertEqual(tensor.ndim, 3)
        self.assertEqual(tensor.shape[-1], 6144)
        self.assertTrue(torch.isfinite(tensor).all())


if __name__ == "__main__":
    unittest.main()
