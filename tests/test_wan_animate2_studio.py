"""CPU contracts for the setup-gated full-frame Animate 2 Studio adapter."""
import types
import unittest
from unittest.mock import MagicMock, patch

from test_wan_animate2 import animate2


class WanAnimate2StudioTests(unittest.TestCase):
    def project(self, **config):
        return {"id": "a" * 32, "source": {"file": "source.mp4"},
                "opening_input": {"file": "finished.png"}, "opening_key": "look",
                "opening_approval": "look", "config": {
                    "engine": "wan2", "workflow_mode": "motion", "edit_area": "scene",
                    "subject_mode": "people", "length_mode": "custom", "start": .5,
                    "duration": 2., "seed": 42, "prompt": "An adult dancer in a new city.", **config}}

    def video(self, duration=4., width=1920, height=1080):
        stream = types.SimpleNamespace(duration=duration, time_base=1, width=width, height=height)
        context = MagicMock()
        context.__enter__.return_value = types.SimpleNamespace(streams=types.SimpleNamespace(video=[stream]))
        return context

    def build(self, project=None, **video):
        import av
        with patch.object(av, "open", return_value=self.video(**video)):
            return animate2.build_studio_graph(project or self.project(), lambda asset: asset["file"])

    def test_exact_selected_interval_padding_and_final_trim(self):
        graph = self.build()
        self.assertEqual(graph["select"]["inputs"], {
            "video": ["driving_video", 0], "start_seconds": .5, "duration_seconds": 2.,
            "long_edge": 832, "use_original_length": False})
        self.assertEqual(graph["driving_video_frames"]["inputs"]["video"], ["pad_source", 0])
        self.assertEqual(graph["animate2_conditioning"]["inputs"]["length"], 49)
        self.assertEqual(graph["trim_output"]["inputs"]["num_frames"], 48)
        self.assertEqual(graph["animate2_video"]["inputs"]["images"], ["trim_output", 0])
        self.assertEqual(graph["wan2_export"]["inputs"]["clip_details"], ["select", 1])
        self.assertNotIn("animate2_save", graph)
        self.assertEqual(graph["reference_image"]["inputs"]["image"], "finished.png")

    def test_original_length_and_portrait_aspect_respect_bounds(self):
        graph = self.build(self.project(length_mode="original"), duration=3., width=1080, height=1920)
        self.assertEqual(graph["select"]["inputs"]["start_seconds"], 0.)
        self.assertEqual(graph["trim_output"]["inputs"]["num_frames"], 72)
        values = graph["animate2_conditioning"]["inputs"]
        self.assertLess(values["width"], values["height"])
        self.assertLessEqual(values["width"] * values["height"], animate2.MAX_OUTPUT_PIXELS)
        self.assertEqual(values["length"], 73)

    def test_custom_range_cannot_silently_shorten_at_source_end(self):
        with self.assertRaisesRegex(ValueError, 'shorter range'):
            self.build(self.project(start=.5,duration=3.25),duration=3.74)
        graph=self.build(self.project(start=.5,duration=3.25),duration=4.)
        self.assertEqual(graph['trim_output']['inputs']['num_frames'],78)
        self.assertEqual(graph['animate2_conditioning']['inputs']['length'],81)

    def test_unapproved_look_unsupported_features_and_too_long_rejected(self):
        project = self.project()
        project["opening_approval"] = None
        with self.assertRaisesRegex(ValueError, "approve"):
            self.build(project)
        for config in ({"edit_area": "mask"}, {"workflow_mode": "viewport"},
                       {"audio_id": "replacement"}, {"remove_text": True},
                       {"subject_mode": "objects"}, {"duration": 3.5}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.build(self.project(**config))

    def test_readiness_reports_specific_official_assets_and_unqualified_output(self):
        required = (set(animate2.NATIVE_NODE_INPUTS) - {"SaveVideo"}) | animate2.STUDIO_NODES
        report = animate2.readiness(dict.fromkeys(required), lambda folder, filename: "/models/" + filename)
        self.assertTrue(report["ready"])
        self.assertFalse(report["quality_verified_locally"])
        self.assertEqual(report["limits"]["max_frames"], 81)
        self.assertTrue(all(item["url"].startswith("https://huggingface.co/Comfy-Org/Wan-Animate-2/") for item in report["model_files"]))
        report = animate2.readiness({}, lambda folder, filename: None)
        self.assertFalse(report["ready"])
        self.assertIn("WanAnimate2Cache", report["missing_nodes"])
        self.assertFalse(any(item["ready"] for item in report["model_files"]))


if __name__ == "__main__":
    unittest.main()
