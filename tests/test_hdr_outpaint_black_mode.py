"""Native HDR black-mask graph parity; no GPU or public route required."""
import copy
import importlib
import unittest
from unittest.mock import patch

import torch
import test_artist_studio

experiment = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_experiment')
planner = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_long_plan')
outpaint = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_studio')
canvas = importlib.import_module('ComfyUI_zura_nodes.artist_studio.ltx_outpaint')
colour = importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')
chunks = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_comfy')


class HDRBlackTests(unittest.TestCase):
    def setUp(self):
        self.source = {'file':'original-hdr.mov','sha':'a'*64,'duration':10.,
                       'width':190,'height':130,'has_audio':True,'asset_kind':'video'}
        self.selection = outpaint.plan(self.source,start=.517,duration=.5,mode='black',
            width=190,height=130,black_threshold=.01)
        self.key = experiment.hdr_review_key(self.selection,'pq_rec2020')

    def stage(self, source=None, selection=None, key=None):
        return experiment.build_reviewed_sdr_first_stage(source or self.source, selection or self.selection,
            review_key=key or self.key,colour_space='pq_rec2020',prefix='genj/hdr_outpaint/blacktest')

    def test_short_review_generation_and_restoration_use_same_hdr_mask(self):
        review,_ = experiment.build_hdr_review_experiment(self.source,self.selection,colour_space='pq_rec2020')
        stage = self.stage()
        final = experiment.build_reviewed_sdr_first_composite(self.source,self.selection,'intermediate.mp4',
            review_key=self.key,colour_space='pq_rec2020',has_audio=True)
        self.assertEqual(review['canvas']['class_type'],'ZuraLTXOutpaintHDRCanvas')
        for graph, name in ((stage,'canvas'),(final,'native_canvas')):
            reference = review['canvas']['inputs']; actual = graph[name]['inputs']
            for field in ('mode','width','height','left','top','right','bottom','black_threshold'):
                self.assertEqual(actual[field],reference[field])
            self.assertEqual(actual['mode'],'black')
        self.assertEqual(stage['canvas']['inputs']['images'],['hdr_input_hold',0])
        self.assertEqual(stage['tone_map_source']['inputs']['image'],['canvas',0])
        self.assertEqual(stage['masked_sdr_guide']['inputs']['mask'],['canvas',1])
        self.assertEqual(stage['masked_sdr_guide']['inputs']['source'],['black_fill',0])
        self.assertEqual(stage['mask_image']['inputs']['mask'],['canvas',1])
        self.assertEqual(stage['low_reference']['inputs']['image'],['masked_sdr_guide',0])
        self.assertEqual(stage['green_high']['inputs']['images'],['masked_sdr_guide',0])
        self.assertEqual(stage['green_high']['inputs']['mask'],['canvas',1])
        self.assertEqual(stage['blend_high']['inputs']['mask'],['canvas',1])
        self.assertEqual(stage['adapter']['inputs']['lora_name'],'ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors')
        self.assertEqual(final['final_hdr_composite']['inputs']['mask'],['native_mask_crop',0])
        self.assertEqual(final['native_mask_crop']['inputs']['mask'],['native_canvas',1])
        self.assertEqual(final['final_hdr_composite']['inputs']['colour_match'],1.0)
        self.assertEqual(final['native_source_crop']['inputs']['width'],190)
        self.assertEqual(final['native_source_crop']['inputs']['height'],130)
        self.assertEqual(final['hdr_original_length']['inputs']['image'],['final_hdr_composite',0])
        self.assertEqual(final['zura_hdr_hlg']['inputs']['image'],['hdr_delivery_hold',0])
        self.assertEqual(final['zura_hdr_archive']['inputs']['images'],['hdr_delivery_hold',0])
        for graph in (stage,final):
            for node in graph.values():
                for value in node['inputs'].values():
                    if isinstance(value,list) and len(value)==2 and isinstance(value[0],str):
                        self.assertIn(value[0],graph,f'dangling connection {value}')

    def test_audio_and_padding_are_explicit(self):
        stage=self.stage()
        self.assertEqual(stage['source_audio']['inputs']['start_seconds'],.517)
        self.assertEqual(stage['source_audio']['inputs']['source_duration'],.5)
        self.assertEqual(stage['stage_audio']['inputs']['frames'],17)
        self.assertEqual(stage['audio_encoded']['inputs']['audio'],['stage_audio',0])
        silent=self.stage({**self.source,'has_audio':False})
        self.assertEqual(silent['stage_audio']['class_type'],'EmptyAudio')
        self.assertEqual(silent['stage_audio']['inputs']['duration'],17/24)
        self.assertNotIn('source_audio',silent)
        with self.assertRaisesRegex(ValueError,'has audio'):
            self.stage({k:v for k,v in self.source.items() if k!='has_audio'})
        self.assertEqual(stage['trim_result']['inputs']['length'],17)
        self.assertEqual(stage['stage_video']['inputs']['images'],['trim_result',0])

    def test_review_binds_mode_and_threshold(self):
        for change in ({'black_threshold':.02},{'mode':'expand'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.stage(selection={**self.selection,**change})
        with self.assertRaisesRegex(ValueError,'approve'):
            self.stage(key='wrong')

    def test_native_mask_uses_linear_light_and_preserves_unselected_interior(self):
        linear=torch.full((1,130,190,3),2.)
        linear[:,:20] = 0
        linear[:,75:80,80:90] = .005
        encoded=colour.encode_ct(linear)
        prepared,mask=canvas.prepare_hdr_canvas(encoded,'black',192,192,black_threshold=.01)
        self.assertEqual(mask.shape,(1,192,192))
        self.assertTrue(bool((mask[0,:20,:190]==1).all()))
        self.assertTrue(bool((mask[0,75:80,80:90]==1).all()))
        self.assertTrue(bool((mask[0,30:65,20:170]==0).all()))
        self.assertTrue(bool((mask[0,130:,:]==1).all()))
        generated=colour.encode_ct(torch.full_like(prepared,3.))
        mixed=canvas.composite_hdr_outpaint(generated,prepared,mask,8,1.)
        self.assertTrue(torch.equal(mixed[:,35:60,30:160],prepared[:,35:60,30:160]))
        self.assertGreater(float(colour.decode_ct(mixed[0,40,40]).max()),1.)

    def test_long_selection_and_every_section_keep_mask_and_crop(self):
        settings=dict(start=.517,duration=5.,mode='black',width=190,height=130,
            left=0,top=0,right=0,bottom=0,colour_space='pq_rec2020',black_threshold=.01)
        full,parts,subs=planner.plan_hdr_windows(self.source,**settings)
        self.assertGreater(len(parts),1)
        self.assertEqual(full['mode'],'black')
        self.assertTrue(all(s['mode']=='black' and s['black_threshold']==.01 for s in subs))
        changed,_,_=planner.plan_hdr_windows(self.source,**{**settings,'black_threshold':.02})
        self.assertNotEqual(changed['review_key'],full['review_key'])
        for index,sub in enumerate(subs):
            stage=planner.build_long_hdr_sdr_window(self.source,full,sub,review_key=full['review_key'],
                anchor_file='genj_studio/anchors/previous.png' if index else None)
            self.assertEqual(stage['masked_sdr_guide']['inputs']['mask'],['canvas',1])
            self.assertEqual(stage['stage_video']['inputs']['images'],['stage_unpad',0])
            self.assertEqual(stage['stage_unpad']['inputs']['width'],190)
            self.assertEqual(stage['stage_unpad']['inputs']['height'],130)
            self.assertEqual(stage['trim_result']['inputs']['length'],sub['frames'])
            if index:
                self.assertEqual(stage['zura_anchor_i2v']['inputs']['image'],['zura_anchor_pad',0])
                self.assertEqual(stage['zura_anchor_pad']['inputs'],{
                    'destination':['zura_anchor_canvas',0], 'source':['zura_anchor_image',0],
                    'x':0, 'y':0, 'resize_source':False})
                self.assertEqual(stage['zura_anchor_canvas']['inputs'],{
                    'width':192, 'height':192, 'batch_size':1, 'color':0})
            else:
                self.assertNotIn('zura_anchor_pad',stage)
            final=planner.build_long_hdr_conversion_window(self.source,full,sub,'assembled.mp4',
                review_key=full['review_key'],prompt_start_frame=parts[index].start)
            self.assertEqual(final['native_canvas']['inputs']['mode'],'black')
            self.assertEqual(final['native_canvas']['inputs']['black_threshold'],.01)
            self.assertEqual(final['native_mask_crop']['inputs']['mask'],['native_canvas',1])
            self.assertEqual(final['final_hdr_composite']['inputs']['mask'],['native_mask_crop',0])
            self.assertEqual(final['final_hdr_composite']['inputs']['colour_match'],1.0)
            self.assertEqual((final['native_mask_crop']['inputs']['width'],final['native_mask_crop']['inputs']['height']),(190,130))
            self.assertEqual((final['hdr_generated_crop']['inputs']['width'],final['hdr_generated_crop']['inputs']['height']),(190,130))
            store=type('Store',(),{'plan':parts,'identity':'a'*32,'width':190,'height':130})()
            staged=chunks.chunk_graph(final,store,index,'final_hdr_composite',anchor_strength=.75,anchor_mode='i2v')
            self.assertEqual(staged['zura_hdr_stage_chunk']['inputs']['images'],['final_hdr_composite',0])
        stale=copy.deepcopy(full);stale['black_threshold']=.02
        with self.assertRaisesRegex(ValueError,'selection changed'):
            planner.build_long_hdr_sdr_window(self.source,stale,subs[0],review_key=full['review_key'])

    def test_actual_comfy_nodes_pad_without_resampling_pixels(self):
        try:
            import nodes
            from comfy_extras.nodes_mask import ImageCompositeMasked
            import comfy.model_management
        except ImportError:
            self.skipTest('The installed ComfyUI nodes are unavailable.')
        # Nonuniform data catches even a subtle resize, shift or crop.
        source = torch.arange(130*190*3,dtype=torch.float32).reshape(1,130,190,3)/(130*190*3)
        with patch.object(comfy.model_management,'intermediate_device',return_value=torch.device('cpu')):
            black = nodes.EmptyImage().generate(width=192,height=192,batch_size=1,color=0)[0]
        result = ImageCompositeMasked.execute(destination=black,source=source,x=0,y=0,resize_source=False)[0]
        self.assertEqual(tuple(result.shape),(1,192,192,3))
        self.assertTrue(torch.equal(result[:,:130,:190],source))
        self.assertEqual(torch.count_nonzero(result[:,130:,:,:]).item(),0)
        self.assertEqual(torch.count_nonzero(result[:,:,190:,:]).item(),0)


if __name__ == '__main__':
    unittest.main()
