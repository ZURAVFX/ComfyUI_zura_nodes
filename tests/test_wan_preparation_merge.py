"""Neutral CPU-only tests of exact, atomic preparation cache assembly."""
from __future__ import annotations

import copy
import hashlib
import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import torch

import v2_bootstrap
from test_wan_preparation_windows import fixture, mutate_storage_float

merge = importlib.import_module("ComfyUI_zura_nodes.wan_preparation_merge")
windows = importlib.import_module("ComfyUI_zura_nodes.wan_preparation_windows")
KEY = "d" * 64
PART_KEY = "a" * 64


def prepare(root, counts=(3, 5, 4), mutate=None):
    full = fixture(sum(counts))
    full["footage"]["video_info"].update(frames=sum(counts), duration=sum(counts)/24,
                                           source_raster=(10, 8))
    # Exercise native strided source/pose views, independent face rasters,
    # signed zero, and a window containing no selected performer.
    full["footage"]["pose_video"] = full["footage"]["frames"].transpose(1, 2)
    full["footage"]["frames"][0, 0, 0, 0] = -0.0
    full["footage"]["character_mask"][:counts[0]].zero_()
    metadata = {k: v for k, v in full["footage"].items() if k not in windows.TENSOR_NAMES}
    parts, start = [], 0
    for index, count in enumerate(counts):
        part = {"version": 1, "footage": copy.deepcopy(metadata), "reference": full["reference"].clone()}
        part["footage"].update({name: full["footage"][name][start:start+count]
                               for name in windows.TENSOR_NAMES[:-1]})
        if mutate:
            mutate(index, part)
        path = Path(root) / "parts" / f"{start}-{count}.pt"
        path.parent.mkdir(exist_ok=True)
        torch.save(part, path)
        stamp = path.stat()
        parts.append(merge.ShardSpec(PART_KEY, path, start, count,
            hashlib.sha256(path.read_bytes()).hexdigest(), stamp.st_size, stamp.st_mtime_ns))
        start += count
    return full, metadata, parts


def delivered(root):
    return Path(root) / "genj" / "wan_conditioning" / (KEY + ".pt")


def receipts(parts, full, metadata):
    result = []
    ref_sha = hashlib.sha256(full["reference"].contiguous().numpy().tobytes()).hexdigest()
    review = Path(parts[0].path).parent.parent/"genj"/"reviews"/"shot_0123456789abcdef"
    review.mkdir(parents=True,exist_ok=True)
    render_pin = {}
    for label in ("source","mask"):
        path = review/(label+".mp4")
        if not path.exists():
            path.write_bytes(("neutral derived "+label).encode())
        stamp = path.stat()
        render_pin[label] = {"path":str(path.resolve()),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                             "size":stamp.st_size,"mtime_ns":stamp.st_mtime_ns}
    for index, part in enumerate(parts):
        source = full["footage"]["frames"][part.start:part.start+part.count]
        result.append({**part.__dict__, "schema":"zura_wan_preparation_part_v1",
            "total_frames":len(full["footage"]["frames"]),
            "source_pin":{"review_shot_id":review.name, "original_source_sha256":"b"*64,
                "window_source_sha256":hashlib.sha256(source.contiguous().numpy().tobytes()).hexdigest()},
            "review_pin":{"manifest_sha256":"c"*64, "mask_sha256":"e"*64},
            "reference_sha256":ref_sha, "footage_metadata_sha256":merge._metadata_sha(metadata),
            "render_cache_pin":copy.deepcopy(render_pin),
            "carry_in_kind":"none" if index == 0 else "body",
            "carry_in_sha256":hashlib.sha256(b"zura-wan-pose-carry-v1:none" if index == 0 else str(index).encode()).hexdigest(),
            "carry_out_sha256":hashlib.sha256(str(index+1).encode()).hexdigest()})
    return result


class MergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def test_native_weights_only_and_unchanged_reader_are_bit_exact(self):
        with tempfile.TemporaryDirectory() as root:
            full, metadata, parts = prepare(root)
            with patch.object(torch.UntypedStorage, "from_file", side_effect=AssertionError("COW forbidden")):
                receipt = merge.merge_preparation(parts, root, KEY, 12, metadata)
            result = torch.load(delivered(root), map_location="cpu", weights_only=True)
            self.assertEqual(result["version"], 1)
            reader = windows.WanPreparationWindows(delivered(root), KEY, root, max_window_frames=4)
            self.assertEqual(reader.metadata, metadata)
            for name in windows.TENSOR_NAMES:
                wanted = full["reference"] if name == "reference" else full["footage"][name]
                actual = result["reference"] if name == "reference" else result["footage"][name]
                self.assertEqual(actual.numpy().tobytes(), wanted.contiguous().numpy().tobytes())
                for start in range(0, len(wanted), 4):
                    self.assertEqual(reader.arrays[name][start:start+4].numpy().tobytes(),
                                     wanted[start:start+4].contiguous().numpy().tobytes())
            self.assertEqual(receipt["sha256"], hashlib.sha256(delivered(root).read_bytes()).hexdigest())
            self.assertEqual(receipt["frames"], 12)
            self.assertLessEqual(receipt["merge"]["maximum_block_frames"], 4)
            self.assertLessEqual(receipt["merge"]["maximum_copy_bytes"], 4*8*10*3*4)
            with zipfile.ZipFile(delivered(root)) as archive:
                members = [m for m in archive.infolist() if "/data/" in m.filename]
                self.assertEqual(len(members), 5)
                self.assertTrue(all(m.compress_type == zipfile.ZIP_STORED for m in members))
                self.assertTrue(all(m.extract_version >= 45 for m in members))
            self.assertFalse(list(delivered(root).parent.glob(".merge*")))
            self.assertTrue(all(Path(p.path).exists() for p in parts))

    def test_every_torch_load_is_metadata_only_and_every_copy_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            _, metadata, parts = prepare(root)
            real_load, real_map = torch.load, np.memmap
            calls, maps = [], []
            def load(*args, **kwargs):
                value = real_load(*args, **kwargs)
                calls.append(kwargs)
                self.assertTrue(hasattr(value["footage"]["frames"], "fake_mode"))
                return value
            def map_view(*args, **kwargs):
                self.assertEqual(kwargs["mode"], "r")
                result = real_map(*args, **kwargs)
                maps.append(result)
                return result
            with patch.object(torch, "load", side_effect=load), patch.object(np, "memmap", side_effect=map_view):
                merge.merge_preparation(parts, root, KEY, 12, metadata)
            self.assertTrue(calls and maps)
            self.assertTrue(all(k == {"map_location":"cpu", "weights_only":True, "mmap":False} for k in calls))
            self.assertTrue(all(m._mmap.closed for m in maps))

    def test_gap_overlap_order_duplicate_and_bad_receipts_fail(self):
        with tempfile.TemporaryDirectory() as root:
            _, metadata, parts = prepare(root)
            changes = [parts[1:]+parts[:1], parts[:2], [parts[0], parts[0], parts[2]],
                [merge.ShardSpec(**{**parts[0].__dict__, "start": True}), *parts[1:]],
                [merge.ShardSpec(**{**parts[0].__dict__, "sha256":"bad"}), *parts[1:]]]
            for changed in changes:
                with self.assertRaises(ValueError):
                    merge.merge_preparation(changed, root, KEY, 12, metadata)
                self.assertFalse(delivered(root).exists())

    def test_receipts_bind_source_review_reference_metadata_and_pose_carry(self):
        with tempfile.TemporaryDirectory() as root:
            full, metadata, parts = prepare(root)
            # Worker receipts use the same full key for every part.
            parts = [merge.ShardSpec(**{**p.__dict__, "cache_key":KEY}) for p in parts]
            original = receipts(parts, full, metadata)
            specs = merge.shards_from_receipts(original, KEY, 12, metadata)
            merge.merge_preparation(specs, root, KEY, 12, metadata)
            changes = [
                lambda r: r[1]["source_pin"].update(original_source_sha256="0"*64),
                lambda r: r[1]["review_pin"].update(mask_sha256="0"*64),
                lambda r: r[1].update(reference_sha256="0"*64),
                lambda r: r[1].update(footage_metadata_sha256="0"*64),
                lambda r: r[1].update(carry_in_sha256="0"*64),
                lambda r: r[0].update(carry_in_sha256="0"*64),
                lambda r: r[1].update(carry_in_kind="none"),
                lambda r: r[1].update(total_frames=11),
                lambda r: r[1].update(schema="unsupported"),
                lambda r: r[1].pop("render_cache_pin"),
                lambda r: r[1]["render_cache_pin"]["source"].update(sha256="0"*64),
                lambda r: r[1]["source_pin"].pop("window_source_sha256"),
            ]
            for change in changes:
                altered = copy.deepcopy(original)
                change(altered)
                with self.assertRaises(ValueError):
                    merge.shards_from_receipts(altered, KEY, 12, metadata)
        for pin in ("source", "reference"):
            with tempfile.TemporaryDirectory() as root:
                full, metadata, parts = prepare(root)
                parts = [merge.ShardSpec(**{**p.__dict__, "cache_key":KEY}) for p in parts]
                approved = receipts(parts, full, metadata)
                if pin == "source":
                    approved[1]["source_pin"]["window_source_sha256"] = "0"*64
                else:
                    for part in approved:
                        part["reference_sha256"] = "0"*64
                specs = merge.shards_from_receipts(approved, KEY, 12, metadata)
                with self.assertRaisesRegex(ValueError, "source pixels" if pin == "source" else "reference digest"):
                    merge.merge_preparation(specs, root, KEY, 12, metadata)
                self.assertFalse(delivered(root).exists())

    def test_same_stamp_derived_source_mutation_is_rejected_before_use_and_publication(self):
        for late in (False,True):
            with tempfile.TemporaryDirectory() as root:
                full,metadata,parts = prepare(root)
                parts = [merge.ShardSpec(**{**p.__dict__,"cache_key":KEY}) for p in parts]
                approved = receipts(parts,full,metadata)
                specs = merge.shards_from_receipts(approved,KEY,12,metadata)
                path = Path(approved[0]["render_cache_pin"]["source"]["path"])
                before = path.stat()
                def mutate():
                    data = bytearray(path.read_bytes())
                    data[0] ^= 1
                    path.write_bytes(data)
                    os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
                real_write = merge._write_archive
                def write(*args,**kwargs):
                    result = real_write(*args,**kwargs)
                    mutate()
                    return result
                if not late:
                    mutate()
                with patch.object(merge,"_write_archive",side_effect=write if late else real_write):
                    with self.assertRaisesRegex(ValueError,"derived source/mask bytes changed"):
                        merge.merge_preparation(specs,root,KEY,12,metadata)
                self.assertFalse(delivered(root).exists())

    def test_malformed_input_archive_and_failed_hardlink_never_fall_back(self):
        for problem in ("zip", "hardlink"):
            with tempfile.TemporaryDirectory() as root:
                _, metadata, parts = prepare(root)
                if problem == "zip":
                    path = Path(parts[1].path)
                    path.write_bytes(b"unsupported archive")
                    stamp = path.stat()
                    parts[1] = merge.ShardSpec(PART_KEY, path, parts[1].start, parts[1].count,
                        hashlib.sha256(path.read_bytes()).hexdigest(), stamp.st_size, stamp.st_mtime_ns)
                    with self.assertRaises(ValueError):
                        merge.merge_preparation(parts, root, KEY, 12, metadata)
                else:
                    with patch.object(merge.os, "link", side_effect=OSError("hardlinks unavailable")):
                        with self.assertRaisesRegex(OSError, "hardlinks unavailable"):
                            merge.merge_preparation(parts, root, KEY, 12, metadata)
                self.assertFalse(delivered(root).exists())
                self.assertFalse(list(delivered(root).parent.glob(".merge*")))

    def test_reference_raster_metadata_dtype_pixels_and_global_empty_mask_fail(self):
        changes = [
            lambda i,p: p["reference"].fill_(.25) if i == 1 else None,
            lambda i,p: p["footage"].update(cut_frames=[6]) if i == 1 else None,
            lambda i,p: p["footage"]["video_info"].update(fps=30) if i == 1 else None,
            lambda i,p: p["footage"].update(keep_audio=True) if i == 1 else None,
            lambda i,p: p["footage"].update(pose_video=p["footage"]["pose_video"].half()) if i == 1 else None,
            lambda i,p: p["footage"]["face_video"].fill_(float("nan")) if i == 1 else None,
            lambda i,p: p["footage"].update(face_video=p["footage"]["face_video"][:,:2]) if i == 1 else None,
            lambda i,p: p["footage"]["character_mask"].zero_(),
        ]
        for change in changes:
            with tempfile.TemporaryDirectory() as root:
                _, metadata, parts = prepare(root, mutate=change)
                with self.assertRaises(ValueError):
                    merge.merge_preparation(parts, root, KEY, 12, metadata)
                self.assertFalse(delivered(root).exists())
                self.assertFalse(list(delivered(root).parent.glob(".merge*")))

    def test_same_stamp_mutation_before_read_and_before_publication_fails(self):
        for late in (False, True):
            with tempfile.TemporaryDirectory() as root:
                _, metadata, parts = prepare(root)
                if not late:
                    mutate_storage_float(parts[1].path, restore_mtime=True)
                real_write = merge._write_archive
                def write(*args, **kwargs):
                    stats = real_write(*args, **kwargs)
                    mutate_storage_float(parts[1].path, restore_mtime=True)
                    return stats
                with patch.object(merge, "_write_archive", side_effect=write if late else real_write):
                    with self.assertRaisesRegex(ValueError, "bytes changed"):
                        merge.merge_preparation(parts, root, KEY, 12, metadata)
                self.assertFalse(delivered(root).exists())
                self.assertFalse(list(delivered(root).parent.glob(".merge*")))

    def test_cancellation_during_archive_or_final_validation_never_publishes(self):
        for phase in ("storage", "final"):
            with tempfile.TemporaryDirectory() as root:
                _, metadata, parts = prepare(root)
                state = {"writing":False, "written":False}
                real_write = merge._write_archive
                def write(*args, **kwargs):
                    state["writing"] = True
                    result = real_write(*args, **kwargs)
                    state["written"] = True
                    return result
                def cancel():
                    if state["writing"] and (phase == "storage" or state["written"]):
                        raise RuntimeError("cancelled")
                with patch.object(merge, "_write_archive", side_effect=write):
                    with self.assertRaisesRegex(RuntimeError, "cancelled"):
                        merge.merge_preparation(parts, root, KEY, 12, metadata, interrupt=cancel)
                self.assertFalse(delivered(root).exists())
                self.assertFalse(list(delivered(root).parent.glob(".merge*")))

    def test_root_confinement_redirects_existing_final_and_disk_budget(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as other:
            _, metadata, parts = prepare(other)
            with self.assertRaisesRegex(ValueError, "leaves"):
                merge.merge_preparation(parts, root, KEY, 12, metadata)
            _, metadata, parts = prepare(root)
            with patch.object(merge.shutil, "disk_usage", return_value=type("Usage", (), {"free":1})()):
                with self.assertRaisesRegex(OSError, "disk space"):
                    merge.merge_preparation(parts, root, KEY, 12, metadata)
            merge.merge_preparation(parts, root, KEY, 12, metadata)
            before = delivered(root).read_bytes()
            with self.assertRaises(FileExistsError):
                merge.merge_preparation(parts, root, KEY, 12, metadata)
            self.assertEqual(delivered(root).read_bytes(), before)
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as other:
            _, metadata, parts = prepare(root)
            genj = Path(root)/"genj"
            try:
                genj.symlink_to(other, target_is_directory=True)
            except OSError:
                self.skipTest("Platform cannot create a neutral directory symlink")
            with self.assertRaisesRegex(ValueError, "redirected"):
                merge.merge_preparation(parts, root, KEY, 12, metadata)


if __name__ == "__main__":
    unittest.main()
