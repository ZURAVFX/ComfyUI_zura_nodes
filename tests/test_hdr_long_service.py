"""Long HDR submission uses validated assets and safe output references."""
import asyncio
import importlib
import sys
import tempfile
import types
import unittest
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
    async def test_checked_asset_single_job_and_relative_output(self):
        with tempfile.TemporaryDirectory() as root:
            output=Path(root)/'genj'/'hdr'/'result.zip';output.parent.mkdir(parents=True);output.write_bytes(b'x')
            created=[]
            def create(server,asset,body,check,out,**kwargs):
                self.assertEqual(check(asset),'verified');self.assertEqual(kwargs['anchor_strength'],.75)
                job=Job(output);created.append(job);return job,{'id':'a'*32,'frames':130}
            client=service.HDRLongService(None,Store(),lambda asset:'verified',root,create_sdr=create)
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

    async def test_http_start_status_and_cancellation(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        with tempfile.TemporaryDirectory() as root:
            created=[]
            def create(server,asset,body,check,out,**kwargs):
                job=Job(Path(root)/'unused');created.append(job)
                return job,{'id':'b'*32,'frames':130}
            client_service=service.HDRLongService(None,Store(),lambda asset:'verified',root,create_sdr=create)
            routes=web.RouteTableDef()
            def response(fn):
                async def wrapped(request):
                    try:return await fn(request)
                    except ValueError as error:return web.json_response({'error':str(error)},status=400)
                return wrapped
            service.register(routes,response,client_service)
            app=web.Application();app.add_routes(routes)
            async with TestClient(TestServer(app)) as client:
                response1=await client.post('/zura/studio/hdr/jobs',json={'mode':'sdr','source_id':'video'})
                self.assertEqual(response1.status,200);self.assertEqual((await response1.json())['id'],'b'*32)
                await created[0].entered.wait()
                status=await client.get('/zura/studio/hdr/jobs/'+'b'*32)
                self.assertEqual((await status.json())['state'],'rendering')
                cancel=await client.post('/zura/studio/hdr/jobs/'+'b'*32+'/cancel')
                self.assertEqual((await cancel.json())['state'],'cancelled')
                await client_service.jobs.tasks['b'*32]
                missing=await client.get('/zura/studio/hdr/jobs/'+'c'*32)
                self.assertEqual(missing.status,400);self.assertIn('not restarted',(await missing.json())['error'])

if __name__=='__main__':unittest.main()
