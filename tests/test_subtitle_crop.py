"""CPU-only checks for the subtitle crop adapter and whole-crop blend."""
import importlib
from pathlib import Path
import sys
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
import torch

root=Path(__file__).resolve().parents[1]
package=types.ModuleType('subtitle_crop_test');package.__path__=[str(root/'paintout')]
sys.modules.setdefault(package.__name__,package)
crop=importlib.import_module(package.__name__+'.subtitle_crop')
native=importlib.import_module(package.__name__+'.paintout')


class SubtitleCropTests(unittest.TestCase):
    def test_two_stage_padding_preserves_original_frames_and_crop_geometry(self):
        image=torch.rand((9,192,320,3));mask=torch.zeros((9,192,320));mask[:,20:30,50:80]=1
        plate={'_work_images':image,'_work_mask':mask,'padded':[192,320],'resized':[190,315],
               'rect':[5,7,315,190],'count':7,'start':0,'fps':30000/1001,'source':{'kind':'sequence'}}
        prepared,low,w,h=crop.ZuraSubtitlePrepareCrop().prepare(plate)
        self.assertEqual(prepared['padded'],[256,384]);self.assertEqual((w,h),(192,128))
        self.assertEqual(tuple(low.shape),(9,128,192,3));self.assertEqual(prepared['count'],7)
        self.assertEqual(prepared['fps'],plate['fps']);self.assertEqual(prepared['rect'],plate['rect'])
        self.assertTrue(torch.equal(prepared['_work_images'][:,:192,:320],image))
        self.assertTrue(prepared['subtitle_full_crop'])
        silence=crop.ZuraSubtitleSourceAudio().load(prepared)[0]
        self.assertEqual(silence['sample_rate'],48000)
        self.assertEqual(silence['waveform'].shape[-1],round(9/plate['fps']*48000))
        self.assertEqual(torch.count_nonzero(silence['waveform']),0)

    def test_entire_crop_is_blended_not_just_painted_selection(self):
        source=np.zeros((64,64,3),dtype=np.float32);edited=np.ones_like(source)
        output,support=native.composite_subtitle_crop(source,edited,[20,10,64,64],(120,100),8)
        self.assertTrue(support.all());self.assertEqual(output[32,32,0],1)
        self.assertGreater(output[0,0,0],0);self.assertLess(output[0,0,0],1)
        self.assertEqual(output[32,20,0],1)

    def test_no_fade_on_real_frame_edges(self):
        source=np.zeros((16,16,3),dtype=np.float32);edited=np.ones_like(source)
        output,_=native.composite_subtitle_crop(source,edited,[0,0,16,16],(16,16),8)
        self.assertTrue(np.all(output==1))

    def test_uncrop_processes_full_rectangle_and_keeps_outside_pixels(self):
        # A tiny paint mark defines the crop; unpainted pixels within that crop
        # still receive the generated result. Held tail frames are discarded.
        original=np.full((72,72,3),.2,dtype=np.float32)
        selected=np.zeros((72,72),dtype=np.float32);selected[30,30]=1
        plate={'source':{'kind':'sequence'},'mask':{'kind':'rectangle','width':72,'height':72,'count':2,'rect':[30,30,1,1]},
               'padded':[64,64],'resized':[64,64],'rect':[4,4,64,64],'count':2,'start':0,'fps':25,
               'fps_rational':'25','space':'srgb_display','processing':'SDR (sRGB)','grow':0,'feather':0,
               'subtitle_full_crop':True,'subtitle_feather':4}
        rendered=[]
        class Delivery:
            def __init__(self,*args):pass
            def append(self,frame):rendered.append(frame.numpy().copy())
            def finish(self):return {}
        media=importlib.import_module(package.__name__+'.media')
        with tempfile.TemporaryDirectory() as target, \
             patch.dict(sys.modules,{'folder_paths':types.SimpleNamespace(get_output_directory=lambda:target)}), \
             patch.object(media,'Delivery',Delivery), \
             patch.object(native,'frames',side_effect=lambda *_:[original.copy(),original.copy()]), \
             patch.object(native,'mask_frames',side_effect=lambda *_:[selected.copy(),selected.copy()]), \
             patch.object(native,'protection_mask',return_value=np.zeros((72,72),dtype=np.float32)), \
             patch.object(native,'unworking',side_effect=lambda image,*_:image), \
             patch.object(native,'to_linear',side_effect=lambda image,*_:image), \
             patch.object(native,'from_linear',side_effect=lambda image,*_:image), \
             patch.object(native,'frame_progress',return_value=lambda *_:None):
            native.ZuraPaintoutUncrop().save(torch.ones((9,64,64,3)),plate,'subtitles','float32',False,'SDR video')
        self.assertEqual(len(rendered),2)
        np.testing.assert_array_equal(rendered[0][0],original[0])
        self.assertEqual(rendered[0][35,35,0],1)
        self.assertEqual(rendered[0][20,20,0],1) # outside painted mark, inside crop
        self.assertEqual(rendered[0][2,20,0],original[2,20,0])

    def test_empty_or_mismatched_work_mask_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'crop'):
            crop.ZuraSubtitlePrepareCrop().prepare({'_work_images':torch.zeros((1,8,8,3)),'_work_mask':torch.zeros((1,7,8))})

    def test_low_memory_stops_before_padding_the_batch(self):
        image=torch.zeros((9,192,320,3));mask=torch.zeros((9,192,320))
        memory=types.SimpleNamespace(available=100*1024**2,total=8*1024**3)
        with patch.dict(sys.modules,{'psutil':types.SimpleNamespace(virtual_memory=lambda:memory)}), \
             patch.object(crop.F,'pad',side_effect=AssertionError('Must reject before allocating')):
            with self.assertRaisesRegex(ValueError,'Reduce the crop, processing scale or clip length'):
                crop.ZuraSubtitlePrepareCrop().prepare({'_work_images':image,'_work_mask':mask})

    def test_small_crop_can_run_with_cached_models_in_a_large_system(self):
        memory=types.SimpleNamespace(available=6*1024**3,total=64*1024**3)
        with patch.dict(sys.modules,{'psutil':types.SimpleNamespace(virtual_memory=lambda:memory)}):
            crop.ensure_subtitle_memory(500*1024**2)

    def test_large_crop_checks_memory_before_decoding_frames(self):
        width=height=1024
        source={'kind':'sequence','width':width,'height':height,'count':993,'fps':25}
        mask={'kind':'rectangle','width':width,'height':height,'count':1,'rect':[0,0,width,height]}
        memory=types.SimpleNamespace(available=2*1024**3,total=8*1024**3)
        with patch.dict(sys.modules,{'psutil':types.SimpleNamespace(virtual_memory=lambda:memory)}), \
             patch.object(native,'describe',return_value=source), \
             patch.object(native,'selected_space',return_value='srgb_display'), \
             patch.object(native,'mask_frames',return_value=iter([np.ones((height,width),dtype=np.float32)])), \
             patch.object(native,'frames',side_effect=AssertionError('Must reject before decoding')):
            with self.assertRaisesRegex(ValueError,'Reduce the crop, processing scale or clip length'):
                native.ZuraPaintoutCrop().prepare('C:/clip',mask,'srgb_display',0,993,25,64,4096,0,0,
                                                   'SDR (sRGB)','Smart crop (experimental)',1024,1024,1)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'Requires FFmpeg')
    def test_source_audio_is_trimmed_and_internal_tail_is_silence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'tone.wav'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1',str(path)],check=True,capture_output=True)
            plate={'source':{'kind':'video','path':str(path)},'start':3,'count':10,'fps':25,'_work_images':torch.zeros((17,1,1,3))}
            audio=crop.ZuraSubtitleSourceAudio().load(plate)[0]
            waveform=audio['waveform']
            self.assertEqual(waveform.shape,(1,2,round(17/25*48000)))
            self.assertGreater(torch.count_nonzero(waveform[:,:,:round(10/25*48000)]),0)
            self.assertEqual(torch.count_nonzero(waveform[:,:,round(10/25*48000):]),0)


if __name__=='__main__':unittest.main()
