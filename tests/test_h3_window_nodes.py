"""CPU-only VIDEO/audio/state IO contracts for the unregistered H3 window data layer."""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import av
import numpy as np
import torch


COMFY_ROOT = Path(os.environ.get("COMFYUI_ROOT", ""))
if COMFY_ROOT.is_dir() and str(COMFY_ROOT) not in sys.path:
    sys.path.insert(0, str(COMFY_ROOT))

import v2_bootstrap  # noqa: E402

PACKAGE = "ComfyUI_zura_nodes.artist_studio"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[PACKAGE] = package

try:
    from comfy.nested_tensor import NestedTensor
    USING_NATIVE_NESTED_TENSOR = True
except ImportError:
    comfy = types.ModuleType("comfy")
    comfy.__path__ = []
    nested_module = types.ModuleType("comfy.nested_tensor")

    class NestedTensor:
        def __init__(self, tensors):
            self.tensors = list(tensors)
            self.is_nested = True

    nested_module.NestedTensor = NestedTensor
    comfy.nested_tensor = nested_module
    sys.modules.setdefault("comfy", comfy)
    sys.modules["comfy.nested_tensor"] = nested_module
    USING_NATIVE_NESTED_TENSOR = False

WINDOWS = importlib.import_module("ComfyUI_zura_nodes.artist_studio.h3_windows")
IO = importlib.import_module("ComfyUI_zura_nodes.artist_studio.h3_window_nodes")


try:
    from comfy_api.latest._input_impl.video_types import VideoFromFile as _NativeVideoFromFile
except ImportError:
    _NativeVideoFromFile = None


if _NativeVideoFromFile is not None:
    class NativeVideoSource(_NativeVideoFromFile):
        """Actual installed Comfy VIDEO object with full materialization forbidden."""

        def __init__(self, path, trim=(0.0, 0.0)):
            super().__init__(str(path), start_time=trim[0], duration=trim[1])
            self.components_calls = 0

        def get_components(self):
            self.components_calls += 1
            raise AssertionError("H3 window loading must never materialize full VIDEO components")
else:
    class NativeVideoSource:
        """Minimal Comfy VIDEO stream-source contract; full-frame API is forbidden."""

        def __init__(self, path, trim=(0.0, 0.0)):
            self.path = str(path)
            self.trim = trim
            self.components_calls = 0

        def get_stream_source(self):
            return self.path

        def get_active_trim_window(self):
            return self.trim

        def get_components(self):
            self.components_calls += 1
            raise AssertionError("H3 window loading must never materialize full VIDEO components")


def write_video(path: Path, frames: list[np.ndarray], pixel_format: str) -> Path:
    height, width = frames[0].shape[:2]
    container = av.open(str(path), mode="w", format="avi")
    stream = container.add_stream("rawvideo", rate=24)
    stream.width = width
    stream.height = height
    stream.pix_fmt = pixel_format
    try:
        for pixels in frames:
            frame = av.VideoFrame.from_ndarray(pixels, format=pixel_format)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    finally:
        container.close()
    return path


def make_media(directory: Path, count: int = 136):
    source_frames = []
    combined_frames = []
    genuine_frames = []
    for index in range(count):
        source_frames.append(np.full((32, 32, 3), index % 256, dtype=np.uint8))
        combined = np.zeros((16, 16), dtype=np.uint8)
        combined[1:4, 1:5] = 255
        combined_frames.append(combined)
        genuine = np.zeros((16, 16), dtype=np.uint8)
        if 4 <= index < 132:
            genuine[2, 2] = 255
        if index == 120:
            genuine[15, 15] = 255  # Outside the decoded context, inside the same shot.
        genuine_frames.append(genuine)
    source = NativeVideoSource(write_video(directory / "source.avi", source_frames, "bgr24"))
    combined = NativeVideoSource(write_video(directory / "combined.avi", combined_frames, "gray"))
    genuine = NativeVideoSource(write_video(directory / "genuine.avi", genuine_frames, "gray"))
    return source, combined, genuine


