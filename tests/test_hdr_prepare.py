import importlib.util
from pathlib import Path
import unittest
import torch

spec=importlib.util.spec_from_file_location('hdr_prepare',Path(__file__).parents[1]/'artist_studio/hdr_prepare.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class PrepareHDR(unittest.TestCase):
    def test_pads_and_can_recover_unchanged_source(self):
        source=torch.rand(14,41,65,3)
        result,w,h,n,pw,ph,pn=module.pad_sdr_guide(source)
        self.assertEqual((w,h,n,pw,ph,pn),(65,41,14,96,64,17))
        self.assertTrue(torch.equal(result[:n,:h,:w],source))
        self.assertTrue(torch.equal(result[-1,:h,:w],source[-1]))
        self.assertTrue(torch.equal(result[n:,:h,:w],source[-1:].expand(3,-1,-1,-1)))
    def test_short_input_held_to_nine(self):
        result,*values=module.pad_sdr_guide(torch.full((1,32,32,3),0.5))
        self.assertEqual(result.shape,(9,32,32,3));self.assertEqual(values[-1],9)
    def test_refuses_extended_or_invalid_input(self):
        for source in (torch.ones((1,32,32,3))*2,torch.full((1,32,32,3),float('nan')),torch.zeros((122,32,32,3))):
            with self.assertRaises(ValueError):module.pad_sdr_guide(source)
    def test_trim_audio_preserves_exact_selected_duration(self):
        audio={'waveform':torch.ones((1,2,48000)),'sample_rate':48000}
        trimmed=module.ZuraHDRTrimAudio().trim(audio,14,24)[0]
        self.assertEqual(trimmed['waveform'].shape[-1],28000)
        self.assertEqual(audio['waveform'].shape[-1],48000)
        with self.assertRaises(ValueError):module.ZuraHDRTrimAudio().trim(audio,100,24)

if __name__=='__main__':unittest.main()
