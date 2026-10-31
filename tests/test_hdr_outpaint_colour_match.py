"""Colour harmonisation cannot alter the unblended native HDR interior."""
import importlib
import sys
import types
import unittest

import torch
import v2_bootstrap

for name, folder in [('ComfyUI_zura_nodes.artist_studio', 'artist_studio'),
                     ('ComfyUI_zura_nodes.paintout', 'paintout')]:
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(v2_bootstrap.ROOT / folder)]
        sys.modules[name] = package
canvas = importlib.import_module('ComfyUI_zura_nodes.artist_studio.ltx_outpaint')
colour = importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


class ColourMatchTests(unittest.TestCase):
    def fixture(self, frames=1):
        source = colour.encode_ct(torch.full((frames, 160, 256, 3), 2.0))
        generated = colour.encode_ct(torch.full_like(source, 3.0))
        mask = torch.ones(source.shape[:3]); mask[:, 48:112, 80:176] = 0
        return generated, source, mask

    def test_matches_exposure_at_all_edges_and_keeps_interior_exact(self):
        generated, source, mask = self.fixture()
        result = canvas.composite_hdr_outpaint(generated, source, mask, 8, 1)
        self.assertTrue(torch.equal(result[:, 56:104, 88:168], source[:, 56:104, 88:168]))
        self.assertTrue(torch.isfinite(result).all())
        self.assertTrue(torch.equal(result[mask == 0], source[mask == 0]), 'Native plate remains exact up to its edge')
        for y, x in [(48, 128), (111, 128), (80, 80), (80, 175)]:
            torch.testing.assert_close(result[:, y, x], source[:, y, x], rtol=0, atol=1e-6)

    def test_black_padding_never_becomes_the_colour_reference(self):
        generated, source, mask = self.fixture()
        source = torch.where(mask[..., None] > .5, colour.encode_ct(torch.zeros_like(source)), source)
        result = canvas.composite_hdr_outpaint(generated, source, mask, 8, 1)
        at_edge = colour.decode_ct(result[:, 47, 128])
        self.assertGreater(float(at_edge.min()), 1.8)

    def test_noop_when_matching_is_disabled_or_no_reference_exists(self):
        generated, source, mask = self.fixture()
        self.assertTrue(torch.equal(canvas.composite_hdr_outpaint(generated, source, mask, 8, 0),
                                    canvas.composite_hdr_outpaint(generated, source, mask, 8)))
        for value, expected in [(0, source), (1, generated)]:
            actual = canvas.composite_hdr_outpaint(generated, source, torch.full_like(mask, value), 8, 1)
            self.assertTrue(torch.equal(actual, expected))

    def test_temporal_filter_reduces_a_one_frame_colour_excursion(self):
        generated, source, mask = self.fixture(3)
        generated[1] += .04
        corrected = canvas.match_hdr_outpaint_colour(generated, source, mask, 8, 1)
        changes = corrected[:, 48, 128, 0] - generated[:, 48, 128, 0]
        self.assertLess(abs(float(changes[1] - changes[0])), .04)
        self.assertTrue(torch.equal(corrected[:, :8], generated[:, :8]))

    def test_invalid_strength_is_rejected(self):
        for value in (-1, 1.1, True, float('nan')):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Colour matching'):
                canvas.composite_hdr_outpaint(*self.fixture(), 8, value)

    def test_temporal_filter_cannot_invent_a_reference_in_another_frame(self):
        generated, source, mask = self.fixture(3)
        mask[1] = 1
        corrected = canvas.match_hdr_outpaint_colour(generated, source, mask, 8, 1)
        self.assertTrue(torch.equal(corrected[1], generated[1]))


if __name__ == '__main__':
    unittest.main()
