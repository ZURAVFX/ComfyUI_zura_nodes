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
        self.assertTrue(s.h3_viewport_direct({'config': c, 'look_mode': 'build'}))
        self.assertFalse(s.h3_viewport_direct({'config': c, 'look_mode': 'ready'}))
        c = s.clean_config({**c, 'openjutsu_background': 'replace'})
        self.assertEqual(c['edit_area'], 'scene')
        self.assertFalse(c['openjutsu_direct'])
        self.assertFalse(s.h3_viewport_direct({'config': c, 'look_mode': 'build'}))
