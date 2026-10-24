"""Non-human source edits must not disappear behind an empty person mask."""
import copy
import asyncio
from unittest.mock import patch
import test_artist_studio as fixture
from ComfyUI_zura_nodes.artist_studio.opening_subject import directed_source_subject, missing_opening_selection

studio = fixture.studio


class OpeningSubjectTests(fixture.unittest.TestCase):
    def project(self):
        p = fixture.SharedEngineTests().project()
        p['config']['image_prompt'] = 'replace the nugget with the character'
        return p

    def graph(self, p, stage):
        with patch.object(studio, 'assert_approved'), patch.object(studio, 'check_asset'):
            return studio.build_graph(p, stage, use_cache=False)

    def test_explicit_nonhuman_target_drives_native_detection(self):
        p = self.project()
        g = self.graph(p, 'prepare')
        self.assertEqual(g['7']['inputs']['text'], 'nugget')
        self.assertFalse(g['8']['inputs']['individual_masks'])
        self.assertEqual(g['9']['inputs']['performer'], -1)
        self.assertEqual(p['config']['mask_method'], 'auto')

    def test_manual_selection_and_other_tasks_take_precedence(self):
        p = self.project()
        for changes in ({'mask_method':'text'}, {'mask_method':'points'}, {'scope':'head'},
                        {'workflow_mode':'relight'}, {'edit_area':'scene'}, {'preserve_people':True}):
            c = {**p['config'], **changes}
            self.assertIsNone(directed_source_subject(c))
        for prompt in ('a new outfit', 'replace him with the character', 'replace the man with my character', 'replace everything with a garden'):
            self.assertIsNone(directed_source_subject({**p['config'], 'image_prompt':prompt}))

    def test_target_changes_invalidate_selection_but_style_changes_do_not(self):
        p = self.project()
        first = studio.prep_key(p)
        p['config']['image_prompt'] += ', wearing a red coat'
        self.assertEqual(studio.prep_key(p), first)
        p['config']['image_prompt'] = 'replace the mascot with the character'
        self.assertNotEqual(studio.prep_key(p), first)

    def test_nonhuman_opening_allows_new_silhouette_and_keeps_reference_latents(self):
        p = self.project()
        original = copy.deepcopy(p)
        g = self.graph(p, 'design')
        self.assertEqual(p, original)
        self.assertEqual(g['zura_opening_original_resolution']['inputs']['image'], ['92:105', 0])
        self.assertNotIn('zura_masked_look', g)
        self.assertEqual(g['92:103']['inputs']['positive'], ['92:131', 0])
        text = g['127']['inputs']['value']
        self.assertIn('does not need to be human', text)
        self.assertIn('silhouette', text)
        self.assertIn('replace the nugget with the character', text)

    def test_missing_opening_mask_does_not_erase_a_generated_person_edit(self):
        p = self.project()
        p['config']['image_prompt'] = 'a person in a red coat'
        p['tracking_coverage'] = {'shots':[{'start':0, 'near_empty_ranges':[{'start':0,'end':48}]}]}
        self.assertTrue(missing_opening_selection(p))
        g = self.graph(p, 'design')
        self.assertEqual(g['zura_opening_original_resolution']['inputs']['image'], ['92:105', 0])
        p['tracking_coverage']['shots'][0]['near_empty_ranges'][0]['start'] = 12
        self.assertFalse(missing_opening_selection(p))
        self.assertIn('zura_masked_look', self.graph(p, 'design'))

    def test_empty_source_selection_blocks_video_before_queueing(self):
        p = self.project()
        p['tracking_coverage'] = {'shots':[{'start':0, 'near_empty_ranges':[{'start':0,'end':48}]}]}
        controller = studio.Studio.__new__(studio.Studio)
        controller.collect = lambda project: project
        with self.assertRaisesRegex(ValueError, 'source subject was not selected'):
            asyncio.run(controller.action(p, 'animate', {}))


if __name__ == '__main__':
    fixture.unittest.main()
