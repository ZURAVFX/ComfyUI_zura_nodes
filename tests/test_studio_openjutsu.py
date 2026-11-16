"""Protect the approved H3 default and the experimental stage hand-off."""
import test_artist_studio as fixtures

s = fixtures.studio


class StudioOpenJutsuTests(fixtures.unittest.TestCase):
    def test_approved_method_remains_default(self):
        c = s.clean_config({"engine": "h3"})
        self.assertEqual(c["h3_character_method"], "control")

    def test_experiment_is_eight_steps_and_has_no_enhancement_handoff(self):
        c = s.clean_config({"engine": "h3", "h3_character_method": "openjutsu",
                            "resolution": 1920, "delivery_mode": "enhanced1080", "quality": "detailed"})
        self.assertEqual(c["delivery_mode"], "native")
        self.assertEqual(c["h3_steps"], 8)
        self.assertEqual(c["quality"], "fast")
        self.assertFalse(s._needs_h3_reference_stage({"config": c}, {}))

    def test_experiment_does_not_leak_into_other_workflows(self):
        c = s.clean_config({"engine": "wan", "h3_character_method": "openjutsu"})
        self.assertEqual(c["h3_character_method"], "control")

    def test_unknown_methods_are_rejected(self):
        with self.assertRaises(ValueError):
            s.clean_config({"engine": "h3", "h3_character_method": "invented"})

    def test_direct_route_is_character_only_and_background_requires_scene_review(self):
        c = s.clean_config({'engine': 'h3', 'h3_character_method': 'openjutsu', 'openjutsu_direct': True})
        self.assertFalse(c['openjutsu_direct'])
        self.assertFalse(s.h3_viewport_direct({'config': c, 'look_mode': 'build'}))
        self.assertFalse(s.h3_viewport_direct({'config': c, 'look_mode': 'ready'}))
        c = s.clean_config({**c, 'openjutsu_background': 'replace'})
        self.assertEqual(c['edit_area'], 'scene')
        self.assertFalse(c['openjutsu_direct'])
        self.assertFalse(s.h3_viewport_direct({'config': c, 'look_mode': 'build'}))


    def test_mask_action_without_reference_reaches_queue_and_stops_at_review(self):
        import asyncio,types,sys
        from fractions import Fraction
        from unittest.mock import Mock,AsyncMock,patch
        controller=s.Studio.__new__(s.Studio);controller.collect=lambda p:p;controller.store=Mock();controller.start_watcher=Mock();controller.server_address='local'
        queue=Mock();controller.server=types.SimpleNamespace(trigger_on_prompt=lambda value:value,node_replace_manager=types.SimpleNamespace(apply_replacements=lambda graph:None),prompt_queue=queue,number=0)
        config=s.clean_config({'engine':'h3','workflow_mode':'swap','h3_character_method':'openjutsu','duration':17/24,'mask_prompt':'person, red coat'})
        p={'id':'a'*32,'source':{'file':'source.mkv','sha':'source','duration':17/24},'config':config,'character':None,'references':[],'look_mode':'build','phase':'new','actions':[]}
        video=types.SimpleNamespace(streams=types.SimpleNamespace(video=[types.SimpleNamespace(duration=17,time_base=Fraction(1,24))],audio=[]))
        media=Mock();media.__enter__=Mock(return_value=video);media.__exit__=Mock(return_value=False)
        execution=types.SimpleNamespace(validate_prompt=AsyncMock(return_value=(True,None,['20'],{})))
        with patch.object(s,'check_asset',return_value='source.mkv'),patch.object(s.av,'open',return_value=media),patch.dict(sys.modules,{'execution':execution}):
            asyncio.run(controller.action(p,'prepare',{'request_key':'b'*36}))
        queue.put.assert_called_once()
        queued=queue.put.call_args.args[0][2]
        self.assertEqual(queued['20']['class_type'],'GenjSaveReview')
        self.assertEqual(queued['7']['inputs']['text'],'person, red coat')
        self.assertEqual(p['actions'][0]['stage'],'prepare')
        self.assertNotIn('next_stage',p['actions'][0])
        self.assertEqual(p['character'],None)
