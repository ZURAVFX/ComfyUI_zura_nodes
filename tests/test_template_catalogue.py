"""Keep private drafts and local media out of the public template bundle."""
from pathlib import Path
import json
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]

class CatalogueTests(unittest.TestCase):
    def test_only_reviewed_templates_are_bundled(self):
        entries=json.loads((ROOT/'template_catalogue.json').read_text(encoding='utf-8'))['templates']
        names=[entry['file'] for entry in entries]
        self.assertEqual(len(names),len(set(names)))
        self.assertEqual(set(names),{p.name for p in (ROOT/'workflows').rglob('*.json')})
        rules=(ROOT/'.comfyignore').read_text(encoding='utf-8').splitlines()
        self.assertNotIn('!/workflows/**',rules)
        self.assertIn('/workflows/*',rules)
        self.assertEqual({r.removeprefix('!/workflows/') for r in rules if r.startswith('!/workflows/') and r.endswith('.json')},set(names))
        for entry in entries:
            name=entry['file']
            with self.subTest(name=name):
                self.assertTrue(name.startswith(entry['category']+' - '))
                self.assertNotRegex(name.lower(),r'audition|anyangle|(?:^|[ _-])(?:wip|test|draft)(?:[ _.-]|$)')
                raw=(ROOT/'workflows'/name).read_text(encoding='utf-8')
                self.assertTrue(json.loads(raw)['nodes'])
                self.assertNotRegex(raw.lower(),r'data:(?:audio|image|video)/|base64,|c:\\\\users\\\\|comfyui-shared|/users/|/home/')

    def test_speech_templates_retain_the_approved_quality_and_stages(self):
        audio=json.loads((ROOT/'workflows/Audio - Replace Speech (LongCat).json').read_text(encoding='utf-8'))
        video=json.loads((ROOT/'workflows/Video - Replace Speech (LTX INT8).json').read_text(encoding='utf-8'))
        self.assertEqual(len(audio['nodes']),4)
        self.assertEqual(len(video['nodes']),3)
        self.assertTrue(audio['definitions']['subgraphs'])
        self.assertTrue(video['definitions']['subgraphs'])
        source=next(n for n in video['nodes'] if n['type']=='ZuraDialogueSource')
        self.assertIn(512,source['widgets_values'])
        self.assertIn('int8',json.dumps(video).lower())

if __name__=='__main__':unittest.main()
