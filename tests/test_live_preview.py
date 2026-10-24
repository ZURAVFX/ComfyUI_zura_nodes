import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('live_preview',Path(__file__).resolve().parents[1]/'artist_studio/live_preview.py')
preview=importlib.util.module_from_spec(spec);spec.loader.exec_module(preview)

class LivePreviewTests(unittest.TestCase):
    def test_h3_uses_temporal_tae_only_when_exact_supported_decoder_exists(self):
        self.assertEqual(preview.preview_method({},'h3',['taeh3.safetensors']),'taesd')
        self.assertEqual(preview.preview_method({},'h3',['taeh3_2d_kijai.safetensors']),'auto')
        self.assertEqual(preview.preview_method({},'h3',[]),'auto')
    def test_wan_14b_and_relight_use_the_21_vae_family(self):
        for stage in ('wan','wan2','wan21_relight'):
            self.assertEqual(preview.preview_method({},stage,['lighttaew2_1.safetensors']),'taesd')
            self.assertEqual(preview.preview_method({},stage,['lighttaew2_2.safetensors']),'auto')
    def test_no_cross_family_tae_or_unsupported_ltx_core_override(self):
        for stage in ('design','prepare','background','restyle','h3_enhance'):
            self.assertEqual(preview.preview_method({},stage,['taeh3.safetensors','taeltx2_3.safetensors']),'auto')
if __name__=='__main__':unittest.main()
