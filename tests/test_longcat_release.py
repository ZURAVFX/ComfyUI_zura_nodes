"""CPU-only checks for the distributable LongCat workflows and runtime boundary."""
import ast
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    def test_version_matches_module(self):
        project = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
        version = re.search(r'^version = "([^"]+)"', project, re.M).group(1)
        tree = ast.parse((ROOT / '__init__.py').read_text(encoding='utf-8'))
        actual = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == '__version__' for t in n.targets))
        self.assertEqual(actual, version)

    def test_runtime_files_present(self):
        for name in ('longcat.py', 'setup_longcat.py', 'Setup_LongCat_Windows.cmd',
                     'longcat_runtime/worker.py', 'longcat_runtime/text.py',
                     'longcat_runtime/requirements.txt', 'LONGCAT.md'):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_templates_have_registered_node_and_no_voice_data(self):
        for path in (ROOT / 'workflows').glob('Zura_LongCat_*.json'):
            raw = path.read_text(encoding='utf-8')
            data = json.loads(raw)
            voice = [n for n in data['nodes'] if n['type'] == 'ZuraLongCatVoice']
            self.assertEqual(len(voice), 1)
            self.assertEqual(voice[0]['properties']['cnr_id'], 'comfyui-zura-nodes')
            self.assertEqual(voice[0]['widgets_values_named']['reference_transcript'], '')
            self.assertNotRegex(raw.lower(), r'c:\\\\users\\\\|/users/|/home/|data:audio/|base64,')
            for node in data['nodes']:
                if node['type'] == 'LoadAudio':
                    self.assertEqual(node['widgets_values_named']['audio'], '')
        self.assertEqual(len(list((ROOT / 'workflows').glob('Zura_LongCat_*.json'))), 2)

    def test_machine_config_is_excluded(self):
        for name in ('.gitignore', '.comfyignore'):
            self.assertIn('longcat.local.json*', (ROOT / name).read_text(encoding='utf-8').splitlines())
        self.assertFalse(list(ROOT.glob('longcat.local.json*')))

    def test_speech_models_not_imported_by_node(self):
        tree = ast.parse((ROOT / 'longcat.py').read_text(encoding='utf-8'))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(n.name.split('.')[0] for n in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or '').split('.')[0])
        self.assertFalse(imported & {'audiodit', 'transformers', 'librosa'})
        self.assertIn('soundfile', imported)
        self.assertIn('soundfile>=0.12.0', (ROOT / 'requirements.txt').read_text())

    def test_node_is_registered(self):
        text = (ROOT / '__init__.py').read_text(encoding='utf-8')
        self.assertIn('from .longcat import NODE_CLASS_MAPPINGS as LONGCAT_NODES', text)
        self.assertIn('NODE_CLASS_MAPPINGS.update(LONGCAT_NODES)', text)
        self.assertIn('NODE_DISPLAY_NAME_MAPPINGS.update(LONGCAT_NAMES)', text)


if __name__ == '__main__':
    unittest.main()
