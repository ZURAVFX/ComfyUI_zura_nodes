"""Actual Studio graph routing keeps adapters on the selected video model."""
import copy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

import test_artist_studio as fixtures

studio = fixtures.studio


class StudioCustomLoraTests(fixtures.unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'character.safetensors'
        header = json.dumps({'__metadata__': {'base_model': 'minimax_h3'}, 'diffusion_model.x': {}}).encode()
        self.path.write_bytes(len(header).to_bytes(8, 'little') + header)
        self.lora = {'name': self.path.name, 'strength': .7, 'confirm_unknown': False}
        self.graph = json.loads((Path(__file__).parents[1] / 'artist_studio/graphs/OpenJutsu_Experimental.json').read_text())

    def apply(self, graph=None, stage='h3', config=None):
        config = config or {'engine': 'h3', 'workflow_mode': 'swap', 'custom_loras': [self.lora]}
        with patch.object(studio.folder_paths, 'get_filename_list', return_value=[self.path.name], create=True), \
             patch.object(studio.folder_paths, 'get_full_path', return_value=str(self.path), create=True):
            return studio.apply_video_loras({'config': config}, stage, graph or self.graph)

    def test_openjutsu_base_and_existing_loras_remain_connected(self):
        result = self.apply()
        self.assertEqual(result['zura_custom_lora_0_0']['inputs']['model'], ['1', 0])
        self.assertEqual(result['zura_custom_lora_0_0']['inputs']['lora_name'], self.path.name)
        consumers = [node for node in result.values() if node.get('inputs', {}).get('model') == ['zura_custom_lora_0_0', 0]]
        self.assertTrue(consumers, 'The sampled OpenJutsu model must consume the selected adapter')
        self.assertEqual(self.graph['1']['class_type'], 'UNETLoader')

    def test_preparation_is_not_treated_as_a_sampling_graph(self):
        graph = {'wan_save': {'class_type': 'ZuraWanSavePreparationPart', 'inputs': {}}}
        config = {'engine': 'wan', 'custom_loras': [self.lora]}
        self.assertEqual(self.apply(graph=graph, stage='wan', config=config), graph)

    def test_native_animate2_and_relight_graphs_consume_matching_adapters(self):
        from ComfyUI_zura_nodes.artist_studio.wan_animate2 import build_animate2_graph
        graphs = [
            ('wan_animate_2', 'wan2', {'engine': 'wan2'},
             build_animate2_graph('reference.png', 'source.mp4', 'a character', frame_count=9, width=832, height=480)),
            ('wan_2.1', 'wan21_relight', {'engine': 'h3', 'workflow_mode': 'relight', 'relight_engine': 'wan21'},
             json.loads((Path(__file__).parents[1] / 'artist_studio/graphs/07_Wan21_Relight_Recipe.json').read_text())['graph']),
        ]
        for family, stage, config, graph in graphs:
            with self.subTest(stage=stage):
                header = json.dumps({'__metadata__': {'base_model': family}, 'diffusion_model.x': {}}).encode()
                self.path.write_bytes(len(header).to_bytes(8, 'little') + header)
                result = self.apply(graph=graph, stage=stage, config={**config, 'custom_loras': [self.lora]})
                self.assertIn('zura_custom_lora_0_0', result)
                self.assertTrue(any(node.get('inputs', {}).get('model') == ['zura_custom_lora_0_0', 0]
                                    for node in result.values()))

    def test_unqualified_second_sampler_is_gated(self):
        self.assertIsNone(studio.custom_lora_family({'engine': 'wan', 'lip_sync': True}))
        self.assertIsNone(studio.custom_lora_family({'engine': 'h3', 'delivery_mode': 'enhanced1080'}))
        for stage in ('wan_speech', 'h3_enhance', 'ltx25_stage1', 'ltx25_refine', 'restyle'):
            with self.subTest(stage=stage), self.assertRaisesRegex(ValueError, 'available'):
                studio.build_graph({'config': {'custom_loras': [self.lora]}}, stage)

    def test_lo_ra_config_does_not_share_state_or_accept_malformed_entries(self):
        source = {'custom_loras': [copy.deepcopy(self.lora)]}
        first = studio.clean_config(source)
        first['custom_loras'][0]['strength'] = 1.5
        self.assertEqual(source['custom_loras'][0]['strength'], .7)
        with self.assertRaises(ValueError):
            studio.clean_config({'custom_loras': [{'name': ''}]})

    def test_starting_image_loras_apply_to_image_model_only(self):
        from ComfyUI_zura_nodes.artist_studio.opening_models import MODELS
        for model, declared in [('klein9b', 'flux2_klein_9b'), ('flux3', 'flux3_klein'),
                                ('qwen2511', 'qwen_image_2511'), ('qwen21', 'qwen_image_2.1')]:
            with self.subTest(model=model):
                header=json.dumps({'__metadata__': {'base_model': declared}, 'diffusion_model.x': {}}).encode()
                self.path.write_bytes(len(header).to_bytes(8,'little')+header)
                project=fixtures.SharedEngineTests().project()
                project['config'].update(opening_model=model, opening_loras=[self.lora])
                project['references']=[project['character']]
                with patch.object(studio, 'assert_approved'), patch.object(studio, 'check_asset'), \
                     patch.object(studio.folder_paths, 'get_filename_list', return_value=[self.path.name], create=True), \
                     patch.object(studio.folder_paths, 'get_full_path', return_value=str(self.path), create=True):
                    graph=studio.build_graph(project, 'design', use_cache=False)
                self.assertIn('zura_custom_lora_0_0', graph)
                self.assertEqual(graph['zura_custom_lora_0_0']['inputs']['lora_name'],self.path.name)
                self.assertEqual(graph['92:107']['inputs']['unet_name'],MODELS[model]['files'][0][1])
                self.assertTrue(any(n.get('inputs',{}).get('model')==['zura_custom_lora_0_0',0] for n in graph.values()))

    def test_starting_image_lora_changes_invalidate_old_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller=studio.Studio.__new__(studio.Studio)
            controller.store=studio.Store(tmp);controller.collect=lambda project: project
            project=fixtures.SharedEngineTests().project()
            project['approval']=studio.prep_key(project);project['prepared_key']=project['approval']
            controller.configure(project,{**project['config'],'opening_loras':[self.lora]})
            self.assertIsNone(project['opening_input'])
            self.assertIsNone(project['opening_approval'])
