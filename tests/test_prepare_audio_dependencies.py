"""Preparation must only validate voice-separation models when requested."""
import unittest
from unittest.mock import patch

import test_artist_studio as shared

studio = shared.studio


class PrepareAudioDependencies(unittest.TestCase):
    def graph(self, engine, pitch, scene=False, reference_audio=False):
        project = shared.SharedEngineTests().project()
        project['config'] = studio.clean_config({**project['config'],
            'engine': engine, 'pitch': pitch, 'edit_area': 'scene' if scene else 'mask'})
        if reference_audio:
            project['audio'] = {'file': 'speech.wav', 'sha': 'speech'}
        with patch.object(studio, 'check_asset'):
            return studio.build_graph(project, 'prepare')

    def test_original_audio_needs_no_separator_for_any_review_engine(self):
        for engine in ('local', 'h3', 'wan', 'seedance'):
            for scene in (False, True):
                with self.subTest(engine=engine, scene=scene):
                    graph = self.graph(engine, False, scene)
                    self.assertNotIn('isolated_vocals', graph['18']['inputs'])
                    self.assertFalse(any('MelBand' in node['class_type'] for node in graph.values()))
                    self.assertEqual(graph['18']['inputs']['original_audio'], ['4', 1])
                    self.assertEqual(graph['20']['inputs']['guidance_audio'], ['18', 0])

    def test_requested_pitch_keeps_real_vocal_separation(self):
        graph = self.graph('wan', True)
        self.assertTrue(graph['18']['inputs']['pitch_vocals'])
        self.assertEqual(graph['18']['inputs']['isolated_vocals'], ['22', 0])
        self.assertEqual(graph['22']['inputs']['model'], ['21', 0])
        self.assertEqual(graph['22']['inputs']['audio'], ['4', 1])

    def test_reference_audio_keeps_selected_audio_without_separator(self):
        graph = self.graph('local', False, True, True)
        self.assertEqual(graph['3']['inputs']['audio'], ['zura_reference_audio', 0])
        self.assertNotIn('21', graph)
        self.assertNotIn('22', graph)


if __name__ == '__main__':
    unittest.main()
