"""Standalone tests for the v2 looped chunk renderer."""
from __future__ import annotations

import json
import math
import sys
import types
import unittest
from unittest.mock import patch

import v2_bootstrap  # noqa: F401
from ComfyUI_zura_nodes import render as render_module

import torch


def install_fake_native(calls, crops):
    nodes = types.ModuleType("nodes")
    nodes.CLIPTextEncode = type("T", (), {"encode": lambda s, c, t: ([t],)})
    nodes.CLIPVisionEncode = type("V", (), {"encode": lambda s, c, i, crop: (crops.append(crop) or "vision",)})
    nodes.common_ksampler = lambda *args: (args[-1],)

    class Decode:
        def decode(self, vae, value, **kwargs):
            return (torch.zeros(((int(value['samples'].shape[2]) - 1) * 4 + 1, 1, 1, 3)),)

    nodes.VAEDecodeTiled = Decode
    wanmod = types.ModuleType("comfy_extras.nodes_wan")

    class Native:
        def execute(self, positive, negative, vae, width, height, length, batch_size,
                    continue_motion_max_frames, video_frame_offset, reference_image=None,
                    clip_vision_output=None, face_video=None, pose_video=None,
                    continue_motion=None, background_video=None, character_mask=None):
            calls.append({"offset": video_frame_offset, "continue": continue_motion, "pose": pose_video,
                          "face": face_video, "background": background_video, "mask": character_mask,
                          "max_frames": continue_motion_max_frames})
            # Mimic the native node: trim_image reports how many leading frames
            # reproduce the continue_motion context.
            trim_image = int(continue_motion.shape[0]) if continue_motion is not None else 0
            return (positive, negative, {"samples": torch.zeros((1, 1, (length - 1) // 4 + 2, 1, 1))},
                    1, trim_image, 0)

    native = Native()
    wanmod.WanAnimateToVideo = lambda: native
    extras = types.ModuleType("comfy_extras")
    extras.__path__ = []
    old = {k: sys.modules.get(k) for k in ("nodes", "comfy_extras", "comfy_extras.nodes_wan")}
    sys.modules.update({"nodes": nodes, "comfy_extras": extras, "comfy_extras.nodes_wan": wanmod})
    return old, native


class RenderTests(unittest.TestCase):
    def make_media(self, total=100):
        frames = torch.arange(total, dtype=torch.float32).view(total, 1, 1, 1).expand(-1, -1, -1, 3)
        mask = torch.ones((total, 1, 1))
        audio = {"sample_rate": 32000, "waveform": torch.ones((1, 2, round(total / 24 * 32000)))}
        return {"frames": frames, "pose_video": frames, "face_video": frames, "character_mask": mask,
                "audio": audio, "keep_audio": True, "video_info": {"fps": 24},
                "replacement_area": "Whole character"}

    def test_renderer_windows_trims_and_assembles_video(self):
        calls, crops, events = [], [], []
        old_send = render_module._send_wan22_progress
        render_module._send_wan22_progress = lambda **data: events.append(data)
        old_modules, _ = install_fake_native(calls, crops)
        try:
            media = self.make_media()
            node = render_module.ZuraWan22LoopedChunksSampler()
            images, video, receipt = node.render(
                "m", "c", "v", "cv", media["frames"][:1], media, "p", "n", steps=6, cfg=1.0,
                chunk_frames=41, max_side=16, overlap_frames=5, shot_mode="Manual cuts",
                cut_frames="50", unique_id="77:1")
            self.assertEqual(len(calls), 4)
            self.assertEqual(crops, ["none"])
            self.assertEqual([(c["pose"].shape[0], c["pose"][0, 0, 0, 0].item()) for c in calls],
                             [(41, 0), (17, 36), (41, 50), (17, 86)])
            # Native continuation: each chunk after a shot's first is handed
            # the predecessor's real output tail as continue_motion, and never
            # across the cut at frame 50.
            self.assertEqual([0 if c["continue"] is None else int(c["continue"].shape[0]) for c in calls],
                             [0, 5, 0, 5])
            self.assertEqual([c["max_frames"] for c in calls], [1, 5, 1, 5])
            # Continuation windows begin at the predecessor's tail (absolute
            # frames 36..49 and 86..99 for the cut-at-50 plan).
            self.assertEqual([c["pose"].shape[0] for c in calls], [41, 17, 41, 17])
            # Every window is still sampled with source conditioning.
            self.assertTrue(all(c["pose"] is not None and c["background"] is not None for c in calls))
            self.assertEqual(images.shape[0], 100)
            self.assertIsNotNone(calls[0]["mask"])
            # Built-in audio assembly: exact frame count and source audio kept.
            components = video if isinstance(video, dict) else video.get_components()
            self.assertEqual(int(components["images"].shape[0]), 100)
            self.assertIsNotNone(components["audio"])
            self.assertTrue(torch.equal(components["audio"]["waveform"], media["audio"]["waveform"]))
            self.assertEqual(components["frame_rate"].numerator, 24)
            receipt_data = json.loads(receipt)
            self.assertEqual(receipt_data["generated_frames"], 100)
            self.assertEqual(receipt_data["cuts"], [50])
            self.assertEqual(receipt_data["shots"], [[0, 50], [50, 100]])
            self.assertEqual(receipt_data["continuation"]["frames"], 5)
            self.assertIn("max_delta", receipt_data["continuation"])
            self.assertEqual([e['completed_frames'] for e in events if e['state'] == 'chunk_completed'], [41, 50, 91, 100])
            self.assertEqual(events[-1]['state'], 'completed')
        finally:
            render_module._send_wan22_progress = old_send
            for k, v in old_modules.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    def test_muted_audio_omits_audio_components(self):
        calls, crops = [], []
        old_send = render_module._send_wan22_progress
        render_module._send_wan22_progress = lambda **data: None
        old_modules, _ = install_fake_native(calls, crops)
        try:
            media = self.make_media(total=45)
            media["keep_audio"] = False
            _, video, _ = render_module.ZuraWan22LoopedChunksSampler().render(
                "m", "c", "v", "cv", media["frames"][:1], media, "p", "n", chunk_frames=41,
                max_side=16, overlap_frames=5, shot_mode="Continuous")
            components = video if isinstance(video, dict) else video.get_components()
            self.assertIsNone(components["audio"])
        finally:
            render_module._send_wan22_progress = old_send
            for k, v in old_modules.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    def test_background_conditioning_blacks_out_the_performer(self):
        calls, crops = [], []
        old_send = render_module._send_wan22_progress
        render_module._send_wan22_progress = lambda **data: None
        old_modules, _ = install_fake_native(calls, crops)
        try:
            media = self.make_media(total=10)
            media["character_mask"] = torch.zeros((10, 4, 4))
            media["character_mask"][:, 1:3, 1:3] = 1
            media["frames"] = torch.ones((10, 4, 4, 3))
            media["pose_video"] = torch.ones((10, 4, 4, 3))
            media["face_video"] = torch.ones((10, 4, 4, 3))
            render_module.ZuraWan22LoopedChunksSampler().render(
                "m", "c", "v", "cv", torch.ones((1, 4, 4, 3)), media, "p", "n", chunk_frames=9,
                max_side=16, overlap_frames=1, shot_mode="Continuous")
            background = calls[0]["background"]
            self.assertEqual(float(background[:, 1:3, 1:3].max()), 0.0, "performer pixels must be removed")
            self.assertEqual(float(background[:, 0, 0].max()), 1.0, "background pixels must be preserved")
        finally:
            render_module._send_wan22_progress = old_send
            for k, v in old_modules.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    def test_head_scope_prefixes_the_prompt(self):
        calls, crops = [], []
        old_send = render_module._send_wan22_progress
        render_module._send_wan22_progress = lambda **data: None
        old_modules, _ = install_fake_native(calls, crops)
        try:
            media = self.make_media(total=10)
            media["replacement_area"] = "Whole head"
            seen = {}

            class TextEncode:
                def encode(self, clip, text):
                    seen.setdefault("prompts", []).append(text)
                    return ([text],)

            sys.modules["nodes"].CLIPTextEncode = TextEncode
            render_module.ZuraWan22LoopedChunksSampler().render(
                "m", "c", "v", "cv", media["frames"][:1], media, "keep the scene", "n",
                chunk_frames=9, max_side=16, overlap_frames=1, shot_mode="Continuous")
            positive = seen["prompts"][0]
            self.assertIn("head, face and hair", positive)
            self.assertIn("keep the scene", positive)
        finally:
            render_module._send_wan22_progress = old_send
            for k, v in old_modules.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    def test_missing_conditioning_fails_fast(self):
        media = self.make_media(total=10)
        del media["pose_video"]
        with self.assertRaisesRegex(ValueError, "Zura Mask"):
            render_module.ZuraWan22LoopedChunksSampler().render(
                "m", "c", "v", "cv", media["frames"][:1], media, "p", "n", shot_mode="Continuous")

    def test_face_video_512_crops_pass_when_clip_is_smaller(self):
        """WanAnimatePreprocess always returns 512x512 face crops; the native
        node upscales pose/face conditioning itself, so a size mismatch must
        never abort the render."""
        calls, crops = [], []
        old_send = render_module._send_wan22_progress
        render_module._send_wan22_progress = lambda **data: None
        old_modules, _ = install_fake_native(calls, crops)
        try:
            media = self.make_media(total=10)
            media["frames"] = torch.ones((10, 4, 4, 3))
            media["pose_video"] = torch.ones((10, 4, 4, 3))
            media["face_video"] = torch.full((10, 512, 512, 3), 0.5)
            media["character_mask"] = torch.ones((10, 4, 4))
            render_module.ZuraWan22LoopedChunksSampler().render(
                "m", "c", "v", "cv", media["frames"][:1], media, "p", "n", chunk_frames=9,
                max_side=16, overlap_frames=1, shot_mode="Continuous")
            self.assertEqual(len(calls), 2)
            self.assertEqual(tuple(calls[0]["face"].shape), (9, 512, 512, 3))
        finally:
            render_module._send_wan22_progress = old_send
            for k, v in old_modules.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    def test_mask_size_mismatch_is_still_rejected(self):
        """The mask is combined with the frames arithmetically, so it alone
        must match the driving clip resolution."""
        media = self.make_media(total=10)
        media["character_mask"] = torch.ones((10, 8, 8))
        with self.assertRaisesRegex(ValueError, "character_mask must match the footage"):
            render_module.ZuraWan22LoopedChunksSampler().render(
                "m", "c", "v", "cv", media["frames"][:1], media, "p", "n", shot_mode="Continuous")

    def test_invalid_chunk_geometry_is_rejected(self):
        calls, crops = [], []
        old_send = render_module._send_wan22_progress
        render_module._send_wan22_progress = lambda **data: None
        old_modules, _ = install_fake_native(calls, crops)
        try:
            media = self.make_media(total=10)
            with self.assertRaisesRegex(ValueError, r"overlap_frames must be 4n\+1"):
                render_module.ZuraWan22LoopedChunksSampler().render(
                    "m", "c", "v", "cv", media["frames"][:1], media, "p", "n",
                    chunk_frames=5, overlap_frames=5, max_side=16, shot_mode="Continuous")
        finally:
            render_module._send_wan22_progress = old_send
            for k, v in old_modules.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v


def install_value_native(calls):
    """Native shim whose decode returns per-chunk distinct pixel values so
    blend tests can verify exact cross-fade arithmetic with pixel checks.

    The k-th window renders absolute frame i as value ``i + w_k * 100`` where
    ``w_k`` is the k-th chunk's window_start from the real planner.
    """
    nodes = types.ModuleType("nodes")
    nodes.CLIPTextEncode = type("T", (), {"encode": lambda s, c, t: ([t],)})
    nodes.CLIPVisionEncode = type("V", (), {"encode": lambda s, c, i, crop: ("vision",)})
    nodes.common_ksampler = lambda *args: (args[-1],)

    state = {"plan": [], "decode_index": -1}

    class Decode:
        def decode(self, vae, value, **kwargs):
            count = (int(value['samples'].shape[2]) - 1) * 4 + 1
            state["decode_index"] += 1
            base = 100.0 * state["plan"][state["decode_index"]] if state["plan"] else 0.0
            vals = base + torch.arange(count, dtype=torch.float32)
            return (vals.view(count, 1, 1, 1).expand(-1, 1, 1, 3),)

    nodes.VAEDecodeTiled = Decode
    wanmod = types.ModuleType("comfy_extras.nodes_wan")

    class Native:
        def execute(self, positive, negative, vae, width, height, length, batch_size,
                    continue_motion_max_frames, video_frame_offset, reference_image=None,
                    clip_vision_output=None, face_video=None, pose_video=None,
                    continue_motion=None, background_video=None, character_mask=None):
            calls.append({"length": length, "continue": continue_motion})
            trim_image = int(continue_motion.shape[0]) if continue_motion is not None else 0
            return (positive, negative, {"samples": torch.zeros((1, 1, (length - 1) // 4 + 2, 1, 1))},
                    1, trim_image, 0)

    native = Native()
    wanmod.WanAnimateToVideo = lambda: native
    extras = types.ModuleType("comfy_extras")
    extras.__path__ = []
    old = {k: sys.modules.get(k) for k in ("nodes", "comfy_extras", "comfy_extras.nodes_wan")}
    sys.modules.update({"nodes": nodes, "comfy_extras": extras, "comfy_extras.nodes_wan": wanmod})

    real_plan = render_module.plan_chunks

    def tracking_plan(*args, **kwargs):
        plan = real_plan(*args, **kwargs)
        state["plan"] = [p.window_start for p in plan]
        state["decode_index"] = -1
        return plan

    render_module.plan_chunks = tracking_plan

    def restore():
        for k, v in old.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        render_module.plan_chunks = real_plan

    return restore, native, state


class BlendAssemblyTests(unittest.TestCase):
    def render_two_chunks(self):
        calls, events = [], []
        old_send = render_module._send_wan22_progress
        render_module._send_wan22_progress = lambda **data: events.append(data)
        restore, _, _ = install_value_native(calls)
        try:
            total = 50
            frames = torch.zeros((total, 4, 4, 3))
            mask = torch.ones((total, 4, 4))
            media = {"frames": frames, "pose_video": frames, "face_video": frames,
                     "character_mask": mask, "keep_audio": False, "video_info": {"fps": 24},
                     "replacement_area": "Whole character"}
            images, _, receipt = render_module.ZuraWan22LoopedChunksSampler().render(
                "m", "c", "v", "cv", frames[:1], media, "p", "n", chunk_frames=41,
                max_side=16, overlap_frames=5, shot_mode="Continuous", unique_id="9:9")
            return images, calls
        finally:
            render_module._send_wan22_progress = old_send
            restore()

    def test_continuation_anchor_is_the_predecessors_real_frames(self):
        images, calls = self.render_two_chunks()
        # The second chunk must be told to continue from exactly the frames the
        # first one emitted, and the first chunk of the clip has nothing to
        # continue from.
        self.assertIsNone(calls[0]["continue"])
        anchor = calls[1]["continue"]
        self.assertIsNotNone(anchor, "the successor must receive the predecessor's tail")
        self.assertEqual(int(anchor.shape[0]), 5)
        self.assertTrue(torch.allclose(anchor[:, 0, 0, 0], torch.arange(36.0, 41.0)),
                        "the anchor must be the shared absolute frames, not a re-render")
        self.assertEqual(tuple(images.shape), (50, 1, 1, 3))

    def test_anchors_chain_chunk_to_chunk_in_one_shot(self):
        """Every chunk hands its tail to the next, and the native trim_image
        frames are kept as the blend zone rather than dropped."""
        calls, events = [], []
        old_send = render_module._send_wan22_progress
        render_module._send_wan22_progress = lambda **data: events.append(data)
        restore, _, _ = install_value_native(calls)
        try:
            total = 100
            frames = torch.zeros((total, 4, 4, 3))
            media = {"frames": frames, "pose_video": frames, "face_video": frames,
                     "character_mask": torch.ones((total, 4, 4)), "keep_audio": False,
                     "video_info": {"fps": 24}, "replacement_area": "Whole character"}
            images, _, receipt = render_module.ZuraWan22LoopedChunksSampler().render(
                "m", "c", "v", "cv", frames[:1], media, "p", "n", chunk_frames=41,
                max_side=16, overlap_frames=5, shot_mode="Continuous", unique_id="4:4")
            self.assertEqual(tuple(images.shape), (100, 1, 1, 3))
            # Windows 0..41, 36..77 and 72..100 (a 28-frame tail padded to 29).
            self.assertEqual([c["length"] for c in calls], [41, 41, 29])
            self.assertEqual([0 if c["continue"] is None else int(c["continue"].shape[0]) for c in calls],
                             [0, 5, 5])
            # Chunk B renders window position k (absolute 36+k) as 3600+k, so
            # the tail it hands on is its rendition of absolute 72..76.
            self.assertTrue(torch.allclose(calls[1]["continue"][:, 0, 0, 0], torch.arange(36.0, 41.0)))
            self.assertTrue(torch.allclose(calls[2]["continue"][:, 0, 0, 0], 3600.0 + torch.arange(36.0, 41.0)))
            receipt_data = json.loads(receipt)
            self.assertEqual(receipt_data["shots"], [[0, 100]])
            self.assertEqual([t["continue_frames"] for t in receipt_data["chunk_timings"]], [0, 5, 5])
            # The shim renders each window with a different constant so the
            # measured continuation disagreement is large and must be reported.
            self.assertGreater(receipt_data["continuation"]["max_delta"], 0.0)
        finally:
            render_module._send_wan22_progress = old_send
            restore()

    def test_shared_zone_is_cross_faded_not_snapped(self):
        images, calls = self.render_two_chunks()
        # 14-frame window padded to Wan's 4n+1 boundary (17 sampling frames).
        self.assertEqual([c["length"] for c in calls], [41, 17])
        # Chunk A (window 0..41) renders absolute frame i as value i.
        # Chunk B (window 36..50) renders window position k (absolute 36+k)
        # as value 3600+k, i.e. its rendition of absolute frame i is 3600+i-36.
        # The shared zone (absolute 36..41) must be a ramped mix of the two
        # renditions: exactly the neighbour's rendition at the flat ends and
        # a strict mix in between.
        self.assertEqual(tuple(images.shape), (50, 1, 1, 3))
        zone_a = torch.arange(36, 41, dtype=torch.float32)
        zone_b = 3600.0 + torch.arange(5, dtype=torch.float32)  # window positions 0..4
        zone = images[36:41, 0, 0, 0]
        # Flat-ended ramp: the zone's first frame is exactly chunk A's pure
        # rendition (zero step against the neighbour) and its last frame is
        # exactly chunk B's pure rendition; everything between is a strict mix.
        self.assertEqual(float(zone[0]), float(zone_a[0]))
        self.assertEqual(float(zone[-1]), float(zone_b[4]))
        self.assertTrue(torch.all(zone[1:-1] > torch.minimum(zone_a, zone_b)[1:-1]))
        self.assertTrue(torch.all(zone[1:-1] < torch.maximum(zone_a, zone_b)[1:-1]))
        # Ramp is strictly monotonic towards chunk B's rendition.
        self.assertTrue(torch.all((zone[1:] - zone[:-1]) > 0))
        self.assertGreater(float(zone[-1] - zone[0]), 1000.0)
        # Outside the zone: pure chunk renditions, no blending residue.
        self.assertEqual(float(images[35, 0, 0, 0]), 35.0)
        self.assertEqual(float(images[41, 0, 0, 0]), 3605.0)

    def test_blend_weights_are_flat_ended_and_monotonic(self):
        w = render_module._blend_weights(9)
        self.assertAlmostEqual(float(w[0]), 0.0, places=6)
        self.assertTrue(torch.all(w[1:] >= w[:-1]))
        self.assertAlmostEqual(float(w[-1]), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
