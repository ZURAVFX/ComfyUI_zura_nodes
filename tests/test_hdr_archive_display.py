"""Original native HDR archive display tests, without model execution."""
from pathlib import Path
import hashlib
import importlib
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer

import numpy as np
import OpenImageIO as oiio
from PIL import Image
import v2_bootstrap

name='ComfyUI_zura_nodes.artist_studio'
if name not in sys.modules:
    package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/'artist_studio')];sys.modules[name]=package
if 'ComfyUI_zura_nodes.paintout' not in sys.modules:
    package=types.ModuleType('ComfyUI_zura_nodes.paintout');package.__path__=[str(v2_bootstrap.ROOT/'paintout')];sys.modules[package.__name__]=package
archive_display=importlib.import_module(name+'.hdr_archive_display')
views=importlib.import_module(name+'.display_view_routes')
native_result=importlib.import_module(name+'.ltx25_hdr_result')


class NativeArchiveDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.output=self.root/'output';self.output.mkdir()
        self.roots={'input':self.root/'input','output':self.output,'temp':self.root/'temp'}
        for path in self.roots.values():path.mkdir(exist_ok=True)
        self.store=types.SimpleNamespace(load=lambda _:None)
        archive_display._indexes.clear()

    def tearDown(self):self.temp.cleanup()

    def exr(self,name='source.exr',storage='float32',*,width=3,height=2,colour='ACEScg',chroma=True,channels=('R','G','B'),level=0):
        path=self.root/name
        spec=oiio.ImageSpec(width,height,len(channels),oiio.HALF if storage=='half' else oiio.UINT if storage=='uint32' else oiio.FLOAT)
        spec.channelnames=list(channels);spec.attribute('compression','zip')
        if colour is not None:spec.attribute('oiio:ColorSpace',colour)
        if chroma:spec.attribute('chromaticities',oiio.TypeDesc('float[8]'),archive_display._AP1 if chroma is True else chroma)
        pixels=np.empty((height,width,len(channels)),dtype=np.float32)
        pixels[...,:3]=np.array([-.005123,.180123+level,2.123456+level],dtype=np.float32)
        if len(channels)>3:pixels[...,3:]=1
        writer=oiio.ImageOutput.create(str(path));self.assertTrue(writer.open(str(path),spec));self.assertTrue(writer.write_image(pixels));writer.close()
        return path,pixels

    def archive(self,count=3,storage='float32',name='native.zip'):
        destination=self.output/name;expected=[]
        with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
            for index in range(count):
                path,pixels=self.exr(f'source{index}.exr',storage,level=index)
                archive.write(path,f'frame_{index:05d}.exr');expected.append(pixels)
        return destination,expected

    def selector(self,path):return {'file':{'filename':path.name,'subfolder':'','type':'output'}}

    def test_half_and_float_n1_n3_original_hdr_pixels_selected_index_and_clock(self):
        for count in (1,3):
            for storage in ('half','float32'):
                with self.subTest(count=count,storage=storage):
                    path,pixels=self.archive(count,storage,f'{storage}-{count}.zip');before=path.read_bytes()
                    native_result._check_archive(path,count,3,2,exr_storage=storage)
                    expected={'width':3,'height':2,'frame_count':count,'exr_storage':storage,'frame_rate':{'numerator':30000,'denominator':1001}}
                    selected,metadata=archive_display.read_archive_frame(path,count-1,expected)
                    target=pixels[-1].astype(np.float16).astype(np.float32) if storage=='half' else pixels[-1]
                    np.testing.assert_array_equal(selected[...,:3],target);np.testing.assert_array_equal(selected[...,3],np.ones((2,3)))
                    self.assertLess(float(selected[0,0,0]),0);self.assertGreater(float(selected[0,0,2]),1)
                    self.assertEqual(metadata['frame_rate'],expected['frame_rate']);self.assertEqual(metadata['exr_storage'],storage)
                    self.assertEqual(path.read_bytes(),before)
                    original,space,metadata=views.read_original(self.selector(path),count-1,self.store,lambda value:value,self.roots,archive_metadata=lambda _:expected)
                    np.testing.assert_array_equal(original,selected);self.assertEqual(space,'acescg');self.assertEqual(metadata['frame_count'],count)
                    shown,space=views.preview({'source':self.selector(path),'frame':count-1},self.store,lambda value:value,self.roots,archive_metadata=lambda _:expected)
                    self.assertEqual(np.array(Image.open(io.BytesIO(shown))).shape,(2,3,4));self.assertEqual(space,'acescg');self.assertEqual(path.read_bytes(),before)

    def test_index_is_cached_without_decoding_or_copying_unselected_frames(self):
        path,_=self.archive();original_build=archive_display._build_index;original_copy=archive_display._copy_member;copied=[]
        def record_copy(source,entry,destination,*args):copied.append(entry['name']);return original_copy(source,entry,destination,*args)
        with patch.object(archive_display,'_build_index',wraps=original_build) as build,patch.object(archive_display,'_copy_member',side_effect=record_copy),patch.object(archive_display,'_decode_frame',wraps=archive_display._decode_frame) as decode:
            first=archive_display.describe_archive(path);self.assertEqual(first['frame_count'],3);self.assertIsNone(first['frame_rate']);self.assertEqual(decode.call_count,0)
            archive_display.read_archive_frame(path,2);archive_display.read_archive_frame(path,1)
            self.assertEqual(build.call_count,1);self.assertEqual(decode.call_count,2);self.assertEqual(copied,['frame_00002.exr','frame_00001.exr'])

    def test_intended_metadata_and_selected_frame_metadata_must_match(self):
        path,_=self.archive()
        for expected in ({'width':4},{'height':3},{'frame_count':2},{'exr_storage':'half'},{'frame_rate':{'numerator':True,'denominator':1}}):
            with self.subTest(expected=expected),self.assertRaises(ValueError):archive_display.read_archive_frame(path,0,expected)
        with self.assertRaises(ValueError):archive_display.read_archive_frame(path,3)
        other,_=self.exr('different.exr',width=4)
        original,_=self.exr('ordinary.exr')
        mixed=self.output/'mixed.zip'
        with zipfile.ZipFile(mixed,'w',compression=zipfile.ZIP_STORED) as archive:
            archive.write(original,'frame_00000.exr');archive.write(other,'frame_00001.exr')
        with self.assertRaisesRegex(ValueError,'inconsistent metadata'):archive_display.read_archive_frame(mixed,1)

    def test_zip_paths_compression_duplicates_links_and_extensions_reject(self):
        exr,_=self.exr();payload=exr.read_bytes()
        cases=[(['../frame_00000.exr'],zipfile.ZIP_STORED),(['C:/frame_00000.exr'],zipfile.ZIP_STORED),
               (['frame_00001.exr'],zipfile.ZIP_STORED),(['frame_00000.exr','frame_00000.exr'],zipfile.ZIP_STORED),
               (['frame_00000.exr','metadata.json'],zipfile.ZIP_STORED),(['frame_00000.exr'],zipfile.ZIP_DEFLATED)]
        for index,(names,compression) in enumerate(cases):
            path=self.output/f'bad-{index}.zip'
            with zipfile.ZipFile(path,'w',compression=compression) as archive:
                for name in names:archive.writestr(name,payload)
            with self.subTest(names=names,compression=compression),self.assertRaises(ValueError):archive_display.read_archive_frame(path,0)
        for attribute,value in [('external_attr',0o120777<<16),('extra',b'\x75\x70\x00\x00'),('extra',struct.pack('<HHQ',1,8,0)),('comment',b'unsupported')]:
            path=self.output/(attribute+'.zip');info=zipfile.ZipInfo('frame_00000.exr');setattr(info,attribute,value)
            with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_STORED) as archive:archive.writestr(info,payload)
            with self.subTest(attribute=attribute),self.assertRaises(ValueError):archive_display.read_archive_frame(path,0)

    def test_missing_or_wrong_hdr_metadata_and_nonfinite_pixels_reject(self):
        variants=[{'chroma':False},{'colour':'ACEScct'},{'chroma':(.64,.33,.30,.60,.15,.06,.3127,.3290)},{'storage':'uint32'},{'level':float('nan')}]
        for index,settings in enumerate(variants):
            frame,_=self.exr(f'bad-{index}.exr',**settings);path=self.output/f'metadata-{index}.zip'
            with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_STORED) as archive:archive.write(frame,'frame_00000.exr')
            with self.subTest(settings=settings),self.assertRaises(ValueError):archive_display.read_archive_frame(path,0)
        path,_=self.archive(name='budget.zip')
        with patch.object(archive_display,'MAX_FRAME_BYTES',1),self.assertRaises(ValueError):archive_display.read_archive_frame(path,0)

    @unittest.skipUnless(importlib.util.find_spec('OpenImageIO') and importlib.util.find_spec('torch'),'Native HDR exporter dependencies required')
    def test_actual_rgba_exporter_n1_n9_previews_alpha_and_rejects_proof_tamper(self):
        from fractions import Fraction
        from test_hdr_alpha_delivery import HDRAlphaDeliveryTests, export
        fixture=HDRAlphaDeliveryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        for count in (1,9):
            alpha,values,_=fixture.source(count)
            stage=fixture.staged(count,'a' if count==1 else 'b')
            exported=export.export_rgba_exr_zip(stage,fixture.root,f'viewer_{count}',alpha_source=alpha,frame_rate=Fraction(30000,1001))
            path=self.output/f'viewer_{count}.zip';shutil.copyfile(exported,path)
            metadata=archive_display.describe_archive(path)
            self.assertEqual(metadata['frame_count'],count);self.assertTrue(metadata['has_alpha'])
            self.assertEqual(metadata['exr_storage'],'float32');self.assertEqual(metadata['frame_rate'],{'numerator':30000,'denominator':1001})
            selected,actual=archive_display.read_archive_frame(path,count-1)
            np.testing.assert_array_equal(selected[...,3].view(np.uint32),values.view(np.uint32))
            self.assertGreater(float(selected[0,0,2]),1)
            shown,space,preview_metadata=views.preview({'source':self.selector(path),'frame':count-1},self.store,lambda value:value,self.roots,return_metadata=True)
            self.assertEqual(space,'acescg');self.assertFalse(preview_metadata['opaque'])
            expected_alpha=np.rint(values*255).astype(np.uint8)
            np.testing.assert_array_equal(np.array(Image.open(io.BytesIO(shown)))[...,3],expected_alpha)
            with zipfile.ZipFile(path) as archive:
                members={name:archive.read(name) for name in archive.namelist()}
            proof=json.loads(members[archive_display.PROOF_NAME])
            for key in ('sha256','alphaSha256'):
                changed=json.loads(json.dumps(proof));changed['frames'][count-1][key]='0'*64
                invalid=self.output/f'viewer_{count}_{key}.zip'
                with zipfile.ZipFile(invalid,'w',compression=zipfile.ZIP_STORED) as archive:
                    for name,data in members.items():archive.writestr(name,json.dumps(changed).encode() if name==archive_display.PROOF_NAME else data)
                archive_display._indexes.clear()
                with self.assertRaisesRegex(ValueError,'delivery proof'):archive_display.read_archive_frame(invalid,count-1)

    def test_selected_member_crc_failure_cleans_private_frame_and_keeps_archive(self):
        path,_=self.archive()
        with zipfile.ZipFile(path) as archive:info=archive.getinfo('frame_00002.exr')
        data=bytearray(path.read_bytes());name_size,extra_size=struct.unpack('<2H',data[info.header_offset+26:info.header_offset+30])
        data[info.header_offset+30+name_size+extra_size+info.file_size-1]^=1;path.write_bytes(data)
        before=hashlib.sha256(path.read_bytes()).hexdigest();created=[]
        make=archive_display.tempfile.TemporaryDirectory
        def temporary(*args,**kwargs):
            value=make(*args,**kwargs);created.append(Path(value.name));return value
        with patch.object(archive_display.tempfile,'TemporaryDirectory',side_effect=temporary),self.assertRaisesRegex(ValueError,'checksum'):
            archive_display.read_archive_frame(path,2)
        self.assertTrue(created);self.assertTrue(all(not directory.exists() for directory in created))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_cache_identity_and_original_file_lock_detect_tamper(self):
        path,_=self.archive();archive_display.describe_archive(path);original=path.read_bytes()
        with path.open('ab') as stream:stream.write(b'changed')
        with self.assertRaises(ValueError):archive_display.read_archive_frame(path,0)
        path.write_bytes(original);archive_display._indexes.clear()
        decode=archive_display._decode_frame;blocked=[]
        def tamper(frame,metadata):
            try:
                with path.open('ab') as changed:changed.write(b'changed')
            except PermissionError:blocked.append(True)
            return decode(frame,metadata)
        with patch.object(archive_display,'_decode_frame',side_effect=tamper):
            if os.name=='nt':archive_display.read_archive_frame(path,0);self.assertEqual(blocked,[True]);self.assertEqual(path.read_bytes(),original)
            else:
                with self.assertRaisesRegex(ValueError,'changed'):archive_display.read_archive_frame(path,0)

    def test_completed_native_service_metadata_supplies_rational_cadence(self):
        path,_=self.archive()
        job=types.SimpleNamespace(state='complete',result={'files':[str(path)],'frames':3,'fps':30000/1001,'exr_storage':'float32'})
        details={'width':3,'height':2,'frames':3,'fps':30000/1001,'exr_storage':'float32'}
        service=types.SimpleNamespace(jobs=types.SimpleNamespace(jobs={'native':(job,details)}))
        studio=types.SimpleNamespace(server=types.SimpleNamespace(_zura_hdr_long_preview=service),store=self.store)
        expected=views.native_archive_metadata(studio,path,self.output)
        self.assertEqual(expected['frame_rate'],{'numerator':30000,'denominator':1001})
        _,metadata=archive_display.read_archive_frame(path,2,expected);self.assertEqual(metadata['frame_rate'],expected['frame_rate'])
        job.state='failed';self.assertIsNone(views.native_archive_metadata(studio,path,self.output))


class ArchiveDisplayRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_zip_frame_endpoint_reports_the_full_frame_range(self):
        fixture=NativeArchiveDisplayTests();fixture.setUp()
        try:
            path,_=fixture.archive();before=path.read_bytes();routes=web.RouteTableDef()
            def response(fn):
                async def wrapped(request):
                    try:return await fn(request)
                    except (ValueError,OSError,TypeError,KeyError) as error:return web.json_response({'error':str(error)},status=400)
                return wrapped
            studio=types.SimpleNamespace(store=fixture.store)
            folders=sys.modules['folder_paths']
            with patch.object(folders,'get_input_directory',return_value=str(fixture.roots['input'])),patch.object(folders,'get_output_directory',return_value=str(fixture.output)),patch.object(folders,'get_temp_directory',return_value=str(fixture.roots['temp'])):
                views.register(studio,routes,response,lambda value:value)
                app=web.Application();app.add_routes(routes)
                async with TestClient(TestServer(app)) as client:
                    shown=await client.post('/zura/studio/display/frame',json={'source':fixture.selector(path),'frame':2})
                    self.assertEqual(shown.status,200,await shown.text() if shown.status!=200 else '')
                    self.assertEqual(shown.headers['X-Zura-Display-Frames'],'3');self.assertEqual(shown.headers['X-Zura-Display-Source'],'acescg')
                    self.assertTrue((await shown.read()).startswith(b'\x89PNG'));self.assertEqual(path.read_bytes(),before)
                    bad=await client.post('/zura/studio/display/frame',json={'source':fixture.selector(path),'frame':3})
                    self.assertEqual(bad.status,400)
        finally:fixture.tearDown()


if __name__=='__main__':unittest.main()
