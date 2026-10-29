"""Native HDR input preparation; no model inference or GPU required."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np
import torch
import v2_bootstrap

for name, path in [('ComfyUI_zura_nodes.artist_studio', 'artist_studio'),
                   ('ComfyUI_zura_nodes.paintout', 'paintout')]:
    if name not in sys.modules:
        module = types.ModuleType(name)
        module.__path__ = [str(v2_bootstrap.ROOT / path)]
        sys.modules[name] = module
native = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_native_source')
paintout = importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


class NativeHDRInputTests(unittest.TestCase):
    def test_acescg_exr_extended_highlights_survive(self):
        info = {'kind':'sequence', 'files':['f0.exr','f1.exr'], 'count':2, 'width':2, 'height':2}
        source = [np.full((2,2,3), value, np.float32) for value in (1.0, 4.0)]
        with patch.object(paintout,'describe',return_value=info), \
             patch.object(paintout,'selected_space',return_value='acescg'), \
             patch.object(paintout,'frames',return_value=iter(source)) as read:
            images, fps = native.load_native_hdr_frames('exr-directory',0,2,sequence_fps=25)
        read.assert_called_once_with(info,0,2)
        self.assertEqual((tuple(images.shape),fps),((2,2,2,3),25.0))
        self.assertAlmostEqual(float(paintout.decode_ct(images)[1,0,0,0]),4.0,places=4)

    def test_hlg_is_transformed_by_comfy_colour_management(self):
        info = {'kind':'video','count':2,'width':2,'height':2,'fps':24,'transfer':'arib-std-b67'}
        source = [np.full((2,2,3),0.5,np.float32)]
        with patch.object(paintout,'describe',return_value=info), \
             patch.object(paintout,'selected_space',return_value='hlg_rec2020'), \
             patch.object(paintout,'frames',return_value=iter(source)), \
             patch.object(paintout,'native_colour',return_value=torch.full((1,2,2,3),0.4)) as convert:
            images, fps = native.load_native_hdr_frames('hlg.mov',1,1)
        self.assertEqual(fps,24)
        self.assertEqual(convert.call_args.args[1:],('HDR','HDR ACEScct'))
        self.assertTrue(torch.allclose(images,torch.full_like(images,0.4),atol=1e-5))

    def test_rejects_sdr_non_exr_unbounded_and_short(self):
        info = {'kind':'video','count':2,'width':2,'height':2,'fps':24,'transfer':'bt709'}
        with patch.object(paintout,'describe',return_value=info), self.assertRaisesRegex(ValueError,'tagged SDR'):
            native.load_native_hdr_frames('sdr.mp4',0,1,'hlg_rec2020')
        exr = {'kind':'sequence','files':['f.png'],'count':1,'width':2,'height':2}
        with patch.object(paintout,'describe',return_value=exr), self.assertRaisesRegex(ValueError,'EXR'):
            native.load_native_hdr_frames('f.png',0,1,'acescg')
        with patch.object(paintout,'describe',return_value={**info,'width':2000,'height':2000,'count':121}), self.assertRaisesRegex(ValueError,'too large'):
            native.load_native_hdr_frames('hdr.mp4',0,121)
        with patch.object(paintout,'describe',return_value=info), self.assertRaisesRegex(ValueError,'past the source'):
            native.load_native_hdr_frames('hdr.mp4',1,2)


if __name__ == '__main__': unittest.main()
