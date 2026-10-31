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
            "long_edge": 832, "use_original_length": False, "round_up": True})
        self.assertEqual(graph["driving_video_frames"]["inputs"]["video"], ["pad_source", 0])
        self.assertEqual(graph["animate2_conditioning"]["inputs"]["length"], 49)
        self.assertEqual(graph["trim_output"]["inputs"]["num_frames"], 48)
        self.assertEqual(graph["hold_output"]["inputs"]["images"], ["trim_output", 0])
        self.assertEqual(graph["animate2_video"]["inputs"]["images"], ["hold_output", 0])
        self.assertEqual(graph["wan2_export"]["inputs"]["target_frames"], ["hold_output", 1])
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

    def test_mask_route_uses_reviewed_interval_once_and_sampler_only(self):
        project = self.project(workflow_mode="swap", edit_area="mask", scope="person", mask_method="auto")
        project.update(review="reviewed-shot", approval="current-preparation-hash")
        graph = self.build(project)
        self.assertEqual(graph["reviewed"]["inputs"]["approved_shot_id"], "reviewed-shot")
        self.assertTrue(graph["reviewed"]["inputs"]["preserve_aspect"])
        self.assertEqual(graph["reviewed_frames"]["inputs"], {
            "source": ["reviewed", 0], "mask_video": ["reviewed", 1]})
        self.assertNotIn("select", graph, "The reviewed interval must not be trimmed a second time")
        self.assertEqual(graph["hold_source"]["inputs"]["stride"], 4)
        self.assertEqual(graph["pose_frames"]["inputs"]["image"], ["hold_source", 0])
        mask = graph["spatial_mask"]["inputs"]
        self.assertEqual(mask["source_video"], ["reviewed_frames", 0])
        self.assertEqual(mask["edit_mask"], ["reviewed_frames", 1])
        self.assertEqual(mask["video_frame_offset"], 0)
        self.assertEqual(mask["length"], 49)
        self.assertEqual((mask["grow_pixels"], mask["block_size"], mask["temporal_radius"]), (32, 32, 1))
        self.assertTrue(mask["fill_holes"])
        self.assertTrue(mask["lock_background"])
        self.assertFalse(mask["condition_background"])
        sample = graph["animate2_sample"]["inputs"]
        for field, output in (("positive", 0), ("negative", 1), ("latent_image", 2)):
            self.assertEqual(sample[field], ["spatial_mask", output])
        self.assertEqual(graph["wan2_export"]["inputs"]["clip_details"], ["reviewed", 3])
        output = graph["wan2_export"]["inputs"]
        native = graph["animate2_conditioning"]["inputs"]
        self.assertEqual((output["output_width"], output["output_height"]), (native["width"], native["height"]),
                         "Reviewed-source metadata must not stretch the native output")
        for node in graph.values():
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    self.assertIn(value[0], graph, "No dangling links after switching to reviewed footage")

    def test_mask_requires_review_and_full_character_scope(self):
        project = self.project(workflow_mode="swap", edit_area="mask")
        with self.assertRaisesRegex(ValueError, "approve"):
            self.build(project)
        project.update(review="reviewed-shot", approval="approved")
        for change in ({"scope": "head"}, {"mask_method": "points"}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "full-character"):
                self.build({**project, "config": {**project["config"], **change}})

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
        self.assertFalse(report["masked_ready"], "Full-frame installs remain usable without mask nodes")
        masked = animate2.readiness(dict.fromkeys(required | set(report["missing_mask_nodes"])),
                                   lambda folder, filename: "/models/" + filename)
        self.assertTrue(masked["masked_ready"])
        self.assertFalse(report["quality_verified_locally"])
        self.assertEqual(report["limits"]["max_frames"], 81)
        self.assertTrue(all(item["url"].startswith("https://huggingface.co/Comfy-Org/Wan-Animate-2/") for item in report["model_files"]))
        report = animate2.readiness({}, lambda folder, filename: None)
        self.assertFalse(report["ready"])
        self.assertIn("WanAnimate2Cache", report["missing_nodes"])
        self.assertFalse(any(item["ready"] for item in report["model_files"]))


if __name__ == "__main__":
    unittest.main()
