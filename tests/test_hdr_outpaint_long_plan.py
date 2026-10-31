import importlib
import types
import unittest

import test_artist_studio

module = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_long_plan')
chunks = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunks')
comfy = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_comfy')


class HDRLongPlanTests(unittest.TestCase):
    def setUp(self):
        self.source = {'file':'source.mp4','sha':'a'*64,'asset_kind':'video',
                       'duration':20,'width':1920,'height':1080}
        self.settings = dict(start=.517, duration=4., width=1088, height=640,
                             left=128, top=96, right=128, bottom=96, colour_space='pq_rec2020')

    def test_source_budget_bounds_windows_even_with_small_output(self):
        selected, parts, subplans = module.plan_hdr_windows(self.source, **self.settings)
        self.assertEqual(selected['frames'], 96)
        self.assertEqual(sum(part.count-part.overlap for part in parts), 96)
        self.assertTrue(all(part.count * 1920 * 1080 <= module.MAX_PIXEL_FRAMES for part in parts))
        self.assertTrue(all(sub['padded_frames'] * 1920 * 1080 <= module.MAX_PIXEL_FRAMES for sub in subplans))
        for i in range(1,len(parts)):
            self.assertEqual(parts[i].start, parts[i-1].start+parts[i-1].count-parts[i].overlap)
            self.assertAlmostEqual(subplans[i]['start'], .517+parts[i].start/24)
        self.assertTrue(all(sub['padded_frames'] <= 113 for sub in subplans))

    def test_review_key_binds_hdr_colour_and_full_geometry(self):
        first, _, _ = module.plan_hdr_windows(self.source, **self.settings)
        changed, _, _ = module.plan_hdr_windows(self.source, **{**self.settings,'colour_space':'hlg_rec2020'})
        self.assertNotEqual(first['review_key'], changed['review_key'])
        fractional, _, _ = module.plan_hdr_windows(self.source, **{**self.settings,'duration':3.99})
        self.assertEqual(first['frames'], fractional['frames'])
        self.assertNotEqual(first['review_key'], fractional['review_key'])
        with self.assertRaisesRegex(ValueError, 'within the HDR source'):
            module.plan_hdr_windows(self.source, **{**self.settings,'duration':30})

    def test_anchored_window_keeps_exact_source_and_full_review(self):
        full, parts, subs = module.plan_hdr_windows(self.source, **self.settings)
        graph = module.build_long_hdr_sdr_window(self.source, full, subs[1], review_key=full['review_key'],
            anchor_file='genj_studio/anchors/previous.png')
        self.assertAlmostEqual(graph['hdr_source']['inputs']['start_seconds'], .517+parts[1].start/24)
        self.assertEqual(graph['hdr_source']['inputs']['frame_count'], subs[1]['frames'])
        self.assertEqual(graph['trim_result']['inputs']['length'], subs[1]['frames'])
        self.assertEqual(graph['guide']['inputs']['latent'], ['zura_anchor_i2v',0])
        self.assertEqual(graph['guide']['inputs']['image'], ['canvas',0])
        self.assertEqual(graph['zura_anchor_image']['inputs']['image'],'genj_studio/anchors/previous.png')
        self.assertEqual(graph['zura_anchor_i2v']['inputs']['image'],['zura_anchor_image',0])
        self.assertNotIn('zura_anchor_pad',graph,'Expanded-canvas continuation must remain unchanged')
        with self.assertRaisesRegex(ValueError, 'full HDR selection changed'):
            module.build_long_hdr_sdr_window(self.source,{**full,'left':127},subs[1],review_key=full['review_key'])
        with self.assertRaisesRegex(ValueError, 'does not belong'):
            module.build_long_hdr_sdr_window(self.source,full,{**subs[1],'frames':3},review_key=full['review_key'])
        with self.assertRaisesRegex(ValueError, 'anchor frame'):
            module.build_long_hdr_sdr_window(self.source,full,subs[1],review_key=full['review_key'],anchor_file='../outside.png')

    def test_full_review_preview_uses_each_exact_hdr_section(self):
        full,parts,subs=module.plan_hdr_windows(self.source,**self.settings)
        graph=module.build_long_hdr_review_window(self.source,full,subs[1],review_key=full['review_key'])
        self.assertAlmostEqual(graph['hdr_source']['inputs']['start_seconds'],.517+parts[1].start/24)
        self.assertEqual(graph['hdr_source']['inputs']['frame_count'],parts[1].count)
        self.assertEqual(graph['canvas']['inputs']['left'],full['left'])
        self.assertEqual(graph['overlay']['inputs']['mask'],['canvas',1])
        with self.assertRaisesRegex(ValueError,'full HDR selection changed'):
            module.build_long_hdr_review_window(self.source,{**full,'colour_space':'hlg_rec2020'},subs[1],review_key=full['review_key'])

    def test_too_large_source_fails_before_render(self):
        with self.assertRaisesRegex(ValueError, 'memory budget'):
            module.plan_hdr_windows({**self.source,'width':7680,'height':4320}, **self.settings)

    def test_hdr_conversion_uses_same_time_and_chunk_writer_plan(self):
        full, parts, subs = module.plan_hdr_windows(self.source, **self.settings)
        graph = module.build_long_hdr_conversion_window(self.source, full, subs[1], 'assembled.mp4',
            review_key=full['review_key'], prompt_start_frame=parts[1].start)
        self.assertEqual(graph['zura_hdr_source']['inputs']['start_frame'],parts[1].start)
        self.assertAlmostEqual(graph['native_original']['inputs']['start_seconds'],.517+parts[1].start/24)
        self.assertEqual(graph['native_original']['inputs']['frame_count'],parts[1].count)
        self.assertEqual(graph['final_hdr_composite']['inputs']['source'],['native_canvas',0])
        self.assertEqual(graph['final_hdr_composite']['inputs']['colour_match'], 1.0,
                         'Every HDR section must use the same bounded seam matching as the short route')
        store=types.SimpleNamespace(plan=parts,identity='a'*32,width=1088,height=640)
        staged=comfy.chunk_graph(graph,store,1,'final_hdr_composite',anchor_strength=.75,anchor_mode='i2v')
        self.assertEqual(staged['zura_hdr_stage_chunk']['inputs']['images'],['final_hdr_composite',0])
        self.assertEqual(staged['final_hdr_composite']['inputs']['colour_match'], 1.0)
        self.assertEqual(staged['hdr_guide']['inputs']['latent'],['zura_hdr_sdr_anchor',0])
        rebuilt=chunks.plan_chunks(0,full['frames'],1088,640,overlap=full['overlap'],max_frames=parts[0].count)
        self.assertEqual([(p.start,p.count,p.overlap) for p in parts],[(p.start,p.count,p.overlap) for p in rebuilt])
        with self.assertRaisesRegex(ValueError,'does not belong'):
            module.build_long_hdr_conversion_window(self.source,full,subs[1],'assembled.mp4',review_key=full['review_key'],prompt_start_frame=0)
