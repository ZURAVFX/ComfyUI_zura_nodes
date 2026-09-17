"""Standalone tests for the Zura Mask node."""
from __future__ import annotations

import types
import unittest
from unittest.mock import patch

import v2_bootstrap  # noqa: F401
from ComfyUI_zura_nodes import mask_performer, video as video_module

import torch


def fake_pose_data(faces):
    return {"pose_metas_original": [{"keypoints_face": face, "keypoints_body": None} for face in faces]}


class BlockifyTests(unittest.TestCase):
    def test_blockify_quantises_and_preserves_foreground(self):
        # An L-shaped mask (arm + leg) so block quantisation actually changes
        # the silhouette, not just a solid rectangle.
        mask = torch.zeros((1, 64, 64))
        mask[:, 20:30, 20:45] = 1   # arm
        mask[:, 30:55, 20:30] = 1   # leg
        original = float(mask.sum())
        result = mask_performer._blockify(mask, 10)
        self.assertEqual(tuple(result.shape), (1, 64, 64))
        values = torch.unique(result)
        self.assertTrue(all(float(v) in (0.0, 1.0) for v in values))
        # Never erases foreground, quantised in blocks (grows the silhouette).
        self.assertGreaterEqual(float(result.sum()), original)
        # Exact KJNodes bbox-grid arithmetic for block_size 10 on a 35x25 bbox:
        # 2x3 block grid of 12x11 blocks; the corner remainder rows/cols clamp
        # into the last block.  Blocks on: (0,0),(0,1),(1,0),(2,0).
        self.assertAlmostEqual(float(result.sum()), 132 + 143 + 132 + 156, places=3)
        # Coarser blocks quantify more aggressively.
        self.assertGreater(float(mask_performer._blockify(mask, 25).sum()), float(result.sum()))

    def test_blockify_never_erases_or_overgrows(self):
        torch.manual_seed(0)
        mask = (torch.rand((3, 48, 48)) > 0.7).float()
        fine = mask_performer._blockify_internal(mask, 8)
        coarse = mask_performer._blockify_internal(mask, 32)
        # Every original pixel survives.
        self.assertTrue(torch.all(fine[mask > 0] > 0))
        # Nothing turns on outside each frame's bounding box.
        for index in range(3):
            frame = mask[index] > 0
            y_idx = torch.nonzero(frame.any(dim=1), as_tuple=True)[0]
            x_idx = torch.nonzero(frame.any(dim=0), as_tuple=True)[0]
            y_min, y_max = int(y_idx[0]), int(y_idx[-1])
            x_min, x_max = int(x_idx[0]), int(x_idx[-1])
            outside = fine[index].clone()
            outside[y_min:y_max + 1, x_min:x_max + 1] = 0
            self.assertEqual(float(outside.abs().sum()), 0.0, f"frame {index} grew outside its bbox")
        # Finer blocks always fit tighter than (or equal) coarser ones.
        self.assertLessEqual(float(fine.sum()), float(coarse.sum()))

    def test_blockify_matches_kjnodes_when_available(self):
        kj = types.ModuleType("kjnodes_stub")

        class BlockifyMask:
            FUNCTION = "process"
            called = False

            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {"masks": ("MASK",), "block_size": ("INT", {"default": 32}), "device": (["cpu", "gpu"], {"default": "cpu"})}}

            def process(self, masks, block_size=32, device="cpu"):
                BlockifyMask.called = True
                import torch.nn.functional as F
                b = int(block_size)
                blocks = F.max_pool2d(masks[:, None], b, stride=b)
                out = F.interpolate(blocks, scale_factor=b, mode="nearest")
                return (out[:, 0],)

        kj.BlockifyMask = BlockifyMask
        fake_nodes = types.ModuleType("nodes")
        fake_nodes.NODE_CLASS_MAPPINGS = {"BlockifyMask": BlockifyMask}
        with patch.dict("sys.modules", {"nodes": fake_nodes}):
            mask = torch.zeros((1, 64, 64))
            mask[:, 10:40, 12:44] = 1
            result = mask_performer._blockify(mask, 32)
        self.assertTrue(BlockifyMask.called)
        self.assertTrue(torch.equal(result, BlockifyMask().process(mask, 32)[0]))

    def test_blockify_size_one_is_identity_for_binary_masks(self):
        mask = (torch.rand((1, 16, 16)) > 0.5).float()
        self.assertTrue(torch.equal(mask_performer._blockify(mask, 1), mask))

    def test_block_size_widget_matches_kjnodes_range(self):
        widget = mask_performer.ZuraMask.INPUT_TYPES()["required"]["block_size"]
        self.assertEqual(widget[0], "INT")
        self.assertEqual(widget[1]["min"], 8)
        self.assertEqual(widget[1]["max"], 512)
        self.assertEqual(widget[1]["step"], 1)
        self.assertEqual(widget[1]["default"], 32)

    def test_prepare_rejects_out_of_range_block_size(self):
        frames = torch.zeros((1, 8, 8, 3))
        with self.assertRaisesRegex(ValueError, "between 8 and 512"):
            mask_performer.ZuraMask().prepare(
                {"frames": frames, "video_info": {"fps": 24}}, blockify_mask=True, block_size=4)


