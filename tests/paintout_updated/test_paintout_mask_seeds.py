"""A newly added segment must track its own subject, never the merged mask."""
import base64
import io
import json
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from test_paintout_editor_store import editor, core, package


class MaskSeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.source = self.root / 'source.mp4'
        self.source.write_bytes(b'fixture')
        self.identity = dict(path=str(self.source), fingerprint='source-v1', width=5, height=5, count=8)
        self.description = dict(path=str(self.source), width=5, height=5, count=8, kind='video')
        browser = types.ModuleType(package.__name__ + '.browser')
        browser.checked_path = lambda value: pathlib.Path(value).resolve(strict=True)
        browser.grant = lambda value: '/seed/' + pathlib.Path(value).parent.name + '/' + pathlib.Path(value).name
        self.patches = [patch.object(editor, 'project_root', return_value=self.root / 'projects'),
                        patch.dict('sys.modules', {package.__name__ + '.browser': browser}),
                        patch.object(core, 'describe', return_value=self.description),
                        patch.object(editor, 'source_identity', return_value=self.identity)]
        for item in self.patches:
            item.start()
        self.project = editor.save_project(data={'draft': {'source': str(self.source)}})['id']
        self.old = np.zeros((5, 5), np.float32)
        self.old[1, 1] = 1
        self.new = np.zeros((5, 5), np.float32)
        self.new[3, 3] = 1

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def commit(self, mask, operation='replace'):
        return editor.commit_mask_pass(self.project, self.identity, {2: mask}, operation,
                                       editor.load_project(self.project)['revision'], {'frame': 2})

    def test_add_seed_is_raw_hard_incoming_and_existing_coverage_is_preserved(self):
        self.commit(self.old)
        incoming = self.new.copy()
        incoming[0, 0] = .2
        incoming[0, 1] = .8
        result = self.commit(incoming, 'add')
        seed = np.asarray(Image.open(result['seed_file']))
        np.testing.assert_array_equal(seed, (incoming >= .5) * 255)
        self.assertFalse(seed[1, 1])
        self.assertTrue(editor.read_project_mask(self.project, 2)[1, 1])
        response = editor.project_response(editor.load_project(self.project))['mask_seed']
        self.assertEqual((response['frame'], response['mask_revision'], response['operation']),
                         (2, result['revision'], 'add'))
        self.assertEqual(response['url'], f"/seed/{result['revision']}/seed.png")

    def test_revision_seed_is_immutable_and_undo_restores_its_own_seed(self):
        first = self.commit(self.old)
        original = pathlib.Path(first['seed_file']).read_bytes()
        self.commit(self.new, 'add')
        self.assertEqual(pathlib.Path(first['seed_file']).read_bytes(), original)
        document = editor.load_project(self.project)
        editor.select_mask_revision(self.project, first['revision'], document['revision'])
        seed = editor.project_response(editor.load_project(self.project))['mask_seed']
        self.assertEqual(seed['mask_revision'], first['revision'])
        np.testing.assert_array_equal(editor.read_project_mask(self.project, 2), self.old)

    def test_explicit_add_choice_returns_only_the_chosen_seed(self):
        self.commit(self.old)
        choices = np.stack([self.new, np.fliplr(self.new)])
        selection = editor.save_mask_choices(self.project, self.identity, 2, choices, 'add',
                                             editor.load_project(self.project)['revision'])
        response = editor.choose_mask_candidate(dict(project=self.project, token=selection['token'], index=0,
            source=str(self.source), frame=2, expected_revision=editor.load_project(self.project)['revision']))
        manifest = editor._mask_manifest(self.project)
        np.testing.assert_array_equal(np.asarray(Image.open(manifest['seed']['path'])) / 255, self.new)
        self.assertEqual(response['mask_seed']['operation'], 'add')
        np.testing.assert_array_equal(editor.read_project_mask(self.project, 2), np.maximum(self.old, self.new))

    def test_tampered_or_foreign_seed_is_rejected_before_grant(self):
        result = self.commit(self.new)
        manifest_path = pathlib.Path(result['path']) / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        original = pathlib.Path(result['seed_file']).read_bytes()
        pathlib.Path(result['seed_file']).write_bytes(original + b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            editor.project_response(editor.load_project(self.project))
        pathlib.Path(result['seed_file']).write_bytes(original)
        outside = self.root / 'outside.png'
        outside.write_bytes(original)
        manifest['seed']['path'] = str(outside)
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'does not belong'):
            editor.project_response(editor.load_project(self.project))

    def test_single_frame_paint_result_returns_seed_url_separate_from_add_union(self):
        import torch
        self.commit(self.old)
        stream = io.BytesIO()
        Image.fromarray((self.new * 255).astype(np.uint8)).save(stream, format='PNG')
        paint = 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()
        with patch.object(core, 'selected_space', return_value='srgb_display'), \
             patch.object(editor, '_frame_batch', return_value=torch.zeros((1, 5, 5, 3))):
            result = editor.ZuraPaintoutMaskPass().run(str(self.source), self.project, 2, 2, 1,
                'srgb_display', 'add', paint_mask=paint, expected_revision=editor.load_project(self.project)['revision'])
        summary = result['ui']['zura_mask'][0]
        self.assertEqual(summary['seed_frame'], 2)
        self.assertEqual(summary['seed_revision'], summary['revision'])
        self.assertEqual(summary['seed_url'], f"/seed/{summary['revision']}/seed.png")
        np.testing.assert_array_equal(np.asarray(Image.open(summary['seed_file'])) / 255, self.new)
        np.testing.assert_array_equal(editor.read_project_mask(self.project, 2), np.maximum(self.old, self.new))

    def test_reselected_replacement_keeps_existing_foreground_protection(self):
        import torch
        self.commit(np.ones_like(self.old))
        self.commit(self.new, 'protect')
        protected_before = editor._mask_manifest(self.project)['protection_files']['2']
        protected_bytes = pathlib.Path(protected_before).read_bytes()
        stream = io.BytesIO()
        Image.fromarray(np.full((5, 5), 255, np.uint8)).save(stream, format='PNG')
        paint = 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()
        with patch.object(core, 'selected_space', return_value='srgb_display'), \
             patch.object(editor, '_frame_batch', return_value=torch.zeros((1, 5, 5, 3))):
            editor.ZuraPaintoutMaskPass().run(str(self.source), self.project, 2, 2, 1,
                'srgb_display', 'replace', paint_mask=paint, expected_revision=editor.load_project(self.project)['revision'])
        self.assertFalse(editor.read_project_mask(self.project, 2)[3, 3])
        self.assertTrue(editor.read_project_mask(self.project, 2)[1, 1])
        protection_after = editor._mask_manifest(self.project)['protection_files']['2']
        self.assertEqual(pathlib.Path(protection_after).read_bytes(), protected_bytes)


if __name__ == '__main__':
    unittest.main()
