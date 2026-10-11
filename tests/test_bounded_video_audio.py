"""CPU neutral native VIDEO packet-copy, exact audio and speech-source checks."""
from __future__ import annotations

from fractions import Fraction
import importlib
import os
from pathlib import Path
import sys
import struct
import tempfile
import unittest
from unittest.mock import patch

import av
import numpy as np
import torch

root = Path(os.environ.get("COMFYUI_ROOT", ""))
if root.is_dir():
    sys.path.insert(0, str(root))
from comfy_api.latest import InputImpl
import v2_bootstrap

io = importlib.import_module("ComfyUI_zura_nodes.bounded_video_audio")
guard = importlib.import_module("ComfyUI_zura_nodes.wan_bounded_speech")
windows = importlib.import_module("ComfyUI_zura_nodes.wan_preparation_windows")
speech_spec = importlib.util.spec_from_file_location("bounded_test_existing_speech", v2_bootstrap.ROOT / "artist_studio/wan_speech.py")
existing_speech = importlib.util.module_from_spec(speech_spec)
speech_spec.loader.exec_module(existing_speech)


class NativeFile(InputImpl.VideoFromFile):
    def get_components(self):
        raise AssertionError("Full RGB materialisation is forbidden")


def write_video(path, count=24, width=48, source_audio=None, audio_delay=0):
    with av.open(str(path), "w", format="mov", options={"avoid_negative_ts": "disabled"}) as container:
        stream = container.add_stream("libx264", rate=24)
        stream.width, stream.height, stream.pix_fmt = width, 32, "yuv420p"
        stream.options = {"crf": "16", "bf": "3", "g": "48"}
        astream = None
        if source_audio is not None:
            astream = container.add_stream("pcm_f32le", rate=source_audio["sample_rate"])
            astream.layout = "mono" if source_audio["waveform"].shape[1] == 1 else "stereo"
            astream.format = "flt"
        packets = []
        for index in range(count):
            pixels = np.zeros((32, width, 3), dtype=np.uint8)
            pixels[:, :, 0] = (index * 9) % 256
            pixels[:, index % width:, 1] = (index * 7) % 256
            pixels[8:20, 6:24, 2] = 180
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = index, Fraction(1, 24)
            packets.extend(stream.encode(frame))
        packets.extend(stream.encode())
        if astream is not None:
            for packet in io._audio_packets(astream, source_audio, 0, lambda: None):
                packet.pts += round(audio_delay * source_audio["sample_rate"])
                packet.dts += round(audio_delay * source_audio["sample_rate"])
                packets.append(packet)
        packets.sort(key=lambda p: Fraction(p.dts) * p.time_base)
        for packet in packets:
            container.mux(packet)
    return path


def wave(samples=12000, channels=2, rate=12000):
    values = torch.linspace(-.4, .5, samples)
    channels_data = torch.stack([values * (index + 1) / channels for index in range(channels)])
    return {"waveform": channels_data[None], "sample_rate": rate}


def details(video):
    info = io.inspect_video(video)
    return {"frames": info.frames, "fps": 24, "duration": float(info.duration),
            "width": info.width, "height": info.height, "source": str(info.path),
            "source_hash": io.file_digest(info.path), "start": float(info.start)}


def make_cache(root, video):
    # A tiny real preparation cache built from actual native decoder output.
    images = InputImpl.VideoFromFile(video.get_stream_source(),
        start_time=video.get_active_trim_window()[0], duration=video.get_active_trim_window()[1]).get_components().images
    mask = torch.zeros(images.shape[:3]); mask[:, 8:20, 6:24] = 1
    value = {"version": 1, "footage": {"frames": images, "character_mask": mask,
        "pose_video": images.clone(), "face_video": images[:, :16, :16].clone(),
        "video_info": {"fps": 24}, "replacement_area": "Whole character", "keep_audio": False,
        "speech_provenance": {"guide_key": "b" * 64, "guide_sha": "c" * 64}}, "reference": images[:1].clone()}
    key = "a" * 64
    path = Path(root) / (key + ".pt")
    torch.save(value, path)
    reader = windows.WanPreparationWindows(path, key, root, max_window_frames=4)
    return reader, value


