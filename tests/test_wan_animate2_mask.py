"""Causal masks, immutable conditioning and background-lock contracts."""
import sys
import types
import unittest
from unittest.mock import patch

import torch
import torch.nn.functional as F
import v2_bootstrap
from wan_animate2_mask import spatial_condition, temporal_mask, prepare_spatial_mask


class VAE:
    def encode(self, image):
        # Deterministic fake VAE exercises geometry/compression, not model quality.
        small = F.avg_pool2d(image.movedim(-1, 1), 8)
        first = small[:1]
        rest = small[1:].reshape(-1, 4, 3, *small.shape[-2:]).mean(1)
        return torch.cat((first, rest)).mean(1)[None, None].repeat(1, 16, 1, 1, 1)


def resize(x, width, height, method, crop):
    assert crop == "center"
    assert x.shape[-2:] == (height, width)
    return x


class MaskTests(unittest.TestCase):
    def setUp(self):
        self.utils = types.ModuleType("comfy.utils")
        self.utils.common_upscale = resize
        self.comfy = types.ModuleType("comfy")
        self.comfy.__path__ = []
        self.comfy.utils = self.utils
        self.modules = patch.dict(sys.modules, {"comfy": self.comfy, "comfy.utils": self.utils})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def inputs(self):
        native = torch.full((1, 16, 3, 4, 4), .5)
        native[:, :, 0] = .8
        mask = torch.ones(1, 1, 3, 4, 4)
        mask[:, :, 0] = 0
        metadata = {"concat_latent_image": native, "concat_mask": mask,
                    "pose_video_latent": torch.zeros(1, 16, 2, 4, 4), "reference_strength": 1.3}
        return dict(positive=[[torch.zeros(1), metadata]], negative=[[torch.ones(1), dict(metadata)]],
                    latent={"samples": torch.zeros_like(native)}, vae=VAE(),
                    source_video=torch.full((5, 32, 32, 3), .2), edit_mask=torch.zeros(5, 32, 32),
                    length=5, trim_latent=1, grow_pixels=0)

    def test_black_locks_source_not_grey_and_keeps_reference(self):
        args = self.inputs()
        pos, neg, out = spatial_condition(**args)
        self.assertTrue(torch.all(out["noise_mask"] == 0))
        self.assertTrue(torch.all(out["samples"][:, :, 0] == .8))
        self.assertTrue(torch.allclose(out["samples"][:, :, 1:], torch.full((1, 16, 2, 4, 4), .2)))
        self.assertTrue(torch.all(pos[0][1]["concat_mask"] == 0))
        self.assertIs(pos[0][1]["pose_video_latent"], args["positive"][0][1]["pose_video_latent"])
        self.assertEqual(neg[0][1]["reference_strength"], 1.3)
        self.assertTrue(torch.all(args["positive"][0][1]["concat_mask"][:, :, 1:] == 1))
        self.assertTrue(torch.all(args["latent"]["samples"] == 0))

    def test_white_edits_video_never_reference(self):
        args = self.inputs()
        args["edit_mask"].fill_(1)
        pos, _, out = spatial_condition(**args)
        self.assertTrue(torch.all(out["noise_mask"][:, :, 0] == 0))
        self.assertTrue(torch.all(out["noise_mask"][:, :, 1:] == 1))
        self.assertTrue(torch.all(pos[0][1]["concat_latent_image"][:, :, 1:] == .5))

    def test_sampler_only_keeps_official_conditioning_and_encodes_source_once(self):
        args = self.inputs()
        args['edit_mask'][:, 4:12, 4:12] = 1
        with patch.object(args['vae'], 'encode', wraps=args['vae'].encode) as encode:
            pos, neg, out = spatial_condition(**args, condition_background=False)
        self.assertEqual(encode.call_count, 1)
        for actual, original in ((pos, args['positive']), (neg, args['negative'])):
            self.assertIsNot(actual[0][1], original[0][1])
            self.assertIs(actual[0][1]['concat_mask'], original[0][1]['concat_mask'])
            self.assertIs(actual[0][1]['concat_latent_image'], original[0][1]['concat_latent_image'])
        self.assertGreater(out['noise_mask'][:, :, 1:].sum(), 0)
        self.assertGreater((out['noise_mask'][:, :, 1:] == 0).sum(), 0)

    def test_conservative_blocks_keep_thin_features_and_partial_edge_blocks(self):
        raw = torch.zeros(1, 1, 35, 37)
        raw[0, 0, 10, 17] = 1
        raw[0, 0, 34, 36] = 1
        actual = prepare_spatial_mask(raw, 0, 16)
        self.assertEqual(actual.shape, raw.shape)
        self.assertTrue(torch.all(actual[0, 0, :16, 16:32] == 1))
        self.assertTrue(torch.all(actual[0, 0, 32:, 32:] == 1))
        self.assertEqual(actual.sum(), 256 + 15)
        self.assertEqual(raw.sum(), 2)

    def test_hole_filling_leaves_exterior_background_and_growth_is_exact(self):
        raw = torch.zeros(1, 1, 24, 24)
        raw[:, :, 8:16, 8:16] = 1
        raw[:, :, 10:14, 10:14] = 0
        actual = prepare_spatial_mask(raw, 2, fill_holes=True)
        expected = torch.zeros_like(raw)
        expected[:, :, 6:18, 6:18] = 1
        self.assertTrue(torch.equal(actual, expected))

    def test_temporal_margin_covers_only_neighbours_and_keeps_long_gaps(self):
        raw = torch.zeros(9, 1, 8, 8)
        raw[2, :, 3, 4] = 1
        actual = prepare_spatial_mask(raw, 0, temporal_radius=1)
        self.assertTrue(torch.all(actual[1:4, 0, 3, 4] == 1))
        self.assertEqual(actual.sum(), 3)
        self.assertEqual(actual[4:].sum(), 0)

    def test_temporal_union_keeps_one_frame_thin_feature(self):
        masks = torch.zeros(9, 4, 4)
        masks[3, 2, 1] = 1
        reduced = temporal_mask(masks)
        self.assertEqual(reduced.shape, (3, 4, 4))
        self.assertEqual(reduced[1, 2, 1], 1)
        self.assertEqual(reduced.sum(), 1)

    def test_static_mask_and_tail_hold(self):
        args = self.inputs()
        args["source_video"] = args["source_video"][:3]
        args["edit_mask"] = torch.ones(1, 32, 32)
        _, _, out = spatial_condition(**args)
        self.assertEqual(out["samples"].shape, (1, 16, 3, 4, 4))

    def test_continuation_is_never_overwritten(self):
        args = self.inputs()
        args["edit_mask"].fill_(1)
        for c in (args["positive"], args["negative"]):
            c[0][1]["concat_mask"][:, :, 1] = 0
            c[0][1]["concat_latent_image"][:, :, 1] = .7
        pos, _, out = spatial_condition(**args)
        self.assertTrue(torch.all(pos[0][1]["concat_latent_image"][:, :, 1] == .7))
        self.assertTrue(torch.all(out["samples"][:, :, 1] == .7))
        self.assertTrue(torch.all(out["noise_mask"][:, :, 1] == 0))

    def test_conditioning_only_ablation_leaves_sampler_unmodified(self):
        args = self.inputs()
        _, _, out = spatial_condition(**args, lock_background=False)
        self.assertIs(out["samples"], args["latent"]["samples"])
        self.assertNotIn("noise_mask", out)

    def test_rejects_misaligned_mask_and_other_model_latent(self):
        for key, value in [("edit_mask", torch.zeros(4, 32, 32)), ("length", 6),
                           ("video_frame_offset", 5), ("edit_mask", torch.full((5, 32, 32), float('nan')))]:
            args = self.inputs()
            args[key] = value
            with self.assertRaises(ValueError):
                spatial_condition(**args)


if __name__ == "__main__":
    unittest.main()