def native_latent(token_count=37, raster=(32, 32)):
    width, height = raster
    video = torch.arange(24 * token_count * (height // 16) * (width // 16),
                         dtype=torch.float32).reshape(1, 24, token_count, height // 16, width // 16)
    audio = torch.arange(1 * 32 * 2 * 207, dtype=torch.float32).reshape(1, 32, 2, 207)
    video_mask = torch.full_like(video, 0.75)
    audio_mask = torch.full_like(audio, 0.5)
    return {"samples": NestedTensor((video, audio)),
            "noise_mask": NestedTensor((video_mask, audio_mask)),
            "metadata": {"keep": "same"}}


class WindowDecodeTests(unittest.TestCase):
    def test_streamed_decode_pads_tiny_cut_fragments_and_selects_shot_regions(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, combined, genuine = make_media(Path(temporary))
            details = {
                "frames": 136, "fps": 24, "width": 32, "height": 32,
                "text_regions_size": [16, 16],
                "text_regions": [{"x": 0, "y": 0, "width": 1, "height": 1}],
                "text_regions_by_shot": [
                    {"start": 0, "end": 4, "regions": []},
                    {"start": 4, "end": 132,
                     "regions": [{"x": 4, "y": 5, "width": 6, "height": 7}]},
                    {"start": 132, "end": 136, "regions": [{"x": 8, "y": 1, "width": 2, "height": 3}]},
                ],
            }
            plan = WINDOWS.plan_h3_windows(136, (4, 132))
            first_tiny, main, continuation, last_tiny = plan
            self.assertEqual((first_tiny.valid_frames, last_tiny.valid_frames), (4, 4))
            self.assertEqual((first_tiny.overlap_frames, last_tiny.overlap_frames), (0, 0))
            self.assertEqual((main.shot_index, continuation.shot_index), (1, 1))

            audio_samples = torch.arange(136 * 32000 // 24, dtype=torch.float32)[None, None]
            full_audio = IO.ZuraH3PrepareFullAudioTimeline().prepare(
                {"waveform": audio_samples, "sample_rate": 32000}, 136, audio_start_frame=4)[0]
            decoded_outputs = IO.ZuraH3WindowInputs().load(
                source, combined, genuine, full_audio, details, json.dumps(asdict(main)))
            decoded = IO.H3WindowData(*decoded_outputs, main)

            self.assertEqual(tuple(decoded.source_frames.shape), (124, 32, 32, 3))
            self.assertEqual(tuple(decoded.combined_mask.shape), (124, 16, 16))
            self.assertEqual(tuple(decoded.genuine_mask.shape), (124, 16, 16))
            self.assertEqual(tuple(decoded.whole_shot_genuine_union.shape), (1, 16, 16))
            self.assertTrue(torch.all(decoded.source_frames[:90, 0, 0, 0]
                                      == torch.arange(4, 94, dtype=torch.float32) / 255))
            self.assertTrue(torch.all(decoded.source_frames[90:] == decoded.source_frames[89]))
            self.assertTrue(torch.all(decoded.combined_mask[:90, 1:4, 1:5] == 1))
            self.assertTrue(torch.all(decoded.combined_mask[90:] == decoded.combined_mask[89]))
            self.assertTrue(torch.all(decoded.genuine_mask[:90, 2, 2] == 1))
            self.assertTrue(torch.all(decoded.genuine_mask[90:] == decoded.genuine_mask[89]))
            self.assertEqual(decoded.whole_shot_genuine_union[0, 15, 15].item(), 1.0)
            self.assertEqual(decoded.clip_details["text_regions"], details["text_regions_by_shot"][1]["regions"])
            self.assertEqual(decoded.clip_details["text_regions_by_shot"], details["text_regions_by_shot"])
            self.assertEqual(decoded.clip_details["h3_window"]["shot_index"], 1)

            # Audio slices use global boundaries. The chosen track starts at frame 4;
            # all model padding stays silent, including across the following cut.
            segment = decoded.audio["waveform"]
            start, end = WINDOWS.audio_sample_bounds(main.input_start, main.input_end, 32000)
            context_end = WINDOWS.audio_sample_bounds(main.input_start,
                                                       main.input_start + 124, 32000)[1]
            self.assertTrue(torch.equal(segment[..., :end - start], full_audio["waveform"][..., start:end]))
            self.assertEqual(segment.shape[-1], context_end - start)
            self.assertTrue(torch.equal(segment[..., end - start:], torch.zeros_like(segment[..., end - start:])))

            tiny = IO.decode_h3_window_data(source, combined, genuine, full_audio, details, last_tiny)
            self.assertEqual(tiny.clip_details["text_regions"], details["text_regions_by_shot"][2]["regions"])
            self.assertEqual(tiny.source_frames.shape, (124, 32, 32, 3))
            self.assertTrue(torch.all(tiny.source_frames[:4, 0, 0, 0]
                                      == torch.arange(132, 136, dtype=torch.float32) / 255))
            self.assertTrue(torch.all(tiny.source_frames[4:] == tiny.source_frames[3]))
            self.assertEqual(float(tiny.genuine_mask.sum()), 0.0)
            self.assertTrue(torch.equal(tiny.audio["waveform"][..., :4 * 32000 // 24],
                                        full_audio["waveform"][..., 132 * 32000 // 24:]))
            self.assertEqual(float(tiny.audio["waveform"][..., 4 * 32000 // 24:].abs().sum()), 0.0)
            self.assertEqual((source.components_calls, combined.components_calls, genuine.components_calls),
                             (0, 0, 0))

    def test_audio_timeline_applies_one_global_offset_at_supported_sample_rates(self):
        for sample_rate in (24000, 32000, 48000):
            with self.subTest(sample_rate=sample_rate):
                timeline_samples = 130 * sample_rate // 24
                onset = WINDOWS.audio_sample_bounds(0, 3, sample_rate)[1]
                sample_count = timeline_samples - onset
                source = torch.arange(sample_count, dtype=torch.float32)[None, None]
                full = IO.prepare_full_audio_timeline(
                    {"waveform": source, "sample_rate": sample_rate}, 130, 3)
                self.assertEqual(full["waveform"][..., :onset].abs().sum().item(), 0.0)
                self.assertTrue(torch.equal(full["waveform"][..., onset:onset + sample_count], source))
                for start, end in ((0, 3), (3, 122), (117, 130)):
                    left, right = WINDOWS.audio_sample_bounds(start, end, sample_rate)
                    actual = WINDOWS.slice_audio_frames(full["waveform"], start, end, sample_rate)
                    self.assertTrue(torch.equal(actual, full["waveform"][..., left:right]))

    def test_rejects_nonaligned_video_metadata_and_missing_stream_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, combined, genuine = make_media(Path(temporary), count=10)
            window = WINDOWS.plan_h3_windows(10)[0]
            full_audio = IO.prepare_full_audio_timeline(
                {"waveform": torch.zeros(1, 1, 10000), "sample_rate": 24000}, 10)
            details = {"frames": 10, "fps": 23.976, "width": 32, "height": 32}
            with self.assertRaisesRegex(ValueError, "24 fps"):
                IO.decode_h3_window_data(source, combined, genuine, full_audio, details, window)

            class BrokenVideo:
                def get_components(self):
                    raise AssertionError("must not call get_components")

            details["fps"] = 24
            with self.assertRaisesRegex(ValueError, "stream source"):
                IO.decode_h3_window_data(BrokenVideo(), combined, genuine, full_audio, details, window)

    def test_native_video_trim_uses_frame_aligned_stream_source_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, combined, genuine = make_media(Path(temporary), count=10)
            trim = (1 / 24, 2 / 24)
            source = NativeVideoSource(source.get_stream_source(), trim)
            combined = NativeVideoSource(combined.get_stream_source(), trim)
            genuine = NativeVideoSource(genuine.get_stream_source(), trim)
            window = WINDOWS.plan_h3_windows(2)[0]
            audio = IO.prepare_full_audio_timeline(
                {"waveform": torch.zeros(1, 1, 2000), "sample_rate": 24000}, 2)
            details = {"frames": 2, "fps": 24, "width": 32, "height": 32,
                       "text_regions_by_shot": [{"start": 0, "end": 2, "regions": []}]}
            result = IO.decode_h3_window_data(source, combined, genuine, audio, details, window)
            self.assertTrue(torch.all(result.source_frames[:2, 0, 0, 0]
                                      == torch.tensor([1, 2], dtype=torch.float32) / 255))
            self.assertTrue(torch.all(result.source_frames[2:] == result.source_frames[1]))
            self.assertEqual(result.clip_details["text_regions"], [])
            mismatched_mask_trim = NativeVideoSource(combined.get_stream_source(), (0.0, 2 / 24))
            with self.assertRaisesRegex(ValueError, "same active VIDEO trim"):
                IO.decode_h3_window_data(source, mismatched_mask_trim, genuine,
                                         audio, details, window)


class ContinuationStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output_root = Path(self.temporary.name)
        try:
            import folder_paths
        except ImportError:
            folder_paths = types.ModuleType("folder_paths")
            sys.modules["folder_paths"] = folder_paths
        self.folder_paths = folder_paths
        self.folder_patch = patch.object(folder_paths, "get_output_directory",
                                         return_value=str(self.output_root), create=True)
        self.folder_patch.start()
        self.addCleanup(self.folder_patch.stop)

    def test_persists_native_prefix_and_guide_and_applies_only_video_prefix(self):
        for total, endpoint, expected_tokens in (
                (125, 90, 27), (144, 107, 32), (240, 124, 37), (244, 90, 27)):
            with self.subTest(total=total, endpoint=endpoint):
                digest = f"{total:064x}"[-64:]
                model_digest = "b" * 64
                plan = WINDOWS.plan_h3_windows(total)
                previous = next(window for window in plan
                                 if window.valid_frames == endpoint and window.carry_video_tokens == 2)
                next_window = plan[previous.index + 1]
                self.assertEqual(previous.valid_frames, endpoint)
                latent = native_latent()
                native_frames = torch.linspace(0, 1, 124)[:, None, None, None].expand(124, 32, 32, 3).contiguous()
                state = IO.save_h3_continuation(latent, native_frames, previous, digest, model_digest)
                count = WINDOWS.h3_video_token_count(endpoint)
                self.assertEqual(count, expected_tokens)
                expected = latent["samples"].tensors[0][:, :, count - 2:count]
                self.assertEqual(state.prefix.video_tokens.shape, (1, 24, 2, 2, 2))
                self.assertTrue(torch.equal(state.prefix.video_tokens, expected))
                self.assertTrue(torch.equal(state.guide_frames,
                                            native_frames[endpoint - 5:endpoint]))
                expected_path = self.output_root / "genj" / "h3_continuation" / digest
                state_directory = expected_path / f"window-{previous.index:06d}"
                self.assertTrue((state_directory / "state.safetensors").is_file())
                manifest = json.loads((state_directory / "state.json").read_text(encoding="utf-8"))["manifest"]
                self.assertEqual(manifest["guide"]["window_local_frame_range"],
                                 [endpoint - 5, endpoint])
                self.assertEqual(manifest["guide"]["global_clip_frame_range"],
                                 [previous.input_start + endpoint - 5, previous.input_end])
                loaded, loader_guide = IO.ZuraLoadH3Continuation().load(
                    json.dumps(asdict(next_window)), digest, model_digest, 32, 32)
                self.assertTrue(torch.equal(loaded.prefix.video_tokens, expected))
                self.assertEqual(loaded.state_sha256, state.state_sha256)
                self.assertTrue(torch.equal(loader_guide, state.guide_frames))
                applied, guide = IO.ZuraApplyH3Continuation().apply(native_latent(), loaded)
                video, audio = applied["samples"].tensors
                video_mask, audio_mask = applied["noise_mask"].tensors
                self.assertTrue(torch.equal(video[:, :, :2], expected))
                self.assertTrue(torch.equal(video_mask[:, :, :2], torch.zeros_like(video_mask[:, :, :2])))
                self.assertTrue(torch.equal(video_mask[:, :, 2:], torch.full_like(video_mask[:, :, 2:], 0.75)))
                self.assertTrue(torch.equal(audio, native_latent()["samples"].tensors[1]))
                self.assertTrue(torch.equal(audio_mask, native_latent()["noise_mask"].tensors[1]))
                self.assertEqual(guide.shape, (5, 32, 32, 3))
                self.assertTrue(torch.equal(guide, loaded.guide_frames))
                self.assertTrue(torch.equal(native_frames[endpoint - 5:endpoint], guide))

    def test_rejects_mismatched_stale_corrupt_or_overwrite_state(self):
        plan = WINDOWS.plan_h3_windows(240)
        previous, next_window = plan[:2]
        digest = "a" * 64
        model_digest = "b" * 64
        latent = native_latent()
        frames = torch.zeros(124, 32, 32, 3)
        state = IO.save_h3_continuation(latent, frames, previous, digest, model_digest)
        # Identical state is idempotent; changed state under the same key is rejected.
        again = IO.save_h3_continuation(latent, frames, previous, digest, model_digest)
        self.assertEqual(again.state_sha256, state.state_sha256)
        with self.assertRaisesRegex(ValueError, "mismatched"):
            IO.save_h3_continuation(latent, frames + 0.1, previous, digest, model_digest)

        mismatched_requests = (
            ("c" * 64, model_digest, (32, 32)),
            (digest, "d" * 64, (32, 32)),
            (digest, model_digest, (64, 32)),
        )
        for request in mismatched_requests:
            with self.subTest(request=request), self.assertRaises(ValueError):
                IO.load_h3_continuation(next_window, *request)

        across_cut = replace(next_window, shot_index=1)
        with self.assertRaises(ValueError):
            IO.load_h3_continuation(across_cut, digest, model_digest, (32, 32))

        import json
        state_directory = (self.output_root / "genj" / "h3_continuation" / digest
                           / "window-000000")
        envelope = json.loads((state_directory / "state.json").read_text(encoding="utf-8"))
        envelope["state_sha256"] = "0" * 64
        (state_directory / "state.json").write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing, stale, corrupt or mismatched"):
            IO.load_h3_continuation(next_window, digest, model_digest, (32, 32))

        with self.assertRaises(TypeError):
            IO.load_h3_continuation(next_window, digest, model_digest, (32, 32),
                                    arbitrary_path=str(self.output_root))

    def test_rejects_symlinked_state_keys_and_oversized_native_guide(self):
        plan = WINDOWS.plan_h3_windows(240)
        digest = "e" * 64
        root = self.output_root / "genj" / "h3_continuation"
        root.mkdir(parents=True)
        generation_path = root / digest
        real_is_symlink = Path.is_symlink

        def report_generation_symlink(path):
            if path == generation_path:
                return True
            return real_is_symlink(path)

        with patch.object(Path, "is_symlink", report_generation_symlink):
            with self.assertRaisesRegex(ValueError, "redirected"):
                IO._state_directory(root, digest, 0)

        frames = torch.zeros(124, 32, 32, 3)
        with patch.object(IO, "_MAX_STATE_BYTES", 1024):
            with self.assertRaisesRegex(ValueError, "guide exceeds"):
                IO.save_h3_continuation(native_latent(), frames, plan[0], digest, "f" * 64)
        self.assertFalse(generation_path.exists())

    def test_loader_always_revalidates_cached_disk_state(self):
        changed = IO.ZuraLoadH3Continuation.IS_CHANGED(
            next_window_json="{}", generation_digest="a" * 64,
            model_digest="b" * 64, width=704, height=1280)
        self.assertTrue(changed != changed)  # ComfyUI cache-bypass NaN sentinel.

    def test_rejects_cross_cut_context_and_bad_model_or_native_guide(self):
        plan = WINDOWS.plan_h3_windows(240, (4,))
        self.assertTrue(all(window.carry_video_tokens is None or window.shot_end > window.owned_end
                            for window in plan))
        for frames in (torch.full((124, 32, 32, 3), float("nan")),
                       torch.full((124, 32, 32, 3), 1.1),
                       torch.zeros((123, 32, 32, 3))):
            with self.subTest(shape=tuple(frames.shape)), self.assertRaises(ValueError):
                IO.save_h3_continuation(native_latent(), frames, plan[0], "a" * 64, "b" * 64)


if __name__ == "__main__":
    unittest.main()
