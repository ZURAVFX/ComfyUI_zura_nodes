"""Native HDR outpaint comparison validates execution, timing and mask wiring."""
import importlib
import sys
import types
import unittest

import v2_bootstrap

for name, folder in [('ComfyUI_zura_nodes.artist_studio', 'artist_studio'),
                     ('ComfyUI_zura_nodes.paintout', 'paintout')]:
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(v2_bootstrap.ROOT / folder)]
        sys.modules[name] = package

native = importlib.import_module('ComfyUI_zura_nodes.artist_studio.ltx_hdr_outpaint_native')
experiment = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_experiment')
outpaint = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_studio')


class NativeHDROutpaintTest(unittest.TestCase):
    def setUp(self):
        self.source = {'sha':'a'*64, 'file':'fixture.mov', 'duration':4.,
                       'width':1920, 'height':1080, 'asset_kind':'video'}
        self.selection = outpaint.plan(self.source, start=.25, duration=14/24, mode='expand',
            width=1088, height=640, left=64, right=64, top=32, bottom=32)
        self.key = experiment.hdr_review_key(self.selection, 'pq_rec2020')

    def graph(self, **kwargs):
        return native.build_native_hdr_outpaint_test(self.source, self.selection,
            review_key=self.key, colour_space='pq_rec2020', **kwargs)

    def test_matches_masked_two_stage_recipe_and_uses_native_hdr(self):
        g = self.graph(has_audio=True)
        self.assertEqual(g['hdr_source']['inputs']['start_seconds'], .25)
        self.assertEqual(g['hdr_source']['inputs']['frame_count'], 14)
        self.assertEqual(g['canvas']['inputs']['images'], ['hdr_hold', 0])
        self.assertEqual(g['canvas']['inputs']['left'], 64)
        self.assertEqual(g['canvas']['inputs']['top'], 32)
        self.assertEqual(g['inpaint']['inputs']['mask'], ['low_mask', 0])
        self.assertEqual(g['guide']['inputs']['image'], ['inpaint', 0])
        self.assertEqual(g['adapter']['inputs']['lora_name'], 'ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors')
        self.assertEqual(g['adapter']['inputs']['strength_model'], 1.)
        self.assertEqual((g['empty']['inputs']['width'],g['empty']['inputs']['height'],g['empty']['inputs']['length']),(544,320,17))
        self.assertEqual(g['video_vae']['inputs']['vae_name'], 'ltx-2.5-video-vae-bf16.safetensors')
        self.assertEqual(g['hdr_vae']['class_type'], 'LTXVVAEForceFloat32')
        self.assertEqual(g['guide']['inputs']['vae'], ['hdr_vae', 0])
        self.assertEqual(g['split']['inputs']['av_latent'], ['sample', 1])
        self.assertEqual(g['blend_low']['inputs']['mask_low_res_dilation'],5)
        self.assertEqual(g['upsize']['inputs']['image'], ['blend_low',0])
        self.assertEqual(g['sigmas_high']['inputs']['sigmas'], '0.7250, 0.4219, 0.0')
        self.assertEqual(g['blend_high']['inputs']['mask_low_res_dilation'],6)
        self.assertEqual(g['hdr_trim']['inputs']['image'], ['blend_high',0])
        self.assertNotIn('hdr_composite', g)
        self.assertEqual(g['test_delivery_hold']['inputs']['length'],17)
        self.assertEqual(g['hdr_experiment_hlg']['inputs']['image'], ['test_delivery_hold',0])
        self.assertEqual(g['hdr_experiment_exr']['inputs']['images'], ['test_delivery_hold',0])
        self.assertEqual(g['audio_encoded']['inputs']['audio'], ['hdr_audio_hold',1])
        self.assertEqual(g['hdr_experiment_video']['inputs']['audio'], ['hdr_audio_hold',1])
        self.assertEqual(g['hdr_preview_video']['inputs']['audio'], ['hdr_audio_hold',1])
        for item in g.values():
            for value in item['inputs'].values():
                if isinstance(value,list) and len(value)==2 and isinstance(value[0],str):
                    self.assertIn(value[0],g, f'Dangling graph link: {value}')

    def test_plate_preserving_variant_shares_the_same_sampling_graph(self):
        direct, preserved = self.graph(has_audio=True), self.graph(has_audio=True,preserve_source=True)
        for key in ('model','adapter','hdr_vae','sample','sample_high','blend_low','blend_high'):
            self.assertEqual(direct[key],preserved[key])
        self.assertEqual(preserved['hdr_trim']['inputs']['image'], ['hdr_composite',0])
        self.assertEqual(preserved['hdr_composite']['inputs']['source'], ['canvas',0])
        self.assertEqual(preserved['hdr_composite']['inputs']['mask'], ['canvas',1])

    def test_no_audio_does_not_freeze_empty_audio_as_reference(self):
        g = self.graph(has_audio=False)
        self.assertEqual(g['audio_encoded']['class_type'], 'LTXVEmptyLatentAudio')
        self.assertEqual(g['av']['inputs']['audio_latent'], ['audio_encoded',0])
        self.assertEqual(g['av_high']['inputs']['audio_latent'], ['split',1])
        self.assertNotIn('audio_frozen',g)
        self.assertNotIn('freeze_high',g)
        self.assertNotIn('audio',g['hdr_experiment_video']['inputs'])

    def test_changed_selection_or_review_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'approve'):
            native.build_native_hdr_outpaint_test(self.source,self.selection,review_key='invalid',colour_space='pq_rec2020')
        with self.assertRaisesRegex(ValueError,'Review the selection again'):
            native.build_native_hdr_outpaint_test(self.source,{**self.selection,'left':48},review_key=self.key,colour_space='pq_rec2020')
        with self.assertRaisesRegex(ValueError,'preserve'):
            self.graph(preserve_source='yes')


if __name__ == '__main__':
    unittest.main()
