import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('hdr_probe',Path(__file__).parents[1]/'artist_studio/hdr_probe.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class HDRProbe(unittest.TestCase):
    def test_known_and_untagged_inputs(self):
        self.assertEqual(module.classify_transfer(16),'hdr_pq')
        self.assertEqual(module.classify_transfer(18),'hdr_hlg')
        self.assertEqual(module.classify_transfer(1),'sdr')
        self.assertEqual(module.classify_transfer(13),'sdr')
        self.assertEqual(module.classify_transfer(2),'unknown')
        self.assertEqual(module.classify_transfer(8),'unknown')  # linear may be scene-referred HDR
        self.assertEqual(module.classify_transfer(None),'unknown')

if __name__=='__main__':unittest.main()
