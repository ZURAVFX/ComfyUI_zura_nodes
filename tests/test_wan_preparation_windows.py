"""CPU-only exact preparation windows; no native inference or private assets."""
from __future__ import annotations

import hashlib
import importlib
import mmap
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import torch

import v2_bootstrap

windows = importlib.import_module("ComfyUI_zura_nodes.wan_preparation_windows")
KEY = "a" * 64


def fixture(count=12):
    source = torch.arange(count * 8 * 10 * 3, dtype=torch.float32).reshape(count, 8, 10, 3) / 4096
    mask = torch.zeros(count, 8, 10)
    mask[:, 2:4, 3:6] = 1
    return {"version": 1, "footage": {"frames": source, "character_mask": mask,
        "pose_video": source.flip(2), "face_video": source[:, :4, :6].clone(),
        "video_info": {"fps": 24}, "replacement_area": "Whole character", "keep_audio": False,
        "speech_provenance": {"guide_key": "b" * 64, "guide_sha": "c" * 64},
        "cut_frames": [5]}, "reference": source[:1].clone()}


def save(root, value=None):
    path = Path(root) / (KEY + ".pt")
    torch.save(fixture() if value is None else value, path)
    return path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mutate_storage_float(path, new_value=.875, restore_mtime=False):
    stamp = Path(path).stat()
    with zipfile.ZipFile(path) as archive:
        member = next(info for info in archive.infolist() if info.filename.endswith("/data/0"))
    with Path(path).open("r+b") as handle:
        handle.seek(member.header_offset)
        header = struct.unpack("<IHHHHHIIIHH", handle.read(30))
        handle.seek(member.header_offset + 30 + header[-2] + header[-1])
        handle.write(struct.pack("<f", new_value))
    if restore_mtime:
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))


