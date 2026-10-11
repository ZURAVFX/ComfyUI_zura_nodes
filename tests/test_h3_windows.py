"""CPU-only contracts for bounded MiniMax H3 continuation data helpers."""
from __future__ import annotations

import importlib
import os
import sys
import types
import unittest
from dataclasses import replace
from pathlib import Path

import torch


# When available, exercise ComfyUI's real NestedTensor container. Set
# COMFYUI_ROOT to the local ComfyUI checkout for that path.
COMFY_ROOT = Path(os.environ.get("COMFYUI_ROOT", ""))
if COMFY_ROOT.is_dir() and str(COMFY_ROOT) not in sys.path:
    sys.path.insert(0, str(COMFY_ROOT))

import v2_bootstrap  # noqa: E402

# Import the data module without Studio registration or Comfy device setup.
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

MODULE = importlib.import_module("ComfyUI_zura_nodes.artist_studio.h3_windows")


def _latent(*, token_count=37, height=2, width=3):
    video = torch.arange(24 * token_count * height * width, dtype=torch.float32).reshape(
        1, 24, token_count, height, width)
    audio = torch.arange(1 * 32 * 2 * 207, dtype=torch.float32).reshape(1, 32, 2, 207)
    video_mask = torch.linspace(0, 1, video.numel(), dtype=torch.float32).reshape_as(video)
    audio_mask = torch.linspace(1, 0, audio.numel(), dtype=torch.float32).reshape_as(audio)
    return {
        "samples": NestedTensor((video, audio)),
        "noise_mask": NestedTensor((video_mask, audio_mask)),
        "metadata": {"private_key": "unchanged"},
    }


class WindowPlannerTests(unittest.TestCase):
    def _assert_plan(self, total, cuts, expected):
        plan = MODULE.plan_h3_windows(total, cuts)
        actual = [(p.input_start, p.valid_frames, p.owned_start, p.owned_end)
                  for p in plan]
        self.assertEqual(actual, expected)
        cursor = 0
        for part in plan:
            self.assertEqual(part.owned_start, cursor)
            self.assertLessEqual(part.valid_frames, 124)
            self.assertEqual(part.padded_frames, 124 - part.valid_frames)
            self.assertEqual(part.input_end, part.owned_end)
            self.assertGreaterEqual(part.input_start, part.shot_start)
            self.assertLessEqual(part.input_end, part.shot_end)
            if part.overlap_frames:
                self.assertEqual(part.overlap_frames, 5)
                self.assertEqual(part.input_start + 5, part.owned_start)
            if not part.is_terminal:
                self.assertIn(part.valid_frames, (5, 22, 39, 56, 73, 90, 107, 124))
                self.assertEqual(part.carry_video_tokens, 2)
                self.assertGreaterEqual(part.shot_end - part.owned_end, 34)
            else:
                self.assertIsNone(part.carry_video_tokens)
            cursor = part.owned_end
        self.assertEqual(cursor, total)
        return plan

    def test_approved_arithmetic_cases_and_tiny_cut_fragments(self):
        self._assert_plan(125, (), [(0, 90, 0, 90), (85, 40, 90, 125)])
        self._assert_plan(144, (), [(0, 107, 0, 107), (102, 42, 107, 144)])
        self._assert_plan(244, (), [(0, 124, 0, 124), (119, 90, 124, 209),
                                   (204, 40, 209, 244)])
        self._assert_plan(240, (), [(0, 124, 0, 124), (119, 121, 124, 240)])
        self._assert_plan(570, (466,), [(0, 124, 0, 124), (119, 124, 124, 243),
                                        (238, 124, 243, 362), (357, 109, 362, 466),
                                        (466, 104, 466, 570)])
        tiny = self._assert_plan(127, (2, 125), [(0, 2, 0, 2), (2, 123, 2, 125),
                                                (125, 2, 125, 127)])
        self.assertEqual([part.shot_index for part in tiny], [0, 1, 2])
        self.assertTrue(all(part.overlap_frames == 0 for part in tiny))

    def test_cut_reset_and_every_short_length(self):
        for total in range(1, 351):
            plan = MODULE.plan_h3_windows(total)
            self.assertEqual([p.owned_start for p in plan],
                             [0] + [p.owned_end for p in plan[:-1]])
            self.assertEqual(plan[-1].owned_end, total)
        for fragment in range(1, 5):
            plan = MODULE.plan_h3_windows(fragment + 130, (fragment,))
            cut_right = next(p for p in plan if p.shot_start == fragment)
            self.assertEqual(cut_right.input_start, fragment)
            self.assertEqual(cut_right.overlap_frames, 0)
            self.assertEqual(plan[0].owned_end, fragment)

    def test_rejects_invalid_clip_and_cut_indices(self):
        for total, cuts in ((0, ()), (True, ()), (4.5, ()), (10, None),
                            (10, "2"), (10, (0,)),
                            (10, (10,)), (10, (4, 4)), (10, (5, 3)),
                            (10, (True,)), (10, (2.0,))):
            with self.subTest(total=total, cuts=cuts), self.assertRaises(ValueError):
                MODULE.plan_h3_windows(total, cuts)


