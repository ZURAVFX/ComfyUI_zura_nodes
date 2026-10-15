"""Exact sample preservation and guarded timing for audio word edits."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import v2_bootstrap
import numpy as np
import torch

if 'comfy.model_management' not in sys.modules:
    sys.modules.setdefault('comfy',types.ModuleType('comfy'))
    sys.modules['comfy.model_management']=types.ModuleType('comfy.model_management')
    utils=types.ModuleType('comfy.utils');utils.ProgressBar=object;sys.modules['comfy.utils']=utils

m=importlib.import_module('ComfyUI_zura_nodes.audio_dialogue')


class AudioDialogueTests(unittest.TestCase):
    def audio(self,rate=44100,channels=1):
        t=np.arange(rate*2)/rate
        a=np.column_stack([np.sin(t*(900+100*i))*.2 for i in range(channels)]).astype(np.float32)
        g=np.column_stack([np.sin(t*(1800+100*i))*.1 for i in range(channels)]).astype(np.float32)
        return a,g

    def test_natural_duration_preserves_all_other_samples(self):
        for rate,channels in [(44100,1),(48000,2)]:
            a,g=self.audio(rate,channels)
            out,r=m.splice(a,g,rate,.5,1.,.2,.8,12,'Natural duration (no stretch)')
            x,y=r['source_samples'];n=r['output_replacement_samples']
            np.testing.assert_array_equal(out[:x],a[:x]);np.testing.assert_array_equal(out[x+n:],a[y:])
            self.assertEqual(len(out),len(a)+round(.1*rate));self.assertFalse(r['time_stretched'])

    def test_small_fit_keeps_exact_length_and_untouched_surroundings(self):
        a,g=self.audio(48000,2)
        out,r=m.splice(a,g,48000,.5,1.,.2,.72,12,'Keep timing (up to 15% fit)')
        self.assertEqual(out.shape,a.shape)
        np.testing.assert_array_equal(out[:24000],a[:24000]);np.testing.assert_array_equal(out[48000:],a[48000:])
        self.assertTrue(r['time_stretched'])

    def test_large_fit_is_refused(self):
        a,g=self.audio()
        with self.assertRaisesRegex(ValueError,'No large time stretch'):
            m.splice(a,g,44100,.5,1.,.2,1.2,12,'Keep timing (up to 15% fit)')

    def test_invalid_selection_does_not_silently_clamp(self):
        for start,end in [(1.,.5),(-1.,.5),(0.,3.),(float('nan'),1.)]:
            with self.assertRaises(ValueError):m.bounds(start,end,88200,44100,'test')

    def test_millisecond_rounded_file_end_snaps_only_within_half_a_millisecond(self):
        for rate,length in [(44100,80640),(48000,87771),(24000,43886)]:
            duration=length/rate
            start,end=m.bounds(.5,round(duration,3),length,rate,'Original')
            self.assertEqual(start,round(.5*rate))
            self.assertLessEqual(end,length)
            if round(duration,3)>duration:self.assertEqual(end,length)
            with self.assertRaises(ValueError):m.bounds(.5,duration+.0006,length,rate,'Original')
        original,generated=self.audio()
        original=original[:80640]
        output,receipt=m.splice(original,generated,44100,1.065,1.829,1.388,1.7,12,'Natural duration (no stretch)')
        self.assertEqual(receipt['source_samples'][1],len(original))
        np.testing.assert_array_equal(output[:round(1.065*44100)],original[:round(1.065*44100)])

    def test_auto_words_accept_spoken_number_and_reject_ambiguous_match(self):
        words=[{'text':t,'start':i*.2,'end':i*.2+.15} for i,t in enumerate('They wanted me to pay 8 euros for that.'.split())]
        np.testing.assert_allclose(m.changed_range('They wanted me to pay eight quid for that.','They wanted me to pay eight euros for that.',words),(1.2,1.35))
        with self.assertRaisesRegex(ValueError,'unambiguously'):
            m.changed_range('quid','euros',words+[{'text':'euros','start':2.,'end':2.2}])

    def test_editor_reuses_identical_take_without_synthesis(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);wave=torch.zeros((1,1,24000));calls=[]
            def generate(*args,**kwargs):
                import soundfile as sf
                path=root/'voice.wav';sf.write(path,np.zeros((24000,1),np.float32),24000,subtype='FLOAT');calls.append(1)
                return {'waveform':wave,'sample_rate':24000},json.dumps({'wav':str(path),'script':'hello'})
            with patch.object(m,'runtime_config',return_value={'revision':'test'}),patch.object(m.folder_paths,'get_output_directory',return_value=temp,create=True),patch.object(m,'local_path',side_effect=Path),patch.object(m.ZuraLongCatVoice,'generate',side_effect=generate):
                node=m.ZuraLongCatDialogueVoice();args=('Clone a voice','hello','original',1.,42,'test',{'waveform':wave,'sample_rate':24000})
                node.generate(*args);node.generate(*args)
                self.assertEqual(len(calls),1)
                node.generate(*args[:4],43,*args[5:]);self.assertEqual(len(calls),2)

    def test_additional_reference_combines_audio_and_matching_transcripts(self):
        a,_=self.audio(48000,2)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'source.wav';path.write_bytes(b'test')
            with patch.object(m,'local_path',return_value=path),patch.object(m,'decode',return_value=(a,48000)):
                ref,text,edit=m.ZuraAudioDialogueSource().prepare('source','Original sentence.',.5,1.,0.,0.,'extra','More of the same speaker.','Source and extra reference')
                self.assertEqual(text,'Original sentence. More of the same speaker.')
                self.assertEqual(ref['waveform'].shape,(1,1,99600))
                self.assertAlmostEqual(edit['reference_seconds'],4.15)
                ref,text,_=m.ZuraAudioDialogueSource().prepare('source','Original sentence.',.5,1.,0.,0.,'extra','Extra only.','Extra reference only')
                self.assertEqual(ref['waveform'].shape,(1,1,48000));self.assertEqual(text,'Extra only.')

    def test_trimmed_reference_requires_its_own_transcript(self):
        a,_=self.audio()
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'source.wav';path.write_bytes(b'test')
            with patch.object(m,'local_path',return_value=path),patch.object(m,'decode',return_value=(a,44100)):
                with self.assertRaisesRegex(ValueError,'trimmed source reference'):
                    m.ZuraAudioDialogueSource().prepare('source','Full phrase.',.5,1.,.2,1.5,'','','Source and extra reference')
                _,text,_=m.ZuraAudioDialogueSource().prepare('source','Full phrase.',.5,1.,.2,1.5,'','','Source and extra reference','Trimmed words.')
                self.assertEqual(text,'Trimmed words.')


if __name__=='__main__':unittest.main()
