"""CPU-only exact-cache, native ownership and atomic delivery contracts."""
from __future__ import annotations

import importlib
import json
import os
import struct
from pathlib import Path
import sys
import tempfile
import types
import unittest
import zipfile
from unittest.mock import patch

import av
import torch

# Exercise the real native file VIDEO API when a Comfy checkout is available.
# This imports data interfaces only; CUDA is disabled in the CPU test command.
COMFY_ROOT = Path(os.environ.get("COMFYUI_ROOT", ""))
if COMFY_ROOT.is_dir():
    sys.path.insert(0, str(COMFY_ROOT))
try:
    from comfy_api.latest import InputImpl
except ImportError:
    InputImpl = None

import v2_bootstrap

artist = importlib.import_module("ComfyUI_zura_nodes.wan_artist")
render = importlib.import_module("ComfyUI_zura_nodes.render")
delivery = importlib.import_module("ComfyUI_zura_nodes.streaming_video")
planning = importlib.import_module("ComfyUI_zura_nodes.planning")
windows = importlib.import_module("ComfyUI_zura_nodes.wan_preparation_windows")


def data(count=19):
    frames = torch.arange(count, dtype=torch.float32).view(count, 1, 1, 1).expand(count, 64, 64, 3).clone() / 64
    mask = torch.zeros(count, 64, 64)
    mask[:, 10:20, 10:20] = 1
    return {"version": 1, "footage": {"frames": frames, "character_mask": mask,
        "pose_video": frames.clone(), "face_video": frames[:, :16, :16].clone(),
        "replacement_area": "Whole character", "video_info": {"fps": 24}, "keep_audio": False},
        "reference": torch.full((1, 64, 64, 3), .34719)}


def read(path):
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        fps = stream.average_rate
        frames = [(frame.to_ndarray(format="rgb24"), frame.pts * frame.time_base) for frame in container.decode(stream)]
        return fps, frames, len(container.streams.audio)


def change_one_mapped_float(path):
    """Tamper one real ZIP tensor byte range, preserving file size and mtime."""
    stamp = Path(path).stat()
    with zipfile.ZipFile(path) as archive:
        member = next(info for info in archive.infolist() if info.filename.endswith("/data/0"))
    with Path(path).open("r+b") as handle:
        handle.seek(member.header_offset)
        header = struct.unpack("<IHHHHHIIIHH", handle.read(30))
        start = member.header_offset + 30 + header[-2] + header[-1]
        handle.seek(start)
        old = handle.read(4)
        handle.seek(start)
        handle.write(struct.pack("<f", .875 if struct.unpack("<f", old)[0] != .875 else .125))
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    after = Path(path).stat()
    assert (after.st_size, after.st_mtime_ns) == (stamp.st_size, stamp.st_mtime_ns)


def restore_cache_copy(path, contents, stamp):
    # A Windows active mapping permits same-size writes, not truncating save.
    with Path(path).open("r+b") as handle:
        handle.write(contents)
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))


def save_window_cache(output_root, key, value):
    cache_dir = Path(output_root) / "genj" / "wan_conditioning"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / (key + ".pt")
    torch.save(value, path)
    return path


def mock_wan_runtime(records, calls):
    """Mock only inference kernels; keep preparation, PyAV and writer real."""
    class Native:
        def execute(self, *args, **kwargs):
            calls["native"] = calls.get("native", 0) + 1
            pose = kwargs["pose_video"]
            anchor = kwargs["continue_motion"]
            records.append({"pose": pose.clone(), "bg": kwargs["background_video"].clone(),
                "mask": kwargs["character_mask"].clone(),
                "anchor": None if anchor is None else anchor.clone()})
            output = pose.clone()
            if anchor is not None:
                output[:len(anchor)] = (anchor + .03).clamp(0, 1)
            records[-1]["generated"] = output.clone()
            samples = output.permute(3, 0, 1, 2)[None]
            return "positive", "negative", {"samples": samples}, 0, 0 if anchor is None else len(anchor), None

    def encode_text(*args):
        calls["text"] = calls.get("text", 0) + 1
        return ("encoded",)

    def encode_vision(*args):
        calls["vision"] = calls.get("vision", 0) + 1
        return ("vision",)

    def sample(*args):
        calls["sampler"] = calls.get("sampler", 0) + 1
        return (args[-1],)

    def decode(vae, latent, **kwargs):
        calls["decode"] = calls.get("decode", 0) + 1
        return (latent["samples"][0].permute(1, 2, 3, 0),)

    nodes = types.ModuleType("nodes")
    nodes.CLIPTextEncode = lambda: types.SimpleNamespace(encode=encode_text)
    nodes.CLIPVisionEncode = lambda: types.SimpleNamespace(encode=encode_vision)
    nodes.common_ksampler = sample
    nodes.VAEDecodeTiled = lambda: types.SimpleNamespace(decode=decode)
    wan = types.ModuleType("comfy_extras.nodes_wan")
    wan.WanAnimateToVideo = Native
    management = types.ModuleType("comfy.model_management")
    management.throw_exception_if_processing_interrupted = lambda: None
    utils = types.ModuleType("comfy.utils")
    utils.ProgressBar = lambda count: types.SimpleNamespace(update=lambda count: None)
    return {"nodes": nodes, "comfy_extras.nodes_wan": wan,
            "comfy.model_management": management, "comfy.utils": utils}


