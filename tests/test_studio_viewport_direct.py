"""Direct H3 viewport mode must never bind a stale generated opening."""
import asyncio
import unittest
from unittest.mock import patch

import test_h3_frame_anchors as fixtures

studio = fixtures.studio
h3 = fixtures.h3


class DirectViewportTests(unittest.TestCase):
    def project(self):
        p = fixtures.H3FinishedFrameAnchorTests().viewport_project(ready=False)
        p.update(look_mode='build', opening_input={'file': 'stale.png', 'sha': 'stale'},
                 opening_key='stale', opening_approval='stale')
        p['config']['h3_viewport_direct'] = True
        return p

    def test_direct_keeps_nine_refs_without_inserting_stale_opening(self):
        p = self.project()
        p['references'] += [{'file': f'other-{i}.png', 'sha': str(i)} for i in range(4)]
        normalized = studio._viewport_project(p)
        self.assertEqual(normalized['look_mode'], 'build')
        self.assertEqual(len(normalized['viewport_references']), 9)
        self.assertFalse(any(r.get('viewport_role') == 'starting_frame' for r in normalized['viewport_references']))
        with patch.object(studio, 'assert_approved'), patch.object(studio, 'check_asset'), \
                patch('av.open', return_value=fixtures.H3FinishedFrameAnchorTests.media_container(15)):
            graph = h3.build_h3_graph(normalized, use_cache=False)
        self.assertIn('h3_viewport_source', graph)
        self.assertFalse(any(n['class_type'] == 'H3ImageToVideo' for n in graph.values()))
        self.assertNotIn('stale.png', str(graph))

    def test_build_and_ready_keep_existing_anchor_behavior(self):
        p = self.project()
        p['config']['h3_viewport_direct'] = False
        self.assertEqual(studio._viewport_project(p)['starting_asset']['file'], 'stale.png')
        p['config']['h3_viewport_direct'] = True
        p.update(look_mode='ready', starting_asset={'file': 'artist.png', 'sha': 'artist'})
        self.assertFalse(studio.h3_viewport_direct(p))
        self.assertEqual(studio._viewport_project(p)['viewport_references'][0]['file'], 'artist.png')

    def test_flag_is_scoped_and_old_config_keeps_explicit_build(self):
        self.assertFalse(studio.clean_config({'engine': 'h3', 'workflow_mode': 'viewport'})['h3_viewport_direct'])
        p = self.project()
        for mode in ('motion', 'swap', 'relight'):
            p['config']['workflow_mode'] = mode
            self.assertFalse(studio.h3_viewport_direct(p))
        p['config'].update(workflow_mode='viewport', engine='local')
        self.assertFalse(studio.h3_viewport_direct(p))

    def test_direct_design_does_not_invent_an_opening(self):
        with self.assertRaisesRegex(ValueError, 'Build starting frame'):
            studio.build_graph(self.project(), 'design', use_cache=False)

    def native_graph(self, project):
        return fixtures.H3FinishedFrameAnchorTests().build_viewport(studio._viewport_project(project))

    def test_custom_audio_uses_selected_offset_for_conditioning_lock_and_export(self):
        p = self.project()
        p['audio'] = {'id': 'audio', 'file': 'custom.wav', 'sha': 'custom'}
        p['config'].update(audio_id='audio', audio_start=1.25, lip_sync=True)
        graph = self.native_graph(p)
        selected = graph['h3_viewport_clip']['inputs']
        self.assertEqual(graph['h3_viewport_audio']['inputs']['audio'], 'custom.wav')
        self.assertEqual(selected['audio'], ['h3_viewport_audio', 0])
        self.assertEqual(selected['audio_start_seconds'], 1.25)
        audio = ['h3_viewport_components', 1]
        self.assertEqual(graph['h3_viewport_components']['inputs']['video'], ['h3_viewport_clip', 0])
        self.assertEqual(graph['h3_references']['inputs']['ref_audios.ref_audio_0'], audio)
        self.assertEqual(graph['h3_viewport_speech']['inputs']['audio'], audio)
        self.assertEqual(graph['h3_locked_audio']['inputs']['audio'], audio)
        self.assertEqual(graph['h3_sample']['inputs']['latent_image'], ['h3_locked_audio', 0])
        self.assertEqual(graph['h3_video']['inputs']['audio'], audio)
        self.assertEqual(graph['h3_export']['inputs']['clip_details'], ['h3_viewport_clip', 1])
        self.assertIn('replacement speech', graph['h3_references']['inputs']['prompt'])
        p['config']['lip_sync'] = False
        graph = self.native_graph(p)
        self.assertIn('do not invent dialogue', graph['h3_references']['inputs']['prompt'])

    def test_original_audio_route_remains_unchanged(self):
        graph = self.native_graph(self.project())
        self.assertNotIn('h3_viewport_audio', graph)
        self.assertNotIn('h3_locked_audio', graph)
        self.assertNotIn('ref_audios.ref_audio_0', graph['h3_references']['inputs'])
        self.assertEqual(graph['h3_export']['inputs']['clip_details'], ['h3_viewport_clip', 1])

    def test_enhanced1080_really_samples_at_720p_and_saves_intermediate(self):
        p = self.project()
        p['config'].update(resolution=1920, delivery_mode='enhanced1080')
        graph = self.native_graph(p)
        self.assertEqual(graph['h3_viewport_clip']['inputs']['long_edge'], 1280)
        self.assertEqual(graph['h3_export']['inputs']['output_subfolder'], 'studio_intermediate')
        self.assertTrue(graph['h3_export']['inputs']['take_name'].endswith('_h3_base'))
        p['config']['delivery_mode'] = 'native'
        graph = self.native_graph(p)
        self.assertEqual(graph['h3_viewport_clip']['inputs']['long_edge'], 1920)
        self.assertNotIn('output_subfolder', graph['h3_export']['inputs'])

    def test_viewport_rejects_unimplemented_optional_lip_refinement(self):
        p = self.project()
        p['config']['refine_lips'] = True
        with self.assertRaisesRegex(ValueError, 'not available for viewport'):
            self.native_graph(p)

    def test_animate_action_accepts_motion_review_without_opening_approval(self):
        p = self.project()
        p.update(actions=[], phase='approved')
        for key in ('opening_input', 'opening_key', 'opening_approval'):
            p.pop(key)
        controller = studio.Studio.__new__(studio.Studio)
        controller.collect = lambda _: None
        with patch.object(studio, 'validate_selection'), patch.object(studio, 'build_graph', side_effect=RuntimeError('reached native graph')) as build:
            with self.assertRaisesRegex(RuntimeError, 'reached native graph'):
                asyncio.run(controller.action(p, 'animate', {'request_key': 'a' * 36}))
        self.assertEqual(build.call_args.args[1], 'h3')
        self.assertNotIn('opening_approval', p)

    def test_export_auto_and_animate_choose_real_h3_graph_without_opening(self):
        p = self.project()
        for key in ('opening_input', 'opening_key', 'opening_approval'):
            p.pop(key)
        p['approval'] = studio.prep_key(p)
        for stage in ('auto', 'animate'):
            with patch.object(studio, 'build_graph', return_value={'render': {'class_type': 'PreviewAny', 'inputs': {'source': 'test'}}}) as build:
                result = studio.editable_graph(p, stage)
            self.assertEqual(build.call_args.args[1], 'h3')
            self.assertNotIn('opening_approval', build.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
