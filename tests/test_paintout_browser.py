"""CPU browser helpers keep selected paths and exact source frames intact."""
import ast
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from aiohttp import web
import numpy as np
import torch
import OpenImageIO as oiio

ROOT=Path(__file__).resolve().parents[1]
PACKAGE='_zura_paintout_browser_test'


def load_browser(native):
    server=types.ModuleType('server');server.PromptServer=types.SimpleNamespace(instance=None)
    # Read the production origin guard without importing unrelated media tooling.
    tree=ast.parse((ROOT/'media_source.py').read_text(encoding='utf-8'))
    guard=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='require_same_origin')
    security=types.ModuleType(PACKAGE+'.media_source')
    security.__dict__['urlsplit']=urlsplit
    exec(compile(ast.Module(body=[guard],type_ignores=[]),str(ROOT/'media_source.py'),'exec'),security.__dict__)
    modules={PACKAGE:types.ModuleType(PACKAGE),PACKAGE+'.paintout':types.ModuleType(PACKAGE+'.paintout'),
             PACKAGE+'.paintout.paintout':native,PACKAGE+'.media_source':security,'server':server}
    spec=importlib.util.spec_from_file_location(PACKAGE+'.paintout.browser',ROOT/'paintout/browser.py')
    module=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,modules):spec.loader.exec_module(module)
    return module,modules


class PaintoutBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.video=self.root/'source.mp4';self.video.write_bytes(b'local video')
        self.native=types.ModuleType(PACKAGE+'.paintout.paintout')
        self.native.describe=Mock(return_value={'kind':'video','width':1920,'height':1080,'count':181,'fps':24})
        self.native.selected_space=lambda d,space:space
        self.native.is_hdr=lambda space:space in ('acescg','hlg_rec2020','pq_rec2020')
        self.native.frames=Mock()
        self.native.working=lambda x,space,processing:x
        self.native.ZuraPaintoutExportFrames=Mock()
        self.browser,self.modules=load_browser(self.native)
        self.module_patch=patch.dict(sys.modules,self.modules);self.module_patch.start();self.addCleanup(self.module_patch.stop)

    def request(self,query=None,origin=None,body=None):
        async def read():return body
        return types.SimpleNamespace(query=query or {},headers={'Origin':origin} if origin else {},host='localhost:8188',json=read)

    def test_metadata_has_frame_count_and_token_scoped_video_url(self):
        result=self.browser.describe_media(str(self.video))
        self.assertEqual((result['frames'],result['fps'],result['width'],result['height']),(181,24,1920,1080))
        self.assertEqual(result['kind'],'video')
        self.assertNotIn(str(self.video),result['media_url'])
        query=parse_qs(urlsplit(result['media_url']).query)
        token=query['token'][0]
        response=asyncio.run(self.browser.media(self.request({'token':token})))
        self.assertEqual(response._path,self.video.resolve())
        with self.assertRaises(web.HTTPNotFound):asyncio.run(self.browser.media(self.request({'file':str(self.video)})))

    def test_unsupported_file_is_not_probed_or_served(self):
        private=self.root/'private.json';private.write_text('{"secret":true}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'supported'):self.browser.describe_media(str(private))
        with self.assertRaisesRegex(ValueError,'supported'):self.browser.grant(private)
        self.native.describe.assert_not_called()
        with self.assertRaisesRegex(ValueError,'file picker'):self.browser.checked_path('relative.mp4')

    def test_expired_grants_and_cross_origin_requests_fail(self):
        url=self.browser.grant(self.video);token=parse_qs(urlsplit(url).query)['token'][0]
        with patch.object(self.browser.time,'monotonic',return_value=10**20):
            with self.assertRaises(web.HTTPNotFound):asyncio.run(self.browser.media(self.request({'token':token})))
        for handler,request in ((self.browser.info,self.request({'file':str(self.video)},'https://other.example')),
                                (self.browser.media,self.request({'token':token},'https://other.example')),
                                (self.browser.preview,self.request({'file':str(self.video)},'https://other.example')),
                                (self.browser.export_frame,self.request(origin='https://other.example',body={'file':str(self.video),'frame':0}))):
            with self.assertRaises(web.HTTPForbidden):asyncio.run(handler(request))

    def test_source_export_keeps_exact_absolute_frame_and_native_precision(self):
        output=self.root/'paint_000123.exr';output.write_bytes(b'exr')
        exporter=Mock();exporter.export.return_value={'result':(json.dumps([{'frame':123,'file':str(output),'colour_space':'acescg'}]),)}
        self.native.ZuraPaintoutExportFrames=Mock(return_value=exporter)
        result=self.browser.export_source_frame(str(self.video),123,'hlg_rec2020')
        exporter.export.assert_called_once_with(str(self.video.resolve()),'hlg_rec2020','123','paintout/paint_frames')
        self.assertEqual((result['frame'],result['path'],result['colour_space']),(123,str(output),'acescg'))
        token=parse_qs(urlsplit(result['url']).query)['token'][0]
        response=asyncio.run(self.browser.media(self.request({'token':token})))
        self.assertIn('attachment',response.headers['Content-Disposition'])
        for invalid in (-1,1.25,True,'2'):
            with self.assertRaisesRegex(ValueError,'whole source frame'):self.browser.export_source_frame(str(self.video),invalid,'auto')

    def test_thumbnail_uses_requested_source_frame_and_bounds_size(self):
        import numpy as np
        import torch
        self.native.frames=Mock(return_value=iter([np.zeros((20,40,3),dtype=np.float32)]))
        self.native.resize=lambda x,w,h:torch.zeros((1,h,w,3))
        self.native.selected_space=lambda d,space:'srgb_display'
        output=self.browser.thumbnail(str(self.video),'auto',123,1280)
        self.assertTrue(output.startswith(b'\x89PNG'))
        self.assertEqual(self.native.frames.call_args.args[1:],(123,1))
        for frame,size in ((181,240),(-1,240),(0,1281),(0,1)):
            with self.assertRaises(ValueError):self.browser.thumbnail(str(self.video),'auto',frame,size)

    def test_sdr_export_is_full_resolution_16_bit_srgb_png(self):
        import numpy as np
        import OpenImageIO as oiio
        original=np.random.default_rng(42).random((20,40,3),dtype=np.float32)
        self.native.frames=Mock(return_value=iter([original]))
        folder_paths=types.ModuleType('folder_paths');folder_paths.get_output_directory=lambda:str(self.root/'output')
        with patch.dict(sys.modules,{'folder_paths':folder_paths}):
            result=self.browser.export_source_frame(str(self.video),42,'srgb_display')
        self.assertEqual((result['frame'],result['colour_space']),(42,'srgb_display'))
        self.assertTrue(result['path'].endswith('.png'))
        self.assertEqual(self.native.frames.call_args.args[1:],(42,1))
        self.native.ZuraPaintoutExportFrames.assert_not_called()
        image=oiio.ImageInput.open(result['path'])
        try:
            spec=image.spec();self.assertEqual((spec.width,spec.height,spec.nchannels),(40,20,3))
            self.assertEqual(str(spec.format),'uint16')
            np.testing.assert_allclose(image.read_image(format=oiio.FLOAT),original,atol=1/65535)
        finally:image.close()


if __name__=='__main__':unittest.main()