class AudioTimelineTests(unittest.TestCase):
    def test_global_rational_boundaries_at_supported_rates(self):
        for rate in (24000, 32000, 48000):
            cuts = (0, 5, 119, 238, 362, 570)
            bounds = [MODULE.audio_sample_bounds(a, b, rate) for a, b in zip(cuts, cuts[1:])]
            self.assertEqual(bounds[0][0], 0)
            for left, right in zip(bounds, bounds[1:]):
                self.assertEqual(left[1], right[0])
            self.assertEqual(bounds[-1][1], 570 * rate // 24)
            self.assertTrue(all(end >= start for start, end in bounds))
        self.assertEqual(MODULE.audio_sample_bounds(119, 243, 32000),
                         (119 * 32000 // 24, 243 * 32000 // 24))

    def test_slice_uses_global_bounds_and_returns_an_independent_copy(self):
        rate = 32000
        waveform = torch.arange(570 * rate // 24, dtype=torch.float32)[None, None]
        start, end = MODULE.audio_sample_bounds(119, 243, rate)
        actual = MODULE.slice_audio_frames(waveform, 119, 243, rate)
        self.assertTrue(torch.equal(actual, waveform[..., start:end]))
        self.assertIsNot(actual, waveform[..., start:end])
        original = waveform.clone()
        actual.zero_()
        self.assertTrue(torch.equal(waveform, original))

    def test_rejects_invalid_audio_inputs(self):
        valid = torch.zeros(1, 2, 1000)
        for args in ((-1, 5, 32000), (5, 4, 32000), (0, 5, 0),
                     (0.0, 5, 32000), (False, 5, 32000)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                MODULE.audio_sample_bounds(*args)
        for waveform in (torch.zeros(0), torch.zeros(1, 0, 1000), torch.zeros(0, 2, 1000),
                         torch.zeros(1000, dtype=torch.int32),
                         torch.full((1000,), float("nan"))):
            with self.subTest(shape=waveform.shape, dtype=waveform.dtype), self.assertRaises(ValueError):
                MODULE.slice_audio_frames(waveform, 0, 1, 32000)
        with self.assertRaisesRegex(ValueError, "beyond"):
            MODULE.slice_audio_frames(valid, 0, 2, 32000)


class VideoPrefixTests(unittest.TestCase):
    def test_native_endpoint_mapping_and_extracts_the_valid_tokens_not_padding(self):
        for endpoint, count, first_index in ((124, 37, 35), (107, 32, 30), (90, 27, 25)):
            self.assertEqual(MODULE.h3_video_token_count(endpoint), count)
            latent = _latent(token_count=37)
            prefix = MODULE.extract_video_prefix(latent, endpoint)
            self.assertEqual(prefix.video_tokens.shape, (1, 24, 2, 2, 3))
            self.assertEqual(prefix.video_tokens.device.type, "cpu")
            self.assertEqual((prefix.valid_frames, prefix.token_count), (endpoint, count))
            self.assertTrue(torch.equal(prefix.video_tokens,
                                        latent["samples"].tensors[0][:, :, first_index:first_index + 2]))
        for endpoint in (4, 6, 89, 91, 108, 123, 125, True, 90.0):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                MODULE.h3_video_token_count(endpoint)

    def test_applies_only_the_two_video_prefix_tokens_and_two_noise_masks(self):
        previous = _latent()
        prefix = MODULE.extract_video_prefix(previous, 124)
        target = _latent()
        before_video = target["samples"].tensors[0].clone()
        before_audio = target["samples"].tensors[1].clone()
        before_video_mask = target["noise_mask"].tensors[0].clone()
        before_audio_mask = target["noise_mask"].tensors[1].clone()

        output = MODULE.apply_video_prefix(target, prefix)
        result_video, result_audio = output["samples"].tensors
        result_video_mask, result_audio_mask = output["noise_mask"].tensors
        self.assertTrue(torch.equal(result_video[:, :, :2], prefix.video_tokens))
        self.assertTrue(torch.equal(result_video[:, :, 2:], before_video[:, :, 2:]))
        self.assertTrue(torch.equal(result_video_mask[:, :, :2], torch.zeros_like(result_video_mask[:, :, :2])))
        self.assertTrue(torch.equal(result_video_mask[:, :, 2:], before_video_mask[:, :, 2:]))
        self.assertIs(result_audio, target["samples"].tensors[1])
        self.assertIs(result_audio_mask, target["noise_mask"].tensors[1])
        self.assertTrue(torch.equal(result_audio, before_audio))
        self.assertTrue(torch.equal(result_audio_mask, before_audio_mask))
        self.assertEqual(output["metadata"], {"private_key": "unchanged"})
        self.assertTrue(torch.equal(target["samples"].tensors[0], before_video))
        self.assertTrue(torch.equal(target["noise_mask"].tensors[0], before_video_mask))
        self.assertTrue(torch.equal(previous["samples"].tensors[0][:, :, -2:],
                                    prefix.video_tokens))

    def test_rejects_bad_latents_prefixes_and_masks(self):
        valid = _latent()
        prefix = MODULE.extract_video_prefix(valid, 124)
        bad_sample_latents = [
            {},
            {"samples": torch.zeros(1, 24, 37, 2, 3)},
            {"samples": NestedTensor((torch.zeros(1, 23, 37, 2, 3), valid["samples"].tensors[1]))},
            {"samples": NestedTensor((torch.full((1, 24, 37, 2, 3), float("inf")),
                                       valid["samples"].tensors[1]))},
        ]
        for latent in bad_sample_latents:
            with self.subTest(latent=type(latent.get("samples"))), self.assertRaises(ValueError):
                MODULE.extract_video_prefix(latent, 124)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            MODULE.extract_video_prefix(_latent(token_count=26), 90)

        for corrupted in (
            replace(prefix, token_count=32),
            replace(prefix, video_tokens=torch.full_like(prefix.video_tokens, float("nan"))),
            replace(prefix, video_tokens=torch.zeros(1, 24, 2, 3, 2)),
        ):
            with self.subTest(shape=corrupted.video_tokens.shape), self.assertRaises(ValueError):
                MODULE.apply_video_prefix(valid, corrupted)
        with self.assertRaises(ValueError):
            MODULE.apply_video_prefix({"samples": valid["samples"]}, prefix)
        wrong_mask = {**valid, "noise_mask": NestedTensor((torch.zeros(1, 24, 36, 2, 3),
                                                             valid["noise_mask"].tensors[1]))}
        with self.assertRaisesRegex(ValueError, "match"):
            MODULE.apply_video_prefix(wrong_mask, prefix)
        out_of_range_mask = {**valid, "noise_mask": NestedTensor((
            torch.full_like(valid["noise_mask"].tensors[0], 1.1),
            valid["noise_mask"].tensors[1]))}
        with self.assertRaisesRegex(ValueError, "noise masks"):
            MODULE.apply_video_prefix(out_of_range_mask, prefix)


if __name__ == "__main__":
    unittest.main()
