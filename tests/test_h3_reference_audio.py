"""Preserved H3 speech uses the native latent mask contract, without inference."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch

import v2_bootstrap
import torch

NAME = 'ComfyUI_zura_nodes.artist_studio'
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT/'artist_studio')]
    sys.modules[NAME] = package
h3 = importlib.import_module(NAME+'.h3')

# Use ComfyUI's actual container when installed; the standalone tests need only
# its public .tensors contract. No model, sampler or audio encoder is mocked here
# as proof of rendering quality.
try:
    from comfy.nested_tensor import NestedTensor
except ImportError:
    class NestedTensor:
        def __init__(self, tensors): self.tensors = list(tensors)


class ReferenceAudioTests(unittest.TestCase):
    def setUp(self):
        self.video = torch.randn(1,24,2,2,2)
        self.template = torch.zeros(1,32,2,4)
        self.latent = {'samples':NestedTensor((self.video,self.template)), 'metadata':'preserve'}
        self.wave = torch.ones(1,1,800)
        self.audio = {'sample_rate':32000,'waveform':self.wave}
        self.encoded = torch.full_like(self.template,.25)
        self.received = []
        self.vae = types.SimpleNamespace(audio_sample_rate=32000,encode=self.encode)
        comfy = types.ModuleType('comfy'); comfy.__path__ = []
        audio = types.ModuleType('comfy.audio')
        audio.resample = lambda wave,old,new: wave.repeat_interleave(new//old,dim=-1)
        comfy.audio = audio
        nested = types.ModuleType('comfy.nested_tensor'); nested.NestedTensor = NestedTensor
        self.modules = patch.dict(sys.modules,{'comfy':comfy,'comfy.audio':audio,'comfy.nested_tensor':nested})
        self.modules.start(); self.addCleanup(self.modules.stop)

    def encode(self, wave):
        self.received.append(wave)
        return self.encoded

    def test_short_mono_track_encodes_stereo_waveform_silence_and_preserves_picture(self):
        output = h3.ZuraH3LockReferenceAudio().lock(self.latent,self.vae,self.audio)[0]
        wave = self.received[0]
        self.assertEqual(wave.shape,(1,3200,2))
        self.assertTrue(torch.equal(wave[:,:800,0],self.wave[:,0]))
        self.assertTrue(torch.equal(wave[:,:,0],wave[:,:,1]))
        self.assertEqual(wave[:,800:].count_nonzero(),0)
        self.assertIs(output['samples'].tensors[0],self.video)
        self.assertTrue(torch.equal(output['samples'].tensors[1],self.encoded))
        self.assertEqual(output['noise_mask'].tensors[1].count_nonzero(),0)
        self.assertTrue(torch.equal(output['noise_mask'].tensors[0],torch.ones_like(self.video)))
        self.assertEqual(output['metadata'],'preserve')
        self.assertNotIn('noise_mask',self.latent)
        self.assertTrue(torch.equal(self.audio['waveform'],self.wave))

    def test_preserves_existing_video_mask_and_only_replaces_the_audio(self):
        mask = torch.rand_like(self.video)
        self.latent['noise_mask'] = NestedTensor((mask,torch.ones_like(self.template)))
        output = h3.ZuraH3LockReferenceAudio().lock(self.latent,self.vae,self.audio)[0]
        self.assertIs(output['noise_mask'].tensors[0],mask)
        self.assertEqual(output['noise_mask'].tensors[1].count_nonzero(),0)

    def test_resampling_and_trim_do_not_shift_the_start(self):
        wave = torch.arange(4000).float()[None,None].repeat(1,2,1)
        h3.ZuraH3LockReferenceAudio().lock(self.latent,self.vae,{'sample_rate':16000,'waveform':wave})
        self.assertTrue(torch.equal(self.received[0][:,:,0],wave[:,0,:1600].repeat_interleave(2,-1)))

    def test_only_small_native_encoder_rounding_is_fitted(self):
        self.encoded = torch.ones(1,32,2,3)
        output = h3.ZuraH3LockReferenceAudio().lock(self.latent,self.vae,self.audio)[0]
        self.assertEqual(output['samples'].tensors[1].shape,self.template.shape)
        self.encoded = torch.ones(1,32,2,7)
        with self.assertRaisesRegex(ValueError,'audio VAE'):
            h3.ZuraH3LockReferenceAudio().lock(self.latent,self.vae,self.audio)
        self.encoded = torch.ones(1,32,2,0)
        with self.assertRaisesRegex(ValueError,'audio VAE'):
            h3.ZuraH3LockReferenceAudio().lock(self.latent,self.vae,self.audio)

    def test_rejects_wrong_model_and_invalid_speech_before_encoding(self):
        for latent in ({'samples':torch.zeros(1,16,2,2,2)},
                       {'samples':NestedTensor((self.video,torch.zeros(1,8,2,4)))},
                       {'samples':NestedTensor((self.video,torch.zeros(1,32,2,0)))}):
            with self.assertRaises(ValueError):h3.ZuraH3LockReferenceAudio().lock(latent,self.vae,self.audio)
        for wave in (torch.full((1,1,800),float('nan')),torch.zeros(1,3,800),torch.zeros(1,1,0)):
            with self.assertRaises(ValueError):
                h3.ZuraH3LockReferenceAudio().lock(self.latent,self.vae,{'sample_rate':32000,'waveform':wave})
        self.assertFalse(self.received)

    def test_background_mask_keeps_brief_moving_edges_and_preserved_audio(self):
        video = torch.randn(1,24,7,4,6)
        audio = torch.randn(1,32,2,36)
        empty = torch.zeros_like(video)
        audio_mask = torch.zeros_like(audio)
        latent = {'samples':NestedTensor((empty,audio)),
                  'noise_mask':NestedTensor((torch.ones_like(video),audio_mask)), 'metadata':'keep'}
        mask = torch.zeros(22,64,96)
        mask[2,31,31] = 1
        mask[20,45,80] = 1
        result = h3.ZuraH3PreserveBackground().preserve(latent,{'samples':video},mask)[0]
        protected = result['noise_mask'].tensors[0]
        self.assertIs(result['samples'].tensors[0],video)
        self.assertIs(result['samples'].tensors[1],audio)
        self.assertIs(result['noise_mask'].tensors[1],audio_mask)
        # Brief edits span their causal encoder chunk and whole DiT patches.
        self.assertTrue(torch.all(protected[:,:,0:5,0:2,0:2] == 1))
        self.assertTrue(torch.all(protected[:,:,5:,2:,4:] == 1))
        self.assertEqual(protected[:,:,0:5,2:,4:].count_nonzero(),0)
        self.assertEqual(result['metadata'],'keep')
        self.assertIs(latent['samples'].tensors[0],empty)

    def test_caption_depth_cleaning_scales_regions_and_preserves_other_geometry(self):
        depth=torch.zeros(2,40,60,3)
        depth[:,10:16,12:36]=1
        details={'text_regions':[{'x':6,'y':5,'width':12,'height':3}], 'text_regions_size':[30,20]}
        result=h3.ZuraH3CleanDepthTextRegions().clean(depth,details)[0]
        self.assertEqual(result[:,10:16,12:36].count_nonzero(),0)
        self.assertTrue(torch.equal(result[:,:10],depth[:,:10]))
        self.assertTrue(torch.equal(result[:,:,36:],depth[:,:,36:]))
        self.assertEqual(depth[:,10:16,12:36].count_nonzero(),2*6*24*3)
        self.assertIs(h3.ZuraH3CleanDepthTextRegions().clean(depth,{})[0],depth)


if __name__ == '__main__': unittest.main()
