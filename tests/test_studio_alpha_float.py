"""CPU-only precision proof for AE alpha masters; no inference or media codecs."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfylink import float_io
from comfylink.studio_alpha import write_ae_alpha


class AEAlphaFloatTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.input = Path(self.temp.name)/'input'; self.input.mkdir()
        self.output = Path(self.temp.name)/'output'; self.output.mkdir()
        self.pixels = np.array([[[[-.25, 2.0, .1234567, .75], [3.2, -.01, .5, 0.0]]]], dtype=np.float32)
        self.session = 'a'*32
        _, self.manifest = float_io.write_transfer(self.input, 'ComfyLink/'+self.session, self.pixels,
            colour={'encoding':'unknown','sceneLinear':False}, frame_rate={'numerator':30000,'denominator':1001},
            source_start={'numerator':1001,'denominator':30000})
        self.contract = {'schemaVersion':1,'sessionId':self.session,'frameCount':1,'modelFrames':9,'trimFrames':1,
            'width':2,'height':1,'frameRate':self.manifest['frameRate'],
            'sourceManifestSha256':hashlib.sha256(float_io.canonical_manifest_bytes(self.manifest)).hexdigest()}
        self.info = {'width':2,'height':1,'frame_count':1,'content_width':2,'content_height':1,
            'start_frame':0,'fps_rational':'30000/1001'}
        self.matte = torch.tensor([[[[.1234567]*3,[.7]*3]]],dtype=torch.float32)

    def test_float_matte_preserves_hdr_hidden_rgb_and_source_clock(self):
        relative, manifest = write_ae_alpha(self.input,self.output,self.contract,self.info,self.matte)
        frame = next(float_io.iter_transfer(self.output,relative))
        np.testing.assert_array_equal(frame[...,:3].view(np.uint32),self.pixels[0,...,:3].view(np.uint32))
        self.assertEqual(frame[0,0,3],np.float32(.75)*np.float32(.1234567))
        self.assertNotEqual(frame[0,0,3],np.float32(round(float(frame[0,0,3])*65535)/65535))
        self.assertEqual(frame[0,1,3],0)
        self.assertEqual(manifest['sourceBitDepth'],32)
        for key in ('frameRate','sourceStart','colour'):
            self.assertEqual(manifest[key],self.manifest[key])

    def test_float_resize_precedes_quantisation(self):
        info={**self.info,'content_width':1}
        matte=torch.tensor([[[[.31415927]*3]]],dtype=torch.float32)
        relative,_=write_ae_alpha(self.input,self.output,self.contract,info,matte)
        frame=next(float_io.iter_transfer(self.output,relative))
        self.assertEqual(frame[0,0,3],np.float32(.75)*np.float32(.31415927))

    def test_wrong_source_rate_count_raster_or_hash_rejected(self):
        for patch in ({'sourceManifestSha256':'b'*64},{'sessionId':'b'*32},{'width':3},
                      {'frameCount':2,'trimFrames':2},{'frameRate':{'numerator':25,'denominator':1}}):
            with self.subTest(patch=patch), self.assertRaises((ValueError,FileNotFoundError)):
                write_ae_alpha(self.input,self.output,{**self.contract,**patch},self.info,self.matte)
        self.assertEqual(list(self.output.iterdir()),[])

    def test_nonfinite_matte_and_source_alpha_rejected(self):
        with self.assertRaises(ValueError):
            write_ae_alpha(self.input,self.output,self.contract,self.info,torch.full_like(self.matte,float('nan')))
        self.assertFalse(any((self.output/'ComfyLink').glob('*/manifest.json')))

    def test_cancellation_does_not_publish_a_partial_master(self):
        def cancelled():raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):
            write_ae_alpha(self.input,self.output,self.contract,self.info,self.matte,check_cancelled=cancelled)
        self.assertFalse(any((self.output/'ComfyLink').glob('*/manifest.json')))


if __name__=='__main__':unittest.main()
