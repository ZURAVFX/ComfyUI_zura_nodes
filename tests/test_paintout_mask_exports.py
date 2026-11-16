"""Actual repair matte, original clock, lossless frames and typed exports."""
import importlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile
from fractions import Fraction
import av
import numpy as np
from PIL import Image
import torch
import v2_bootstrap

for part in ('paintout','artist_studio'):
    name='ComfyUI_zura_nodes.'+part
    if name not in sys.modules:
        package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/part)];sys.modules[name]=package
paint=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')
exports=importlib.import_module('ComfyUI_zura_nodes.paintout.mask_exports')

class MatteTests(unittest.TestCase):
    def test_exr_archive_keeps_the_actual_rendered_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'render';target.mkdir()
            (target/'frame_000007.exr').write_bytes(b'original float frame 7');(target/'frame_000008.exr').write_bytes(b'original float frame 8')
            entry=exports.sequence_exports(target,root)[0];self.assertEqual(entry['role'],'exr')
            with zipfile.ZipFile(target/entry['file']['filename']) as archive:self.assertEqual(archive.read('frame_000007.exr'),b'original float frame 7')

    def test_export_formula_is_the_composite_formula(self):
        mask=np.zeros((32,32),np.float32);mask[12:20,12:20]=1
        protect=np.zeros_like(mask);protect[16:18,16:18]=1
        matte,_=paint.repair_matte(mask,2,5,protect)
        result,_=paint.composite_crop(np.zeros((32,32,3),np.float32),np.ones((32,32,3),np.float32),mask,2,5,False,protection=protect)
        np.testing.assert_allclose(result[:,:,0],matte,atol=1e-7)
        self.assertEqual(matte[16,16],0);self.assertTrue(np.any((matte>0)&(matte<1)))

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_real_save_emits_mask_frames_and_video_at_source_clock(self):
        import folder_paths
        with tempfile.TemporaryDirectory() as folder:
            source={'kind':'sequence','width':32,'height':32,'count':30}
            mask={'kind':'rectangle','width':32,'height':32,'rect':[12,12,8,8],'count':1}
            plate={'source':source,'mask':mask,'space':'srgb_display','processing':'SDR (sRGB)','start':7,'count':3,
                   'fps':30000/1001,'fps_rational':'30000/1001','rect':[0,0,32,32],'padded':[32,32],'resized':[32,32],'grow':1,'feather':4}
            frames=[np.full((32,32,3),.2,np.float32) for _ in range(3)]
            with patch.object(folder_paths,'get_output_directory',return_value=folder,create=True),patch.object(paint,'frames',return_value=iter(frames)),patch.object(paint,'matrix_rgb',side_effect=lambda image,*args,**kwargs:image):
                result=paint.ZuraPaintoutUncrop().save(torch.full((3,32,32,3),.9),plate,'test/result','float32',False,'SDR video',False)
            roles={entry['role']:entry['file'] for entry in result['ui']['zura_exports']}
            self.assertEqual(set(roles),{'mask','mask_sequence'})
            def file(role):return Path(folder)/roles[role]['subfolder']/roles[role]['filename']
            with av.open(str(file('mask'))) as movie:
                self.assertEqual(movie.streams.video[0].average_rate,Fraction(30000,1001));self.assertEqual(len(list(movie.decode(video=0))),3)
                self.assertEqual(movie.streams.video[0].codec_context.name,'prores')
            with zipfile.ZipFile(file('mask_sequence')) as archive:
                self.assertEqual([p for p in archive.namelist() if p.endswith('.png')],['mask_000007.png','mask_000008.png','mask_000009.png'])
                info=json.loads(archive.read('mask_info.json'));self.assertEqual(info['frameRate'],{'numerator':30000,'denominator':1001})
                actual=np.asarray(Image.open(io.BytesIO(archive.read('mask_000007.png'))))/65535
                raw=np.zeros((32,32),np.float32);raw[12:20,12:20]=1
                expected=paint.repair_matte(raw,1,4)[0];np.testing.assert_allclose(actual,expected,atol=1/65535)
            self.assertTrue(any(item['filename'].endswith('.mov') for item in result['ui']['images']))