def stream_kwargs(footage, reference, *, chunk_frames=13):
    return {"model": object(), "clip": object(), "vae": object(), "clip_vision": object(),
        "reference_image": reference, "footage": footage, "prompt": "Appearance",
        "negative_prompt": "Artifacts", "steps": 2, "cfg": 1.0, "seed": 7,
        "chunk_frames": chunk_frames, "overlap_frames": 5, "max_side": 128,
        "shot_mode": "Manual cuts", "cut_frames": "21"}


class StreamingTests(unittest.TestCase):
    def test_same_stamp_mapped_cache_edit_rejected_before_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ("a" * 64 + ".pt")
            torch.save(data(3), path)
            footage, _ = artist.load_mapped_preparation(path, "a" * 64)
            provenance = footage["streaming_preparation"]
            delivery.verify_preparation_file(path, provenance)
            change_one_mapped_float(path)
            self.assertEqual(float(footage["frames"][0, 0, 0, 0]), .875)
            with self.assertRaisesRegex(ValueError, "bytes changed"):
                delivery.verify_preparation_file(path, provenance)
            # Check provenance after real encoded-file readback and before
            # os.replace. A stale receipt may never publish a successful MP4.
            with self.assertRaisesRegex(ValueError, "bytes changed"):
                with delivery.AtomicVideoWriter(tmp, "b" * 64, 3, 64, 64) as writer:
                    writer.write(data(3)["footage"]["frames"], 0)
                    writer.finish(before_publish=lambda: delivery.verify_preparation_file(path, provenance))
            self.assertFalse(writer.path.exists())
            self.assertFalse(writer.temporary.exists())

    def test_mmap_exact_fp32_and_no_fallback(self):
        original = data()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.pt"
            torch.save(original, path)
            real_load = torch.load
            with patch.object(artist.torch, "load", wraps=real_load) as load:
                footage, reference = artist.load_mapped_preparation(path, "a" * 64)
            self.assertEqual(load.call_args.kwargs, {"map_location": "cpu", "weights_only": True, "mmap": True})
            for key in ("frames", "character_mask", "pose_video", "face_video"):
                self.assertTrue(torch.equal(footage[key], original["footage"][key]))
                self.assertEqual(footage[key].dtype, torch.float32)
            self.assertTrue(torch.equal(reference, original["reference"]))
            # An independent mapping shares the backing file pointer, not an
            # eager clone of all tensors (MAP_PRIVATE mutations stay private).
            footage["frames"][0, 0, 0, 0] = .123
            reloaded = real_load(path, weights_only=True, mmap=True)
            self.assertTrue(torch.equal(reloaded["footage"]["frames"], original["footage"]["frames"]))
            # Permuted/sliced native IMAGE views remain exact too; the mmap
            # loader must not flatten or copy a complete strided clip.
            strided = data()
            strided["footage"]["face_video"] = strided["footage"]["face_video"].transpose(1, 2)
            strided_path = Path(tmp) / "strided.pt"
            torch.save(strided, strided_path)
            strided_footage, _ = artist.load_mapped_preparation(strided_path, "b" * 64)
            self.assertEqual(strided_footage["face_video"].stride(), strided["footage"]["face_video"].stride())
            self.assertTrue(torch.equal(strided_footage["face_video"], strided["footage"]["face_video"]))
            legacy = Path(tmp) / "legacy.pt"
            torch.save(original, legacy, _use_new_zipfile_serialization=False)
            with patch.object(artist.torch, "load") as load:
                with self.assertRaisesRegex(ValueError, "cannot be memory mapped"):
                    artist.load_mapped_preparation(legacy, "a" * 64)
                load.assert_not_called()

    def test_reject_corrupt_shapes_dtype_pixels_and_provenance(self):
        for mutate in (
                lambda x: x.update(version=2),
                lambda x: x["footage"].update(character_mask=torch.ones(2, 64, 64)),
                lambda x: x["footage"].update(frames=x["footage"]["frames"].half()),
                lambda x: x["footage"]["pose_video"].fill_(float("nan")),
                lambda x: x["footage"].update(speech_provenance={"guide_key": "a" * 64}),
                lambda x: x["footage"]["character_mask"].zero_(),
                lambda x: x["footage"].update(video_info={"fps": 25})):
            candidate = data()
            mutate(candidate)
            with self.assertRaises(ValueError):
                artist.validate_mapped_preparation(candidate)

    def test_writer_exact_timeline_and_raster(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = data(7)["footage"]["frames"]
            with delivery.AtomicVideoWriter(tmp, "b" * 64, 7, 64, 64) as writer:
                writer.write(frames[:3], 0)
                writer.write(frames[3:], 3)
                receipt = writer.finish()
            fps, output, audio = read(receipt["path"])
            self.assertEqual((fps, len(output), audio), (24, 7, 0))
            for index, (pixels, stamp) in enumerate(output):
                self.assertEqual(float(stamp), index / 24)
                self.assertEqual(pixels.shape, (64, 64, 3))
                self.assertLess(abs(float(pixels.mean()) / 255 - float(frames[index].mean())), .012)
            self.assertEqual(delivery.file_sha256(receipt["path"]), receipt["sha256"])
            self.assertFalse(writer.temporary.exists())

    def test_full_plan_native_ownership_and_cut_reset(self):
        # Synthetic decoded values identify both the originating window and
        # absolute timestamp. The old deferred-tail assembly and immediate
        # owned-span assembly must agree, including the genuine hard cut.
        for total, cuts in ((157, []), (570, [466]), (6, [1, 3]), (123, [9, 22])):
            plan = planning.plan_chunks(total, 81, 5, cuts, continuation=True)
            planning.validate_plan(plan, total)
            old, streamed, pending = [], [], None
            previous_shot = None
            for part in plan:
                if previous_shot != part.shot_index:
                    self.assertEqual(part.anchor_frames, 0)
                    self.assertIsNone(pending)
                if part.anchor_frames:
                    self.assertEqual(len(pending), part.anchor_frames)
                window = torch.arange(part.window_start, part.window_start + part.window_count) + part.index * 10000
                context = part.output_start - part.window_start
                streamed.append(window[context:context + part.output_count].clone())
                if pending is not None:
                    old.append(pending)
                old.append(window[context:part.window_count - part.blend_frames])
                pending = window[-part.blend_frames:].clone() if part.blend_frames else None
                previous_shot = part.shot_index
            self.assertTrue(torch.equal(torch.cat(old), torch.cat(streamed)))
            self.assertEqual(len(torch.cat(streamed)), total)

    def test_cancel_during_encoding_never_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = 0
            def cancel():
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise RuntimeError("interrupted")
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                with delivery.AtomicVideoWriter(tmp, "c" * 64, 7, 64, 64, interrupt=cancel) as writer:
                    writer.write(data(7)["footage"]["frames"], 0)
                    writer.finish()
            self.assertFalse(writer.path.exists())
            self.assertFalse(writer.temporary.exists())

    def test_cancel_during_readback_and_invalid_spans_never_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = 0
            def cancel():
                nonlocal calls
                calls += 1
                if calls == 6:
                    raise RuntimeError("verification interrupted")
            with self.assertRaisesRegex(RuntimeError, "verification interrupted"):
                with delivery.AtomicVideoWriter(tmp, "c" * 64, 3, 64, 64, interrupt=cancel) as writer:
                    writer.write(data(3)["footage"]["frames"], 0)
                    writer.finish()
            self.assertFalse(writer.path.exists())
            self.assertFalse(writer.temporary.exists())
            with self.assertRaises(ValueError):
                with delivery.AtomicVideoWriter(tmp, "c" * 64, 7, 64, 64) as writer:
                    writer.write(data(3)["footage"]["frames"], 1)
            self.assertFalse(writer.path.exists())
            self.assertFalse(writer.temporary.exists())
            with self.assertRaises(ValueError):
                with delivery.AtomicVideoWriter(tmp, "c" * 64, 7, 64, 64) as writer:
                    writer.write(data(3)["footage"]["frames"], 0)
                    writer.finish()
            self.assertFalse(writer.path.exists())
            self.assertFalse(writer.temporary.exists())

    def test_confined_paths_and_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                delivery.AtomicVideoWriter(tmp, "../escape", 1, 64, 64)
            # Simulate a directory junction resolving outside the output root;
            # its resolved target must be checked before any file is opened.
            with patch.object(delivery.Path, "resolve", side_effect=[Path(tmp), Path(tmp).parent]):
                with self.assertRaisesRegex(ValueError, "leaves the Comfy output"):
                    delivery.AtomicVideoWriter(tmp, "f" * 64, 1, 64, 64)

    @unittest.skipIf(InputImpl is None, "Set COMFYUI_ROOT to test real native VIDEO delivery")
    def test_shared_native_loop_old_and_streamed_own_same_frames(self):
        # Only native model, sampler and decoder calls are mocked. PyAV,
        # preparation, planner, tensor arithmetic and writer/readback are real.
        records = []
        class Native:
            def execute(self, *args, **kwargs):
                pose = kwargs["pose_video"]
                anchor = kwargs["continue_motion"]
                records.append({"pose": pose.clone(), "bg": kwargs["background_video"].clone(),
                    "mask": kwargs["character_mask"].clone(),
                    "anchor": None if anchor is None else anchor.clone()})
                output = pose.clone()
                if anchor is not None:
                    output[:len(anchor)] = (anchor + .03).clamp(0, 1)
                samples = output.permute(3, 0, 1, 2)[None]
                return "positive", "negative", {"samples": samples}, 0, 0 if anchor is None else len(anchor), None
        nodes = types.ModuleType("nodes")
        nodes.CLIPTextEncode = lambda: types.SimpleNamespace(encode=lambda *a: ("encoded",))
        nodes.CLIPVisionEncode = lambda: types.SimpleNamespace(encode=lambda *a: ("vision",))
        nodes.common_ksampler = lambda model, seed, steps, cfg, sampler, scheduler, p, n, latent: (latent,)
        nodes.VAEDecodeTiled = lambda: types.SimpleNamespace(decode=lambda vae, latent, **kwargs: (latent["samples"][0].permute(1, 2, 3, 0),))
        wan = types.ModuleType("comfy_extras.nodes_wan")
        wan.WanAnimateToVideo = Native
        management = types.ModuleType("comfy.model_management")
        management.throw_exception_if_processing_interrupted = lambda: None
        utils = types.ModuleType("comfy.utils")
        utils.ProgressBar = lambda count: types.SimpleNamespace(update=lambda count: None)
        modules = {"nodes": nodes, "comfy_extras.nodes_wan": wan,
                   "comfy.model_management": management, "comfy.utils": utils}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, modules):
            path = Path(tmp) / ("d" * 64 + ".pt")
            original = data(29)
            torch.save(original, path)
            footage, reference = artist.load_mapped_preparation(path, "d" * 64)
            kwargs = {"model": object(), "clip": object(), "vae": object(), "clip_vision": object(),
                "reference_image": reference, "footage": original["footage"], "prompt": "Appearance",
                "negative_prompt": "Artifacts", "chunk_frames": 13, "overlap_frames": 5,
                "shot_mode": "Manual cuts", "cut_frames": "21", "max_side": 1280}
            old_images, old_video, old_receipt = render.ZuraWan22LoopedChunksSampler().render(**kwargs)
            old_records = records[:]
            records.clear()
            kwargs["footage"] = footage
            folder = sys.modules["folder_paths"]
            with patch.object(folder, "get_output_directory", lambda: tmp, create=True):
                video, raw_receipt = render.ZuraWan22StreamedSampler().render(delivery_key="e" * 64, **kwargs)
            receipt = json.loads(raw_receipt)
            self.assertEqual(receipt["frame_plan"], json.loads(old_receipt)["frame_plan"])
            self.assertEqual(receipt["cuts"], [21])
            self.assertEqual(receipt["generated_frames"], 29)
            self.assertEqual(len(old_records), len(records))
            plan = planning.plan_chunks(29, 13, 5, [21], continuation=True)
            for part, old, new in zip(plan, old_records, records):
                for name in ("pose", "bg", "mask"):
                    self.assertTrue(torch.equal(old[name], new[name]))
                if part.anchor_frames:
                    self.assertTrue(torch.equal(old["anchor"], new["anchor"]))
                    self.assertEqual(len(new["anchor"]), 5)
                else:
                    self.assertIsNone(new["anchor"])
            self.assertIsInstance(video, InputImpl.VideoFromFile)
            fps, output, audio = read(video.get_stream_source())
            self.assertEqual((fps, len(output), audio), (24, 29, 0))
            for index, (pixels, _) in enumerate(output):
                self.assertLess(abs(float(pixels.mean()) / 255 - float(old_images[index].mean())), .012)
            self.assertTrue(receipt["streaming"])
            self.assertEqual(receipt["preparation"]["storage"], "torch_zip_mmap_float32")
            # The same-stamp mutation must fail before any prompt/model calls.
            original_bytes, original_stamp = path.read_bytes(), path.stat()
            change_one_mapped_float(path)
            records.clear()
            with patch.object(folder, "get_output_directory", lambda: tmp, create=True), \
                    patch.object(nodes, "CLIPTextEncode", wraps=nodes.CLIPTextEncode) as encode:
                with self.assertRaisesRegex(ValueError, "bytes changed"):
                    render.ZuraWan22StreamedSampler().render(delivery_key="f" * 64, **kwargs)
                encode.assert_not_called()
                self.assertEqual(records, [])
            restore_cache_copy(path, original_bytes, original_stamp)
            # A cache edit after sampling must also fail after real video
            # readback and before the writer's atomic publication operation.
            real_finish = delivery.AtomicVideoWriter.finish
            def finish_with_cache_mutation(writer, before_publish=None):
                def hook():
                    change_one_mapped_float(path)
                    before_publish()
                return real_finish(writer, before_publish=hook)
            existing_outputs = set((Path(tmp) / "genj" / "wan_streams").glob("*.mp4"))
            with patch.object(folder, "get_output_directory", lambda: tmp, create=True), \
                    patch.object(delivery.AtomicVideoWriter, "finish", finish_with_cache_mutation):
                with self.assertRaisesRegex(ValueError, "bytes changed"):
                    render.ZuraWan22StreamedSampler().render(delivery_key="f" * 64, **kwargs)
            self.assertEqual(set((Path(tmp) / "genj" / "wan_streams").glob("*.mp4")), existing_outputs)