class ReadOnlyWindowTests(unittest.TestCase):
    def test_empty_mask_part_cannot_be_exposed_to_rendering(self):
        with tempfile.TemporaryDirectory() as tmp:
            value = fixture()
            value["footage"]["character_mask"].zero_()
            path = save(tmp, value)
            with self.assertRaisesRegex(ValueError, "non-empty"):
                windows.WanPreparationWindows(path, KEY, tmp)
            reader = windows.WanPreparationWindows(path, KEY, tmp, require_nonempty_mask=False)
            self.assertEqual(reader.arrays["frames"][:2].numpy().tobytes(),
                             value["footage"]["frames"][:2].numpy().tobytes())
            with self.assertRaisesRegex(ValueError, "merged"):
                reader.footage()
            reader.require_nonempty_mask = True
            with self.assertRaisesRegex(ValueError, "merged"):
                reader.assert_renderable()
            for policy in (None, 0, 1, "false"):
                with self.assertRaisesRegex(ValueError, "explicit"):
                    windows.WanPreparationWindows(path, KEY, tmp, require_nonempty_mask=policy)

    def test_exact_windows_metadata_and_bitwise_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = fixture()
            original["footage"]["video_info"]["source_raster"] = (10, 8)
            # Exercise a native strided tensor, offset storage view and alias.
            original["footage"]["face_video"] = original["footage"]["frames"][:, 1:5, 2:8].transpose(1, 2)
            path = save(tmp, original)
            sha = digest(path)
            reader = windows.WanPreparationWindows(path, KEY, tmp, max_window_frames=4, expected_sha256=sha)
            footage = reader.footage()
            for name in windows.TENSOR_NAMES:
                expected = original["reference"] if name == "reference" else original["footage"][name]
                for start in range(0, len(expected), 4):
                    actual = reader.arrays[name][start:min(start + 4, len(expected))]
                    wanted = expected[start:min(start + 4, len(expected))].contiguous()
                    self.assertEqual(actual.dtype, torch.float32)
                    self.assertEqual(actual.numpy().tobytes(), wanted.numpy().tobytes())
                    actual.zero_()  # All returned storage is writable and independent.
            self.assertEqual(digest(path), sha)
            self.assertEqual(footage["speech_provenance"], original["footage"]["speech_provenance"])
            self.assertEqual(footage["cut_frames"], [5])
            self.assertEqual(footage["video_info"], {"fps": 24, "source_raster": (10, 8)})
            self.assertEqual(footage["streaming_preparation"]["sha256"], sha)

    def test_metadata_load_is_fake_without_torch_mmap_or_storage_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save(tmp)
            real_load = torch.load
            calls = []
            def spy(*args, **kwargs):
                calls.append(kwargs)
                value = real_load(*args, **kwargs)
                self.assertTrue(hasattr(value["footage"]["frames"], "fake_mode"))
                return value
            with patch.object(windows.torch, "load", side_effect=spy), \
                    patch.object(torch.UntypedStorage, "from_file", side_effect=AssertionError("full torch mmap forbidden")):
                reader = windows.WanPreparationWindows(path, KEY, tmp, max_window_frames=4)
            self.assertEqual(calls, [{"map_location": "cpu", "weights_only": True, "mmap": False}])
            self.assertFalse(any(isinstance(value, torch.Tensor) for value in reader.__dict__.values()))

    def test_each_mapping_is_readonly_and_closed_after_bounded_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save(tmp)
            real_map = np.memmap
            mappings = []
            mapping_sizes = []
            def spy(*args, **kwargs):
                self.assertEqual(kwargs["mode"], "r")
                result = real_map(*args, **kwargs)
                self.assertFalse(result.flags.writeable)
                mappings.append(result)
                mapping_sizes.append(len(result._mmap))
                return result
            with patch.object(windows.np, "memmap", side_effect=spy):
                reader = windows.WanPreparationWindows(path, KEY, tmp, max_window_frames=4)
                reader.arrays["frames"][4:8]
            self.assertTrue(mappings)
            self.assertTrue(all(mapping._mmap.closed for mapping in mappings))
            self.assertLessEqual(reader.stats["maximum_copy_bytes"], 4 * 8 * 10 * 3 * 4)
            self.assertLessEqual(reader.stats["maximum_map_bytes"], 4 * 8 * 10 * 3 * 4 + mmap.ALLOCATIONGRANULARITY - 1)
            self.assertEqual(reader.stats["maximum_map_bytes"], max(mapping_sizes))
            for item in (slice(None), slice(0, 5), slice(0, 4, 2), slice(3, 3), [0, 1]):
                with self.assertRaises(ValueError):
                    reader.arrays["frames"][item]
            with self.assertRaises(IndexError):
                reader.arrays["frames"][100]
            with self.assertRaises(ValueError):
                windows.WanPreparationWindows(path, KEY, tmp, max_window_bytes=32)

    def test_mutation_digest_and_file_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save(tmp)
            sha = digest(path)
            reader = windows.WanPreparationWindows(path, KEY, tmp, max_window_frames=4)
            mutate_storage_float(path, restore_mtime=True)
            with self.assertRaisesRegex(ValueError, "bytes changed"):
                reader.verify()
            with self.assertRaisesRegex(ValueError, "digest differs"):
                windows.WanPreparationWindows(path, KEY, tmp, expected_sha256=sha)
            mutate_storage_float(path, new_value=.25)
            with self.assertRaisesRegex(ValueError, "identity changed"):
                reader.arrays["frames"][:1]

    def test_reject_dtype_shape_pixels_hidden_metadata_and_compressed_zip(self):
        changes = [
            lambda x: x.update(version=2),
            lambda x: x["footage"].update(frames=x["footage"]["frames"].half()),
            lambda x: x["footage"].update(character_mask=torch.ones(2, 8, 10)),
            lambda x: x["footage"]["pose_video"].fill_(float("nan")),
            lambda x: x["footage"]["character_mask"].zero_(),
            lambda x: x["footage"].update(hidden=torch.ones(10)),
            lambda x: x["footage"].update(keep_audio=True),
            lambda x: x["footage"].update(speech_provenance={"guide_key": "bad", "guide_sha": "c" * 64}),
        ]
        for change in changes:
            with tempfile.TemporaryDirectory() as tmp:
                value = fixture()
                change(value)
                with self.assertRaises(ValueError):
                    windows.WanPreparationWindows(save(tmp, value), KEY, tmp)
        with tempfile.TemporaryDirectory() as tmp:
            path = save(tmp)
            with zipfile.ZipFile(path) as original:
                entries = [(name, original.read(name)) for name in original.namelist()]
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as rewritten:
                for name, contents in entries:
                    rewritten.writestr(name, contents)
            with self.assertRaisesRegex(ValueError, "uncompressed"):
                windows.WanPreparationWindows(path, KEY, tmp)
            path.write_bytes(b"not a ZIP")
            with self.assertRaises(ValueError):
                windows.WanPreparationWindows(path, KEY, tmp)

    def test_confinement_and_bad_key(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            path = save(outside)
            with self.assertRaisesRegex(ValueError, "leaves"):
                windows.WanPreparationWindows(path, KEY, root)
            with self.assertRaisesRegex(ValueError, "Invalid"):
                windows.WanPreparationWindows(path, "../escape", root)
            link = Path(root) / (KEY + ".pt")
            try:
                link.symlink_to(path)
            except OSError:
                self.skipTest("Platform cannot create a test symlink without privileges")
            with self.assertRaisesRegex(ValueError, "leaves"):
                windows.WanPreparationWindows(link, KEY, root)

    def test_tensor_metadata_cannot_escape_verified_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save(tmp)
            real_load = torch.load
            def oversized_view(*args, **kwargs):
                value = real_load(*args, **kwargs)
                frames = value["footage"]["frames"]
                # A valid fake shape is not proof that its strides fit the file.
                value["footage"]["frames"] = frames.as_strided(frames.shape, (10000, 30, 3, 1))
                return value
            with patch.object(windows.torch, "load", side_effect=oversized_view):
                with self.assertRaisesRegex(ValueError, "exceeds its native storage"):
                    windows.WanPreparationWindows(path, KEY, tmp)

    def test_bad_local_zip_header_duplicate_directory_and_byteorder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save(tmp)
            with zipfile.ZipFile(path) as archive:
                member = next(entry for entry in archive.infolist() if "/data/" in entry.filename)
            with path.open("r+b") as handle:
                handle.seek(member.header_offset)
                handle.write(b"FAIL")
            with self.assertRaisesRegex(ValueError, "header is unsupported"):
                windows.WanPreparationWindows(path, KEY, tmp)
            path = save(tmp)
            with zipfile.ZipFile(path) as archive:
                entries = [(name, archive.read(name)) for name in archive.namelist()]
            for problem in ("duplicate", "byteorder"):
                with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
                    for name, contents in entries:
                        archive.writestr(name, b"big" if problem == "byteorder" and name.endswith("/byteorder") else contents)
                    if problem == "duplicate":
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore", UserWarning)
                            archive.writestr(entries[0][0], entries[0][1])
                with self.assertRaisesRegex(ValueError, "duplicate" if problem == "duplicate" else "little-endian"):
                    windows.WanPreparationWindows(path, KEY, tmp)

    def test_cancellation_is_checked_during_validation_and_hashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save(tmp)
            count = 0
            def interrupt():
                nonlocal count
                count += 1
                if count == 5:
                    raise RuntimeError("cancelled")
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                windows.WanPreparationWindows(path, KEY, tmp, interrupt=interrupt)


if __name__ == "__main__":
    unittest.main()