class HeadMaskTests(unittest.TestCase):
    def test_face_only_matches_v1_profile(self):
        person = torch.ones((1, 40, 40))
        face = [[.40, .35, .95], [.60, .35, .95], [.50, .55, .95]]
        result = mask_performer._head_mask_from_pose(fake_pose_data([face]), person, area="Face only")
        whole = mask_performer._head_mask_from_pose(fake_pose_data([face]), person, area="Whole head")
        self.assertGreater(float(result.sum()), 0)
        # Whole head strictly covers more than the face-only ellipse.
        self.assertGreater(float(whole.sum()), float(result.sum()))
        self.assertTrue(torch.all(whole[0] >= result[0] - 1e-6))

    def test_whole_head_covers_above_the_brow_for_hair(self):
        # Face landmarks span rows 14-22 of 40; hair lives above the brow line.
        person = torch.ones((1, 40, 40))
        face = [[.40, .35, .95], [.60, .35, .95], [.50, .55, .95]]
        face_only = mask_performer._head_mask_from_pose(fake_pose_data([face]), person, area="Face only")
        whole = mask_performer._head_mask_from_pose(fake_pose_data([face]), person, area="Whole head")
        hair_band = whole[0, 8:13, :] - face_only[0, 8:13, :]
        self.assertGreater(float(hair_band.sum()), 0, "whole head must reach above the face ellipse")

    def test_whole_head_is_cut_at_the_neck(self):
        person = torch.ones((1, 40, 40))
        face = [[.40, .35, .95], [.60, .35, .95], [.50, .55, .95]]
        body = [[0, 0, 0.0] for _ in range(18)]
        body[1] = [.50, .72, .9]  # neck below the jaw
        meta = {"keypoints_face": face, "keypoints_body": body}
        result = mask_performer._head_mask_from_pose({"pose_metas_original": [meta]}, person, area="Whole head")
        self.assertEqual(float(result[0, 30:, :].sum()), 0, "torso below the neck must stay out of the mask")

    def test_missing_landmarks_fail_loudly(self):
        person = torch.ones((1, 12, 12))
        with self.assertRaisesRegex(RuntimeError, "face/head landmarks"):
            mask_performer._head_mask_from_pose(fake_pose_data([[["x"]]]), person, area="Whole head")

    def test_rear_facing_ears_get_head_height(self):
        body = [[0, 0, 0.0] for _ in range(18)]
        body[14] = [.40, .40, .9]
        body[15] = [.60, .40, .9]
        meta = {"keypoints_face": [], "keypoints_body": body}
        result = mask_performer._head_mask_from_pose({"pose_metas_original": [meta]}, torch.ones((1, 20, 20)), area="Whole head")
        ys = torch.where(result[0] > 0)[0]
        self.assertGreater(int(result.sum()), 10)
        self.assertLess(int(ys.min()), 8)


