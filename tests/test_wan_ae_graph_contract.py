"""Native Wan export recognition, without model execution or live state."""
import copy
import importlib
import json
import unittest
from unittest.mock import patch

import test_artist_studio as fixture
import test_wan21_relight as recipe

studio = fixture.studio
wan21 = importlib.import_module(studio.__package__ + '.wan21_relight')
contracts = importlib.import_module(studio.__package__.rsplit('.', 1)[0] + '.comfylink.frame_contract')


class WanAEGraphContractTests(unittest.TestCase):
    def graph(self):
        project = recipe.Wan21RelightTests().project()
        contract = {'schemaVersion': 1, 'sessionId': 'a' * 32, 'frameCount': 9,
                    'modelFrames': 9, 'trimFrames': 9, 'width': 1920, 'height': 1080,
                    'frameRate': {'numerator': 25, 'denominator': 1}}
        project['config'] = studio.clean_config({**project['config'], 'ae_frame_contract': contract})
        with patch.object(studio, 'assert_approved'), patch.object(wan21, '_output_size', return_value=(1280, 704)), \
                patch.object(wan21, '_source_size', return_value=(1920, 1080)):
            graph = wan21.build_studio_graph(project, lambda asset: asset['file'])
        return graph, contract

    def test_only_complete_wan_export_owns_its_source_raster_boundary(self):
        graph, contract = self.graph()
        original = copy.deepcopy(graph)
        prepared = contracts.prepare_frame_contract_graph(graph, contract, 'relight')
        self.assertEqual(graph, original)
        self.assertEqual(prepared['wan21_video'], graph['wan21_video'])
        self.assertEqual(prepared['272:407:276:252']['inputs']['length'], graph['272:407:276:252']['inputs']['length'])
        self.assertFalse(any(n['class_type'] == 'ZuraComfyLinkMatchFrames' for n in prepared.values()))
        output = prepared['wan21_export']['inputs']
        self.assertEqual((output['target_frames'], output['model_stride']), (9, 0))
        self.assertEqual(json.loads(output['ae_frame_contract']), contract)
        self.assertEqual((output['output_width'], output['output_height']), (1920, 1080))
        self.assertIs(contracts.prepare_frame_contract_graph(graph, None, 'relight'), graph)

    def test_altered_routes_keep_the_tensor_guard(self):
        graph, contract = self.graph()
        changes = [
            ('wan21_export', 'clip_details', ['wan21_shot', 0]),
            ('wan21_export', 'output_width', 1280),
            ('wan21_video', 'fps', 25),
            ('wan21_shot', 'preserve_source_timing', False),
            ('wan21_shot', 'approved_shot_id', 'another-shot'),
            ('272:402', 'length', 9),
            ('272:402', 'batch_index', 1),
            ('wan21_hold_result', 'stride', 8),
            ('272:407:276:252', 'length', 9),
        ]
        for identity, field, value in changes:
            with self.subTest(identity=identity, field=field):
                altered = copy.deepcopy(graph)
                altered[identity]['inputs'][field] = value
                prepared = contracts.prepare_frame_contract_graph(altered, contract, 'relight')
                self.assertTrue(any(n['class_type'] == 'ZuraComfyLinkMatchFrames' for n in prepared.values()))
        for mode in ('swap', 'paintout', 'viewport'):
            with self.subTest(mode=mode):
                prepared = contracts.prepare_frame_contract_graph(graph, contract, mode)
                self.assertTrue(any(n['class_type'] == 'ZuraComfyLinkMatchFrames' for n in prepared.values()))

    def test_another_output_does_not_acquire_the_native_export_exception(self):
        graph, contract = self.graph()
        graph['save'] = {'class_type': 'SaveVideo', 'inputs': {'video': ['wan21_video', 0]}}
        prepared = contracts.prepare_frame_contract_graph(graph, contract, 'relight')
        self.assertTrue(any(n['class_type'] == 'ZuraComfyLinkMatchFrames' for n in prepared.values()))


if __name__ == '__main__':
    unittest.main()
