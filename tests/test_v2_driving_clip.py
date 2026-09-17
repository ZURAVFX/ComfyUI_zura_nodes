"""Standalone tests for Zura Load Video (decode + VIDEO assembly)."""
from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import v2_bootstrap  # noqa: F401
from ComfyUI_zura_nodes import driving_clip, media_source, video as video_module

import torch


class DrivingClipTests(unittest.TestCase):
    def make_frames(self, count=48, height=16, width=16):
        return torch.zeros((count, height, width, 3))

    def make_audio(self, seconds=2, rate=32000):
        return {"sample_rate": rate, "waveform": torch.zeros((1, 2, round(seconds * rate)))}

    def test_load_returns_a_plain_video_wire_and_exact_frames(self):
        frames, audio = self.make_frames(), self.make_audio(2)
        info = {"fps": 24, "delivery_frames": 48}
        with patch.object(media_source, "local_path", return_value="ref.mp4") as local, \
                patch.object(media_source, "decode_clip", return_value=(frames, audio, info)) as decode:
            node = driving_clip.ZuraLoadVideo()
            video, out_frames = node.load(clip="ref.mp4", start_seconds=1.5, duration_seconds=2.0,
                                          keep_source_audio=True, source_max_side=1280)
        local.assert_called_once_with("ref.mp4")
        self.assertEqual(decode.call_args.args[1:], (1.5, 2.0, 1280))
        self.assertEqual(int(out_frames.shape[0]), 48)
        self.assertIs(out_frames, frames)
        # The video wire is an ordinary one: frames, rate and audio, readable by
        # any node (Zura Mask included) through video_components.
        images, out_audio, fps = video_module.video_components(video)
        self.assertEqual(int(images.shape[0]), 48)
        self.assertEqual(fps, 24.0)
        self.assertIsNotNone(out_audio)

    def test_mute_switch_removes_audio_from_the_video_wire(self):
        frames, audio = self.make_frames(), self.make_audio(2)
        info = {"fps": 24}
        with patch.object(media_source, "local_path", return_value="ref.mp4"), \
                patch.object(media_source, "decode_clip", return_value=(frames, audio, info)):
            video, _ = driving_clip.ZuraLoadVideo().load(
                clip="ref.mp4", duration_seconds=2, keep_source_audio=False, source_max_side=1280)
        components = video if isinstance(video, dict) else video.get_components()
        self.assertIsNone(components["audio"])

    def test_silent_source_does_not_invent_audio(self):
        frames, info = self.make_frames(), {"fps": 24}
        with patch.object(media_source, "local_path", return_value="ref.mp4"), \
                patch.object(media_source, "decode_clip", return_value=(frames, None, info)):
            video, _ = driving_clip.ZuraLoadVideo().load(
                clip="ref.mp4", duration_seconds=2, keep_source_audio=True, source_max_side=1280)
        components = video if isinstance(video, dict) else video.get_components()
        self.assertIsNone(components["audio"])

    def test_url_takes_priority_over_local_file(self):
        with patch.object(media_source, "download_video", return_value="downloaded.mp4") as download, \
                patch.object(media_source, "decode_clip", return_value=(self.make_frames(), None, {"fps": 24})):
            driving_clip.ZuraLoadVideo().load(
                clip="ref.mp4", video_url="https://example.com/v", duration_seconds=2, source_max_side=1280)
        download.assert_called_once_with("https://example.com/v")

    def test_decode_rejects_out_of_range_duration(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 120"):
            media_source.decode_clip("unused.mp4", 0, clip_seconds=121)

    def test_source_max_side_validation(self):
        self.assertEqual(media_source.source_max_side(1280), 1280)
        with self.assertRaisesRegex(ValueError, "multiple of 64"):
            media_source.source_max_side(1000)
        with self.assertRaisesRegex(ValueError, "multiple of 64"):
            media_source.source_max_side(2500)



class ClipChoiceTests(unittest.TestCase):
    """The clip widget must list where uploads actually land (the input dir).

    Regression: the combo was built only from a ``videos`` model category that
    core ComfyUI does not define, so it was always empty and an uploaded file
    could never be selected.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.input_dir = Path(self.tmp.name)
        (self.input_dir / "uploaded.mp4").write_bytes(b"x")
        (self.input_dir / "notes.txt").write_bytes(b"x")
        (self.input_dir / "takes").mkdir()
        (self.input_dir / "takes" / "take.mov").write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def test_choices_include_input_dir_videos_and_skip_other_files(self):
        with patch.object(driving_clip.folder_paths, "get_input_directory", return_value=str(self.input_dir)), \
                patch.object(driving_clip.folder_paths, "get_filename_list", return_value=["registered.mp4"]):
            choices = driving_clip._video_choices()
        self.assertEqual(choices, ["registered.mp4", "takes/take.mov", "uploaded.mp4"])

    def test_choices_survive_a_missing_videos_category(self):
        def missing(_name):
            raise KeyError("videos")

        with patch.object(driving_clip.folder_paths, "get_input_directory", return_value=str(self.input_dir)), \
                patch.object(driving_clip.folder_paths, "get_filename_list", side_effect=missing):
            self.assertEqual(driving_clip._video_choices(), ["takes/take.mov", "uploaded.mp4"])

    def test_input_types_expose_those_choices(self):
        with patch.object(driving_clip.folder_paths, "get_input_directory", return_value=str(self.input_dir)), \
                patch.object(driving_clip.folder_paths, "get_filename_list", return_value=[]):
            schema = driving_clip.ZuraLoadVideo.INPUT_TYPES()
        choices, options = schema["required"]["clip"]
        self.assertIn("uploaded.mp4", choices)
        # The ``video_upload`` widget flag is not understood by this frontend;
        # the picker uploads through /upload/image instead.
        self.assertNotIn("video_upload", options)

    def test_validate_inputs_accepts_a_name_missing_from_the_list(self):
        # VALIDATE_INPUTS exempts ``clip`` from ComfyUI's combo membership check,
        # so a file uploaded after the node was created still runs.
        cls = driving_clip.ZuraLoadVideo
        with patch.object(driving_clip.folder_paths, "exists_annotated_filepath", return_value=True):
            self.assertIs(cls.VALIDATE_INPUTS(clip="freshly_uploaded.mp4"), True)
        with patch.object(driving_clip.folder_paths, "exists_annotated_filepath", return_value=False):
            self.assertIn("Invalid video file", cls.VALIDATE_INPUTS(clip="ghost.mp4"))

    def test_outputs_are_a_plain_video_and_frames(self):
        cls = driving_clip.ZuraLoadVideo
        self.assertEqual(cls.RETURN_NAMES, ("video", "frames"))
        self.assertEqual(cls.RETURN_TYPES, ("VIDEO", "IMAGE"))
        self.assertEqual(cls.CATEGORY, "Zura")
        # No custom wire type leaves this node any more.
        self.assertNotIn("ZURA_FOOTAGE", cls.RETURN_TYPES)

    def test_video_components_reject_junk(self):
        with self.assertRaisesRegex(ValueError, "no video was provided"):
            video_module.video_components(None)
        with self.assertRaisesRegex(ValueError, "video has no frames"):
            video_module.video_components({})

    def test_preview_clip_returns_temp_reference(self):
        probe = {"format": {"duration": "300"}, "streams": [{"codec_type": "video", "width": 1080, "height": 1920}]}
        with patch.object(media_source, "download_video", return_value="dl.mp4"), \
                patch.object(media_source, "choose_clip_start", return_value=12.0), \
                patch("subprocess.check_output", return_value=b'{"format":{"duration":"300"},"streams":[{"codec_type":"video","width":1080,"height":1920}]}'), \
                patch("subprocess.run") as run:
            result = media_source.preview_clip("https://youtu.be/x", automatic=True, duration=10)
        self.assertEqual(result["start"], 12.0)
        self.assertEqual(result["duration"], 10)
        self.assertEqual(result["type"], "temp")
        self.assertEqual(result["subfolder"], "zura_media")
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
