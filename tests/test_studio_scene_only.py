"""CPU graph contracts for native scene-only H3 preservation, not render evidence."""
import tempfile
import ast
import os
import sys
import types
import torch
import unittest
from pathlib import Path
from unittest.mock import patch
from test_artist_studio import studio, h3, package
import test_artist_studio as shared


class SceneOnlyTests(unittest.TestCase):
    def project(self):
        p = shared.SharedEngineTests().project()
        p['config'] = studio.clean_config({**p['config'], 'engine': 'h3',
            'workflow_mode': 'motion', 'preserve_people': True})
        return p

    def test_supported_combination_and_speech_contract(self):
        self.assertEqual(self.project()['config']['edit_area'], 'mask')
        for engine, mode in [('local', 'motion'), ('wan', 'motion'), ('h3', 'swap'),
                             ('h3', 'viewport'), ('h3', 'relight')]:
            with self.subTest(engine=engine, mode=mode), self.assertRaisesRegex(ValueError, 'Keep original people'):
                studio.clean_config({'engine': engine, 'workflow_mode': mode, 'preserve_people': True})
        with self.assertRaisesRegex(ValueError, 'facial performance'):
            studio.clean_config({**self.project()['config'], 'audio_id': 'b'*32, 'lip_sync': True})

    def test_protection_keeps_tight_silhouette_after_cut_tracking(self):
        p = self.project()
        p['config'].update(mask_method='points', mask_points=[], scope='head', performer=4, remove_text=True)
        with patch.object(studio, 'check_asset'):
            g = studio.build_graph(p, 'prepare')
        self.assertEqual(g['7']['inputs']['text'], 'person:20')
        self.assertFalse(g['8']['inputs']['individual_masks'])
        self.assertEqual(g['9']['inputs']['performer'], -1)
        self.assertIn('zura_split_tracking_shots', g)
        self.assertEqual(g['12']['inputs']['mask'], ['zura_join_tracking_masks', 0])
        self.assertEqual(g['12']['inputs']['expand'], 0,
                         'Protect the entire detected person without copying an old-background halo')
        self.assertEqual(g['zura_edit_surroundings']['class_type'], 'InvertMask')
        self.assertEqual(g['zura_edit_surroundings']['inputs']['mask'], ['12', 0])
        self.assertEqual(g['20']['inputs']['mask'], ['zura_edit_surroundings', 0])
        self.assertEqual(g['20']['class_type'], 'GenjSaveReview')
        self.assertNotIn('text_removal', g, 'Text union must never reopen protected people')
        self.assertNotIn('zura_mask_points', g)

    def test_design_composites_only_surroundings_before_animation(self):
        p = self.project()
        with patch.object(studio, 'check_asset'), patch.object(studio, 'assert_approved'):
            g = studio.build_graph(p, 'design', use_cache=False)
            self.assertEqual(g['122']['inputs']['images'], ['zura_opening_preserve_source', 0])
            self.assertEqual(g['zura_opening_preserve_source']['inputs']['destination'], ['125', 0])
            self.assertEqual(g['zura_opening_preserve_source']['inputs']['mask'], ['zura_look_inside_mask', 0])
            self.assertEqual(g['zura_opening_original_resolution']['inputs']['image'], ['zura_masked_look', 0])
            self.assertIn('Keep every original person', g['127']['inputs']['value'])
            p['look_mode'] = 'ready'
            with self.assertRaisesRegex(ValueError, 'Build from references'):
                studio.build_graph(p, 'design')

    def test_toggle_invalidates_review_and_opening(self):
        p = self.project()
        protected_key = studio.prep_key(p)
        p['config']['preserve_people'] = False
        p['config'] = studio.clean_config(p['config'])
        before = studio.prep_key(p)
        self.assertNotEqual(before, protected_key)
        p['approval'] = p['prepared_key'] = before
        with tempfile.TemporaryDirectory() as tmp:
            controller = studio.Studio.__new__(studio.Studio)
            controller.store = studio.Store(tmp)
            controller.collect = lambda p: p
            controller.configure(p, {**p['config'], 'preserve_people': True})
        self.assertIsNone(p['review'])
        self.assertIsNone(p['opening_input'])

    def test_inactive_selection_controls_do_not_invalidate_protection_review(self):
        p = self.project()
        before = studio.prep_key(p)
        p['config'].update(scope='head', performer=3, mask_method='points', mask_points=[], margin=40)
        self.assertEqual(before, studio.prep_key(p))

    def test_tight_boundary_invalidates_previous_grown_protection_reviews(self):
        p = self.project()
        seen = []
        canonical = studio.canonical
        with patch.object(studio, 'canonical', side_effect=lambda value: (seen.append(value), canonical(value))[1]):
            studio.prep_key(p)
        self.assertEqual(seen[0]['person_boundary_recipe'], 1)
        self.assertNotIn('margin', seen[0])

    def test_subject_replacement_still_honours_its_edit_margin(self):
        p = self.project()
        p['config'] = studio.clean_config({**p['config'], 'preserve_people': False,
                                           'workflow_mode': 'swap', 'margin': 20})
        with patch.object(studio, 'check_asset'):
            g = studio.build_graph(p, 'prepare')
        self.assertEqual(g['12']['inputs']['expand'], 20)

    def test_h3_native_mask_lock_cannot_be_disabled(self):
        p = self.project()
        with patch.object(studio, 'check_asset'), patch.object(studio, 'assert_approved'), \
                patch.object(package, 'verify_review', return_value=(None, {'clip': {'frames': 48}}), create=True), \
                patch.object(h3, 'cache_key', return_value='c'*64):
            g = h3.build_h3_graph(p, use_cache=False)
            self.assertEqual(g['h3_preserve_background']['inputs']['mask'], ['h3_pad', 1])
            self.assertFalse(g['h3_preserve_background']['inputs']['protect_unedited_regions'],
                             'Regenerate moving boundary patches instead of locking an old-room halo')
            self.assertEqual(g['h3_inpaint']['inputs']['mask'], ['h3_pad', 1])
            self.assertNotIn('ref_videos.ref_video_0', g['h3_references']['inputs'],
                             'Original-room appearance reference overrode the approved replacement')
            self.assertNotIn('h3_source_reference', g)
            self.assertEqual(g['h3_inpaint']['inputs']['source_video'], ['h3_pad', 0])
            self.assertIn('control_video', g['h3_inpaint']['inputs'])
            self.assertNotIn('<Video 1>', g['h3_prompt']['inputs']['value'])
            self.assertIn('Retain every original person', g['h3_prompt']['inputs']['value'])
            with self.assertRaisesRegex(ValueError, 'native source preservation'):
                h3.build_h3_graph(p, use_cache=False, preserve_background=False)

