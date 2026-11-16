"""Qualified installed Adobe display catalogue; no media processing or apps."""
import hashlib
import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import PyOpenColorIO as ocio

import v2_bootstrap
from test_studio_icc_display import linear_srgb_profile

display = importlib.import_module('ComfyUI_zura_nodes.comfylink.display_view')


class AdobeCatalogueBoundaryTests(unittest.TestCase):
    def test_only_qualified_files_are_addressable_and_default_matches_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'Adobe' / 'Adobe After Effects 2026' / 'Support Files' / 'OpenColorIO-Configs' / 'Actual fixture'
            root.mkdir(parents=True)
            path = root / 'config.ocio'
            config = ocio.Config.CreateFromBuiltinConfig('ocio://cg-config-latest')
            path.write_text(config.serialize(), encoding='utf-8')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with patch.dict(os.environ, {'ProgramFiles': temporary, 'ProgramFiles(x86)': ''}):
                records = display._adobe_records()
                self.assertEqual(len(records), 1)
                record = records[0]
                self.assertTrue(record['name'].startswith('adobe-ae://'))
                actual = display.adobe_view_presets()
                expected = {(record['name'], d, v) for d in config.getDisplays() for v in config.getViews(d)}
                self.assertEqual({(p['config'], p['display'], p['view']) for p in actual}, expected)
                self.assertEqual(len(actual), len(expected))
                self.assertEqual(len({p['label'] for p in actual}), len(actual))
                description = display.describe('', source_colour={'management':'ocio','ocioConfigPath':str(path),'ocioConfigFileSha256':digest})
                self.assertEqual(description['config'], record['name'])
                self.assertEqual(description['view'], config.getDefaultView(description['display']))
                self.assertNotIn(str(path), str(description))
                with self.assertRaises(ValueError):
                    display._config(str(path))
                path.write_text(config.serialize() + '\n# changed\n', encoding='utf-8')
                with self.assertRaises(ValueError):
                    display._config(record['name'])


class InstalledAdobeCatalogueTests(unittest.TestCase):
    def test_full_actual_catalogue_and_every_preview_tuple(self):
        records = display._adobe_records()
        if not records:
            self.skipTest('Adobe AE configurations are not installed on this test machine')
        expected = set()
        for record in records:
            config = ocio.Config.CreateFromFile(record['path'])
            expected.update((record['name'], d, v) for d in config.getDisplays() for v in config.getViews(d))
        presets = display.adobe_view_presets()
        self.assertEqual({(p['config'], p['display'], p['view']) for p in presets}, expected)
        self.assertEqual(len(presets), len(expected))
        self.assertEqual(len({p['label'] for p in presets}), len(presets))
        profile = linear_srgb_profile()
        pixels = np.array([[[-.25, .18, 4., .33333334]]], dtype=np.float32)
        original = pixels.tobytes()
        manifest = {'width':1,'height':1,'sampleType':'float32','sourceBitDepth':32,'alphaAssociation':'straight',
            'colour':{'management':'icc','encoding':'ae_project_icc','sceneLinear':True,'profileSha256':hashlib.sha256(profile).hexdigest()}}
        for preset in presets:
            with self.subTest(config=preset['config'], display=preset['display'], view=preset['view']):
                shown = display.render(original, manifest, config_name=preset['config'], display=preset['display'], view=preset['view'], profile=profile)
                self.assertTrue(shown.startswith(b'\x89PNG'))
                self.assertEqual(pixels.tobytes(), original)
        print(f'Qualified actual Adobe catalogue: {len(records)} configurations, {len(presets)} complete display/view tuples')


if __name__ == '__main__':
    unittest.main()
