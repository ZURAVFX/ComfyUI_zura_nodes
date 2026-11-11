"""CPU-only HTTP tests for immutable one-frame FLOAT staging."""
import hashlib
import asyncio
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
import numpy as np
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault("folder_paths", types.SimpleNamespace())
from comfylink import float_io
from comfylink.native_float_staging import FloatStaging, PREFIX, HEADER


@unittest.skipUnless(os.name == "nt", "Windows handle-based staging cleanup")
class StagingTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = FloatStaging(lambda: self.root)
        app = web.Application(client_max_size=1024)
        app.router.add_post(PREFIX, self.service.create)
        app.router.add_post(PREFIX + '/{id}/frame', self.service.frame)
        app.router.add_post(PREFIX + '/{id}/release', self.service.release)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.samples = np.array([[[[-.125, 4., 16., 1.], [2**-20, .5, .75, 1.]]]], dtype='<f4')
        self.data = self.samples.tobytes()
        self.manifest = {'schemaVersion':1,'sampleType':'float32','layout':'RGBA','byteOrder':'little',
            'width':2,'height':1,'alphaAssociation':'straight','sourceBitDepth':32,
            'colour':{'encoding':'unknown','sceneLinear':False},'frameRate':{'numerator':25,'denominator':1},
            'frames':[{'index':0,'filename':'000001.rgba32f','byteLength':len(self.data),
                       'sha256':hashlib.sha256(self.data).hexdigest(),'time':{'numerator':0,'denominator':1}}]}

    async def create(self):
        response = await self.client.post(PREFIX, json={'manifest':self.manifest})
        self.assertEqual(response.status, 200)
        return await response.json()

    async def test_hdr_upload_is_exact_and_one_use(self):
        ticket = await self.create()
        path = PREFIX + '/' + ticket['id'] + '/frame'
        wrong = await self.client.post(path, data=self.data, headers={HEADER:'bad'})
        self.assertEqual(wrong.status, 403)
        response = await self.client.post(path, data=self.data, headers={HEADER:ticket['capability']})
        self.assertEqual(response.status, 200, await response.text())
        result = await response.json()
        actual, _ = float_io.load_transfer(self.root, result['manifest'])
        self.assertEqual(actual.tobytes(), self.samples.tobytes())
        again = await self.client.post(path, data=self.data, headers={HEADER:ticket['capability']})
        self.assertEqual(again.status, 409)
        release = await self.client.post(PREFIX + '/' + ticket['id'] + '/release', headers={HEADER:ticket['capability']})
        self.assertEqual(release.status, 200)
        self.assertFalse((self.root / 'ComfyLink' / ticket['id']).exists())

    async def test_stream_can_exceed_default_request_body_limit(self):
        self.samples = np.ones((1, 40, 40, 4), dtype='<f4')
        self.data = self.samples.tobytes()
        self.manifest.update(width=40, height=40)
        self.manifest['frames'][0].update(byteLength=len(self.data), sha256=hashlib.sha256(self.data).hexdigest())
        ticket = await self.create()
        response = await self.client.post(PREFIX + '/' + ticket['id'] + '/frame', data=self.data,
                                          headers={HEADER:ticket['capability']})
        self.assertEqual(response.status, 200, await response.text())
        result = await response.json()
        actual, _ = float_io.load_transfer(self.root, result['manifest'])
        self.assertEqual(actual.tobytes(), self.samples.tobytes())

    async def test_changed_or_nonfinite_frame_never_publishes(self):
        ticket = await self.create()
        path = PREFIX + '/' + ticket['id'] + '/frame'
        bad = bytearray(self.data); bad[0] ^= 1
        response = await self.client.post(path, data=bad, headers={HEADER:ticket['capability']})
        self.assertEqual(response.status, 422)
        self.assertFalse((self.root / 'ComfyLink' / ticket['id']).exists())
        self.samples[0,0,0,0] = np.nan
        self.data = self.samples.tobytes()
        self.manifest['frames'][0]['sha256'] = hashlib.sha256(self.data).hexdigest()
        ticket = await self.create()
        response = await self.client.post(PREFIX + '/' + ticket['id'] + '/frame', data=self.data,
                                          headers={HEADER:ticket['capability']})
        self.assertEqual(response.status, 422)
        self.assertFalse((self.root / 'ComfyLink' / ticket['id']).exists())

    async def test_release_never_deletes_foreign_files(self):
        ticket = await self.create()
        response = await self.client.post(PREFIX + '/' + ticket['id'] + '/frame', data=self.data,
                                          headers={HEADER:ticket['capability']})
        self.assertEqual(response.status, 200)
        folder = self.root / 'ComfyLink' / ticket['id']
        foreign = folder / 'user-file.txt'
        foreign.write_text('preserve me')
        response = await self.client.post(PREFIX + '/' + ticket['id'] + '/release',
                                          headers={HEADER:ticket['capability']})
        self.assertEqual(response.status, 409)
        self.assertEqual(foreign.read_text(), 'preserve me')
        self.assertTrue((folder / '000001.rgba32f').exists())

    async def test_two_frames_through_real_float_nodes_without_quantisation(self):
        import importlib
        import torch
        sys.modules['folder_paths'] = types.SimpleNamespace(get_input_directory=lambda: str(self.root), get_output_directory=lambda: str(self.root))
        sys.modules.pop('comfylink.float_nodes', None)
        nodes = importlib.import_module('comfylink.float_nodes')
        for frame_index in range(2):
            values = np.array([[[[-.125, 4., 16., 1.], [2**-20, .25, .75, 1.]]]], dtype='<f4')
            values[..., :3] += np.float32(frame_index / 8)
            self.data = values.tobytes()
            self.manifest['frames'][0].update(byteLength=len(self.data), sha256=hashlib.sha256(self.data).hexdigest())
            self.manifest['sourceStart'] = {'numerator':frame_index,'denominator':25}
            ticket = await self.create()
            response = await self.client.post(PREFIX + '/' + ticket['id'] + '/frame', data=self.data,
                                              headers={HEADER:ticket['capability']})
            self.assertEqual(response.status, 200, await response.text())
            staged = await response.json()
            rgb, _, metadata = nodes.ZuraComfyLinkLoadFloatFrames().load(staged['manifest'])
            output = nodes.ZuraComfyLinkSaveFloatFrames().save(1.0-rgb, metadata)
            returned, wire = float_io.load_transfer(self.root, output['result'][0])
            np.testing.assert_array_equal(returned[..., :3], np.float32(1)-values[..., :3])
            np.testing.assert_array_equal(returned[..., 3], values[..., 3])
            self.assertEqual(wire['sourceStart'], self.manifest['sourceStart'])
            release = await self.client.post(PREFIX + '/' + ticket['id'] + '/release', headers={HEADER:ticket['capability']})
            self.assertEqual(release.status, 200)

    async def test_replaced_expected_leaf_is_never_deleted(self):
        ticket = await self.create()
        response = await self.client.post(PREFIX + '/' + ticket['id'] + '/frame', data=self.data,
                                          headers={HEADER:ticket['capability']})
        self.assertEqual(response.status, 200)
        folder = self.root / 'ComfyLink' / ticket['id']
        original = folder / '000001.rgba32f'
        original.unlink()
        original.write_bytes(b'user replacement')
        response = await self.client.post(PREFIX + '/' + ticket['id'] + '/release', headers={HEADER:ticket['capability']})
        self.assertEqual(response.status, 409)
        self.assertEqual(original.read_bytes(), b'user replacement')

    async def test_expired_ready_ticket_frees_slot_without_deleting_inflight_source(self):
        ticket = await self.create()
        response = await self.client.post(PREFIX + '/' + ticket['id'] + '/frame', data=self.data,
                                          headers={HEADER:ticket['capability']})
        self.assertEqual(response.status, 200)
        self.service.pending[ticket['id']]['expires'] = time.monotonic() - 1
        await self.create()
        self.assertNotIn(ticket['id'], self.service.pending)
        self.assertTrue((self.root / 'ComfyLink' / ticket['id'] / '000001.rgba32f').exists())

    async def test_concurrent_creates_never_exceed_capacity(self):
        responses = await asyncio.gather(*(self.client.post(PREFIX, json={'manifest':self.manifest}) for _ in range(12)))
        self.assertEqual(sum(response.status == 200 for response in responses), 8)
        self.assertTrue(all(response.status in (200, 503) for response in responses))
        self.assertEqual(len(self.service.pending), 8)

    async def test_cross_origin_request_is_rejected(self):
        response = await self.client.post(PREFIX, json={'manifest':self.manifest}, headers={'Origin':'https://evil.invalid'})
        self.assertEqual(response.status, 403)
