"""Original-pixel OCIO preview checks; no models or GPU execution."""
import hashlib
import importlib
import io
from fractions import Fraction
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import numpy as np
from PIL import Image
import OpenImageIO as oiio

import v2_bootstrap

if 'server' not in sys.modules:
    module = types.ModuleType('server'); module.PromptServer = types.SimpleNamespace(instance=None); sys.modules['server'] = module
if 'ComfyUI_zura_nodes.artist_studio' not in sys.modules:
    package = types.ModuleType('ComfyUI_zura_nodes.artist_studio'); package.__path__ = [str(v2_bootstrap.ROOT/'artist_studio')]; sys.modules[package.__name__] = package
views = importlib.import_module('ComfyUI_zura_nodes.artist_studio.display_view_routes')
float_io = importlib.import_module('ComfyUI_zura_nodes.comfylink.float_io')


class OriginalDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.base = Path(self.temp.name)
        self.roots = {kind: self.base/kind for kind in ('input', 'output', 'temp')}
        for root in self.roots.values(): root.mkdir()
        self.store = types.SimpleNamespace(load=lambda _identity: (_ for _ in ()).throw(ValueError('No fixture asset')))
        self.check = lambda asset: Path(asset['file'])

    def tearDown(self):
        views._sources.clear(); self.temp.cleanup()

    def ref(self, name):
        return {'file': {'type': 'output', 'filename': name, 'subfolder': ''}}

    def png(self, name='source.png'):
        path = self.roots['output']/name
        Image.fromarray(np.array([[[0, 128, 255, 255], [64, 192, 127, 64]]], dtype=np.uint8), 'RGBA').save(path)
        return path

    def test_srgb_default_is_real_view_and_keeps_file_and_alpha(self):
        path = self.png(); before = hashlib.sha256(path.read_bytes()).hexdigest()
        shown, space = views.preview({'source': self.ref(path.name)}, self.store, self.check, self.roots)
        pixels = np.array(Image.open(io.BytesIO(shown)))
        original = np.array(Image.open(path))
        self.assertEqual(space, 'srgb_display')
        self.assertLessEqual(np.max(np.abs(pixels.astype(int)-original.astype(int))), 1)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        config = views.display_view.describe()
        self.assertEqual(config['display'], 'sRGB - Display')
        self.assertEqual(config['view'], 'Un-tone-mapped')

    def test_actual_float_exr_survives_preview_and_changes_view(self):
        path = self.roots['output']/'source.exr'
        pixels = np.array([[[-.25, .18, 4., 1.], [1.234567, .03, .4, .33333334]]], dtype=np.float32)
        spec = oiio.ImageSpec(2, 1, 4, oiio.FLOAT); spec.channelnames = ['R', 'G', 'B', 'A']; spec.attribute('oiio:ColorSpace', 'ACEScg')
        writer = oiio.ImageOutput.create(str(path)); self.assertTrue(writer.open(str(path), spec)); self.assertTrue(writer.write_image(pixels)); writer.close()
        before = path.read_bytes()
        read, space, metadata = views.read_original(self.ref(path.name), 0, self.store, self.check, self.roots)
        np.testing.assert_array_equal(read, pixels)
        self.assertEqual(space, 'acescg'); self.assertFalse(metadata['opaque'])
        info = views.display_view.describe()
        available = next(d['views'] for d in info['displays'] if d['name'] == info['display'])
        alternate = next((name for name in available if name != info['view']), None)
        self.assertIsNotNone(alternate)
        a, _ = views.preview({'source':self.ref(path.name)}, self.store, self.check, self.roots)
        b, _ = views.preview({'source':self.ref(path.name), 'view':alternate}, self.store, self.check, self.roots)
        self.assertFalse(np.array_equal(np.array(Image.open(io.BytesIO(a))), np.array(Image.open(io.BytesIO(b)))))
        self.assertEqual(path.read_bytes(), before)

    def test_catalogue_contains_real_qualified_views_and_matches_actual_ocio_values(self):
        catalogue=views.display_view.view_presets()
        self.assertEqual((catalogue[0]['display'],catalogue[0]['view'],catalogue[0]['label']),('sRGB - Display','Un-tone-mapped','sRGB'))
        self.assertGreater(len(catalogue),5)
        identities={(item['display'],item['view']) for item in catalogue}
        self.assertEqual(len(identities),len(catalogue),'Repeated config aliases must not duplicate identical view choices')
        for item in catalogue:
            config=views.display_view._config(item['config'])
            self.assertIn(item['display'],config.getDisplays())
            self.assertIn(item['view'],config.getViews(item['display']))
            self.assertNotIn('AgX',item['label'])
        path=self.roots['output']/'catalogue.exr';pixels=np.array([[[-.01,.18,3.,.33333334]]],np.float32)
        spec=oiio.ImageSpec(1,1,4,oiio.FLOAT);spec.channelnames=['R','G','B','A'];spec.attribute('oiio:ColorSpace','ACEScg')
        writer=oiio.ImageOutput.create(str(path));writer.open(str(path),spec);writer.write_image(pixels);writer.close();original=path.read_bytes()
        selected=[catalogue[0]]+[next(item for item in catalogue if item['display']=='sRGB - Display' and 'aces-v'+version in item['config'])
                    for version in ('1.3','2.0') if any('aces-v'+version in item['config'] for item in catalogue)]
        # The latest alias can represent ACES 2.0 without spelling its version.
        aces2=next((item for item in catalogue if item['display']=='sRGB - Display' and item['view'].startswith('ACES 2.0')),None)
        if aces2:selected.append(aces2)
        for item in selected:
            shown,_=views.preview({'source':self.ref(path.name),**{key:item[key] for key in ('config','display','view')}},self.store,self.check,self.roots)
            actual=np.array(Image.open(io.BytesIO(shown)))
            expected=pixels[...,:3].copy();config=views.display_view._config(item['config'])
            transform=views.display_view._ocio().DisplayViewTransform(src='ACEScg',display=item['display'],view=item['view'])
            config.getProcessor(transform).getDefaultCPUProcessor().applyRGB(expected)
            np.testing.assert_array_equal(actual[...,:3],np.rint(np.clip(expected,0,1)*255).astype(np.uint8))
            self.assertEqual(int(actual[0,0,3]),85)
        self.assertEqual(path.read_bytes(),original)

    def test_embedded_icc_is_used_for_an_ordinary_eight_bit_source(self):
        from PIL import ImageCms
        path = self.png('icc.png')
        with Image.open(path) as original:
            original.save(path, icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
        before = path.read_bytes()
        rgba, space, _ = views.read_original(self.ref(path.name),0,self.store,self.check,self.roots)
        self.assertEqual(space,'srgb_display')
        self.assertAlmostEqual(float(rgba[0,1,3]),64/255,places=6)
        views.preview({'source':self.ref(path.name)},self.store,self.check,self.roots)
        self.assertEqual(path.read_bytes(),before)

    def test_float_manifest_reads_original_bits_and_exact_rate(self):
        pixels = np.array([[[[-.5, .1234567, 3., 0.]]], [[[.2, 2., .4, .75]]]], dtype=np.float32)
        relative, manifest = float_io.write_transfer(self.roots['output'], 'ComfyLink/'+'a'*32, pixels,
            colour={'encoding':'acescg', 'sceneLinear':True}, frame_rate={'numerator':30000, 'denominator':1001})
        selector = {'file':{'type':'output','subfolder':str(Path(relative).parent).replace('\\','/'),'filename':'manifest.json'}}
        actual, space, metadata = views.read_original(selector, 1, self.store, self.check, self.roots)
        np.testing.assert_array_equal(actual, pixels[1]); self.assertEqual(space, 'acescg')
        self.assertEqual(metadata['frame_count'], 2); self.assertEqual(metadata['frame_rate'], manifest['frameRate'])
        payload = self.roots['output']/Path(relative).parent/manifest['frames'][1]['filename']
        data = bytearray(payload.read_bytes()); data[0] ^= 1; payload.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'changed'):
            views.read_original(selector, 1, self.store, self.check, self.roots)

    def test_native_grant_is_scoped_expiring_and_rejects_changed_source(self):
        path = self.png(); token = views.grant_source(path, 'srgb_display')
        resolved = views.resolve_original({'source_token':token}, self.store, self.check, self.roots)
        self.assertEqual(resolved['path'], path.resolve()); resolved['revalidate']()
        rgba, _, metadata = views.read_original({'source_token':token}, 0, self.store, self.check, self.roots)
        self.assertEqual(rgba.shape, (1, 2, 4)); self.assertFalse(metadata['opaque'])
        path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            resolved['revalidate']()
        other = self.png('other.png'); token = views.grant_source(other, 'srgb_display')
        expires = views._sources[token]['expires']
        with patch.object(views.time, 'monotonic', return_value=expires+1):
            with self.assertRaisesRegex(ValueError, 'refresh'):
                views.read_original({'source_token':token}, 0, self.store, self.check, self.roots)

    def test_video_reader_preserves_original_fractional_clock_and_frame_index(self):
        import av
        path=self.roots['output']/'source.mkv';rate=Fraction(30000,1001)
        with av.open(str(path),'w') as output:
            stream=output.add_stream('ffv1',rate=rate);stream.width=64;stream.height=64;stream.pix_fmt='bgr0'
            for index in range(9):
                frame=av.VideoFrame.from_ndarray(np.full((64,64,3),index*16,dtype=np.uint8),format='rgb24')
                for packet in stream.encode(frame):output.mux(packet)
            for packet in stream.encode():output.mux(packet)
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        resolved=views.resolve_original(self.ref(path.name),self.store,self.check,self.roots)
        info=views.source_info({'source':self.ref(path.name)},self.store,self.check,self.roots)
        self.assertEqual(info,{'kind':'video','frame_count':9,'frame_rate':{'numerator':30000,'denominator':1001}})
        pixels,space,metadata=views.read_original(self.ref(path.name),7,self.store,self.check,self.roots,'srgb_display')
        self.assertEqual(metadata['frame_count'],9);self.assertEqual(metadata['frame_rate'],{'numerator':30000,'denominator':1001})
        self.assertEqual(space,'srgb_display');self.assertAlmostEqual(float(pixels[0,0,0]),112/255,places=6)
        resolved['revalidate']();self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
        asset={'kind':'asset','asset_kind':'video','file':str(path)}
        store=types.SimpleNamespace(load=lambda _:asset)
        selected={'asset_id':'b'*32,'frame_time':float(Fraction(7,1)/rate)}
        pixels,_,metadata=views.read_original(selected,0,store,self.check,self.roots,'srgb_display')
        self.assertEqual(metadata['frame_count'],1);self.assertAlmostEqual(float(pixels[0,0,0]),112/255,places=6)
        with self.assertRaises(ValueError):views.read_original(selected,1,store,self.check,self.roots,'srgb_display')
        with self.assertRaisesRegex(ValueError,'exact video frame'):views.read_original({**selected,'frame_time':.01},0,store,self.check,self.roots,'srgb_display')

    def test_premultiplied_display_unassociates_a_copy_before_colour_transform(self):
        straight=np.array([[[.18,.18,.18,.5]]],dtype=np.float32)
        associated=straight.copy();associated[...,:3]*=.5
        before=associated.copy()
        a=views.render_pixels(straight,'linear_rec709')
        b=views.render_pixels(associated,'linear_rec709',alpha_association='premultiplied')
        np.testing.assert_array_equal(np.array(Image.open(io.BytesIO(a))),np.array(Image.open(io.BytesIO(b))))
        np.testing.assert_array_equal(associated,before)

    def test_sequence_grant_keeps_native_order_and_full_revalidation(self):
        directory = self.base/'native'; directory.mkdir()
        for name, level in [('frame10.png', 200), ('frame2.png', 100)]:
            Image.fromarray(np.full((2, 2, 3), level, dtype=np.uint8), 'RGB').save(directory/name)
        token = views.grant_source(directory, 'srgb_display'); selector={'source_token':token}
        resolved = views.resolve_original(selector, self.store, self.check, self.roots)
        self.assertEqual([file.name for file in resolved['files']], ['frame2.png','frame10.png'])
        original, _, metadata = views.read_original(selector, 1, self.store, self.check, self.roots)
        self.assertEqual(metadata['frame_count'], 2); self.assertIsNone(metadata['frame_rate'])
        self.assertAlmostEqual(float(original[0,0,0]), 200/255, places=6)
        (directory/'frame2.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):
            resolved['revalidate']()

    def test_invalid_references_frames_configs_and_oversize_are_rejected(self):
        path = self.png()
        selectors = [{'path':str(path)}, {'file':{'type':'output','filename':'../source.png'}},
                     {'file':{'type':'output','filename':'source.png','subfolder':'../output'}},
                     {'media_url':'https://example.test/zura/paintout/media?token=abc'}]
        for source in selectors:
            with self.assertRaises(ValueError): views.preview({'source':source}, self.store, self.check, self.roots)
        for options in ({'frame':True}, {'frame':-1}, {'frame':1}, {'config':'C:/untrusted.ocio'}, {'view':'missing'}):
            with self.assertRaises(ValueError): views.preview({'source':self.ref(path.name),**options}, self.store, self.check, self.roots)
        with patch.object(views,'MAX_PIXELS',1):
            with self.assertRaisesRegex(ValueError, 'limit'): views.preview({'source':self.ref(path.name)}, self.store, self.check, self.roots)


class DisplayRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_use_original_files_bound_requests_and_reject_cross_origin(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);Image.new('RGB',(2,2),(128,64,32)).save(root/'source.png')
            routes=web.RouteTableDef()
            def response(fn):
                async def wrapped(request):
                    try:return await fn(request)
                    except (ValueError,TypeError,KeyError,OSError) as error:return web.json_response({'error':str(error)},status=400)
                return wrapped
            studio=types.SimpleNamespace(store=types.SimpleNamespace(load=lambda _:None))
            folder_paths=sys.modules['folder_paths']
            with patch.object(folder_paths,'get_input_directory',return_value=str(root)),patch.object(folder_paths,'get_output_directory',return_value=str(root)),patch.object(folder_paths,'get_temp_directory',return_value=str(root)):
                views.register(studio,routes,response,lambda value:value)
                app=web.Application();app.add_routes(routes)
                async with TestClient(TestServer(app)) as client:
                    config=await client.get('/zura/studio/display/config');self.assertEqual(config.status,200)
                    self.assertEqual((await config.json())['display'],'sRGB - Display')
                    denied=await client.get('/zura/studio/display/config',headers={'Origin':'https://other.example'})
                    self.assertEqual(denied.status,403)
                    body={'source':{'file':{'type':'output','filename':'source.png'}}}
                    info=await client.post('/zura/studio/display/info',json=body)
                    self.assertEqual(info.status,200)
                    self.assertEqual(await info.json(),{'kind':'image','frame_count':1,'frame_rate':None})
                    denied_info=await client.post('/zura/studio/display/info',json=body,headers={'Origin':'https://other.example'})
                    self.assertEqual(denied_info.status,403)
                    shown=await client.post('/zura/studio/display/frame',json=body)
                    self.assertEqual(shown.status,200);self.assertEqual(shown.headers['Content-Type'],'image/png')
                    self.assertEqual(shown.headers['X-Zura-Preview-Only'],'1');self.assertEqual(shown.headers['X-Zura-Display-Frames'],'1')
                    self.assertTrue((await shown.read()).startswith(b'\x89PNG'))
                    too_large=await client.post('/zura/studio/display/frame',data=b' '*17000)
                    self.assertEqual(too_large.status,400)
                    traversal=await client.post('/zura/studio/display/frame',json={'source':{'file':{'type':'output','filename':'../source.png'}}})
                    self.assertEqual(traversal.status,400)
                    invalid_info=await client.post('/zura/studio/display/info',json={'source':body['source'],'frame':0})
                    self.assertEqual(invalid_info.status,400)


if __name__ == '__main__': unittest.main()
