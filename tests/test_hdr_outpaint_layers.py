"""Real EXR layer round trips for HDR frame-extension manual compositing."""
import importlib
import io
import json
import sys
import tempfile
import threading
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import OpenImageIO as oiio
import torch
import v2_bootstrap

for name, folder in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),
                     ('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/folder)];sys.modules[name]=package
layers=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_layers')
colour=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


def write_rgb(path, values):
    h,w=values.shape[:2]
    spec=oiio.ImageSpec(w,h,3,oiio.FLOAT);spec.channelnames=('R','G','B')
    out=oiio.ImageOutput.create(str(path));assert out and out.open(str(path),spec)
    try: assert out.write_image(np.ascontiguousarray(values.astype(np.float32)))
    finally:out.close()


def read_rgba(path):
    config=oiio.ImageSpec();config.attribute('oiio:UnassociatedAlpha',1)
    inp=oiio.ImageInput.open(str(path),config)
    if not inp:raise RuntimeError('Could not open layer EXR')
    try:return inp.read_image(format=oiio.FLOAT),inp.spec().get_string_attribute('oiio:ColorSpace')
    finally:inp.close()


class LayerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source.mp4';self.source.write_bytes(b'test')
        self.master=self.root/'master.zip'
        self.selection={'width':64,'height':64,'frames':3,'left':16,'right':16,'top':16,'bottom':16,
                        'mode':'expand','start':.25,'colour_space':'pq_rec2020','black_threshold':.01,
                        'requested_duration':3/24}
        self.scene=np.empty((64,64,3),np.float32);self.scene[:]=[3.,-.002,1.5]
        raw=self.root/'frame.exr';write_rgb(raw,self.scene)
        with zipfile.ZipFile(self.master,'w') as archive:
            for i in range(9):archive.write(raw,f'frame_{i:05d}.exr')
        self.decoder=patch.object(layers,'_native_frame_stream',side_effect=self._decode);self.decode_mock=self.decoder.start();self.addCleanup(self.decoder.stop)
        self.describe=patch.object(colour,'describe',return_value={'width':32,'height':32,'kind':'video'});self.describe.start();self.addCleanup(self.describe.stop)

    def _decode(self,path,selection,info,directory,cancelled):
        for n in range(selection['frames']):
            yield colour.encode_ct(torch.tensor([.25*(n+1),-.002,2.]).expand(1,32,32,3))

    def export(self,prefix='test',**kwargs):
        return layers.export_hdr_outpaint_layers(self.master,self.source,self.selection,self.root,prefix,**kwargs)

    def frame(self,archive,name):
        target=self.root/'read.exr';target.write_bytes(archive.read(name));return read_rgba(target)[0]

    def test_real_exrs_preserve_hdr_source_and_provide_straight_border_and_matte(self):
        from PIL import Image
        output=self.export()
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(len(archive.namelist()),29)
            meta=json.loads(archive.read('manifest.json'))
            self.assertEqual((meta['source_frames'],meta['delivered_frames'],meta['held_tail_frames']),(3,9,6))
            self.assertEqual(meta['alpha'],'straight / unassociated')
            plate=self.frame(archive,'original_plate/frame_00000.exr')
            border=self.frame(archive,'generated_border/frame_00000.exr')
            self.assertEqual((plate.shape,border.shape),((64,64,4),(64,64,4)))
            np.testing.assert_allclose(plate[32,32,:3],[.25,-.002,2.],atol=1e-5)
            self.assertEqual((float(plate[32,32,3]),float(plate[0,0,3])),(1.,0.))
            self.assertEqual((float(border[0,0,3]),float(border[32,32,3])),(1.,0.))
            self.assertGreater(float(border[16,32,3]),.9)
            self.assertTrue(0<float(border[24,32,3])<1)
            # Straight alpha retains RGB even in feathered pixels, including
            # negative AP1 components and values well above display white.
            np.testing.assert_allclose(border[24,32,:3],self.scene[24,32],rtol=0,atol=1e-6)
            matte=self.root/'matte.png';matte.write_bytes(archive.read('border_matte/frame_00000.png'))
            self.assertAlmostEqual(np.asarray(Image.open(matte))[24,32]/65535.,float(border[24,32,3]),places=4)
            second=self.frame(archive,'original_plate/frame_00002.exr')
            last=self.frame(archive,'original_plate/frame_00008.exr')
            np.testing.assert_array_equal(second,last)
            self.assertAlmostEqual(float(last[32,32,0]),.75,places=5)
            self.assertIn('raw model pixels',archive.read('README.txt').decode())

    def test_black_selection_tracks_each_source_frame_and_held_tail(self):
        self.selection.update(mode='black',left=0,top=0,right=0,bottom=0)
        self.describe.return_value={'width':64,'height':64,'kind':'video'}
        def decode(path,selection,info,directory,cancelled):
            for n in range(selection['frames']):
                result=torch.ones((1,64,64,3))*2;result[0,0:4,n*4:n*4+4]=0
                yield colour.encode_ct(result)
        self.decoder.stop()
        with patch.object(layers,'_native_frame_stream',side_effect=decode):
            output=self.export('black')
        with zipfile.ZipFile(output) as archive:
            first=self.frame(archive,'generated_border/frame_00000.exr')
            second=self.frame(archive,'generated_border/frame_00001.exr')
            tail=self.frame(archive,'generated_border/frame_00008.exr')
            self.assertEqual(float(first[0,0,3]),1.)
            self.assertLess(float(second[0,0,3]),1.)
            self.assertEqual(float(second[0,4,3]),1.)
            self.assertEqual(float(tail[0,8,3]),1.)

    def test_bad_archives_are_rejected_without_extracting_paths(self):
        with zipfile.ZipFile(self.master,'a') as archive:archive.writestr('../escape.exr','bad')
        with self.assertRaisesRegex(ValueError,'safe EXR sequence'):self.export()
        self.assertFalse((self.root/'escape.exr').exists())
        self.assertFalse((self.root/'genj/hdr/test_layers.zip').exists())

    def test_mismatched_raster_and_nonfinite_rejected(self):
        raw=self.root/'wrong.exr';write_rgb(raw,np.ones((32,32,3),np.float32))
        with zipfile.ZipFile(self.master,'w') as archive:
            for i in range(9):archive.write(raw,f'frame_{i:05d}.exr')
        with self.assertRaisesRegex(ValueError,'does not match'):self.export()
        self.assertEqual(list((self.root/'genj/hdr').iterdir()),[])
        values=self.scene.copy();values[3,3,0]=float('nan');write_rgb(raw,values)
        with zipfile.ZipFile(self.master,'w') as archive:
            for i in range(9):archive.write(raw,f'frame_{i:05d}.exr')
        with self.assertRaisesRegex(ValueError,'invalid pixels'):self.export()

    def test_cancellation_collision_and_invalid_prefix_leave_existing_files(self):
        event=threading.Event()
        def progress(done,total):
            if done==2:event.set()
        with self.assertRaisesRegex(layers.HDRChunkCancelled,'Stopped'):
            self.export(cancelled=event,progress=progress)
        self.assertEqual(list((self.root/'genj/hdr').iterdir()),[])
        existing=self.root/'genj/hdr/test_layers.zip';existing.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'already exists'):self.export()
        self.assertEqual(existing.read_bytes(),b'keep')
        with self.assertRaisesRegex(ValueError,'valid HDR output name'):self.export('../escape')

    def test_black_mask_may_disappear_or_cover_one_frame(self):
        self.selection.update(mode='black',left=0,top=0,right=0,bottom=0)
        self.describe.return_value={'width':64,'height':64,'kind':'video'}
        def decode(path,selection,info,directory,cancelled):
            first=torch.ones((1,64,64,3))*2;first[0,:4,:4]=0
            for frame in (first,torch.ones_like(first)*2,torch.zeros_like(first)):
                yield colour.encode_ct(frame)
        self.decoder.stop()
        with patch.object(layers,'_native_frame_stream',side_effect=decode):output=self.export('mixed')
        with zipfile.ZipFile(output) as archive:
            empty=self.frame(archive,'generated_border/frame_00001.exr')
            full=self.frame(archive,'generated_border/frame_00002.exr')
            self.assertEqual(float(empty[:,:,3].max()),0.)
            self.assertEqual(float(full[:,:,3].min()),1.)

    def test_insufficient_space_fails_before_decode_or_publish(self):
        fake=types.SimpleNamespace(total=100,used=99,free=1)
        with patch.object(layers.shutil,'disk_usage',return_value=fake):
            with self.assertRaisesRegex(ValueError,'disk space'):self.export()
        self.decode_mock.assert_not_called()
        self.assertFalse((self.root/'genj/hdr/test_layers.zip').exists())

    def test_native_reader_streams_one_fractional_rate_timeline(self):
        self.decoder.stop()
        selection={**self.selection,'frames':3}
        info={'width':2,'height':2,'kind':'video','fps_rational':'24000/1001',
              'count':100,'matrix':'bt2020nc','range':'tv','transfer':'smpte2084'}
        raw=np.arange(36,dtype='<u2').reshape(3,2,2,3)
        process=types.SimpleNamespace(stdout=io.BytesIO(raw.tobytes()),poll=lambda:0,wait=lambda **k:0)
        with patch.object(layers.subprocess,'Popen',return_value=process) as start, \
             patch.object(colour,'selected_space',return_value='pq_rec2020'), \
             patch.object(colour,'working',side_effect=lambda rgb,*args:rgb), \
             patch.object(colour,'find_media_tool',return_value='ffmpeg'):
            result=list(layers._native_frame_stream(self.source,selection,info,self.root,None))
        self.assertEqual(len(result),3)
        np.testing.assert_allclose(result[2].numpy()[0],raw[2].astype(np.float32)/65535.,atol=1e-8)
        start.assert_called_once()
        command=start.call_args.args[0]
        self.assertEqual(command[command.index('-ss')+1],'0.25')
        self.assertIn('setpts=PTS-STARTPTS,fps=24.0,scale=in_color_matrix=bt2020:in_range=tv:out_range=pc,tpad=stop_mode=clone:stop=1',command)


if __name__=='__main__':unittest.main()
