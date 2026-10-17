"""Relight routes retain scene content and accept prompt-only lighting direction."""
import copy
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_artist_studio as fixture
import test_h3_frame_anchors as anchors

studio = fixture.studio
h3 = fixture.h3
appearance = importlib.import_module(studio.__package__ + '.appearance')
enhancement = importlib.import_module(studio.__package__ + '.enhancement')


class RelightTests(unittest.TestCase):
    def test_prompt_only_enhanced_delivery_has_a_direction_bound_generation_key(self):
        project = self.project()
        first = enhancement.generation_key(project)
        project['config']['prompt'] = 'Cool blue moonlight from camera right.'
        self.assertNotEqual(first, enhancement.generation_key(project))

    def project(self):
        project = fixture.SharedEngineTests().project()
        project['config'] = studio.clean_config({'engine': 'h3', 'workflow_mode': 'relight',
                                                'prompt': 'Warm sunset light from camera left.'})
        project.update(character=None, references=[], look_mode='build')
        return project

    def test_mode_requires_h3_and_lighting_direction(self):
        for engine in ('local', 'wan', 'seedance'):
            with self.assertRaisesRegex(ValueError, 'supports MiniMax H3'):
                studio.clean_config({'engine': engine, 'workflow_mode': 'relight', 'prompt': 'sunlight'})
        empty = studio.clean_config({'engine': 'h3', 'workflow_mode': 'relight'})
        with self.assertRaisesRegex(ValueError, 'Describe the lighting'):
            studio.require_relight_direction(empty)
        config = self.project()['config']
        self.assertEqual(config['edit_area'], 'scene')
        self.assertFalse(config['viewport_render'])
        self.assertEqual(config['background'], 'keep')

    def test_appearance_references_are_optional_only_for_relight(self):
        def not_called(_):
            self.fail('No image should be loaded for an empty reference list')
        result = appearance.resolve_appearance({'config': self.project()['config'], 'references': []},
                                               not_called, not_called)
        self.assertIsNone(result['character'])
        self.assertIsNone(result['starting_asset'])
        self.assertEqual(result['references'], [])
        with self.assertRaisesRegex(ValueError, 'at least one'):
            appearance.resolve_appearance({'references': []}, not_called, not_called)

    def test_prompt_only_design_encodes_source_not_video_as_image(self):
        with patch.object(studio, 'assert_approved'), patch.object(studio, 'check_asset'):
            graph = studio.build_graph(self.project(), 'design', use_cache=False)
        self.assertNotIn('121', graph)
        self.assertEqual(graph['92:103']['inputs']['positive'], ['92:128', 0])
        self.assertEqual(graph['92:103']['inputs']['negative'], ['92:126', 0])
        self.assertIn('125', graph)
        prompt = graph['127']['inputs']['value']
        self.assertIn('Relight the first image only', prompt)
        self.assertIn('Warm sunset light', prompt)
        self.assertNotIn('replace the visible performer', prompt)
        self.assertFalse(any(n['class_type'] == 'LoadImage' and n['inputs'].get('image') == 'source.mp4'
                             for n in graph.values()))

    def test_optional_lighting_references_do_not_add_replacement_direction(self):
        project = self.project()
        project['references'] = [{'file': 'lighting-a.png'}, {'file': 'lighting-b.png'}]
        project['character'] = project['references'][0]
        with patch.object(studio, 'assert_approved'), patch.object(studio, 'check_asset'):
            graph = studio.build_graph(project, 'design', use_cache=False)
        prompt = graph['127']['inputs']['value']
        self.assertIn('All additional images guide lighting only', prompt)
        self.assertNotIn('selected subject, object, materials or environment', prompt)
        self.assertEqual(graph['121']['inputs']['image'], 'lighting-a.png')
        self.assertEqual(graph['zura_reference_2']['inputs']['image'], 'lighting-b.png')

    def test_h3_uses_source_video_depth_approved_opening_and_text_protection(self):
        graph = anchors.H3FinishedFrameAnchorTests().build_normal(self.project())
        self.assertNotIn('h3_character', graph)
        self.assertIn('h3_source_latent', graph)
        self.assertTrue(graph['h3_preserve_background']['inputs']['protect_unedited_regions'])
        references = graph['h3_references']['inputs']
        self.assertNotIn('ref_videos.ref_video_0', references,
                         'The original lighting reference pulled illumination back after the opening')
        self.assertNotIn('h3_source_reference', graph)
        self.assertNotIn('ref_images.ref_image_1', references)
        self.assertEqual(graph['h3_depth']['inputs']['image'], ['h3_pad', 0])
        self.assertEqual(graph['h3_first_frame']['inputs']['image'], ['h3_opening_size', 0])
        self.assertIn('h3_locked_audio', graph)
        self.assertEqual(graph['h3_video']['inputs']['audio'], ['h3_pad', 2])
        prompt = graph['h3_prompt']['inputs']['value']
        self.assertIn('Change only lighting', prompt)
        self.assertNotIn('<Picture 2>', prompt)
        self.assertNotIn('replacement character', prompt)
        self.assertNotIn('<Video 1>', prompt)

    def test_native_motion_source_retained_without_appearance_video_reference(self):
        for count in (48, 5, 120):
            with self.subTest(count=count):
                graph = anchors.H3FinishedFrameAnchorTests().build_normal(self.project(), frames=count)
                self.assertNotIn('h3_source_reference', graph)
                self.assertNotIn('ref_videos.ref_video_0', graph['h3_references']['inputs'])
                self.assertEqual(graph['h3_references']['inputs']['length'], ['h3_pad', 5])
                self.assertEqual(graph['h3_depth']['inputs']['image'], ['h3_pad', 0])
                self.assertEqual(graph['h3_inpaint']['inputs']['source_video'], ['h3_pad', 0])
                self.assertEqual(graph['h3_inpaint']['inputs']['mask'], ['h3_pad', 1])
                self.assertEqual(graph['h3_locked_audio']['inputs']['audio'], ['h3_pad', 2])

    def test_source_reference_and_person_boundary_recipes_invalidate_only_their_caches(self):
        import json
        original_dumps = json.dumps
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / 'encoder'
            model.write_bytes(b'encoder')
            for mode, preserve in (('relight', False), ('motion', True), ('motion', False)):
                project = self.project()
                project['config'].update(workflow_mode=mode, preserve_people=preserve)
                with patch('folder_paths.get_full_path', return_value=str(model)), \
                        patch.object(h3.json, 'dumps', wraps=original_dumps) as dumps:
                    h3.cache_key(project)
                payload = dumps.call_args.args[0]
                self.assertNotIn('source_reference_grid', payload)
                self.assertEqual(payload.get('relight_conditioning_recipe'), 2 if mode == 'relight' else None)
                self.assertEqual(payload.get('person_conditioning_recipe'), 2 if preserve else None)

    def test_other_h3_routes_keep_existing_background_lock(self):
        graph = anchors.H3FinishedFrameAnchorTests().build_normal(anchors.H3FinishedFrameAnchorTests().base_project())
        self.assertIn('h3_preserve_background', graph)
        self.assertIn('ref_images.ref_image_1', graph['h3_references']['inputs'])

    def test_direct_wrong_engine_graph_is_rejected(self):
        project = self.project()
        project['config']['engine'] = 'wan'
        with self.assertRaisesRegex(ValueError, 'supports MiniMax H3'):
            studio.build_graph(project, 'wan')

    def test_same_review_and_opening_cannot_reuse_non_relight_conditioning(self):
        project = self.project()
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / 'encoder'
            model.write_bytes(b'encoder')
            with patch('folder_paths.get_full_path', return_value=str(model)):
                relight = h3.cache_key(project)
                project['config']['workflow_mode'] = 'motion'
                other = h3.cache_key(project)
        self.assertNotEqual(relight, other)

    def test_task_change_invalidates_approved_opening_even_with_explicit_image_prompt(self):
        project = self.project()
        project['config']['workflow_mode'] = 'motion'
        project['config']['image_prompt'] = 'Warm light'
        project['approval'] = studio.prep_key(project)
        project['prepared_key'] = project['approval']
        with tempfile.TemporaryDirectory() as temp:
            controller = studio.Studio.__new__(studio.Studio)
            controller.store = studio.Store(temp)
            controller.collect = lambda p: p
            controller.configure(project, {**project['config'], 'workflow_mode': 'relight'})
        self.assertIsNone(project['opening_input'])
        self.assertIsNone(project['opening_approval'])


if __name__ == '__main__':
    unittest.main()
