"""Long HDR submission uses validated assets and safe output references."""
import asyncio
import importlib
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from pathlib import Path
import v2_bootstrap

for name,path in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/path)];sys.modules[name]=module
service=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_long_service')

class Store:
    def load(self,identity):
        if identity=='video':return {'asset_kind':'video','id':identity}
        if identity=='sequence':return {'asset_kind':'hdr_sequence','id':identity}
        raise ValueError('Unknown asset')

class Job:
    def __init__(self,path):self.path=path;self.state='ready';self.release=asyncio.Event();self.entered=asyncio.Event()
    def snapshot(self):return {'state':self.state,'completed':1,'total':1,'active_prompt_id':None,
        'error':None,'result':{'files':[str(self.path)]} if self.state=='complete' else None}
    async def run(self):self.state='rendering';self.entered.set();await self.release.wait();self.state='complete'
    async def cancel(self):self.state='cancelled';self.release.set();return True

class HDRLongServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_setup_stops_before_creating_or_queuing_a_job(self):
        with tempfile.TemporaryDirectory() as root:
            calls=[]
            def missing(mode,output):
                calls.append((mode,output))
                raise ValueError('Missing nodes: LTXVAddGuide')
            def create(*args,**kwargs):raise AssertionError('Must not create a job')
            client=service.HDRLongService(None,Store(),lambda asset:'verified',root,create_native=create,check_setup=missing)
            with self.assertRaisesRegex(ValueError,'LTXVAddGuide'):
                await client.start({'mode':'native','source_id':'video','output':'hlg_video','request_id':'f'*32})
            self.assertEqual(calls,[('native','hlg_video')]);self.assertFalse(client.jobs.tasks);self.assertFalse(client._requests)

    async def test_setup_message_names_missing_files_and_nodes(self):
        readiness=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_readiness')
        nodes=types.ModuleType('nodes');nodes.NODE_CLASS_MAPPINGS={}
        import folder_paths
        with patch.dict(sys.modules,{'nodes':nodes}),patch.object(folder_paths,'get_full_path',return_value=None,create=True), \
             patch.object(readiness,'readiness',return_value={'files':[{'filename':'model.safetensors','ready':False}],
                                                             'missingNodes':['LTXVAddGuide']}):
            with self.assertRaisesRegex(ValueError,'model.safetensors.*LTXVAddGuide.*model setup'):
                service.check_long_setup('native','hlg_video')
    async def test_approved_preview_is_available_and_can_be_disabled(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(service.preview_enabled())
        with patch.dict(os.environ, {'ZURA_HDR_LONG_PREVIEW': 'true'}, clear=True):
            self.assertFalse(service.preview_enabled())
        with patch.dict(os.environ, {'ZURA_HDR_LONG_PREVIEW': '1'}, clear=True):
            self.assertTrue(service.preview_enabled())
        with patch.dict(os.environ, {'ZURA_HDR_LONG_PREVIEW': '0'}, clear=True):
            self.assertFalse(service.preview_enabled())

    async def test_checked_asset_single_job_and_relative_output(self):
        with tempfile.TemporaryDirectory() as root:
            output=Path(root)/'genj'/'hdr'/'result.zip';output.parent.mkdir(parents=True);output.write_bytes(b'x')
            created=[]
            def create(server,asset,body,check,out,**kwargs):
                self.assertEqual(check(asset),'verified');self.assertEqual(kwargs['anchor_strength'],.75)
                self.assertEqual(kwargs['max_chunk_frames'],121)
                job=Job(output);created.append(job);return job,{'id':'a'*32,'frames':130}
            client=service.HDRLongService(None,Store(),lambda asset:'verified',root,create_sdr=create,check_setup=lambda *_:None)
            result=await client.start({'mode':'sdr','source_id':'video'});self.assertEqual(result['id'],'a'*32)
            await created[0].entered.wait()
            with self.assertRaisesRegex(ValueError,'already running'):await client.start({'mode':'sdr','source_id':'video'})
            created[0].release.set();await client.jobs.tasks['a'*32]
            self.assertEqual(client.status('a'*32)['result']['files'],[{'filename':'result.zip','subfolder':'genj/hdr','type':'output'}])

    async def test_unknown_and_mismatched_assets_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            client=service.HDRLongService(None,Store(),lambda asset:'verified',root)
            with self.assertRaisesRegex(ValueError,'source type'):await client.start({'mode':'native','source_kind':'sequence','source_id':'video'})
            with self.assertRaisesRegex(ValueError,'not restarted'):client.status('f'*32)
            with self.assertRaisesRegex(ValueError,'section setting'):await client.start({'mode':'native','source_id':'video','section_frames':26})
            with self.assertRaisesRegex(ValueError,'section setting'):await client.start({'mode':'sdr','source_id':'video','section_frames':25})

    async def test_selected_output_stays_inside_output_root(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'zura'/'take.mp4';path.parent.mkdir();path.write_bytes(b'video')
            client=service.HDRLongService(None,Store(),lambda asset:'verified',root)
            asset,check=client._asset({'source_kind':'output','output_ref':{'type':'output','subfolder':'zura','filename':'take.mp4'}})
            self.assertEqual(asset['asset_kind'],'video');self.assertEqual(check(asset),path.resolve())
            with self.assertRaises(ValueError):client._asset({'source_kind':'output','output_ref':{'type':'output','subfolder':'..','filename':'outside.mp4'}})

    async def test_shorter_native_sections_reach_job_builder(self):
        with tempfile.TemporaryDirectory() as root:
            created=[]
            def create(server,asset,body,check,out,**kwargs):
                self.assertEqual(kwargs['max_chunk_frames'],25)
                job=Job(Path(root)/'unused');created.append(job)
                return job,{'id':'e'*32,'frames':129}
            client=service.HDRLongService(None,Store(),lambda asset:'verified',root,create_native=create,check_setup=lambda *_:None)
            await client.start({'mode':'native','source_id':'video','section_frames':25})
            await created[0].entered.wait();created[0].release.set();await client.jobs.tasks['e'*32]

    async def test_http_start_status_and_cancellation(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        with tempfile.TemporaryDirectory() as root:
            created=[]
            def create(server,asset,body,check,out,**kwargs):
                job=Job(Path(root)/'unused');created.append(job)
                return job,{'id':'b'*32,'frames':130}
            client_service=service.HDRLongService(None,Store(),lambda asset:'verified',root,create_sdr=create,check_setup=lambda *_:None)
            routes=web.RouteTableDef()
            def response(fn):
                async def wrapped(request):
                    try:return await fn(request)
                    except ValueError as error:return web.json_response({'error':str(error)},status=400)
                return wrapped
            service.register(routes,response,client_service)
            app=web.Application();app.add_routes(routes)
            async with TestClient(TestServer(app)) as client:
                body={'mode':'sdr','source_id':'video','request_id':'d'*32}
                response1=await client.post('/zura/studio/hdr/jobs',json=body)
                self.assertEqual(response1.status,200);self.assertEqual((await response1.json())['id'],'b'*32)
                await created[0].entered.wait()
                recovered=await client.get('/zura/studio/hdr/requests/'+'d'*32)
                self.assertEqual((await recovered.json())['id'],'b'*32)
                duplicate=await client.post('/zura/studio/hdr/jobs',json=body)
                self.assertEqual((await duplicate.json())['id'],'b'*32);self.assertEqual(len(created),1)
                conflict=await client.post('/zura/studio/hdr/jobs',json={**body,'source_id':'different'})
                self.assertEqual(conflict.status,400)
                status=await client.get('/zura/studio/hdr/jobs/'+'b'*32)
                self.assertEqual((await status.json())['state'],'rendering')
                cancel=await client.post('/zura/studio/hdr/jobs/'+'b'*32+'/cancel')
                self.assertEqual((await cancel.json())['state'],'cancelled')
                await client_service.jobs.tasks['b'*32]
                missing=await client.get('/zura/studio/hdr/jobs/'+'c'*32)
                self.assertEqual(missing.status,400);self.assertIn('not restarted',(await missing.json())['error'])

if __name__=='__main__':unittest.main()
