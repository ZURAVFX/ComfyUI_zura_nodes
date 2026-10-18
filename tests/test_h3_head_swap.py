"""Contracts for the isolated, unqualified H3 head-swap comparison."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('zura_head_swap_dev', ROOT / 'artist_studio/h3_head_swap.py')
head = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = head
spec.loader.exec_module(head)


class HeadSwapTests(unittest.TestCase):
    def request(self):
        return head.HeadSwapRequest('source.mp4', 'portrait.png', True)

    def test_inference_uses_masked_source_crop_and_landmark_reference(self):
        graph = head.build_graph(self.request())
        self.assertEqual(graph['source_latent']['inputs']['images'], ['crop', 0])
        self.assertEqual(graph['source_latent']['inputs']['latent_mask'], ['latent_mask', 2])
        self.assertEqual(graph['source_latent']['inputs']['audio_mode'], 'keep')
        self.assertEqual(graph['sample']['inputs']['latent_image'], ['source_latent', 0])
        refs = graph['references']['inputs']
        self.assertEqual(refs['ref_videos.ref_video_0'], ['face_motion', 0])
        self.assertEqual(refs['ref_images.ref_image_0'], ['portrait_white', 0])
        self.assertNotIn('ref_audios.ref_audio_0', refs)
        self.assertEqual(graph['face_motion']['inputs']['detect_face'], 'enable')
        self.assertEqual(graph['references']['inputs']['length'], ['crop_size', 2])
        self.assertEqual(graph['uncrop']['inputs']['cropped_masks'], ['blend_mask', 0])
        self.assertEqual(graph['uncrop']['inputs']['bboxes'], ['crop', 2])
        self.assertEqual(graph['pad']['inputs'], {'images':['components',0], 'multiplier':17, 'remainder':5})
        self.assertEqual(graph['trim']['inputs']['num_frames'], ['crop_size', 2])
        self.assertEqual(graph['uncrop']['inputs']['cropped_images'], ['trim', 0])
        self.assertEqual(graph['uncrop']['inputs']['original_images'], ['pad', 0])
        self.assertEqual(graph['trim_output']['inputs']['num_frames'], ['source_size', 2])
        self.assertEqual(graph['video']['inputs']['images'], ['trim_output', 0])
        self.assertEqual(graph['export']['inputs']['clip_details'], ['select', 1])

    def test_invalid_or_unqualified_requests_cannot_build(self):
        for change in ({'source_has_audio':False}, {'source_has_audio':'yes'},
                       {'duration_seconds':6}, {'duration_seconds':float('inf')},
                       {'start_seconds':float('nan')}, {'seed':-1},
                       {'object_indices':'0,invalid'}, {'reference_size':'unbounded'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                head.build_graph(replace(self.request(), **change))

    def test_static_schema_and_all_edges_against_supplied_snapshot(self):
        filename = os.environ.get('ZURA_OBJECT_INFO_PATH')
        if not filename:
            self.skipTest('Set ZURA_OBJECT_INFO_PATH to a Comfy schema snapshot')
        info = json.loads(Path(filename).read_text(encoding='utf-8-sig'))
        graph = head.build_graph(self.request())
        for key, node in graph.items():
            with self.subTest(node=key):
                schema = info[node['class_type']]
                slots = {**schema['input'].get('required', {}), **schema['input'].get('optional', {})}
                required = set(schema['input'].get('required', {}))
                for name, slot in list(slots.items()):
                    if slot[0] == 'COMFY_DYNAMICCOMBO_V3':
                        choice = next(x for x in slot[1]['options'] if x['key'] == node['inputs'][name])
                        nested = choice['inputs']
                        slots.update({name+'.'+k:v for k,v in {**nested.get('required',{}),**nested.get('optional',{})}.items()})
                        required.update(name+'.'+k for k in nested.get('required',{}))
                self.assertTrue(required <= set(node['inputs']), required-set(node['inputs']))
                for name, value in node['inputs'].items():
                    slot = slots.get(name)
                    if slot is None:
                        prefix, field = name.split('.', 1)
                        auto = slots[prefix]
                        self.assertEqual(auto[0], 'COMFY_AUTOGROW_V3')
                        template = auto[1]['template']
                        self.assertTrue(field.startswith(template['prefix']))
                        slot = next(iter(template['input']['required'].values()))
                    expected = slot[0]
                    if isinstance(value, list):
                        parent, index = value
                        output = info[graph[parent]['class_type']]['output'][index]
                        self.assertEqual(output, expected)
                    elif isinstance(expected, list):
                        if (key,name) not in [('portrait','image'),('source','file')]:
                            self.assertIn(value, expected)
                    elif expected == 'COMBO':
                        if (key,name) not in [('portrait','image'),('source','file')]:
                            self.assertIn(value, slot[1]['options'])


if __name__ == '__main__':
    unittest.main()
