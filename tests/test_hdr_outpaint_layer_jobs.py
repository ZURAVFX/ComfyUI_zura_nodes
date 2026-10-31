"""Layer exports are isolated, explicit, cancellable CPU work on a final take."""
import asyncio
import importlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_artist_studio

module=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_layer_jobs')


class LayerJobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.identity='a'*32
        self.job={'id':self.identity,'kind':'render','state':'complete','hdr_render':True,
                  'source':{'id':'source','sha':'verified'},'selection':{'frames':9},
                  'hdr_files':{'exr':{'type':'output','subfolder':'genj/hdr','filename':'hdr_outpaint_'+'b'*32+'.zip'}}}
        self.manager=module.HDRLayerExports(SimpleNamespace(state=lambda identity:self.job))
        self.archive=self.root/'genj/hdr'/self.job['hdr_files']['exr']['filename']
        self.archive.parent.mkdir(parents=True);self.archive.touch()
        self.source=self.root/'source.mp4';self.source.touch()
        self.started=threading.Event();self.release=threading.Event();self.calls=0

    async def asyncTearDown(self):
        self.release.set()
        for record in self.manager.exports.values():
            if record.get('task'):await record['task']
        self.temp.cleanup()

    def fake_export(self,archive,source,selection,root,prefix,*,cancelled,progress):
        self.calls+=1;self.started.set();progress(1,9)
        if not self.release.wait(5):raise RuntimeError('Test release timed out')
        if cancelled.is_set():raise RuntimeError('Export stopped')
        path=self.archive.parent/(prefix+'_layers.zip');path.touch();progress(9,9)
        return path

    def patches(self,function=None):
        from contextlib import ExitStack
        stack=ExitStack()
        stack.enter_context(patch('folder_paths.get_output_directory',return_value=str(self.root)))
        stack.enter_context(patch('ComfyUI_zura_nodes.artist_studio.studio.check_asset',return_value=str(self.source)))
        stack.enter_context(patch('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_layers.export_hdr_outpaint_layers',side_effect=function or self.fake_export))
        return stack

    async def wait_started(self):
        for _ in range(100):
            if self.started.is_set():return
            await asyncio.sleep(.01)
        self.fail('Export did not start')

    async def test_double_click_and_reopen_reuse_the_same_export(self):
        with self.patches():
            first=await self.manager.submit(self.identity)
            await self.wait_started();await asyncio.sleep(0)
            again=await self.manager.submit(self.identity)
            self.assertEqual(first['state'],'running');self.assertEqual(again['state'],'running')
            self.assertEqual(self.calls,1)
            self.assertEqual(self.manager.state(self.identity)['total'],9)
            self.release.set();await self.manager.exports[self.identity]['task']
            ready=self.manager.state(self.identity)
            self.assertEqual(ready['state'],'complete');self.assertEqual(ready['completed'],9)
            self.assertEqual(ready['artifact']['subfolder'],'genj/hdr')
            self.assertEqual(await self.manager.submit(self.identity),ready)
        self.assertEqual(self.job['state'],'complete')

    async def test_cancel_only_sets_owned_export_event_and_keeps_render(self):
        with self.patches():
            await self.manager.submit(self.identity);await self.wait_started()
            self.assertEqual(self.manager.cancel(self.identity)['state'],'cancelling')
            self.release.set();await self.manager.exports[self.identity]['task']
        self.assertEqual(self.manager.state(self.identity)['state'],'cancelled')
        self.assertIsNone(self.manager.state(self.identity)['artifact'])
        self.assertEqual(self.job['state'],'complete');self.assertTrue(self.archive.exists())

    async def test_failure_is_retryable_without_rerendering(self):
        with self.patches(lambda *a,**kw:(_ for _ in ()).throw(ValueError('Read failed'))):
            await self.manager.submit(self.identity);await self.manager.exports[self.identity]['task']
        self.assertEqual(self.manager.state(self.identity)['state'],'failed')
        self.assertIn('Read failed',self.manager.state(self.identity)['error'])
        self.release.set()
        with self.patches():
            await self.manager.submit(self.identity);await self.manager.exports[self.identity]['task']
        self.assertEqual(self.manager.state(self.identity)['state'],'complete')

    async def test_only_owned_finished_native_hdr_renders_are_eligible(self):
        for changes in ({'state':'running'},{'kind':'review'},{'hdr_render':False}, {'hdr_files':{}}):
            with self.subTest(changes=changes),patch.dict(self.job,changes):
                with self.assertRaisesRegex(ValueError,'Finish native HDR'):
                    await self.manager.submit(self.identity)
        with self.assertRaises(ValueError):await self.manager.submit('../unsafe')
        self.job['hdr_files']['exr']['subfolder']='../other'
        with self.patches():
            await self.manager.submit(self.identity);await self.manager.exports[self.identity]['task']
        self.assertEqual(self.manager.state(self.identity)['state'],'failed')
        self.assertEqual(self.calls,0)

    async def test_http_routes_cover_both_namespaces(self):
        handlers={}
        class Routes:
            def route(self,verb,path):
                return lambda handler:(handlers.__setitem__((verb,path),handler) or handler)
            def get(self,path):return self.route('GET',path)
            def post(self,path):return self.route('POST',path)
        jobs=SimpleNamespace(state=lambda _:self.job)
        module.register(jobs,Routes(),lambda handler:handler)
        self.assertEqual(len(handlers),6)
        request=SimpleNamespace(match_info={'identity':self.identity})
        response=await handlers[('GET','/zura/studio/outpaint/jobs/{identity}/layers')](request)
        self.assertEqual(json.loads(response.text)['state'],'idle')


if __name__=='__main__':unittest.main()
