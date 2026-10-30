"""HDR chunk limits and colour-managed boundary arithmetic."""
import importlib
import sys
import types
import unittest

import torch
import v2_bootstrap

for name, path in [('ComfyUI_zura_nodes.artist_studio', 'artist_studio'),
                   ('ComfyUI_zura_nodes.paintout', 'paintout')]:
    if name not in sys.modules:
        module=types.ModuleType(name)
        module.__path__=[str(v2_bootstrap.ROOT / path)]
        sys.modules[name]=module

chunks=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunks')
colour=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


class HDRChunkTests(unittest.TestCase):
    def test_exact_coverage_across_boundaries_and_budget(self):
        for width, height in [(384, 224), (1280, 720), (1920, 1080), (2048, 2048)]:
            for count in (1, 9, 121, 122, 243):
                ranges=chunks.plan_chunks(7, count, width, height)
                canvas_width=max(512, ((width+63)//64)*64)
                canvas_height=max(512, ((height+63)//64)*64)
                coverage=[0]*count
                for index, part in enumerate(ranges):
                    padded=max(9, 1+8*((part.count-1+7)//8))
                    self.assertLessEqual(padded, 121)
                    self.assertLessEqual(canvas_width*canvas_height*padded, 40_000_000)
                    self.assertEqual(part.overlap, 0 if index == 0 else ranges[index-1].start+ranges[index-1].count-part.start)
                    for frame in range(part.start, part.start+part.count): coverage[frame-7]+=1
                self.assertTrue(all(1 <= covered <= 2 for covered in coverage))
                self.assertEqual(ranges[-1].start+ranges[-1].count, 7+count)

    def test_blend_occurs_in_linear_light_not_log_code_values(self):
        a=colour.encode_ct(torch.zeros((3,1,1,3)))
        b=colour.encode_ct(torch.full((3,1,1,3), 2.0))
        result=colour.decode_ct(chunks.blend_acescct_overlap(a,b))
        self.assertTrue(torch.allclose(result[:,0,0,0],torch.tensor([.5,1.,1.5]),atol=2e-6))

    def test_matching_frames_remain_unchanged(self):
        data=colour.encode_ct(torch.rand((8,3,2,3))*4)
        self.assertTrue(torch.allclose(chunks.blend_acescct_overlap(data,data),data,atol=1e-6))

    def test_streamed_stitch_preserves_frame_order_and_source_values(self):
        plan=chunks.plan_chunks(11, 247, 1920, 1080)
        source=colour.encode_ct(torch.arange(247,dtype=torch.float32).reshape(-1,1,1,1).expand(-1,1,1,3)/100)
        rendered=(source[part.start-11:part.start-11+part.count] for part in plan)
        result=torch.cat(list(chunks.stitch_acescct_batches(plan,rendered)))
        self.assertEqual(len(result),len(source))
        self.assertTrue(torch.allclose(result,source,atol=1e-6))

    def test_streamed_stitch_fails_on_missing_or_short_chunk(self):
        plan=chunks.plan_chunks(0, 30, 1920, 1080)
        self.assertGreater(len(plan),1)
        valid=[torch.zeros(part.count,1,1,3) for part in plan]
        with self.assertRaisesRegex(ValueError,'missing'):
            list(chunks.stitch_acescct_batches(plan,valid[:-1]))
        valid[-1]=valid[-1][:-1]
        with self.assertRaisesRegex(ValueError,'wrong frame count'):
            list(chunks.stitch_acescct_batches(plan,valid))

    def test_hard_cut_uses_lowest_adjacent_difference_without_double_exposure(self):
        left=torch.full((5,1,1,3),.1)
        right=torch.tensor([.9,.7,.1,.8,.9]).reshape(5,1,1,1).expand(-1,1,1,3)
        self.assertEqual(chunks.choose_overlap_cut(left,right,3),2)
        plan=[chunks.HDRChunk(0,5,0),chunks.HDRChunk(2,5,3)]
        result=torch.cat(list(chunks.stitch_acescct_batches(plan,[left,right],strategy='cut')))
        self.assertEqual(len(result),7)
        self.assertTrue(torch.equal(result[:,0,0,0],torch.tensor([.1,.1,.1,.1,.1,.8,.9])))

    def test_invalid_input_fails_before_render(self):
        for args in [(-1,1,512,512), (0,0,512,512), (0,10001,512,512), (0,10,511,512), (0,10,512,512,0)]:
            with self.assertRaises(ValueError): chunks.plan_chunks(*args)
        with self.assertRaises(ValueError): chunks.blend_acescct_overlap(torch.zeros(1,2,2,3),torch.zeros(2,2,2,3))

    def test_small_chunk_limit_allows_real_boundary_smoke_tests(self):
        ranges=chunks.plan_chunks(0,10,384,224,max_frames=9)
        self.assertEqual(ranges,[chunks.HDRChunk(0,9,0),chunks.HDRChunk(5,5,4)])
        with self.assertRaises(ValueError):chunks.plan_chunks(0,10,384,224,max_frames=8)


if __name__=='__main__': unittest.main()
