"""HDR setup reports files and nodes from the selected real graph."""
import importlib
import sys
import types
import unittest
import v2_bootstrap

name='ComfyUI_zura_nodes.artist_studio'
if name not in sys.modules:
    module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/'artist_studio')];sys.modules[name]=module
setup=importlib.import_module(name+'.hdr_readiness')
sdr=importlib.import_module(name+'.hdr_studio')
native=importlib.import_module(name+'.hdr_native_graph')


class HDRReadinessTests(unittest.TestCase):
    def test_sdr_checks_full_vae_and_conditioning_used_by_graph(self):
        graph=sdr.build_hdr_graph(source='source.mp4',start_frame=0,frame_count=9,fps=24,output='hlg_and_exr',prefix='test')
        nodes={node['class_type']:object() for node in graph.values()}
        nodes.pop('LTXVLoadConditioning')
        missing={'ltx-2.5-video-vae-bf16.safetensors','ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors'}
        result=setup.readiness('sdr','hlg_and_exr',lambda folder,name:None if name in missing else '/installed',nodes)
        self.assertEqual(result['route'],'hdr_sdr');self.assertFalse(result['ready'])
        self.assertEqual({x['filename'] for x in result['files'] if not x['ready']},missing)
        self.assertIn('LTXVLoadConditioning',result['missingNodes'])
        self.assertEqual(len(result['files']),len({(x['folder'],x['filename']) for x in result['files']}))

    def test_native_checks_only_the_selected_delivery_graph(self):
        graph=native.build_native_video_graph(source='source.mp4',start_frame=0,frame_count=9,fps=24,width=512,height=512,output='hlg_video',prefix='test')
        nodes={node['class_type']:object() for node in graph.values()}
        result=setup.readiness('native','hlg_video',lambda folder,name:'/installed',nodes)
        self.assertTrue(result['ready']);self.assertEqual(result['route'],'hdr_native')
        names={x['filename'] for x in result['files']}
        self.assertIn('ltx-2.5-video-vae-bf16.safetensors',names)
        self.assertIn('gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors',names)
        both=setup.readiness('native','hlg_and_exr',lambda folder,name:'/installed',nodes)
        self.assertIn('ZuraHDRPackageEXR',both['missingNodes'])

    def test_invalid_modes_and_outputs_are_rejected(self):
        for mode,output in [('sdr','invalid'),('unknown','hlg_video')]:
            with self.subTest(mode=mode,output=output),self.assertRaises(ValueError):
                setup.readiness(mode,output,lambda *_:'/installed',{})


if __name__=='__main__':unittest.main()
