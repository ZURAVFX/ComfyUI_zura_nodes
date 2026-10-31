"""CPU-only exactness and integrity tests for bounded Wan preparation parts."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import av
import numpy as np
import torch
import torch.nn.functional as F

comfy_root = Path(os.environ.get("COMFYUI_ROOT", ""))
if comfy_root.is_dir():
    sys.path.insert(0, str(comfy_root))
    sys.path.insert(0, str(comfy_root / "custom_nodes"))

import v2_bootstrap
from comfy_api.latest import InputImpl

native_root = comfy_root / "custom_nodes" / "ComfyUI-WanAnimatePreprocess"
native_package = types.ModuleType("ComfyUI-WanAnimatePreprocess")
native_package.__path__ = [str(native_root)]
sys.modules.setdefault("ComfyUI-WanAnimatePreprocess", native_package)
native_pose_package = types.ModuleType("ComfyUI-WanAnimatePreprocess.pose_utils")
native_pose_package.__path__ = [str(native_root / "pose_utils")]
sys.modules.setdefault("ComfyUI-WanAnimatePreprocess.pose_utils", native_pose_package)

parts = importlib.import_module("ComfyUI_zura_nodes.wan_preparation_parts")
parts._interrupt = lambda: None  # Explicitly keep this fixture suite CPU-only.
pose_utils = importlib.import_module("ComfyUI-WanAnimatePreprocess.pose_utils.pose2d_utils")
visual = importlib.import_module("ComfyUI-WanAnimatePreprocess.pose_utils.human_visualization")
native_utils = importlib.import_module("ComfyUI-WanAnimatePreprocess.utils")


def write_video(path: Path, frames: np.ndarray):
    """Small native decodable RGB fixture, stored under a production basename."""
    with av.open(str(path), "w", format="mov", options={"avoid_negative_ts": "disabled"}) as container:
        stream = container.add_stream("libx264", rate=24)
        stream.width, stream.height = int(frames.shape[2]), int(frames.shape[1])
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "16", "bf": "3", "g": "48"}
        for index, pixels in enumerate(frames):
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = index, Fraction(1, 24)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render_cache_pin(details):
    source = Path(details["selected_path"]).resolve()
    mask = source.parent / "mask.mp4"
    def pin(path):
        stat = path.stat()
        return {"path": str(path.resolve()), "sha256": digest(path),
                "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    return {"source": pin(source), "mask": pin(mask)}


def preparation_window(details, start, count, width, height, mask_width=None, mask_height=None):
    return {"schema": parts.WINDOW_SCHEMA, "start": start, "count": count,
            "total_frames": details["frames"], "fps": 24, "width": width, "height": height,
            "mask_width": mask_width or width, "mask_height": mask_height or height,
            "render_cache_pin": render_cache_pin(details)}


def review_fixture(root: Path, total=5, source_path=None, mask_path=None, width=64, height=32):
    root.mkdir(parents=True, exist_ok=True)
    original = root / "original_source.mp4"
    original.write_bytes(b"synthetic original source identity")
    shot = "shot_0123456789abcdef"
    directory = root / "genj" / "reviews" / shot
    directory.mkdir(parents=True, exist_ok=True)
    source_path = Path(source_path) if source_path else directory / "source.mp4"
    mask_path = Path(mask_path) if mask_path else directory / "mask.mp4"
    if not source_path.exists():
        source_path.write_bytes(b"synthetic approved source")
    if not mask_path.exists():
        mask_path.write_bytes(b"synthetic approved mask")
    details = {"review_shot_id": shot, "source": str(original), "source_hash": digest(original),
               "selected_path": str(source_path), "start": 0.0, "duration": total / 24,
               "frames": total, "fps": 24, "width": width, "height": height,
               "full_source": False}
    manifest = {"shot_id": shot, "clip": {k: v for k, v in details.items() if k != "review_shot_id"},
                "files": {"source.mp4": digest(source_path), "mask.mp4": digest(mask_path)}}
    (directory / "review.json").write_text(json.dumps(manifest), encoding="utf-8")
    return details, directory


def native_pose_data(keypoint_frames, width=64, height=32):
    raw = pose_utils.load_pose_metas_from_kp2ds_seq(keypoint_frames, width=width, height=height)
    return {"retarget_image": None, "refer_pose_meta": None,
            "pose_metas_original": raw,
            "pose_metas": [pose_utils.AAPoseMeta.from_humanapi_meta(meta) for meta in raw]}


def detector_frame(index, width=64, height=32, invalid=False):
    keypoints = np.zeros((133, 3), dtype=np.float32)
    for point in range(133):
        keypoints[point, 0] = 7 + (point % 20) * 2 + (index % 2)
        keypoints[point, 1] = 3 + (point % 10) * 2
        keypoints[point, 2] = 0.9
    if invalid:
        keypoints[:, :2] = -1.0
        keypoints[:, 2] = 0.0
    return keypoints


def draw(meta, width=64, height=32):
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    pose_image = visual.draw_aapose_by_meta_new(canvas, meta, draw_hand=True, draw_head=True,
                                                body_stick_width=-1, hand_stick_width=-1)
    return native_utils.padding_resize(pose_image, height, width)


class BoundedDecodeTests(unittest.TestCase):
    def test_native_windows_match_full_comfy_decode_and_legacy_mask_ops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = root / "genj" / "reviews" / "shot_0123456789abcdef"
            review_dir.mkdir(parents=True)
            source_pixels = np.zeros((9, 32, 64, 3), dtype=np.uint8)
            masks = np.zeros((9, 16, 32, 3), dtype=np.uint8)
            for frame in range(9):
                source_pixels[frame, :, :, 0] = (frame * 19) % 255
                source_pixels[frame, 6:22, 8 + frame:25 + frame, 2] = 220
                masks[frame, 3:12, 4 + frame:15 + frame, :] = 255
            source_path = write_video(review_dir / "source.mp4", source_pixels)
            mask_path = write_video(review_dir / "mask.mp4", masks)
            details, _ = review_fixture(root, 9, source_path, mask_path)
            # Review metadata must pin the exact generated fixture files.
            with patch.object(sys.modules["folder_paths"], "get_output_directory", return_value=str(root), create=True):
                source = InputImpl.VideoFromFile(str(source_path))
                mask_video = InputImpl.VideoFromFile(str(mask_path))
                full_frames = source.get_components().images.float()
                full_masks = mask_video.get_components().images.float()
                expected_mask = (F.interpolate(full_masks.mean(dim=-1)[:, None],
                    full_frames.shape[1:3], mode="nearest")[:, 0] > .5).float()
                ranges = ((0, 4), (4, 4), (8, 1))
                decoded, binary = [], []
                for start, count in ranges:
                    frames, mask, width, height, window = parts.decode_preparation_window(
                        source, mask_video, details, start, count, interrupt=lambda: None)
                    self.assertLessEqual(window["count"], 81)
                    self.assertEqual((width, height), (64, 32))
                    decoded.append(frames)
                    binary.append(mask)
                self.assertTrue(torch.equal(torch.cat(decoded), full_frames))
                self.assertTrue(torch.equal(torch.cat(binary), expected_mask))
                self.assertEqual(tuple(torch.cat(binary).shape), (9, 32, 64))

    def test_rejects_overlong_mismatched_and_unapproved_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = root / "genj" / "reviews" / "shot_0123456789abcdef"
            review_dir.mkdir(parents=True)
            pixels = np.zeros((3, 32, 64, 3), dtype=np.uint8)
            source_path = write_video(review_dir / "source.mp4", pixels)
            mask_path = write_video(review_dir / "mask.mp4", pixels[:2, :, :32])
            details, _ = review_fixture(root, 3, source_path, mask_path)
            source, mask = InputImpl.VideoFromFile(str(source_path)), InputImpl.VideoFromFile(str(mask_path))
            with patch.object(sys.modules["folder_paths"], "get_output_directory", return_value=str(root), create=True):
                with self.assertRaisesRegex(ValueError, "1 to 81"):
                    parts.decode_preparation_window(source, mask, details, 0, 82, interrupt=lambda: None)
                with self.assertRaisesRegex(ValueError, "same reviewed timeline"):
                    parts.decode_preparation_window(source, mask, details, 0, 2, interrupt=lambda: None)
                outside = write_video(root / "unapproved.mp4", pixels)
                with self.assertRaisesRegex(ValueError, "exact source/mask files"):
                    parts.decode_preparation_window(InputImpl.VideoFromFile(str(outside)), mask, details,
                                                    0, 2, interrupt=lambda: None)

    def test_uses_exact_loader_render_cache_and_rejects_arbitrary_review_subfolders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = root / "genj" / "reviews" / "shot_0123456789abcdef"
            review_dir.mkdir(parents=True)
            pixels = np.zeros((3, 32, 64, 3), dtype=np.uint8)
            review_mask_pixels = np.zeros((3, 16, 32, 3), dtype=np.uint8)
            review_mask_pixels[:, 4:10, 6:18, :] = 255
            source_path = write_video(review_dir / "source.mp4", pixels)
            mask_path = write_video(review_dir / "mask.mp4", review_mask_pixels)
            details, _ = review_fixture(root, 3, source_path, mask_path)
            cache = review_dir / "render_audio_v2_768_x1_3f"
            cache.mkdir()
            high_source = write_video(cache / "source.mp4", pixels)
            resized_review_mask = np.repeat(np.repeat(review_mask_pixels, 2, axis=1), 2, axis=2)
            high_mask = write_video(cache / "mask.mp4", resized_review_mask)
            high_details = {**details, "render_long_edge": 768, "selected_path": str(high_source)}
            with patch.object(sys.modules["folder_paths"], "get_output_directory", return_value=str(root), create=True):
                frames, mask, _, _, _ = parts.decode_preparation_window(
                    InputImpl.VideoFromFile(str(high_source)), InputImpl.VideoFromFile(str(high_mask)),
                    high_details, 0, 2, interrupt=lambda: None)
                self.assertEqual(tuple(frames.shape), (2, 32, 64, 3))
                self.assertEqual(tuple(mask.shape), (2, 32, 64))

                current_cache = review_dir / "render_audio_v3_768_x1_3f_aspect"
                current_cache.mkdir()
                current_source = write_video(current_cache / "source.mp4", pixels)
                current_mask = write_video(current_cache / "mask.mp4", resized_review_mask)
                current_details = {**high_details, "selected_path": str(current_source)}
                current_frames, _, _, _, _ = parts.decode_preparation_window(
                    InputImpl.VideoFromFile(str(current_source)), InputImpl.VideoFromFile(str(current_mask)),
                    current_details, 0, 2, interrupt=lambda: None)
                self.assertEqual(tuple(current_frames.shape), (2, 32, 64, 3))

                altered = resized_review_mask.copy()
                altered[:, 8:24, 12:36] = 0
                write_video(high_mask, altered)
                with self.assertRaisesRegex(ValueError, "differs from the approved review mask"):
                    parts.decode_preparation_window(InputImpl.VideoFromFile(str(high_source)),
                        InputImpl.VideoFromFile(str(high_mask)), high_details, 0, 2,
                        interrupt=lambda: None)

                arbitrary = review_dir / "artist-export"
                arbitrary.mkdir()
                arbitrary_source = write_video(arbitrary / "source.mp4", pixels)
                arbitrary_mask = write_video(arbitrary / "mask.mp4", pixels)
                with self.assertRaisesRegex(ValueError, "exact source/mask files"):
                    parts.decode_preparation_window(InputImpl.VideoFromFile(str(arbitrary_source)),
                        InputImpl.VideoFromFile(str(arbitrary_mask)), details, 0, 2, interrupt=lambda: None)

    def test_review_paths_accept_current_loader_cache_and_high_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review = root / 'genj' / 'reviews' / 'shot_0123456789abcdef'
            review.mkdir(parents=True)
            for cache in ('render_audio_v2_3840_x1_3f', 'render_audio_v3_3840_x1_3f', 'render_audio_v3_3840_x1_3f_aspect'):
                details = {'review_shot_id':'shot_0123456789abcdef', 'render_long_edge':3840,
                           'frames':3, 'selected_path':str(review / cache / 'source.mp4')}
                _, source, mask = parts._expected_review_video_paths(root, details)
                self.assertEqual(source, review / cache / 'source.mp4')
                self.assertEqual(mask, review / cache / 'mask.mp4')
            details['selected_path'] = str(review / 'render_audio_v3_3840_x1_4f_aspect' / 'source.mp4')
            with self.assertRaisesRegex(ValueError, 'outside its approved render cache'):
                parts._expected_review_video_paths(root, details)

    def test_rejects_review_mask_changed_after_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = root / "genj" / "reviews" / "shot_0123456789abcdef"
            review_dir.mkdir(parents=True)
            pixels = np.zeros((3, 32, 64, 3), dtype=np.uint8)
            source_path = write_video(review_dir / "source.mp4", pixels)
            mask_path = write_video(review_dir / "mask.mp4", pixels)
            details, _ = review_fixture(root, 3, source_path, mask_path)
            changed = pixels.copy()
            changed[:, 4:20, 5:21] = 255
            write_video(mask_path, changed)
            with patch.object(sys.modules["folder_paths"], "get_output_directory", return_value=str(root), create=True):
                with self.assertRaisesRegex(ValueError, "review files changed"):
                    parts.decode_preparation_window(InputImpl.VideoFromFile(str(source_path)),
                        InputImpl.VideoFromFile(str(mask_path)), details, 0, 2, interrupt=lambda: None)

    def test_rejects_source_and_mask_with_different_active_trim_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = root / "genj" / "reviews" / "shot_0123456789abcdef"
            review_dir.mkdir(parents=True)
            pixels = np.zeros((3, 32, 64, 3), dtype=np.uint8)
            source_path = write_video(review_dir / "source.mp4", pixels)
            mask_path = write_video(review_dir / "mask.mp4", pixels)
            details, _ = review_fixture(root, 2, source_path, mask_path)
            with patch.object(sys.modules["folder_paths"], "get_output_directory", return_value=str(root), create=True):
                source = InputImpl.VideoFromFile(str(source_path), start_time=0, duration=2 / 24)
                shifted_mask = InputImpl.VideoFromFile(str(mask_path), start_time=1 / 24, duration=2 / 24)
                with self.assertRaisesRegex(ValueError, "approved shot beginning"):
                    parts.decode_preparation_window(source, shifted_mask, details, 0, 2,
                                                    interrupt=lambda: None)


class NativePoseCarryTests(unittest.TestCase):
    def test_invalid_body_run_at_chunk_boundary_matches_native_full_sequence_and_draw(self):
        sequence = [detector_frame(i) for i in range(4)]
        sequence.extend(detector_frame(i, invalid=True) for i in range(4, 7))
        sequence.append(detector_frame(7))
        full = native_pose_data(sequence)
        left_native = native_pose_data(sequence[:4])
        right_native = native_pose_data(sequence[4:])
        left, carried = parts.apply_pose_carry(left_native)
        right, final = parts.apply_pose_carry(right_native, left["pose_metas_original"][-1]["keypoints_body"])
        self.assertEqual(tuple(final.shape), (20, 3))
        all_chunked = left["pose_metas_original"] + right["pose_metas_original"]
        for expected, actual in zip(full["pose_metas_original"], all_chunked):
            for name in ("keypoints_body", "keypoints_left_hand", "keypoints_right_hand", "keypoints_face"):
                self.assertTrue(np.array_equal(expected[name], actual[name]), name)
        full_images = [draw(meta) for meta in full["pose_metas"]]
        chunk_images = [draw(meta) for meta in left["pose_metas"] + right["pose_metas"]]
        for expected, actual in zip(full_images, chunk_images):
            self.assertTrue(np.array_equal(expected, actual))
        # Existing inputs and the disconnected second-window metadata stay untouched.
        self.assertTrue(parts._body_is_all_invalid(right_native["pose_metas_original"][0]["keypoints_body"]))
        self.assertFalse(parts._body_is_all_invalid(right["pose_metas_original"][0]["keypoints_body"]))

    def test_rejects_retargeted_or_malformed_native_pose_data_without_mutation(self):
        value = native_pose_data([detector_frame(0)])
        before = value["pose_metas_original"][0]["keypoints_body"].copy()
        with self.assertRaisesRegex(ValueError, "non-retargeted"):
            parts.apply_pose_carry({**value, "retarget_image": torch.zeros(1, 2, 2, 3)})
        with self.assertRaisesRegex(ValueError, "normalized float32"):
            parts.apply_pose_carry(value, np.zeros((19, 3), dtype=np.float32))
        self.assertTrue(np.array_equal(value["pose_metas_original"][0]["keypoints_body"], before))

    def test_rejects_corrupt_face_metadata_before_rebuilding_native_pose(self):
        value = native_pose_data([detector_frame(0)])
        value["pose_metas_original"][0]["keypoints_face"] = np.zeros((68, 3), dtype=np.float32)
        with self.assertRaisesRegex(ValueError, "unsupported shape"):
            parts.apply_pose_carry(value)


class PartSaveTests(unittest.TestCase):
    def test_failed_part_hash_does_not_leave_an_unreceipted_cache_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            details, _ = review_fixture(root, total=1, width=4, height=4)
            key = "d" * 64
            reference = torch.zeros(1, 4, 4, 3)
            frames = torch.zeros(1, 4, 4, 3)
            mask = torch.ones(1, 4, 4)
            window = preparation_window(details, 0, 1, 4, 4)
            _, state = parts.carry_pose_window(native_pose_data([detector_frame(0)]), window, details,
                reference, key, "person", output_root=root)
            directory = root / "genj" / "wan_preparation_parts" / key
            original_file_sha = parts._file_sha
            def fail_shard_hash(path, interrupt=None):
                if Path(path).suffix == ".pt":
                    raise OSError("fixture hash failure")
                return original_file_sha(path, interrupt)
            with patch.object(parts, "_file_sha", side_effect=fail_shard_hash):
                with self.assertRaisesRegex(OSError, "fixture hash failure"):
                    parts.save_preparation_part(frames, mask, frames, frames, reference, window, state,
                        details, key, "person", output_root=root, interrupt=lambda: None)
            self.assertEqual(list(directory.glob("part_*.pt")), [])
            self.assertEqual(list(directory.glob("*.receipt.json")), [])
            self.assertEqual(list(directory.glob("carry_*.json")), [])

    def test_two_parts_save_as_native_v1_shards_with_adjacent_pose_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            details, _ = review_fixture(root, total=5, width=6, height=4)
            key = "a" * 64
            reference = torch.full((1, 4, 4, 3), .25, dtype=torch.float32).contiguous()
            frames = torch.arange(5 * 4 * 6 * 3, dtype=torch.float32).reshape(5, 4, 6, 3).div(500).contiguous()
            masks = torch.zeros(5, 4, 6, dtype=torch.float32)
            masks[3:, 1:3, 2:5] = 1
            poses = torch.full((5, 4, 6, 3), .5, dtype=torch.float32).contiguous()
            faces = torch.full((5, 8, 8, 3), .75, dtype=torch.float32).contiguous()
            seq = [detector_frame(i) for i in range(3)] + [detector_frame(3, invalid=True), detector_frame(4)]
            first_window = preparation_window(details, 0, 3, 6, 4)
            second_window = {**first_window, "start": 3, "count": 2}
            with patch.object(sys.modules["folder_paths"], "get_output_directory", return_value=str(root), create=True):
                first_pose, first_state = parts.carry_pose_window(
                    native_pose_data(seq[:3]), first_window, details, reference, key, "person", output_root=root)
                first_receipt = parts.save_preparation_part(
                    frames[:3].clone(), masks[:3].clone(), poses[:3].clone(), faces[:3].clone(),
                    reference, first_window, first_state, details, key, "person", output_root=root,
                    interrupt=lambda: None)
                second_pose, second_state = parts.carry_pose_window(
                    native_pose_data(seq[3:]), second_window, details, reference, key, "person", output_root=root)
                self.assertFalse(parts._body_is_all_invalid(second_pose["pose_metas_original"][0]["keypoints_body"]))
                second_receipt = parts.save_preparation_part(
                    frames[3:].clone(), masks[3:].clone(), poses[3:].clone(), faces[3:].clone(),
                    reference, second_window, second_state, details, key, "person", output_root=root,
                    interrupt=lambda: None)
                for receipt in (first_receipt, second_receipt):
                    payload = torch.load(receipt["path"], map_location="cpu", weights_only=True)
                    self.assertEqual(payload["version"], 1)
                    self.assertEqual(tuple(payload["footage"]["frames"].shape[1:]), (4, 6, 3))
                    self.assertEqual(payload["footage"]["keep_audio"], False)
                self.assertEqual(first_receipt["carry_in_kind"], "none")
                self.assertEqual(first_receipt["carry_in_sha256"], parts.NONE_CARRY_SHA256)
                self.assertEqual(second_receipt["carry_in_kind"], "body")
                self.assertEqual(first_receipt["carry_out_sha256"], second_receipt["carry_in_sha256"])
                self.assertEqual(first_receipt["render_cache_pin"], second_receipt["render_cache_pin"])
                self.assertEqual(first_state["render_cache_pin"], first_receipt["render_cache_pin"])
                self.assertEqual(second_state["render_cache_pin"], second_receipt["render_cache_pin"])
                self.assertEqual(parts._sha_bytes(Path(first_receipt["path"]).read_bytes()), first_receipt["sha256"])
                self.assertTrue(Path(root / "genj" / "wan_preparation_parts" / key / "carry_00000003.json").is_file())

                merge = importlib.import_module("ComfyUI_zura_nodes.wan_preparation_merge")
                metadata = parts._metadata("person")
                specs = merge.shards_from_receipts([first_receipt, second_receipt], key, 5, metadata)
                final = merge.merge_preparation(specs, root, key, 5, metadata)
                self.assertEqual(final["frames"], 5)
                merged = torch.load(final["path"], map_location="cpu", weights_only=True)
                self.assertTrue(torch.equal(merged["footage"]["frames"], frames))
                self.assertTrue(torch.equal(merged["footage"]["character_mask"], masks))

    def test_empty_part_mask_is_allowed_but_stale_or_corrupt_carry_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            details, _ = review_fixture(root, total=2, width=4, height=4)
            key = "b" * 64
            reference = torch.zeros(1, 4, 4, 3, dtype=torch.float32)
            sequence = [detector_frame(0), detector_frame(1)]
            window = preparation_window(details, 0, 1, 4, 4)
            with patch.object(sys.modules["folder_paths"], "get_output_directory", return_value=str(root), create=True):
                _, state = parts.carry_pose_window(native_pose_data(sequence[:1]), window, details,
                    reference, key, "person", output_root=root)
                receipt = parts.save_preparation_part(
                    torch.zeros(1, 4, 4, 3), torch.zeros(1, 4, 4), torch.zeros(1, 4, 4, 3),
                    torch.zeros(1, 4, 4, 3), reference, window, state, details, key, "person", output_root=root,
                    interrupt=lambda: None)
                self.assertTrue(receipt["path"].endswith("part_00000000_00001.pt"))
                next_window = {**window, "start": 1}
                next_details = dict(details)
                tampered_pin = {**next_window["render_cache_pin"],
                                "source": {**next_window["render_cache_pin"]["source"],
                                           "sha256": "f" * 64}}
                with self.assertRaisesRegex(ValueError, "pins differ from the approved review files"):
                    parts.carry_pose_window(native_pose_data(sequence[1:]),
                        {**next_window, "render_cache_pin": tampered_pin}, details, reference,
                        key, "person", output_root=root)
                wrong_reference = torch.ones_like(reference)
                with self.assertRaisesRegex(ValueError, "different approved source or settings"):
                    parts.carry_pose_window(native_pose_data(sequence[1:]), next_window, next_details,
                        wrong_reference, key, "person", output_root=root)
                part_path = Path(receipt["path"])
                with part_path.open("ab") as handle:
                    handle.write(b"tamper")
                with self.assertRaisesRegex(ValueError, "changed after its receipt"):
                    parts.carry_pose_window(native_pose_data(sequence[1:]), next_window, details,
                        reference, key, "person", output_root=root)

    def test_saver_rejects_storage_views_paths_and_tampered_carry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            details, _ = review_fixture(root, total=1, width=4, height=4)
            key = "c" * 64
            reference = torch.zeros(1, 4, 4, 3)
            window = preparation_window(details, 0, 1, 4, 4)
            _, state = parts.carry_pose_window(native_pose_data([detector_frame(0)]), window, details,
                reference, key, "person", output_root=root)
            frames = torch.zeros(1, 4, 4, 3)
            storage_view = torch.zeros(2, 4, 4, 3)[1:]
            with self.assertRaisesRegex(ValueError, "storage outside"):
                parts.save_preparation_part(storage_view, torch.ones(1, 4, 4), frames, frames, reference,
                    window, state, details, key, "person", output_root=root, interrupt=lambda: None)
            changed = dict(state, carry_out_body=np.ones((20, 3), dtype=np.float32).tolist())
            with self.assertRaisesRegex(ValueError, "output body failed"):
                parts.save_preparation_part(frames, torch.ones(1, 4, 4), frames, frames, reference,
                    window, changed, details, key, "person", output_root=root, interrupt=lambda: None)


if __name__ == "__main__":
    unittest.main()
