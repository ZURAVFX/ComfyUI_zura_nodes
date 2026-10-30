"""Actual bounded native VIDEO path retains the existing Wan provenance gate."""
from __future__ import annotations

import copy
import ast
import importlib
import json
import os
from pathlib import Path
import sys
import types
import unittest
import re
import shutil
import subprocess
from unittest.mock import patch

import torch
import soundfile

import test_bounded_video_audio as media
import test_wan_speech as fixtures

speech, wan, adapters = fixtures.speech, fixtures.wan, fixtures.adapters
bounded = importlib.import_module("ComfyUI_zura_nodes.wan_bounded_speech")
io = media.io
windows = media.windows
FFMPEG = shutil.which("ffmpeg")


class BoundedSpeechGuardTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.GuideTests("test_audio_keeps_rate_channels_silence_and_selected_samples")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.project = f.project
        self.source = media.write_video(f.base / "neutral-source.mov", count=48)
        f.manifest["clip"]["source_hash"] = speech.digest(self.source)
        graph, self.guide_path, history = f.save_and_history()
        self.record = speech.record_guide(self.project, history)
        self.key = self.record["guide_key"]
        self.opening = torch.full((1, 8, 8, 3), .5)
        self.raw_audio = {"waveform": f.wave[None], "sample_rate": 24000}
        self.selected_source = media.NativeFile(str(self.source), start_time=.25, duration=1)
        self.input_details = {**media.details(self.selected_source), "review_shot_id": self.project["review"],
            "source": str(self.source), "source_hash": speech.digest(self.source), "start": .25}
        selected, self.details = io.attach_selected_audio(self.selected_source, self.input_details,
            f.base, self.raw_audio, .1)
        self.video = media.NativeFile(selected.get_stream_source(), start_time=.25, duration=1)
        self.audio = io.fit_selected_audio(self.raw_audio, 1, .1)
        self.assertEqual(speech.audio_signature(self.audio), self.record["key_data"]["selected_audio"])
        # Tiny fixture preparation ground truth uses the actual installed native
        # float RGB converter. The guard itself is forbidden to materialise it.
        images = media.InputImpl.VideoFromFile(selected.get_stream_source(), start_time=.25, duration=1).get_components().images
        mask = torch.zeros(images.shape[:3]); mask[:, 8:20, 6:24] = 1
        value = {"version":1, "footage": {"frames":images, "character_mask":mask,
            "pose_video":images.clone(), "face_video":images[:,:16,:16].clone(),
            "replacement_area":"Whole character", "video_info":{"fps":24}, "keep_audio":False,
            "speech_provenance":{"guide_key":self.key,"guide_sha":self.record["sha"]}}, "reference":self.opening}
        self.cache_path = f.base / ("a"*64 + ".pt")
        torch.save(value, self.cache_path)
        self.cache_value = value
        self.reader = windows.WanPreparationWindows(self.cache_path, "a"*64, f.base, max_window_frames=4)
        self.footage = self.reader.footage()
        import folder_paths
        f.enter(patch.object(folder_paths, "get_annotated_filepath", side_effect=lambda filename:str(f.base/filename)))
        f.enter(patch.object(sys.modules["nodes"], "LoadImage", lambda:type("ImageLoader",(),{
            "load_image":lambda _,filename:(self.opening.clone(),None)})(), create=True))
        # Real PCM file decoder, not a waveform-value stub. The fixture provider
        # module contains only this CPU IO function and no model operations.
        def load_audio(filename):
            array, rate = soundfile.read(filename, dtype="float32", always_2d=True)
            return torch.from_numpy(array.T.copy()), rate
        f.enter(patch.object(sys.modules["comfy_extras.nodes_audio"], "load", side_effect=load_audio))
        management = types.ModuleType("comfy.model_management")
        management.throw_exception_if_processing_interrupted = lambda:None
        f.enter(patch.dict(sys.modules, {"comfy.model_management":management}))
        f.enter(patch.object(adapters, "video_components", side_effect=AssertionError("bounded guard called full VIDEO components")))
        f.enter(patch.object(adapters, "validate_footage", side_effect=AssertionError("bounded guard called whole Tensor validation")))

    def verify(self, **overrides):
        values = {"footage":self.footage,"selected_video":self.video,"clip_details":self.details,
            "opening":self.opening,"approved_opening_file":"opening.png","seed":123,"guide_key":self.key}
        values.update(overrides)
        return adapters.ZuraWanSpeechGuard().verify(**values)

    def assert_stale(self, message, **overrides):
        with self.assertRaisesRegex(ValueError, message) as failure:
            self.verify(**overrides)
        self.assertIn("regenerate the facial performance", str(failure.exception))
        self.assertIn("reopen the animation graph", str(failure.exception))

    def save_record(self, record):
        speech._manifest_path(self.key).write_text(json.dumps(record), encoding="utf-8")

    def test_real_bounded_media_passes_same_objects_and_seed_without_eager_reads(self):
        footage, opening, seed = self.verify()
        self.assertIs(footage, self.footage)
        self.assertIs(opening, self.opening)
        self.assertEqual(seed, 123)
        self.assertLessEqual(self.reader.stats["maximum_copy_bytes"], 4*32*48*3*4)

    def test_manifest_state_guide_recipe_crop_and_artifact_are_still_enforced(self):
        changes = [
            (lambda x:x.update(state="pending"), "not completed verification"),
            (lambda x:x.update(guide_key="b"*64), "not completed verification"),
            (lambda x:x["key_data"].update(seed=456), "recipe changed"),
            (lambda x:x["crop"].update(guide_key="b"*64), "crop recipe"),
            (lambda x:x["crop"].update(source_confidence=.1), "trustworthy approved face"),
            (lambda x:x["crop"].update(crop_xywh=[-1,50,180,240]), "reference crop is invalid"),
            (lambda x:x.update(sha="b"*64), "facial-performance video changed"),
            (lambda x:x.update(path=str(self.source)), "Zura's guide folder"),
        ]
        for change, message in changes:
            with self.subTest(message=message):
                record = copy.deepcopy(self.record); change(record); self.save_record(record)
                self.assert_stale(message)
                self.save_record(self.record)
        original = self.guide_path.read_bytes()
        self.guide_path.write_bytes(b"invalid neutral guide")
        self.assert_stale("cannot be decoded")
        self.guide_path.write_bytes(original)
        self.assert_stale("provenance is missing",guide_key="e"*64)

    def test_source_review_start_count_fps_duration_and_file_are_still_enforced(self):
        for field, value in (("review_shot_id","different-review"),("start",.3),("frames",23),
                             ("fps",25),("duration",1.1),("source_hash","b"*64)):
            with self.subTest(field=field):
                self.assert_stale("selected shot or timing", clip_details={**self.details,field:value})
        self.assert_stale("source footage changed", clip_details={**self.details,"source":str(self.cache_path)})
        media.change_container_metadata_same_stamp(self.source)
        self.assert_stale("source footage changed")

    def test_review_mask_and_prepared_guide_provenance_are_still_enforced(self):
        self.fixture.manifest["files"]["mask.mp4"] = "different-neutral-mask"
        self.assert_stale("reviewed performer mask changed")
        self.fixture.manifest["files"]["mask.mp4"] = self.record["key_data"]["source"]["mask_sha"]
        for provenance in (None, {"guide_key":self.key,"guide_sha":"b"*64}):
            changed = dict(self.footage)
            if provenance is None:
                changed.pop("speech_provenance")
            else:
                changed["speech_provenance"] = provenance
            self.assert_stale("prepared face motion belongs", footage=changed)

    def test_selected_pcm_waveform_and_offset_are_checked_from_actual_video(self):
        for audio, start in (({"waveform":torch.ones(1,1,4800),"sample_rate":24000},.1),
                             (self.raw_audio,0)):
            selected, _ = io.attach_selected_audio(self.selected_source, self.input_details,
                self.fixture.base, audio, start)
            actual = media.NativeFile(selected.get_stream_source(), start_time=.25, duration=1)
            self.assert_stale("selected audio or its start", selected_video=actual)

    def test_actual_body_pixels_must_match_bounded_cache(self):
        changed = copy.deepcopy(self.cache_value)
        changed["footage"]["frames"][15,10,10,0] = .875
        path = self.fixture.base / ("e"*64 + ".pt"); torch.save(changed,path)
        reader = windows.WanPreparationWindows(path,"e"*64,self.fixture.base,max_window_frames=4)
        self.assert_stale("actual selected frames", footage=reader.footage())

    def test_soundtrack_mode_hash_and_actual_pcm_values_are_still_enforced(self):
        self.assert_stale("soundtrack no longer uses", clip_details={**self.details,"audio_mode":"original"})
        self.assert_stale("soundtrack no longer uses", clip_details={**self.details,"audio_source":""})
        self.assert_stale("soundtrack changed on disk", clip_details={**self.details,"audio_hash":"b"*64})
        soundtrack = Path(self.details["audio_source"])
        soundfile.write(soundtrack, torch.ones(24000).numpy(), 24000, subtype="FLOAT")
        # Matching the new file hash must not bypass exact waveform equality.
        self.assert_stale("final soundtrack differs", clip_details={**self.details,"audio_hash":speech.digest(soundtrack)})

    def test_seed_opening_hash_and_actual_connected_opening_are_still_enforced(self):
        self.assert_stale("performance seed changed", seed=124)
        self.assert_stale("connected character opening", opening=self.opening + .1)
        (self.fixture.base/"opening.png").write_bytes(b"different neutral approved appearance")
        self.assert_stale("approved character opening changed")

    def test_forged_receipt_shallow_metadata_or_mixed_cache_cannot_pass(self):
        for receipt in ({},None,[],"forged"):
            changed = dict(self.footage); changed["streaming_preparation"] = receipt
            self.assert_stale("receipt", footage=changed)
        path = self.fixture.base / ("e"*64 + ".pt"); torch.save(self.cache_value,path)
        other = windows.WanPreparationWindows(path,"e"*64,self.fixture.base,max_window_frames=4)
        changed = dict(self.footage); changed["face_video"] = other.arrays["face_video"]
        self.assert_stale("different preparation", footage=changed)
        changed = dict(self.footage); changed["video_info"]["fps"] = 25
        self.assert_stale("metadata changed", footage=changed)

    def test_relaxed_part_arrays_cannot_bypass_speech_footage_boundary(self):
        path = self.fixture.base / ("e" * 64 + ".pt")
        changed = copy.deepcopy(self.cache_value)
        changed["footage"]["character_mask"].zero_()
        torch.save(changed, path)
        reader = windows.WanPreparationWindows(path, "e" * 64, self.fixture.base,
                                              require_nonempty_mask=False)
        forged = dict(reader.metadata)
        forged.update({name: reader.arrays[name] for name in windows.TENSOR_NAMES[:-1]})
        forged["streaming_preparation"] = reader.provenance
        reader.require_nonempty_mask = True
        with self.assertRaisesRegex(ValueError, "merged"):
            bounded.validate_window_footage(forged)

    def test_restored_mtime_cache_mutation_fails_before_selected_video_decode(self):
        stamp = self.cache_path.stat()
        import struct
        with self.cache_path.open("r+b") as handle:
            handle.seek(self.reader.arrays["frames"]._layout.member_offset)
            handle.write(struct.pack("<f",.875))
        os.utime(self.cache_path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        with patch.object(bounded,"inspect_video",side_effect=AssertionError("cache must fail before decode")):
            self.assert_stale("bytes changed")

    def test_cached_builder_uses_one_bounded_audio_and_window_loader_with_same_guard(self):
        key = wan.cache_key(self.project)
        path = wan.cache_path(key); path.parent.mkdir(parents=True,exist_ok=True)
        torch.save(self.cache_value,path)
        graph = wan.build_wan_graph(self.project,use_cache=True)
        self.assertEqual(graph["wan_audio_selection"]["class_type"],"ZuraApplyBoundedReferenceAudio")
        self.assertEqual(graph["wan_cached"]["class_type"],"ZuraWanLoadWindowPreparation")
        self.assertEqual(graph["wan_cached"]["inputs"]["max_window_frames"],81)
        self.assertEqual(graph["wan_render"]["class_type"],"ZuraWan22StreamedSampler")
        self.assertEqual(graph["wan_render"]["inputs"]["footage"],["wan_speech_guard",0])
        self.assertEqual(graph["wan_render"]["inputs"]["seed"],["wan_speech_guard",2])
        self.assertEqual(graph["wan_speech_guard"]["inputs"]["selected_video"],["wan_audio_selection",0])
        self.assertEqual(graph["wan_speech_guard"]["inputs"]["clip_details"],["wan_audio_selection",1])
        self.assertEqual(graph["wan_export"]["inputs"]["video"],["wan_render",0])
        self.assertEqual(graph["wan_export"]["inputs"]["clip_details"],["wan_audio_selection",1])
        self.assertEqual(sum(n["class_type"]=="LoadAudio" for n in graph.values()),1)
        self.assertEqual(sum(n["class_type"]=="GenjRestoreSoundtrack" for n in graph.values()),1)
        self.assertEqual(graph["wan_render"]["inputs"]["overlap_frames"],5)
        self.assertEqual(graph["wan_render"]["inputs"]["join_mode"],"Native continuation")
        self.assertEqual(graph["wan_steps"]["inputs"]["value"],6)
        self.assertEqual(graph["wan_cfg"]["inputs"]["value"],1.0)

    @unittest.skipUnless(FFMPEG,"CPU FFmpeg executable unavailable")
    def test_relight_review_loader_preserves_source_aspect_and_separates_cache(self):
        path = fixtures.v2_bootstrap.ROOT / "artist_studio" / "__init__.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GenjLoadReviewedShot")
        source = media.write_video(self.fixture.base / "aspect-source.mov", count=24, width=48,
                                   source_audio=media.wave(samples=24000, channels=1, rate=24000))
        directory = self.fixture.base / "aspect-review"
        directory.mkdir()
        for name in ("source.mp4", "mask.mp4", "guide.mp4"):
            shutil.copy2(source, directory / name)
        details = {"source": str(source), "source_hash": io.file_digest(source), "start": 0,
                   "duration": 1.0, "frames": 24, "fps": 24}
        manifest = {"clip": details, "files": {}}
        def ffmpeg(*args):
            subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *map(str,args)],
                           capture_output=True, text=True, check=True)
        namespace = {"CATEGORY":"Zura/Artist Studio", "Path":Path, "InputImpl":media.InputImpl,
                     "av":media.av, "digest_file":io.file_digest, "ffmpeg":ffmpeg,
                     "verify_review":lambda _shot:(directory, manifest)}
        exec(compile(ast.Module(body=[definition],type_ignores=[]),str(path),"exec"), namespace)
        loader = namespace["GenjLoadReviewedShot"]()
        default = loader.load("shot", "shot", render_long_edge=256)
        relight = loader.load("shot", "shot", render_long_edge=256, preserve_aspect=True)
        self.assertEqual((default[3]["width"], default[3]["height"]), (256, 192))
        self.assertEqual((relight[3]["width"], relight[3]["height"]), (256, 170))
        self.assertNotEqual(default[3]["selected_path"], relight[3]["selected_path"])
        with media.av.open(relight[3]["selected_path"]) as clip:
            self.assertEqual((clip.streams.video[0].width, clip.streams.video[0].height), (256, 170))

    @unittest.skipUnless(FFMPEG,"CPU FFmpeg executable unavailable")
    def test_review_loader_keeps_selected_frames_at_fractional_source_rates(self):
        path = fixtures.v2_bootstrap.ROOT / "artist_studio" / "__init__.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GenjLoadReviewedShot")
        def ffmpeg(*args):
            subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *map(str,args)],
                           capture_output=True, text=True, check=True)
        for rate in ("24000/1001", "30000/1001", "25"):
            with self.subTest(rate=rate):
                source = self.fixture.base / ("fractional-" + rate.replace('/', '-') + ".mp4")
                ffmpeg("-f", "lavfi", "-i", f"testsrc2=size=96x64:rate={rate}",
                       "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "2",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", source)
                directory = self.fixture.base / ("review-" + rate.replace('/', '-'))
                directory.mkdir()
                for name in ("source.mp4", "mask.mp4", "guide.mp4"):
                    shutil.copy2(source, directory / name)
                details = {"source": str(source), "source_hash": io.file_digest(source), "start": .21,
                           "duration": 1.25, "frames": 30, "fps": 24}
                manifest = {"clip": details, "files": {}}
                namespace = {"CATEGORY":"Zura/Artist Studio", "Path":Path, "InputImpl":media.InputImpl,
                             "av":media.av, "digest_file":io.file_digest, "ffmpeg":ffmpeg,
                             "verify_review":lambda _shot:(directory, manifest)}
                exec(compile(ast.Module(body=[definition],type_ignores=[]),str(path),"exec"), namespace)
                selected = namespace["GenjLoadReviewedShot"]().load("shot", "shot", render_long_edge=256, preserve_aspect=True)
                with media.av.open(selected[3]["selected_path"]) as clip:
                    self.assertEqual(sum(1 for _ in clip.decode(video=0)), 30)
                if rate == "24000/1001":
                    short = directory / "short.mp4"
                    ffmpeg("-i", source, "-frames:v", "5", "-c:v", "libx264", "-c:a", "aac", short)
                    shutil.copy2(short, selected[3]["selected_path"])
                    with self.assertRaisesRegex(ValueError, "5 of 30 requested frames"):
                        namespace["GenjLoadReviewedShot"]().load("shot", "shot", render_long_edge=256, preserve_aspect=True)

    @unittest.skipUnless(FFMPEG,"CPU FFmpeg executable unavailable")
    def test_real_final_soundtrack_restore_uses_normalized_wav_with_zero_offset(self):
        # Load the unchanged production export class without importing/registering
        # the whole Studio extension. Run its actual FFmpeg mux on tiny CPU media.
        path = fixtures.v2_bootstrap.ROOT/"artist_studio"/"__init__.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        definition = next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=="GenjRestoreSoundtrack")
        calls = []
        def ffmpeg(*args):
            calls.append(args)
            completed = subprocess.run([FFMPEG,"-hide_banner","-loglevel","error","-y",*map(str,args)],
                                       capture_output=True,text=True)
            if completed.returncode:
                raise RuntimeError(completed.stderr)
        output_root = self.fixture.base/"output"/"genj"
        output_root.mkdir(parents=True,exist_ok=True)
        namespace = {"CATEGORY":"Zura/Artist Studio","Path":Path,"re":re,"av":media.av,
            "InputImpl":media.InputImpl,"digest_file":io.file_digest,"source_path":lambda v:Path(v.get_stream_source()),
            "root":lambda:output_root,"ffmpeg":ffmpeg}
        exec(compile(ast.Module(body=[definition],type_ignores=[]),str(path),"exec"),namespace)
        generated = media.NativeFile(str(media.write_video(self.fixture.base/"neutral-generated.mov",count=24)))
        result = namespace["GenjRestoreSoundtrack"]().restore(generated,{**self.details,"full_source":False},"neutral_take")
        restored = result["result"][0]
        command = calls[0]
        self.assertEqual(command[command.index("-ss")+1],0)
        inputs = [command[index+1] for index,value in enumerate(command) if value=="-i"]
        self.assertEqual(str(inputs[1]),self.details["audio_source"])
        self.assertEqual(io.inspect_video(restored).frames,24)
        actual = io.decode_selected_audio(restored)
        self.assertEqual(actual["sample_rate"],24000)
        self.assertEqual(tuple(actual["waveform"].shape),(1,1,24000))
        # Delivery AAC is lossy; timing/energy, not PCM hash, is the invariant.
        # A repeated .25-second source offset would remove this entire 0.1s line.
        self.assertGreater(float(actual["waveform"][...,:1000].abs().mean()),.02)
        self.assertLess(float(actual["waveform"][...,4800:].abs().max()),.001)

        # A decoder can lose exactly one 24 fps frame to timebase rounding.
        # The delivery must hold the final frame, not shorten the selection.
        short = media.NativeFile(str(media.write_video(self.fixture.base/"neutral-short.mov",count=23)))
        result = namespace["GenjRestoreSoundtrack"]().restore(short,{**self.details,"full_source":False},"short_take")
        self.assertEqual(io.inspect_video(result["result"][0]).frames,24)
        self.assertIn('tpad=stop_mode=clone:stop=1', calls[-1][calls[-1].index('-vf')+1])
        sized = namespace["GenjRestoreSoundtrack"]().restore(generated,{**self.details,"full_source":False},"sized_take",output_width=96,output_height=64)
        with media.av.open(str(sized["result"][0].get_stream_source())) as container:
            self.assertEqual((container.streams.video[0].width,container.streams.video[0].height),(96,64))
        self.assertIn('force_original_aspect_ratio=increase',calls[-1][calls[-1].index('-vf')+1])


if __name__ == "__main__":
    unittest.main()
