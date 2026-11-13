"""Both public namespaces share the real handlers and unchanged read guards."""
import ast
import asyncio
import importlib
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlparse

import scipy.ndimage  # Keep extension modules loaded before fixture patch.dict.
import numpy.fft
import av
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

import test_artist_studio as fixture

studio_module=fixture.studio
modules={name:importlib.import_module(studio_module.__package__+'.'+name)
         for name in ('display_view_routes','model_view','media_import','hdri_routes')}
PAIRS=[('GET','display/config'),('POST','display/frame'),('POST','display/info'),
       ('POST','model-view'),('POST','media-import/upload'),('POST','media-import/describe'),
       ('POST','media-import/prepare'),('POST','hdri/import'),('POST','hdri/preview'),
       ('POST','hdri/export'),('POST','hdri/scene')]


class FakeContent:
    def __init__(self,body):self.body=body
    async def iter_chunked(self,size):
        for start in range(0,len(self.body),size):yield self.body[start:start+size]


class Transport:
    closing=False
    def is_closing(self):return self.closing


class HugeChunk:
    def __init__(self,size):self.size=size
    def __len__(self):return self.size


class HelperAliasTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.roots={key:self.base/key for key in ('input','output','temp')}
        for root in self.roots.values():root.mkdir()
        self.source=self.roots['output']/'source.png'
        Image.new('RGB',(2,2),(120,80,40)).save(self.source)
        self.outside=self.base/'outside.exr';self.outside.write_bytes(b'never read this fixture')
        self.store=types.SimpleNamespace(load=Mock(side_effect=ValueError('Unknown fixture asset')),save=Mock())
        self.studio=types.SimpleNamespace(store=self.store,start_watcher=Mock())
        self.outputs=types.SimpleNamespace(start=Mock(),schedule_export=Mock())
        # Compile the production nested wrapper unchanged, replacing only its
        # watcher/export dependencies. Every tested alias keeps that wrapper.
        tree=ast.parse(Path(studio_module.__file__).read_text(encoding='utf-8'))
        register=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='register')
        functions=[n for n in register.body if isinstance(n,ast.FunctionDef) and n.name in ('same_origin','response')]
        namespace={'web':web,'urlparse':urlparse,'studio':self.studio,'outputs':self.outputs,'json':json,'av':av}
        exec(compile(ast.fix_missing_locations(ast.Module(body=functions,type_ignores=[])),'production-response','exec'),namespace)
        self.response=namespace['response']
        self.routes=web.RouteTableDef()
        for module in modules.values():module.register(self.studio,self.routes,namespace['response'],lambda value:value)
        self.handlers={(route.method,route.path):route.handler for route in self.routes}
        self.patchers=[]
        import folder_paths
        for kind,root in self.roots.items():
            patcher=patch.object(folder_paths,'get_'+kind+'_directory',return_value=str(root));patcher.start();self.patchers.append(patcher)

    def tearDown(self):
        for patcher in reversed(self.patchers):patcher.stop()
        self.temp.cleanup()

    def test_registry_pairs_share_one_wrapped_handler_and_collisions_refuse(self):
        expected={(method,'/'+prefix+'/studio/'+suffix) for method,suffix in PAIRS for prefix in ('zura','genj')}
        self.assertEqual(set(self.handlers),expected,'Only the requested public Studio helpers are aliased')
        for method,suffix in PAIRS:
            self.assertIs(self.handlers[(method,'/zura/studio/'+suffix)],self.handlers[(method,'/genj/studio/'+suffix)])
        async def existing(_request):return web.Response(text='existing')
        for prefix in ('zura','genj'):
            routes=web.RouteTableDef();routes.post('/'+prefix+'/studio/model-view')(existing)
            with self.assertRaisesRegex(RuntimeError,'already registered'):
                modules['model_view'].register(self.studio,routes,self.response,lambda value:value)
            self.assertEqual(len(routes),1);self.assertIs(next(iter(routes)).handler,existing)
        routes=web.RouteTableDef();routes.head('/genj/studio/display/config')(existing)
        with self.assertRaisesRegex(RuntimeError,'already registered'):
            modules['display_view_routes'].register(self.studio,routes,self.response,lambda value:value)
        self.assertEqual(len(routes),1)
        routes=web.RouteTableDef();routes.route('*','/genj/studio/model-view')(existing)
        with self.assertRaisesRegex(RuntimeError,'already registered'):
            modules['model_view'].register(self.studio,routes,self.response,lambda value:value)
        self.assertEqual(len(routes),1)
        # A different method is not a collision and remains available.
        routes=web.RouteTableDef();routes.get('/genj/studio/model-view')(existing)
        modules['model_view'].register(self.studio,routes,self.response,lambda value:value)
        self.assertEqual(len(routes),3)
        routes=web.RouteTableDef();routes.static('/fixture-static',self.roots['output'])
        modules['model_view'].register(self.studio,routes,self.response,lambda value:value)
        self.assertEqual(len(routes),3)

    async def test_both_namespaces_reject_foreign_origin_before_watchers_or_reads(self):
        app=web.Application();app.add_routes(self.routes)
        async with TestClient(TestServer(app)) as client:
            for method,suffix in PAIRS:
                for prefix in ('zura','genj'):
                    with self.subTest(path=prefix+'/'+suffix):
                        response=await client.request(method,'/'+prefix+'/studio/'+suffix,
                            headers={'Origin':'https://elsewhere.example'},data=b'{')
                        self.assertEqual(response.status,403)
                        if method=='GET':
                            head=await client.head('/'+prefix+'/studio/'+suffix,headers={'Origin':'https://elsewhere.example'})
                            self.assertEqual(head.status,403)
        self.studio.start_watcher.assert_not_called();self.outputs.start.assert_not_called()
        self.store.load.assert_not_called();self.store.save.assert_not_called()

    async def test_read_and_json_limits_are_the_same_and_original_is_unchanged(self):
        before=self.source.read_bytes();app=web.Application();app.add_routes(self.routes)
        forbidden={'source':{'file':{'type':'output','filename':'../outside.exr'}}}
        with patch.object(modules['hdri_routes'].hdri,'read_environment',side_effect=AssertionError('Escaped original was read')):
            async with TestClient(TestServer(app)) as client:
                for prefix in ('zura','genj'):
                    path='/'+prefix+'/studio/'
                    good=await client.post(path+'display/info',json={'source':{'file':{'type':'output','filename':'source.png'}}})
                    self.assertEqual(good.status,200);self.assertEqual((await good.json())['frame_count'],1)
                    for suffix,size,status in [('display/frame',17000,400),('display/info',5000,400),('model-view',17000,400),('media-import/describe',17000,413),('media-import/prepare',17000,413)]:
                        oversized=await client.post(path+suffix,data=b' '*size);self.assertEqual(oversized.status,status,suffix)
                    for suffix in ('display/info','model-view'):
                        rejected=await client.post(path+suffix,json=forbidden);self.assertEqual(rejected.status,400,suffix)
                    for suffix in ('hdri/preview','hdri/export'):
                        rejected=await client.post(path+suffix,json={'file':{'type':'output','filename':'../outside.exr'}})
                        self.assertEqual(rejected.status,400,suffix)
        self.assertEqual(self.source.read_bytes(),before);self.store.save.assert_not_called()

    async def test_multipart_limits_reject_before_writing_the_oversized_chunk(self):
        for suffix,limit in [('hdri/import',500*1024*1024),('media-import/upload',32*1024**3)]:
            for prefix in ('zura','genj'):
                class Part:
                    filename='fixture.exr'
                    async def read_chunk(self,*_args):return HugeChunk(limit+1)
                class Reader:
                    async def next(self):return Part()
                async def multipart():return Reader()
                request=types.SimpleNamespace(headers={},host='local',multipart=multipart,transport=Transport())
                response=await self.handlers[('POST','/'+prefix+'/studio/'+suffix)](request)
                self.assertEqual(response.status,400)
        self.assertEqual(list(self.roots['input'].rglob('source.exr')),[])
        self.assertEqual(list(self.roots['input'].rglob('original.exr')),[])
        self.store.save.assert_not_called()

    async def test_disconnect_cancels_preparation_before_any_asset_publication(self):
        for prefix in ('zura','genj'):
            started=threading.Event();cancelled=threading.Event()
            def prepare(_body,_store,_check,_roots,cancel):
                started.set()
                if not cancel.wait(2):raise AssertionError('Disconnect did not set cancellation')
                cancelled.set();return {'mustNotPublish':True}
            transport=Transport();body=b'{"asset_id":"fixture"}'
            request=types.SimpleNamespace(headers={},host='local',content=FakeContent(body),content_length=len(body),transport=transport)
            with patch.object(modules['media_import'],'prepare_import',side_effect=prepare):
                task=asyncio.create_task(self.handlers[('POST','/'+prefix+'/studio/media-import/prepare')](request))
                await asyncio.to_thread(started.wait,1)
                transport.closing=True
                response=await asyncio.wait_for(task,2)
                self.assertEqual(response.status,400);self.assertTrue(cancelled.is_set())
            self.store.save.assert_not_called()


if __name__=='__main__':unittest.main()
