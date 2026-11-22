"""The Studio route conditions one native H3 generation and exports its decode."""

from fractions import Fraction
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

package = types.ModuleType("zura_switch_tests")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "artist_studio")]
sys.modules[package.__name__] = package
routes = importlib.import_module(package.__name__ + ".switch_x_routes")


class OneGeneration(unittest.TestCase):
    def graph(self, count=359, **options):
        cfg = dict(
            source="shot.mov", matte="keep.mov", refs=["car.png"], prompt="Match <Picture 1>."
        )
        cfg.update(options)
        with (
            patch.object(routes, "input_path", side_effect=Path),
            patch.object(
                routes, "source_info", return_value=(1280, 720, count, Fraction(24000, 1001))
            ),
        ):
            return routes.build(cfg)

    def test_whole_shot_enters_one_native_reference_condition_and_sampler(self):
        for count in (5, 124, 359, 479):
            with self.subTest(count=count):
                g = self.graph(count)
                types = [n["class_type"] for n in g.values()]
                self.assertEqual(types.count("MiniMaxH3ReferenceToVideo"), 1)
                self.assertEqual(types.count("SamplerCustomAdvanced"), 1)
                self.assertEqual(types.count("VAEDecode"), 1)
                self.assertEqual(g["scene"]["inputs"]["ref_videos.ref_video_0"], ["plates", 2])
                self.assertEqual(g["source_latent"]["inputs"]["pixels"], ["plates", 0])
                self.assertEqual(g["structure"]["inputs"]["replace"], ["plates", 1])
                self.assertEqual(g["finish"]["inputs"]["images"], ["decode", 0])
                self.assertEqual(g["finish"]["class_type"], "ZuraSwitchXDeliver")
                self.assertNotIn("matte", g["finish"]["inputs"])
                length = g["scene"]["inputs"]["length"]
                self.assertTrue(count <= length < count + 17 and (length - 5) % 17 == 0)

    def test_timed_requests_and_pinned_stills_share_the_same_generation(self):
        g = self.graph(
            prompt="0:00 Train dark\n0:02 Switch lights on",
            refs=["car.png", "light.png"],
            pinnedFrames={"light.png": 48},
        )
        self.assertEqual(g["guide"]["inputs"]["conditioning"], ["look_1_pin", 0])
        self.assertEqual(g["look_1_pin"]["inputs"]["frame_idx"], 48)
        self.assertIn("0:02 Switch lights on", g["scene"]["inputs"]["prompt"])
        self.assertEqual(sum(n["class_type"] == "SamplerCustomAdvanced" for n in g.values()), 1)

    def test_source_relative_resolution_keeps_all_masked_inputs_aligned(self):
        for scale in (1, .75, .5, .25):
            g = self.graph(scale=scale, pinnedFrames={"car.png": 0})
            side, width, height = routes.processing_size(1280, 720, {"scale": scale})
            self.assertEqual(side, round(1280 * scale))
            self.assertEqual((width, height), (side, ((round(720 * scale) + 31) // 32) * 32))
            self.assertEqual((g["scene"]["inputs"]["width"], g["scene"]["inputs"]["height"]), (width, height))
            for key in ("plates", "look_0", "finish"):
                self.assertEqual(g[key]["inputs"]["side"], side)
        self.assertEqual(routes.processing_size(1080, 1920, {"scale": .5}), (960, 544, 960))
        self.assertEqual(routes.processing_size(1080, 1920, {"side": 1024}), (1024, 576, 1024))
        with self.assertRaisesRegex(ValueError, "lower processing resolution"):
            routes.processing_size(4096, 4096, {"scale": 1})

    def test_stale_two_pass_settings_cannot_reactivate_another_generation(self):
        g = self.graph(independentEnvironment=True, environmentRefs=["car.png"], cleanFringe=True)
        self.assertFalse(any("environment" in key or "fringe" in key for key in g))
        self.assertEqual(g["structure"]["inputs"]["model"], ["shift", 0])
        self.assertEqual(g["sample"]["inputs"]["guider"], ["guide", 0])
        self.assertEqual(g["guide"]["inputs"]["model"], ["structure", 0])

    def test_reject_mismatched_mask(self):
        with (
            patch.object(routes, "input_path", side_effect=Path),
            patch.object(
                routes,
                "source_info",
                side_effect=[(1280, 720, 96, Fraction(24)), (1280, 720, 90, Fraction(24))],
            ),
        ):
            with self.assertRaisesRegex(ValueError, "frame count"):
                routes.build(dict(source="s.mov", matte="m.mov"))

    def test_character_replacement_lock_and_margin_follow_matte_polarity(self):
        keep=self.graph(whiteMeans="keep",replacementMargin=18)
        self.assertEqual(keep["protected_latent"]["class_type"],"ZuraSwitchXProtectedLatent")
        self.assertTrue(keep["protected_latent"]["inputs"]["allow_relight"])
        self.assertNotIn("edit_margin",keep)
        self.assertNotIn("neutralize_replacement",keep["plates"]["inputs"])
        for margin in (0,8):
            edit=self.graph(whiteMeans="replace",replacementMargin=margin)
            self.assertTrue(edit["plates"]["inputs"]["neutralize_replacement"])
            mask=["edit_margin",0] if margin else ["plates",1]
            self.assertFalse(edit["protected_latent"]["inputs"]["allow_relight"])
            for node,key in [("edit_region","mask"),("structure","replace"),("protected_latent","replace")]:
                self.assertEqual(edit[node]["inputs"][key],mask)
            self.assertEqual(edit["sample"]["inputs"]["latent_image"],["protected_latent",0])
        with self.assertRaises(ValueError):
            self.graph(whiteMeans="replace",replacementMargin=-1)

    def test_selection_accepts_luminance_or_embedded_alpha(self):
        import av
        import numpy as np
        media=importlib.import_module(package.__name__+".switch_x_media")
        selection=importlib.import_module(package.__name__+".character_mask")
        rgba=np.zeros((8,8,4),np.uint8);rgba[:,:,:3]=255;rgba[:,:4,3]=255
        frame=av.VideoFrame.from_ndarray(rgba,format="rgba")
        alpha=media.alpha_image(frame,"alpha")
        self.assertTrue(np.all(alpha[:,:4]>.99) and np.all(alpha[:,4:]==0))
        self.assertTrue(np.all(media.alpha_image(frame,"luma")>.99))
        np.testing.assert_array_equal(selection.editable_mask(alpha,"keep"),1-alpha)
        np.testing.assert_array_equal(selection.editable_mask(alpha,"replace"),alpha)
        with self.assertRaisesRegex(ValueError,"embedded alpha"):
            media.alpha_image(av.VideoFrame.from_ndarray(rgba[:,:,:3].copy(),format="rgb24"),"alpha")

    def test_replacement_guidance_removes_selected_chroma_only(self):
        import numpy as np
        media = importlib.import_module(package.__name__ + ".switch_x_media")
        image = np.full((1, 3, 3), [.08, .62, .48], dtype=np.float32)
        weights = np.array([[0, .5, 1]], dtype=np.float32)
        guide = media.neutral_replacement_guide(image, weights)
        np.testing.assert_array_equal(guide[0, 0], image[0, 0])
        np.testing.assert_allclose(guide[0, 2], [guide[0, 2, 0]] * 3, atol=1e-6)
        np.testing.assert_allclose(guide[0, 1], (image[0, 1] + guide[0, 2]) / 2, atol=1e-6)
        luma = np.array([.2126, .7152, .0722], dtype=np.float32)
        np.testing.assert_allclose(guide @ luma, image @ luma, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
