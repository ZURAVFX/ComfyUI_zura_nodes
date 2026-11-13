"""Real CPU colour conversion and lossless model-input timing checks."""
from fractions import Fraction
import hashlib
import importlib
from pathlib import Path
import sys
import tempfile
import threading
import subprocess
import types
import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer

import av
import numpy as np
import OpenImageIO as oiio
from PIL import Image

import v2_bootstrap

if 'server' not in sys.modules:
    module=types.ModuleType('server');module.PromptServer=types.SimpleNamespace(instance=None);sys.modules['server']=module
if 'ComfyUI_zura_nodes.artist_studio' not in sys.modules:
    package=types.ModuleType('ComfyUI_zura_nodes.artist_studio');package.__path__=[str(v2_bootstrap.ROOT/'artist_studio')];sys.modules[package.__name__]=package
model=importlib.import_module('ComfyUI_zura_nodes.artist_studio.model_view')
views=importlib.import_module('ComfyUI_zura_nodes.artist_studio.display_view_routes')
float_io=importlib.import_module('ComfyUI_zura_nodes.comfylink.float_io')


class ModelViewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.roots={kind:self.base/kind for kind in ('input','output','temp')}
        for root in self.roots.values():root.mkdir()
        self.store=types.SimpleNamespace(load=lambda _id:(_ for _ in ()).throw(ValueError('No fixture asset')))
        self.check=lambda asset:Path(asset['file'])

    def tearDown(self):
        views._sources.clear();self.temp.cleanup()

    def source(self,path):
        return {'file':{'filename':path.name,'subfolder':'','type':'output'}}

    def exr(self,name='source.exr',space='Linear Rec.709 (sRGB)'):
        path=self.roots['output']/name
        pixels=np.array([[[.18,.18,.18,1.],[-.25,4.,.18,.25]]],dtype=np.float32)
        spec=oiio.ImageSpec(2,1,4,oiio.FLOAT);spec.channelnames=['R','G','B','A'];spec.attribute('oiio:ColorSpace',space)
        writer=oiio.ImageOutput.create(str(path));self.assertTrue(writer.open(str(path),spec));self.assertTrue(writer.write_image(pixels));writer.close()
        return path,pixels

    def prepare(self,body,cancel=None):
        return model.prepare(body,self.store,self.check,self.roots,cancel)

    def test_linear_hdr_still_gets_real_srgb_model_view_and_keeps_original(self):
        path,pixels=self.exr();before=path.read_bytes()
        result=self.prepare({'source':self.source(path),'colour_space':'linear_rec709'})
        shown=np.array(Image.open(result['path']))
        self.assertEqual(result['resolved_colour'],'srgb_display')
        np.testing.assert_allclose(shown[0,0,:3],[118,118,118],atol=1)
        self.assertGreater(int(shown[0,0,0]),90,'Linear .18 must be colour converted, not directly quantised to46')
        self.assertEqual(shown[0,1,0],0);self.assertEqual(shown[0,1,1],255);self.assertEqual(shown[0,1,3],64)
        self.assertTrue(result['processingView']['clippedRGB']);self.assertGreater(result['processingView']['clippedSampleCount'],0)
        self.assertEqual(path.read_bytes(),before);np.testing.assert_array_equal(views._image(path),pixels)
        self.assertEqual(result['processingView']['originalSource']['path'],str(path))
        self.assertEqual(result['processingView']['originalSourceSha256'],hashlib.sha256(before).hexdigest())
        again=self.prepare({'source':self.source(path),'colour_space':'linear_rec709'})
        self.assertEqual(again['path'],result['path'],'The same input and view reuse one verified proxy')

    def test_native_sequence_selected_range_preserves_ntsc_and_source_hashes(self):
        folder=self.base/'native_sequence';folder.mkdir();before={}
        for index in range(9):
            path=folder/f'frame_{index:04}.exr'
            values=np.full((48,64,3),.02+index*.02,dtype=np.float32)
            spec=oiio.ImageSpec(64,48,3,oiio.FLOAT);spec.channelnames=['R','G','B'];spec.attribute('oiio:ColorSpace','ACEScg')
            writer=oiio.ImageOutput.create(str(path));writer.open(str(path),spec);writer.write_image(values);writer.close();before[path]=path.read_bytes()
        token=views.grant_source(folder,'acescg')
        body={'source':{'source_token':token},'colour_space':'acescg','startFrame':2,'frameCount':4,'frameRate':{'numerator':30000,'denominator':1001}}
        result=self.prepare(body)
        with av.open(result['path']) as video:
            self.assertEqual(video.streams.video[0].average_rate,Fraction(30000,1001))
            frames=[frame.to_ndarray(format='rgba') for frame in video.decode(video=0)]
        self.assertEqual(len(frames),4);self.assertTrue(all(frames[i].mean()<frames[i+1].mean() for i in range(3)))
        self.assertEqual(result['frameRate'],body['frameRate']);self.assertEqual(result['processingView']['originalStartFrame'],2)
        for path,content in before.items():self.assertEqual(path.read_bytes(),content)
        replacement=views.grant_source(folder,'acescg')
        repeated=self.prepare({**body,'source':{'source_token':replacement}})
        self.assertEqual(repeated['path'],result['path']);self.assertEqual(repeated['processingView']['originalSource']['display_source'],replacement)

    def test_float_manifest_full_precision_stays_unchanged_and_proxy_has_exact_interval(self):
        pixels=np.ones((9,48,64,4),dtype=np.float32)
        for index in range(9):pixels[index,...,:3]=.02+index*.01
        pixels[:,0,0,:]=[-.25,4.,.1234567,.33333334]
        relative,manifest=float_io.write_transfer(self.roots['output'],'ComfyLink/'+'a'*32,pixels,
            colour={'encoding':'acescg','sceneLinear':True},frame_rate={'numerator':24000,'denominator':1001})
        directory=self.roots['output']/Path(relative).parent
        before={path:path.read_bytes() for path in directory.iterdir()}
        ref={'file':{'filename':'manifest.json','subfolder':Path(relative).parent.as_posix(),'type':'output'}}
        result=self.prepare({'source':ref,'startFrame':3,'frameCount':4,'sequenceFps':24000/1001})
        with av.open(result['path']) as video:
            self.assertEqual(video.streams.video[0].average_rate,Fraction(24000,1001));self.assertEqual(sum(1 for _ in video.decode(video=0)),4)
        self.assertEqual(result['processingView']['sourceHashScope'],'source_manifest')
        for path,content in before.items():self.assertEqual(path.read_bytes(),content)
        with self.assertRaisesRegex(ValueError,'rational frame rate'):
            self.prepare({'source':ref,'frameRate':{'numerator':24,'denominator':1}})

    def test_real_hlg_and_pq_video_views_keep_selected_frames_rate_and_audio(self):
        from ComfyUI_zura_nodes.paintout.media_tools import find_media_tool
        for transfer,space in ((18,'hlg_rec2020'),(16,'pq_rec2020')):
            with self.subTest(space=space):
                rate=Fraction(30000,1001);silent=self.base/f'{space}-silent.mkv';source=self.roots['output']/f'{space}.mkv'
                with av.open(str(silent),'w') as video:
                    stream=video.add_stream('ffv1',rate=rate);stream.width=64;stream.height=48;stream.pix_fmt='gbrp16le'
                    stream.codec_context.color_primaries=9;stream.codec_context.color_trc=transfer;stream.codec_context.colorspace=0
                    for index in range(9):
                        image=np.full((48,64,3),round((.1+index*.03)*65535),dtype=np.uint16)
                        frame=av.VideoFrame.from_ndarray(image,format='rgb48le');frame.pts=index;frame.time_base=1/rate
                        for packet in stream.encode(frame):video.mux(packet)
                    for packet in stream.encode():video.mux(packet)
                subprocess.run([find_media_tool('ffmpeg'),'-v','error','-y','-i',str(silent),'-f','lavfi','-i','sine=frequency=523:sample_rate=48000',
                    '-map','0:v:0','-map','1:a:0','-t',str(float(9/rate)),'-c:v','copy','-c:a','pcm_f32le',str(source)],check=True,capture_output=True)
                before=source.read_bytes()
                result=self.prepare({'source':self.source(source),'startFrame':2,'frameCount':4,'frameRate':{'numerator':30000,'denominator':1001}})
                self.assertEqual(result['processingView']['sourceColour'],space)
                with av.open(result['path']) as video:
                    self.assertEqual(video.streams.video[0].average_rate,rate);self.assertEqual(len(video.streams.audio),1)
                    means=[frame.to_ndarray(format='rgb24').mean() for frame in video.decode(video=0)]
                self.assertEqual(len(means),4);self.assertTrue(all(means[index]<means[index+1] for index in range(3)))
                with av.open(result['path']) as audio:
                    stream=audio.streams.audio[0];self.assertEqual(stream.codec_context.name,'pcm_f32le')
                    self.assertAlmostEqual(sum(frame.samples for frame in audio.decode(audio=0))/stream.sample_rate,float(4/rate),delta=1/stream.sample_rate)
                self.assertEqual(source.read_bytes(),before)

    def test_invalid_selectors_unknown_colour_and_intervals_fail_without_model_outputs(self):
        path,_=self.exr()
        for body in ({'source':{'path':str(path)}},{'source':{'file':{'filename':'../source.exr','type':'output'}}},
                     {'source':self.source(path),'colour_space':'guess_hdr'},{'source':self.source(path),'startFrame':True},
                     {'source':self.source(path),'frameCount':2},{'source':self.source(path),'frameRate':{'numerator':24,'denominator':0}}):
            with self.subTest(body=body),self.assertRaises(ValueError):self.prepare(body)
        self.assertFalse((self.roots['input']/'zura_model_views').exists())

    def test_premultiplied_float_is_unassociated_only_in_model_copy(self):
        values=np.array([[[[.09,.09,.09,.5],[.1234567,4.,-.2,0.]]]],dtype=np.float32)
        relative,_=float_io.write_transfer(self.roots['output'],'ComfyLink/'+'c'*32,values,
            colour={'encoding':'scene_linear_rec709','sceneLinear':True},frame_rate={'numerator':24,'denominator':1},alpha_association='premultiplied')
        folder=self.roots['output']/Path(relative).parent;before={path:path.read_bytes() for path in folder.iterdir()}
        result=self.prepare({'source':{'file':{'type':'output','filename':'manifest.json','subfolder':Path(relative).parent.as_posix()}}})
        with av.open(result['path']) as video:pixels=next(video.decode(video=0)).to_ndarray(format='rgba')
        np.testing.assert_allclose(pixels[0,0,:3],[118,118,118],atol=1);self.assertEqual(pixels[0,0,3],128)
        np.testing.assert_array_equal(pixels[0,1],[0,0,0,0])
        for path,content in before.items():self.assertEqual(path.read_bytes(),content)

    def test_original_video_frame_marker_is_a_distinct_png_view(self):
        path=self.roots['output']/'frames.mkv';rate=Fraction(24)
        with av.open(str(path),'w') as video:
            stream=video.add_stream('ffv1',rate=rate);stream.width=64;stream.height=48;stream.pix_fmt='bgra'
            stream.codec_context.color_trc=13;stream.codec_context.color_primaries=1;stream.codec_context.colorspace=0
            for index in range(4):
                frame=av.VideoFrame.from_ndarray(np.full((48,64,3),index*50,np.uint8),format='rgb24');frame.pts=index;frame.time_base=1/rate
                for packet in stream.encode(frame):video.mux(packet)
            for packet in stream.encode():video.mux(packet)
        self.store=types.SimpleNamespace(load=lambda _identity:{'asset_kind':'video','file':str(path)})
        first=self.prepare({'source':{'asset_id':'a'*32,'frame_time':1/24}})
        second=self.prepare({'source':{'asset_id':'a'*32,'frame_time':2/24}})
        self.assertTrue(first['path'].endswith('.png'));self.assertNotEqual(first['path'],second['path'])
        self.assertLess(np.array(Image.open(first['path'])).mean(),np.array(Image.open(second['path'])).mean())
        self.assertEqual(first['processingView']['originalSource']['frame_time'],1/24)

    def test_cancellation_and_changed_original_leave_no_completed_proxy(self):
        path,_=self.exr();cancel=threading.Event();cancel.set()
        with self.assertRaisesRegex(ValueError,'cancelled'):self.prepare({'source':self.source(path)},cancel)
        self.assertFalse((self.roots['input']/'zura_model_views').exists())
        original_encode=model._encode
        def changed(rgba,processor,*args):
            result=original_encode(rgba,processor,*args);path.write_bytes(path.read_bytes()+b'changed');return result
        token=views.grant_source(path,'linear_rec709')
        with patch.object(model,'_encode',side_effect=changed),self.assertRaisesRegex(ValueError,'changed'):
            self.prepare({'source':{'source_token':token},'colour_space':'linear_rec709'})
        cache=self.roots['input']/'zura_model_views'
        self.assertFalse(any(cache.glob('*/view.json')));self.assertFalse(any(cache.glob('*.partial')))

    def test_tampered_proxy_is_rejected_and_unknown_cache_directories_are_preserved(self):
        path,_=self.exr();body={'source':self.source(path),'colour_space':'linear_rec709'}
        result=self.prepare(body);proxy=Path(result['path']);proxy.write_bytes(proxy.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'cached model input changed'):self.prepare(body)
        cache=self.roots['input']/'zura_model_views';unowned=cache/('b'*64);unowned.mkdir();(unowned/'important.txt').write_text('Keep this')
        with patch.object(model.time,'time',return_value=model.time.time()+2*model.CACHE_TTL):model._prune(cache)
        self.assertEqual((unowned/'important.txt').read_text(),'Keep this')

    def test_queued_model_input_is_not_pruned_and_full_cache_can_reuse_it(self):
        path,_=self.exr();body={'source':self.source(path),'colour_space':'linear_rec709'}
        result=self.prepare(body);proxy=Path(result['path']);cache=proxy.parent.parent
        queued=types.SimpleNamespace(prompt_queue=types.SimpleNamespace(get_current_queue=lambda:([{'source':str(proxy)}],[])))
        future=model.time.time()+2*model.CACHE_TTL
        with patch.object(sys.modules['server'].PromptServer,'instance',queued),patch.object(model.time,'time',return_value=future):
            model._prune(cache)
        self.assertTrue(proxy.is_file(),'An already queued model input must remain available')
        with patch.object(model,'MAX_CACHE_BYTES',1):reused=self.prepare(body)
        self.assertEqual(reused['path'],result['path'],'Reusing a verified input does not need another cache allocation')


class ModelViewHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_typed_route_uses_contained_media_and_rejects_origin_and_oversize(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);roots={kind:base/kind for kind in ('input','output','temp')}
            for path in roots.values():path.mkdir()
            source=roots['output']/'source.png';Image.fromarray(np.full((2,2,3),128,np.uint8)).save(source)
            routes=web.RouteTableDef()
            def response(handler):
                async def wrapped(request):
                    try:return await handler(request)
                    except ValueError as error:return web.json_response({'error':str(error)},status=400)
                return wrapped
            store=types.SimpleNamespace(load=lambda _identity:None)
            model.register(types.SimpleNamespace(store=store),routes,response,lambda value:value)
            app=web.Application();app.add_routes(routes)
            async with TestClient(TestServer(app)) as client:
                with patch('folder_paths.get_input_directory',return_value=str(roots['input'])),patch('folder_paths.get_output_directory',return_value=str(roots['output'])),patch('folder_paths.get_temp_directory',return_value=str(roots['temp'])):
                    body={'source':{'file':{'type':'output','filename':'source.png','subfolder':''}}}
                    result=await client.post('/zura/studio/model-view',json=body)
                    self.assertEqual(result.status,200);data=await result.json()
                    self.assertEqual(data['resolved_colour'],'srgb_display');self.assertEqual(data['inputRef']['type'],'input')
                    self.assertEqual((roots['input']/data['inputRef']['subfolder']/data['inputRef']['filename']).resolve(),Path(data['path']))
                    result=await client.post('/zura/studio/model-view',json=body,headers={'Origin':'https://other.example'})
                    self.assertEqual(result.status,403)
                    result=await client.post('/zura/studio/model-view',data=b' '*17000)
                    self.assertEqual(result.status,400)
                    result=await client.post('/zura/studio/model-view',json={'source':{'path':str(source)}})
                    self.assertEqual(result.status,400)


if __name__=='__main__':unittest.main()
