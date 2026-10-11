"""Focused CPU tests for the data-only video LATENT cache nodes."""

from __future__ import annotations

import hashlib
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

import v2_bootstrap

NAME = "ComfyUI_zura_nodes.video_latent_data"
module = importlib.import_module(NAME)


class VideoLatentDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "output"
        self.output.mkdir()
        self.output_patch = patch.object(
            module.folder_paths, "get_output_directory", return_value=str(self.output), create=True
        )
        self.output_patch.start()
        self.addCleanup(self.output_patch.stop)
        self.key = "a" * 64
        self.samples = torch.arange(48, dtype=torch.bfloat16).reshape(1, 2, 3, 2, 4)
        self.mask = torch.linspace(0, 1, 3, dtype=torch.float16).reshape(1, 1, 3, 1, 1)
        self.latent = {"samples": self.samples, "noise_mask": self.mask}

    @staticmethod
    def bits(tensor):
        return tensor.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()

    def save(self, latent=None, key=None):
        return module.ZuraSaveVideoLatentData().save(
            self.latent if latent is None else latent,
            self.key if key is None else key,
        )

    def load(self, digest="", key=None):
        return module.ZuraLoadVideoLatentData().load(self.key if key is None else key, digest)[0]

    def test_exact_dtype_and_bitwise_latent_roundtrip_preserves_the_source_storage(self):
        before_samples = self.bits(self.samples)
        before_mask = self.bits(self.mask)
        samples_ptr = self.samples.data_ptr()
        mask_ptr = self.mask.data_ptr()

        key, digest = self.save()
        restored = self.load(digest)

        self.assertEqual(key, self.key)
        self.assertEqual(digest, hashlib.sha256(module._cache_path(self.key).read_bytes()).hexdigest())
        self.assertEqual(set(restored), {"samples", "noise_mask"})
        self.assertEqual(restored["samples"].dtype, torch.bfloat16)
        self.assertEqual(restored["noise_mask"].dtype, torch.float16)
        self.assertEqual(tuple(restored["samples"].shape), tuple(self.samples.shape))
        self.assertEqual(tuple(restored["noise_mask"].shape), tuple(self.mask.shape))
        self.assertEqual(restored["samples"].device.type, "cpu")
        self.assertEqual(restored["noise_mask"].device.type, "cpu")
        self.assertEqual(self.bits(restored["samples"]), before_samples)
        self.assertEqual(self.bits(restored["noise_mask"]), before_mask)
        self.assertEqual(self.samples.data_ptr(), samples_ptr)
        self.assertEqual(self.mask.data_ptr(), mask_ptr)
        self.assertEqual(self.bits(self.samples), before_samples)
        self.assertEqual(self.bits(self.mask), before_mask)

    def test_absent_noise_mask_stays_absent(self):
        self.save({"samples": self.samples})
        restored = self.load()
        self.assertEqual(set(restored), {"samples"})
        self.assertEqual(self.bits(restored["samples"]), self.bits(self.samples))

    def test_same_key_and_same_content_is_idempotent_and_float8_bits_are_preserved(self):
        first = self.save()
        path = module._cache_path(self.key)
        original = path.read_bytes()
        header_length = int.from_bytes(original[:8], "little")
        header = json.loads(original[8 : 8 + header_length].rstrip(b" ").decode("utf-8"))
        metadata = header["__metadata__"]
        header["__metadata__"] = {name: metadata[name] for name in reversed(tuple(metadata))}
        alternate_header = json.dumps(header, separators=(",", ":")).encode("utf-8")
        alternate_header += b" " * ((-len(alternate_header)) % 8)
        self.assertEqual(len(alternate_header), header_length)
        variant = len(alternate_header).to_bytes(8, "little") + alternate_header + original[8 + header_length :]
        path.write_bytes(variant)
        variant_digest = hashlib.sha256(variant).hexdigest()
        for _ in range(50):
            self.assertEqual(self.save(), (first[0], variant_digest))
            self.assertEqual(path.read_bytes(), variant)
        dtype = getattr(torch, "float8_e4m3fn", None)
        if dtype is None:
            self.skipTest("This Torch build does not provide float8_e4m3fn.")
        float8 = torch.tensor([0.0, 0.5, 1.0, -0.5], dtype=dtype).reshape(1, 1, 1, 2, 2)
        self.save({"samples": float8}, key="b" * 64)
        restored = self.load(key="b" * 64)
        self.assertEqual(restored["samples"].dtype, dtype)
        self.assertEqual(self.bits(restored["samples"]), self.bits(float8))

    def test_float8_e8m0_is_rejected_before_writing_an_unloadable_cache(self):
        dtype = getattr(torch, "float8_e8m0fnu", None)
        if dtype is None:
            self.skipTest("This Torch build does not provide float8_e8m0fnu.")
        with self.assertRaisesRegex(ValueError, "safetensors cannot store safely"):
            self.save({"samples": torch.zeros((1, 1, 1, 1, 1), dtype=dtype)})
        self.assertFalse(module._cache_path(self.key, create_directory=True).exists())

    def test_rejects_invalid_mask_shapes_values_unknown_keys_and_bad_keys(self):
        invalid = [
            ({"samples": self.samples, "noise_mask": torch.zeros(1, 1, 2, 1, 1)}, "broadcast"),
            ({"samples": self.samples, "noise_mask": torch.full((1, 1, 3, 1, 1), 1.1)}, "between 0 and 1"),
            ({"samples": self.samples, "downscale_ratio_spacial": 32}, "unsupported metadata"),
            ({"samples": torch.full_like(self.samples, float("nan"))}, "NaN or infinite"),
            ({"samples": self.samples, "noise_mask": torch.full((1, 1, 3, 1, 1), float("inf"))}, "NaN or infinite"),
        ]
        for latent, message in invalid:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.save(latent)
        for bad_key in ("../" + "a" * 62, "g" * 64, "A" * 64, "a" * 63):
            with self.subTest(key=bad_key), self.assertRaisesRegex(ValueError, "64 lowercase hexadecimal"):
                self.save(key=bad_key)

    def test_rejects_wrong_digest_tampering_and_wrong_schema(self):
        _, digest = self.save()
        with self.assertRaisesRegex(ValueError, "digest does not match"):
            self.load("0" * 64)
        path = module._cache_path(self.key)
        valid = path.read_bytes()

        # Make a bitwise-valid safetensors file with a non-finite float32 value.
        bad_tensor = torch.zeros((1, 1, 1, 1, 1), dtype=torch.float32)
        raw = module.safe_save({"samples": bad_tensor}, metadata={"cache_key": self.key, "schema": module._SCHEMA, "version": "1"})
        raw = raw[:-4] + bytes.fromhex("0000807f")
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "NaN or infinite"):
            self.load()

        # A valid tensor payload with an unsupported cache version is rejected
        # before its data is exposed.
        wrong_version = module.safe_save(
            {"samples": self.samples.contiguous()},
            metadata={"cache_key": self.key, "schema": module._SCHEMA, "version": "2"},
        )
        path.write_bytes(wrong_version)
        with self.assertRaisesRegex(ValueError, "another key or uses an unsupported version"):
            self.load()

        # Unknown tensor entries cannot be silently dropped by the loader.
        unknown = module.safe_save(
            {"samples": self.samples.contiguous(), "extra": torch.ones(1, 1, 1, 1, 1)},
            metadata={"cache_key": self.key, "schema": module._SCHEMA, "version": "1"},
        )
        path.write_bytes(unknown)
        with self.assertRaisesRegex(ValueError, "at most one noise_mask"):
            self.load()
        path.write_bytes(valid)
        self.assertEqual(module.ZuraLoadVideoLatentData.IS_CHANGED(self.key), digest)

    def test_existing_key_conflict_and_busy_lock_never_overwrite_or_delete_another_lock(self):
        self.save()
        path = module._cache_path(self.key)
        original = path.read_bytes()
        signed_zero = self.samples.clone()
        signed_zero[0, 0, 0, 0, 0] = -0.0
        changed_payloads = (
            {"samples": torch.ones_like(self.samples), "noise_mask": self.mask},
            {"samples": self.samples.float(), "noise_mask": self.mask},
            {"samples": signed_zero, "noise_mask": self.mask},
        )
        for changed in changed_payloads:
            with self.subTest(dtype=changed["samples"].dtype), self.assertRaisesRegex(
                ValueError, "already contains different"
            ):
                self.save(changed)
            self.assertEqual(path.read_bytes(), original)

        lock_key = "b" * 64
        lock = path.parent / f".{lock_key}.lock"
        lock.write_text("owned by another queue", encoding="ascii")
        with self.assertRaisesRegex(ValueError, "being written by another queue"):
            self.save({"samples": torch.zeros_like(self.samples)}, key="b" * 64)
        self.assertEqual(lock.read_text(encoding="ascii"), "owned by another queue")

    def test_oversize_meta_tensor_is_rejected_without_allocating_its_payload(self):
        huge = torch.empty((1, 1, 1, 8193, 8193), dtype=torch.float32, device="meta")
        with self.assertRaisesRegex(ValueError, "256 MiB cache limit"):
            self.save({"samples": huge})

    def test_missing_cache_marks_node_changed_and_loader_gives_rebuild_guidance(self):
        self.assertTrue(torch.isnan(torch.tensor(module.ZuraLoadVideoLatentData.IS_CHANGED(self.key))))
        with self.assertRaisesRegex(FileNotFoundError, "Rebuild it from the native preparation section"):
            self.load()

    def test_cache_directory_symlink_cannot_escape_the_output_folder(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        try:
            (self.output / "zura").symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"This Windows account cannot create a test symlink: {exc}")
        with self.assertRaisesRegex(ValueError, "inside ComfyUI output"):
            self.save()


if __name__ == "__main__":
    unittest.main()
