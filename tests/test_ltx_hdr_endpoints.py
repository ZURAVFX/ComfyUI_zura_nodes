import importlib
import sys
import types
import unittest
import v2_bootstrap

name='ComfyUI_zura_nodes.artist_studio'
if name not in sys.modules:
    package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/'artist_studio')];sys.modules[name]=package
module=importlib.import_module(name+'.ltx_hdr_endpoints')


class NativeEndpointTests(unittest.TestCase):
    def config(self):
        return dict(first={'manifest':'first.json','sha':'a'*64},last={'manifest':'last.json','sha':'b'*64},
            width=512,height=512,frames=9,prompt='The same scene in motion.',prefix='endpoint_test')

    def test_real_hdr_endpoints_and_both_stage_anchors(self):
        graph=module.build_native_endpoint_graph(**self.config())
        self.assertEqual(graph['vae']['class_type'],'LTXVVAEForceFloat32')
        self.assertEqual(graph['vae_load']['inputs']['vae_name'],module.VIDEO_VAE)
        self.assertNotIn('conv',module.VIDEO_VAE)
        self.assertEqual(graph['first']['inputs']['manifest_sha'],'a'*64)
        self.assertEqual(graph['last']['inputs']['manifest_sha'],'b'*64)
        self.assertNotIn('LoadImage',[node['class_type'] for node in graph.values()])
        self.assertNotIn('LTXVPreprocess',[node['class_type'] for node in graph.values()])
        for stage in ('1','2'):
            self.assertEqual(graph['anchor_first'+stage]['class_type'],'LTXVImgToVideoInplace')
            self.assertEqual(graph['anchor_last'+stage]['inputs']['frame_idx'],8)
            self.assertEqual(graph['av'+stage]['inputs']['video_latent'],['anchor_last'+stage,2])
            self.assertEqual(graph['crop'+stage]['inputs']['latent'],['separate'+stage,0])
        self.assertEqual(graph['fit_first1']['inputs']['width'],256)
        self.assertEqual(graph['fit_first2']['inputs']['width'],512)
        self.assertEqual(graph['anchor_first2']['inputs']['latent'],['upsample',0])
        self.assertEqual(graph['zura_hdr_video']['inputs']['bit_depth'],10)
        self.assertEqual(graph['zura_hdr_archive']['inputs']['images'],['decode',0])

    def test_first_only_and_optional_audio_have_independent_paths(self):
        first=module.build_native_endpoint_graph(**{**self.config(),'last':None})
        self.assertNotIn('last',first)
        self.assertEqual(first['av2']['inputs']['video_latent'],['anchor_first2',0])
        self.assertEqual(first['av2']['inputs']['audio_latent'],['separate1',1])
        self.assertEqual(first['audio_duration']['inputs'],{'audio':['decode_audio',0],'frames':9,'fps':24.})
        self.assertEqual(first['zura_hdr_video']['inputs']['audio'],['audio_duration',0])
        audio=module.build_native_endpoint_graph(**self.config(),audio_file='speech.wav',audio_start=.25)
        self.assertEqual(audio['audio_window']['inputs']['start_index'],.25)
        self.assertEqual(audio['trim_audio']['inputs']['duration'],9/24)
        for stage in ('1','2'):self.assertEqual(audio['av'+stage]['inputs']['audio_latent'],['frozen_audio',0])
        self.assertEqual(audio['zura_hdr_video']['inputs']['audio'],['trim_audio',0])
        self.assertNotIn('decode_audio',audio)

    def test_constraints_reject_sdr_thumbnails_and_overbudget_ranges(self):
        for change in ({'first':{'file':'thumbnail.png'}},{'first':{'manifest':'first.json','sha':'bad'}},
                       {'width':520},{'frames':10},{'width':2048,'height':2048,'frames':17},
                       {'prompt':''},{'seed':True},{'audio_start':float('nan')},{'output':'sdr'},
                       {'first':{'manifest':'first.json','sha':'a'*64,'colour_space':'srgb_display'}}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                module.build_native_endpoint_graph(**{**self.config(),**change})


if __name__=='__main__':unittest.main()
