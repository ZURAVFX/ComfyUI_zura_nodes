"""Real OCIO model-copy tests. No GPU, live server or AE process."""
import copy, hashlib, io, json, sys, tempfile, time, types, unittest
from pathlib import Path
import numpy as np
import PyOpenColorIO as ocio
from PIL import Image
from aiohttp import web
from aiohttp.test_utils import TestServer

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from comfylink import float_io, display_view
from comfylink.studio_processing import validate_processing_input, model_input_processor, encode_sdr8
from comfylink.studio_sessions import StudioSessions

ADOBE=Path('C:/Program Files/Adobe/Adobe After Effects 2026/Support Files/OpenColorIO-Configs/ACES 1.2/config.ocio')
SPACES={'acescg':'ACES - ACEScg','acescct':'ACES - ACEScct','scene_linear_rec709':'Utility - Linear - sRGB'}

def identity(encoding):
    return {'encoding':'unknown','sceneLinear':False,'management':'ocio','ocioConfig':'ACES 1.2',
            'ocioConfigPath':str(ADOBE),'ocioConfigFileSha256':hashlib.sha256(ADOBE.read_bytes()).hexdigest(),
            'ocioWorkingSpace':SPACES[encoding],'ocioConfigHandleSha256':'a'*64,'ocioWorkingSpaceHandleSha256':'b'*64}

def authority(manifest,encoding):
    return {'schemaVersion':1,'precision':8,'conversion':'verified_ocio_to_sdr8','sourceEncoding':encoding,
            'sourceManifestSha256':hashlib.sha256(float_io.canonical_manifest_bytes(manifest)).hexdigest(),
            'sourceColour':copy.deepcopy(manifest['colour']),'sourceConfigSha256':manifest['colour']['ocioConfigFileSha256'],
            'colour':{'encoding':'unknown','sceneLinear':False},'alphaAssociation':'straight'}


@unittest.skipUnless(ADOBE.is_file(),'Installed Adobe config needed for native colour authority')
class ProcessingTests(unittest.TestCase):
    def test_canonical_linear_and_log_sources_convert_before_model_clipping(self):
        config=display_view._config(display_view.DEFAULT_CONFIG)
        linear=np.repeat(np.array([0,.18,1,4,-.25],dtype=np.float32)[None,:,None],3,axis=-1)
        for encoding in SPACES:
            with self.subTest(encoding=encoding),tempfile.TemporaryDirectory() as folder:
                rgb=linear.copy()
                config.getProcessor(display_view._source(config,{'encoding':'scene_linear_rec709'},32),
                    display_view._source(config,{'encoding':encoding},32)).getDefaultCPUProcessor().applyRGB(rgb)
                rgba=np.concatenate((rgb,np.array([0,.1234567,.5,.75,1],dtype=np.float32)[None,:,None]),axis=-1)
                original=rgba.copy()
                _,manifest=float_io.write_transfer(Path(folder),'ComfyLink/'+'c'*32,rgba[None],colour=identity(encoding),frame_rate={'numerator':24,'denominator':1})
                declared=authority(manifest,encoding);validate_processing_input(declared,manifest)
                actual=encode_sdr8(rgba,derived=True,processor=model_input_processor(declared))
                np.testing.assert_array_equal(rgba.view(np.uint32),original.view(np.uint32))
                np.testing.assert_allclose(actual[0,:,0],[0,118,255,255,0],atol=1)
                np.testing.assert_array_equal(actual[...,3],np.rint(original[...,3]*255).astype(np.uint8))
                self.assertGreater(np.max(original[...,:3]),1 if encoding!='acescct' else .5)
                for patch in ({'sourceEncoding':'acescg' if encoding!='acescg' else 'acescct'},
                              {'sourceConfigSha256':'0'*64},{'sourceManifestSha256':'0'*64}):
                    with self.assertRaises(ValueError):validate_processing_input({**declared,**patch},manifest)
                bad=copy.deepcopy(declared);bad['sourceColour']['ocioWorkingSpace']='Utility - Raw'
                with self.assertRaises(ValueError):validate_processing_input(bad,manifest)

    def test_display_srgb_keeps_existing_codes_and_authority(self):
        rgba=np.array([[[.18,1.25,-.25,.1234567]]],dtype=np.float32)
        np.testing.assert_array_equal(encode_sdr8(rgba,derived=True),[[[46,255,0,31]]])

    def test_family_qualified_sdk_names_resolve_without_guessing(self):
        for encoding in SPACES:
            colour=identity(encoding)
            family='Utility' if encoding=='scene_linear_rec709' else 'ACES'
            colour['ocioWorkingSpace']=family+'/'+colour['ocioWorkingSpace']
            self.assertEqual(display_view._verified_ocio_source(colour),encoding)
            colour['ocioWorkingSpace']='Wrong/'+SPACES[encoding]
            with self.assertRaises(ValueError):display_view._verified_ocio_source(colour)