class PrepareTests(unittest.TestCase):
    def make_frames(self, count=2, side=8):
        return torch.zeros((count, side, side, 3))

    @staticmethod
    def video(frames, audio=None, fps=24):
        """An ordinary VIDEO wire, exactly what Zura Load Video emits."""
        return video_module.video_output(frames, audio, fps)

    def patch_detection(self, mask):
        return patch.multiple(mask_performer, detect=lambda frame, previous=None: (mask, [1, 1, 3, 3]),
                              _run_pose_face=lambda media, boxes: {"pose_video": "pose", "face_video": "face",
                                                                              "character_mask": mask,
                                                                              "pose_data": fake_pose_data([
                                                                                  [[.4, .3, .9], [.6, .3, .9], [.5, .5, .9]]] * len(media["frames"]))})

    def test_prepare_returns_preview_footage_and_mask(self):
        frames = self.make_frames()
        mask = torch.zeros((8, 8))
        mask[2:6, 2:6] = 1
        with self.patch_detection(mask):
            preview, media, mask_out = mask_performer.ZuraMask().prepare(
                self.video(frames), replacement_area="Whole character",
                mask_expansion=0, blockify_mask=False)
        self.assertTrue(torch.equal(media["character_mask"], torch.stack([mask, mask])))
        self.assertEqual(media["replacement_area"], "Whole character")
        # The pure mask leaves on a native MASK slot and is exactly the mask the
        # renderer conditions on.
        self.assertEqual(mask_out.ndim, 3)
        self.assertTrue(torch.equal(mask_out, media["character_mask"]))
        # The character reference no longer travels with the payload.
        self.assertNotIn("character_reference", media)
        # Mask preview is a VIDEO-shaped payload (dict fallback without ComfyUI).
        self.assertTrue(isinstance(preview, dict) and "images" in preview or hasattr(preview, "get_components"))
        # background video is the performer-removed driving clip.
        self.assertTrue(torch.equal(media["background_video"][:, 2:6, 2:6], torch.zeros(2, 4, 4, 3)))

    def test_blockify_runs_before_conditioning_when_enabled(self):
        frames = self.make_frames()
        mask = torch.zeros((8, 8))
        mask[2:6, 2:6] = 1
        seen = {}

        def fake_pose_face(media, boxes):
            seen["mask_at_conditioning"] = None
            return {"pose_video": "pose", "face_video": "face",
                    "pose_data": fake_pose_data([[[.4, .3, .9], [.6, .3, .9], [.5, .5, .9]]] * len(media["frames"]))}

        with patch.multiple(mask_performer, detect=lambda frame, previous=None: (mask, [1, 1, 3, 3]),
                            _run_pose_face=fake_pose_face):
            _, media, _ = mask_performer.ZuraMask().prepare(
                self.video(frames), replacement_area="Whole character",
                mask_expansion=0, blockify_mask=True, block_size=8)
        values = torch.unique(media["character_mask"])
        self.assertTrue(all(float(v) in (0.0, 1.0) for v in values))

    def test_head_areas_use_pose_landmarks_and_keep_background(self):
        frames = self.make_frames()
        mask = torch.ones((8, 8))
        with self.patch_detection(mask):
            _, media, _ = mask_performer.ZuraMask().prepare(
                self.video(frames), replacement_area="Whole head",
                mask_expansion=0, blockify_mask=False)
        self.assertEqual(media["replacement_area"], "Whole head")
        self.assertLess(float(media["character_mask"].sum()), float(mask.sum()) * len(frames),
                        "head mask must be smaller than the full body mask")

    def test_mask_is_foreground_one(self):
        frames = self.make_frames()
        mask = torch.zeros((8, 8))
        mask[2:6, 2:6] = 1
        with self.patch_detection(mask):
            _, media, _ = mask_performer.ZuraMask().prepare(
                self.video(frames), mask_expansion=0, blockify_mask=False)
        self.assertEqual(float(media["character_mask"].max()), 1.0)

    def test_accepts_a_video_wire_from_anywhere(self):
        """The input is a plain VIDEO, so any pack's decode can feed it."""
        class ForeignVideo:
            def get_components(self):
                return {"images": torch.zeros((2, 8, 8, 3)), "audio": None, "frame_rate": 25}

        mask = torch.zeros((8, 8))
        mask[2:6, 2:6] = 1
        with self.patch_detection(mask):
            _, media, _ = mask_performer.ZuraMask().prepare(ForeignVideo(), mask_expansion=0,
                                                            blockify_mask=False)
        self.assertEqual(media["video_info"]["fps"], 25.0)

    def test_audio_and_frame_rate_travel_into_the_payload(self):
        frames = self.make_frames()
        audio = {"sample_rate": 32000, "waveform": torch.zeros((1, 2, 2000))}
        mask = torch.zeros((8, 8))
        mask[2:6, 2:6] = 1
        with self.patch_detection(mask):
            preview, media, _ = mask_performer.ZuraMask().prepare(
                self.video(frames, audio, 24), mask_expansion=0, blockify_mask=False)
        self.assertTrue(media["keep_audio"])
        self.assertEqual(media["audio"]["sample_rate"], 32000)
        self.assertEqual(media["video_info"]["fps"], 24.0)
        # The control preview stays a video wire too.
        self.assertEqual(int(video_module.video_components(preview)[2]), 24)


class InterfaceTests(unittest.TestCase):
    """The node surface the user sees: a video in, three outputs out."""

    def test_inputs_are_video_and_mask_controls_only(self):
        required = mask_performer.ZuraMask.INPUT_TYPES()["required"]
        self.assertEqual(list(required), ["video", "replacement_area", "mask_expansion",
                                          "blockify_mask", "block_size"])
        self.assertEqual(required["video"][0], "VIDEO")

    def test_outputs_are_preview_footage_and_mask(self):
        self.assertEqual(mask_performer.ZuraMask.RETURN_NAMES, ("mask_preview", "masked_footage", "mask"))
        self.assertEqual(mask_performer.ZuraMask.RETURN_TYPES, ("VIDEO", "ZURA_FOOTAGE", "MASK"))
        self.assertEqual(mask_performer.ZuraMask.CATEGORY, "Zura")

    def test_class_id_and_display_name(self):
        # Class IDs are kept from the pre-Zura pack so saved graphs still load.
        self.assertIs(mask_performer.NODE_CLASS_MAPPINGS["TrendStudioV2MaskPerformer"], mask_performer.ZuraMask)
        self.assertEqual(mask_performer.NODE_DISPLAY_NAME_MAPPINGS["TrendStudioV2MaskPerformer"], "Zura Mask")


if __name__ == "__main__":
    unittest.main()
