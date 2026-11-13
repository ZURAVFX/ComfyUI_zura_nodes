"""Original precision, selected-frame import and actual decoder preservation."""
from fractions import Fraction
import asyncio
import hashlib
import json
import importlib
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import uuid
import zipfile
from contextlib import ExitStack
from unittest.mock import patch
from aiohttp import web,FormData
from aiohttp.test_utils import TestClient,TestServer

import av
import numpy as np
import OpenImageIO as oiio
import torch
from PIL import Image

import v2_bootstrap
if 'server' not in sys.modules:
    stub=types.ModuleType('server');stub.PromptServer=types.SimpleNamespace(instance=None);sys.modules['server']=stub
if 'ComfyUI_zura_nodes.artist_studio' not in sys.modules:
    package=types.ModuleType('ComfyUI_zura_nodes.artist_studio');package.__path__=[str(v2_bootstrap.ROOT/'artist_studio')];sys.modules[package.__name__]=package
media=importlib.import_module('ComfyUI_zura_nodes.artist_studio.media_import')
precision=importlib.import_module('ComfyUI_zura_nodes.artist_studio.media_precision')
tools=importlib.import_module('ComfyUI_zura_nodes.paintout.media_tools')


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.base=Path(self.temporary.name)
        self.roots={key:self.base/key for key in ('input','output','temp')}
        for root in self.roots.values():root.mkdir()
        self.assets={};self.store=types.SimpleNamespace(load=lambda key:self.assets[key],save=lambda value:self.assets.update({value['id']:value}))
        self.visible=patch.object(media,'_visible',lambda asset:dict(asset));self.visible.start()
    def tearDown(self):self.visible.stop();self.temporary.cleanup()
    def asset(self,name,kind='image'):
        identity=uuid.uuid4().hex;path=self.roots['input']/'genj_studio'/identity/name;path.parent.mkdir(parents=True)
        return identity,path
    def register(self,identity,path,kind='image'):
        asset={'id':identity,'kind':'asset','asset_kind':kind,'name':path.name,
               'file':path.relative_to(self.roots['input']).as_posix(),'sha':hashlib.sha256(path.read_bytes()).hexdigest()}
        self.assets[identity]=asset;return asset
    def check(self,asset):
        path=self.roots['input']/asset['file']
        if not path.resolve().is_relative_to(self.roots['input']/'genj_studio') or hashlib.sha256(path.read_bytes()).hexdigest()!=asset['sha']:raise ValueError('Original changed')
        return path
    def exr(self,path,storage):
        rgba=np.array([[[.18,.18,.18,1],[-.25,4,.2,.25]]],dtype=np.float32)
        spec=oiio.ImageSpec(2,1,4,storage);spec.channelnames=['R','G','B','A'];spec.attribute('oiio:ColorSpace','Linear Rec.709 (sRGB)')
        writer=oiio.ImageOutput.create(str(path));self.assertTrue(writer.open(str(path),spec));self.assertTrue(writer.write_image(rgba));writer.close()
    def test_half_and_float_exr_originals_are_distinct_and_retained(self):
        for depth,storage in ((16,oiio.HALF),(32,oiio.FLOAT)):
            identity,path=self.asset(f'exr{depth}.exr');self.exr(path,storage);before=path.read_bytes();asset=self.register(identity,path)
            result=media.prepare_import({'asset_id':identity,'colour_space':'linear_rec709','frame':0},self.store,self.check,self.roots)
            self.assertEqual(result['precision']['storageBitDepth'],depth)
            self.assertIsNone(result['precision']['effectiveBitDepth'])
            self.assertEqual(result['processingInput']['precision']['sourceBitDepth'],8)
            self.assertEqual(path.read_bytes(),before)
            proxy=self.check(result['processingInput']['studioAsset']);samples=np.array(Image.open(proxy))
            self.assertEqual(samples[0,1,0],0);self.assertEqual(samples[0,1,1],255)
            self.assertEqual(samples[0,1,3],64)
            self.assertEqual(result['colour']['encoding'],'linear_rec709')
    def test_jpeg_and_webp_use_the_checked_image_path(self):
        for suffix in ('jpg','webp'):
            identity,path=self.asset('original.'+suffix);Image.fromarray(np.full((8,8,3),128,np.uint8)).save(path)
            before=path.read_bytes();asset=self.register(identity,path)
            described,_=media.describe_asset(asset,self.store,self.check,self.roots)
            self.assertEqual(described['precision']['storageBitDepth'],8)
            result=media.prepare_import({'asset_id':identity,'frame':0},self.store,self.check,self.roots)
            self.assertEqual(result['processingInput']['studioAsset']['asset_kind'],'image')
            self.assertEqual(path.read_bytes(),before)
    def test_actual_sdr_mp4_selected_frame_binding_crosses_js_adapter_and_display(self):
        identity,path=self.asset('sdr.mp4','video')
        subprocess.run([tools.find_media_tool('ffmpeg'),'-v','error','-f','lavfi','-i','testsrc=size=64x48:rate=25','-frames:v','9',
            '-c:v','libx264','-x264-params','colorprim=bt709:transfer=bt709:colormatrix=bt709','-pix_fmt','yuv420p','-color_trc','bt709','-color_primaries','bt709','-colorspace','bt709',str(path)],check=True)
        self.register(identity,path,'video');before=path.read_bytes()
        result=media.prepare_import({'asset_id':identity,'frame':7},self.store,self.check,self.roots)
        self.assertEqual(result['precision']['decodedBitDepth'],8)
        bridge=subprocess.run(['node',str(v2_bootstrap.ROOT/'tests'/'studio_import_binding_bridge.mjs')],input=json.dumps(result),capture_output=True,text=True,check=True)
        bound=json.loads(bridge.stdout);selector=bound['selector']
        self.assertEqual(selector,{'imported_frame':result['processingInput']['studioAsset']['id']})
        self.assertEqual(bound['preview']['count'],1)
        self.assertEqual(bound['config']['studioDelivery']['processingColourSpace'],'srgb_display')
        actual,space,metadata=media.display.read_original(selector,0,self.store,self.check,self.roots)
        expected,_,_=media.display.read_original({'asset_id':identity,'frame_time':7/25},0,self.store,self.check,self.roots,'rec709_oetf')
        np.testing.assert_array_equal(actual,expected);self.assertEqual(metadata['frame_count'],1)
        self.assertEqual(space,'rec709_oetf');self.assertEqual(path.read_bytes(),before)
        interval=media.prepare_import({'asset_id':identity,'startFrame':2,'frameCount':4},self.store,self.check,self.roots)
        bridge=subprocess.run(['node',str(v2_bootstrap.ROOT/'tests'/'studio_import_binding_bridge.mjs'),'ripple'],input=json.dumps(interval),capture_output=True,text=True,check=True)
        viewed=json.loads(bridge.stdout)
        self.assertEqual(viewed['selector'],{'asset_id':identity},'The video workspace must display the original instead of dropping its registered identity')
        self.assertEqual(viewed['preview']['count'],9,'Original preview covers the whole original while the model input retains its selected interval')
        proxy=result['processingInput']['studioAsset'];self.assets[proxy['id']]['originalFrame']['frameIndex']=2
        with self.assertRaisesRegex(ValueError,'binding changed'):media.display.read_original(selector,0,self.store,self.check,self.roots)
    def test_real_video_pts_rejects_irregular_clock_before_cfr_conversion(self):
        identity,path=self.asset('irregular.mkv','video')
        with av.open(str(path),'w') as output:
            stream=output.add_stream('ffv1',rate=25);stream.width=64;stream.height=48;stream.pix_fmt='bgra'
            for pts in (0,40,120):
                frame=av.VideoFrame.from_ndarray(np.full((48,64,4),128,np.uint8),format='rgba');frame.pts=pts;frame.time_base=Fraction(1,1000)
                for packet in stream.encode(frame):output.mux(packet)
            for packet in stream.encode():output.mux(packet)
        info={'path':str(path),'fps_rational':'25','width':64,'height':48}
        with self.assertRaisesRegex(ValueError,'variable frame timing'):list(media.model_view._video_frames(info,0,3,None))
    def test_media_probe_cancellation_kills_its_actual_child_process(self):
        paintout=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout');cancel=threading.Event()
        timer=threading.Timer(.15,cancel.set);timer.start();started=time.monotonic()
        try:
            with self.assertRaisesRegex(ValueError,'cancelled'):paintout._media_probe([sys.executable,'-c','import time;time.sleep(20)'],cancel)
        finally:timer.cancel()
        self.assertLess(time.monotonic()-started,3)
    def test_prores_decoder_twelve_bits_does_not_claim_encoded_twelve(self):
        identity,path=self.asset('prores.mov','video')
        subprocess.run([tools.find_media_tool('ffmpeg'),'-v','error','-f','lavfi','-i','testsrc=size=64x48:rate=25',
            '-frames:v','2','-c:v','prores_ks','-profile:v','4','-pix_fmt','yuv444p10le',
            '-color_trc','bt709','-color_primaries','bt709','-colorspace','bt709',str(path)],check=True)
        asset=self.register(identity,path,'video');before=path.read_bytes()
        described,_=media.describe_asset(asset,self.store,self.check,self.roots)
        self.assertEqual(described['precision']['decodedBitDepth'],12)
        self.assertIsNone(described['precision']['effectiveBitDepth'])
        self.assertEqual(described['frameRate'],{'numerator':25,'denominator':1})
        result=media.prepare_import({'asset_id':identity,'colour_space':'rec709_oetf','frame':1},self.store,self.check,self.roots)
        self.assertEqual(result['frameCount'],1);self.assertEqual(result['selectedStartFrame'],1)
        self.assertEqual(result['processingInput']['studioAsset']['asset_kind'],'image')
        self.assertEqual(path.read_bytes(),before)
    def test_prores_4444_original_display_retains_varying_alpha_and_hidden_rgb(self):
        identity,path=self.asset('prores_alpha.mov','video')
        pixels=np.full((2,48,64,4),128,np.uint8)
        pixels[...,0]=200;pixels[...,1]=70;pixels[...,2]=30
        pixels[0,...,3]=np.tile(np.repeat([0,32,128,255],16),(48,1))
        pixels[1,...,3]=pixels[0,...,3][:,::-1]
        subprocess.run([tools.find_media_tool('ffmpeg'),'-v','error','-f','rawvideo','-pixel_format','rgba','-video_size','64x48','-framerate','25','-i','-',
            '-c:v','prores_ks','-profile:v','4','-pix_fmt','yuva444p10le','-alpha_bits','16',
            '-color_trc','bt709','-color_primaries','bt709','-colorspace','bt709',str(path)],input=pixels.tobytes(),check=True)
        asset=self.register(identity,path,'video');before=path.read_bytes()
        described,_=media.describe_asset(asset,self.store,self.check,self.roots)
        self.assertTrue(described['precision']['hasAlpha']);self.assertEqual(described['precision']['decodedBitDepth'],12)
        self.assertIsNone(described['precision']['effectiveBitDepth'])
        prepared=media.prepare_import({'asset_id':identity,'colour_space':'rec709_oetf','frame':1},self.store,self.check,self.roots)
        selector=prepared['processingInput']['stills']['first']['processingView']['originalSource']['displaySelector']
        actual,space,metadata=media.display.read_original(selector,0,self.store,self.check,self.roots)
        np.testing.assert_allclose(actual[...,3],pixels[1,...,3]/255,atol=.005)
        self.assertGreater(float(actual[0,-1,:3].max()),.5,'RGB behind zero alpha must remain available')
        self.assertEqual(space,'rec709_oetf');self.assertFalse(metadata['opaque']);self.assertEqual(metadata['frame_count'],1)
        import io
        preview=np.array(Image.open(io.BytesIO(media.display.render_pixels(actual,space))))
        np.testing.assert_array_equal(preview[...,3],np.rint(actual[...,3]*255).astype(np.uint8))
        self.assertEqual(path.read_bytes(),before)
    def test_movie_alpha_is_not_discarded_by_float_decoder(self):
        identity,path=self.asset('rgba.mkv','video');pixels=np.full((48,64,4),100,dtype=np.uint8);pixels[...,3]=32
        with av.open(str(path),'w') as output:
            stream=output.add_stream('ffv1',rate=25);stream.width=64;stream.height=48;stream.pix_fmt='bgra';stream.codec_context.color_trc=13
            for packet in stream.encode(av.VideoFrame.from_ndarray(pixels,format='rgba')):output.mux(packet)
            for packet in stream.encode():output.mux(packet)
        self.register(identity,path,'video')
        result=media.prepare_import({'asset_id':identity,'colour_space':'srgb_display','frameCount':1},self.store,self.check,self.roots)
        with av.open(str(self.check(result['processingInput']['studioAsset']))) as output:decoded=next(output.decode(video=0)).to_ndarray(format='rgba')
        np.testing.assert_array_equal(decoded[...,3],32)
        np.testing.assert_allclose(decoded[...,:3],100,atol=1)
        proxy=result['processingInput']['studioAsset'];preview=self.roots['input']/proxy['preview_file']
        with av.open(str(preview)) as viewing:
            self.assertEqual(viewing.streams.video[0].codec_context.name,'h264')
            shown=list(viewing.decode(video=0));self.assertEqual(len(shown),1)
        self.assertEqual(Path(result['processingInput']['mediaInfo']['path']).suffix,'.mkv','A browser viewing copy never replaces a model input')
        fresh=media.restore_model_info(str(self.check(proxy)),{'sentinel':True},store=self.store,check_asset=self.check,roots=self.roots)
        self.assertEqual(fresh['processingView']['originalAssetId'],identity)
        self.assertNotEqual(fresh['media_url'],result['processingInput']['mediaInfo']['media_url'],'Reopening receives a fresh guarded playback grant')
        plain={'path':str(path),'sentinel':True}
        self.assertIs(media.restore_model_info(str(path),plain,store=self.store,check_asset=self.check,roots=self.roots),plain)
        foreign=self.base/'foreign'/'model.mkv';foreign.parent.mkdir();foreign.write_bytes(path.read_bytes())
        self.assertIs(media.restore_model_info(str(foreign),plain,store=self.store,check_asset=self.check,roots=self.roots),plain,'Foreign paths never receive registered-source metadata')
        original_file=proxy['file'];self.assets[proxy['id']].update(file=path.relative_to(self.roots['input']).as_posix(),sha=hashlib.sha256(path.read_bytes()).hexdigest())
        with self.assertRaisesRegex(ValueError,'another source'):media.restore_model_info(str(self.roots['input']/original_file),plain,store=self.store,check_asset=self.check,roots=self.roots)
    def test_mp4_hdr10_is_detected_from_actual_transfer_not_extension(self):
        identity,path=self.asset('hdr10.mp4','video')
        subprocess.run([tools.find_media_tool('ffmpeg'),'-v','error','-f','lavfi','-i','testsrc=size=64x48:rate=25',
            '-frames:v','2','-c:v','libx265','-x265-params','log-level=error:pools=1:frame-threads=1:colorprim=9:transfer=16:colormatrix=9:range=limited','-pix_fmt','yuv420p10le',
            '-color_trc','smpte2084','-color_primaries','bt2020','-colorspace','bt2020nc','-color_range','tv',str(path)],check=True)
        asset=self.register(identity,path,'video');original=path.read_bytes()
        described,_=media.describe_asset(asset,self.store,self.check,self.roots)
        self.assertEqual(described['precision']['decodedBitDepth'],10)
        self.assertEqual(described['precision']['transfer'],'smpte2084')
        self.assertEqual(described['resolved_colour'],'pq_rec2020')
        result=media.prepare_import({'asset_id':identity,'frameCount':2},self.store,self.check,self.roots)
        self.assertEqual(result['colour']['encoding'],'pq_rec2020')
        self.assertEqual(result['processingInput']['mediaInfo']['resolved_colour'],'srgb_display')
        self.assertEqual(path.read_bytes(),original)
    def test_display_p3_pq_import_uses_its_actual_ocio_space(self):
        identity,path=self.asset('p3_pq.mp4','video')
        subprocess.run([tools.find_media_tool('ffmpeg'),'-v','error','-f','lavfi','-i','testsrc=size=64x48:rate=25',
            '-frames:v','2','-c:v','libx265','-x265-params','log-level=error:pools=1:frame-threads=1:colorprim=12:transfer=16:colormatrix=1:range=limited','-pix_fmt','yuv420p10le',
            '-color_trc','smpte2084','-color_primaries','smpte432','-colorspace','bt709','-color_range','tv',str(path)],check=True)
        asset=self.register(identity,path,'video');before=path.read_bytes()
        described,_=media.describe_asset(asset,self.store,self.check,self.roots)
        self.assertEqual(described['resolved_colour'],'pq_display_p3')
        view=media.prepare_import({'asset_id':identity,'colour_space':'pq_display_p3','frameCount':2},self.store,self.check,self.roots)
        self.assertEqual(view['colour']['encoding'],'pq_display_p3')
        self.assertEqual(view['processingInput']['mediaInfo']['resolved_colour'],'srgb_display')
        original_alpha=importlib.import_module('ComfyUI_zura_nodes.artist_studio.alpha_original')
        samples=np.array([[[.3,.5,.7]]],np.float32);expected=samples.copy()
        from ComfyUI_zura_nodes.comfylink import display_view
        config=display_view._config(display_view.describe()['config']);config.getProcessor('ST2084-P3-D65 - Display','ACEScg').getDefaultCPUProcessor().applyRGB(expected)
        original_alpha._processor('pq_display_p3').applyRGB(samples)
        np.testing.assert_array_equal(samples,expected);self.assertEqual(path.read_bytes(),before)
    def test_sdr_transfer_transform_is_not_an_hdr_display_view(self):
        processor,description=media.model_view._processor('srgb_display')
        rgba=np.array([[[.18,.5,.9,.5]]],dtype=np.float32)
        result,_=media.model_view._encode(rgba,processor)
        self.assertEqual(description['transform'],'colourspace')
        np.testing.assert_array_equal(result,np.rint(rgba*255).astype(np.uint8))
    def test_cancelled_import_and_changed_original_do_not_publish_an_input(self):
        identity,path=self.asset('cancel.png');Image.fromarray(np.full((4,4,3),100,np.uint8)).save(path);self.register(identity,path)
        cancel=threading.Event();cancel.set()
        with self.assertRaisesRegex(ValueError,'cancelled'):media.prepare_import({'asset_id':identity},self.store,self.check,self.roots,cancel)
        self.assertEqual(list(self.assets),[identity])
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'Original changed'):media.prepare_import({'asset_id':identity},self.store,self.check,self.roots)
        self.assertEqual(list(self.assets),[identity])
    def test_original_hdr_alpha_reattachment_n1_n9_keeps_hidden_rgb_and_float_mask(self):
        original_alpha=importlib.import_module('ComfyUI_zura_nodes.artist_studio.alpha_original')
        for n in (1,9):
            identity,manifest=self.asset(f'alpha{n}.json');manifest=manifest.with_name('hdr_sequence.json');frames=manifest.parent/'frames';frames.mkdir()
            entries=[];before={};rgba=np.empty((48,64,4),dtype=np.float32);rgba[...,:3]=[-.003,.18,2];rgba[...,3]=.31415927;rgba[0,0,3]=0
            for index in range(n):
                path=frames/f'{index:06d}.exr';spec=oiio.ImageSpec(64,48,4,oiio.FLOAT);spec.channelnames=['R','G','B','A'];spec.attribute('oiio:ColorSpace','ACEScg')
                writer=oiio.ImageOutput.create(str(path));writer.open(str(path),spec);writer.write_image(rgba);writer.close();before[path]=path.read_bytes()
                entries.append({'name':path.name,'sha256':hashlib.sha256(before[path]).hexdigest()})
            manifest.write_text(json.dumps({'frames':entries}));asset=self.register(identity,manifest,'hdr_sequence')
            with patch('folder_paths.get_input_directory',return_value=str(self.roots['input'])):
                source=media.prepare_import({'asset_id':identity,'colour_space':'acescg','frameRate':{'numerator':30000,'denominator':1001}},self.store,self.check,self.roots)
                proxy=source['processingInput']['studioAsset'];info={'source_path':str(self.check(proxy)),'width':64,'height':48,
                    'start_frame':0,'frame_count':n,'fps_rational':'30000/1001','content_width':64,'content_height':48}
                binding=original_alpha.bind_original(json.dumps({'asset_id':identity,'proxy_id':proxy['id']}),info,self.store,self.check,self.roots)
                images=torch.full((9,64,64,3),.1234567,dtype=torch.float32)
                alpha,master=original_alpha.write_original_alpha(binding,images,info,self.store,self.check,self.roots,self.roots['output'])
                archive=self.roots['output']/master['subfolder']/master['filename']
                with zipfile.ZipFile(archive) as output:
                    proof=json.loads(output.read('zura_hdr_delivery.json'));self.assertEqual(proof['frameCount'],n);self.assertEqual(proof['frameRate'],{'numerator':30000,'denominator':1001})
                    path=self.base/f'checked_{n}.exr';path.write_bytes(output.read('frame_00000.exr'))
                    decoded=media.display._image(path);np.testing.assert_array_equal(decoded[...,:3],rgba[...,:3])
                    mask=images[0,:48].mean(-1).numpy();np.testing.assert_array_equal(decoded[...,3],rgba[...,3]*mask)
                for path,payload in before.items():self.assertEqual(path.read_bytes(),payload)
                if n==1:
                    alpha_nodes=importlib.import_module('ComfyUI_zura_nodes.artist_studio.alpha_video')
                    studio_stub=types.ModuleType('ComfyUI_zura_nodes.artist_studio.studio');studio_stub.Store=lambda:self.store;studio_stub.check_asset=self.check
                    with patch.dict(sys.modules,{'ComfyUI_zura_nodes.artist_studio.studio':studio_stub}),patch('folder_paths.get_output_directory',return_value=str(self.roots['output'])),patch('folder_paths.get_temp_directory',return_value=str(self.roots['temp'])),patch.object(alpha_nodes,'_tool',tools.find_media_tool):
                        prepared=alpha_nodes.ZuraAlphaVideoInput().prepare(str(self.check(proxy)),0,1,1,original_source=json.dumps({'asset_id':identity,'proxy_id':proxy['id']}))
                        self.assertEqual(prepared[1]['original_hdr'],binding)
                        returned=alpha_nodes.ZuraAlphaVideoOutput().save(images,prepared[1],'alpha_full_node')
                        native=next(item for item in returned['ui']['files'] if item['role']=='native_hdr')
                        with zipfile.ZipFile(self.roots['output']/native['subfolder']/native['filename']) as emitted:
                            self.assertEqual(json.loads(emitted.read('zura_hdr_delivery.json'))['frameCount'],1)
                with patch.object(original_alpha,'_processor',side_effect=ValueError('conversion unavailable')):
                    with self.assertRaisesRegex(ValueError,'conversion unavailable'):
                        original_alpha.write_original_alpha(binding,images,info,self.store,self.check,self.roots,self.roots['output'])
                published_before=set((self.roots['output']/'genj'/'hdr').iterdir())
                alpha_before=set((self.roots['output']/'genj'/'alpha').iterdir())
                def stopped():raise RuntimeError('cancel requested')
                with self.assertRaisesRegex(RuntimeError,'cancel requested'):
                    original_alpha.write_original_alpha(binding,images,info,self.store,self.check,self.roots,self.roots['output'],check_cancelled=stopped)
                self.assertEqual(set((self.roots['output']/'genj'/'hdr').iterdir()),published_before)
                self.assertEqual(set((self.roots['output']/'genj'/'alpha').iterdir()),alpha_before)
                first_path=next(iter(before));first_path.write_bytes(b'changed original')
                with self.assertRaisesRegex(ValueError,'EXR frame changed'):
                    original_alpha.write_original_alpha(binding,images,info,self.store,self.check,self.roots,self.roots['output'])
                self.assertEqual(set((self.roots['output']/'genj'/'hdr').iterdir()),published_before)


class ImportHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_container_uploads_and_float_sequence_selected_frame(self):
        fixture=ImportTests();fixture.setUp()
        try:
            routes=web.RouteTableDef()
            def response(handler):
                async def wrapped(request):
                    try:return await handler(request)
                    except (ValueError,KeyError,TypeError) as error:return web.json_response({'error':str(error)},status=400)
                return wrapped
            studio=types.SimpleNamespace(store=fixture.store)
            media.register(studio,routes,response,fixture.check)
            sequence=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_sequence');sequence.register(studio,routes,response)
            app=web.Application();app.add_routes(routes)
            with ExitStack() as stack:
                for kind in fixture.roots:stack.enter_context(patch('folder_paths.get_'+kind+'_directory',return_value=str(fixture.roots[kind])))
                async with TestClient(TestServer(app)) as client:
                    for suffix in ('jpg','webp','mp4','mov'):
                        path=fixture.base/('original.'+suffix)
                        if suffix in ('jpg','webp'):Image.fromarray(np.full((48,64,3),128,np.uint8)).save(path)
                        else:
                            codec=['-c:v','libx264','-x264-params','colorprim=bt709:transfer=bt709:colormatrix=bt709','-pix_fmt','yuv420p'] if suffix=='mp4' else ['-c:v','prores_ks','-profile:v','4','-pix_fmt','yuv444p10le']
                            subprocess.run([tools.find_media_tool('ffmpeg'),'-v','error','-f','lavfi','-i','testsrc=size=64x48:rate=25','-frames:v','3',*codec,'-color_trc','bt709','-color_primaries','bt709','-colorspace','bt709',str(path)],check=True)
                        form=FormData();form.add_field('file',path.read_bytes(),filename=path.name)
                        response_value=await client.post('/zura/studio/media-import/upload',data=form);self.assertEqual(response_value.status,200,await response_value.text())
                        uploaded=await response_value.json();identity=uploaded['asset']['id']
                        response_value=await client.post('/zura/studio/media-import/prepare',json={'asset_id':identity,'colour_space':'rec709_oetf' if suffix in ('mp4','mov') else 'srgb_display','frame':1 if suffix in ('mp4','mov') else 0})
                        self.assertEqual(response_value.status,200,await response_value.text());prepared=await response_value.json()
                        self.assertEqual(fixture.check(fixture.assets[identity]).read_bytes(),path.read_bytes())
                        self.assertEqual(prepared['processingInput']['precision']['sourceBitDepth'],8)
                        if suffix=='mov':self.assertEqual(prepared['precision']['decodedBitDepth'],12);self.assertIsNone(prepared['precision']['effectiveBitDepth'])
                    form=FormData();originals={}
                    for index in range(3):
                        path=fixture.base/f'frame_{index:04d}.exr';fixture.exr(path,oiio.FLOAT);originals[path.name]=path.read_bytes();form.add_field('frames',path.read_bytes(),filename=path.name)
                    response_value=await client.post('/zura/studio/hdr/exr-sequence',data=form);self.assertEqual(response_value.status,200,await response_value.text())
                    identity=(await response_value.json())['id']
                    response_value=await client.post('/zura/studio/media-import/describe',json={'asset_id':identity});self.assertEqual(response_value.status,200,await response_value.text())
                    self.assertEqual((await response_value.json())['asset']['precision']['storageBitDepth'],32)
                    response_value=await client.post('/zura/studio/media-import/prepare',json={'asset_id':identity,'colour_space':'linear_rec709','frame':2,'frameRate':{'numerator':30000,'denominator':1001}})
                    self.assertEqual(response_value.status,200,await response_value.text());prepared=await response_value.json()
                    selector=prepared['processingInput']['stills']['first']['processingView']['originalSource']['displaySelector']
                    pixels,space,metadata=media.display.read_original(selector,0,fixture.store,fixture.check,fixture.roots)
                    np.testing.assert_array_equal(pixels,media.display._image(fixture.base/'frame_0002.exr'))
                    self.assertEqual(metadata['frame_count'],1);self.assertEqual(space,'linear_rec709')
                    stored=fixture.check(fixture.assets[identity]).parent/'frames'
                    for name,payload in originals.items():self.assertEqual((stored/name).read_bytes(),payload)
        finally:fixture.tearDown()
    async def test_disconnection_cancels_worker_probe_before_publication(self):
        cancel=threading.Event();transport=types.SimpleNamespace(is_closing=lambda:False)
        request=types.SimpleNamespace(transport=transport)
        paintout=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')
        started=time.monotonic()
        worker=asyncio.create_task(media._request_work(request,lambda:paintout._media_probe([sys.executable,'-c','import time;time.sleep(20)'],cancel),cancel))
        await asyncio.sleep(.15);request.transport=None
        with self.assertRaisesRegex(ValueError,'cancelled'):await worker
        self.assertTrue(cancel.is_set());self.assertLess(time.monotonic()-started,3)
    async def test_guarded_upload_prepare_origin_size_and_no_path_selectors(self):
        fixture=ImportTests();fixture.setUp()
        try:
            routes=web.RouteTableDef()
            def response(handler):
                async def wrapped(request):
                    try:return await handler(request)
                    except (ValueError,KeyError,TypeError) as error:return web.json_response({'error':str(error)},status=400)
                return wrapped
            media.register(types.SimpleNamespace(store=fixture.store),routes,response,fixture.check)
            app=web.Application();app.add_routes(routes)
            with patch('folder_paths.get_input_directory',return_value=str(fixture.roots['input'])),patch('folder_paths.get_output_directory',return_value=str(fixture.roots['output'])),patch('folder_paths.get_temp_directory',return_value=str(fixture.roots['temp'])):
                async with TestClient(TestServer(app)) as client:
                    original=fixture.base/'original.png';Image.fromarray(np.full((4,4,3),128,np.uint8)).save(original)
                    def form():
                        value=FormData();value.add_field('file',original.read_bytes(),filename='original.png',content_type='image/png');return value
                    uploaded=await client.post('/zura/studio/media-import/upload',data=form());self.assertEqual(uploaded.status,200,await uploaded.text())
                    data=await uploaded.json();identity=data['asset']['id'];self.assertEqual(data['asset']['precision']['storageBitDepth'],8)
                    result=await client.post('/zura/studio/media-import/prepare',json={'asset_id':identity,'frame':0});self.assertEqual(result.status,200,await result.text())
                    imported=await result.json();self.assertNotEqual(imported['processingInput']['studioAsset']['id'],identity)
                    self.assertEqual(fixture.check(fixture.assets[identity]).read_bytes(),original.read_bytes())
                    forbidden=await client.post('/zura/studio/media-import/prepare',json={'asset_id':identity},headers={'Origin':'https://elsewhere.example'});self.assertEqual(forbidden.status,403)
                    invalid=await client.post('/zura/studio/media-import/prepare',json={'source':{'path':str(original)}});self.assertEqual(invalid.status,400)
                    oversized=await client.post('/zura/studio/media-import/prepare',data=b' '*17000);self.assertIn(oversized.status,(400,413))
                    with patch.object(media,'MAX_UPLOAD_BYTES',1):
                        failed=await client.post('/zura/studio/media-import/upload',data=form());self.assertEqual(failed.status,400)
                    self.assertEqual(len(fixture.assets),2,'Rejected uploads must not create asset records')
                    self.assertEqual(len(list((fixture.roots['input']/'genj_studio').iterdir())),2,'Rejected uploads must remove only their fresh directory')
        finally:fixture.tearDown()


if __name__=='__main__':unittest.main()