class ProtectionMaskTests(unittest.TestCase):
    def test_native_tight_mask_retains_people_without_copying_background_ring(self):
        # Execute the installed native GrowMask implementation with real tensors,
        # without importing Comfy's GPU runtime. Optional on standalone installs.
        root = os.environ.get('COMFYUI_ROOT')
        path = Path(root or '') / 'comfy_extras' / 'nodes_mask.py'
        if not root or not path.is_file():
            self.skipTest('COMFYUI_ROOT is required for the native mask operation')
        import numpy as np
        import scipy.ndimage
        tree = ast.parse(path.read_text(encoding='utf8'))
        grow_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GrowMask')
        execute = next(n for n in grow_class.body if isinstance(n, ast.FunctionDef) and n.name in ('execute', 'expand_mask'))
        execute.decorator_list = []
        execute.returns = None
        namespace = {'np': np, 'scipy': scipy, 'torch': torch,
                     'IO': types.SimpleNamespace(NodeOutput=lambda *values: values)}
        exec(compile(ast.Module(body=[execute], type_ignores=[]), str(path), 'exec'), namespace)
        person = torch.zeros(2, 80, 80)
        person[:, 25:55, 30:50] = 1
        person[:, 24, 30:50] = 0.6  # Preserve antialiased hair/edge pixels too.
        p = SceneOnlyTests().project()
        with patch.object(studio, 'check_asset'):
            g = studio.build_graph(p, 'prepare')
        tight = namespace[execute.name](None, person, g['12']['inputs']['expand'], True)[0]
        grown = namespace[execute.name](None, person, 20, True)[0]
        self.assertTrue(torch.equal(tight, person), 'No detected-person pixels may be eroded')
        self.assertEqual(tight[0, 15, 40].item(), 0, 'Old room outside the silhouette stays editable')
        self.assertEqual(grown[0, 15, 40].item(), 1, 'The former margin copied an old-background ring')
        self.assertTrue(torch.equal(person[:, 24, 30:50], tight[:, 24, 30:50]))

    def test_moving_people_protect_spatial_and_temporal_union_without_changing_defaults(self):
        # Exercise the real adapter's tensor operations. The standalone container
        # supplies only ComfyUI's public .tensors contract; no render claim.
        try:
            from comfy.nested_tensor import NestedTensor
        except ImportError:
            class NestedTensor:
                def __init__(self, tensors):
                    self.tensors = list(tensors)
        nested = types.ModuleType('comfy.nested_tensor')
        nested.NestedTensor = NestedTensor
        video = torch.randn(1, 24, 7, 4, 6)
        audio = torch.randn(1, 32, 2, 36)
        audio_mask = torch.zeros_like(audio)
        latent = {'samples': NestedTensor((torch.zeros_like(video), audio)),
                  'noise_mask': NestedTensor((torch.ones_like(video), audio_mask)), 'metadata': 'keep'}
        edit = torch.ones(22, 64, 96)
        edit[0, 4:8, 4:8] = 0       # Person starts in patch (0,0).
        edit[16, 36:40, 36:40] = 0 # Moves into patch (1,1) in the same chunk.
        edit[20, 45:49, 80:84] = 0 # A separate later chunk, patch (1,2).
        with patch.dict(sys.modules, {'comfy.nested_tensor': nested}):
            adapter = h3.ZuraH3PreserveBackground()
            protected = adapter.preserve(latent, {'samples': video}, edit, protect_unedited_regions=True)[0]
            default = adapter.preserve(latent, {'samples': video}, edit)[0]
            explicit_default = adapter.preserve(latent, {'samples': video}, edit, protect_unedited_regions=False)[0]
        noise = protected['noise_mask'].tensors[0]
        self.assertTrue(torch.all(noise[:, :, :5, :2, :2] == 0))
        self.assertTrue(torch.all(noise[:, :, :5, 2:, 2:4] == 0))
        self.assertTrue(torch.all(noise[:, :, :5, :, 4:] == 1))
        self.assertTrue(torch.all(noise[:, :, 5:, 2:, 4:] == 0))
        self.assertTrue(torch.all(noise[:, :, 5:, :2, :] == 1))
        self.assertTrue(torch.all(noise[:, :, 5:, 2:, :4] == 1))
        self.assertIs(protected['samples'].tensors[0], video)
        self.assertIs(protected['samples'].tensors[1], audio)
        self.assertIs(protected['noise_mask'].tensors[1], audio_mask)
        self.assertEqual(protected['metadata'], 'keep')
        self.assertTrue(torch.equal(default['noise_mask'].tensors[0], explicit_default['noise_mask'].tensors[0]))
        self.assertTrue(torch.all(default['noise_mask'].tensors[0] == 1), 'Original edit-union semantics remain unchanged')
        self.assertEqual(int((edit == 0).sum()), 48, 'Caller mask must not be mutated')


if __name__ == '__main__':
    unittest.main()
