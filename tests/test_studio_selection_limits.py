"""Unsupported model timelines fail before expensive preparation is submitted."""
import asyncio
import copy
import importlib
import sys
import types
import unittest
from fractions import Fraction
from unittest.mock import Mock, patch

import v2_bootstrap

NAME = "ComfyUI_zura_nodes.artist_studio"
package = sys.modules.setdefault(NAME, types.ModuleType(NAME))
package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
studio = importlib.import_module(NAME + ".studio")


class SelectionLimitsTests(unittest.TestCase):
    def project(self, engine="h3", **changes):
        config = studio.clean_config({"engine": engine, "duration": 5, **changes})
        return {"source": {"file": "private.mp4", "sha": "source"}, "config": config,
                "audio": {"id": "b" * 32} if config["audio_id"] else None, "actions": []}

    def container(self, frames, stream_duration=True):
        stream = types.SimpleNamespace(duration=frames if stream_duration else None, time_base=Fraction(1, 24))
        container = types.SimpleNamespace(streams=types.SimpleNamespace(video=[stream], audio=[]),
                                         duration=round(frames / 24 * studio.av.time_base))
        cm = Mock()
        cm.__enter__ = Mock(return_value=container)
        cm.__exit__ = Mock(return_value=False)
        return cm

    def validate(self, project, frames, stream_duration=True):
        with patch.object(studio, "check_asset", return_value="private.mp4"), \
                patch.object(studio.av, "open", return_value=self.container(frames, stream_duration)):
            studio.validate_selection(project)

    def test_h3_source_end_and_original_length_use_real_24fps_frame_count(self):
        self.validate(self.project(duration=30), 120)
        self.validate(self.project(length_mode="original", duration=2), 120)
        with self.assertRaisesRegex(ValueError, "0.21 to 5 seconds"):
            self.validate(self.project(length_mode="original", duration=2), 121)
        self.validate(self.project(start=5, duration=30), 240)

    def test_h3_too_short_and_out_of_range_start_fail(self):
        with self.assertRaisesRegex(ValueError, "0.21 to 5 seconds"):
            self.validate(self.project(duration=.1), 120)
        with self.assertRaisesRegex(ValueError, "beyond the end"):
            self.validate(self.project(start=5), 120)
        self.validate(self.project(duration=5), 120, stream_duration=False)

    def test_replacement_speech_length_does_not_limit_original_or_soundtrack_wan(self):
        with patch.object(studio.av, "open") as opened:
            studio.validate_selection(self.project("wan", length_mode="original"))
            studio.validate_selection(self.project("wan", length_mode="original", audio_id="b" * 32, lip_sync=False))
            self.assertFalse(opened.called)
        speech = self.project("wan", length_mode="original", audio_id="b" * 32, lip_sync=True)
        self.validate(speech, 720)
        with self.assertRaisesRegex(ValueError, "up to 30 seconds"):
            self.validate(speech, 721)

    def test_bad_duration_never_queues_or_mutates_saved_project(self):
        controller = studio.Studio.__new__(studio.Studio)
        controller.collect = lambda project: project
        controller.store = Mock()
        project = self.project(length_mode="original")
        project.update(opening_input={"file": "approved.png"}, opening_key="look", opening_approval=None)
        before = copy.deepcopy(project)
        with patch.object(studio, "check_asset", return_value="private.mp4"), \
                patch.object(studio.av, "open", return_value=self.container(240)), \
                patch.object(studio, "build_graph") as build:
            for stage in ("prepare", "animate"):
                with self.subTest(stage=stage), self.assertRaisesRegex(ValueError, "0.21 to 5 seconds"):
                    asyncio.run(controller.action(project, stage, {"request_key": "a" * 36}))
                self.assertEqual(project, before)
            self.assertFalse(build.called)
            self.assertFalse(controller.store.save.called)
        self.assertEqual(project, before)

    def test_ltx_whole_scene_length_checked_before_preparation(self):
        self.validate(self.project("local", edit_area="scene", length_mode="original"), 120)
        with self.assertRaisesRegex(ValueError, "up to 5 seconds"):
            self.validate(self.project("local", edit_area="scene", length_mode="original"), 121)
        self.validate(self.project("local", edit_area="scene", start=5, duration=5), 240)
        with patch.object(studio.av, "open") as opened:
            studio.validate_selection(self.project("local", edit_area="mask", length_mode="original"))
            opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
