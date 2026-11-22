"""Check the H3 source-structure constraint independently of model weights."""

import importlib.util
from pathlib import Path
import unittest
import torch

path = Path(__file__).resolve().parents[1] / "artist_studio" / "switch_x_structure.py"
spec = importlib.util.spec_from_file_location("switch_structure", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Model:
    def get_model_object(self, name):
        assert name == "latent_format"
        return self

    def process_in(self, value):
        return value

    def clone(self):
        return Model()

    def set_model_sampler_post_cfg_function(self, fn):
        self.adjust = fn


class StructureGuidance(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(7)
        self.source = torch.rand(1, 24, 2, 6, 12)
        self.replace = torch.zeros(5, 96, 192)
        self.replace[:, :, 96:] = 1

    def test_constant_light_is_allowed_and_audio_is_untouched(self):
        original = Model()
        (guided,) = module.ZuraH3SourceStructure().patch(
            original, {"samples": self.source}, self.replace, 0.96
        )
        video = self.source + 0.12
        audio = torch.randn(1, 1, 120)
        packed = torch.cat((video.reshape(1, 1, -1), audio), -1)
        out = guided.adjust({"denoised": packed})
        torch.testing.assert_close(out, packed, atol=3e-6, rtol=1e-5)
        self.assertTrue(torch.equal(out[:, :, -120:], audio))
        self.assertFalse(hasattr(original, "adjust"))

    def test_only_covered_source_structure_is_constrained(self):
        (guided,) = module.ZuraH3SourceStructure().patch(
            Model(), {"samples": self.source}, self.replace, 1.0
        )
        random = torch.randn_like(self.source)
        packed = torch.cat((random.reshape(1, 1, -1), torch.rand(1, 1, 120)), -1)
        out = guided.adjust({"denoised": packed})[:, :, :-120].reshape_as(random)
        self.assertTrue(torch.equal(out[..., 6:], random[..., 6:]))
        self.assertLess(
            (out[..., :5] - self.source[..., :5]).abs().mean(),
            (random[..., :5] - self.source[..., :5]).abs().mean(),
        )

    def test_black_matte_skips_patch_and_wrong_frame_alignment_is_rejected(self):
        original = Model()
        (unchanged,) = module.ZuraH3SourceStructure().patch(
            original, {"samples": self.source}, torch.ones_like(self.replace), 1.0
        )
        self.assertIs(unchanged, original)
        with self.assertRaisesRegex(ValueError, "padded matte"):
            module.latent_coverage(self.replace[:-1], self.source.shape)


if __name__ == "__main__":
    unittest.main()
