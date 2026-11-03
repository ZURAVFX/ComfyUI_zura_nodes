"""Real local HTTP requests and tiny fixture downloads; no publisher network."""
import asyncio
import hashlib
import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import numpy
import torch
from PIL import Image, ImageOps

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


class InstallRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        folders = types.ModuleType('folder_paths')
        folders.models_dir = str(self.root/'models')
        folders.get_user_directory = lambda: str(self.root/'user')
        folders.folder_names_and_paths = {'vae': ([str(self.root/'models/vae')], {'.safetensors'})}
        folders.supported_pt_extensions = {'.safetensors'}
        folders.filename_list_cache = {}
        folders.get_folder_paths = lambda name: folders.folder_names_and_paths[name][0]
        folders.get_filename_list = lambda name: [str(p.relative_to(Path(r))) for r in folders.get_folder_paths(name) if Path(r).exists() for p in Path(r).rglob('*.safetensors')]
        def add(name, path, is_default=False):
            roots = folders.folder_names_and_paths.setdefault(name, ([], set()))[0]
            if path in roots:roots.remove(path)
            roots.insert(0 if is_default else len(roots),path)
        folders.add_model_folder_path = add
        package = types.ModuleType('install_fixture');package.__path__=[str(Path(__file__).resolve().parents[1])]
        subpackage = types.ModuleType('install_fixture.artist_studio');subpackage.__path__=[str(Path(package.__path__[0])/'artist_studio')]
        self.modules = patch.dict(sys.modules, {'folder_paths':folders,'install_fixture':package,'install_fixture.artist_studio':subpackage})
        self.modules.start()
        self.downloads=importlib.import_module('install_fixture.artist_studio.model_downloads')
        self.data=b'tiny model fixture for HTTP tests'
        item={'folder':'vae','filename':'needed.safetensors','repo':'test/models','revision':'a'*40,'remote_path':'needed.safetensors','size_bytes':len(self.data),'sha256':hashlib.sha256(self.data).hexdigest()}
        self.catalogue=patch.dict(self.downloads.CATALOG,{'test':{'name':'Fixture','files':[item],'gated':False,'license_url':''}},clear=True);self.catalogue.start()
        routes=web.RouteTableDef()
        def response(handler):
            async def call(request):
                try:return await handler(request)
                except ValueError as error:return web.json_response({'error':str(error)},status=400)
            return call
        self.downloads.register(routes,response)
        app=web.Application();app.add_routes(routes)
        self.client=TestClient(TestServer(app));await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close();self.catalogue.stop();self.modules.stop();self.tmp.cleanup()
        for name in list(sys.modules):
            if name.startswith('install_fixture'):sys.modules.pop(name,None)

    async def test_storage_and_batch_install_refresh_over_real_http(self):
        external=self.root/'shared';external.mkdir()
        response=await self.client.post('/zura/studio/model-folders',json={'path':str(external)})
        self.assertEqual(response.status,200)
        self.assertEqual((await response.json())['external'],str(external.resolve()))
        first=self.root/'first';first.mkdir()
        response=await self.client.post('/zura/studio/model-folders',json={'folders':[str(first),str(external)],'download_to':str(external)})
        self.assertEqual(response.status,200)
        self.assertEqual((await response.json())['folders'],[str(first),str(external)])
        class Response:
            status_code=200
            def __enter__(inner):return inner
            def __exit__(inner,*args):pass
            def raise_for_status(inner):pass
            def iter_content(inner,chunk_size):yield self.data
        with patch('requests.get',return_value=Response()) as fetch:
            response=await self.client.get('/zura/studio/model-downloads')
            self.assertEqual((await response.json())['models'][0]['remaining_bytes'],len(self.data));fetch.assert_not_called()
            response=await self.client.post('/zura/studio/model-downloads',json={'model_ids':['test'],'file_keys':['vae/needed.safetensors']})
            self.assertEqual(response.status,200);identity=(await response.json())['id']
            for _ in range(300):
                status=await (await self.client.get('/zura/studio/model-downloads/'+identity)).json()
                if status['phase'] in ('done','failed'):break
                await asyncio.sleep(.01)
            self.assertEqual(status['phase'],'done',status)
            self.assertEqual((external/'vae/needed.safetensors').read_bytes(),self.data)
            self.assertEqual(fetch.call_count,1)
            catalogue=await (await self.client.get('/genj/studio/model-downloads')).json()
            self.assertEqual(catalogue['models'][0]['remaining_bytes'],0)
        self.assertTrue((self.root/'user/zura/model-folders.json').exists())

    async def test_cross_origin_storage_changes_and_unlisted_files_are_rejected(self):
        response=await self.client.post('/zura/studio/model-folders',json={'path':str(self.root)},headers={'Origin':'https://unrelated.example'})
        self.assertEqual(response.status,403)
        response=await self.client.post('/zura/studio/model-downloads',json={'model_ids':['test'],'file_keys':['vae/not-allowlisted.safetensors']})
        self.assertEqual(response.status,400)
        response=await self.client.get('/genj/studio/model-folders')
        self.assertEqual(response.status,200)


if __name__=='__main__':unittest.main()
