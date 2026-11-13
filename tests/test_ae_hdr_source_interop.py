"""SDK-like OCIO capture identity through actual FLOAT EXR upload, without GPU."""
import asyncio
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import numpy as np
import OpenImageIO as oiio
import PyOpenColorIO as ocio

import v2_bootstrap
for name,folder in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/folder)];sys.modules[name]=package
if 'server' not in sys.modules:
    module=types.ModuleType('server');module.PromptServer=types.SimpleNamespace(instance=None);sys.modules['server']=module
sequence=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_sequence')
float_io=importlib.import_module('ComfyUI_zura_nodes.comfylink.float_io')
sessions=importlib.import_module('ComfyUI_zura_nodes.comfylink.studio_sessions')


class AEHDRSourceInteropTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.inputs=self.root/'input';self.outputs=self.root/'output';self.inputs.mkdir();self.outputs.mkdir()
        self.program=self.root/'Program Files'
        folder=self.program/'Adobe'/'Adobe After Effects 2026'/'Support Files'/'OpenColorIO-Configs'/'test'
        folder.mkdir(parents=True)
        self.config=ocio.Config.CreateFromFile('ocio://cg-config-latest')
        self.config.addColorSpace(ocio.ColorSpace(name='Unsupported camera working space'))
        self.config_path=folder/'config.ocio';self.config_path.write_text(self.config.serialize(),encoding='utf-8')
        self.environment=patch.dict(os.environ,{'ProgramFiles':str(self.program)});self.environment.start()
        self.paths=patch('folder_paths.get_input_directory',return_value=str(self.inputs));self.paths.start()

    def tearDown(self):
        self.paths.stop();self.environment.stop();self.temp.cleanup()

    def colour(self,working='ACEScg'):
        return {'encoding':'unknown','sceneLinear':False,'management':'ocio','ocioConfig':'SDK fixture',
            'ocioConfigPath':str(self.config_path),'ocioWorkingSpace':working,
            'ocioConfigHandleSha256':'a'*64,'ocioWorkingSpaceHandleSha256':'b'*64,
            'ocioConfigFileSha256':hashlib.sha256(self.config_path.read_bytes()).hexdigest()}

    def frame(self,path,colour):
        pixels=np.array([[[-.25,.18,4.,1.],[.1234567,1.234567,.03,.33333334]]],dtype=np.float32)
        float_io.write_exr(path,pixels,colour=colour,storage='float32')
        return pixels

    async def test_actual_native_import_upload_discovers_verified_colour_without_relabelling(self):
        for working,encoding,space in [('ACEScg','acescg','acescg'),('Linear Rec.709 (sRGB)','scene_linear_rec709','linear_rec709')]:
            with self.subTest(working=working):
                colour=self.colour(working);values=np.array([[[[-.25,.18,4.,1.],[.1234567,1.234567,.03,.33333334]]]],dtype=np.float32)
                identity=hashlib.sha256(working.encode()).hexdigest()[:32]
                relative,manifest=float_io.write_transfer(self.inputs,'ComfyLink/'+identity,values,
                    colour=colour,frame_rate={'numerator':24000,'denominator':1001})
                original=copy.deepcopy(manifest);raw_path=self.inputs/Path(relative).parent/manifest['frames'][0]['filename'];raw=raw_path.read_bytes()
                saved={};store=types.SimpleNamespace(save=lambda asset:saved.update({asset['id']:asset}))
                routes=web.RouteTableDef()
                def response(handler):
                    async def wrapped(request):
                        try:return await handler(request)
                        except ValueError as error:return web.json_response({'error':str(error)},status=400)
                    return wrapped
                sequence.register(types.SimpleNamespace(store=store),routes,response)
                app=web.Application();app.add_routes(routes)
                native=TestServer(app,host='127.0.0.1');await native.start_server()
                try:
                    service=sessions.StudioSessions(input_root=self.inputs,output_root=self.outputs)
                    session=types.SimpleNamespace(id=identity,origin=str(native.make_url('/')).rstrip('/'),closed=False,expires=time.time()+600)
                    service.sessions[identity]=session
                    imported=await service.native_import(session,self.inputs/Path(relative).parent,manifest)
                    self.assertEqual(manifest,original);self.assertEqual(manifest['colour'],colour);self.assertFalse(manifest['colour']['sceneLinear'])
                    self.assertEqual(raw_path.read_bytes(),raw)
                    mapped=imported['nativeInputColour'];asset=imported['studioAsset']
                    self.assertEqual(mapped['encoding'],encoding);self.assertTrue(mapped['sceneLinear']);self.assertEqual(imported['resolved_colour'],space)
                    self.assertEqual(mapped['source'],'verified_ae_ocio');self.assertEqual(mapped['ocioConfigFileSha256'],colour['ocioConfigFileSha256'])
                    self.assertEqual(mapped['sourceColourSha256'],hashlib.sha256(float_io.canonical_manifest_bytes(colour)).hexdigest())
                    self.assertEqual(asset['nativeInputColour'],mapped);self.assertEqual(saved[asset['id']]['resolved_colour'],space)
                    uploaded=self.inputs/Path(asset['file']).parent/'frames'/'000001.exr'
                    generated=next((self.inputs/Path(relative).parent).glob('native-*'))/'000001.exr'
                    self.assertEqual(uploaded.read_bytes(),generated.read_bytes(),'The uploader must not resave EXR channels or storage')
                    reader=oiio.ImageInput.open(str(uploaded))
                    try:
                        spec=reader.spec();self.assertEqual(spec.format,oiio.FLOAT)
                        self.assertEqual(json.loads(spec.getattribute('comfylink:colour')),colour)
                        actual=np.asarray(reader.read_image(format=oiio.FLOAT))
                        channels=[spec.channelnames.index(name) for name in ('R','G','B','A')]
                        np.testing.assert_array_equal(actual[...,channels],values[0])
                    finally:reader.close()
                finally:await native.close()

    async def test_every_ae_header_must_have_the_same_verified_identity(self):
        first=self.outputs/'first.exr';second=self.outputs/'second.exr'
        colour=self.colour();self.frame(first,colour);self.frame(second,self.colour('ACEScct'))
        with self.assertRaisesRegex(ValueError,'differs between'):sequence.discover_colour([first,second])
        second.unlink();second.with_suffix('.exr.json').unlink()
        spec=oiio.ImageSpec(2,1,3,oiio.FLOAT);writer=oiio.ImageOutput.create(str(second));writer.open(str(second),spec);writer.write_image(np.ones((1,2,3),np.float32));writer.close()
        with self.assertRaisesRegex(ValueError,'differs between'):sequence.discover_colour([first,second])

    async def test_native_import_independently_rejects_upload_mapping_mismatch(self):
        colour=self.colour();identity='d'*32;values=np.array([[[[.1234567,2.,-.25,1.]]]],dtype=np.float32)
        relative,manifest=float_io.write_transfer(self.inputs,'ComfyLink/'+identity,values,colour=colour,frame_rate={'numerator':24,'denominator':1})
        expected=sequence.native_input_colour(colour)
        async def wrong_upload(request):
            part=await(await request.multipart()).next();await part.read()
            return web.json_response({'id':'e'*32,'count':1,'nativeInputColour':{**expected,'ocioConfigFileSha256':'0'*64},'resolved_colour':'acescg'})
        app=web.Application();app.router.add_post('/zura/studio/hdr/exr-sequence',wrong_upload)
        native=TestServer(app,host='127.0.0.1');await native.start_server()
        try:
            service=sessions.StudioSessions(input_root=self.inputs,output_root=self.outputs)
            session=types.SimpleNamespace(id=identity,origin=str(native.make_url('/')).rstrip('/'),closed=False,expires=time.time()+600);service.sessions[identity]=session
            original=copy.deepcopy(manifest)
            with self.assertRaisesRegex(ValueError,'differs from the captured AE identity'):
                await service.native_import(session,self.inputs/Path(relative).parent,manifest)
            self.assertEqual(manifest,original)
        finally:await native.close()

    async def test_actual_adobe_aces12_config_if_installed(self):
        path=Path(r'C:/Program Files/Adobe/Adobe After Effects 2026/Support Files/OpenColorIO-Configs/ACES 1.2/config.ocio')
        if not path.is_file():self.skipTest('Adobe ACES1.2 config is not installed on this test host')
        colour={**self.colour(),'ocioConfigPath':str(path),'ocioConfig':'ACES 1.2','ocioWorkingSpace':'ACES - ACEScg','ocioConfigFileSha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        with patch.dict(os.environ,{'ProgramFiles':r'C:/Program Files'}):mapped=sequence.native_input_colour(colour)
        self.assertEqual(mapped['encoding'],'acescg');self.assertTrue(mapped['sceneLinear']);self.assertFalse(colour['sceneLinear'])

    async def test_unverified_config_unknown_space_and_oversized_identity_are_explicit_failures(self):
        colour=self.colour();bad={**colour,'ocioConfigFileSha256':'0'*64}
        with self.assertRaisesRegex(ValueError,'changed'):sequence.native_input_colour(bad)
        with self.assertRaisesRegex(ValueError,'not mapped'):sequence.native_input_colour(self.colour('Unsupported camera working space'))
        path=self.outputs/'oversized.exr';spec=oiio.ImageSpec(1,1,3,oiio.FLOAT);spec.attribute('comfylink:colour',' '*32769)
        writer=oiio.ImageOutput.create(str(path));writer.open(str(path),spec);writer.write_image(np.zeros((1,1,3),np.float32));writer.close()
        with self.assertRaisesRegex(ValueError,'too large'):sequence.discover_colour([path])

    async def test_ordinary_tagged_exr_keeps_existing_explicit_interpretation(self):
        path=self.outputs/'normal.exr';spec=oiio.ImageSpec(1,1,3,oiio.HALF);spec.attribute('oiio:ColorSpace','ACEScg')
        writer=oiio.ImageOutput.create(str(path));writer.open(str(path),spec);writer.write_image(np.array([[[.1,.2,2.]]],np.float32));writer.close();before=path.read_bytes()
        self.assertEqual(sequence.discover_colour([path]),{});self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
