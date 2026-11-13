import copy
import importlib.util
from pathlib import Path
import unittest
import torch

spec = importlib.util.spec_from_file_location('ltx_colour_test', Path(__file__).parents[1] / 'comfylink' / 'ltx_colour.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def metadata(encoding='acescg', association='straight'):
    return {'manifest': {'colour': {'encoding': encoding, 'sceneLinear': encoding != 'acescct'}, 'alphaAssociation': association}, 'original_alpha': torch.tensor([[[0., .5, 1.]]]), 'transformations': []}

class LTXColourTests(unittest.TestCase):
    def test_round_trip_negative_toe_highlights_and_alpha(self):
        a = torch.tensor([[[[-.005, .18, 4.], [1., 16., .001], [0., .0078125, 100.]]]], dtype=torch.float32)
        meta = metadata(); old = copy.deepcopy(meta)
        encoded, mid = m.ZuraComfyLinkToLTXColour().convert(a, meta)
        result, out = m.ZuraComfyLinkFromLTXColour().convert(encoded, mid)
        torch.testing.assert_close(result, a, rtol=2e-6, atol=2e-6)
        self.assertTrue(torch.equal(out['original_alpha'], old['original_alpha']))
        self.assertEqual(meta['manifest'], old['manifest'])
        self.assertEqual(out['manifest']['colour'], {'encoding':'acescg','sceneLinear':True})
        self.assertEqual(mid['manifest']['colour'], {'encoding':'acescct','sceneLinear':False})

    def test_rec709_primary_matrix_orientation(self):
        a = torch.tensor([[[[1.,0.,0.], [0.,1.,0.], [0.,0.,1.]]]])
        codes, meta = m.ZuraComfyLinkToLTXColour().convert(a, metadata('scene_linear_rec709'))
        out, _ = m.ZuraComfyLinkFromLTXColour().convert(codes, meta)
        self.assertTrue(torch.allclose(out[0,0], torch.tensor([[.6131,.0702,.0206],[.3395,.9163,.1096],[.0474,.0135,.8698]]), atol=.0003))

    def test_out_of_domain_requires_explicit_clamp_and_reports(self):
        image = torch.tensor([[[[-.02, 1000., .18], [0.,0.,0.], [0.,0.,0.]]]])
        with self.assertRaisesRegex(ValueError, 'outside'):
            m.ZuraComfyLinkToLTXColour().convert(image, metadata())
        x, meta = m.ZuraComfyLinkToLTXColour().convert(image, metadata(), 'clamp')
        report = meta['transformations'][-1]
        self.assertEqual(report['belowZeroCount'], 1)
        self.assertEqual(report['aboveOneCount'], 1)
        self.assertLess(report['codeMin'], 0)
        self.assertGreater(report['codeMax'], 1)
        self.assertEqual(float(x.min()), 0)
        self.assertEqual(float(x.max()), 1)
        bad = x.clone(); bad[0,0,0,0] = -0.2
        with self.assertRaisesRegex(ValueError, 'outside'):
            m.ZuraComfyLinkFromLTXColour().convert(bad, meta)
        _, clamped = m.ZuraComfyLinkFromLTXColour().convert(bad, meta, 'clamp')
        self.assertEqual(clamped['transformations'][-1]['belowZeroCount'], 1)

    def test_reject_ambiguous_metadata_premultiplication_and_nonfinite(self):
        a = torch.zeros((1,1,3,3))
        for meta in (metadata('ae_project_icc'), metadata('acescg', 'premultiplied')):
            with self.assertRaises(ValueError): m.ZuraComfyLinkToLTXColour().convert(a, meta)
        a[0,0,0,0] = float('nan')
        with self.assertRaises(ValueError): m.ZuraComfyLinkToLTXColour().convert(a, metadata())


    def test_short_graph_storage_choice_keeps_display_preview_independent(self):
        spec = importlib.util.spec_from_file_location('delivery_test', Path(__file__).parents[1] / 'artist_studio' / 'hdr_delivery.py')
        delivery = importlib.util.module_from_spec(spec); spec.loader.exec_module(delivery)
        args = dict(output='acescg_exr', prefix='fixture', working_space='ltx25_acescct_qualified')
        default = delivery.ltx_hdr_delivery(['decode', 0], 24, **args)
        full = delivery.ltx_hdr_delivery(['decode', 0], 24, exr_storage='float32', **args)
        # EXR storage is applied by the delivery writer. This graph's output
        # node is a display-only preview and must not quantise the HDR master.
        self.assertEqual(default['zura_hdr_exr']['class_type'], 'ZuraHDRSDRPreview')
        self.assertEqual(default['zura_hdr_exr'], full['zura_hdr_exr'])
        self.assertEqual(default['zura_hdr_exr']['inputs']['image'], ['decode', 0])
        with self.assertRaises(ValueError): delivery.ltx_hdr_delivery(['decode', 0], 24, exr_storage='unknown', **args)


if __name__ == '__main__':
    unittest.main()
