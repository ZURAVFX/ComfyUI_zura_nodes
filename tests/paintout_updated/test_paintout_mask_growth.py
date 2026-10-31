"""CPU mask growth must retain the native square-pooling result exactly."""
import importlib
from pathlib import Path
import sys
import types
import unittest

import torch
import torch.nn.functional as F

package=types.ModuleType('zura_mask_growth_test')
package.__path__=[str(Path(__file__).resolve().parents[2]/'paintout')]
sys.modules.setdefault(package.__name__,package)
core=importlib.import_module(package.__name__+'.paintout')


class MaskGrowthTests(unittest.TestCase):
    def test_exact_native_square_dilation_and_frame_isolation(self):
        random=torch.rand((3,23,37),generator=torch.Generator().manual_seed(18))
        borders=torch.zeros((3,23,37))
        borders[0,0,0]=1
        borders[1,-1,-1]=.75
        borders[2,11,18]=.5
        for mask in (random,borders,torch.zeros_like(borders)):
            for grow in (0,1,5,55):
                with self.subTest(grow=grow,case=float(mask.sum())):
                    expected=F.max_pool2d(mask[:,None],2*grow+1,1,grow)[:,0] if grow else mask
                    actual=core.grow_frame_masks(mask,grow)
                    self.assertTrue(torch.equal(expected,actual))
                    self.assertEqual(actual.dtype,mask.dtype)
                    self.assertEqual(actual.device,mask.device)


if __name__=='__main__':
    unittest.main()
