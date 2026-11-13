import importlib.util
from pathlib import Path
import unittest
import torch

spec=importlib.util.spec_from_file_location('qwen_edit_canvas',Path(__file__).parents[1]/'artist_studio/qwen_edit_canvas.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class QwenCanvasTest(unittest.TestCase):
    def test_native_reference_size_and_samples_are_retained(self):
        # A 512px source is internally encoded at1024px by Edit Plus. A canvas
        # derived from that conditioning must stay128 latents wide, not64.
        for shape in [(1,16,128,128),(1,16,96,171),(1,16,171,96),(1,16,1,128,128)]:
            ref=torch.arange(torch.tensor(shape).prod().item(),dtype=torch.float32).reshape(shape)
            samples=module.ZuraQwenEditLatent().canvas([[None,{'reference_latents':[ref,torch.zeros(1,16,32,32)]}]])[0]['samples']
            self.assertEqual(samples.shape,ref.shape)
            self.assertTrue(torch.equal(samples,ref))
            samples.zero_()
            self.assertNotEqual(ref.count_nonzero().item(),0,'Sampling cannot mutate the encoded reference')

    def test_missing_or_inconsistent_references_fail_clearly(self):
        canvas=module.ZuraQwenEditLatent().canvas
        for conditioning in [[],[[None,{}]],[[None,{'reference_latents':[]}]],[[None,{'reference_latents':['not a latent']}]],
                             [[None,{'reference_latents':[torch.zeros(2,16,32,32)]}]],
                             [[None,{'reference_latents':[torch.zeros(1,16,32,32)]}],[None,{'reference_latents':[torch.zeros(1,16,64,64)]}]]]:
            with self.assertRaises(ValueError):canvas(conditioning)


if __name__=='__main__':unittest.main()
