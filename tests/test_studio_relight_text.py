"""Relight lettering is protected before sampling, never pasted on output video.

Graph contracts do not establish bit-exact lettering after VAE compression.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

import test_studio_relight as relight
import test_h3_frame_anchors as anchors

studio, h3 = relight.studio, relight.h3


class RelightTextTests(unittest.TestCase):
    def project(self, remove=False):
        p = relight.RelightTests().project()
        p['config']['remove_text'] = remove
        return p

    def test_native_detection_covers_real_frames_and_saves_protected_review(self):
        with patch.object(studio, 'check_asset'):
            g = studio.build_graph(self.project(), 'prepare')
        self.assertEqual(g['zura_relight_sam']['class_type'], 'CheckpointLoaderSimple')
        self.assertEqual(g['zura_relight_text_prompt']['inputs']['text'], 'text:20')
        detected = g['zura_relight_text_detect']
        self.assertEqual(detected['class_type'], 'SAM3_Detect')
        self.assertEqual(detected['inputs']['image'], ['4', 0])
        self.assertFalse(detected['inputs']['individual_masks'])
        self.assertEqual(detected['inputs']['refine_iterations'], 0)
        self.assertEqual(g['zura_relight_text_margin']['class_type'], 'GrowMask')
        self.assertEqual(g['zura_relight_edit_mask']['class_type'], 'InvertMask')
        for target in ('17', '20'):
            self.assertEqual(g[target]['inputs']['mask'], ['zura_relight_edit_mask', 0])
        # Empty native detections pass through grow/invert as an all-editable mask.
        # There is no detection-count gate that could reject a no-text clip.
        self.assertNotIn('text_removal', g)
        self.assertNotIn('7', g)
        self.assertFalse(any(n['class_type'] == 'GenjTextRemovalMask' for n in g.values()))

    def test_remove_text_stays_full_scene_without_source_text_lock(self):
        p = self.project(remove=True)
        with patch.object(studio, 'check_asset'), patch.object(studio, 'assert_approved'):
            prepare = studio.build_graph(p, 'prepare')
            design = studio.build_graph(p, 'design', use_cache=False)
        self.assertEqual(prepare['12']['class_type'], 'ZuraWholeSceneMask')
        self.assertEqual(prepare['text_removal']['inputs']['performer_mask'], ['12', 0])
        self.assertEqual(prepare['20']['inputs']['mask'], ['text_removal', 0])
        self.assertEqual(prepare['20']['inputs']['clip_details'], ['text_removal', 1])
        self.assertNotIn('zura_relight_text_detect', prepare)
        self.assertNotIn('zura_masked_look', design)
        graph = anchors.H3FinishedFrameAnchorTests().build_normal(p)
        self.assertNotIn('h3_preserve_background', graph)
        self.assertNotIn('h3_source_latent', graph)

    def test_approved_opening_preserves_same_reviewed_text_before_video(self):
        with patch.object(studio, 'check_asset'), patch.object(studio, 'assert_approved'):
            g = studio.build_graph(self.project(), 'design', use_cache=False)
        self.assertEqual(g['122']['inputs']['images'], ['zura_masked_look', 0])
        self.assertEqual(g['zura_masked_look']['class_type'], 'ImageCompositeMasked')
        self.assertEqual(g['zura_masked_look']['inputs']['destination'], ['zura_look_source', 0])
        self.assertEqual(g['zura_look_mask_video']['inputs']['video'], ['123', 1])

    def test_source_lock_reaches_sampler_with_causal_caption_protection(self):
        g = anchors.H3FinishedFrameAnchorTests().build_normal(self.project())
        lock = g['h3_preserve_background']['inputs']
        self.assertTrue(lock['protect_unedited_regions'])
        self.assertEqual(lock['protection_timing'], 'causal')
        self.assertEqual(lock['mask'], ['h3_pad', 1])
        self.assertEqual(g['h3_source_latent']['class_type'], 'VAEEncode')
        self.assertEqual(g['h3_source_latent']['inputs']['pixels'], ['h3_pad', 0])
        self.assertEqual(g['h3_locked_audio']['inputs']['latent'], ['h3_preserve_background', 0])
        self.assertEqual(g['h3_sample']['inputs']['latent_image'], ['h3_locked_audio', 0])

    def test_future_subtitle_does_not_lock_empty_opening_hoodie(self):
        from comfy.nested_tensor import NestedTensor
        video = torch.randn(1, 24, 7, 4, 6)
        audio = torch.randn(1, 32, 2, 36)
        latent = {'samples': NestedTensor((torch.zeros_like(video), audio))}
        edit = torch.ones(22, 64, 96)
        edit[:, 4:8, 4:8] = 0       # Persistent title.
        edit[7:10, 36:40, 36:40] = 0  # Subtitle appears after the first two bins.
        edit[20, 45:49, 80:84] = 0  # New caption in the second chunk.
        adapter = h3.ZuraH3PreserveBackground()
        result = adapter.preserve(latent, {'samples': video}, edit,
                                  protect_unedited_regions=True, protection_timing='causal')[0]
        noise = result['noise_mask'].tensors[0]
        self.assertTrue(torch.all(noise[:, :, :5, :2, :2] == 0), 'Persistent title stays protected')
        self.assertTrue(torch.all(noise[:, :, :2, 2:, 2:4] == 1), 'Future subtitle cannot lock opening hoodie')
        self.assertTrue(torch.all(noise[:, :, 2:5, 2:, 2:4] == 0), 'Caption is protected in its bin and later context')
        self.assertTrue(torch.all(noise[:, :, 5, 2:, 4:] == 1), 'A later chunk does not lock its empty first frame')
        self.assertTrue(torch.all(noise[:, :, 6, 2:, 4:] == 0), 'Second chunk caption reaches its temporal bin')
        self.assertIs(result['samples'].tensors[0], video)
        self.assertTrue(torch.all(result['noise_mask'].tensors[1] == 1))
        conservative = adapter.preserve(latent, {'samples': video}, edit, protect_unedited_regions=True)[0]
        self.assertTrue(torch.all(conservative['noise_mask'].tensors[0][:, :, :5, 2:, 2:4] == 0),
                        'Existing moving-person chunk protection remains the default')
        with self.assertRaisesRegex(ValueError, 'protection timing'):
            adapter.preserve(latent, {'samples': video}, edit, protection_timing='future')

    def test_uploaded_finished_frame_cannot_skip_lighting_frame_review(self):
        p = self.project()
        p['look_mode'] = 'ready'
        with patch.object(studio, 'assert_approved'), patch.object(studio, 'check_asset'):
            with self.assertRaisesRegex(ValueError, 'Relight requires Build from references'):
                studio.build_graph(p, 'design')
        with self.assertRaisesRegex(ValueError, 'Relight requires Build from references'):
            anchors.H3FinishedFrameAnchorTests().build_normal(p)

    def test_old_white_mask_review_and_reference_cache_cannot_be_reused(self):
        p = self.project()
        protected = studio.prep_key(p)
        p['config']['workflow_mode'] = 'motion'
        self.assertNotEqual(protected, studio.prep_key(p))
        p['config']['workflow_mode'] = 'relight'
        with tempfile.TemporaryDirectory() as tmp:
            encoder = Path(tmp) / 'encoder'
            encoder.write_bytes(b'encoder')
            with patch('folder_paths.get_full_path', return_value=str(encoder)):
                protected_cache = h3.cache_key(p)
                p['config']['remove_text'] = True
                self.assertNotEqual(protected_cache, h3.cache_key(p))
        self.assertNotEqual(protected, studio.prep_key(p))


if __name__ == '__main__':
    unittest.main()
