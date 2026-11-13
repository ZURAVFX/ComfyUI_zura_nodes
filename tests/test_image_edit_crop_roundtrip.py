"""Optional CPU integration with the user's installed Smart Crop/Stitch nodes.

Set ZURA_SMART_CROP_ROOT to ComfyUI-Smart-Image-Crop-and-Stitch. No ComfyUI
server, checkpoint, sampler inference, CUDA context or live files are used.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest

import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class NativeCropRoundtrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = os.environ.get('ZURA_SMART_CROP_ROOT')
        if not directory:
            raise unittest.SkipTest('Set ZURA_SMART_CROP_ROOT to run native crop/stitch integration')
        directory = Path(directory)
        package = types.ModuleType('zura_crop_fixture')
        package.__path__ = [str(directory)]
        sys.modules[package.__name__] = package
        cls.crop = load('zura_crop_fixture.smart_image_crop', directory / 'smart_image_crop.py').SmartImageCrop()
        cls.stitch = load('zura_crop_fixture.smart_image_stitcher', directory / 'smart_image_stitcher.py').SmartImageStitcher()
        cls.mask = load('zura_area_fixture', ROOT / 'artist_studio/image_edit_area.py').ZuraImageEditMask()
        cls.cases = json.loads(subprocess.check_output(['node', str(ROOT / 'tests/test_image_edit_placement.mjs'), '--fixture'], text=True))
        torch.set_num_threads(2)

    def test_offcentre_draw_to_native_crop_and_source_sized_stitch(self):
        for case in self.cases:
            with self.subTest(case=case):
                w,h,pw,ph = [case[key] for key in ['width','height','proxyWidth','proxyHeight']]
                # Non-SDR values deliberately exercise unchanged source pixels.
                source = torch.tensor([-.1,.5,1.5]).view(1,1,1,3).expand(1,h,w,3).clone()
                yy,xx = torch.meshgrid(torch.arange(ph),torch.arange(pw),indexing='ij')
                brush = ((xx-case['x'])**2+(yy-case['y'])**2 <= case['r']**2).float()
                painted = brush[None,:,:,None].expand(1,ph,pw,3)
                raw,blend = self.mask.prepare(source,painted,16,drawing_region=True)
                self.assertEqual(float(raw[0,round(h*.73),round(w*.62)]),1)
                self.assertEqual(float(raw[0,round(h*.73),round(w*.8)]),0)
                # The real graph restores the proxy before using source-pixel padding.
                proxy = F.interpolate(source.movedim(-1,1),size=(ph,pw),mode='bilinear',align_corners=False).movedim(1,-1)
                guide = torch.where(painted>0,torch.tensor([1.,.388,.278]),proxy)
                guide = F.interpolate(guide.movedim(-1,1),size=(h,w),mode='bilinear',align_corners=False).movedim(1,-1)
                args=dict(mask=raw,resolution_mode='Automatic',max_resolution=8192,min_resolution=256,manual_width=1024,manual_height=1024,mask_grow_pixels=0,patch_mask_holes=False,no_mask_mode='Bypass',force_divisibility=16,context_padding=64)
                clean,mask,geometry,_ = self.crop.run(image=source,**args)
                drawn,drawn_mask,drawn_geometry,_ = self.crop.run(image=guide,**args)
                self.assertEqual(geometry,drawn_geometry)
                self.assertEqual(clean.shape,drawn.shape)
                self.assertTrue(torch.equal(mask,drawn_mask))
                # A deterministic stand-in for the model edits the crop. The
                # native stitch and final source-space blend are real operations.
                generated = torch.tensor([.2,.8,.1]).view(1,1,1,3).expand_as(clean).clone()
                result = self.stitch.stitch(source,generated,geometry,0,blend_mode='Hard Paste',enable_color_match=False)[0]
                final = result*blend[:,:,:,None]+source*(1-blend[:,:,:,None])
                self.assertEqual(final.shape,source.shape)
                self.assertTrue(torch.equal(final[blend==0],source[blend==0]),'Untouched pixels remain bit-identical, including HDR values')
                self.assertTrue(torch.allclose(final[0,round(h*.73),round(w*.62)],torch.tensor([.2,.8,.1]),atol=1e-6))
                self.assertFalse(torch.any(torch.all(final==torch.tensor([1.,.388,.278]),dim=-1)),'No painted-guide raster is pasted into the final base')


if __name__ == '__main__':
    unittest.main()