class WindowBackedStreamingTests(unittest.TestCase):
    def _load(self, output_root, key, source, max_window_frames):
        path = save_window_cache(output_root, key, source)
        folder = sys.modules["folder_paths"]
        with patch.object(folder, "get_output_directory", lambda: str(output_root), create=True):
            footage, reference, width, height = windows.ZuraWanLoadWindowPreparation().load(
                key, max_window_frames=max_window_frames)
        self.assertEqual((width, height), (64, 64))
        return path, footage, reference

    def test_cached_builder_uses_window_loader_and_restores_original_soundtrack_once(self):
        # Exercise the no-replacement-audio/original-soundtrack studio route.
        # It must use the registered bounded loader and append one global audio
        # restore after the streamed, intentionally silent video file.
        fixtures = importlib.import_module("test_artist_studio")
        studio, wan = fixtures.studio, fixtures.wan
        folder = sys.modules["folder_paths"]
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "window-cache.pt"
            cache.touch()
            project = fixtures.SharedEngineTests().project()
            with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                    patch.object(wan, "cache_key", return_value="a" * 64), \
                    patch.object(wan, "cache_path", return_value=cache), \
                    patch.object(folder, "get_full_path", return_value="unused", create=True):
                graph = wan.build_wan_graph(project, use_cache=True)

        self.assertEqual(graph["wan_cached"]["class_type"], "ZuraWanLoadWindowPreparation")
        self.assertEqual(graph["wan_cached"]["inputs"]["max_window_frames"], 81)
        self.assertEqual(graph["wan_render"]["class_type"], "ZuraWan22StreamedSampler")
        self.assertEqual(graph["wan_render"]["inputs"]["footage"], ["wan_cached", 0])
        self.assertEqual(graph["wan_export"]["class_type"], "GenjRestoreSoundtrack")
        self.assertEqual(graph["wan_export"]["inputs"]["video"], ["wan_render", 0])
        self.assertEqual(graph["wan_export"]["inputs"]["clip_details"], ["wan_shot", 3])
        self.assertNotIn("wan_reference_audio", graph)
        registry = (Path(v2_bootstrap.ROOT) / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('"ZuraWanLoadWindowPreparation": ZuraWanLoadWindowPreparation', registry)

    def test_window_cache_loop_matches_image_sampler_cut_reset_pts_and_publication_guard(self):
        if InputImpl is None:
            self.skipTest("Set COMFYUI_ROOT to test real native VIDEO delivery")
        records, calls = [], {}
        modules = mock_wan_runtime(records, calls)
        original = data(29)
        key = "d" * 64
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, modules):
            cache, window_footage, reference = self._load(tmp, key, original, 13)
            self.assertTrue(all(isinstance(window_footage[name], windows.WindowArray)
                                for name in ("frames", "character_mask", "pose_video", "face_video")))
            self.assertEqual(window_footage["streaming_preparation"]["storage"],
                             "torch_zip_readonly_windows_float32")

            kwargs = stream_kwargs(original["footage"], original["reference"])
            old_images, _, old_receipt_text = render.ZuraWan22LoopedChunksSampler().render(**kwargs)
            old_receipt = json.loads(old_receipt_text)
            old_records = records[:]
            records.clear()
            calls.clear()
            kwargs["footage"] = window_footage
            folder = sys.modules["folder_paths"]
            with patch.object(folder, "get_output_directory", lambda: tmp, create=True):
                video, receipt_text = render.ZuraWan22StreamedSampler().render(
                    delivery_key="e" * 64, **kwargs)
            receipt = json.loads(receipt_text)
            new_records = records[:]

            self.assertEqual(receipt["frame_plan"], old_receipt["frame_plan"])
            self.assertEqual(receipt["cuts"], [21])
            self.assertEqual(receipt["generated_frames"], 29)
            self.assertEqual(receipt["audio_policy"], "restore_global_soundtrack_once")
            plan = planning.plan_chunks(29, 13, 5, [21], continuation=True)
            self.assertEqual(len(old_records), len(new_records))
            self.assertEqual(len(new_records), len(plan))
            saw_cut_reset = False
            for index, (part, old, new) in enumerate(zip(plan, old_records, new_records)):
                for name in ("pose", "bg", "mask"):
                    self.assertTrue(torch.equal(old[name], new[name]), (part.index, name))
                if part.anchor_frames:
                    self.assertEqual(len(new["anchor"]), 5)
                    self.assertTrue(torch.equal(old["anchor"], new["anchor"]))
                    self.assertTrue(torch.equal(new["anchor"], new_records[index - 1]["generated"][-5:]))
                else:
                    self.assertIsNone(old["anchor"])
                    self.assertIsNone(new["anchor"])
                    if part.window_start == 21:
                        saw_cut_reset = True
                if old["generated"] is not None:
                    self.assertTrue(torch.equal(old["generated"], new["generated"]))
            self.assertTrue(saw_cut_reset)

            self.assertIsInstance(video, InputImpl.VideoFromFile)
            fps, output, audio_tracks = read(video.get_stream_source())
            self.assertEqual((fps, len(output), audio_tracks), (24, 29, 0))
            for index, (pixels, stamp) in enumerate(output):
                self.assertEqual(float(stamp), index / 24)
                self.assertLess(abs(float(pixels.mean()) / 255 - float(old_images[index].mean())), .012)
            self.assertLessEqual(window_footage["frames"]._reader.stats["maximum_copy_bytes"],
                                 13 * 64 * 64 * 3 * 4)

            # A same-size, same-mtime edit to the actual windows cache must be
            # rejected before the prompt/model calls, leaving no output.
            original_bytes, original_stamp = cache.read_bytes(), cache.stat()
            before_outputs = set((Path(tmp) / "genj" / "wan_streams").glob("*.mp4"))
            change_one_mapped_float(cache)
            records.clear()
            calls.clear()
            with patch.object(folder, "get_output_directory", lambda: tmp, create=True), \
                    patch.object(delivery, "AtomicVideoWriter", wraps=delivery.AtomicVideoWriter) as writer:
                with self.assertRaisesRegex(ValueError, "bytes changed"):
                    render.ZuraWan22StreamedSampler().render(delivery_key="f" * 64, **kwargs)
                self.assertEqual(calls, {})
                self.assertEqual(records, [])
                writer.assert_not_called()
            restore_cache_copy(cache, original_bytes, original_stamp)

            # Recheck after actual encoded-file readback, immediately before
            # atomic publication. Failure must remove the partial MP4.
            real_finish = delivery.AtomicVideoWriter.finish
            def finish_with_cache_mutation(writer, before_publish=None):
                def hook():
                    change_one_mapped_float(cache)
                    before_publish()
                return real_finish(writer, before_publish=hook)
            with patch.object(folder, "get_output_directory", lambda: tmp, create=True), \
                    patch.object(delivery.AtomicVideoWriter, "finish", finish_with_cache_mutation):
                with self.assertRaisesRegex(ValueError, "bytes changed"):
                    render.ZuraWan22StreamedSampler().render(delivery_key="f" * 64, **kwargs)
            self.assertEqual(set((Path(tmp) / "genj" / "wan_streams").glob("*.mp4")), before_outputs)
            self.assertEqual(list((Path(tmp) / "genj" / "wan_streams").glob("*.partial.mp4")), [])
            restore_cache_copy(cache, original_bytes, original_stamp)

    def test_mixed_forged_and_undersized_window_readers_fail_before_model(self):
        records, calls = [], {}
        modules = mock_wan_runtime(records, calls)
        source = data(29)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, modules):
            _, first, reference = self._load(tmp, "a" * 64, source, 13)
            _, second, _ = self._load(tmp, "b" * 64, source, 13)
            _, undersized, _ = self._load(tmp, "c" * 64, source, 12)
            mixed = dict(first)
            mixed["pose_video"] = second["pose_video"]
            forged = dict(first)
            forged["streaming_preparation"] = dict(first["streaming_preparation"])
            forged["streaming_preparation"]["max_window_frames"] += 1
            cases = ((mixed, 13), (forged, 13), (undersized, 13))
            folder = sys.modules["folder_paths"]
            for bad_footage, chunk_frames in cases:
                with self.subTest(storage=bad_footage["streaming_preparation"]["storage"],
                                  bound=bad_footage["streaming_preparation"]["max_window_frames"]), \
                        patch.object(folder, "get_output_directory", lambda: tmp, create=True), \
                        patch.object(delivery, "AtomicVideoWriter", wraps=delivery.AtomicVideoWriter) as writer:
                    calls.clear()
                    records.clear()
                    kwargs = stream_kwargs(bad_footage, reference, chunk_frames=chunk_frames)
                    with self.assertRaisesRegex(ValueError, "verified window receipt"):
                        render.ZuraWan22StreamedSampler().render(delivery_key="f" * 64, **kwargs)
                    self.assertEqual(calls, {})
                    self.assertEqual(records, [])
                    writer.assert_not_called()

    def test_relaxed_part_arrays_cannot_reach_native_sampling(self):
        records, calls = [], {}
        modules = mock_wan_runtime(records, calls)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, modules):
            value = data(29)
            value["footage"]["character_mask"].zero_()
            path = Path(tmp) / ("a" * 64 + ".pt")
            torch.save(value, path)
            reader = windows.WanPreparationWindows(path, "a" * 64, tmp,
                                                  max_window_frames=13, require_nonempty_mask=False)
            media = dict(reader.metadata)
            media.update({name: reader.arrays[name] for name in windows.TENSOR_NAMES[:-1]})
            media["streaming_preparation"] = reader.provenance
            reader.require_nonempty_mask = True
            folder = sys.modules["folder_paths"]
            with patch.object(folder, "get_output_directory", lambda: tmp, create=True), \
                    patch.object(delivery, "AtomicVideoWriter", wraps=delivery.AtomicVideoWriter) as writer:
                with self.assertRaisesRegex(ValueError, "merged"):
                    render.ZuraWan22StreamedSampler().render(delivery_key="f" * 64,
                        **stream_kwargs(media, value["reference"], chunk_frames=13))
                self.assertEqual(calls, {})
                self.assertEqual(records, [])
                writer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