@unittest.skipUnless(ADOBE.is_file(),'Installed Adobe config needed')
class NativeUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_linear_video_keeps_original_frames_and_exact_model_cadence(self):
        self.frame_count=3
        await self.test_sdr_model_asset_and_original_hdr_asset_are_distinct()

    async def test_sdr_model_asset_and_original_hdr_asset_are_distinct(self):
        import OpenImageIO as oiio
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);inputs=root/'input';outputs=root/'output';inputs.mkdir();outputs.mkdir()
            rgba=np.array([[[[-.25,.18,4,.1234567],[1,1,1,0]]]],dtype=np.float32)
            count=getattr(self,'frame_count',1);rgba=np.repeat(rgba,count,axis=0)
            relative,manifest=float_io.write_transfer(inputs,'ComfyLink/'+'f'*32,rgba,colour=identity('acescg'),frame_rate={'numerator':25,'denominator':1})
            directory=inputs/Path(relative).parent
            original={p.name:p.read_bytes() for p in directory.iterdir()}
            float_io._exclusive_write(directory/'processing-input.json',float_io.canonical_manifest_bytes(authority(manifest,'acescg')))
            received={}
            async def upload_sdr(request):
                part=await (await request.multipart()).next();data=await part.read()
                if count==1:received['sdr']=np.array(Image.open(io.BytesIO(data)))
                else:
                    import av
                    with av.open(io.BytesIO(data)) as media:
                        self.assertEqual(media.streams.video[0].average_rate,25)
                        frames=list(media.decode(video=0));self.assertEqual(len(frames),count)
                        self.assertEqual([float(frame.pts*frame.time_base) for frame in frames],[0,.04,.08])
                        received['sdr']=frames[0].to_ndarray(format='rgba')
                return web.json_response({'id':'e'*32,'kind':'asset','asset_kind':'image' if count==1 else 'video','file':'model.png' if count==1 else 'model.mkv'})
            native_colour={'encoding':'acescg','sceneLinear':True,'source':'verified_ae_ocio',
                'sourceColourSha256':hashlib.sha256(float_io.canonical_manifest_bytes(manifest['colour'])).hexdigest(),
                'ocioConfigFileSha256':manifest['colour']['ocioConfigFileSha256']}
            async def upload_hdr(request):
                reader=await request.multipart();values=[]
                while (part:=await reader.next()) is not None:
                    data=await part.read();path=root/('uploaded-'+str(len(values))+'.exr');path.write_bytes(data)
                    values.append(np.asarray(oiio.ImageBuf(str(path)).get_pixels(oiio.FLOAT),dtype=np.float32))
                received['hdr']=np.stack(values)
                return web.json_response({'id':'d'*32,'kind':'asset','asset_kind':'hdr_sequence','file':'original.exr',
                    'nativeInputColour':native_colour,'resolved_colour':'acescg'})
            app=web.Application();app.router.add_post('/zura/studio/upload',upload_sdr);app.router.add_post('/zura/studio/hdr/exr-sequence',upload_hdr)
            server=TestServer(app,host='127.0.0.1');await server.start_server()
            try:
                # Build the same importer boundary without a Comfy process.
                service=object.__new__(StudioSessions)
                service.roots=lambda:(inputs,outputs);service.check_stream_memory=lambda _:None
                session=types.SimpleNamespace(id='f'*32,origin=str(server.make_url('/')).rstrip('/'),closed=False,expires=time.time()+600)
                service.sessions={session.id:session}
                imported=await service.native_import(session,directory,manifest)
                self.assertEqual(imported['studioAsset']['id'],'d'*32)
                self.assertEqual(imported['processingInput']['studioAsset']['id'],'e'*32)
                self.assertEqual(imported['processingInput']['stills']['first']['width'],2)
                np.testing.assert_array_equal(received['hdr'],rgba)
                self.assertEqual(received['sdr'].dtype,np.uint8)
                self.assertEqual(received['sdr'][0,0,0],0)
                for name,data in original.items():self.assertEqual((directory/name).read_bytes(),data)
            finally:await server.close()


if __name__=='__main__':unittest.main()
