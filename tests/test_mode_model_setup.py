"""Fresh-machine camera dependency coverage and gated-download preflight."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
import requests

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


camera = module('setup_camera', 'artist_studio/panorama_camera.py')
downloads = module('setup_downloads', 'artist_studio/model_downloads.py')
access = module('setup_access', 'model_access.py')


class CameraSetupTests(unittest.TestCase):
    def readiness(self, nodes, locate):
        package = types.ModuleType('setup_fixture');package.__path__ = []
        folders = types.SimpleNamespace(get_full_path=locate)
        with patch.dict(sys.modules, {'setup_fixture': package, 'setup_fixture.panorama_camera': camera,
                                      'folder_paths': folders, 'nodes': types.SimpleNamespace(NODE_CLASS_MAPPINGS=nodes)}):
            routes = module('setup_fixture.panorama_routes', 'artist_studio/panorama_routes.py')
            return routes.readiness()

    def test_every_camera_file_has_a_pinned_automatic_download(self):
        catalog = {(file['folder'], file['filename']): file for pack in downloads.CATALOG.values() for file in pack['files']}
        for model in camera.MODELS.values():
            file = catalog[model]
            self.assertEqual(len(file['revision']), 40)
            self.assertEqual(len(file['sha256']), 64)
            self.assertGreater(file['size_bytes'], 0)
        self.assertEqual(catalog[camera.MODELS['geometry']]['size_bytes'], 541524124)

    def test_fresh_machine_reports_files_and_the_complete_graph_nodes(self):
        def missing_category(*args):
            raise KeyError('geometry_estimation')
        result = self.readiness({}, missing_category)
        self.assertFalse(result['ready'])
        self.assertEqual(result['route'], 'panorama')
        self.assertEqual(len(result['files']), len(camera.MODELS))
        self.assertTrue(all(not file['ready'] for file in result['files']))
        self.assertTrue({'LoadDA3Model', 'DA3Inference', 'PanoramaStudio', 'ManualSigmas', 'SaveVideo',
                         'ZuraCameraLoadScene', 'ZuraCameraAlignViews', 'LTXAddVideoICLoRAGuide', 'LoadImage'} <= set(result['missingNodes']))
        nodes = dict.fromkeys(result['missingNodes'])
        self.assertTrue(self.readiness(nodes, lambda *args: '/fixture/model')['ready'])
        nodes.pop('ManualSigmas')
        self.assertFalse(self.readiness(nodes, lambda *args: '/fixture/model')['ready'])


class GatedPreflightTests(unittest.TestCase):
    files = [{'repo': 'fixture/' + name, 'revision': 'a' * 40, 'remote_path': 'model.safetensors'} for name in ('first', 'second')]

    def check(self, head, files=None, token='hf_TestOnly'):
        with patch('requests.head', side_effect=head), patch('requests.get', side_effect=AssertionError('Preflight must not download bytes')):
            return access.check_files(files or self.files, ({'fixture': {'files': self.files}},), token)

    def test_all_gates_report_together_without_bytes_or_secret_in_response(self):
        def head(url, **kwargs):
            self.assertFalse(kwargs['allow_redirects'])
            self.assertTrue(url.startswith('https://huggingface.co/fixture/'))
            return types.SimpleNamespace(status_code=403, close=lambda: None)
        result = self.check(head)
        self.assertEqual(result['access_repos'], ['fixture/first', 'fixture/second'])
        self.assertFalse(result['allowed'])
        self.assertTrue(result['auth_required'])
        self.assertNotIn('hf_TestOnly', str(result))

    def test_approved_gates_and_network_errors_are_distinct(self):
        result = self.check(lambda *args, **kwargs: types.SimpleNamespace(status_code=302, close=lambda: None))
        self.assertTrue(result['allowed'])
        result = self.check(lambda *args, **kwargs: (_ for _ in ()).throw(requests.ConnectionError('private request detail')))
        self.assertFalse(result['allowed'])
        self.assertFalse(result['auth_required'])
        self.assertNotIn('private request detail', str(result))

    def test_unlisted_destinations_are_rejected_before_network(self):
        with self.assertRaises(ValueError):
            self.check(lambda *args, **kwargs: self.fail('Unlisted network request'),
                       [{**self.files[0], 'repo': 'not/allowlisted'}])


if __name__ == '__main__':
    unittest.main()
