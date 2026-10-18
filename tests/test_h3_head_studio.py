"""Head-only Studio routing must never silently replace the approved full-character path."""
import copy
import importlib
import types
from unittest.mock import patch
import test_artist_studio as fixtures
studio = fixtures.studio
head = importlib.import_module(fixtures.NAME + '.h3_head_swap')
availability = importlib.import_module(fixtures.NAME + '.availability')

class HeadStudioTests(fixtures.unittest.TestCase):
    def project(self):
        config = studio.clean_config({'engine':'h3', 'workflow_mode':'swap', 'scope':'head',
            'h3_head_swap':True, 'duration':2, 'resolution':1280})
        return {'id':'a'*32, 'config':config, 'source':{'file':'source.mp4','sha':'src'},
                'references':[{'file':'portrait.png','sha':'ref'}], 'phase':'new', 'actions':[]}

    def video(self,audio=True,duration=2):
        c=types.SimpleNamespace(streams=types.SimpleNamespace(video=[types.SimpleNamespace(duration=duration,time_base=1)],audio=[object()] if audio else []))
        cm=fixtures.unittest.mock.MagicMock();cm.__enter__.return_value=c
        return cm

    def test_direct_head_graph_needs_no_opening_or_preparation_and_skips_reference_handoff(self):
        p=self.project()
        with patch.object(studio,'check_asset',return_value='source.mp4'),patch.object(studio.av,'open',return_value=self.video()):
            graph,stage=studio.editable_graph(p)
        self.assertEqual(stage,'h3')
        self.assertEqual(graph['references']['inputs']['ref_videos.ref_video_0'],['face_motion',0])
        self.assertFalse(studio._needs_h3_reference_stage(p,graph))
        self.assertEqual(graph['portrait']['inputs']['image'],'portrait.png')
        self.assertEqual(graph['source']['inputs']['file'],'source.mp4')
        self.assertNotIn('opening_input',p)
        availability.require_verified_setup(p['config'],'h3')
        with self.assertRaises(ValueError):availability.require_verified_setup(p['config'],'design')

    def test_unqualified_audio_length_and_multiple_references_are_rejected(self):
        for audio,duration in [(False,2),(True,3)]:
            with patch.object(studio.av,'open',return_value=self.video(audio,duration)),self.assertRaises(ValueError):
                p=self.project();p['config']['duration']=duration;head.build_studio_graph(p,lambda a:'source.mp4')
        p=self.project();p['references']=[]
        with self.assertRaises(ValueError):head.build_studio_graph(p,lambda a:'source.mp4')
        for key,value in [('audio_id','a'*32),('remove_text',True),('delivery_mode','enhanced1080')]:
            p=self.project();p['config'][key]=value
            self.assertFalse(availability.verified_setup(p['config']))

    def test_old_head_scope_does_not_opt_in_to_new_recipe(self):
        p=self.project();p['config']['h3_head_swap']=False
        self.assertFalse(availability.head_swap_setup(p['config']))
        self.assertTrue(availability.verified_setup(p['config']))
