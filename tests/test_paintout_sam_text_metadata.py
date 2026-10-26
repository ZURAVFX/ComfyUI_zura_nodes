import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import numpy as np
import torch
from test_paintout_editor_store import editor, core, package


class SamTextMetadataTests(unittest.TestCase):
    def test_plain_conditioning_requests_24_and_preserves_original_tensors_and_metadata(self):
        embedding = torch.zeros((1, 3, 4))
        attention = torch.ones((1, 3))
        original = [[embedding, {'attention_mask': attention, 'custom': {'kept': True}}]]
        adapted = editor._sam_subject_conditioning(original)
        self.assertIsNot(adapted, original)
        self.assertIsNot(adapted[0][1], original[0][1])
        entry = adapted[0][1]['sam3_multi_cond'][0]
        self.assertIs(entry['cond'], embedding)
        self.assertIs(entry['attention_mask'], attention)
        self.assertEqual(entry['max_detections'], 24)
        self.assertNotIn('sam3_multi_cond', original[0][1])
        self.assertEqual(original[0][1]['custom'], {'kept': True})

    def test_existing_multi_entries_are_copied_and_share_a_24_detection_budget(self):
        embedding = torch.zeros((1, 3, 4))
        entries = [{'cond': embedding, 'attention_mask': None, 'max_detections': 10},
                   {'cond': embedding, 'attention_mask': None, 'max_detections': 100},
                   {'cond': embedding, 'attention_mask': None, 'max_detections': 5}]
        original = [[embedding, {'sam3_multi_cond': entries}]]
        adapted = editor._sam_subject_conditioning(original)[0][1]['sam3_multi_cond']
        self.assertEqual([e['max_detections'] for e in adapted], [10, 14])
        self.assertEqual([e['max_detections'] for e in entries], [10, 100, 5])
        self.assertIsNot(adapted[0], entries[0])
        self.assertIs(adapted[0]['cond'], embedding)

    def test_missing_attention_is_explicit_none_and_empty_conditioning_is_rejected(self):
        embedding = torch.zeros((1, 3, 4))
        self.assertIsNone(editor._sam_subject_conditioning([[embedding, {}]])[0][1]['sam3_multi_cond'][0]['attention_mask'])
        with self.assertRaises(ValueError):
            editor._sam_subject_conditioning([])

    def run_detection(self, with_points):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / 'source.png'
            source.write_bytes(b'fixture')
            description = dict(path=str(source), width=40, height=40, count=1)
            embedding = torch.zeros((1, 3, 4))
            conditioning = [[embedding, {'attention_mask': None}]]
            captured = {}
            class Detect:
                @classmethod
                def execute(cls, **kwargs):
                    captured.update(kwargs)
                    masks = torch.zeros((1 if with_points else 2, 40, 40))
                    masks[0, 5:15, 5:15] = 1
                    if not with_points:
                        masks[1, 20:30, 20:30] = 1
                    return (masks,)
            browser = types.ModuleType(package.__name__ + '.browser')
            browser.checked_path = lambda value: pathlib.Path(value)
            browser.grant = lambda value: '/fixture/' + pathlib.Path(value).name
            nodes = types.SimpleNamespace(NODE_CLASS_MAPPINGS={'SAM3_Detect': Detect})
            with patch.object(editor, 'project_root', return_value=root / 'projects'), \
                 patch.object(core, 'describe', return_value=description), \
                 patch.object(core, 'selected_space', return_value='srgb_display'), \
                 patch.object(editor, '_frame_batch', return_value=torch.zeros((1, 40, 40, 3))), \
                 patch.dict(sys.modules, {'nodes': nodes, package.__name__ + '.browser': browser}):
                project = editor.save_project(data={'draft': {'source': str(source)}})
                result = editor.ZuraPaintoutMaskPass().run(str(source), project['id'], 0, 0, 1, 'auto', 'replace',
                    model=object(), conditioning=conditioning, positive_coords='[{"x":10,"y":10}]' if with_points else '[]', expected_revision=1)
                self.assertTrue(captured['individual_masks'])
                self.assertNotIn('sam3_multi_cond', conditioning[0][1])
                if with_points:
                    self.assertNotIn('conditioning', captured)
                    self.assertIn('positive_coords', captured)
                    self.assertIsNotNone(editor.load_project(project['id'])['mask_revision'])
                else:
                    entry = captured['conditioning'][0][1]['sam3_multi_cond'][0]
                    self.assertEqual(entry['max_detections'], 24)
                    self.assertIs(entry['cond'], embedding)
                    self.assertEqual(len(result['ui']['zura_mask_choices'][0]['choices']), 2)
                    self.assertIsNone(editor.load_project(project['id'])['mask_revision'])
                    self.assertEqual(editor.load_project(project['id'])['mask_history'], [])

    def test_native_text_dispatch_uses_multi_metadata_and_waits_for_subject_choice(self):
        self.run_detection(False)

    def test_point_detection_path_does_not_receive_text_conditioning(self):
        self.run_detection(True)


if __name__ == '__main__':
    unittest.main()
