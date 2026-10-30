"""Structure and constraints for the experimental native HDR recipe."""
import importlib
import sys
import types
import unittest
import v2_bootstrap

name='ComfyUI_zura_nodes.artist_studio'
if name not in sys.modules:
    module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/'artist_studio')];sys.modules[name]=module
native=importlib.import_module(name+'.hdr_native_graph')


class NativeHDRGraphTests(unittest.TestCase):
    def args(self):return dict(source='sequence',frame_count=9,fps=24,width=512,height=512,prefix='test')
    def test_two_stages_use_float_vae_and_real_exr_input(self):
        g=native.build_native_exr_graph(**self.args())
        self.assertEqual(g['source']['class_type'],'LTXVLoadEXRSequence')
        self.assertEqual(g['source']['inputs']['frame_cap'],9)
        self.assertEqual(g['vae']['class_type'],'LTXVVAEForceFloat32')
        self.assertEqual(g['lora']['inputs']['lora_name'],native.REFINER)
        self.assertEqual(g['sample1']['inputs']['latents'],['guide1',2])
        self.assertEqual(g['sample2']['inputs']['latents'],['guide2',2])
        self.assertEqual(g['guide2']['inputs']['latent'],['upsample',0])
        self.assertTrue(g['guide1']['inputs']['use_streaming'])
        self.assertTrue(g['guide2']['inputs']['use_streaming'])
        self.assertEqual(g['zura_hdr_save_video']['class_type'],'ZuraHDRSaveExactRate')
        self.assertEqual(g['zura_hdr_exr']['class_type'],'LTXVHDRDecodePostprocess')
    def test_rejects_unsupported_frame_and_canvas_constraints(self):
        for change in ({'frame_count':10},{'width':500},{'source_colour':'srgb_display'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                native.build_native_exr_graph(**{**self.args(),**change})

    def test_video_graph_crops_padding_and_preserves_range_audio(self):
        g=native.build_native_video_graph(source='source.mp4',start_frame=5,frame_count=10,
            fps=24,width=384,height=224,prefix='video_test',has_audio=True)
        self.assertEqual(g['source']['class_type'],'ZuraHDRLoadNativeSource')
        self.assertEqual(g['source']['inputs']['start_frame'],5)
        self.assertEqual(g['empty']['inputs']['length'],17)
        self.assertEqual(g['resize2']['inputs']['image'],['native_pad',0])
        self.assertEqual(g['trim_raster']['inputs']['width'],384)
        self.assertEqual(g['trim_raster']['inputs']['height'],224)
        self.assertEqual(g['trim_frames']['inputs']['length'],10)
        self.assertEqual(g['zura_hdr_video']['inputs']['audio'],['native_audio',0])
        self.assertEqual(g['native_audio']['inputs']['start_frame'],5)


if __name__=='__main__':unittest.main()
