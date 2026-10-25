"""Keep the integrated paintout examples portable and publishable."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = (
    'Video - Targeted Paintout (LTX 2.5).json',
    'Video - Full Scene Clean Plate (LTX 2.5).json',
)


class PaintoutReleaseTests(unittest.TestCase):
    def test_examples_have_no_private_media_and_keep_the_qualified_sampler(self):
        for name in EXAMPLES:
            raw = (ROOT/'workflows'/name).read_text(encoding='utf-8')
            graph = json.loads(raw)
            nodes = graph['nodes'] + [n for g in graph['definitions']['subgraphs'] for n in g['nodes']]
            self.assertNotRegex(raw, r'(?i)ellio|LTX PAINT TEST|ComfyUI-Shared|G:/|C:/|data:image/|base64,')
            source = next(n for n in nodes if n['type'] in ('ZuraPaintoutCrop', 'ZuraPaintoutFullFrame'))
            values = source['widgets_values_named']
            self.assertEqual(values['plate_path'], '')
            self.assertEqual(values['frame_count'], 81)
            sampler = next(n for n in nodes if n['type'] == 'KSampler')['widgets_values_named']
            self.assertEqual((sampler['steps'], sampler['cfg'], sampler['sampler_name'], sampler['scheduler']),
                             (8, 1, 'euler_ancestral', 'linear_quadratic'))
            guide = next(n for n in nodes if n['type'] == 'LTXAddVideoICLoRAGuideAdvanced')['widgets_values_named']
            self.assertFalse(guide['use_streaming'])
            self.assertFalse(guide['use_tiled_encode'])
            self.assertTrue(any(n['type'] == 'LTXVVAEForceFloat32' for n in nodes))
            if source['type'] == 'ZuraPaintoutCrop':
                self.assertEqual(values['mask_path'], '')
                anchors = next(n for n in nodes if n['type'] == 'ZuraPaintoutAnchors')
                self.assertEqual(json.loads(anchors['widgets_values_named']['anchors']), [])
                self.assertTrue(any(n['type'] == 'InvertMask' for n in nodes))
                self.assertTrue(any(n['type'] == 'GrowMask' and n['widgets_values_named']['expand'] == 32 for n in nodes))
                self.assertTrue(any(n['type'] == 'BlockifyMask' and n['widgets_values_named']['block_size'] == 32 for n in nodes))
            else:
                self.assertFalse(any(n['type'] == 'ZuraPaintoutAnchors' for n in nodes))
                self.assertNotIn('mask_path', values)

    def test_registry_includes_the_new_runtime_and_templates(self):
        init = (ROOT/'__init__.py').read_text(encoding='utf-8')
        self.assertIn('NODE_CLASS_MAPPINGS.update(PAINTOUT_NODES)', init)
        self.assertIn('NODE_DISPLAY_NAME_MAPPINGS.update(PAINTOUT_NAMES)', init)
        catalogue = json.loads((ROOT/'template_catalogue.json').read_text(encoding='utf-8'))
        for name in EXAMPLES:
            self.assertTrue(any(e['file'] == name for e in catalogue['templates']))
            self.assertIn('!/workflows/'+name, (ROOT/'.comfyignore').read_text(encoding='utf-8'))
        for name in ('paintout.py', 'media.py', 'attention.py', 'browser.py', '__init__.py'):
            ast.parse((ROOT/'paintout'/name).read_text(encoding='utf-8'))
        self.assertTrue((ROOT/'web/paintout.js').read_text(encoding='utf-8').isascii())

    def test_browser_route_registration_is_idempotent_with_legacy_routes(self):
        from aiohttp import web
        for legacy in (False, True):
            routes = web.RouteTableDef()
            if legacy:
                routes.post('/zura/paintout/pick')(lambda request: None)
                routes.get('/zura/paintout/thumbnail')(lambda request: None)
            server = types.ModuleType('server')
            server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(routes=routes))
            spec = importlib.util.spec_from_file_location('paintout_browser_routes_test', ROOT/'paintout/browser.py')
            module = importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules, {'server': server}):
                spec.loader.exec_module(module)
                module.register_routes()
                module.register_routes()
            self.assertEqual([(r.method, r.path) for r in routes],
                             [('POST', '/zura/paintout/pick'), ('GET', '/zura/paintout/thumbnail')])


if __name__ == '__main__':
    unittest.main()
