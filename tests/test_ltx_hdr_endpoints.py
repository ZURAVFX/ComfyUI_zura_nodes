import importlib
import sys
import types
import unittest
from unittest.mock import patch
import v2_bootstrap

name='ComfyUI_zura_nodes.artist_studio'
if name not in sys.modules:
    package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/'artist_studio')];sys.modules[name]=package
module=importlib.import_module(name+'.ltx_hdr_endpoints')
routes=importlib.import_module(name+'.ltx_hdr_endpoint_routes')


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

    def test_exact_1080_delivery_restores_after_the_model_grid(self):
        graph=module.build_native_endpoint_graph(**{
            **self.config(),'width':1920,'height':1088,'frames':17,
            'output_width':1920,'output_height':1080})
        self.assertEqual(graph['delivery_first']['inputs'],{
            'image':['first',0],'upscale_method':'bilinear',
            'width':1920,'height':1080,'crop':'center'})
        self.assertEqual(graph['delivery_last']['inputs']['width'],1920)
        self.assertEqual(graph['delivery_last']['inputs']['height'],1080)
        for stage,w,h in (('1',960,544),('2',1920,1088)):
            self.assertEqual(graph['fit_first'+stage]['inputs'],{
                'image':['delivery_first',0],'upscale_method':'bilinear',
                'width':w,'height':h,'crop':'disabled'})
            self.assertEqual(graph['fit_last'+stage]['inputs']['image'],['delivery_last',0])
            self.assertEqual(graph['fit_last'+stage]['inputs']['crop'],'disabled')
        self.assertEqual(graph['restore_output']['inputs'],{
            'image':['decode',0],'upscale_method':'lanczos',
            'width':1920,'height':1080,'crop':'disabled'})
        self.assertEqual(graph['zura_hdr_hlg']['inputs']['image'],['restore_output',0])
        self.assertEqual(graph['zura_hdr_exr']['inputs']['image'],['restore_output',0])
        self.assertEqual(graph['zura_hdr_archive']['inputs']['images'],['restore_output',0])

    def test_portrait_delivery_preserves_an_odd_source_dimension_as_even_mp4(self):
        graph=module.build_native_endpoint_graph(**{
            **self.config(),'width':1088,'height':1920,'frames':17,
            'output_width':1080,'output_height':1920})
        self.assertEqual(graph['delivery_first']['inputs']['width'],1080)
        self.assertEqual(graph['delivery_first']['inputs']['height'],1920)
        self.assertEqual(graph['restore_output']['inputs']['width'],1080)
        self.assertEqual(graph['restore_output']['inputs']['height'],1920)
        self.assertEqual(graph['zura_hdr_video']['inputs']['images'],['zura_hdr_hlg',0])

    def test_every_hdr_output_uses_the_restored_images(self):
        expected={
            'hlg_video':{
                'zura_hdr_hlg':('image',['restore_output',0]),
                'tonemap':('image',['restore_output',0]),
            },
            'acescg_exr':{
                'zura_hdr_exr':('image',['restore_output',0]),
                'zura_hdr_archive':('images',['restore_output',0]),
            },
            'hlg_and_exr':{
                'zura_hdr_hlg':('image',['restore_output',0]),
                'zura_hdr_exr':('image',['restore_output',0]),
                'zura_hdr_archive':('images',['restore_output',0]),
            },
        }
        for output,links in expected.items():
            with self.subTest(output=output):
                graph=module.build_native_endpoint_graph(**{
                    **self.config(),'width':1920,'height':1088,'frames':17,
                    'output_width':1920,'output_height':1080,'output':output})
                for node,(field,link) in links.items():
                    self.assertEqual(graph[node]['inputs'][field],link)
                if output=='hlg_video':
                    self.assertNotIn('zura_hdr_exr',graph)
                    self.assertEqual(graph['preview_video']['inputs']['images'],['tonemap',0])
                elif output=='acescg_exr':
                    self.assertNotIn('zura_hdr_hlg',graph)
                    self.assertEqual(graph['preview_video']['inputs']['images'],['zura_hdr_exr',0])
                else:
                    self.assertEqual(graph['preview_video']['inputs']['images'],['zura_hdr_exr',0])

    def test_without_delivery_size_the_existing_graph_path_is_unchanged(self):
        graph=module.build_native_endpoint_graph(**self.config())
        self.assertNotIn('delivery_first',graph)
        self.assertNotIn('delivery_last',graph)
        self.assertNotIn('restore_output',graph)
        self.assertEqual(graph['fit_first1']['inputs']['image'],['first',0])
        self.assertEqual(graph['fit_first1']['inputs']['crop'],'center')
        self.assertEqual(graph['fit_first2']['inputs']['crop'],'center')
        self.assertEqual(graph['fit_last1']['inputs']['crop'],'center')
        self.assertEqual(graph['fit_last2']['inputs']['crop'],'center')
        self.assertEqual(graph['zura_hdr_hlg']['inputs']['image'],['decode',0])
        self.assertEqual(graph['zura_hdr_exr']['inputs']['image'],['decode',0])
        self.assertEqual(graph['zura_hdr_archive']['inputs']['images'],['decode',0])

    def test_graph_route_propagates_exact_delivery_dimensions(self):
        captured={}
        def build(**values):
            captured.update(values)
            return {}
        endpoint=({'manifest':'first.json','sha':'a'*64},{'width':1920,'height':1088})
        with patch.object(routes,'resolve_endpoint',return_value=endpoint), patch.object(
                routes,'build_native_endpoint_graph',side_effect=build):
            routes.prepare_graph(object(),lambda *_:None,{
                'first_id':'first','width':1920,'height':1088,'frames':17,
                'prompt':'The same scene in motion.','output_width':1920,
                'output_height':1080})
        self.assertEqual(captured['output_width'],1920)
        self.assertEqual(captured['output_height'],1080)

    def test_constraints_reject_sdr_thumbnails_and_overbudget_ranges(self):
        for change in ({'first':{'file':'thumbnail.png'}},{'first':{'manifest':'first.json','sha':'bad'}},
                       {'width':520},{'frames':10},{'width':2048,'height':2048,'frames':17},
                       {'prompt':''},{'seed':True},{'audio_start':float('nan')},{'output':'sdr'},
                       {'first':{'manifest':'first.json','sha':'a'*64,'colour_space':'srgb_display'}},
                       {'output_width':1920},{'output_width':1919,'output_height':1080},
                       {'output_width':4096,'output_height':4096},{'output_width':True,'output_height':1080},
                       {'output_width':4096,'output_height':1080}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                module.build_native_endpoint_graph(**{**self.config(),**change})


if __name__=='__main__':unittest.main()
