import importlib.util
import json
from pathlib import Path
import unittest

import torch


SPEC = importlib.util.spec_from_file_location("image_guidance", Path(__file__).resolve().parents[1] / "image_guidance.py")
guidance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guidance)


def stroke(tool, x, y, width=9):
    return {"tool": tool, "width": width, "points": [[x, y]], "colour": "#ff7245"}


class PainterTests(unittest.TestCase):
    def test_rgb_overlay_and_inverse_alpha_agree_with_edit_mask(self):
        state = {"version": 1, "width": 80, "height": 64,
                 "mask": [stroke("brush", .25, .5), stroke("brush", .75, .5), stroke("erase", .75, .5)],
                 "markup": [stroke("brush", .25, .5), stroke("brush", .75, .5)],
                 "alpha": [stroke("brush", .25, .5), stroke("brush", .75, .5), stroke("erase", .75, .5)]}
        frames = torch.rand((2, 64, 80, 3))
        reference, mask, markup, alpha = guidance.ZuraImageGuidance().draw(frames, json.dumps(state))
        self.assertTrue(torch.equal(reference, frames[:1]))
        self.assertEqual(tuple(markup.shape), (1, 64, 80, 4))
        self.assertEqual(mask[0, 32, 20].item(), 1)
        self.assertEqual(mask[0, 32, 59].item(), 0)
        self.assertEqual(markup[0, 32, 20, 3].item(), 0)
        self.assertEqual(markup[0, 32, 59, 3].item(), 1)
        self.assertEqual(markup[0, 32, 59, 0].item(), 1)
        self.assertTrue(torch.equal(1 - markup[..., 3], alpha))

    def test_refuses_stale_dimensions_and_invalid_points(self):
        state = {"version": 1, "width": 80, "height": 64, "mask": [stroke("brush", 9, .5)]}
        with self.assertRaisesRegex(ValueError, "dimensions have changed"):
            guidance._render(json.dumps(state), 72, 64)
        with self.assertRaisesRegex(ValueError, "outside the frame"):
            guidance._render(json.dumps(state), 80, 64)


if __name__ == "__main__":
    unittest.main()
