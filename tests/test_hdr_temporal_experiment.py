"""Private temporal fusion graph stays isolated from bounded Studio HDR."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np
import torch
import v2_bootstrap

for name,path in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/path)];sys.modules[name]=module
native=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_native_source')
graph=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_native_graph')
paintout=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


class HDRTemporalTests(unittest.TestCase):
    def params(self):return dict(source='source.mp4',start_frame=0,frame_count=129,fps=24,width=384,height=224,prefix='private',colour_space='hlg_rec2020')
    def test_public_guard_remains_and_private_uses_one_canvas_and_matching_windows(self):
        with self.assertRaisesRegex(ValueError,'121'):graph.build_native_video_graph(**self.params())
        result=graph.build_native_video_graph(**self.params(),temporal_window=65,output='hlg_video')
        self.assertEqual(result['empty']['inputs']['length'],129)
        self.assertEqual(result['source']['class_type'],'ZuraHDRLoadNativeSourceLong')
        self.assertEqual(result['native_pad']['class_type'],'ZuraHDRNativePrepareLong')
        for node in ('guide1','guide2','sample1','sample2'):
            self.assertEqual(result[node]['inputs']['tile_frames'],65)
        self.assertTrue(result['guide1']['inputs']['use_streaming'])
        self.assertTrue(result['guide2']['inputs']['use_streaming'])
        self.assertEqual(result['sample1']['inputs']['canvas_device'],'cpu')
        self.assertEqual(result['trim_frames']['inputs']['length'],129)
    def test_private_rejects_audio_exr_and_excess_padded_budget(self):
        with self.assertRaisesRegex(ValueError,'silent HLG'):graph.build_native_video_graph(**self.params(),temporal_window=65,output='hlg_and_exr')
        with self.assertRaisesRegex(ValueError,'silent HLG'):graph.build_native_video_graph(**self.params(),temporal_window=65,output='hlg_video',has_audio=True)
        params={**self.params(),'width':1920,'height':1080}
        with self.assertRaisesRegex(ValueError,'too large'):graph.build_native_video_graph(**params,temporal_window=65,output='hlg_video')
    def test_private_loader_reads_exact_extended_range(self):
        info={'kind':'video','count':130,'width':32,'height':32,'fps':24,'transfer':'arib-std-b67'}
        pixels=[np.full((32,32,3),.5,np.float32)]*129
        with patch.object(paintout,'describe',return_value=info),patch.object(paintout,'selected_space',return_value='hlg_rec2020'), \
             patch.object(paintout,'frames',return_value=iter(pixels)),patch.object(paintout,'working',side_effect=lambda rgb,*args:rgb):
            result,fps=native.load_native_hdr_frames('source',1,129,max_frames=257)
        self.assertEqual((len(result),fps),(129,24.))
    def test_preparation_rejects_oversized_padded_range_before_allocation(self):
        images=torch.zeros(129,32,32,3)
        with patch.object(native,'MAX_PIXEL_FRAMES',1),self.assertRaisesRegex(ValueError,'memory budget'):
            native.prepare_native_hdr(images,257)


if __name__=='__main__':unittest.main()
