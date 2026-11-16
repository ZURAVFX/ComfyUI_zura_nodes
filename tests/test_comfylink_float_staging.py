"""CPU-only HTTP tests for immutable, streamed FLOAT sequence staging."""
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
        app.router.add_get(PREFIX + '/capabilities', self.service.capabilities)
        app.router.add_post(PREFIX, self.service.create)
        app.router.add_post(PREFIX + '/{id}/frame', self.service.frame)
        app.router.add_post(PREFIX + '/{id}/frame/{index}', self.service.frame)
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

    def sequence(self, count):
        self.samples = np.concatenate([self.samples + np.float32(i / 32) for i in range(count)], axis=0)
        # Alpha remains exact and independent of the RGB operation under test.
        self.samples[..., 3] = 1
        self.manifest['frameRate'] = {'numerator': 30000, 'denominator': 1001}
        self.manifest['sourceStart'] = {'numerator': 1001, 'denominator': 30000}
        self.manifest['frames'] = [dict(index=i, filename=f'{i+1:06d}.rgba32f',
            byteLength=self.samples[i].nbytes, sha256=hashlib.sha256(self.samples[i].tobytes()).hexdigest(),
            time={'numerator':i*1001,'denominator':30000}) for i in range(count)]

    async def send_index(self, ticket, index, data=None):
        return await self.client.post(PREFIX + '/' + ticket['id'] + '/frame/' + str(index),
            data=self.samples[index].tobytes() if data is None else data,
            headers={HEADER:ticket['capability']})

    async def test_sequence_capabilities_and_4k_admission_preserve_existing_limits(self):
        response = await self.client.get(PREFIX + '/capabilities')
        self.assertEqual(response.status, 200)
        caps = await response.json()
        self.assertEqual(caps, dict(schemaVersion=1, sequence=True, indexBase=0,
            maxFrames=10000, maxBytes=16*1024**3, maxFrameBytes=16*1024*1024*16))
        self.manifest.update(width=3840, height=2160)
        self.manifest['frames'][0]['byteLength'] = 3840*2160*16
        ticket = await self.create()
        self.assertEqual(self.service.pending[ticket['id']]['bytes'], 132710400)
        self.assertFalse((self.root/'ComfyLink'/ticket['id']).exists())

    async def test_17_frame_sequence_is_published_once_in_order_after_all_frames(self):
        self.sequence(17)
        ticket = await self.create()
        relative = 'ComfyLink/' + ticket['id'] + '/manifest.json'
        final = self.root / relative
        # Indexed uploads may arrive in any order; the manifest retains exact
        # rational source time and canonical frame order.
        for index in list(range(16, -1, -1)):
            response = await self.send_index(ticket, index)
            self.assertEqual(response.status, 200, await response.text())
            result = await response.json()
            self.assertEqual(result['complete'], index == 0)
            if index:
                self.assertNotIn('manifest', result)
                self.assertFalse(final.exists())
            else:
                self.assertEqual(result['manifest'], relative)
        actual, manifest = float_io.load_transfer(self.root, relative)
        np.testing.assert_array_equal(actual, self.samples)
        self.assertEqual(manifest, self.manifest)
        self.assertEqual((await self.send_index(ticket, 0)).status, 409)
        response = await self.client.post(PREFIX + '/' + ticket['id'] + '/release',
            headers={HEADER:ticket['capability']})
        self.assertEqual(response.status, 200)
        self.assertFalse(final.parent.exists())

    async def test_sequence_missing_duplicate_invalid_index_and_legacy_route_never_publish(self):
        self.sequence(3)
        ticket = await self.create()
        path = PREFIX + '/' + ticket['id']
        headers = {HEADER:ticket['capability']}
        self.assertEqual((await self.client.post(path+'/frame', data=self.samples[0].tobytes(), headers=headers)).status, 400)
        for index in ('-1', '01', '3', '100000', 'not-an-index'):
            self.assertEqual((await self.client.post(path+'/frame/'+index, data=b'', headers=headers)).status, 400)
        self.assertEqual((await self.send_index(ticket, 0)).status, 200)
        self.assertEqual((await self.send_index(ticket, 0)).status, 409)
        self.assertEqual((await self.send_index(ticket, 2)).status, 200)
        self.assertFalse((self.root/'ComfyLink'/ticket['id']).exists())
        release = await self.client.post(path+'/release', headers=headers)
        self.assertEqual(release.status, 409)
        self.assertEqual(self.service.pending[ticket['id']]['received'], {0, 2})

    async def test_sequence_tampered_earlier_frame_or_foreign_leaf_is_not_published_or_deleted(self):
        self.sequence(2)
        ticket = await self.create()
        self.assertEqual((await self.send_index(ticket, 0)).status, 200)
        temporary = self.service.pending[ticket['id']]['temp']
        original = temporary/'000001.rgba32f'
        changed = bytearray(original.read_bytes()); changed[0] ^= 1; original.write_bytes(changed)
        response = await self.send_index(ticket, 1)
        self.assertEqual(response.status, 422)
        self.assertFalse((self.root/'ComfyLink'/ticket['id']).exists())

        ticket = await self.create()
        self.assertEqual((await self.send_index(ticket, 0)).status, 200)
        temporary = self.service.pending[ticket['id']]['temp']
        foreign = temporary/'user-file.txt'
        foreign.write_text('preserve me')
        response = await self.send_index(ticket, 1)
        self.assertEqual(response.status, 422)
        self.assertEqual(foreign.read_text(), 'preserve me')
        self.assertFalse((self.root/'ComfyLink'/ticket['id']).exists())

    async def test_sequence_wrong_capability_and_truncated_stream_do_not_publish(self):
        self.sequence(2)
        ticket = await self.create()
        path = PREFIX + '/' + ticket['id'] + '/frame/0'
        response = await self.client.post(path, data=self.samples[0].tobytes(), headers={HEADER:'f'*64})
        self.assertEqual(response.status, 403)
        async def truncated():
            yield self.samples[0].tobytes()[:4]
        response = await self.client.post(path, data=truncated(), headers={HEADER:ticket['capability']})
        self.assertEqual(response.status, 422)
        self.assertNotIn(ticket['id'], self.service.pending)
        self.assertFalse((self.root/'ComfyLink'/ticket['id']).exists())

    async def test_sequence_rejects_aggregate_overflow_without_allocating_frame_bytes(self):
        self.manifest.update(width=4096, height=4096)
        self.manifest['frames'] = [dict(index=i, filename=f'{i+1:06d}.rgba32f', byteLength=4096*4096*16,
            sha256='0'*64, time={'numerator':i,'denominator':25}) for i in range(65)]
        response = await self.client.post(PREFIX, json={'manifest':self.manifest})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.service.pending, {})
        self.assertFalse((self.root/'ComfyLink').exists())

    async def test_sequence_accepts_large_manifest_and_rejects_frame_count_overflow(self):
        original = self.manifest['frames'][0]
        self.manifest['frames'] = [dict(original, index=i, filename=f'{i+1:06d}.rgba32f',
            time={'numerator':i, 'denominator':25}) for i in range(1000)]
        self.assertGreater(len(float_io.canonical_manifest_bytes(self.manifest)), 65536)
        ticket = await self.create()
        self.assertEqual(self.service.pending[ticket['id']]['bytes'], len(self.data)*1000)
        self.assertFalse((self.root/'ComfyLink'/ticket['id']).exists())
        self.manifest['frames'] = [dict(original, index=i, filename=f'{i+1:06d}.rgba32f',
            time={'numerator':i, 'denominator':25}) for i in range(10001)]
        response = await self.client.post(PREFIX, json={'manifest':self.manifest})
        self.assertEqual(response.status, 400)
        self.assertEqual(len(self.service.pending), 1)

    async def test_sequence_storage_admission_reserves_all_frames(self):
        from unittest.mock import patch
        self.sequence(17)
        total = sum(frame['byteLength'] for frame in self.manifest['frames'])
        with patch('comfylink.native_float_staging.shutil.disk_usage',
                   return_value=types.SimpleNamespace(free=4*1024**3 + total - 1)):
            response = await self.client.post(PREFIX, json={'manifest':self.manifest})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.service.pending, {})

    async def test_17_frames_through_real_float_loader_and_saver_as_one_image_batch(self):
        import importlib
        import torch
        self.sequence(17)
        sys.modules['folder_paths'] = types.SimpleNamespace(get_input_directory=lambda: str(self.root), get_output_directory=lambda: str(self.root))
        sys.modules.pop('comfylink.float_nodes', None)
        nodes = importlib.import_module('comfylink.float_nodes')
        ticket = await self.create()
        for index in range(17):
            response = await self.send_index(ticket, index)
            self.assertEqual(response.status, 200, await response.text())
        staged = await response.json()
        rgb, _, metadata = nodes.ZuraComfyLinkLoadFloatFrames().load(staged['manifest'])
        self.assertEqual(tuple(rgb.shape), (17, 1, 2, 3))
        output = nodes.ZuraComfyLinkSaveFloatFrames().save(torch.ones_like(rgb)-rgb, metadata)
        actual, manifest = float_io.load_transfer(self.root, output['result'][0])
        np.testing.assert_array_equal(actual[..., :3], np.float32(1)-self.samples[..., :3])
        np.testing.assert_array_equal(actual[..., 3], self.samples[..., 3])
        self.assertEqual(len(manifest['frames']), 17)
        self.assertEqual(manifest['frameRate'], self.manifest['frameRate'])
        self.assertEqual(manifest['sourceStart'], self.manifest['sourceStart'])

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
        response = await self.client.get(PREFIX+'/capabilities', headers={'Origin':'https://evil.invalid'})
        self.assertEqual(response.status, 403)
