"""Local HTTP boundary tests; no Comfy/GPU, vendor API or AE process."""
import hashlib
import importlib.util
import asyncio
import copy
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
import zipfile
from datetime import datetime, timezone
from unittest.mock import patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfylink import float_io
from comfylink.studio_sessions import register, PREFIX, SESSION_HEADER, TOKEN_HEADER, DOWNLOAD_HEADER, _video_sdr_metadata


async def no_import(*args):
    return {}


def processing_authority(manifest):
    return {'schemaVersion': 1, 'precision': 8, 'conversion': 'verified_srgb_to_sdr8',
            'sourceManifestSha256': hashlib.sha256(float_io.canonical_manifest_bytes(manifest)).hexdigest(),
            'sourceColour': copy.deepcopy(manifest['colour']),
            'colour': {'encoding': 'unknown', 'sceneLinear': False}, 'alphaAssociation': 'straight'}


class StudioHTTPTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inputs, self.outputs = self.root / "input", self.root / "output"
        self.inputs.mkdir(); self.outputs.mkdir()
        self.token, self.broker_id = "b" * 64, "a" * 32
        self.payload = np.array([[[[-.25, 2., .375, .5]]]], dtype=np.float32)
        source_root = self.root / "source"
        source_root.mkdir()
        _, self.manifest = float_io.write_transfer(source_root, "ComfyLink/" + "c" * 32, self.payload,
            colour={"encoding": "unknown", "sceneLinear": False}, frame_rate={"numerator": 24, "denominator": 1})
        self.source_bytes = self.payload.astype("<f4").tobytes()
        self.broker_calls, self.received = [], []
        self.received_originals = []
        self.grant_override = {}
        self.result_status = 'sent'
        self.redirect_grant = False
        self.source_override = None
        self.pause_result = False
        self.result_entered, self.release_result = asyncio.Event(), asyncio.Event()
        self.broker_revoked, self.native_applied = False, False
        broker_routes = web.RouteTableDef()

        @broker_routes.get('/studio-bridge/{id}/grant')
        async def grant(request):
            self.assertEqual(request.headers.get(TOKEN_HEADER), self.token)
            self.broker_calls.append("grant")
            if self.redirect_grant:
                raise web.HTTPFound(location='http://example.com/forbidden')
            return web.json_response({"schemaVersion": 1, "id": self.broker_id,
                "expiresAt": datetime.fromtimestamp(time.time() + 600, timezone.utc).isoformat(),
                "comfyOrigin": self.origin, "target": {"label": "AE layer"},
                "capabilities": {"source": True, "transfer": True},
                "source": {"width": 1, "height": 1, "frameCount": 1}, **self.grant_override})

        @broker_routes.get('/studio-bridge/{id}/source')
        async def source(request):
            self.assertEqual(request.headers.get(TOKEN_HEADER), self.token)
            self.broker_calls.append("source")
            return web.json_response(self.source_override or {"manifest": self.manifest, "files": [
                {key: frame[key] for key in ("filename", "byteLength", "sha256")} for frame in self.manifest["frames"]]})

        @broker_routes.get('/studio-bridge/{id}/source/{filename}')
        async def blob(request):
            self.assertEqual(request.headers.get(TOKEN_HEADER), self.token)
            self.assertEqual(request.match_info["filename"], "000001.rgba32f")
            self.broker_calls.append("blob")
            return web.Response(body=self.source_bytes)

        @broker_routes.post('/studio-bridge/{id}/result')
        async def result(request):
            self.assertEqual(request.headers.get(TOKEN_HEADER), self.token)
            body = await request.json()
            self.received.append(body)
            self.result_entered.set()
            if self.pause_result:
                await self.release_result.wait()
            if self.broker_revoked:
                raise web.HTTPGone(text='Scoped broker authority revoked')
            # Exercise the actual scoped download route while /result awaits.
            async with aiohttp.ClientSession() as client:
                for namespace, entries in (("result-files", body["files"]), ("original-files", body.get("originals", []))):
                    for entry in entries:
                        url = self.origin + PREFIX + "/sessions/" + body["adapterSessionId"] + "/" + namespace + "/" + str(entry["index"])
                        async with client.get(url, headers={DOWNLOAD_HEADER: body["downloadCapability"]}) as response:
                            self.assertEqual(response.status, 200)
                            encoded = await response.read()
                            self.assertEqual(len(encoded), entry["byteLength"])
                            self.assertEqual(hashlib.sha256(encoded).hexdigest(), entry["sha256"])
                            if namespace == "original-files":
                                self.received_originals.append((entry, encoded))
            if self.broker_revoked:
                raise web.HTTPGone(text='Scoped broker authority revoked')
            self.native_applied = True
            return web.json_response({"ok": True, "status": self.result_status, "downloadCapability": "never echo"})

        @broker_routes.get('/studio-bridge/{id}/status')
        async def status(request):
            self.assertEqual(request.headers.get(TOKEN_HEADER), self.token)
            self.broker_calls.append("status")
            return web.json_response({"ready": True, "importPending": self.result_status == 'import_pending',
                "status": self.result_status, "downloadCapability": "never echo", "personalPath": "never echo"})

        @broker_routes.post('/studio-bridge/{id}/leave')
        async def leave(request):
            self.broker_calls.append("leave")
            self.broker_revoked = True
            return web.json_response({"ok": True})

        broker_app = web.Application()
        broker_app.add_routes(broker_routes)
        self.broker_server = TestServer(broker_app, host="127.0.0.1")
        await self.broker_server.start_server()
        self.broker_url = str(self.broker_server.make_url('/studio-bridge/' + self.broker_id))
        routes = web.RouteTableDef()
        self.server = types.SimpleNamespace(routes=routes)
        self.service = register(self.server, input_root=self.inputs, output_root=self.outputs, importer=no_import)
        app = web.Application()
        app.add_routes(routes)
        self.client = TestClient(TestServer(app, host="127.0.0.1"))
        await self.client.start_server()
        self.origin = str(self.client.make_url('/')).rstrip('/')

    async def asyncTearDown(self):
        await self.client.close()
        await self.broker_server.close()
        self.temp.cleanup()

    async def create(self):
        response = await self.client.post(PREFIX + '/sessions', json={"broker": self.broker_url, "token": self.token})
        self.assertEqual(response.status, 201, await response.text())
        value = await response.json()
        return value, {SESSION_HEADER: value["capability"]}

    def route(self, session, suffix=""):
        return PREFIX + '/sessions/' + session['id'] + suffix

    async def test_desktop_handoff_targets_one_unchanged_socket_and_waits_for_ack(self):
        class Socket:
            def __init__(self): self.closed = False; self.messages = []
            async def send_json(self, value): self.messages.append(copy.deepcopy(value))
        selected, unrelated = Socket(), Socket()
        self.server.sockets = {'desktop-client': selected, 'unrelated-client': unrelated}
        base = '/zura/comfylink/v1/studio/desktop'
        response = await self.client.post(base + '/register', json={'clientId': 'desktop-client'})
        self.assertEqual(response.status, 200)
        request_id, challenge, nonce = 'd' * 32, 'e' * 64, 'f' * 32
        response = await self.client.post(base + '/challenge', json={'requestId': request_id, 'challenge': challenge, 'broker': self.broker_url, 'token': self.token})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(len(selected.messages), 1); self.assertEqual(unrelated.messages, [])
        self.assertEqual(selected.messages[0], {'type': 'comfylink-desktop-challenge', 'data': {'requestId': request_id, 'challenge': challenge}})
        answer = {'requestId': request_id, 'challenge': challenge, 'clientId': 'desktop-client', 'windowNonce': nonce}
        response = await self.client.post(base + '/respond', json=answer); self.assertEqual(response.status, 200)
        response = await self.client.get(base + '/status/' + request_id, headers={TOKEN_HEADER: '0' * 64}); self.assertEqual(response.status, 403)
        response = await self.client.get(base + '/status/' + request_id, headers={TOKEN_HEADER: self.token})
        self.assertEqual((await response.json())['candidates'], [{'clientId': 'desktop-client', 'windowNonce': nonce}])
        self.server.sockets['desktop-client'] = Socket()
        response = await self.client.post(base + '/deliver', headers={TOKEN_HEADER: self.token}, json={'requestId': request_id, 'clientId': 'desktop-client', 'windowNonce': nonce})
        self.assertEqual(response.status, 409); self.assertEqual(len(selected.messages), 1)
        self.server.sockets['desktop-client'] = selected
        response = await self.client.post(base + '/deliver', headers={TOKEN_HEADER: self.token}, json={'requestId': request_id, 'clientId': 'desktop-client', 'windowNonce': nonce})
        self.assertEqual(response.status, 200)
        self.assertEqual(selected.messages[-1]['data']['broker'], self.broker_url)
        self.assertEqual(selected.messages[-1]['data']['token'], self.token)
        self.assertEqual(unrelated.messages, [])
        response = await self.client.post(base + '/deliver', headers={TOKEN_HEADER: self.token}, json={'requestId': request_id, 'clientId': 'desktop-client', 'windowNonce': nonce})
        self.assertEqual(response.status, 409, 'handoff must be one-use')
        response = await self.client.post(base + '/ack', json={**answer, 'accepted': True}); self.assertEqual(response.status, 200)
        response = await self.client.get(base + '/status/' + request_id, headers={TOKEN_HEADER: self.token})
        self.assertEqual((await response.json())['state'], 'accepted')
        self.assertEqual(self.service.desktop.handoffs[request_id].token, '')

    async def test_desktop_challenge_never_sends_token_to_candidates_or_accepts_bad_response(self):
        class Socket:
            closed = False
            def __init__(self): self.messages = []
            async def send_json(self, value): self.messages.append(copy.deepcopy(value))
        first, second = Socket(), Socket(); self.server.sockets = {'first': first, 'second': second}
        base = '/zura/comfylink/v1/studio/desktop'
        for client in self.server.sockets:
            response = await self.client.post(base + '/register', json={'clientId': client}); self.assertEqual(response.status, 200)
        body = {'requestId': 'd' * 32, 'challenge': 'e' * 64, 'broker': self.broker_url, 'token': self.token}
        response = await self.client.post(base + '/challenge', json=body); self.assertEqual(response.status, 200)
        self.assertNotIn(self.token, json.dumps(first.messages + second.messages))
        bad = {'requestId': body['requestId'], 'challenge': '0' * 64, 'clientId': 'first', 'windowNonce': 'f' * 32}
        response = await self.client.post(base + '/respond', json=bad); self.assertEqual(response.status, 403)
        response = await self.client.post(base + '/cancel', headers={TOKEN_HEADER: self.token}, json={'requestId': body['requestId']}); self.assertEqual(response.status, 200)
        self.assertEqual(self.service.desktop.handoffs[body['requestId']].token, '')

    async def test_float_display_preview_is_scoped_and_does_not_change_source(self):
        from io import BytesIO
        from PIL import Image
        import PyOpenColorIO as ocio
        self.manifest['colour'] = {'encoding': 'scene_linear_rec709', 'sceneLinear': True}
        before = hashlib.sha256(self.source_bytes).hexdigest()
        session, headers = await self.create()
        response = await self.client.get(self.route(session, '/display-config'), headers=headers)
        self.assertEqual(response.status, 200, await response.text())
        settings = await response.json()
        self.assertEqual((settings['display'], settings['view']), ('sRGB - Display', 'Un-tone-mapped'))
        response = await self.client.get(self.route(session, '/display-frame?index=0'), headers=headers)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers['Content-Type'], 'image/png')
        rendered = np.array(Image.open(BytesIO(await response.read())))
        rgb = self.payload[0, ..., :3].copy()
        config = ocio.Config.CreateFromFile(settings['config'])
        source = config.getColorSpace('lin_rec709_srgb').getName()
        config.getProcessor(ocio.DisplayViewTransform(src=source, display=settings['display'], view=settings['view'])).getDefaultCPUProcessor().applyRGB(rgb)
        expected = np.rint(np.clip(rgb, 0, 1) * 255).astype(np.uint8)
        self.assertEqual(rendered[0, 0, :3].tolist(), expected[0, 0].tolist())
        self.assertEqual(int(rendered[0, 0, 3]), 128)
        self.assertEqual(hashlib.sha256(self.source_bytes).hexdigest(), before)
        self.assertEqual(self.broker_calls.count('blob'), 1)
        response = await self.client.get(self.route(session, '/display-frame?index=1'), headers=headers)
        self.assertEqual(response.status, 422)
        response = await self.client.get(self.route(session, '/display-frame?index=0'))
        self.assertEqual(response.status, 403)

    async def test_display_rejects_unmapped_32bit_source_and_untrusted_config(self):
        session, headers = await self.create()
        response = await self.client.get(self.route(session, '/display-config?config=file%3A%2F%2F%2Fsecret'), headers=headers)
        self.assertEqual(response.status, 400)
        response = await self.client.get(self.route(session, '/display-frame?index=0'), headers=headers)
        self.assertEqual(response.status, 422)

    async def test_display_accepts_only_the_hashed_ae_builtin_ocio_identity(self):
        from comfylink import display_view
        import PyOpenColorIO as ocio
        root = self.root / 'Program Files' / 'Adobe' / 'Adobe After Effects 2026' / 'Support Files' / 'OpenColorIO-Configs' / 'fixture'
        root.mkdir(parents=True)
        config = ocio.Config.CreateRaw()
        config.addColorSpace(ocio.ColorSpace(name='Output - sRGB', family='Output'))
        config.addDisplayView('ACES', 'sRGB', 'Output - sRGB')
        path = root / 'config.ocio'; path.write_text(config.serialize(), encoding='utf-8')
        colour = {'encoding':'unknown','sceneLinear':False,'management':'ocio','ocioConfig':'fixture',
            'ocioConfigPath':str(path),'ocioWorkingSpace':'Output - sRGB','ocioConfigHandleSha256':'a'*64,
            'ocioWorkingSpaceHandleSha256':'b'*64,'ocioConfigFileSha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        self.manifest['colour'] = colour
        session, headers = await self.create()
        with patch.dict(os.environ, {'ProgramFiles': str(self.root / 'Program Files')}):
            self.assertEqual(display_view._verified_ocio_source(colour), 'srgb8')
            from comfylink.studio_processing import validate_processing_input
            authority=processing_authority(self.manifest)
            authority['sourceConfigSha256']=colour['ocioConfigFileSha256']
            self.assertEqual(validate_processing_input(authority,self.manifest),authority)
            bad=copy.deepcopy(authority);bad['sourceConfigSha256']='0'*64
            with self.assertRaises(ValueError):validate_processing_input(bad,self.manifest)
            response = await self.client.get(self.route(session, '/display-frame?index=0'), headers=headers)
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers['X-ComfyLink-Preview-Note'], 'Preview uses the verified AE working space')
            self.assertTrue((await response.read()).startswith(b'\x89PNG'))
            colour['ocioConfigFileSha256'] = '0'*64
            bad=processing_authority(self.manifest);bad['sourceConfigSha256']='0'*64
            with self.assertRaises(ValueError):validate_processing_input(bad,self.manifest)
            response = await self.client.get(self.route(session, '/display-frame?index=0'), headers=headers)
            self.assertEqual(response.status, 422)

    async def test_display_rejects_changed_frame_and_revoked_session(self):
        import threading
        from comfylink import display_view
        self.manifest['colour'] = {'encoding': 'scene_linear_rec709', 'sceneLinear': True}
        session, headers = await self.create()
        original = self.source_bytes
        self.source_bytes = original[:-1] + bytes([original[-1] ^ 1])
        response = await self.client.get(self.route(session, '/display-frame?index=0'), headers=headers)
        self.assertEqual(response.status, 422)
        self.source_bytes = original
        started, release = threading.Event(), threading.Event()
        def delayed_render(*args):
            started.set()
            if not release.wait(5): raise RuntimeError('Preview fixture timed out')
            return b'not delivered after revocation'
        with patch.object(display_view, 'render', delayed_render):
            pending = asyncio.create_task(self.client.get(self.route(session, '/display-frame?index=0'), headers=headers))
            self.assertTrue(await asyncio.to_thread(started.wait, 3))
            response = await self.client.post(self.route(session, '/leave'), headers=headers, json={})
            self.assertEqual(response.status, 200)
            release.set()
            response = await pending
            self.assertEqual(response.status, 410)
            self.assertNotIn(b'not delivered', await response.read())

    async def test_desktop_registration_needs_no_environment_token_and_is_one_use(self):
        with patch.dict(os.environ, {}, clear=True):
            session, headers = await self.create()
        self.assertEqual(len(session["id"]), 32)
        self.assertEqual(len(session["capability"]), 64)
        self.assertNotIn(self.token, json.dumps(session))
        response = await self.client.get(self.route(session), headers=headers)
        context = await response.json()
        self.assertEqual(context["context"]["target"], {"label": "AE layer"})
        self.assertNotIn("capability", context)
        response = await self.client.post(PREFIX + '/sessions', json={"broker": self.broker_url, "token": self.token})
        self.assertEqual(response.status, 409)

    async def test_session_capability_protects_other_tabs_and_foreign_origins(self):
        session, headers = await self.create()
        for auth in ({}, {SESSION_HEADER: "0" * 64}, {**headers, "Origin": "http://127.0.0.1:1"}):
            response = await self.client.get(self.route(session), headers=auth)
            self.assertEqual(response.status, 403)
        response = await self.client.post(self.route(session, '/source'), headers=headers, json={})
        self.assertEqual(response.status, 200)

    async def test_source_staging_preserves_float_bits_and_colour(self):
        session, headers = await self.create()
        response = await self.client.post(self.route(session, '/source'), headers=headers, json={})
        self.assertEqual(response.status, 200, await response.text())
        value = await response.json()
        self.assertNotIn('studioAsset', value)
        self.assertNotIn('mediaInfo', value)
        self.assertEqual(value["colour"], self.manifest["colour"])
        samples, _ = float_io.load_transfer(self.inputs, 'ComfyLink/' + session['id'] + '/manifest.json')
        self.assertEqual(samples.tobytes(), self.payload.tobytes())
        response = await self.client.post(self.route(session, '/source'), headers=headers, json={})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.broker_calls.count('source'), 1)

    async def test_source_admission_rejects_low_disk_before_download(self):
        session, headers = await self.create()
        with patch('comfylink.studio_sessions.shutil.disk_usage', return_value=types.SimpleNamespace(free=0)):
            response = await self.client.post(self.route(session,'/source'), headers=headers,json={})
        self.assertEqual(response.status,507)
        self.assertNotIn('blob',self.broker_calls)
        self.assertFalse((self.inputs/'ComfyLink').exists())

    async def test_large_source_reserves_memory_headroom_for_ae_and_os(self):
        with patch.object(float_io,'available_memory_bytes',return_value=8*1024**3-1):
            with self.assertRaisesRegex(ValueError,'8.0 GiB'):
                self.service.check_stream_memory(3840*2160*16)
        with patch.object(float_io,'available_memory_bytes',return_value=8*1024**3):
            self.service.check_stream_memory(3840*2160*16)

    async def test_source_validation_never_loads_a_whole_batch(self):
        session, headers = await self.create()
        with patch.object(float_io,'load_transfer',side_effect=AssertionError('whole batch forbidden')):
            response = await self.client.post(self.route(session,'/source'),headers=headers,json={})
        self.assertEqual(response.status,200,await response.text())

    @unittest.skipUnless(importlib.util.find_spec('OpenImageIO'),'OpenImageIO required for streamed native FLOAT cache')
    async def test_native_hdr_import_streams_101_actual_float_exrs(self):
        import OpenImageIO as oiio
        from test_comfylink_large_shot import tiny_frames
        native_root = self.root/'native-upload';native_root.mkdir()
        received=[]
        async def native_upload(request):
            reader=await request.multipart()
            while (part:=await reader.next()) is not None:
                path=native_root/part.filename
                with path.open('xb') as stream:
                    while chunk:=await part.read_chunk():stream.write(chunk)
                image=oiio.ImageInput.open(str(path))
                try:
                    spec=image.spec()
                    self.assertEqual(spec.format,oiio.FLOAT)
                    data=image.read_image(format=oiio.FLOAT)[:,:, [list(spec.channelnames).index(c) for c in 'RGBA']]
                    received.append(data.tobytes())
                finally:image.close()
            return web.json_response({'id':'e'*32,'kind':'asset','asset_kind':'hdr_sequence','count':len(received)})
        app=web.Application();app.router.add_post('/zura/studio/hdr/exr-sequence',native_upload)
        native=TestServer(app,host='127.0.0.1');await native.start_server()
        try:
            identity='f'*32
            relative,manifest=float_io.write_transfer_frames(self.inputs,'ComfyLink/'+identity,tiny_frames(),
                colour={'encoding':'acescg','sceneLinear':True},frame_rate={'numerator':25,'denominator':1},expected_count=101)
            session=types.SimpleNamespace(id=identity,origin=str(native.make_url('/')).rstrip('/'),closed=False,expires=time.time()+600)
            self.service.sessions[identity]=session
            with patch.object(float_io,'load_transfer',side_effect=AssertionError('whole batch forbidden')),patch.object(np,'stack',side_effect=AssertionError('whole batch forbidden')):
                result=await self.service.native_import(session,self.inputs/Path(relative).parent,manifest)
            self.assertEqual(result['studioAsset']['count'],101)
            self.assertEqual(received,[frame.tobytes() for frame in tiny_frames()])
        finally:await native.close()

    async def test_ssrf_urls_rejected_before_network(self):
        for url in ('http://example.com/studio-bridge/' + self.broker_id,
                    'http://localhost:2/studio-bridge/' + self.broker_id,
                    'https://127.0.0.1:2/studio-bridge/' + self.broker_id,
                    self.broker_url + '?url=http://example.com', self.broker_url + '#x',
                    self.broker_url.replace('127.0.0.1', 'user@127.0.0.1'),
                    self.broker_url.replace('/studio-bridge/', '/other/')):
            response = await self.client.post(PREFIX + '/sessions', json={"broker": url, "token": self.token})
            self.assertEqual(response.status, 400, url)
        self.assertEqual(self.broker_calls, [])

    async def test_grant_foreign_instance_expired_or_target_path_is_rejected(self):
        for override, status in (({"comfyOrigin": "http://127.0.0.1:1"}, 403),
                                 ({"expiresAt": "2000-01-01T00:00:00Z"}, 410),
                                 ({"target": {"label": "AE", "projectPath": "secret"}}, 502)):
            self.grant_override = override
            response = await self.client.post(PREFIX + '/sessions', json={"broker": self.broker_url, "token": self.token})
            self.assertEqual(response.status, status)
            self.assertEqual(len(self.service.sessions), 0)

    async def test_broker_redirect_is_not_followed(self):
        self.redirect_grant = True
        response = await self.client.post(PREFIX + '/sessions', json={"broker": self.broker_url, "token": self.token})
        self.assertEqual(response.status, 502)
        self.assertEqual(self.broker_calls, ['grant'])

    async def test_source_icc_requires_verified_profile_payload(self):
        self.manifest['colour'] = {"encoding": "ae_project_icc", "sceneLinear": False, "profileSha256": 'f' * 64}
        session, headers = await self.create()
        response = await self.client.post(self.route(session, '/source'), headers=headers, json={})
        self.assertEqual(response.status, 422)
        self.assertNotIn('blob', self.broker_calls)

    async def test_expiry_and_leave_revoke_all_local_authority(self):
        session, headers = await self.create()
        response = await self.client.post(self.route(session, '/leave'), headers=headers, json={})
        self.assertEqual(response.status, 200)
        self.assertIn('leave', self.broker_calls)
        self.assertNotIn(session['id'], self.service.sessions)
        response = await self.client.get(self.route(session), headers=headers)
        self.assertEqual(response.status, 410)
        self.service.used.clear()
        session, headers = await self.create()
        self.service.sessions[session['id']].expires = time.time() - 1
        response = await self.client.post(self.route(session, '/source'), headers=headers, json={})
        self.assertEqual(response.status, 410)
        if self.service._revocations:
            await asyncio.gather(*self.service._revocations)
        self.assertEqual(self.broker_calls.count('leave'), 2)

    async def test_leave_revokes_before_an_inflight_result_is_released(self):
        self.pause_result = True
        relative, _ = float_io.write_transfer(self.outputs, 'ComfyLink/' + 'd' * 32, self.payload,
            colour=self.manifest['colour'], frame_rate={"numerator": 24, "denominator": 1})
        session, headers = await self.create()
        authority = self.service.sessions[session['id']]
        result_task = asyncio.create_task(self.client.post(self.route(session, '/result'), headers=headers, json={
            "kind": "float_sequence", "master": {"filename": "manifest.json", "subfolder": 'ComfyLink/' + 'd' * 32, "type": "output"}}))
        try:
            await asyncio.wait_for(self.result_entered.wait(), 2)
            self.assertTrue(authority.lock.locked())
            leave = await asyncio.wait_for(self.client.post(self.route(session, '/leave'), headers=headers, json={}), 2)
            self.assertEqual(leave.status, 200)
            self.assertTrue(authority.closed)
            self.assertNotIn(session['id'], self.service.sessions)
            self.assertEqual(authority.download_capability, '')
            self.assertEqual(authority.token, '')
            self.assertTrue(self.broker_revoked)
            self.assertFalse(self.native_applied)
        finally:
            self.release_result.set()
        result = await asyncio.wait_for(result_task, 2)
        self.assertEqual(result.status, 410)
        self.assertFalse(self.native_applied)

    async def test_nonfinite_pixels_never_publish(self):
        self.source_bytes = np.full((1, 1, 1, 4), np.nan, dtype='<f4').tobytes()
        self.manifest['frames'][0]['sha256'] = hashlib.sha256(self.source_bytes).hexdigest()
        session, headers = await self.create()
        response = await self.client.post(self.route(session, '/source'), headers=headers, json={})
        self.assertEqual(response.status, 422)
        self.assertFalse((self.inputs / 'ComfyLink' / session['id']).exists())
        self.assertEqual(list((self.inputs / 'ComfyLink').iterdir()), [])

    async def test_manifest_paths_integrity_and_existing_folder_are_rejected(self):
        session, headers = await self.create()
        self.manifest['frames'][0]['filename'] = '../foreign'
        response = await self.client.post(self.route(session, '/source'), headers=headers, json={})
        self.assertEqual(response.status, 422)
        self.manifest['frames'][0]['filename'] = '000001.rgba32f'
        foreign = self.inputs / 'ComfyLink' / session['id']
        foreign.mkdir(parents=True)
        (foreign / 'keep').write_text('foreign')
        response = await self.client.post(self.route(session, '/source'), headers=headers, json={})
        self.assertEqual(response.status, 422)
        self.assertEqual((foreign / 'keep').read_text(), 'foreign')
        self.assertNotIn('blob', self.broker_calls)

    async def test_master_transfer_download_is_scoped_and_capability_not_returned(self):
        session, headers = await self.create()
        rel, _ = float_io.write_transfer(self.outputs, 'ComfyLink/' + 'd' * 32, self.payload,
            colour={"encoding": "unknown", "sceneLinear": False}, frame_rate={"numerator": 24, "denominator": 1})
        response = await self.client.post(self.route(session, '/result'), headers=headers, json={
            "kind": "float_sequence", "master": {"filename": "manifest.json", "subfolder": 'ComfyLink/' + 'd' * 32, "type": "output"},
            "preview": {"filename": "never-read.png", "subfolder": "", "type": "output"}})
        self.assertEqual(response.status, 200, await response.text())
        visible = await response.json()
        self.assertEqual(visible, {"ok": True, "status": "sent", "diagnostic": "Sent to After Effects"})
        descriptor = self.received[-1]
        self.assertNotIn('originals', descriptor)
        self.assertEqual(descriptor['manifest'], self.manifest)
        response = await self.client.get(self.route(session, '/result-files/0'), headers={DOWNLOAD_HEADER: descriptor['downloadCapability']})
        self.assertEqual(response.status, 403)

    async def test_foreign_or_unsupported_result_retains_pending(self):
        session, headers = await self.create()
        (self.outputs / 'unsupported.bin').write_bytes(b'not media')
        for ref in ({"filename": "../outside", "type": "output"}, {"filename": "x", "subfolder": "../outside", "type": "output"},
                    {"filename": "unsupported.bin", "type": "output"}, {"filename": "unsupported.bin", "type": "input"}):
            response = await self.client.post(self.route(session, '/result'), headers=headers, json={"kind": "image", "master": ref})
            self.assertEqual(response.status, 422)
            self.assertEqual((await response.json())['status'], 'pending')
        self.assertEqual(self.received, [])

    async def test_png_sdr_master_supported_but_cannot_claim_hdr(self):
        from PIL import Image
        Image.new('RGBA', (1, 1), (64, 128, 255, 128)).save(self.outputs / 'master.png')
        session, headers = await self.create()
        body = {"kind": "image", "master": {"filename": "master.png", "subfolder": "", "type": "output"}, "fps": 24}
        response = await self.client.post(self.route(session, '/result'), headers=headers, json={**body, "colour": {"encoding": "acescg", "sceneLinear": True}})
        self.assertEqual(response.status, 422)
        response = await self.client.post(self.route(session, '/result'), headers=headers, json=body)
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(self.received[-1]['manifest']['sourceBitDepth'], 8)
        self.assertEqual(self.received[-1]['colour'], {"encoding": "unknown", "sceneLinear": False})
        original, encoded = self.received_originals[-1]
        self.assertEqual(encoded, (self.outputs / 'master.png').read_bytes())
        self.assertEqual(original['mediaType'], 'image/png')
        self.assertNotIn('storage', original)
        self.assertEqual(self.received[-1]['provenance'], {"schemaVersion": 1, "kind": "sdr8_image", "sourceBitDepth": 8,
            "embeddedICC": False, "hdrMetadata": False, "transfer": "unspecified", "primaries": "unspecified",
            "validatedFrameCount": 1, "originalSha256": original['sha256']})

    async def test_colour_managed_or_hdr_images_are_retained_without_sdr_provenance(self):
        from PIL import Image, PngImagePlugin
        session, headers = await self.create()
        image = Image.new('RGB', (2, 2), (64, 128, 255))
        cases = [('icc.png', {'icc_profile': b'not-an-unmanaged-profile'}),
                 ('gamma.png', {'pnginfo': self.png_chunk(PngImagePlugin, b'gAMA', (45455).to_bytes(4, 'big'))}),
                 ('hdr.png', {'pnginfo': self.png_chunk(PngImagePlugin, b'cICP', b'\x09\x10\x09\x01')}),
                 ('icc.webp', {'icc_profile': b'not-an-unmanaged-profile'})]
        exif = Image.Exif(); exif[0xa001] = 1
        cases.append(('exif.jpg', {'exif': exif}))
        for filename, options in cases:
            image.save(self.outputs / filename, **options)
            response = await self.client.post(self.route(session, '/result'), headers=headers, json={
                "kind": "image", "master": {"filename": filename, "type": "output"}})
            self.assertEqual(response.status, 422, filename)
            self.assertTrue((self.outputs / filename).is_file())
        self.assertEqual(self.received, [])

    @staticmethod
    def png_chunk(plugin, kind, payload):
        result = plugin.PngInfo()
        result.add(kind, payload)
        return result

    async def test_actual_jpeg_webp_and_standard_srgb_png_get_bound_provenance(self):
        from PIL import Image, PngImagePlugin
        session, headers = await self.create()
        for filename, options, transfer in (('plain.jpg', {}, 'unspecified'), ('plain.webp', {}, 'unspecified'),
                ('srgb.png', {'pnginfo': self.png_chunk(PngImagePlugin, b'sRGB', b'\0')}, 'srgb')):
            Image.new('RGB', (2, 2), (32, 128, 224)).save(self.outputs / filename, **options)
            response = await self.client.post(self.route(session, '/result'), headers=headers, json={
                "kind": "image", "master": {"filename": filename, "type": "output"}})
            self.assertEqual(response.status, 200, await response.text())
            proof = self.received[-1]['provenance']
            self.assertEqual(proof['transfer'], transfer)
            self.assertEqual(proof['sourceBitDepth'], 8)
            self.assertEqual(proof['originalSha256'], self.received[-1]['originals'][0]['sha256'])
            self.assertEqual(proof['validatedFrameCount'], self.received[-1]['frameCount'])

    async def test_ae_import_pending_is_not_reported_as_sent(self):
        from PIL import Image
        Image.new('RGB', (1, 1)).save(self.outputs / 'master.png')
        self.result_status = 'import_pending'
        session, headers = await self.create()
        response = await self.client.post(self.route(session, '/result'), headers=headers, json={
            "kind": "image", "master": {"filename": "master.png", "subfolder": "", "type": "output"}})
        self.assertEqual(response.status, 202)
        self.assertEqual((await response.json())['status'], 'import_pending')

    async def test_status_polling_confirms_import_without_duplicate_submission(self):
        session, headers = await self.create()
        self.result_status = 'import_pending'
        response = await self.client.get(self.route(session, '/status'), headers=headers)
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {"ok": True, "ready": True, "importPending": True, "status": "import_pending"})
        self.result_status = 'sent'
        response = await self.client.get(self.route(session, '/status'), headers=headers)
        self.assertEqual((await response.json())['status'], 'sent')
        self.assertEqual(self.received, [])
        response = await self.client.get(self.route(session, '/status'))
        self.assertEqual(response.status, 403)

    async def test_prepare_graph_is_scoped_to_immutable_source_and_native_outputs(self):
        session, headers = await self.create()
        await self.client.post(self.route(session, '/source'), headers=headers, json={})
        contract = {"schemaVersion": 1, "sessionId": session['id'], "frameCount": 1,
            "frameRate": {"numerator": 24, "denominator": 1}, "width": 1, "height": 1, "modelFrames": 1, "trimFrames": 1}
        graph = {"source": {"class_type": "LoadImage", "inputs": {"image": "owned-source.png"}},
                 "save": {"class_type": "SaveImage", "inputs": {"images": ["source", 0], "filename_prefix": "ComfyLink/result"}}}
        body = {"mode": "image", "graph": graph, "ae_frame_contract": contract}
        response = await self.client.post(self.route(session, '/prepare-graph'), headers=headers, json=body)
        self.assertEqual(response.status, 200, await response.text())
        prepared = (await response.json())['graph']
        self.assertTrue(any(node['class_type'] == 'ZuraComfyLinkMatchFrames' for node in prepared.values()))
        self.assertEqual(len(graph), 2)
        for change in ({"sessionId": 'f' * 32}, {"width": 2}, {"frameCount": 2, "trimFrames": 2, "modelFrames": 2},
                       {"frameRate": {"numerator": 25, "denominator": 1}}):
            response = await self.client.post(self.route(session, '/prepare-graph'), headers=headers,
                json={**body, "ae_frame_contract": {**contract, **change}})
            self.assertEqual(response.status, 422)
        unsafe = copy.deepcopy(body)
        unsafe['graph']['save']['inputs']['filename_prefix'] = '../outside'
        response = await self.client.post(self.route(session, '/prepare-graph'), headers=headers, json=unsafe)
        self.assertEqual(response.status, 422)
        response = await self.client.post(self.route(session, '/prepare-graph'), json=body)
        self.assertEqual(response.status, 403)
        self.assertEqual(self.received, [])

    async def test_alpha_graph_and_float_master_bind_original_source_and_keep_mov(self):
        self.manifest['sourceStart'] = {'numerator': 0, 'denominator': 1}
        session, headers = await self.create()
        response = await self.client.post(self.route(session, '/source'), headers=headers, json={})
        self.assertEqual(response.status, 200)
        contract = {'schemaVersion': 1, 'sessionId': session['id'], 'frameCount': 1,
            'frameRate': {'numerator': 24, 'denominator': 1}, 'width': 1, 'height': 1,
            'modelFrames': 9, 'trimFrames': 1, 'sourceManifestSha256': 'f'*64}
        graph = {'source': {'class_type': 'ZuraAlphaVideoInput', 'inputs': {}},
                 'save': {'class_type': 'ZuraAlphaVideoOutput', 'inputs': {'images': ['source', 0], 'info': ['source', 1], 'filename_prefix': 'alpha'}}}
        response = await self.client.post(self.route(session, '/prepare-graph'), headers=headers,
            json={'mode': 'alpha', 'graph': graph, 'ae_frame_contract': contract})
        self.assertEqual(response.status, 200, await response.text())
        prepared = await response.json()
        fingerprint = hashlib.sha256(float_io.canonical_manifest_bytes(self.manifest)).hexdigest()
        self.assertEqual(prepared['ae_frame_contract']['sourceManifestSha256'], fingerprint)
        self.assertEqual(json.loads(prepared['graph']['save']['inputs']['ae_frame_contract'])['sourceManifestSha256'], fingerprint)
        pixels = self.payload.copy();pixels[..., 3] *= np.float32(.1234567)
        relative, master = float_io.write_transfer(self.outputs, 'ComfyLink/'+'e'*32, pixels,
            colour=self.manifest['colour'], frame_rate=self.manifest['frameRate'], source_start=self.manifest['sourceStart'])
        original = self.outputs/'alpha.mov'; original.write_bytes(b'retained MOV fixture')
        body = {'kind': 'alpha_extract', 'master': {'filename': 'manifest.json', 'subfolder': str(Path(relative).parent).replace('\\','/'), 'type': 'output'},
                'original': {'filename': 'alpha.mov', 'subfolder': '', 'type': 'output'}}
        response = await self.client.post(self.route(session, '/result'), headers=headers, json=body)
        self.assertEqual(response.status, 200, await response.text())
        descriptor = self.received[0]
        self.assertEqual(descriptor['kind'], 'alpha_extract')
        self.assertEqual(descriptor['manifest']['sourceBitDepth'], 32)
        self.assertEqual(descriptor['provenance'], {'schemaVersion': 1, 'kind': 'source_alpha_float32',
            'sourceManifestSha256': fingerprint, 'alphaOperation': 'multiply',
            'originalSha256': hashlib.sha256(original.read_bytes()).hexdigest()})
        self.assertEqual(self.received_originals[0][1], original.read_bytes())

    async def test_intermediate_image_is_bound_to_parent_and_cannot_relax_final_video(self):
        session, headers = await self.create()
        _, manifest = float_io.write_transfer(self.inputs, 'ComfyLink/' + 'd' * 32,
            np.repeat(self.payload, 9, axis=0), colour={'encoding': 'unknown', 'sceneLinear': False},
            frame_rate={'numerator': 24, 'denominator': 1})
        self.service.sessions[session['id']].source = {'manifest': manifest}
        contract = {'schemaVersion': 1, 'sessionId': session['id'], 'frameCount': 9,
            'frameRate': {'numerator': 24, 'denominator': 1}, 'width': 1, 'height': 1, 'modelFrames': 9, 'trimFrames': 9}
        intermediate = {'schemaVersion': 1, 'kind': 'ripple_keyframe', 'handoffId': 'handoff-1',
            'anchorId': 'anchor-1', 'sourceFrame': 8, 'width': 1, 'height': 1,
            'parentSessionId': session['id'], 'parentFrameCount': 9}
        graph = {'source': {'class_type': 'LoadImage', 'inputs': {'image': 'source.png'}},
                 'save': {'class_type': 'SaveImage', 'inputs': {'images': ['source', 0], 'filename_prefix': 'ordinary'}}}
        body = {'mode': 'image', 'graph': graph, 'ae_frame_contract': contract, 'ae_intermediate_image': intermediate}
        response = await self.client.post(self.route(session, '/prepare-graph'), headers=headers, json=body)
        self.assertEqual(response.status, 200, await response.text())
        result = await response.json()
        self.assertEqual(result['ae_frame_contract']['frameCount'], 1)
        self.assertEqual(result['ae_intermediate_image'], intermediate)
        self.assertEqual(self.service.sessions[session['id']].source['manifest'], manifest)
        for change in ({'parentSessionId': 'f' * 32}, {'parentFrameCount': 1}, {'sourceFrame': 9},
                       {'sourceFrame': -1}, {'width': 2}, {'anchorId': ''}):
            response = await self.client.post(self.route(session, '/prepare-graph'), headers=headers,
                json={**body, 'ae_intermediate_image': {**intermediate, **change}})
            self.assertEqual(response.status, 422, change)
        for invalid in ({**body, 'mode': 'paintout'}, {**body, 'ae_frame_contract': result['ae_frame_contract']},
                        {key: value for key, value in body.items() if key != 'ae_intermediate_image'}):
            response = await self.client.post(self.route(session, '/prepare-graph'), headers=headers, json=invalid)
            self.assertEqual(response.status, 422)
        video = {'source': graph['source'], 'video': {'class_type': 'CreateVideo', 'inputs': {'images': ['source', 0], 'fps': 24}},
                 'save': {'class_type': 'SaveVideo', 'inputs': {'video': ['video', 0], 'filename_prefix': 'final'}}}
        response = await self.client.post(self.route(session, '/prepare-graph'), headers=headers,
            json={'mode': 'paintout', 'graph': video, 'ae_frame_contract': contract})
        self.assertEqual(response.status, 200, await response.text())
        result = await response.json()
        self.assertEqual(result['ae_frame_contract']['frameCount'], 9)
        self.assertEqual(result['graph']['zura_ae_match_frames_0']['inputs']['frame_count'], 9)
        response = await self.client.post(self.route(session, '/prepare-graph'), json=body)
        self.assertEqual(response.status, 403)
        self.assertEqual(self.received, [])

    async def test_intermediate_master_cannot_be_sent_as_even_a_single_frame_final(self):
        from PIL import Image
        session, headers = await self.create()
        folder = self.outputs / 'ComfyLink' / 'intermediate' / session['id'] / 'handoff-1'
        folder.mkdir(parents=True)
        path = folder / 'guide.png'
        Image.new('RGB', (1, 1)).save(path)
        original = path.read_bytes()
        response = await self.client.post(self.route(session, '/result'), headers=headers, json={
            'kind': 'image', 'master': {'filename': path.name, 'subfolder': folder.relative_to(self.outputs).as_posix(), 'type': 'output'}})
        self.assertEqual(response.status, 422)
        self.assertEqual(self.received, [])
        self.assertEqual(path.read_bytes(), original)

    async def test_still_result_inherits_exact_authenticated_source_cadence(self):
        from PIL import Image
        path = self.outputs / 'still.png'
        Image.new('RGB', (1, 1), (10, 20, 30)).save(path)
        original = path.read_bytes()
        session, headers = await self.create()
        for rate in ({'numerator': 25, 'denominator': 1}, {'numerator': 30000, 'denominator': 1001}):
            self.service.sessions[session['id']].source = {}
            source = {**copy.deepcopy(self.manifest), 'frameRate': rate}
            self.source_override = {'manifest': source}
            for staged in (False, True):
                if staged:
                    self.service.sessions[session['id']].source = {'manifest': source}
                body = {'kind': 'image', 'master': {'filename': path.name, 'type': 'output'}}
                response = await self.client.post(self.route(session, '/result'), headers=headers, json=body)
                self.assertEqual(response.status, 200, await response.text())
                self.assertEqual(self.received[-1]['manifest']['frameRate'], rate)
                self.assertEqual(self.received[-1]['frameCount'], 1)
                self.assertEqual(self.received_originals[-1][1], original)
                response = await self.client.post(self.route(session, '/result'), headers=headers,
                    json={**body, 'fps': 24})
                self.assertEqual(response.status, 422, 'Browser frame-rate labels cannot override the source cadence')

    @staticmethod
    def native_module(name):
        # Load the actual sibling helpers without running Studio's registration
        # side effects in this standalone CPU test process.
        import v2_bootstrap
        for suffix in ('artist_studio', 'paintout'):
            key = 'ComfyUI_zura_nodes.' + suffix
            if key not in sys.modules:
                package = types.ModuleType(key)
                package.__path__ = [str(v2_bootstrap.ROOT / suffix)]
                sys.modules[key] = package
        return importlib.import_module('ComfyUI_zura_nodes.artist_studio.' + name)

    @unittest.skipUnless(importlib.util.find_spec('OpenImageIO'), 'OpenImageIO required for actual native HDR ZIP')
    async def test_actual_native_hdr_package_zip_float_half_retained_and_decoded(self):
        import OpenImageIO as oiio
        native = self.native_module('hdr_package')
        paintout = importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')
        session, headers = await self.create()
        source = copy.deepcopy(self.manifest)
        source['frameRate'] = {"numerator": 30000, "denominator": 1001}
        self.service.sessions[session['id']].source = {"manifest": source}
        for storage in ('float32', 'half'):
            prefix = 'native_' + storage
            directory = self.outputs / 'genj' / 'hdr' / prefix
            directory.mkdir(parents=True)
            rgb = np.ascontiguousarray(self.payload[0, :, :, :3])
            frame = directory / 'frame_00000.exr'
            paintout.save_exr(frame, rgb, 'acescg', storage == 'half')
            path = native.package_sequence(self.outputs, prefix, 1)
            expected_zip = path.read_bytes()
            with patch('comfylink.studio_sessions._studio_module', side_effect=self.native_module):
                response = await self.client.post(self.route(session, '/result'), headers=headers, json={
                    "kind": "hdr_sequence", "master": {"filename": path.name, "subfolder": 'genj/hdr', "type": "output"}})
            self.assertEqual(response.status, 200, await response.text())
            descriptor = self.received[-1]
            self.assertEqual(descriptor['manifest']['colour'], {"encoding": "acescg", "sceneLinear": True})
            self.assertEqual(descriptor['manifest']['frameRate'], source['frameRate'])
            self.assertEqual(self.received_originals[-1][1], expected_zip)
            self.assertEqual(self.received_originals[-1][0]['mediaType'], 'application/zip')
            reader = oiio.ImageInput.open(str(frame))
            try:
                spec = reader.spec()
                decoded = reader.read_image(format=oiio.FLOAT)[:, :, [list(spec.channelnames).index(c) for c in 'RGB']]
            finally:
                reader.close()
            actual, _ = float_io.load_transfer(self.outputs, descriptor['master']['subfolder'] + '/manifest.json')
            self.assertEqual(actual[0, :, :, :3].tobytes(), decoded.tobytes())
            self.assertTrue(np.all(actual[..., 3] == 1))

    @unittest.skipUnless(importlib.util.find_spec('OpenImageIO') and importlib.util.find_spec('torch'), 'Native HDR exporter dependencies required')
    async def test_actual_rgba_hdr_export_zip_transfers_alpha_and_hdr(self):
        import shutil
        from test_hdr_alpha_delivery import HDRAlphaDeliveryTests, export
        from fractions import Fraction
        fixture = HDRAlphaDeliveryTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        session, headers = await self.create()
        source = copy.deepcopy(self.manifest); source['frameRate'] = {'numerator':30000,'denominator':1001}
        self.service.sessions[session['id']].source = {'manifest': source}
        for count in (1, 9):
            alpha, values, _ = fixture.source(count)
            stage = fixture.staged(count, 'a' if count == 1 else 'b')
            actual_archive = export.export_rgba_exr_zip(stage, fixture.root, 'interop_' + str(count), alpha_source=alpha, frame_rate=Fraction(30000,1001))
            path = self.outputs / ('rgba_' + str(count) + '.zip'); shutil.copyfile(actual_archive, path)
            response = await self.client.post(self.route(session, '/result'), headers=headers, json={
                'kind':'hdr_sequence', 'master':{'filename':path.name,'type':'output'}})
            self.assertEqual(response.status, 200, await response.text())
            frames, manifest = float_io.load_transfer(self.outputs, self.received[-1]['master']['subfolder'] + '/manifest.json')
            self.assertEqual(len(frames), count); self.assertEqual(manifest['colour'], {'encoding':'acescg','sceneLinear':True})
            np.testing.assert_array_equal(frames[0,:,:,3].view(np.uint32), values.view(np.uint32))
            self.assertGreater(float(frames[0,1,0,2]), 1)
            self.assertEqual(self.received_originals[-1][1], path.read_bytes())
            if count == 1:
                with zipfile.ZipFile(path) as z: members = {n:z.read(n) for n in z.namelist()}
                for field in ('alphaSha256','sha256'):
                    proof = json.loads(members['zura_hdr_delivery.json']); proof['frames'][0][field] = '0'*64
                    bad = self.outputs / ('invalid_'+field+'.zip')
                    with zipfile.ZipFile(bad, 'w', compression=zipfile.ZIP_STORED) as z:
                        for name, data in members.items(): z.writestr(name, json.dumps(proof).encode() if name == 'zura_hdr_delivery.json' else data)
                    before = len(self.received)
                    denied = await self.client.post(self.route(session, '/result'), headers=headers, json={
                        'kind':'hdr_sequence','master':{'filename':bad.name,'type':'output'}})
                    self.assertEqual(denied.status, 422);self.assertEqual(len(self.received),before)
                    self.assertTrue(bad.is_file())

    @unittest.skipUnless(importlib.util.find_spec('OpenImageIO'), 'OpenImageIO required for native ZIP validation')
    async def test_native_zip_rejects_paths_links_duplicates_compression_gaps_and_limits(self):
        session, headers = await self.create()
        self.service.sessions[session['id']].source = {"manifest": copy.deepcopy(self.manifest)}
        cases = [('../escape.exr', zipfile.ZIP_STORED, False), ('C:/escape.exr', zipfile.ZIP_STORED, False),
                 ('frame_00002.exr', zipfile.ZIP_STORED, False), ('frame_00000.exr', zipfile.ZIP_DEFLATED, False),
                 ('frame_00000.exr', zipfile.ZIP_STORED, True)]
        for index, (name, compression, symlink) in enumerate(cases):
            path = self.outputs / f'unsafe{index}.zip'
            info = zipfile.ZipInfo(name)
            info.compress_type = compression
            if symlink:
                info.create_system, info.external_attr = 3, 0o120777 << 16
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr(info, b'x' * 1024)
            response = await self.client.post(self.route(session, '/result'), headers=headers, json={
                "kind": "hdr_sequence", "master": {"filename": path.name, "type": "output"}})
            self.assertEqual(response.status, 422)
            self.assertTrue(path.is_file())
        duplicate = self.outputs / 'duplicate.zip'
        with zipfile.ZipFile(duplicate, 'w') as archive:
            archive.writestr('frame_00000.exr', b'x')
            archive.writestr('FRAME_00000.EXR', b'x')
        response = await self.client.post(self.route(session, '/result'), headers=headers, json={
            "kind": "hdr_sequence", "master": {"filename": duplicate.name, "type": "output"}})
        self.assertEqual(response.status, 422)
        oversized = self.outputs / 'oversized.zip'
        with zipfile.ZipFile(oversized, 'w') as archive:
            archive.writestr('frame_00000.exr', b'x' * 128)
        with patch.object(float_io, 'MAX_TRANSFER_BYTES', 64):
            response = await self.client.post(self.route(session, '/result'), headers=headers, json={
                "kind": "hdr_sequence", "master": {"filename": oversized.name, "type": "output"}})
        self.assertEqual(response.status, 422)
        metadata = self.outputs / 'hardlink-extra.zip'
        info = zipfile.ZipInfo('frame_00000.exr')
        info.extra = b'\x0d\x00\x01\x00x'  # Unix extra field may carry link targets.
        with zipfile.ZipFile(metadata, 'w') as archive:
            archive.writestr(info, b'x')
        encrypted = self.outputs / 'encrypted.zip'
        with zipfile.ZipFile(encrypted, 'w') as archive:
            archive.writestr('frame_00000.exr', b'x')
        encoded = bytearray(encrypted.read_bytes())
        central = encoded.index(b'PK\x01\x02')
        encoded[6:8] = (1).to_bytes(2, 'little')
        encoded[central + 8:central + 10] = (1).to_bytes(2, 'little')
        encrypted.write_bytes(encoded)
        for path in (metadata, encrypted):
            response = await self.client.post(self.route(session, '/result'), headers=headers, json={
                "kind": "hdr_sequence", "master": {"filename": path.name, "type": "output"}})
            self.assertEqual(response.status, 422)
        count = self.outputs / 'too-many-frames.zip'
        with zipfile.ZipFile(count, 'w') as archive:
            archive.writestr('frame_00000.exr', b'x')
            archive.writestr('frame_00001.exr', b'x')
        with patch.object(float_io, 'MAX_FRAMES', 1):
            response = await self.client.post(self.route(session, '/result'), headers=headers, json={
                "kind": "hdr_sequence", "master": {"filename": count.name, "type": "output"}})
        self.assertEqual(response.status, 422)
        self.assertEqual(self.received, [])
        self.assertFalse((self.outputs / 'ComfyLink').exists())

    @unittest.skipUnless(importlib.util.find_spec('OpenImageIO'), 'OpenImageIO required for native ZIP profile validation')
    async def test_native_zip_unknown_profile_is_pending_and_private_extraction_removed(self):
        native = self.native_module('hdr_package')
        paintout = importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')
        directory = self.outputs / 'genj' / 'hdr' / 'wrong_profile'
        directory.mkdir(parents=True)
        paintout.save_exr(directory / 'frame_00000.exr', self.payload[0, :, :, :3], 'acescct', False)
        path = native.package_sequence(self.outputs, 'wrong_profile', 1)
        session, headers = await self.create()
        self.service.sessions[session['id']].source = {"manifest": copy.deepcopy(self.manifest)}
        with patch('comfylink.studio_sessions._studio_module', side_effect=self.native_module):
            response = await self.client.post(self.route(session, '/result'), headers=headers, json={
                "kind": "hdr_sequence", "master": {"filename": path.name, "subfolder": 'genj/hdr', "type": "output"}})
        self.assertEqual(response.status, 422)
        self.assertTrue(path.is_file())
        self.assertEqual(self.received, [])
        self.assertEqual(list((self.outputs / 'ComfyLink').iterdir()), [])

    async def test_hardlink_output_cannot_expose_foreign_file(self):
        foreign = self.root / 'foreign.png'
        from PIL import Image
        Image.new('RGB', (1, 1)).save(foreign)
        os.link(foreign, self.outputs / 'master.png')
        session, headers = await self.create()
        response = await self.client.post(self.route(session, '/result'), headers=headers, json={
            "kind": "image", "master": {"filename": "master.png", "subfolder": "", "type": "output"}})
        self.assertEqual(response.status, 422)
        self.assertEqual(self.received, [])

    async def test_real_sdr_video_master_preserves_frame_count_rate_and_alpha(self):
        import av
        from fractions import Fraction
        path = self.outputs / 'master.mkv'
        rate = Fraction(30000, 1001)
        with av.open(str(path), 'w') as container:
            stream = container.add_stream('ffv1', rate=rate)
            stream.width, stream.height, stream.pix_fmt = 2, 2, 'bgra'
            for index in range(2):
                rgba = np.full((2, 2, 4), (32 + index, 64, 128, 96), dtype=np.uint8)
                frame = av.VideoFrame.from_ndarray(rgba, format='rgba')
                frame.pts, frame.time_base = index, 1 / rate
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        session, headers = await self.create()
        response = await self.client.post(self.route(session, '/result'), headers=headers, json={
            "kind": "video", "master": {"filename": "master.mkv", "subfolder": "", "type": "output"}, "frameCount": 2})
        self.assertEqual(response.status, 200, await response.text())
        manifest = self.received[-1]['manifest']
        self.assertEqual(manifest['frameRate'], {"numerator": 30000, "denominator": 1001})
        samples, _ = float_io.load_transfer(self.outputs, self.received[-1]['master']['subfolder'] + '/manifest.json')
        self.assertTrue(np.array_equal(samples[0, 0, 0], np.array([32, 64, 128, 96], np.float32) / 255))
        original, encoded = self.received_originals[-1]
        self.assertEqual(encoded, path.read_bytes())
        self.assertEqual(original['mediaType'], 'video/x-matroska')
        self.assertEqual(self.received[-1]['provenance']['kind'], 'sdr8_video')
        self.assertEqual(self.received[-1]['provenance']['validatedFrameCount'], 2)
        self.assertEqual(self.received[-1]['provenance']['originalSha256'], original['sha256'])

    async def test_10bit_sdr_video_decode_keeps_more_than_eight_bit_precision(self):
        import av
        from fractions import Fraction
        path=self.outputs/'tenbit.mp4'
        try:
            with av.open(str(path),'w') as container:
                stream=container.add_stream('libx264',rate=Fraction(24,1))
                stream.width=32;stream.height=32;stream.pix_fmt='yuv420p10le'
                stream.codec_context.color_trc=13;stream.codec_context.color_primaries=1;stream.codec_context.colorspace=1;stream.codec_context.color_range=1
                for n in range(2):
                    rgb=np.arange(32*32*3,dtype=np.uint16).reshape(32,32,3)*19+n*13
                    for packet in stream.encode(av.VideoFrame.from_ndarray(rgb,format='rgb48le')):container.mux(packet)
                for packet in stream.encode():container.mux(packet)
        except (av.error.FFmpegError, ValueError): self.skipTest('10-bit x264 encoder unavailable')
        converted, _, proof = self.service.convert_master(path,{})
        pixels, manifest = float_io.load_transfer(self.outputs,converted.relative_to(self.outputs).as_posix())
        self.assertEqual(proof['kind'],'sdr10_video');self.assertEqual(proof['sourceBitDepth'],10)
        self.assertEqual(manifest['sourceBitDepth'],32);self.assertEqual(len(pixels),2)
        self.assertTrue(np.any(np.abs(pixels[...,:3]*255-np.rint(pixels[...,:3]*255))>1e-4))
        with av.open(str(path)) as media:
            expected=np.stack([frame.reformat(format='rgb48le',src_colorspace='ITU709',dst_colorspace='ITU709',src_color_range='MPEG',dst_color_range='JPEG').to_ndarray().astype(np.float32)/np.float32(65535) for frame in media.decode(video=0)])
        np.testing.assert_array_equal(pixels[...,:3],expected)
        session,headers=await self.create()
        self.service.sessions[session['id']].source={'manifest':copy.deepcopy(self.manifest)}
        response=await self.client.post(self.route(session,'/result'),headers=headers,json={'kind':'video','master':{'filename':path.name,'type':'output'}})
        self.assertEqual(response.status,200,await response.text())
        self.assertEqual(self.received[-1]['provenance']['kind'],'sdr10_video')
        self.assertEqual(self.received_originals[-1][1],path.read_bytes())

    async def test_actual_eight_bit_video_with_hdr_tags_is_not_labelled_sdr(self):
        import av
        path = self.outputs / 'hdr.mkv'
        with av.open(str(path), 'w') as container:
            stream = container.add_stream('ffv1', rate=24)
            stream.width, stream.height, stream.pix_fmt = 2, 2, 'bgra'
            stream.codec_context.color_trc, stream.codec_context.color_primaries, stream.codec_context.colorspace = 16, 9, 9
            frame = av.VideoFrame.from_ndarray(np.full((2, 2, 4), 128, np.uint8), format='rgba')
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        session, headers = await self.create()
        response = await self.client.post(self.route(session, '/result'), headers=headers, json={
            "kind": "video", "master": {"filename": path.name, "type": "output"}})
        self.assertEqual(response.status, 422)
        self.assertEqual(self.received, [])
        self.assertTrue(path.is_file())

    async def test_actual_h264_sdr_and_embedded_container_profile_guard(self):
        import av
        path = self.outputs / 'ordinary.mp4'
        with av.open(str(path), 'w') as container:
            stream = container.add_stream('libx264', rate=24)
            stream.width, stream.height, stream.pix_fmt = 16, 16, 'yuv420p'
            stream.codec_context.color_trc, stream.codec_context.color_primaries, stream.codec_context.colorspace = 1, 1, 1
            frame = av.VideoFrame.from_ndarray(np.full((16, 16, 3), 128, np.uint8), format='rgb24')
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        session, headers = await self.create()
        body = {"kind": "video", "master": {"filename": path.name, "type": "output"}}
        response = await self.client.post(self.route(session, '/result'), headers=headers, json=body)
        if response.status != 200:
            # Keep detailed codec failures in this synthetic fixture's test
            # output, while the public endpoint continues to redact paths.
            try:
                self.service.convert_master(path, {})
            except Exception as error:
                reason = str(error).replace(str(self.root), '<test-root>')
                self.fail(f'H.264 SDR fixture failed with PyAV {av.__version__}: {type(error).__name__}: {reason}')
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(self.received[-1]['provenance']['transfer'], 'bt709')
        self.assertEqual(self.received[-1]['provenance']['primaries'], 'bt709')
        # Even if a decoder build ignores a colour-profile atom, the original
        # container cannot acquire an unmanaged proof.
        with path.open('ab') as stream:
            stream.write((16).to_bytes(4, 'big') + b'colrprof' + b'ICC!')
        response = await self.client.post(self.route(session, '/result'), headers=headers, json=body)
        self.assertEqual(response.status, 422)
        self.assertEqual(len(self.received), 1)

    async def test_each_decoded_frame_rejects_hdr_and_high_depth(self):
        import av
        frame = av.VideoFrame(2, 2, 'rgba')
        self.assertEqual(_video_sdr_metadata(frame), (2, 2, 2))
        # A portable metadata view exercises an explicit per-frame HLG tag
        # even on PyAV versions which do not expose those frame properties.
        hdr_frame = types.SimpleNamespace(format=frame.format, side_data=(),
            color_trc=18, color_primaries=2, colorspace=2)
        with self.assertRaises(ValueError):
            _video_sdr_metadata(hdr_frame, (1, 1, 1))
        with self.assertRaises(ValueError):
            _video_sdr_metadata(av.VideoFrame(2, 2, 'rgba64le'))

    async def test_decoded_frame_missing_colour_fields_inherits_only_safe_stream(self):
        import av
        decoded = av.VideoFrame(2, 2, 'yuv420p')
        legacy_frame = types.SimpleNamespace(format=decoded.format, side_data=(), colorspace=1)
        self.assertEqual(_video_sdr_metadata(legacy_frame, (1, 1, 1)), (1, 1, 1))
        nullable_frame = types.SimpleNamespace(format=decoded.format, side_data=(),
            color_trc=None, color_primaries=None, colorspace=None)
        self.assertEqual(_video_sdr_metadata(nullable_frame, (1, 1, 1)), (1, 1, 1))
        for unsafe in ((16, 9, 9), (18, 9, 9), (1, 9, 1)):
            with self.assertRaises(ValueError):
                _video_sdr_metadata(legacy_frame, unsafe)

    async def test_side_data_objects_and_type_key_mappings_validate_every_payload(self):
        import av
        from av.sidedata.sidedata import Type
        class Payload:
            def __init__(self, kind, encoded):
                self.type, self.encoded = kind, encoded
            def __bytes__(self):
                return self.encoded
        fmt = av.VideoFrame(2, 2, 'yuv420p').format
        safe = Payload(Type.SEI_UNREGISTERED, b'\0' * 16 + b'x264 - core 164 fixture')
        for sides in ([safe], {Type.SEI_UNREGISTERED: safe}):
            frame = types.SimpleNamespace(format=fmt, side_data=sides, color_trc=1, color_primaries=1, colorspace=1)
            self.assertEqual(_video_sdr_metadata(frame), (1, 1, 1))
        for kind in (Type.ICC_PROFILE, Type.MASTERING_DISPLAY_METADATA, Type.DYNAMIC_HDR_PLUS):
            unsafe = Payload(kind, b'unsupported colour metadata')
            for sides in ([safe, unsafe], {Type.SEI_UNREGISTERED: safe, kind: unsafe}):
                frame = types.SimpleNamespace(format=fmt, side_data=sides, color_trc=1, color_primaries=1, colorspace=1)
                with self.assertRaises(ValueError):
                    _video_sdr_metadata(frame)
        unknown_sei = Payload(Type.SEI_UNREGISTERED, b'\0' * 16 + b'not the approved encoder identification')
        for sides in ([unknown_sei], {Type.SEI_UNREGISTERED: unknown_sei}, {Type.SEI_UNREGISTERED: Type.SEI_UNREGISTERED}):
            frame = types.SimpleNamespace(format=fmt, side_data=sides, color_trc=1, color_primaries=1, colorspace=1)
            with self.assertRaises(ValueError):
                _video_sdr_metadata(frame)

    @unittest.skipUnless(importlib.util.find_spec('OpenImageIO'), 'OpenImageIO required for actual EXR fidelity')
    async def test_actual_float_and_half_exr_original_containers_retained_byte_for_byte(self):
        session, headers = await self.create()
        for storage in ('float32', 'half'):
            with self.subTest(storage=storage):
                path = self.outputs / (storage + '.exr')
                float_io.write_exr(path, self.payload[0], colour=self.manifest['colour'], storage=storage)
                original_bytes = path.read_bytes()
                response = await self.client.post(self.route(session, '/result'), headers=headers, json={
                    "kind": "image", "master": {"filename": path.name, "type": "output"}})
                self.assertEqual(response.status, 200, await response.text())
                metadata, retained = self.received_originals[-1]
                self.assertEqual(retained, original_bytes)
                self.assertEqual(metadata['storage'], storage)
                self.assertEqual(metadata['mediaType'], 'image/x-exr')
                self.assertEqual(metadata['sha256'], hashlib.sha256(original_bytes).hexdigest())
                decoded, _ = float_io.read_exr(path)
                converted, _ = float_io.load_transfer(self.outputs, self.received[-1]['master']['subfolder'] + '/manifest.json')
                self.assertEqual(converted[0].tobytes(), decoded.tobytes())

    @unittest.skipUnless(importlib.util.find_spec('OpenImageIO'), 'OpenImageIO required for actual EXR sequence fidelity')
    async def test_actual_explicit_exr_sequence_keeps_all_originals_in_order(self):
        refs, expected = [], []
        for index, storage in enumerate(('half', 'float32')):
            path = self.outputs / f'frame{index}.exr'
            float_io.write_exr(path, self.payload[0] + np.float32(index), colour=self.manifest['colour'], storage=storage)
            refs.append({"filename": path.name, "type": "output"})
            expected.append(path.read_bytes())
        session, headers = await self.create()
        response = await self.client.post(self.route(session, '/result'), headers=headers, json={
            "kind": "hdr_sequence", "master": refs, "fps": 25, "frameCount": 2})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual([encoded for _, encoded in self.received_originals], expected)
        self.assertEqual([entry['index'] for entry in self.received[-1]['originals']], [0, 1])

    async def test_original_download_scope_and_post_submission_revocation(self):
        from PIL import Image
        Image.new('RGBA', (1, 1), (128, 64, 32, 255)).save(self.outputs / 'master.png')
        session, headers = await self.create()
        response = await self.client.get(self.route(session, '/original-files/0'), headers=headers)
        self.assertEqual(response.status, 403)
        response = await self.client.post(self.route(session, '/result'), headers=headers, json={
            "kind": "image", "master": {"filename": "master.png", "type": "output"}})
        self.assertEqual(response.status, 200)
        response = await self.client.get(self.route(session, '/original-files/0'), headers={DOWNLOAD_HEADER: self.received[-1]['downloadCapability']})
        self.assertEqual(response.status, 403)

    async def test_real_native_sdr_upload_api_receives_generated_lossless_media(self):
        from PIL import Image
        import io
        received = []
        # Add a tiny actual native API surface in another loopback app. The
        # importer must call it and return its real asset record, not invent one.
        async def native_upload(request):
            part = await (await request.multipart()).next()
            encoded = await part.read()
            with Image.open(io.BytesIO(encoded)) as image:
                received.append(np.array(image))
            return web.json_response({"id": 'e' * 32, "kind": "asset", "asset_kind": "image", "file": "real-native-upload.png"})
        app = web.Application()
        app.router.add_post('/zura/studio/upload', native_upload)
        native = TestServer(app, host='127.0.0.1')
        await native.start_server()
        try:
            samples = np.array([[[[64, 128, 255, 128]]]], dtype=np.float32) / np.float32(255)
            relative, manifest = float_io.write_transfer(self.inputs, 'ComfyLink/' + 'f' * 32, samples,
                colour={"encoding": "unknown", "sceneLinear": False}, frame_rate={"numerator": 24, "denominator": 1}, source_bit_depth=32 if getattr(self,'derived_processing',False) else 8)
            if getattr(self,'derived_processing',False):
                float_io._exclusive_write(self.inputs/Path(relative).parent/'processing-input.json',float_io.canonical_manifest_bytes(processing_authority(manifest)))
            session = types.SimpleNamespace(id='f' * 32, origin=str(native.make_url('/')).rstrip('/'), closed=False, expires=time.time() + 600)
            self.service.sessions[session.id] = session
            result = await self.service.native_import(session, self.inputs / Path(relative).parent, manifest)
            self.assertEqual(result['studioAsset']['file'], 'real-native-upload.png')
            self.assertEqual(received[0].tolist(), [[ [64, 128, 255, 128] ]])
            self.assertTrue((self.inputs / result['stills']['first']['file']).is_file())
        finally:
            await native.close()

    async def test_real_derived_float_source_image_upload(self):
        self.derived_processing=True
        await self.test_real_native_sdr_upload_api_receives_generated_lossless_media()

    async def test_processing_keeps_original_float_source_identity(self):
        from comfylink.studio_processing import validate_processing_input, encode_sdr8
        authority=processing_authority(self.manifest)
        self.source_override={'manifest':self.manifest,'processingInput':authority}
        session,headers=await self.create()
        response=await self.client.post(self.route(session,'/source'),json={},headers=headers)
        self.assertEqual(response.status,200)
        source=await response.json()
        self.assertEqual(source['precision']['sourceBitDepth'],32)
        self.assertEqual(source['manifest'],self.manifest)
        self.assertEqual(source['processingInput']['precision'],{'sampleType':'uint8','sourceBitDepth':8})
        self.assertEqual(source['processingInput']['sourceManifestSha256'],authority['sourceManifestSha256'])
        validate_processing_input(authority,self.manifest)
        for values in ([float('nan'),.2,.3,1],[.1,.2,.3,float('nan')],[.1,.2,.3,1.1]):
            with self.assertRaises(ValueError):
                encode_sdr8(np.array(values,dtype=np.float32),derived=True)
        original=np.array([-.25,2.,.5,.25],dtype=np.float32)
        before=original.copy()
        self.assertEqual(encode_sdr8(original,derived=True).tolist(),[0,255,128,64])
        self.assertTrue(np.array_equal(original,before),'Clipping applies only to the derived model view')
        encoded=encode_sdr8(np.array([.123,.456,.789,1],dtype=np.float32),derived=True)
        self.assertEqual(encoded.tolist(),[31,116,201,255])
        tampered=copy.deepcopy(authority);tampered['sourceColour']['sceneLinear']=True
        with self.assertRaises(ValueError):validate_processing_input(tampered,self.manifest)
        tampered=copy.deepcopy(authority);tampered['sourceManifestSha256']='0'*64
        with self.assertRaises(ValueError):validate_processing_input(tampered,self.manifest)

    async def test_bounded_and_duplicate_json_rejected(self):
        response = await self.client.post(PREFIX + '/sessions', data=b'{' + b' ' * 5000 + b'}')
        self.assertEqual(response.status, 413)
        response = await self.client.post(PREFIX + '/sessions', data=b'{"broker":1,"broker":2}')
        self.assertEqual(response.status, 400)

    async def test_real_multiframe_sdr_native_upload_keeps_frames_rate_and_endpoints(self):
        import av
        from fractions import Fraction
        from PIL import Image
        expected=[]
        for index in range(3):
            rgba=np.full((2,2,4),(32+index,64+index,128+index,255),dtype=np.uint8)
            rgba[0,0]=(17+index,45+index,200-index,0)
            rgba[0,1]=(80+index,90+index,100+index,128)
            expected.append(rgba)
        native_root=self.inputs/'native-video-upload';native_root.mkdir()
        native_file=native_root/'reference.mkv'
        inspected={}
        async def native_upload(request):
            self.assertEqual(request.query.get('kind'),'video')
            part=await (await request.multipart()).next()
            self.assertEqual(part.filename,'source.mkv')
            with native_file.open('xb') as destination:
                while chunk:=await part.read_chunk():destination.write(chunk)
            with av.open(str(native_file)) as container:
                stream=container.streams.video[0]
                self.assertEqual(stream.codec_context.name,'ffv1')
                self.assertEqual(stream.average_rate,Fraction(25,1))
                decoded=list(container.decode(video=0))
                self.assertEqual(len(decoded),len(expected))
                for index,frame in enumerate(decoded):
                    self.assertEqual(frame.to_ndarray(format='rgba').tobytes(),expected[index].tobytes())
                    self.assertEqual(Fraction(frame.pts)*frame.time_base,Fraction(index,25))
                inspected.update(path=str(native_file),kind='video',frames=len(decoded),fps=float(stream.average_rate),width=stream.width,height=stream.height)
            return web.json_response({'id':'e'*32,'kind':'asset','asset_kind':'video','count':len(expected),
                'file':native_file.relative_to(self.inputs).as_posix(),'duration':len(expected)/25,'width':2,'height':2})
        async def native_info(request):
            self.assertTrue(native_file.is_file())
            return web.json_response(inspected)
        app=web.Application()
        app.router.add_post('/zura/studio/upload',native_upload)
        app.router.add_post('/zura/studio/assets/'+'e'*32+'/ripple',native_info)
        native=TestServer(app,host='127.0.0.1');await native.start_server()
        try:
            identity='f'*32
            source=(frame.astype(np.float32)/np.float32(255) for frame in expected)
            relative,manifest=float_io.write_transfer_frames(self.inputs,'ComfyLink/'+identity,source,
                colour={'encoding':'unknown','sceneLinear':False},frame_rate={'numerator':25,'denominator':1},source_bit_depth=32 if getattr(self,'derived_processing',False) else 8,expected_count=len(expected))
            if getattr(self,'derived_processing',False):
                float_io._exclusive_write(self.inputs/Path(relative).parent/'processing-input.json',float_io.canonical_manifest_bytes(processing_authority(manifest)))
            session=types.SimpleNamespace(id=identity,origin=str(native.make_url('/')).rstrip('/'),closed=False,expires=time.time()+600)
            self.service.sessions[identity]=session
            with patch.object(float_io,'load_transfer',side_effect=AssertionError('whole batch forbidden')),patch.object(np,'stack',side_effect=AssertionError('whole batch forbidden')):
                result=await self.service.native_import(session,self.inputs/Path(relative).parent,manifest)
            self.assertEqual(result['studioAsset']['asset_kind'],'video')
            self.assertEqual(result['studioAsset']['count'],3)
            self.assertEqual(result['mediaInfo']['frames'],3)
            self.assertEqual(result['mediaInfo']['fps'],25)
            self.assertEqual((result['mediaInfo']['width'],result['mediaInfo']['height']),(2,2))
            for key,index in (('first',0),('last',2)):
                path=self.inputs/result['stills'][key]['file']
                with Image.open(path) as still:
                    self.assertEqual(still.mode,'RGBA')
                    self.assertEqual(np.array(still).tobytes(),expected[index].tobytes())
        finally:await native.close()

    async def test_real_derived_float_source_multiframe_upload(self):
        self.derived_processing=True
        await self.test_real_multiframe_sdr_native_upload_keeps_frames_rate_and_endpoints()


if __name__ == '__main__':
    unittest.main()
