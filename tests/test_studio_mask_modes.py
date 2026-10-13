"""Selection contracts and camera registration, without inference or private data."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import av
import torch

import test_artist_studio as fixture

studio = fixture.studio


class MaskModeTests(unittest.TestCase):
    def project(self, **settings):
        p = fixture.SharedEngineTests().project()
        # The task selector now owns scene versus masked editing. Translate
        # legacy test inputs into the equivalent current control before
        # normalising a config that already contains workflow_mode.
        if "edit_area" in settings and "workflow_mode" not in settings:
            settings["workflow_mode"] = "motion" if settings["edit_area"] == "scene" else "swap"
        p['config'] = studio.clean_config({**p['config'], **settings})
        return p

    def graph(self, p, stage='prepare'):
        with patch.object(studio, 'check_asset'), patch.object(studio, 'assert_approved'):
            return studio.build_graph(p, stage)

    def test_cut_aware_recipe_invalidates_legacy_automatic_approval(self):
        p = self.project()
        legacy = {'source': p['source']['sha'], **{k: p['config'][k] for k in studio.PREP_KEYS}}
        expected = hashlib.sha256(studio.canonical(legacy).encode()).hexdigest()
        self.assertNotEqual(studio.prep_key(p), expected)
        current = dict(legacy, tracking_recipe=2)
        self.assertEqual(studio.prep_key(p), hashlib.sha256(studio.canonical(current).encode()).hexdigest())
        graph = self.graph(p)
        self.assertEqual(graph['7']['inputs']['text'], 'person')
        self.assertEqual(graph['10']['inputs']['initial_mask'], ['9', 0])
        self.assertEqual(graph['8']['inputs']['image'], ['zura_split_tracking_shots', 1])
        self.assertEqual(graph['10']['inputs']['images'], ['zura_split_tracking_shots', 0])
        self.assertEqual(graph['12']['inputs']['mask'], ['zura_join_tracking_masks', 0])
        self.assertEqual(graph['20']['inputs']['tracking_coverage'], ['zura_join_tracking_masks', 1])

    def test_whole_scene_skips_every_sam_node_even_with_remove_text(self):
        p = self.project(edit_area='scene', remove_text=True)
        graph = self.graph(p)
        self.assertEqual(graph['12']['class_type'], 'ZuraWholeSceneMask')
        self.assertEqual(graph['12']['inputs']['images'], ['4', 0])
        self.assertFalse(any('SAM3' in n['class_type'] for n in graph.values()))
        self.assertNotIn('6', graph)
        self.assertNotIn('text_detect', graph)
        for n in graph.values():
            for value in n['inputs'].values():
                if isinstance(value, list) and len(value) == 2:
                    self.assertIn(value[0], graph, 'The whole-scene graph has no missing dependency')
        self.assertEqual(graph['20']['inputs']['mask'], ['12', 0])

    def test_text_mask_uses_description_and_tracks_result(self):
        graph = self.graph(self.project(mask_method='text', mask_prompt='red chair'))
        self.assertEqual(graph['7']['inputs']['text'], 'red chair')
        self.assertFalse(graph['8']['inputs']['individual_masks'])
        self.assertEqual(graph['10']['inputs']['initial_mask'], ['9', 0])
        self.assertNotIn('zura_mask_points', graph)

    def test_text_removal_saves_genuine_mask_separately_from_combined_mask(self):
        graph = self.graph(self.project(remove_text=True))
        inputs = graph['20']['inputs']
        self.assertEqual(inputs['mask'], ['text_removal', 0], 'Generation still receives the combined person and text mask')
        self.assertEqual(inputs['performer_mask'], ['zura_join_tracking_masks', 0], 'Text cleanup protects the rejoined native outline independently of extra edit room')
        self.assertEqual(graph['text_detect']['inputs']['threshold'], .5)
        self.assertEqual(graph['text_removal']['inputs']['tracking_segments'], ['zura_split_tracking_shots', 2])
        self.assertNotIn('performer_mask', self.graph(self.project()).get('20', {}).get('inputs', {}))

    def test_text_review_version_invalidates_previous_text_review(self):
        p = self.project(remove_text=True)
        expected = {'source': p['source']['sha'], **{key: p['config'][key] for key in studio.PREP_KEYS},
                    'remove_text': 6, 'tracking_recipe': 2}
        self.assertEqual(studio.prep_key(p), hashlib.sha256(studio.canonical(expected).encode()).hexdigest())
        old = dict(expected, remove_text=5)
        p.update(review='shot_' + 'a' * 16, approval=hashlib.sha256(studio.canonical(old).encode()).hexdigest(),
                 prepared_key=hashlib.sha256(studio.canonical(old).encode()).hexdigest(), phase='approved')
        with tempfile.TemporaryDirectory() as tmp:
            controller = studio.Studio.__new__(studio.Studio)
            controller.store = studio.Store(tmp)
            controller.collect = lambda project: project
            controller.configure(p, dict(p['config']))
        self.assertEqual(p['phase'], 'new')
        self.assertIsNone(p['review'])
        self.assertIsNone(p['approval'])

    def test_click_mask_does_not_union_unrelated_text_detections(self):
        points = [{'x': .3, 'y': .75, 'include': True}, {'x': .4, 'y': .1, 'include': False}]
        graph = self.graph(self.project(mask_method='points', mask_points=points))
        self.assertNotIn('7', graph)
        self.assertNotIn('conditioning', graph['8']['inputs'])
        self.assertEqual(graph['8']['inputs']['positive_coords'], ['zura_mask_points', 0])
        self.assertEqual(graph['8']['inputs']['negative_coords'], ['zura_mask_points', 1])
        self.assertEqual(json.loads(graph['zura_mask_points']['inputs']['points_json']), points)
        self.assertEqual(graph['10']['inputs']['initial_mask'], ['9', 0])

    def test_missing_selection_fails_before_any_native_submission(self):
        for settings in ({'mask_method':'text', 'mask_prompt':'   '}, {'mask_method':'points'},
                         {'mask_method':'points', 'mask_points':[{'x':.2,'y':.4,'include':False}]}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.graph(self.project(**settings))

    def test_active_mask_changes_require_review_inactive_controls_do_not(self):
        p = self.project(edit_area='scene')
        original = studio.prep_key(p)
        p['config'].update(mask_method='text', mask_prompt='sky', scope='head', margin=20, performer=3)
        self.assertEqual(studio.prep_key(p), original)
        p['config']['edit_area'] = 'mask'
        self.assertNotEqual(studio.prep_key(p), original)
        text_key = studio.prep_key(p)
        p['config']['mask_prompt'] = 'chair'
        self.assertNotEqual(studio.prep_key(p), text_key)
        p['config'].update(mask_method='points', mask_points=[{'x':.3,'y':.5,'include':True}])
        click_key = studio.prep_key(p)
        p['config']['mask_points'][0]['y'] = .6
        self.assertNotEqual(studio.prep_key(p), click_key)

    def test_changing_edit_area_invalidates_review_and_opening(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = studio.Studio.__new__(studio.Studio)
            controller.store = studio.Store(tmp)
            controller.collect = lambda p:p
            p = self.project()
            p['approval'] = studio.prep_key(p)
            p['prepared_key'] = p['approval']
            controller.configure(p, {**p['config'], 'workflow_mode':'motion', 'edit_area':'scene'})
            self.assertEqual(p['phase'], 'new')
            self.assertIsNone(p['review'])
            self.assertIsNone(p['opening_input'])

    def test_masked_opening_registers_source_and_changes_only_reviewed_area(self):
        graph = self.graph(self.project(), 'design')
        self.assertEqual(graph['122']['inputs']['images'], ['zura_masked_look',0])
        composite = graph['zura_masked_look']['inputs']
        self.assertEqual(composite['destination'], ['zura_look_source',0])
        self.assertEqual(composite['source'], ['92:105',0])
        self.assertEqual(composite['mask'], ['zura_look_inside_mask',0])
        self.assertEqual(graph['zura_look_mask_video']['inputs']['video'], ['123',1])
        self.assertEqual(graph['92:111']['inputs']['resolution_steps'], 16)
        self.assertEqual(graph['92:85']['inputs']['resolution_steps'], 16)

    def test_new_selection_has_room_for_clothing_but_saved_margin_is_retained(self):
        self.assertEqual(studio.clean_config({})['margin'], 20)
        self.assertEqual(studio.clean_config({'margin':8})['margin'], 8)
        self.assertEqual(studio.clean_config({'margin':0})['margin'], 0)

    def test_opening_edge_cleanup_is_bounded_by_the_reviewed_mask(self):
        graph = self.graph(self.project(), 'design')
        boundary = graph['zura_look_boundary']['inputs']
        self.assertEqual(boundary, {'mask':['zura_look_mask',0],'value':0.5})
        inside = graph['zura_look_inside_mask']['inputs']
        self.assertEqual(inside['operation'],'multiply')
        self.assertEqual(inside['destination'],['zura_look_boundary',0])
        self.assertEqual(inside['source'],['zura_look_soft_mask',0])

    def test_whole_scene_opening_can_change_background_and_mentions_camera_geometry(self):
        graph = self.graph(self.project(edit_area='scene'), 'design')
        self.assertEqual(graph['122']['inputs']['images'], ['92:105',0])
        self.assertNotIn('zura_masked_look', graph)
        self.assertIn('ground plane', graph['127']['inputs']['value'])
        self.assertIn('camera framing', graph['127']['inputs']['value'])

    def test_ltx_custom_selections_follow_selected_audio_performance_mode(self):
        for area, method in [('scene','auto'), ('mask','text'), ('mask','points')]:
            for speech in (False, True):
                with self.subTest(area=area,method=method,speech=speech):
                    p = self.project(engine='local',edit_area=area,mask_method=method,
                                     mask_prompt='person',audio_id='b'*32,lip_sync=speech)
                    p['audio'] = {'file':'synthetic_reference.wav','sha':'synthetic-audio'}
                    stage = 'restyle' if area == 'scene' else 'background'
                    with patch.object(fixture.package,'text_cache_path',return_value=Path('/nonexistent-mask-mode-cache'),create=True), \
                            patch.object(studio,'text_cache_info',return_value=('synthetic-cache',{})):
                        graph = self.graph(p,stage)
                    text = graph['5508' if stage=='restyle' else '5404']['inputs']['value']
                    if speech:
                        self.assertNotIn('Keep the original facial performance',text)
                        self.assertIn('replacement dialogue',text)
                        self.assertIn('resting mouth during silence',text)
                    else:
                        self.assertIn('Keep the original facial performance and lip movements',text)

    def test_defaults_have_no_shared_mutable_click_list(self):
        first, second = studio.clean_config({}), studio.clean_config({})
        first['mask_points'].append({'x':.2,'y':.3,'include':True})
        self.assertEqual(second['mask_points'], [])
        self.assertEqual(studio.DEFAULTS['mask_points'], [])

    def test_visible_edit_area_overrides_legacy_background_for_every_engine(self):
        for engine in ('local', 'h3', 'wan', 'seedance'):
            with self.subTest(engine=engine):
                c = studio.clean_config({'engine':engine, 'edit_area':'mask', 'background':'restyle'})
                self.assertEqual(c['background'], 'keep')
                c = studio.clean_config({'engine':engine, 'edit_area':'scene', 'background':'keep'})
                self.assertEqual(c['background'], 'restyle' if engine in ('local','seedance') else 'keep')
        legacy = {'engine':'local','background':'restyle'}
        self.assertEqual(studio.clean_config(legacy)['edit_area'], 'scene')
        self.assertNotIn('edit_area',legacy,'Migration does not write to a saved record on read')

    def test_h3_selection_prompt_does_not_force_hidden_head_or_character_scope(self):
        h3 = fixture.h3
        with patch.object(fixture.package,'verify_review',return_value=(None,{'clip':{'frames':9}}),create=True), \
                patch.object(studio,'assert_approved'), patch.object(studio,'check_asset'), \
                patch.object(h3,'cache_key',return_value='a'*64):
            for area, method in [('scene','auto'), ('mask','text'), ('mask','points')]:
                p = self.project(engine='h3',edit_area=area,mask_method=method,mask_prompt='red chair',scope='head')
                graph = h3.build_h3_graph(p,use_cache=False)
                prompt = graph['h3_prompt']['inputs']['value']
                self.assertNotIn('Replace only the selected head',prompt)
                self.assertIn('ground plane',prompt)
                if area == 'scene':
                    self.assertIn('Transform the whole scene',prompt)
                    self.assertNotIn('Preserve the background',prompt)
                else:
                    self.assertIn('only the reviewed masked area',prompt)
                # Mask guidance still precedes generation; no RGB face paste.
                self.assertIn('h3_preserve_background',graph)
                self.assertNotIn('zura_speech_0video',graph)

    def test_h3_selection_prompt_changes_cannot_reuse_legacy_encoded_cache(self):
        import folder_paths
        p = self.project(engine='h3')
        with patch.object(folder_paths,'get_full_path',return_value=str(Path(__file__))):
            original = fixture.h3.cache_key(p)
            p['config']['mask_method']='text'
            described = fixture.h3.cache_key(p)
            self.assertNotEqual(original,described)
            p['config']['mask_prompt']='red chair'
            self.assertNotEqual(described,fixture.h3.cache_key(p))
            p['config']['edit_area']='scene'
            scene = fixture.h3.cache_key(p)
            p['config']['mask_prompt']='sky'
            self.assertEqual(scene,fixture.h3.cache_key(p),'Inactive text does not alter a scene prompt')

    def test_wan_custom_area_does_not_require_a_person_in_reference_image(self):
        wan = fixture.wan
        with patch.object(studio,'assert_approved'), patch.object(studio,'check_asset'), \
                patch.object(wan,'cache_key',return_value='a'*64):
            p = self.project(edit_area='mask',mask_method='text',mask_prompt='red chair',scope='head')
            graph = wan.build_wan_graph(p,use_cache=False)
            self.assertNotIn('wan_person_prompt',graph)
            self.assertEqual(graph['wan_cached']['inputs']['reference'],['wan_character',0])
            self.assertEqual(graph['wan_cached']['inputs']['scope'],'person')
            self.assertIn('only the reviewed masked area',graph['wan_render']['inputs']['prompt'])


class PreparationAspectTests(unittest.TestCase):
    def test_actual_review_clip_retains_16_by_9_instead_of_rounding_to_2_by_1(self):
        fixture.AudioAdapterTests.setUpClass()
        ns = fixture.AudioAdapterTests.ns
        import folder_paths
        with tempfile.TemporaryDirectory() as tmp, patch.object(folder_paths,'get_output_directory',return_value=tmp,create=True):
            source = Path(tmp) / 'synthetic_viewport.mp4'
            ns['encode_frames'](source, torch.zeros(6,360,640,3))
            video = ns['InputImpl'].VideoFromFile(str(source))
            video.get_dimensions = lambda:(640,360)
            selected, details, _ = ns['GenjSelectClip']().select(video,0,.25,512)
            self.assertEqual((details['width'],details['height']), (512,288))
            with av.open(selected.path) as container:
                stream = container.streams.video[0]
                self.assertEqual((stream.width,stream.height),(512,288))
                self.assertEqual(sum(1 for _ in container.decode(video=0)),6)


if __name__ == '__main__':
    unittest.main()
