"""CPU-only checks for both VoiceDesign routes and the isolated runtime boundary."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('voice_design_setup_test', ROOT/'setup_voice_design.py')
SETUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SETUP)
WORKFLOWS = ('Zura_Voice_Design_Qwen_Direct.json', 'Zura_Voice_Design_Qwen_to_LongCat.json')


class ReleaseTests(unittest.TestCase):
    def test_assets_and_registration(self):
        for name in ('qwen_voice_design.py','setup_voice_design.py','VOICE_DESIGN.md',
                     'Setup_Voice_Design_Windows.cmd','voice_design_runtime/qwen_voice_worker.py',
                     'voice_design_runtime/requirements.txt'):
            self.assertTrue((ROOT/name).is_file(), name)
        init = (ROOT/'__init__.py').read_text(encoding='utf-8')
        self.assertIn('NODE_CLASS_MAPPINGS.update(QWEN_DESIGN_NODES)', init)
        self.assertIn('NODE_DISPLAY_NAME_MAPPINGS.update(QWEN_DESIGN_NAMES)', init)

    def test_both_templates_are_portable(self):
        for filename in WORKFLOWS:
            raw = (ROOT/'workflows'/filename).read_text(encoding='utf-8')
            workflow = json.loads(raw)
            design = [n for n in workflow['nodes'] if n['type']=='ZuraQwenVoiceDesign']
            self.assertEqual(len(design), 1)
            self.assertEqual(design[0]['properties']['cnr_id'], 'comfyui-zura-nodes')
            self.assertNotRegex(raw.lower(), r'c:\\\\users\\\\|/users/|/home/|data:audio|base64,|voiceclonelab')
            self.assertFalse(any(n['type']=='LoadAudio' for n in workflow['nodes']))

    def test_direct_does_not_require_longcat_model(self):
        w = json.loads((ROOT/'workflows'/WORKFLOWS[0]).read_text())
        self.assertFalse(any(n['type']=='ZuraLongCatVoice' for n in w['nodes']))
        source = (ROOT/'qwen_voice_design.py').read_text()
        self.assertNotIn('longcat.local.json', source)

    def test_reference_text_is_shared_in_chained_graph(self):
        w = json.loads((ROOT/'workflows'/WORKFLOWS[1]).read_text())
        nodes = {n['id']:n for n in w['nodes']}
        refs = [n for n in nodes.values() if n['type']=='PrimitiveStringMultiline']
        self.assertEqual(len(refs), 1)
        connected = {(nodes[link[3]]['type'], nodes[link[3]]['inputs'][link[4]]['name'])
                     for link in w['links'] if link[1]==refs[0]['id']}
        self.assertIn(('ZuraQwenVoiceDesign','script'), connected)
        self.assertIn(('ZuraLongCatVoice','reference_transcript'), connected)
        self.assertTrue(any(nodes[l[1]]['type']=='ZuraQwenVoiceDesign' and
                            nodes[l[3]]['type']=='ZuraLongCatVoice' and l[-1]=='AUDIO' for l in w['links']))

    def test_configs_excluded_and_model_pinned(self):
        for name in ('.gitignore','.comfyignore'):
            self.assertIn('qwen_voice_design.local.json*', (ROOT/name).read_text().splitlines())
        self.assertFalse(list(ROOT.glob('qwen_voice_design.local.json*')))
        self.assertEqual(SETUP.MODEL_REVISION, '5ecdb67327fd37bb2e042aab12ff7391903235d3')
        self.assertEqual(SETUP.MODEL_ID, 'Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign')

    def test_no_speech_dependencies_imported_by_host_node(self):
        tree = ast.parse((ROOT/'qwen_voice_design.py').read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(n.name.split('.')[0] for n in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append((node.module or '').split('.')[0])
        self.assertFalse(set(imports) & {'qwen_tts','transformers','librosa','huggingface_hub'})
        self.assertNotIn('shell=True', (ROOT/'qwen_voice_design.py').read_text())
        self.assertIn("HF_HUB_OFFLINE='1'", (ROOT/'qwen_voice_design.py').read_text())

    def test_cached_reference_fingerprint_is_stable(self):
        # Load just this node with a stubbed host, not the pack's video/segmentation nodes.
        package=types.ModuleType('zura_voice_test'); package.__path__=[str(ROOT)]
        comfy=types.ModuleType('comfy'); comfy.__path__=[]
        management=types.ModuleType('comfy.model_management'); comfy.model_management=management
        helpers=types.ModuleType('zura_voice_test.longcat')
        helpers.project_directory=lambda _: None
        helpers.stop_worker=lambda _: None
        modules={'zura_voice_test':package, 'comfy':comfy, 'comfy.model_management':management,
                 'zura_voice_test.longcat':helpers, 'zura_voice_test.setup_voice_design':SETUP}
        with tempfile.TemporaryDirectory() as d, patch.dict(sys.modules, modules):
            file=Path(d)/'machine.json'
            with patch.dict(os.environ, {'ZURA_QWEN_VOICE_DESIGN_CONFIG':str(file)}):
                spec=importlib.util.spec_from_file_location('zura_voice_test.qwen_voice_design', ROOT/'qwen_voice_design.py')
                node=importlib.util.module_from_spec(spec);spec.loader.exec_module(node)
                first=node.ZuraQwenVoiceDesign.IS_CHANGED()
                self.assertEqual(first,node.ZuraQwenVoiceDesign.IS_CHANGED())
                file.write_text('{}')
                self.assertNotEqual(first,node.ZuraQwenVoiceDesign.IS_CHANGED())


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config=self.root/'settings.json'
        self.model=self.root/'model';self.model.mkdir()
        (self.root/'python').touch()
        for name in ('model.safetensors','tokenizer_config.json','vocab.json','merges.txt','preprocessor_config.json',
                     'speech_tokenizer/config.json','speech_tokenizer/model.safetensors','speech_tokenizer/preprocessor_config.json'):
            f=self.model/name;f.parent.mkdir(exist_ok=True);f.touch()
        (self.model/'config.json').write_text(json.dumps({'tts_model_type':'voice_design'}))
        self.config.write_text(json.dumps({'python':'python','model_path':'model','device_index':0}))

    def test_relative_paths_resolve_at_config_file(self):
        c=SETUP.read_config(self.config)
        self.assertEqual(Path(c['model_path']), self.model)
        self.assertEqual(Path(c['python']),self.root/'python')

    def test_wrong_checkpoint_rejected(self):
        (self.model/'config.json').write_text(json.dumps({'tts_model_type':'base'}))
        with self.assertRaisesRegex(ValueError, 'VoiceDesign checkpoint'):
            SETUP.read_config(self.config)

    def test_incomplete_model_fails_before_generation(self):
        (self.model/'speech_tokenizer/model.safetensors').unlink()
        with self.assertRaisesRegex(FileNotFoundError,'asset missing'):
            SETUP.read_config(self.config)

    def test_missing_config_is_actionable(self):
        with self.assertRaisesRegex(RuntimeError,'Setup_Voice_Design_Windows'):
            SETUP.read_config(self.root/'missing.json')

    def test_setup_check_is_offline_and_environment_isolated(self):
        with patch.dict(os.environ, {'PYTHONPATH':'unrelated','VIRTUAL_ENV':'other'}):
            env=SETUP.isolated_environment(offline=True)
        self.assertNotIn('PYTHONPATH',env)
        self.assertNotIn('VIRTUAL_ENV',env)
        self.assertEqual(env['HF_HUB_OFFLINE'],'1')
        self.assertEqual(env['TRANSFORMERS_OFFLINE'],'1')


if __name__=='__main__':
    unittest.main()
