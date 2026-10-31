"""Graph/provenance checks for the internal HDR performance experiment."""
import copy
import importlib
import sys
import tempfile
import types
import unittest

import v2_bootstrap
from test_ltx25_native_plan import inputs

NAME = 'ComfyUI_zura_nodes.artist_studio'
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / 'artist_studio')]
    sys.modules[NAME] = package
hdr = importlib.import_module(NAME + '.ltx25_hdr_plan')
ltx = hdr.ltx25


class HDRPerformanceTests(unittest.TestCase):
    def config(self, scenario='replacement'):
        project, kwargs = inputs(scenario)
        project['config']['resolution'] = 512
        kwargs['timeline'].update(frames=9, width=512, height=512)
        kwargs['models']['video_vae'] = hdr.VIDEO_VAE
        endpoint = {'manifest': 'verified-frame.json', 'sha': 'd' * 64,
                    'colour_space': 'acescg', 'opening_key': project['opening_key']}
        return project, dict(hdr_endpoint=endpoint, **kwargs)

    def test_hdr_anchor_is_original_exr_at_both_stages_and_no_jpeg(self):
        project, kwargs = self.config()
        before = copy.deepcopy((project, kwargs))
        plan = hdr.build_native_hdr_plan(project, **kwargs)
        self.assertEqual((project, kwargs), before)
        self.assertEqual(plan['basis']['models']['video_vae'], hdr.VIDEO_VAE)
        for phase in ('stage1', 'upscale', 'decode'):
            graph = plan['phases'][phase]
            self.assertEqual(graph['video_vae']['class_type'], 'LTXVVAEForceFloat32')
            self.assertEqual(graph['video_vae_load']['inputs']['vae_name'], hdr.VIDEO_VAE)
        for phase, width in (('stage1', 256), ('upscale', 512)):
            graph = plan['phases'][phase]
            self.assertEqual(graph['opening']['class_type'], 'ZuraHDRLoadNativeSource')
            self.assertEqual(graph['opening']['inputs']['manifest_sha'], 'd' * 64)
            self.assertEqual(graph['preprocess_size']['inputs']['width'], width)
            self.assertEqual(graph['preprocess_size']['inputs']['crop'], 'center')
            self.assertEqual(graph['preprocess_linear']['inputs']['destination'], 'linear ACEScg')
            self.assertEqual(graph['first_frame']['inputs']['image'], ['preprocess', 0])
        classes = {n['class_type'] for graph in plan['phases'].values() for n in graph.values()}
        self.assertTrue(classes.isdisjoint({'LoadImage', 'LTXVPreprocess'}))
        guide = plan['phases']['stage1']
        self.assertEqual(guide['guide_colour']['inputs']['source'], 'sRGB')
        self.assertEqual(guide['guide']['inputs']['image'], ['guide_colour', 0])
        self.assertEqual(guide['sample']['inputs']['latent_image'], ['concat', 0])
        self.assertEqual(guide['concat']['inputs']['video_latent'], ['guide', 2])
        self.assertEqual(guide['crop_guides']['inputs']['latent'], ['separate', 0])

    def test_caches_graph_hashes_and_receipts_are_hdr_specific(self):
        project, kwargs = self.config()
        sdr_kwargs = copy.deepcopy(kwargs)
        sdr_kwargs.pop('hdr_endpoint')
        sdr_kwargs['models']['video_vae'] = ltx.QUALIFIED_MODELS['video_vae']
        sdr = ltx.build_plan(project, **sdr_kwargs)
        plan = hdr.build_native_hdr_plan(project, **kwargs)
        self.assertNotEqual(plan['key'], sdr['key'])
        self.assertEqual(plan['key'], ltx.digest(plan['basis']))
        for phase, graph in plan['phases'].items():
            self.assertEqual(plan['graph_hashes'][phase], ltx.digest(graph))
        for name, spec in plan['artifacts'].items():
            if 'key' in spec:
                self.assertEqual(spec['key'], ltx.digest({'plan': plan['key'], 'artifact': name}))
                self.assertNotEqual(spec['key'], sdr['artifacts'][name]['key'])
                fields = plan['phases'][spec['phase']][spec['node']]['inputs']
                if spec['kind'] == 'audio':
                    self.assertIn(plan['key'], fields['filename_prefix'])
                else:
                    self.assertEqual(fields['cache_key'], spec['key'])
            if 'prefix' in spec:
                self.assertIn(plan['key'], spec['prefix'])
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(ltx.bind_phase(plan, 'text', {}, output_directory=directory,
                input_directory=directory), plan['phases']['text'])
            sdr_receipt = {'plan_key': sdr['key'], 'scenario': sdr['scenario'], 'artifact': 'text'}
            with self.assertRaisesRegex(ValueError, 'another plan or scenario'):
                ltx.bind_phase(plan, 'stage1', {'text': sdr_receipt},
                    output_directory=directory, input_directory=directory)
        for field, value in (('sha', 'e' * 64), ('colour_space', 'acescct')):
            changed = copy.deepcopy(kwargs)
            changed['hdr_endpoint'][field] = value
            self.assertNotEqual(plan['key'], hdr.build_native_hdr_plan(project, **changed)['key'])
        changed = hdr.build_native_hdr_plan(project, output='hlg_video', **kwargs)
        self.assertNotEqual(plan['key'], changed['key'])

    def test_prompt_and_verified_source_identity_are_never_rekeyed(self):
        project, kwargs = self.config()
        project['config']['prompt'] = 'Read zura/ltx25/example/reference literally.'
        plan = hdr.build_native_hdr_plan(project, **kwargs)
        self.assertIn(project['config']['prompt'], plan['phases']['text']['positive']['inputs']['text'])
        self.assertEqual(plan['basis']['source'], project['source'])
        self.assertEqual(plan['basis']['opening'], project['opening_input'])

    def test_hdr_video_provenance_is_bound_to_the_approved_timeline_and_cache(self):
        project, kwargs = self.config()
        project['source']['native_hdr_video'] = {'asset_id':'e'*32,'sha':project['source']['sha'],'colour_space':'auto'}
        source = {'asset_id':'e'*32,'file':project['source']['file'],'sha':project['source']['sha'],
            'colour_space':'auto','resolved_colour_space':'pq_rec2020','start_seconds':kwargs['timeline'].get('start',0),
            'frames':kwargs['timeline']['frames'],'fps':kwargs['timeline']['fps'],'source_fps':'30000/1001',
            'source_frames':90,'first_source_frame':0,'selection':'first-at-or-after-cfr-provisional-v1','path':'private-original'}
        kwargs['timeline']['start']=0
        with self.assertRaisesRegex(ValueError,'verified together'):
            hdr.build_native_hdr_plan(project, **kwargs)
        plan=hdr.build_native_hdr_plan(project, hdr_source=source, **kwargs)
        self.assertNotIn('path',plan['basis']['native_hdr']['source'])
        self.assertEqual(plan['basis']['native_hdr']['source']['sha'],project['source']['sha'])
        for field,value in [('start_seconds',.3),('frames',8),('sha','f'*64),('file','different.mp4')]:
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'approved source interval'):
                hdr.build_native_hdr_plan(project,hdr_source={**source,field:value},**kwargs)
        video_endpoint={'kind':'video','path':'private-original','source_sha':source['sha'],
            'start_seconds':0,'colour_space':'auto','opening_key':project['opening_key']}
        video=hdr.build_native_hdr_plan(project,hdr_source=source,**{**kwargs,'hdr_endpoint':video_endpoint})
        for phase in ('stage1','upscale'):
            opening=video['phases'][phase]['opening']
            self.assertEqual(opening['class_type'],'ZuraHDRSelectNativeTimeline')
            self.assertEqual(opening['inputs']['source'],'private-original')
            self.assertEqual((opening['inputs']['start_seconds'],opening['inputs']['frame_count']),(0,1))
        with self.assertRaisesRegex(ValueError,'approved HDR video interval'):
            hdr.build_native_hdr_plan(project,hdr_source=source,**{**kwargs,'hdr_endpoint':{**video_endpoint,'start_seconds':.3}})

    def test_native_delivery_is_separate_from_sdr_viewing_proxy(self):
        for scenario in ('original', 'replacement', 'silent'):
            for output in ('hlg_video', 'hlg_and_exr', 'acescg_exr'):
                project, kwargs = self.config(scenario)
                plan = hdr.build_native_hdr_plan(project, output=output, **kwargs)
                graph = plan['phases']['decode']
                self.assertNotIn('save_video', graph)
                self.assertEqual(graph['delivery_size']['inputs']['destination'], 'HDR ACEScct')
                self.assertEqual(graph['delivery_size_linear']['inputs']['destination'], 'linear ACEScg')
                self.assertEqual('audio' in graph['preview_video']['inputs'], scenario != 'silent')
                self.assertEqual('zura_hdr_archive' in graph, output != 'hlg_video')
                self.assertEqual('zura_hdr_save_video' in graph, output != 'acescg_exr')
                if output != 'acescg_exr':
                    self.assertEqual(graph['zura_hdr_video']['inputs']['bit_depth'], 10)
                    self.assertEqual(graph['zura_hdr_hlg']['inputs']['image'], ['delivery_size', 0])
                if output != 'hlg_video':
                    self.assertEqual(graph['zura_hdr_archive']['inputs']['images'], ['delivery_size', 0])
                self.assertNotEqual(graph['preview_video']['inputs']['images'], ['delivery_size', 0])
                self.assertEqual(plan['generation_audio'], 'raw_original' if scenario == 'original' else scenario if scenario == 'replacement' else 'zero')
                self.assertIn('Not enabled in Studio', plan['qualification'])

    def test_exact_finished_frame_and_objects_retain_existing_semantics(self):
        project, kwargs = self.config('original')
        project.update(look_mode='ready', starting_asset='ready-exr')
        project['config'].update(finished_frame_position='frame', finished_frame_number=5,
                                 subject_mode='objects')
        for key in ('bbox_detector', 'pose_estimator'):
            kwargs['models'].pop(key)
            kwargs['model_pins'].pop(key)
        plan = hdr.build_native_hdr_plan(project, **kwargs)
        self.assertEqual(plan['phases']['motion']['pose']['class_type'], 'Canny')
        for phase in ('stage1', 'refine'):
            graph = plan['phases'][phase]
            self.assertEqual(graph['finished_frame']['inputs']['frame_idx'], 4)
            self.assertEqual(graph['opening']['class_type'], 'ZuraHDRLoadNativeSource')

    def test_invalid_models_approval_hdr_identity_and_memory_are_rejected(self):
        project, kwargs = self.config()
        for field, value, error in (('opening_key', 'stale', 'approved opening'),
                                    ('sha', 'invalid', 'verified EXR'),
                                    ('colour_space', 'srgb_display', 'EXR colour')):
            bad = copy.deepcopy(kwargs)
            bad['hdr_endpoint'][field] = value
            with self.assertRaisesRegex(ValueError, error):
                hdr.build_native_hdr_plan(project, **bad)
        bad = copy.deepcopy(kwargs)
        bad['models']['video_vae'] = ltx.QUALIFIED_MODELS['video_vae']
        with self.assertRaisesRegex(ValueError, 'full LTX'):
            hdr.build_native_hdr_plan(project, **bad)
        with self.assertRaisesRegex(ValueError, 'HDR output'):
            hdr.build_native_hdr_plan(project, output='sdr', **kwargs)
        project['approval'] = 'stale'
        with self.assertRaisesRegex(ValueError, 'Approve the current source'):
            hdr.build_native_hdr_plan(project, **kwargs)
        project['approval'] = kwargs['approval_key']
        project['config']['resolution'] = 1920
        kwargs['timeline']['frames'] = 120
        with self.assertRaisesRegex(ValueError, 'memory budget'):
            hdr.build_native_hdr_plan(project, **kwargs)


if __name__ == '__main__':
    unittest.main()
