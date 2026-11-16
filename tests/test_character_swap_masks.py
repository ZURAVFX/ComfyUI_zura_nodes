import unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_artist_studio as fixtures
from importlib import import_module
import torch
m = import_module(fixtures.NAME + '.character_mask')

class CharacterMaskTests(unittest.TestCase):
    def test_mask_video_follows_trim_and_resizes(self):
        frames=torch.zeros(48,4,4,3);frames[24:,1:3,1:3]=1
        video=SimpleNamespace(get_components=lambda:SimpleNamespace(images=frames,frame_rate=24))
        mask,=m.ZuraCharacterMaskFrames().match(video,torch.zeros(12,8,8,3),1)
        self.assertEqual(tuple(mask.shape),(12,8,8));self.assertGreater(mask.max().item(),.9)
        with self.assertRaisesRegex(ValueError,'shorter'):
            m.ZuraCharacterMaskFrames().match(video,torch.zeros(80,8,8,3))
    def test_custom_mask_bypasses_tracking_without_dangling_links(self):
        s=fixtures.studio
        p=fixtures.SharedEngineTests().project()
        identity='b'*32
        p['config'].update(engine='h3',h3_character_method='openjutsu',mask_video=identity)
        p['selection_mask']={'id':identity,'file':'mask.mov','asset_kind':'video'}
        with patch.object(s,'check_asset'):
            graph=s.build_graph(p,'prepare')
        self.assertNotIn('10',graph)
        self.assertNotIn('zura_join_tracking_masks',graph)
        self.assertEqual(graph['12']['inputs']['mask'],['zura_character_mask_frames',0])
        for node in graph.values():
            for value in node['inputs'].values():
                if isinstance(value,list) and len(value)==2 and isinstance(value[0],str):
                    self.assertIn(value[0],graph)
    def test_automatic_prompt_changes_review_identity_and_detector(self):
        s=fixtures.studio;p=fixtures.SharedEngineTests().project();p['config']['mask_prompt']='person, red coat'
        first=s.prep_key(p)
        with patch.object(s,'check_asset'):g=s.build_graph(p,'prepare')
        self.assertEqual(g['7']['inputs']['text'],'person, red coat')
        p['config']['mask_prompt']='person, blue coat';self.assertNotEqual(first,s.prep_key(p))

    def test_paired_mask_keeps_all_frames_when_movie_clock_changes(self):
        values=torch.linspace(0,1,17)[:,None,None,None].expand(17,4,4,3).clone()
        video=SimpleNamespace(get_components=lambda:SimpleNamespace(images=values,frame_rate=30000/1001))
        masks,=m.ZuraCharacterMaskFrames().match(video,torch.zeros(17,4,4,3))
        torch.testing.assert_close(masks[:,0,0],torch.linspace(0,1,17))
