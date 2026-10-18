"""H3 finished-frame anchors use delivered output frames; graph-only, no GPU."""
import importlib
import sys
import types
import unittest
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


class H3FinishedFrameAnchorTests(unittest.TestCase):
    def base_project(self, *, position="first", number=1, ready=True):
        config = studio.clean_config({
            "engine": "h3", "duration": 2, "resolution": 1280,
            "finished_frame_position": position, "finished_frame_number": number,
        })
        project = {
            "id": "a" * 32,
            "look_mode": "ready" if ready else "build",
            "starting_asset": {"file": "finished.png", "sha": "finished"} if ready else None,
            "opening_input": {"file": "opening.png", "sha": "finished"},
            "opening_key": "finished", "opening_approval": "finished",
            "character": {"file": "character.png", "sha": "character"},
            "source": {"file": "source.mp4", "sha": "source"},
            "review": "shot_" + "b" * 16,
            "config": config,
        }
        if not ready:
            project.pop("starting_asset")
        return project

    @staticmethod
    def manifest(frames=48):
        return {"clip": {"frames": frames}, "files": {"source.mp4": "0" * 64,
                                                         "mask.mp4": "1" * 64}}

    def build_normal(self, project, *, frames=48):
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                patch.object(package, "verify_review", return_value=(None, self.manifest(frames)), create=True), \
                patch.object(h3, "cache_key", return_value="c" * 64), \
                patch.object(h3, "cache_valid", return_value=False):
            return h3.build_h3_graph(project, use_cache=False)

    @staticmethod
    def media_container(seconds):
        class Container:
            streams = types.SimpleNamespace(video=[types.SimpleNamespace(duration=seconds, time_base=1)])
            duration = seconds * 1_000_000

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        return Container()

    def viewport_project(self, *, position="first", number=1, ready=True):
        config = studio.clean_config({
            "workflow_mode": "viewport", "engine": "h3", "duration": 2,
            "resolution": 1280, "finished_frame_position": position,
            "finished_frame_number": number,
        })
        references = [{"file": f"look-{i}.png", "sha": f"look-{i}", "role": "environment"}
                      for i in range(1, 6)]
        project = {
            "id": "d" * 32, "viewport_render": True,
            "source": {"file": "blockout.mp4", "sha": "blockout"},
            "references": references, "viewport_references": references,
            "config": config,
        }
        if ready:
            project["look_mode"] = "ready"
            project["starting_asset"] = {"file": "finished.png", "sha": "finished"}
            project = studio._viewport_project(project)
        return project

    def build_viewport(self, project):
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                patch("av.open", return_value=self.media_container(15)):
            return h3.build_h3_graph(project, use_cache=False)

    def test_resolves_one_based_custom_and_first_last_within_delivered_frames(self):
        project = self.base_project(position="first")
        self.assertEqual(h3._finished_frame_index(project, 48), 0)
        project["config"]["finished_frame_position"] = "last"
        self.assertEqual(h3._finished_frame_index(project, 48), 47)
        project["config"].update(finished_frame_position="frame", finished_frame_number=25)
        self.assertEqual(h3._finished_frame_index(project, 48), 24)

    def test_frame_number_is_rejected_when_it_only_fits_the_padded_latent(self):
        project = self.base_project(position="frame", number=49)
        # A 48-frame delivery is padded to 56 frames internally. The UI still
        # accepts only real delivered frames, never the latent padding.
        with self.assertRaisesRegex(ValueError, "from 1 to 48"):
            h3._finished_frame_index(project, 48)

    def test_timed_anchor_is_enabled_only_for_uploaded_finished_look(self):
        project = self.base_project(position="last", ready=False)
        self.assertIsNone(h3._finished_frame_index(project, 48))
        graph = self.build_normal(project)
        self.assertEqual(graph["h3_first_frame"]["inputs"]["frame_idx"], 0)
        self.assertNotIn("h3_finished_frame", graph)

    def test_normal_h3_graph_anchors_custom_frame_and_keeps_audio_at_zero(self):
        project = self.base_project(position="frame", number=25)
        graph = self.build_normal(project)
        anchor = graph["h3_finished_frame"]
        self.assertEqual(anchor["class_type"], "MiniMaxH3AddGuide")
        self.assertEqual(anchor["inputs"]["frame_idx"], 24)
        self.assertEqual(anchor["inputs"]["image"], ["h3_opening_size", 0])
        self.assertEqual(graph["h3_speech"]["inputs"]["positive"], ["h3_finished_frame", 0])
        self.assertEqual(graph["h3_speech"]["inputs"]["frame_idx"], 0)
        self.assertIn("output frame 25 of 48", graph["h3_prompt"]["inputs"]["value"])

    def test_normal_h3_last_frame_uses_last_delivered_not_padded_latent_frame(self):
        project = self.base_project(position="last")
        graph = self.build_normal(project, frames=48)
        self.assertEqual(graph["h3_finished_frame"]["inputs"]["frame_idx"], 47)

    def test_viewport_h3_last_frame_anchors_starting_asset_at_last_delivered_frame(self):
        project = self.viewport_project(position="last")
        graph = self.build_viewport(project)
        anchor = graph["h3_finished_frame"]
        self.assertEqual(anchor["class_type"], "MiniMaxH3AddGuide")
        self.assertEqual(anchor["inputs"]["frame_idx"], 47)
        self.assertEqual(anchor["inputs"]["image"], ["h3_viewport_image_1", 0])
        self.assertEqual(graph["h3_guider"]["inputs"]["conditioning"], ["h3_finished_frame", 0])
        self.assertIn("output frame 48 of 48", graph["h3_references"]["inputs"]["prompt"])

    def test_viewport_h3_specific_frame_uses_one_based_output_frame(self):
        project = self.viewport_project(position="frame", number=17)
        graph = self.build_viewport(project)
        self.assertEqual(graph["h3_finished_frame"]["inputs"]["frame_idx"], 16)

    def test_viewport_h3_without_finished_look_keeps_reference_only_route(self):
        project = self.viewport_project(position="last", ready=False)
        graph = self.build_viewport(project)
        self.assertNotIn("h3_finished_frame", graph)
        self.assertEqual(graph["h3_guider"]["inputs"]["conditioning"], ["h3_references", 0])

    def test_ready_frame_cache_key_separates_nonfirst_placements(self):
        project = self.base_project(position="first")
        with patch("folder_paths.get_full_path", return_value=__file__), \
                patch.object(h3.Path, "stat", autospec=True) as stat:
            stat.return_value.st_size = 1
            stat.return_value.st_mtime_ns = 1
            first = h3.cache_key(project)
            project["config"].update(finished_frame_position="last")
            last = h3.cache_key(project)
            project["config"].update(finished_frame_position="frame", finished_frame_number=25)
            custom = h3.cache_key(project)
        self.assertNotEqual(first, last)
        self.assertNotEqual(last, custom)


if __name__ == "__main__":
    unittest.main()
