"""Real multipart upload checks: incremental hashing and responsive media probing."""
import asyncio
import hashlib
import io
import json
import sys
import tempfile
import threading
import time
import types
import importlib
from pathlib import Path
from unittest.mock import patch

import test_artist_studio as fixtures
from PIL import Image

studio = fixtures.studio
# Route registration imports these native modules. Keep them outside mocked
# module snapshots so a later route test cannot re-import NumPy's extensions.
importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


class UploadTests(fixtures.unittest.IsolatedAsyncioTestCase):
    async def test_prores_colour_variants_share_one_preview_writer(self):
        await self.preview_variants(fail=False)

    async def test_prores_colour_variants_share_preview_failure_without_retry(self):
        with self.assertLogs(level='ERROR'):
            await self.preview_variants(fail=True)

    async def preview_variants(self, *, fail):
        preview_proxy = importlib.import_module('ComfyUI_zura_nodes.artist_studio.preview_proxy')
        server = types.SimpleNamespace(routes=studio.web.RouteTableDef())
        module = types.ModuleType('server')
        module.PromptServer = types.SimpleNamespace(instance=server)
        started, release = threading.Event(), threading.Event()
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'genj_studio/original/source.mov'
            source.parent.mkdir(parents=True);source.write_bytes(b'original remains unchanged')
            target = source.with_name('preview.mp4')
            original = {'id':'a'*32, 'kind':'asset', 'asset_kind':'video',
                        'file':'genj_studio/original/source.mov',
                        'preview_file':'genj_studio/original/preview.mp4'}
            clone = {**original, 'id':'b'*32}
            records = {item['id']:item for item in (original,clone)}
            instance = types.SimpleNamespace(start_watcher=lambda:None,
                store=types.SimpleNamespace(load=lambda identity:dict(records[identity])))
            def build(media, dest, ffmpeg):
                calls.append((media,dest));started.set()
                if not release.wait(5):raise RuntimeError('Test did not release its preview worker')
                if fail:raise ValueError('test proxy failure')
                dest.write_bytes(b'playable proxy')
            with patch.dict(sys.modules, {'server':module}), \
                    patch.object(studio,'Studio',return_value=instance), \
                    patch.object(importlib.import_module('ComfyUI_zura_nodes.artist_studio'),'ffmpeg',lambda *args:None,create=True), \
                    patch.object(studio.folder_paths,'get_input_directory',return_value=tmp), \
                    patch.object(studio,'check_asset',return_value=source), \
                    patch.object(studio,'public_project',side_effect=lambda asset:dict(asset)), \
                    patch.object(preview_proxy,'build_proxy',side_effect=build):
                studio.register()
                handler = next(r.handler for r in server.routes if r.path=='/zura/studio/assets/{identity}/preview')
                async def poll(identity):
                    result=await handler(types.SimpleNamespace(headers={},host='localhost',match_info={'identity':identity}))
                    self.assertEqual(result.status,200)
                    return json.loads(result.body)
                try:
                    await poll(original['id'])
                    for _ in range(100):
                        if started.is_set():break
                        await asyncio.sleep(.01)
                    self.assertTrue(started.is_set())
                    await asyncio.gather(poll(original['id']),poll(clone['id']))
                    await asyncio.sleep(.02)
                    self.assertEqual(len(calls),1,'Both asset IDs must share the same target writer')
                finally:
                    release.set()
                for _ in range(100):
                    first,second=await asyncio.gather(poll(original['id']),poll(clone['id']))
                    if (first.get('preview_status')=='error' if fail else target.is_file()):break
                    await asyncio.sleep(.01)
                self.assertEqual(len(calls),1)
                self.assertEqual(source.read_bytes(),b'original remains unchanged')
                if fail:
                    self.assertEqual(first['preview_status'],'error')
                    self.assertEqual(second['preview_status'],'error')
                else:
                    self.assertEqual(target.read_bytes(),b'playable proxy')

    async def test_image_upload_hashes_once_and_inspects_off_event_loop(self):
        image = io.BytesIO()
        Image.new('RGB', (64, 48), 'purple').save(image, format='PNG')
        payload = image.getvalue()
        main_thread = threading.get_ident()
        calls = []
        original_open = studio.Image.open

        def slow_open(*args, **kwargs):
            calls.append(threading.get_ident())
            time.sleep(.15)
            return original_open(*args, **kwargs)

        class Part:
            filename = 'test.png'
            offset = 0
            async def read_chunk(self, size):
                chunk = payload[self.offset:self.offset + 31]
                self.offset += len(chunk)
                return chunk

        class Reader:
            async def next(self):
                return Part()

        async def multipart():
            return Reader()

        server = types.SimpleNamespace(routes=studio.web.RouteTableDef())
        module = types.ModuleType('server')
        module.PromptServer = types.SimpleNamespace(instance=server)
        instance = types.SimpleNamespace(start_watcher=lambda: None,
            store=types.SimpleNamespace(save=lambda asset: None))
        ticks = []
        async def heartbeat():
            for _ in range(12):
                ticks.append(asyncio.get_running_loop().time())
                await asyncio.sleep(.02)

        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(sys.modules, {'server': module}), \
                patch.object(studio, 'Studio', return_value=instance), \
                patch.object(studio.folder_paths, 'get_input_directory', return_value=tmp), \
                patch.object(studio.Image, 'open', side_effect=slow_open), \
                patch.object(studio, 'sha', side_effect=AssertionError('Do not reread the uploaded file')):
            studio.register()
            handler = next(r.handler for r in server.routes if r.path == '/zura/studio/upload')
            request = types.SimpleNamespace(headers={}, host='localhost', query={'kind': 'image'}, multipart=multipart)
            response, _ = await asyncio.gather(handler(request), heartbeat())
            self.assertEqual(response.status, 200)
            asset = json.loads(response.body)
            self.assertEqual(asset['sha'], hashlib.sha256(payload).hexdigest())
            self.assertEqual((Path(tmp) / asset['file']).read_bytes(), payload)
        self.assertTrue(calls)
        self.assertTrue(all(t != main_thread for t in calls))
        self.assertLess(max(b-a for a, b in zip(ticks, ticks[1:])), .12,
                        'Slow media inspection must not freeze the server event loop')


    async def test_real_mp4_multipart_upload_and_thumbnail(self):
        import av
        import numpy as np
        from aiohttp import FormData
        from aiohttp.test_utils import TestClient, TestServer

        server = types.SimpleNamespace(routes=studio.web.RouteTableDef())
        module = types.ModuleType('server')
        module.PromptServer = types.SimpleNamespace(instance=server)
        instance = types.SimpleNamespace(start_watcher=lambda: None,
            store=types.SimpleNamespace(save=lambda asset: None))
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(sys.modules, {'server': module}), \
                patch.object(studio, 'Studio', return_value=instance), \
                patch.object(studio.folder_paths, 'get_input_directory', return_value=tmp), \
                patch.object(studio, 'sha', side_effect=AssertionError('Video must be hashed during copy')):
            clip = Path(tmp) / 'fixture.mp4'
            with av.open(str(clip), 'w') as output:
                stream = output.add_stream('mpeg4', rate=24)
                stream.width, stream.height, stream.pix_fmt = 64, 48, 'yuv420p'
                for _ in range(24):
                    frame = av.VideoFrame.from_ndarray(np.full((48, 64, 3), 100, dtype=np.uint8), format='rgb24')
                    for packet in stream.encode(frame):
                        output.mux(packet)
                for packet in stream.encode():
                    output.mux(packet)
            # Valid MP4 free atom exercises a sizeable body without a long decode.
            import struct
            with clip.open('ab') as f:
                f.write(struct.pack('>I4s', 16*1024**2 + 8, b'free'))
                f.write(bytes(16*1024**2))
            payload = clip.read_bytes()
            studio.register()
            app = studio.web.Application()
            app.add_routes(server.routes)
            async with TestClient(TestServer(app)) as client:
                form = FormData()
                form.add_field('file', io.BytesIO(payload), filename='fixture.mp4', content_type='video/mp4')
                response = await client.post('/zura/studio/upload?kind=video', data=form)
                self.assertEqual(response.status, 200, await response.text())
                asset = await response.json()
                self.assertEqual(asset['sha'], hashlib.sha256(payload).hexdigest())
                self.assertEqual((asset['width'], asset['height']), (64, 48))
                self.assertAlmostEqual(asset['duration'], 1, places=2)
                self.assertTrue((Path(tmp) / asset['thumbnail_file']).is_file())


if __name__ == '__main__':
    fixtures.unittest.main()
