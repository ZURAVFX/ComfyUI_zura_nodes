import importlib.util
from pathlib import Path
import unittest
import torch

spec=importlib.util.spec_from_file_location('ripple_adapter',Path(__file__).resolve().parents[1]/'paintout/ripple.py')
ripple=importlib.util.module_from_spec(spec);spec.loader.exec_module(ripple)

class RippleGuideTests(unittest.TestCase):
    def fixture(self):
        images=torch.arange(97,dtype=torch.float32).reshape(97,1,1,1).expand(-1,2,2,3).clone()
        return {'processing':'SDR (sRGB)','space':'srgb_display','count':94,'_work_images':images},[(0,torch.full_like(images[:1],999),1)]
    def test_prepend_alignment_preserves_every_source_frame_and_held_tail(self):
        plate,anchors=self.fixture();guide,length=ripple.ZuraRippleGuide().prepare(plate,anchors)
        self.assertEqual(length,105);self.assertEqual(length%8,1)
        self.assertTrue(torch.equal(guide[:1],anchors[0][1]))
        self.assertTrue(torch.equal(guide[1:98],plate['_work_images']))
        self.assertTrue(torch.equal(guide[-7:],plate['_work_images'][-1:].expand(7,-1,-1,-1)))
        self.assertTrue(torch.equal(guide[1:1+plate['count']],plate['_work_images'][:plate['count']]))
    def test_later_multiple_hdr_and_dimension_mismatches_are_rejected(self):
        plate,anchors=self.fixture();adapter=ripple.ZuraRippleGuide()
        for invalid in ([],[(7,anchors[0][1],1)],anchors+anchors):
            with self.assertRaisesRegex(ValueError,'first selected'):adapter.prepare(plate,invalid)
        for space in ('hlg_rec2020','pq_rec2020','acescg'):
            with self.assertRaisesRegex(ValueError,'SDR'):adapter.prepare({**plate,'space':space},anchors)
        with self.assertRaisesRegex(ValueError,'dimensions'):adapter.prepare(plate,[(0,torch.zeros(1,3,2,3),1)])
        with self.assertRaisesRegex(ValueError,'8n'):adapter.prepare({**plate,'_work_images':plate['_work_images'][:-1]},anchors)

if __name__=='__main__':unittest.main()
