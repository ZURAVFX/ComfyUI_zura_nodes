"""CPU media/pixel proof: HDR RGB conversion never quantises retained alpha."""
import hashlib,importlib,json,shutil,subprocess,sys,tempfile,types,unittest,zipfile
from fractions import Fraction
from pathlib import Path

import numpy as np
import torch
from PIL import Image
import v2_bootstrap

for name,folder in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/folder)];sys.modules[name]=package
matte=importlib.import_module('ComfyUI_zura_nodes.artist_studio.alpha_matte')
alpha=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_alpha')
chunks=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunks')
storage=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_store')
export=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_exr')
paintout=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')

class HDRAlphaDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.rate=Fraction(30000,1001)
    def source(self,count=9):
        values=np.array([[.1234567,.31415927],[0,1]],dtype=np.float32)
        writer=matte.AlphaFloatWriter(self.root,{'width':2,'height':2,'frame_count':count,'start_frame':4,'fps_rational':str(self.rate)})
        for index in range(count):writer.write(index,values)
        reference=writer.finish()
        source=alpha.HDRAlphaSource(self.root,reference,width=2,height=2,count=count,frame_rate=self.rate)
        return source,values,reference
    def staged(self,count,identity='a'):
        stage=storage.HDRChunkStore(self.root/'staging',identity*32,[chunks.HDRChunk(0,count,0)],2,2,create=True)
        rgb=torch.tensor([-.003,.18,2.0]).reshape(1,1,1,3).expand(count,2,2,3).clone();stage.write(0,paintout.encode_ct(rgb));return stage
    def test_float_artifact_and_rgba_hdr_exr_keep_fractional_alpha_at_n1_and_n9(self):
        import OpenImageIO as oiio
        for count in (1,9):
            source,values,reference=self.source(count);stage=self.staged(count,'a' if count==1 else 'b')
            path=export.export_rgba_exr_zip(stage,self.root,'rgba_'+str(count),alpha_source=source,frame_rate=self.rate)
            with zipfile.ZipFile(path) as archive:
                proof=json.loads(archive.read('zura_hdr_delivery.json'));self.assertEqual(proof['kind'],'rgba_hdr');self.assertEqual(proof['alphaAssociation'],'straight')
                self.assertEqual(proof['frameCount'],count);self.assertEqual(proof['frameRate'],{'numerator':30000,'denominator':1001});self.assertEqual(proof['alphaSource']['kind'],'alpha_float32')
                self.assertEqual(proof['sourceStart'],{'numerator':4004,'denominator':30000});self.assertEqual(len(proof['frames']),count)
                for entry in proof['frames']:
                    data=archive.read(entry['filename']);self.assertEqual(hashlib.sha256(data).hexdigest(),entry['sha256']);self.assertEqual(entry['alphaSha256'],alpha.alpha_hash(values))
                    frame=self.root/'check.exr';frame.write_bytes(data);image=oiio.ImageInput.open(str(frame))
                    try:
                        spec=image.spec();rgba=np.asarray(image.read_image(format=oiio.FLOAT));self.assertEqual(list(spec.channelnames),['R','G','B','A']);self.assertEqual(spec.get_string_attribute('comfylink:alphaAssociation'),'straight')
                        self.assertEqual(str(spec.format),'float')
                        np.testing.assert_array_equal(rgba[...,3].view(np.uint32),values.view(np.uint32));np.testing.assert_allclose(rgba[...,:3],np.broadcast_to([-.003,.18,2.0],rgba[...,:3].shape),atol=1e-5)
                        self.assertGreater(float(rgba[1,0,2]),1,'Hidden RGB under zero alpha is retained')
                    finally:image.close()
                self.assertFalse(any(name.endswith('.exr.json') for name in archive.namelist()))
            self.assertNotEqual(values[0,0],np.float32(round(float(values[0,0])*65535)/65535),'The test matte is not on the PNG16 grid')
            with self.assertRaisesRegex(ValueError,'already exists'):export.export_rgba_exr_zip(stage,self.root,'rgba_'+str(count),alpha_source=source,frame_rate=self.rate)
    def test_transparent_image_alpha_is_copied_and_not_used_as_rgb(self):
        rgba=np.zeros((2,2,4),dtype=np.uint8);rgba[...,:3]=[240,128,10];rgba[...,3]=[[0,64],[128,255]]
        path=self.root/'transparent.png';Image.fromarray(rgba).save(path)
        source=alpha.HDRAlphaSource(self.root,{'filename':path.name,'type':'output'},width=2,height=2,count=1,frame_rate=25,image=True)
        expected=rgba[...,3].astype(np.float32)/np.float32(255)
        np.testing.assert_array_equal(next(source.frames()).view(np.uint32),expected.view(np.uint32))
        decoded,_=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_source').load_sdr_frames(str(path),0,1,'srgb_display',25)
        np.testing.assert_allclose(decoded[0,0,0].numpy(),rgba[0,0,:3]/255,atol=2e-7)
    def test_changes_wrong_clock_nonfinite_or_out_of_range_alpha_reject_before_publish(self):
        source,_,reference=self.source(1)
        for change in ({'count':2},{'width':3},{'frame_rate':25}):
            with self.assertRaises(ValueError):alpha.HDRAlphaSource(self.root,reference,**({'width':2,'height':2,'count':1,'frame_rate':self.rate}|change))
        entry=source.manifest['frames'][0];frame=source.path.parent/entry['filename'];frame.write_bytes(np.ones((2,2),dtype='<f4').tobytes())
        stage=self.staged(1)
        with self.assertRaisesRegex(ValueError,'changed'):export.export_rgba_exr_zip(stage,self.root,'changed',alpha_source=source,frame_rate=self.rate)
        self.assertFalse((self.root/'genj/hdr/changed.zip').exists())
        writer=matte.AlphaFloatWriter(self.root,{'width':2,'height':2,'frame_count':1,'start_frame':0,'fps_rational':'25'})
        for value in (float('nan'),-0.1,1.1):
            with self.assertRaises(ValueError):writer.write(0,np.full((2,2),value,dtype=np.float32))
        writer.abort()
    def test_cancellation_removes_only_new_archive_and_keeps_source(self):
        source,_,_=self.source(9);stage=self.staged(9)
        def stop(done,total):
            if done==3:stage.cancel()
        with self.assertRaises(storage.HDRChunkCancelled):export.export_rgba_exr_zip(stage,self.root,'cancelled',alpha_source=source,frame_rate=self.rate,progress=stop)
        self.assertFalse((self.root/'genj/hdr/cancelled.zip').exists());self.assertTrue(source.path.exists())
    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_final_alpha_multiplies_existing_source_opacity_in_float(self):
        original=np.zeros((1,2,2,4),dtype=np.uint8);original[...,:3]=120;original[...,3]=[[[0,128],[255,64]]]
        path=self.root/'source.mkv'
        subprocess.run(['ffmpeg','-v','error','-f','rawvideo','-pixel_format','rgba','-video_size','2x2','-framerate','25','-i','pipe:0','-frames:v','1','-c:v','ffv1','-pix_fmt','bgra',str(path)],input=original.tobytes(),check=True,capture_output=True)
        info={'frame_count':1,'width':2,'height':2,'content_width':2,'content_height':2,'start_frame':0,'pixel_format':'bgra'}
        images=torch.full((1,2,2,3),.31415927,dtype=torch.float32)
        actual=next(matte.final_alpha_frames(images,info,path,'ffmpeg'))
        np.testing.assert_allclose(actual,(original[0,...,3].astype(np.float32)/255)*np.float32(.31415927),atol=1e-7)
