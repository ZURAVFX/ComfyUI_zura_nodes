"""CPU differential tests against the installed native H3 control implementation."""
import importlib
import unittest
from types import SimpleNamespace
from unittest import mock

import torch
import torch.nn.functional as F

import comfy.cli_args
comfy.cli_args.args.cpu = True
import v2_bootstrap

module = importlib.import_module("ComfyUI_zura_nodes.h3_control_data")
native = importlib.import_module("comfy_extras.nodes_minimax_h3")
nodes = importlib.import_module("nodes")


def latent(shape=(1, 24, 37, 2, 4), value=0.2):
    return {"samples": torch.full(shape, value)}


class StubVAE:
    def __init__(self, target_shape):
        self.target_shape = target_shape
        self.calls = []

    def spacial_compression_encode(self):
        return 16

    def encode(self, pixels):
        self.calls.append(pixels.clone())
        # Deliberately depends on space/time/RGB: detects order, threshold and
        # tail-clamping differences without claiming production VAE parity.
        data = pixels.movedim(-1, 1).permute(1, 0, 2, 3)[None]
        data = F.interpolate(data, size=self.target_shape[2:], mode="trilinear", align_corners=False)
        return data.repeat(1, 8, 1, 1, 1)


class Control:
    def __init__(self, norm=False):
        self.inpaint_post_norm = norm
        self.injection_layers = [1, 3]
        self.calls = []

    def init_stream(self, pristine, control, layout, emb):
        self.calls.append(("init", control.clone()))
        return pristine.clone()

    def step(self, index, stream, emb, segments, rope, transformer_options):
        self.calls.append(("step", index))
        return stream, torch.ones_like(stream)


class Model:
    def __init__(self):
        self.model_options = {"transformer_options": {}}
        self.wrappers = []
        self.blocks = {}
        self.sigmas = []

    def clone(self):
        clone = Model()
        clone.model_options = self.model_options
        return clone

    def get_model_object(self, name):
        if name != "model_sampling":
            raise AssertionError(name)
        return SimpleNamespace(percent_to_sigma=lambda value: 100.0 * (1.0 - value))

    def add_wrapper(self, kind, wrapper):
        self.wrappers.append((kind, wrapper))

    def set_model_patch_replace(self, patch, kind, name, index):
        self.blocks[(kind, name, index)] = patch


