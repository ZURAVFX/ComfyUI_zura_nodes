"""A retry edits original footage and cannot recast neighbouring performers."""
import ast
import copy
from pathlib import Path
from unittest.mock import patch
import torch
import test_artist_studio as fixture
from ComfyUI_zura_nodes.artist_studio.opening_edit import target_position

studio = fixture.studio


class OpeningEditTests(fixture.unittest.TestCase):
    def project(self, mode='motion'):
        p = fixture.SharedEngineTests().project()
        p['config'] = studio.clean_config({**p['config'], 'engine': 'wan2' if mode == 'motion' else 'wan',
            'workflow_mode': mode, 'image_prompt': 'replace the center character with my reference character', 'start': 1.5})
        p['opening_input'] = {'file': 'previous-generation.png', 'sha': 'previous'}
        return p

    def graph(self, p, stage='design'):
        with patch.object(studio, 'assert_approved'), patch.object(studio, 'check_asset'):
            return studio.build_graph(p, stage, use_cache=False)

    def test_original_video_slice_is_always_source_even_after_retry(self):
        p = self.project()
        initial = self.graph(p)
        p['opening_input']['file'] = 'another-generated-image.png'
        retry = self.graph(p)
        self.assertEqual(initial, retry)
        self.assertEqual(retry['zura_original_video']['inputs']['file'], 'source.mp4')
        self.assertEqual(retry['124']['inputs']['video'], ['zura_original_slice', 0])
        self.assertEqual(retry['zura_original_slice']['inputs']['start_time'], 1.5)
        self.assertLessEqual(retry['zura_original_slice']['inputs']['duration'], 0.1)
        self.assertNotIn('another-generated-image.png', str(retry))

    def test_motion_video_settings_cannot_make_image_edit_replace_whole_scene(self):
        p = self.project()
        before = copy.deepcopy(p)
        g = self.graph(p)
        self.assertEqual(p, before)
        text = g['127']['inputs']['value']
        self.assertIn('center character', text)
        self.assertIn('Preserve every other person exactly', text)
        self.assertNotIn('Finish the whole scene using any environment', text)
        self.assertEqual(g['zura_opening_person']['inputs']['text'], 'person:20')
        self.assertTrue(g['zura_opening_detect']['inputs']['individual_masks'])
        self.assertEqual(g['zura_opening_choose']['inputs']['position'], 'centre')
        self.assertEqual(g['92:104']['inputs']['latent_image'], ['zura_opening_latent_mask', 0])
        self.assertEqual(g['zura_opening_latent_mask']['inputs']['samples'], ['92:127', 0])
        self.assertEqual(g['zura_opening_original_resolution']['inputs']['width'], ['zura_original_size', 0])
        self.assertEqual(g['zura_opening_preserve_source']['inputs']['destination'], ['125', 0])

    def test_masked_swap_selects_individual_centre_person_and_invalidates_old_review(self):
        p = self.project('swap')
        centre_key = studio.prep_key(p)
        g = self.graph(p, 'prepare')
        self.assertEqual(g['7']['inputs']['text'], 'person:20')
        self.assertTrue(g['8']['inputs']['individual_masks'])
        self.assertEqual(g['9']['inputs']['position'], 'centre')
        p['config']['image_prompt'] = 'replace the right character with my reference character'
        self.assertNotEqual(studio.prep_key(p), centre_key)

    def test_actual_performer_node_respects_spatial_target_instead_of_largest(self):
        path = Path(studio.__file__).with_name('__init__.py')
        node = next(n for n in ast.parse(path.read_text(encoding='utf8')).body
                    if isinstance(n, ast.ClassDef) and n.name == 'GenjChoosePerformer')
        scope = {'torch': torch, 'CATEGORY': 'test'}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(path), 'exec'), scope)
        masks = torch.zeros(3, 100, 100)
        masks[0, 20:70, 5:20] = 1
        masks[1, 20:75, 42:54] = 1
        masks[2, 5:95, 60:98] = 1
        choose = scope['GenjChoosePerformer']().choose
        self.assertTrue(torch.equal(choose(masks, -1, 'auto')[0], masks[2:3]))
        self.assertTrue(torch.equal(choose(masks, -1, 'centre')[0], masks[1:2]))
        self.assertTrue(torch.equal(choose(masks, -1, 'left')[0], masks[0:1]))
        self.assertTrue(torch.equal(choose(masks, -1, 'right')[0], masks[2:3]))
        self.assertTrue(torch.equal(choose(masks, 0, 'right')[0], masks[0:1]))

    def test_only_clear_spatial_people_are_treated_as_spatial_selection(self):
        self.assertEqual(target_position('centre character'), 'centre')
        self.assertEqual(target_position('leftmost person'), 'left')
        for target in ('nugget', 'everything', 'right object', 'centre character and the man'):
            self.assertEqual(target_position(target), 'auto')


if __name__ == '__main__':
    fixture.unittest.main()
