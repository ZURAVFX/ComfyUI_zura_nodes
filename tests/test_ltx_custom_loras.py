"""The optional user adapter must reach every LTX sampler without replacing its guide."""
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_artist_studio  # registers the package fixture
import folder_paths

loras=importlib.import_module('ComfyUI_zura_nodes.artist_studio.custom_loras')
outpaint=importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_studio')
masked=importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_long_masked')
hdr=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_studio')
native=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_native_graph')


class LTXCustomLoraTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.file=Path(self.tmp.name)/'ltx-style.safetensors'
        header=json.dumps({'__metadata__':{'base_model':'ltx-2.5'},'diffusion_model.x':{}}).encode()
        self.file.write_bytes(len(header).to_bytes(8,'little')+header)
        self.choice={'name':self.file.name,'strength':.6,'confirm_unknown':False}

    def apply(self,graph):
        with patch.object(folder_paths,'get_filename_list',return_value=[self.file.name]), patch.object(folder_paths,'get_full_path',return_value=str(self.file)):
            return loras.apply_installed_ltx_loras(graph,[self.choice])

    def test_workflows_chain_user_lora_before_required_guidance(self):
        source={'file':'genj_studio/abc/source.mp4','sha':'a'*64,'duration':8,'width':768,'height':432}
        selection=outpaint.plan(source,start=0,duration=1,mode='expand',width=1152,height=640,left=128,right=128)
        graphs=[
            (outpaint.build_studio_graph(source,selection,review_key=selection['review_key'],output_prefix='genj/outpaint/test'),'adapter','model'),
            (masked.build_masked_expand_graph(source,selection,review_key=selection['review_key'],output_prefix='genj/outpaint/test'),'adapter','model'),
            (hdr.build_hdr_graph(source='source.mp4',start_frame=0,frame_count=9,fps=24,prefix='test'),'hdr_lora','hdr_model'),
            (native.build_native_video_graph(source='source.mp4',start_frame=0,frame_count=9,fps=24,width=384,height=224,prefix='test'),'lora','model'),
        ]
        for graph,adapter,model in graphs:
            with self.subTest(adapter=adapter,model=model):
                before=graph[adapter]['inputs']['lora_name'];patched=self.apply(graph)
                self.assertEqual(patched[adapter]['inputs']['model'],['zura_custom_lora_0_0',0])
                self.assertEqual(patched[adapter]['inputs']['lora_name'],before)
                self.assertEqual(patched['zura_custom_lora_0_0']['inputs']['model'],[model,0])
                self.assertEqual(patched['zura_custom_lora_0_0']['inputs']['strength_model'],.6)
                self.assertEqual(graph[adapter]['inputs']['model'],[model,0])

    def test_incompatible_or_unconfirmed_loras_cannot_be_added(self):
        graph={'model':{'class_type':'UNETLoader','inputs':{'unet_name':'ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors'}}}
        header=json.dumps({'__metadata__':{'base_model':'minimax_h3'},'diffusion_model.x':{}}).encode()
        self.file.write_bytes(len(header).to_bytes(8,'little')+header)
        with self.assertRaisesRegex(ValueError,'incompatible'):self.apply(graph)

    def test_wan_high_and_low_adapters_only_touch_their_own_phase(self):
        header=json.dumps({'__metadata__':{'base_model':'wan2.2'},'diffusion_model.x':{}}).encode()
        self.file.write_bytes(len(header).to_bytes(8,'little')+header)
        graph={}
        for phase in ('high','low'):
            graph[phase+'_model']={'class_type':'UNETLoader','inputs':{'unet_name':f'WAN/wan2.2_i2v_{phase}_noise_14B_fp8_scaled.safetensors'}}
            graph[phase+'_turbo']={'class_type':'LoraLoaderModelOnly','inputs':{'model':[phase+'_model',0],'lora_name':phase+'_turbo.safetensors','strength_model':1}}
        resolve=lambda folder,name:str(self.file)
        high=loras.apply_studio_video_loras(graph,'wan22_high',[self.choice],[self.file.name],resolve)
        self.assertEqual(high['high_turbo']['inputs']['model'],['zura_custom_lora_high_0_0',0])
        self.assertEqual(high['low_turbo']['inputs']['model'],['low_model',0])
        both=loras.apply_studio_video_loras(high,'wan22_low',[self.choice],[self.file.name],resolve)
        self.assertEqual(both['high_turbo']['inputs']['model'],['zura_custom_lora_high_0_0',0])
        self.assertEqual(both['low_turbo']['inputs']['model'],['zura_custom_lora_low_0_0',0])
        self.assertEqual(both['low_turbo']['inputs']['lora_name'],'low_turbo.safetensors')
        bad=dict(graph);bad['high_model']=graph['low_model']
        with self.assertRaisesRegex(ValueError,'noise phase'):
            loras.apply_studio_video_loras(bad,'wan22_high',[self.choice],[self.file.name],resolve)
        bad_choice=dict(self.choice,name='low_noise_character.safetensors')
        with self.assertRaisesRegex(ValueError,'other Wan noise phase'):
            loras.apply_studio_video_loras(graph,'wan22_high',[bad_choice],[bad_choice['name']],resolve)


if __name__=='__main__':unittest.main()
