"""The visual selections must reach the final splice without synthesising again."""
from pathlib import Path
import tempfile
from unittest.mock import patch
import json
import unittest
import numpy as np
import torch
import test_audio_dialogue as base
m=base.m

class SplitEditorTests(unittest.TestCase):
    def test_two_explicit_ranges_drive_final_audio_and_keep_take(self):
        rate=24000
        original=np.sin(np.arange(rate*2)[:,None]*.05).astype(np.float32)*.2
        take={'waveform':torch.from_numpy(original.T.copy())[None], 'sample_rate':rate}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.wav';source.touch()
            edit={'source':str(source),'identity':m.identity(source),'word_start':.1,'word_end':.2,
                  'reference_seconds':3.,'source_transcript':'pay eight quid', 'take':{'script':'pay eight euros'}}
            with patch.object(m,'local_path',side_effect=Path),patch.object(m,'decode',return_value=(original,rate)),patch.object(m.folder_paths,'get_output_directory',return_value=temp),patch.object(m,'transcribe',return_value=[]),patch('ComfyUI_zura_nodes.longcat.project_directory',return_value=root),patch.object(m.ZuraLongCatVoice,'generate',side_effect=AssertionError('Must reuse the supplied take')):
                selector=m.ZuraAudioDialogueSelect()
                first=selector.select(take,edit,'Manual IN/OUT',.8,1.2,.5,.9)
                second=selector.select(take,edit,'Manual IN/OUT',.9,1.1,.6,.95)
                self.assertIs(second['result'][0],take)
                self.assertEqual(first['ui']['zura_audio_dialogue'][0]['take'],second['ui']['zura_audio_dialogue'][0]['take'])
                result=m.ZuraAudioDialogueOutput().finish(*second['result'],'Natural duration (no stretch)',12.,'test')
                audio,receipt=result['result'];receipt=json.loads(receipt)
                self.assertEqual(receipt['source_samples'],[14400,22800])
                self.assertEqual(receipt['generated_selection'],[.9,1.1])
                output=audio['waveform'][0].numpy().T
                np.testing.assert_array_equal(output[:14400],original[:14400])
                np.testing.assert_array_equal(output[14400+4800:],original[22800:])
                np.testing.assert_allclose(result['ui']['zura_audio_dialogue'][0]['output_selection'],[.6,.8])
                at_end=selector.select(take,edit,'Manual IN/OUT',.9,2.0004,.6,2.0004)
                self.assertEqual(at_end['result'][1]['word_end'],2.)
                self.assertEqual(at_end['result'][1]['generated_selection'][1],2.)

    def test_failed_auto_selection_cannot_export_unchanged_source_as_finished(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'source.wav';path.touch()
            edit={'source':str(path),'identity':m.identity(path),'word_start':.1,'word_end':.2}
            take={'waveform':torch.zeros((1,1,24000)),'sample_rate':24000}
            with patch.object(m,'local_path',side_effect=Path),patch.object(m,'decode',return_value=(np.zeros((24000,1),np.float32),24000)),patch.object(m.folder_paths,'get_output_directory',return_value=temp),patch.object(m,'transcribe',side_effect=RuntimeError('ASR unavailable')):
                result=m.ZuraAudioDialogueSelect().select(take,edit,'Auto changed words',0.,.5)
                with self.assertRaisesRegex(ValueError,'Select replacement words'):
                    m.ZuraAudioDialogueOutput().finish(*result['result'],'Natural duration (no stretch)',12.,'test')
                manual=m.ZuraAudioDialogueSelect().select(take,edit,'Manual IN/OUT',.3,.5)
                self.assertFalse(manual['result'][1]['selection_error'])

if __name__=='__main__':unittest.main()
