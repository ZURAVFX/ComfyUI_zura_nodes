import asyncio
import importlib.util
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

spec = importlib.util.spec_from_file_location('output_settings', Path(__file__).parents[1] / 'artist_studio/output_settings.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OutputTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output = self.root / 'output'
        self.service = module.OutputSettings(self.output, self.root / 'settings')

    def tearDown(self):
        self.temporary.cleanup()

    def asset(self, subfolder='genj/final', filename='take.mp4', content=b'finished media'):
        file = self.output / subfolder / filename
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
        return {'type': 'output', 'subfolder': subfolder, 'filename': filename}

    def test_default_custom_folder_and_restart_persistence(self):
        self.assertEqual(self.service.describe()['folder'], str(self.output.resolve() / 'ZURA STUDIO'))
        target = self.root / 'Artist deliveries'
        self.service.save(str(target))
        restarted = module.OutputSettings(self.output, self.root / 'settings')
        self.assertEqual(restarted.describe()['folder'], str(target))
        for invalid in ('relative/path', None, 123):
            with self.assertRaises(ValueError):
                self.service.save(invalid)
        file = self.root / 'a-file'
        file.write_text('do not replace')
        with self.assertRaises(OSError):
            self.service.save(str(file))
        self.assertEqual(restarted.describe()['folder'], str(target))

    def test_export_categories_collisions_repeat_and_new_destination(self):
        for subfolder, name, category in [('genj/final', 'take.mp4', 'Videos'),
                ('zura_images/flux3', 'image.png', 'Images'), ('genj/hdr', 'master.zip', 'Sequences'),
                ('genj/panorama', 'take_001.mp4', 'Videos'), ('genj/reference_video', 'h3.mp4', 'Videos'),
                ('zura/first_last/ltx', 'result_0001.mp4', 'Videos'), ('zura/reference', 'h3_0001.mp4', 'Videos'),
                ('zura/ltx25/key', 'result_0001.mp4', 'Videos'), ('paintout/job', 'paintout_HLG_10bit.mp4', 'Videos')]:
            with self.subTest(name=name):
                asset = self.asset(subfolder, name)
                destination = Path(self.service.export([asset])[0])
                self.assertEqual(destination.parent.name, category)
                self.assertEqual(destination.read_bytes(), b'finished media')
                self.assertEqual(self.service.export([asset]), [str(destination)])
                self.assertTrue((self.output / subfolder / name).exists(), 'Original history URLs remain valid')
        asset = self.asset(filename='collision.mp4')
        existing = self.output / 'ZURA STUDIO/Videos/collision.mp4'
        existing.write_bytes(b'artist file')
        saved = Path(self.service.export([asset])[0])
        self.assertNotEqual(saved, existing)
        self.assertEqual(existing.read_bytes(), b'artist file')
        self.service.save(str(self.root / 'Other folder'))
        self.assertEqual(Path(self.service.export([asset])[0]).parent, self.root / 'Other folder/Videos')

    def test_no_private_working_files_previews_inputs_or_traversal(self):
        for asset in [self.asset('genj/studio_intermediate'), self.asset('genj/reviews/shot'),
                      self.asset('genj/hdr', 'master_preview.mp4'), self.asset('genj/panorama', 'warp_x.mp4'),
                      self.asset('zura/ltx25/key/pose', 'frame_001.png'),
                      {'type':'input','subfolder':'genj/final','filename':'take.mp4'},
                      {'type':'output','subfolder':'genj/final/../../..','filename':'take.mp4'},
                      {'type':'output','subfolder':'genj/final','filename':'../take.mp4'},
                      {'type':'output','subfolder':123,'filename':'take.mp4'}]:
            self.assertEqual(self.service.export([asset]), [])

    async def test_delivery_failure_does_not_fail_the_render(self):
        asset = self.asset()
        with patch.object(self.service, 'export', side_effect=PermissionError('disk read-only')):
            self.assertEqual(await self.service.export_safely({'results':[{'asset':asset}]}), [])
        self.assertIn('disk read-only', self.service.describe()['error'])

    async def test_delivery_copies_do_not_block_ui_or_duplicate_pending_work(self):
        asset = self.asset()
        gate = asyncio.Event()
        calls = []

        async def copy(assets):
            calls.append(assets)
            await gate.wait()

        self.service.export_safely = copy
        self.service.schedule_export({'results': [asset]})
        self.service.schedule_export({'results': [asset]})
        await asyncio.sleep(0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.service.tasks), 1)
        gate.set()
        await asyncio.gather(*self.service.tasks)
        self.assertEqual(self.service.pending, set())

    async def test_settings_and_explicit_save_http_contract(self):
        asset = self.asset('zura_images', 'ready.png')
        queue = types.SimpleNamespace(get_history=lambda **kwargs: {})
        server = types.SimpleNamespace(prompt_queue=queue)
        paths = types.SimpleNamespace(get_output_directory=lambda: str(self.output), get_user_directory=lambda: str(self.root / 'user'))
        app = web.Application()
        routes = web.RouteTableDef()
        with patch.dict('sys.modules', {'folder_paths': paths}):
            service = module.register(server, routes, lambda function: function)
        # Avoid a perpetual watcher in this route-only integration test.
        service.start = lambda: None
        app.add_routes(routes)
        async with TestClient(TestServer(app)) as client:
            result = await client.get('/zura/studio/output-settings')
            self.assertIn('ZURA STUDIO', (await result.json())['folder'])
            result = await client.post('/zura/studio/output-settings', json={'folder': str(self.root / 'Chosen')})
            self.assertEqual(result.status, 200)
            result = await client.post('/zura/studio/save-output', json={'assets':[asset]})
            body = await result.json()
            self.assertEqual(Path(body['saved'][0]).read_bytes(), b'finished media')
            result = await client.post('/zura/studio/save-output', json={'assets':[asset]})
            self.assertEqual((await result.json())['saved'], body['saved'])
