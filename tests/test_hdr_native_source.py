"""Native HDR input preparation; no model inference or GPU required."""
import importlib
import sys
import types
import unittest
import tempfile
from pathlib import Path
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
    def test_tagged_display_p3_pq_uses_primaries_conversion(self):
        rec_to_aces = ((.673459, .165661, .160880), (.034844, .946710, .018446), (.002647, .023144, .974209))
        fake = types.ModuleType('comfy_extras.nodes_images')
        fake._REC2020_TO_ACESCG = rec_to_aces
        rgb = torch.tensor([[[[.4,.2,.1], [.1,.3,.5]]]])
        # Independent calibrated ST 2084 linear-light values in units of 203 nits.
        m1,m2,c1,c2,c3=2610/16384,2523/32,3424/4096,2413/128,2392/128
        p=rgb.double().pow(1/m2)
        linear=((p-c1).clamp_min(0)/(c2-c3*p)).pow(1/m1)*10000/203
        matrix=torch.tensor(rec_to_aces,dtype=torch.float64)
        faux=linear @ matrix.T
        p3_to_aces=torch.tensor(((.73579791,.21216649,.05203560),(.04717988,.93804570,.01477441),(.00356366,.04114189,.95529445)),dtype=torch.float64)
        with patch.dict(sys.modules, {'comfy_extras':types.ModuleType('comfy_extras'), 'comfy_extras.nodes_images':fake}), \
             patch.object(paintout,'native_colour',return_value=paintout.encode_ct(faux.float())):
            result=paintout.to_linear(rgb,'pq_display_p3')
        torch.testing.assert_close(result.double(),linear @ p3_to_aces.T,rtol=2e-5,atol=1e-6)
        info={'kind':'video','primaries':'smpte432','transfer':'smpte2084','matrix':'bt709','range':'tv'}
        self.assertEqual(paintout.selected_space(info,'auto'),'pq_display_p3')
        for bad in ({**info,'transfer':'arib-std-b67'}, {**info,'matrix':'unknown'}, {**info,'range':'unknown'}):
            with self.assertRaises(ValueError):paintout.selected_space(bad,'auto')

    def test_real_oiio_linear_rec709_exr_roundtrip(self):
        try:
            import OpenImageIO as oiio
        except ImportError:
            self.skipTest('OpenImageIO is not installed')
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'linear.exr')
            spec = oiio.ImageSpec(2, 2, 3, oiio.FLOAT)
            spec.attribute('oiio:ColorSpace', 'lin_rec709_scene')
            spec.attribute('chromaticities', oiio.TypeDesc('float[8]'), (.64,.33,.30,.60,.15,.06,.3127,.3290))
            output = oiio.ImageOutput.create(path)
            self.assertTrue(output.open(path, spec))
            self.assertTrue(output.write_image(np.full((2,2,3), 0.25, np.float32)))
            output.close()
            source = oiio.ImageInput.open(path)
            self.assertEqual(source.spec().getattribute('oiio:ColorSpace'), 'lin_rec709_scene')
            source.close()
            self.assertEqual(paintout.selected_space({'kind':'sequence','files':[path]}, 'auto'), 'linear_rec709')

    def test_exr_sequence_auto_checks_all_headers_and_override_skips_them(self):
        rec709 = (.64,.33,.30,.60,.15,.06,.3127,.3290)
        acescg = (.713,.293,.165,.830,.128,.044,.32168,.33767)
        opened = []
        def open_header(path):
            opened.append(path)
            chroma = rec709 if path == 'a.exr' else acescg
            spec = types.SimpleNamespace(getattribute=lambda key: chroma if key == 'chromaticities' else None)
            return types.SimpleNamespace(spec=lambda: spec, close=lambda: None)
        oiio = types.SimpleNamespace(ImageInput=types.SimpleNamespace(open=open_header))
        info = {'kind':'sequence', 'files':['a.exr','b.exr']}
        with patch.dict(sys.modules, {'OpenImageIO': oiio}):
            with self.assertRaisesRegex(ValueError, 'b.exr.*acescg.*linear_rec709'):
                paintout.selected_space(info, 'auto')
            self.assertEqual(opened, ['a.exr','b.exr'])
            opened.clear()
            self.assertEqual(paintout.selected_space(info, 'acescg'), 'acescg')
            self.assertEqual(opened, [])

    def test_exr_colour_detection_uses_all_primaries_and_white_point(self):
        rec709 = (.64,.33,.30,.60,.15,.06,.3127,.3290)
        acescg = (.713,.293,.165,.830,.128,.044,.32168,.33767)
        # Same red x as Rec.709 is insufficient to establish the gamut.
        other_gamut = (.64,.33,.265,.69,.15,.06,.3127,.3290)
        cases = [('', rec709, 'linear_rec709'), ('', acescg, 'acescg'),
                 ('ACEScct', acescg, 'acescct'), ('ACEScg', None, 'acescg'),
                 ('lin_ap1_scene', acescg, 'acescg')]
        for tag, chroma, expected in cases:
            with self.subTest(tag=tag, chroma=chroma):
                spec = types.SimpleNamespace(getattribute=lambda key: tag if key == 'oiio:ColorSpace' else chroma if key == 'chromaticities' else None)
                reader = types.SimpleNamespace(spec=lambda: spec, close=lambda: None)
                oiio = types.SimpleNamespace(ImageInput=types.SimpleNamespace(open=lambda _: reader))
                with patch.dict(sys.modules, {'OpenImageIO': oiio}):
                    self.assertEqual(paintout.selected_space({'kind':'sequence','files':['frame.exr']}, 'auto'), expected)
        for tag, chroma in [('', other_gamut), ('ACEScg', rec709), ('sRGB', rec709), ('', None)]:
            with self.subTest(tag=tag, chroma=chroma):
                spec = types.SimpleNamespace(getattribute=lambda key: tag if key == 'oiio:ColorSpace' else chroma if key == 'chromaticities' else None)
                reader = types.SimpleNamespace(spec=lambda: spec, close=lambda: None)
                oiio = types.SimpleNamespace(ImageInput=types.SimpleNamespace(open=lambda _: reader))
                with patch.dict(sys.modules, {'OpenImageIO': oiio}), self.assertRaises(ValueError):
                    paintout.selected_space({'kind':'sequence','files':['frame.exr']}, 'auto')
                self.assertEqual(paintout.selected_space({'kind':'sequence','files':['frame.exr']}, 'acescg'), 'acescg')

    def test_unreadable_exr_header_has_actionable_error(self):
        oiio = types.SimpleNamespace(ImageInput=types.SimpleNamespace(open=lambda _: None))
        with patch.dict(sys.modules, {'OpenImageIO': oiio}), self.assertRaisesRegex(ValueError, 'frame.exr.*Cannot open EXR header'):
            paintout.selected_space({'kind':'sequence','files':['frame.exr']}, 'auto')

    def test_explicit_hdr_video_space_rejects_conflicting_tagged_primaries(self):
        for space in ('pq_rec2020', 'hlg_rec2020'):
            with self.subTest(space=space):
                info = {'kind': 'video', 'primaries': 'smpte432'}
                with self.assertRaisesRegex(ValueError, 'smpte432.*Rec.2020.*Convert'):
                    paintout.selected_space(info, space)

    def test_explicit_hdr_video_space_accepts_bt2020_and_untagged(self):
        for space in ('pq_rec2020', 'hlg_rec2020'):
            for primaries in ('bt2020', None, 'unknown', 'unspecified'):
                with self.subTest(space=space, primaries=primaries):
                    info = {'kind': 'video', 'primaries': primaries}
                    self.assertEqual(paintout.selected_space(info, space), space)

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

    def test_native_padding_preserves_frame_pixels_and_extends_tail(self):
        source=torch.rand(10,224,384,3)
        padded,w,h,count,pw,ph,n=native.ZuraHDRNativePrepare().prepare(source)
        self.assertEqual((w,h,count,pw,ph,n),(384,224,10,512,512,17))
        self.assertTrue(torch.equal(padded[:10,:224,:384],source))
        self.assertTrue(torch.equal(padded[-1],padded[9]))


if __name__ == '__main__': unittest.main()
