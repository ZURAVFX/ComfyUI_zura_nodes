"""Real aiohttp requests through registration, origin checks and a tiny download.

Only Comfy's server/folder discovery are replaced. The standalone package's
real media_source guard, download manager and local streaming HTTP run normally.
"""
import asyncio
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import requests

from test_model_downloads import tensor_file


class ModelDownloadRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = tensor_file(4 * 1024 * 1024)
        self.weight_started = asyncio.Event()
        self.weight_requests = []
        self.slow = False
        self.routes = web.RouteTableDef()
        self.folder_paths = types.ModuleType('folder_paths')
        self.folder_paths.models_dir = str(self.root)
        self.folder_paths.filename_list_cache = {'vae': 'old entry'}
        self.folder_paths.get_folder_paths = lambda folder: [str(self.root)] if folder == 'vae' else []
        self.folder_paths.get_filename_list = lambda folder: [path.relative_to(self.root).as_posix() for path in self.root.rglob('*.safetensors')]
        server = types.ModuleType('server')
        server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(routes=self.routes))
        prefix = '_paintout_download_route_test'
        package = types.ModuleType(prefix)
        # Match the standalone distribution: media_source at package root,
        # with the downloader one package below it in paintout/.
        package_root = Path(__file__).resolve().parents[2]
        media_root = package_root if (package_root / 'media_source.py').exists() else package_root.parent / 'paintout-vendor'
        package.__path__ = [str(media_root)]
        paintout = types.ModuleType(prefix + '.paintout')
        paintout.__path__ = [str(Path(__file__).resolve().parents[2] / 'paintout')]
        replacements = {'server': server, 'folder_paths': self.folder_paths,
                        prefix: package, prefix + '.paintout': paintout}
        previous = {name: sys.modules.get(name) for name in replacements}
        sys.modules.update(replacements)
        def restore_modules():
            # Restore only our modules, keeping libraries imported while testing
            # alive (NumPy's C extension cannot be unloaded and loaded again).
            for name in list(sys.modules):
                if name == prefix or name.startswith(prefix + '.'):
                    sys.modules.pop(name, None)
            for name, value in previous.items():
                if value is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = value
        self.addCleanup(restore_modules)
        self.downloads = importlib.import_module(prefix + '.paintout.model_downloads')
        item = dict(folder='vae', filename='route-fixture.safetensors', repo='Example/route-fixture',
                    revision='1' * 40, remote_path='vae/route-fixture.safetensors',
                    size_bytes=len(self.data), sha256=hashlib.sha256(self.data).hexdigest(),
                    gated=False, model_card='https://huggingface.co/Example/route-fixture')
        self.catalog = patch.object(self.downloads, 'CATALOG', {'fixture': dict(name='Route fixture',
                    files=[item], license_url=item['model_card'])})
        self.catalog.start()
        self.addCleanup(self.catalog.stop)
        self.downloads.register_routes()
        self.downloads.register_routes()
        self.assertEqual(len(self.routes), 4, 'Repeated registration must not add duplicate endpoints.')
        guard = importlib.import_module(prefix + '.media_source')
        self.assertEqual(Path(guard.__file__).resolve(), (Path(package.__path__[0]) / 'media_source.py').resolve())
        app = web.Application()
        app.add_routes(self.routes)
        app.router.add_get('/weights', self.weights)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        original_get = requests.get
        def local_weight_request(url, **kwargs):
            self.assertTrue(url.startswith('https://huggingface.co/Example/route-fixture/resolve/'))
            self.weight_requests.append(url)
            return original_get(str(self.client.make_url('/weights')), **kwargs)
        network = patch.object(requests, 'get', side_effect=local_weight_request)
        network.start()
        self.addCleanup(network.stop)
        self.base = '/zura/paintout/model-downloads'
        self.origin = str(self.client.make_url('/')).rstrip('/')

    async def weights(self, request):
        offset = int(request.headers.get('Range', 'bytes=0-').split('=')[1].split('-')[0])
        headers = {'Content-Length': str(len(self.data) - offset), 'Content-Type': 'application/octet-stream'}
        if offset:
            headers['Content-Range'] = f'bytes {offset}-{len(self.data)-1}/{len(self.data)}'
        response = web.StreamResponse(status=206 if offset else 200, headers=headers)
        await response.prepare(request)
        self.weight_started.set()
        try:
            for index in range(offset, len(self.data), 65536):
                await response.write(self.data[index:index + 65536])
                if self.slow:
                    await asyncio.sleep(.01)
            await response.write_eof()
        except ConnectionError:
            pass
        return response

    async def wait_for_job(self, identity):
        for _ in range(300):
            response = await self.client.get(self.base + '/' + identity)
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            status = await response.json()
            if status['phase'] in ('done', 'failed', 'cancelled'):
                return status
            await asyncio.sleep(.01)
        self.fail('Local download did not finish.')

    async def start(self):
        response = await self.client.post(self.base, json={'model_ids': ['fixture'], 'token': 'hf_FixtureOnly'},
                                          headers={'Origin': self.origin})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        return (await response.json())['id']

    async def test_catalogue_start_status_and_completed_install(self):
        response = await self.client.get(self.base, headers={'Origin': self.origin})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        catalogue = await response.json()
        self.assertIsNone(catalogue['active'])
        self.assertFalse(catalogue['models'][0]['files'][0]['installed'])
        self.assertFalse(self.weight_requests, 'Viewing the catalogue must not start downloads.')
        identity = await self.start()
        status = await self.wait_for_job(identity)
        self.assertEqual(status['phase'], 'done', status)
        self.assertEqual(status['done_bytes'], len(self.data))
        self.assertEqual((self.root / 'route-fixture.safetensors').read_bytes(), self.data)
        self.assertNotIn('vae', self.folder_paths.filename_list_cache)
        catalogue = await (await self.client.get(self.base)).json()
        self.assertTrue(catalogue['models'][0]['files'][0]['installed'])
        self.assertNotIn('hf_FixtureOnly', json.dumps(status) + json.dumps(catalogue))
        self.assertNotIn(str(self.root), json.dumps(catalogue))
        # Cancelling an already completed job is harmless and preserves it.
        response = await self.client.post(self.base + '/' + identity + '/cancel')
        self.assertEqual(await response.json(), {'ok': True})
        self.assertEqual((await self.wait_for_job(identity))['phase'], 'done')

    async def test_cancel_route_stops_only_model_download(self):
        self.slow = True
        identity = await self.start()
        await asyncio.wait_for(self.weight_started.wait(), 3)
        response = await self.client.post(self.base + '/' + identity + '/cancel', headers={'Origin': self.origin})
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {'ok': True})
        status = await self.wait_for_job(identity)
        self.assertEqual(status['phase'], 'cancelled', status)
        self.assertFalse((self.root / 'route-fixture.safetensors').exists())
        self.assertEqual(len(self.weight_requests), 1)

    async def test_invalid_json_catalogue_token_and_unknown_job(self):
        for body in ({'model_id': 'unknown'}, {'model_id': 'fixture', 'url': 'https://evil.invalid'},
                     {'model_id': 'fixture', 'token': 'secret invalid token'}, []):
            response = await self.client.post(self.base, json=body)
            self.assertEqual(response.status, 400)
            public = await response.text()
            self.assertNotIn('secret invalid token', public)
            self.assertNotIn('evil.invalid', public)
        response = await self.client.post(self.base, data='{broken', headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status, 400)
        for method, path in [('get', '/unknown'), ('post', '/unknown/cancel')]:
            response = await getattr(self.client, method)(self.base + path)
            self.assertEqual(response.status, 404)
        self.assertFalse(self.weight_requests)

    async def test_all_download_routes_reject_cross_origin_requests(self):
        for method, path in [('get', ''), ('post', ''), ('get', '/unknown'), ('post', '/unknown/cancel')]:
            response = await getattr(self.client, method)(self.base + path, headers={'Origin': 'https://elsewhere.invalid'})
            self.assertEqual(response.status, 403)
        response = await self.client.post(self.base, json={'model_id': 'fixture'}, headers={'Sec-Fetch-Site': 'cross-site'})
        self.assertEqual(response.status, 403)
        self.assertFalse(self.weight_requests)


if __name__ == '__main__':
    unittest.main()
