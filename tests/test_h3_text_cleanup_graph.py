"""Native H3 background text cleanup graph contracts; no inference or GPU use."""
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import v2_bootstrap

NAME = "ComfyUI_zura_nodes.artist_studio"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[NAME] = package
package = sys.modules[NAME]
studio = importlib.import_module(NAME + ".studio")
h3 = importlib.import_module(NAME + ".h3")


class H3TextCleanupGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / "missing-conditioning.pt"

    def project(self, *, remove_text=True, preserve=True, regions=True, genuine_mask=True, pitch=True):
        config = studio.clean_config({"engine": "h3", "quality": "fast", "duration": 2,
                                      "resolution": 1280, "remove_text": remove_text, "pitch": pitch})
        project = {"id": "a" * 32, "source": {"file": "source.mp4", "sha": "source"},
                   "character": {"file": "character.png", "sha": "character"}, "config": config,
                   "review": "shot_" + "a" * 16, "opening_key": "look", "opening_approval": "look",
                   "opening_input": {"file": "opening.png", "sha": "look"}}
        clip = {"frames": 48}
        if regions:
            clip.update(text_regions=[{"x": 30, "y": 8, "width": 190, "height": 54}],
                        text_regions_size=[720, 1280])
        files = {"source.mp4": "0" * 64, "mask.mp4": "1" * 64}
        if genuine_mask:
            files["performer_mask.mp4"] = "2" * 64
        manifest = {"clip": clip, "files": files}
        return project, manifest, preserve

    def build(self, project, manifest, preserve=True):
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                patch.object(package, "verify_review", return_value=(None, manifest), create=True), \
                patch.object(h3, "text_cleanup_readiness", return_value={"ready": True, "missing_nodes": []}), \
                patch.object(h3, "cache_path", return_value=self.cache), \
                patch.object(h3, "cache_key", return_value="b" * 64):
            return h3.build_h3_graph(project, use_cache=False, preserve_background=preserve)

    def test_cleanup_is_gated_by_preservation_text_option_regions_and_verified_genuine_mask(self):
        cases = (
            self.project(genuine_mask=False),
            self.project(preserve=False),
            self.project(remove_text=False),
            self.project(regions=False),
        )
        for project, manifest, preserve in cases:
            with self.subTest(preserve=preserve, remove_text=project["config"]["remove_text"],
                              regions=bool(manifest["clip"].get("text_regions")),
                              genuine="performer_mask.mp4" in manifest["files"]):
                graph = self.build(project, manifest, preserve)
                self.assertNotIn("h3_text_background_mask", graph)
                self.assertNotIn("h3_lama_model", graph)
                self.assertNotIn("h3_text_repair_switch", graph)

    def test_eligible_graph_cleans_native_source_and_masks_before_depth_and_encoding(self):
        project, manifest, preserve = self.project()
        graph = self.build(project, manifest, preserve)

        self.assertEqual(graph["h3_genuine_mask_pad"]["class_type"], "GenjH3FramePad")
        self.assertEqual(graph["h3_genuine_mask_pad"]["inputs"], {
            "source": ["h3_shot", 0], "mask_video": ["h3_shot", 4],
            "guidance_audio": ["h3_guidance", 1]})
        adapter = graph["h3_text_background_mask"]
        self.assertEqual(adapter["class_type"], "ZuraTextBackgroundRepairMask")
        self.assertEqual(adapter["inputs"], {"combined_mask": ["h3_pad", 1],
                                              "performer_mask": ["h3_genuine_mask_pad", 1],
                                              "clip_details": ["h3_shot", 3], "context": 32})
        self.assertEqual(graph["h3_text_background_crop"]["class_type"], "ImageCrop")
        self.assertEqual(graph["h3_text_background_crop"]["inputs"], {
            "image": ["h3_pad", 0], "width": ["h3_text_background_mask", 2],
            "height": ["h3_text_background_mask", 3], "x": ["h3_text_background_mask", 4],
            "y": ["h3_text_background_mask", 5]})
        self.assertEqual(graph["h3_lama_model"], {"class_type": "LoadLaMaModel",
                                                  "inputs": {"model_name": "big-lama.pt"}})
        self.assertEqual(graph["h3_lama_inpaint"]["class_type"], "LaMaInpaint")
        self.assertEqual(graph["h3_lama_inpaint"]["inputs"], {
            "image": ["h3_text_background_crop", 0], "mask": ["h3_text_background_mask", 0],
            "device_mode": "AUTO", "lama_model": ["h3_lama_model", 0]})
        self.assertEqual(graph["h3_text_background_composite"]["class_type"], "ImageCompositeMasked")
        self.assertEqual(graph["h3_text_background_composite"]["inputs"], {
            "destination": ["h3_pad", 0], "source": ["h3_lama_inpaint", 0],
            "x": ["h3_text_background_mask", 4], "y": ["h3_text_background_mask", 5],
            "resize_source": False, "mask": ["h3_text_background_mask", 0]})
        self.assertEqual(graph["h3_text_repair_switch"]["class_type"], "LazySwitchKJ")
        self.assertEqual(graph["h3_text_repair_switch"]["inputs"], {
            "switch": ["h3_text_background_mask", 6], "on_false": ["h3_pad", 0],
            "on_true": ["h3_text_background_composite", 0]})

        source = ["h3_text_repair_switch", 0]
        mask = ["h3_text_background_mask", 1]
        self.assertEqual(graph["h3_depth"]["inputs"]["image"], source)
        self.assertEqual(graph["h3_inpaint"]["inputs"]["source_video"], source)
        self.assertEqual(graph["h3_inpaint"]["inputs"]["mask"], mask)
        self.assertEqual(graph["h3_source_latent"]["inputs"]["pixels"], source)
        self.assertEqual(graph["h3_preserve_background"]["inputs"]["mask"], mask)
        self.assertEqual(graph["h3_clean_depth"]["inputs"]["depth"], ["h3_depth_size", 0])
        self.assertEqual(graph["h3_clean_depth"]["inputs"]["clip_details"], ["h3_shot", 3])

    def test_optional_audio_pad_and_speech_cache_reference_paths_stay_intact(self):
        project, manifest, preserve = self.project(pitch=True)
        graph = self.build(project, manifest, preserve)
        self.assertEqual(graph["h3_pad"]["inputs"]["guidance_audio"], ["h3_guidance", 1])
        self.assertEqual(graph["h3_genuine_mask_pad"]["inputs"]["guidance_audio"], ["h3_guidance", 1])
        self.assertEqual(graph["h3_references"]["inputs"]["ref_audios.ref_audio_0"], ["h3_pad", 2])
        self.assertEqual(graph["h3_speech"]["inputs"]["audio"], ["h3_pad", 2])
        self.assertEqual(graph["h3_locked_audio"]["inputs"]["audio"], ["h3_pad", 2])
        self.assertEqual(graph["h3_sample"]["inputs"]["latent_image"], ["h3_locked_audio", 0])

        references = h3.reference_graph(graph, "c" * 64)
        self.assertIn("h3_save_references", references)
        self.assertIn("h3_references", references)
        self.assertIn("h3_speech", references)
        self.assertEqual(references["h3_save_references"]["inputs"]["positive"], ["h3_speech", 0])
        self.assertNotIn("h3_lama_model", references,
                         "Conditioning-cache construction should not require background cleanup inference.")

    def test_without_pitch_the_second_pad_uses_the_same_reviewed_video_and_genuine_mask(self):
        project, manifest, preserve = self.project(pitch=False)
        graph = self.build(project, manifest, preserve)
        self.assertNotIn("h3_guidance", graph)
        self.assertEqual(graph["h3_genuine_mask_pad"]["inputs"], {
            "source": ["h3_shot", 0], "mask_video": ["h3_shot", 4]})

    def test_missing_native_cleanup_pack_has_an_actionable_error_before_queueing(self):
        project, manifest, preserve = self.project()
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                patch.object(package, "verify_review", return_value=(None, manifest), create=True), \
                patch.object(h3, "text_cleanup_readiness", return_value={
                    "ready": False, "missing_nodes": ["LaMaInpaint"]}):
            with self.assertRaisesRegex(ValueError, "ComfyUI-ArtVenture.*ComfyUI-KJNodes.*LaMaInpaint"):
                h3.build_h3_graph(project, use_cache=False, preserve_background=preserve)

    def test_cleanup_readiness_checks_only_its_native_optional_dependencies(self):
        native = types.ModuleType("nodes")
        native.NODE_CLASS_MAPPINGS = {name: object() for name in h3.H3_TEXT_CLEANUP_NODES}
        with patch.dict(sys.modules, {"nodes": native}):
            self.assertTrue(h3.text_cleanup_readiness()["ready"])
            del native.NODE_CLASS_MAPPINGS["LoadLaMaModel"]
            self.assertEqual(h3.text_cleanup_readiness(), {
                "ready": False, "missing_nodes": ["LoadLaMaModel"]})


if __name__ == "__main__":
    unittest.main()