class H3ControlDataTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(10)
        self.source = torch.rand(7, 20, 27, 3)
        self.control = torch.rand(3, 25, 19, 4)
        self.mask = torch.rand(4, 19, 31)
        self.mask[0, 0, :3] = torch.tensor([0.499, 0.5, 0.501])
        self.target = latent()
        self.patch = SimpleNamespace(model=Control())
        self.prepare = module.ZuraH3PrepareControlPixels()
        self.pack = module.ZuraH3PackEncodedControl()

    def differential(self, temporal, norm):
        target = latent((1, 24, temporal, 2, 4))
        shape = tuple(target["samples"].shape)
        patch = SimpleNamespace(model=Control(norm))
        vae = StubVAE(shape)
        reference = native.MiniMaxH3FunControlPatch(patch, vae, self.control[..., :3].movedim(-1, 1),
                                                  self.mask, self.source.movedim(-1, 1), 1.0, 100.0, 0.0)
        with mock.patch.object(native.comfy.model_management, "loaded_models", return_value=[]), \
             mock.patch.object(native.comfy.model_management, "load_models_gpu"):
            reference.prepare_control_latent(shape)
        native_pixels = vae.calls[:]
        depth, source, visibility = self.prepare.prepare(self.source, self.control, self.mask, target, patch)
        self.assertTrue(torch.equal(depth, native_pixels[0]))
        self.assertTrue(torch.equal(source, native_pixels[1]))
        depth_latent, = nodes.VAEEncode().encode(vae, depth)
        source_latent, = nodes.VAEEncode().encode(vae, source)
        packed, = self.pack.pack(depth_latent, source_latent, visibility, target)
        self.assertEqual(packed["samples"].dtype, torch.float32)
        self.assertEqual(tuple(packed["samples"].shape), (1, 49, temporal, 2, 4))
        self.assertTrue(torch.equal(packed["samples"], reference.control_latent))
        self.assertTrue(torch.equal(depth[-1], depth[2]))
        self.assertTrue(torch.equal(source[-1], source[6]))
        self.assertTrue(torch.equal(packed["samples"][:, :24], depth_latent["samples"]))
        self.assertTrue(torch.equal(packed["samples"][:, 25:], source_latent["samples"]))
        return packed

    def test_exact_native_formula_124_and_107_with_both_normalisations(self):
        for temporal in (37, 32):
            for norm in (False, True):
                with self.subTest(temporal=temporal, norm=norm):
                    self.differential(temporal, norm)

    def test_threshold_at_half_and_single_frame_mask(self):
        mask = torch.full((32, 64), 0.5)
        mask[:, 32:] = 0.50001
        depth, source, visibility = self.prepare.prepare(self.source, self.control, mask, self.target, self.patch)
        self.assertTrue(torch.equal(visibility[:, :, :32], torch.ones_like(visibility[:, :, :32])))
        self.assertEqual(torch.count_nonzero(visibility[:, :, 32:]).item(), 0)
        self.assertEqual(torch.count_nonzero(source[:, :, 32:]).item(), 0)

    def test_pack_casts_native_vae_float_types_to_float32(self):
        shape = self.target["samples"].shape
        vis = torch.ones(124, 32, 64)
        for dtype in (torch.float16, torch.bfloat16, torch.float64):
            packed, = self.pack.pack({"samples": torch.ones(shape, dtype=dtype)},
                                    {"samples": torch.zeros(shape, dtype=dtype)}, vis, self.target)
            self.assertEqual(packed["samples"].dtype, torch.float32)

    def test_invalid_target_channels_temporal_spatial_metadata_and_nonfinite(self):
        invalid = [latent((1, 49, 37, 2, 4)), latent((1, 24, 36, 2, 4)),
                   latent((1, 24, 37, 3, 4)), {**self.target, "unknown": "unsupported"},
                   latent(value=float("nan")), latent(value=float("inf"))]
        for target in invalid:
            with self.subTest(shape=tuple(target["samples"].shape)), self.assertRaises(ValueError):
                self.prepare.prepare(self.source, self.control, self.mask, target, self.patch)

    def test_invalid_pixels_masks_and_actual_model_patch(self):
        cases = [(self.source[..., :2], self.control, self.mask, self.patch),
                 (self.source, self.control.to(torch.int32), self.mask, self.patch),
                 (self.source, self.control, torch.ones_like(self.mask) * 1.01, self.patch),
                 (self.source, self.control, torch.full_like(self.mask, float("nan")), self.patch),
                 (self.source, self.control, self.mask, SimpleNamespace(model=SimpleNamespace(inpaint_post_norm=False)))]
        for source, control, mask, patch in cases:
            with self.assertRaises(ValueError):
                self.prepare.prepare(source, control, mask, self.target, patch)

    def test_bounds_fail_before_fitting_or_packing(self):
        with mock.patch.object(module, "MAX_PREPARED_PIXEL_BYTES", 1), \
             mock.patch.object(module, "_fit", side_effect=AssertionError("allocation reached")):
            with self.assertRaisesRegex(ValueError, "bounded payload"):
                self.prepare.prepare(self.source, self.control, self.mask, self.target, self.patch)
        with mock.patch.object(module, "MAX_LATENT_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "payload limit"):
                self.pack.pack(self.target, self.target, torch.ones(124, 32, 64), self.target)

    def test_pack_rejects_wrong_grid_nonbinary_and_nonfinite(self):
        for visibility in (torch.ones(123, 32, 64), torch.ones(124, 31, 64),
                           torch.full((124, 32, 64), 0.5), torch.full((124, 32, 64), float("inf"))):
            with self.assertRaises(ValueError):
                self.pack.pack(self.target, self.target, visibility, self.target)
        with self.assertRaises(ValueError):
            self.pack.pack(latent((1, 24, 32, 2, 4)), self.target, torch.ones(124, 32, 64), self.target)

    def test_native_registration_sigmas_cleanup_restore_and_no_raw_references(self):
        prepared = self.differential(37, False)
        original = Model()
        result, = module.ZuraH3ApplyEncodedControl().apply(original, self.patch, prepared, 0.7, 0.2, 0.8)
        self.assertIsNot(result, original)
        self.assertEqual(len(original.wrappers), 0)
        patch = result.wrappers[0][1].__self__
        self.assertIsInstance(patch, native.MiniMaxH3FunControlPatch)
        self.assertEqual(patch.sigma_start, 80.0)
        self.assertAlmostEqual(patch.sigma_end, 20.0)
        self.assertEqual(patch.strength, 0.7)
        self.assertEqual(set(result.blocks), {("dit", "double_block", 1), ("dit", "double_block", 3)})
        for block in result.blocks.values():
            self.assertIsInstance(block, native.MiniMaxH3FunControlBlockPatch)
            self.assertIs(block.control_patch, patch)
        self.assertEqual(patch.models(), [self.patch])
        for name in ("vae", "control_video", "source_video", "mask"):
            self.assertIsNone(getattr(patch, name))
        before = prepared["samples"].clone()
        prepared["samples"].zero_()
        with mock.patch.object(native.MiniMaxH3FunControlPatch, "prepare_control_latent",
                               side_effect=AssertionError("raw fallback reached")):
            for _ in range(2):
                patch.prepare_control_latent(self.target["samples"].shape)
                self.assertTrue(torch.equal(patch.control_latent, before))
                patch.control_latent.zero_()
                patch.cleanup()
                self.assertIsNone(patch.control_latent)
                self.assertIsNone(patch.control_latent_shape)
                self.assertFalse(patch.active)
            with self.assertRaisesRegex(ValueError, "target video shape"):
                patch.prepare_control_latent((1, 24, 32, 2, 4))
        patch.to(torch.device("cpu"))
        self.patch.model.inpaint_post_norm = True
        with self.assertRaisesRegex(ValueError, "normalisation changed"):
            patch.prepare_control_latent(self.target["samples"].shape)

    def test_inherited_stream_step_strength_and_audio_skip(self):
        result, = module.ZuraH3ApplyEncodedControl().apply(Model(), self.patch,
                   {"samples": torch.ones(1, 49, 37, 2, 4)}, 0.5)
        patch = result.wrappers[0][1].__self__
        patch.prepare_control_latent(self.target["samples"].shape)
        patch.active = True
        args = {"img": torch.zeros(4, 3), "layout": SimpleNamespace(audio_pos=torch.tensor([2, 3])),
                "t_emb": torch.zeros(1), "mod_segments": None, "rope_freqs": None, "transformer_options": {}}
        patch.before_block(1, args)
        out = {"img": args["img"].clone()}
        returned = patch.after_block(1, args, out)
        self.assertIs(returned, out)
        self.assertTrue(torch.equal(out["img"], torch.tensor([[.5] * 3, [.5] * 3, [0.] * 3, [0.] * 3])))
        patch.after_block(3, args, out)
        self.assertEqual([call[0] for call in self.patch.model.calls], ["init", "step", "step"])
        self.assertEqual([call[1] for call in self.patch.model.calls[1:]], [0, 1])

    def test_apply_rejects_bad_prepared_and_intervals_before_clone(self):
        apply = module.ZuraH3ApplyEncodedControl()
        valid = {"samples": torch.ones(1, 49, 37, 2, 4)}
        for prepared in (self.target, {"samples": valid["samples"].half()},
                         {"samples": valid["samples"], "noise_mask": torch.ones(1, 1, 1, 1, 1)}):
            with self.assertRaises(ValueError):
                apply.apply(Model(), self.patch, prepared)
        for strength, start, end in ((float("nan"), 0, 1), (11, 0, 1), (1, .8, .2), (1, 0, 1.1)):
            with self.assertRaises(ValueError):
                apply.apply(Model(), self.patch, valid, strength, start, end)
        model = Model()
        self.assertIs(apply.apply(model, self.patch, valid, 0)[0], model)

    def test_inherited_wrapper_sigma_boundaries_and_inactive_skip(self):
        result, = module.ZuraH3ApplyEncodedControl().apply(Model(), self.patch,
                   {"samples": torch.ones(1, 49, 37, 2, 4)}, 1, .2, .8)
        patch = result.wrappers[0][1].__self__
        calls = []
        executor = lambda *args, **kwargs: calls.append(patch.active) or "native result"
        for sigma, active in ((80., True), (50., True), (patch.sigma_end, True), (81., False), (19., False)):
            out = patch.diffusion_model_wrapper(executor, [self.target["samples"]], torch.tensor([500.]), None,
                                                {"sigmas": torch.tensor([sigma], dtype=torch.float64)})
            self.assertEqual(out, "native result")
            self.assertEqual(calls[-1], active)
            self.assertIsNone(patch.control_stream)
            self.assertIsNone(patch.pristine_stream)
        patch.cleanup()
        patch.diffusion_model_wrapper(executor, [self.target["samples"]], torch.tensor([50000.]), None, {})
        self.assertTrue(calls[-1])

    def test_half_source_payload_promotion_is_bounded_before_fitting(self):
        # Source output is float32 because the native visibility is float32.
        count, height, width = 124, 32, 64
        too_small = count * height * width * (3 * 2 + 3 * 4 + 4)
        with mock.patch.object(module, "MAX_PREPARED_PIXEL_BYTES", too_small), \
             mock.patch.object(module, "_fit", side_effect=AssertionError("allocation reached")):
            with self.assertRaisesRegex(ValueError, "bounded payload"):
                self.prepare.prepare(self.source.half(), self.control, self.mask, self.target, self.patch)

    def test_meta_sparse_and_integer_latents_fail_closed(self):
        for sample in (torch.empty(1, 24, 37, 2, 4, device="meta"),
                       self.target["samples"].to_sparse(), self.target["samples"].to(torch.int32)):
            with self.assertRaises(ValueError):
                self.prepare.prepare(self.source, self.control, self.mask, {"samples": sample}, self.patch)


if __name__ == "__main__":
    unittest.main()