def change_container_metadata_same_stamp(path):
    stamp = Path(path).stat()
    # Neutral tiny fixture only: mutate muxer-name metadata, not pixels/audio.
    data = Path(path).read_bytes()
    offset = data.index(b"Lavf") + 3
    with Path(path).open("r+b") as handle:
        handle.seek(offset); handle.write(b"g")
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))


class BoundedAudioTests(unittest.TestCase):
    def test_signature_matches_existing_wan_contract_exactly(self):
        for channels, rate, samples in ((1,44100,1739), (2,48000,8113), (2,12000,12000)):
            audio = wave(samples, channels, rate)
            self.assertEqual(io.audio_signature(audio), existing_speech.audio_signature(audio))

    def test_lossless_packets_and_native_body_pixels_with_bframes(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = NativeFile(str(write_video(Path(tmp) / "source.mov")))
            chosen = wave()
            with patch.object(NativeFile, "get_components", side_effect=AssertionError("not bounded")):
                output, metadata = io.attach_selected_audio(original, details(original), tmp, chosen)
            self.assertIsInstance(output, InputImpl.VideoFromFile)
            self.assertEqual(io._packet_signature(original.get_stream_source()), io._packet_signature(output.get_stream_source()))
            before = InputImpl.VideoFromFile(original.get_stream_source()).get_components()
            after = output.get_components()
            self.assertTrue(torch.equal(before.images, after.images))
            self.assertEqual(io.audio_signature(after.audio), io.audio_signature(chosen))
            self.assertEqual(io.audio_signature(io.decode_selected_audio(output)), io.audio_signature(chosen))
            self.assertEqual(metadata["audio_mode"], "reference")
            self.assertEqual(output.get_active_trim_window(), original.get_active_trim_window())
            with av.open(original.get_stream_source()) as container:
                frames = list(container.decode(video=0))
                self.assertIn(av.video.frame.PictureType.B, [frame.pict_type for frame in frames])
            self.assertEqual(io.file_digest(metadata["audio_source"]), metadata["audio_hash"])
            self.assertFalse(list(Path(tmp).rglob("*.partial.*")))

    def test_nonkeyframe_native_trim_and_reference_offset_once_with_tail_pad(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_video(Path(tmp) / "source.mov", count=48)
            source = NativeFile(str(path), start_time=.5, duration=1)
            chosen = wave(12000)
            expected = io.fit_selected_audio(chosen, 1, .25)
            output, _ = io.attach_selected_audio(source, details(source), tmp, chosen, .25)
            self.assertEqual(output.get_active_trim_window(), (.5, 1.0))
            actual = output.get_components()
            original = InputImpl.VideoFromFile(str(path), start_time=.5, duration=1).get_components()
            self.assertTrue(torch.equal(actual.images, original.images))
            self.assertEqual(io.audio_signature(actual.audio), io.audio_signature(expected))
            self.assertTrue(torch.equal(actual.audio["waveform"][..., :9000], chosen["waveform"][..., 3000:]))
            self.assertEqual(int(torch.count_nonzero(actual.audio["waveform"][..., 9000:])), 0)

    def test_fractional_audio_duration_preserves_untrimmed_native_sample_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = NativeFile(str(write_video(Path(tmp)/"odd.mov", count=25)))
            reference = wave(60000, channels=1, rate=44100)
            output, _ = io.attach_selected_audio(source, details(source), tmp, reference)
            expected = io.fit_selected_audio(reference, 25/24)
            self.assertEqual(output.get_active_trim_window(), (0.0, 0.0))
            self.assertEqual(io.audio_signature(output.get_components().audio), io.audio_signature(expected))
            explicit = NativeFile(source.get_stream_source(), duration=25/24)
            with self.assertRaisesRegex(ValueError, "rounded audio sample"):
                io.attach_selected_audio(explicit, details(explicit), tmp, reference)

    def test_delayed_original_audio_and_silent_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            chosen = wave(6000, channels=1)
            path = write_video(Path(tmp) / "delayed.mov", source_audio=chosen, audio_delay=.25)
            source = NativeFile(str(path))
            expected = torch.zeros(1, 1, 12000)
            expected[..., 3000:9000] = chosen["waveform"]
            output, metadata = io.attach_selected_audio(source, details(source), tmp)
            self.assertTrue(torch.equal(io.decode_selected_audio(output)["waveform"], expected))
            self.assertNotIn("audio_mode", metadata)
            silent = NativeFile(str(write_video(Path(tmp) / "silent.mov")))
            result, _ = io.attach_selected_audio(silent, details(silent), tmp)
            audio = io.decode_selected_audio(result)
            self.assertEqual(audio["sample_rate"], 48000)
            self.assertEqual(tuple(audio["waveform"].shape), (1, 2, 48000))
            self.assertEqual(int(torch.count_nonzero(audio["waveform"])), 0)

    def test_bounded_guard_exact_native_float_rgb_and_every_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = NativeFile(str(write_video(Path(tmp) / "source.mov")))
            selected, _ = io.attach_selected_audio(source, details(source), tmp, wave())
            forbidden = NativeFile(selected.get_stream_source(), start_time=0, duration=1)
            reader, _ = make_cache(tmp, forbidden)
            expected_audio = io.audio_signature(wave())
            result = guard.verify_selected_media(reader.footage(), forbidden,
                {"frames": 24, "fps": 24, "duration": 1}, expected_audio, window_frames=4)
            self.assertEqual(result["frames"], 24)
            self.assertEqual(result["comparison_window_frames"], 4)
            self.assertLessEqual(reader.stats["maximum_copy_bytes"], 4*32*48*3*4)
            actual_frames = torch.stack([frame for _, frame in io.iter_native_frames(forbidden)])
            self.assertTrue(torch.equal(actual_frames, InputImpl.VideoFromFile(selected.get_stream_source()).get_components().images))
            changed = dict(expected_audio); changed["sha"] = "d" * 64
            with self.assertRaisesRegex(ValueError, "selected audio"):
                guard.verify_selected_media(reader.footage(), forbidden,
                    {"frames": 24, "fps": 24, "duration": 1}, changed)

    def test_reject_mismatch_and_mixed_preparation_before_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = NativeFile(str(write_video(Path(tmp) / "source.mov")))
            selected, _ = io.attach_selected_audio(source, details(source), tmp, wave())
            reader, value = make_cache(tmp, selected)
            value["footage"]["frames"][15, 10, 10, 0] = .8125
            path = Path(tmp) / ("e" * 64 + ".pt"); torch.save(value, path)
            changed_reader = windows.WanPreparationWindows(path, "e"*64, tmp, max_window_frames=4)
            args = ({"frames":24,"fps":24,"duration":1}, io.audio_signature(wave()))
            with self.assertRaisesRegex(ValueError, "selected frames"):
                guard.verify_selected_media(changed_reader.footage(), selected, *args)
            mixed = reader.footage(); mixed["pose_video"] = changed_reader.arrays["pose_video"]
            with self.assertRaisesRegex(ValueError, "different preparation"):
                guard.validate_window_footage(mixed)
            changed_receipt = reader.footage(); changed_receipt["streaming_preparation"] = {}
            with self.assertRaisesRegex(ValueError, "receipt"):
                guard.validate_window_footage(changed_receipt)
            # A shallow metadata alias is not proof of approved disk metadata.
            altered = reader.footage(); altered["video_info"]["fps"] = 25
            with self.assertRaisesRegex(ValueError, "metadata changed"):
                guard.validate_window_footage(altered)

    def test_cancellation_and_source_mutation_leave_no_published_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_video(Path(tmp) / "source.mov")
            source = NativeFile(str(path))
            original_digest = io.file_digest
            def mutate_on_final_verify(p, interrupt=lambda: None):
                if Path(p) == path and list(Path(tmp).rglob("*.partial.mov")):
                    change_container_metadata_same_stamp(path)
                return original_digest(p, interrupt)
            with patch.object(io, "file_digest", side_effect=mutate_on_final_verify):
                with self.assertRaisesRegex(ValueError, "source changed"):
                    io.attach_selected_audio(source, details(source), tmp, wave())
            self.assertFalse(list((Path(tmp)/"genj").rglob("*.mov")))
            self.assertFalse(list((Path(tmp)/"genj").rglob("*.wav")))
            count = 0
            def cancel():
                nonlocal count
                count += 1
                if count == 60:
                    raise RuntimeError("cancelled")
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                io.attach_selected_audio(source, details(source), tmp, wave(), interrupt=cancel)
            self.assertFalse(list((Path(tmp)/"genj").rglob("*.mov")))

    def test_guard_hashes_cache_before_decode_and_source_after_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = NativeFile(str(write_video(Path(tmp)/"source.mov")))
            selected, _ = io.attach_selected_audio(source, details(source), tmp, wave())
            reader, _ = make_cache(tmp, selected)
            original_frames = guard.iter_native_frames
            def mutate_during_frames(*args, **kwargs):
                for index, frame in original_frames(*args, **kwargs):
                    if index == 1:
                        change_container_metadata_same_stamp(selected.get_stream_source())
                    yield index, frame
            with patch.object(guard, "iter_native_frames", side_effect=mutate_during_frames):
                with self.assertRaisesRegex(ValueError, "source changed"):
                    guard.verify_selected_media(reader.footage(), selected,
                        {"frames":24,"fps":24,"duration":1}, io.audio_signature(wave()))
            stamp = reader.path.stat()
            with reader.path.open("r+b") as handle:
                handle.seek(reader.arrays["frames"]._layout.member_offset)
                handle.write(struct.pack("<f", .875))
            os.utime(reader.path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            with patch.object(guard, "inspect_video", side_effect=AssertionError("cache must fail before VIDEO decode")):
                with self.assertRaisesRegex(ValueError, "bytes changed"):
                    guard.verify_selected_media(reader.footage(), selected,
                        {"frames":24,"fps":24,"duration":1}, io.audio_signature(wave()))

    def test_invalid_metadata_audio_and_crop_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = NativeFile(str(write_video(Path(tmp) / "source.mov")))
            wrong = details(source); wrong["frames"] = 20
            with self.assertRaisesRegex(ValueError, "metadata"):
                io.attach_selected_audio(source, wrong, tmp, wave())
            with self.assertRaisesRegex(ValueError, "within"):
                io.attach_selected_audio(source, details(source), tmp, wave(), 2)
            with self.assertRaises(ValueError):
                io.fit_selected_audio(wave(), 31)
            invalid = wave(); invalid["waveform"][0,0,0] = float("nan")
            with self.assertRaises(ValueError):
                io.attach_selected_audio(source, details(source), tmp, invalid)
            with self.assertRaisesRegex(ValueError, "cropping"):
                io.inspect_video(source.as_cropped(0,0,16,16))
            invalid = wave(24000); invalid["waveform"][0,0,-1] = float("nan")
            with self.assertRaisesRegex(ValueError, "finite"):
                io.fit_selected_audio(invalid, 1)

    def test_output_junction_or_symlink_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            source = NativeFile(str(write_video(Path(tmp)/"source.mov")))
            target = Path(tmp)/"genj"/"reference_video"
            target.parent.mkdir()
            try:
                target.symlink_to(Path(outside), target_is_directory=True)
            except OSError:
                self.skipTest("This platform cannot create a directory symlink")
            with self.assertRaisesRegex(ValueError, "directory leaves"):
                io.attach_selected_audio(source, details(source), tmp, wave())
            self.assertEqual(list(Path(outside).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
