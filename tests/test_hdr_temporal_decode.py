"""Experimental VAE cut keeps exact frame ordering without blend ghosts."""
import importlib
import sys
import types
import unittest

import torch
import v2_bootstrap

name='ComfyUI_zura_nodes.artist_studio'
if name not in sys.modules:
    module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/'artist_studio')];sys.modules[name]=module
node=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_temporal_decode')


class FakeVAE:
    def __init__(self):self.calls=[]
    def temporal_compression_decode(self):return 8
    def spacial_compression_decode(self):return 32
    def decode_tiled(self,samples,**kwargs):
        self.calls.append(samples.shape[2]);start=int(samples[0,0,0,0,0]);count=(samples.shape[2]-1)*8+1
        values=torch.arange(start*8,start*8+count,dtype=torch.float32)
        return values.reshape(1,count,1,1,1).expand(1,count,1,1,3)


class HDRTemporalCutTests(unittest.TestCase):
    def test_overlapping_windows_preserve_all_frames_without_blending(self):
        samples=torch.arange(17.).reshape(1,1,17,1,1);vae=FakeVAE()
        output=node.ZuraHDRTemporalDecodeCut().decode({'samples':samples},vae,64,16,512,64)[0]
        self.assertEqual(vae.calls,[8,8,5]);self.assertEqual(len(output),129)
        self.assertTrue(torch.equal(output[:,0,0,0],torch.arange(129.)))
    def test_invalid_configuration_is_rejected(self):
        samples=torch.zeros(1,1,17,1,1)
        with self.assertRaises(ValueError):node.ZuraHDRTemporalDecodeCut().decode({'samples':samples},FakeVAE(),64,64,512,64)


if __name__=='__main__':unittest.main()
