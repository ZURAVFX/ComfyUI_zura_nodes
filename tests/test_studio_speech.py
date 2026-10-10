"""Audio contracts and engine wiring, without downloads or inference."""
import copy
import asyncio
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import v2_bootstrap
import torch

NAME = 'ComfyUI_zura_nodes.artist_studio'
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT/'artist_studio')]
    sys.modules[NAME] = package
speech = importlib.import_module(NAME+'.speech')
voice = importlib.import_module(NAME+'.voice')
signals = importlib.import_module(NAME+'.signals')
studio = importlib.import_module(NAME+'.studio')
wan = importlib.import_module(NAME+'.wan')


class SpeechTests(unittest.TestCase):
    def test_audio_is_trimmed_or_padded_without_pitch_or_voice_changes(self):
        wave=torch.linspace(-1,1,96000)[None,None]
        audio={'waveform':wave,'sample_rate':48000}
        short=speech.fit_speech(audio,24,24)
        self.assertTrue(torch.equal(short['waveform'],wave[...,:48000]))
        long=speech.fit_speech(audio,72,24)
        self.assertTrue(torch.equal(long['waveform'][...,:96000],wave))
        self.assertEqual(long['waveform'][...,96000:].count_nonzero(),0)
        self.assertEqual(long['sample_rate'],48000)

    def test_bad_audio_and_frame_rates_are_rejected(self):
        for audio,fps in [(None,24),({'waveform':torch.full((1,1,10),float('nan')),'sample_rate':48000},24),
                          ({'waveform':torch.zeros(2,1,10),'sample_rate':48000},24),
                          ({'waveform':torch.zeros(1,1,10),'sample_rate':48000},float('nan'))]:
            with self.assertRaises(ValueError):speech.fit_speech(audio,24,fps)

    def test_speech_timing_uses_actual_frame_rate(self):
        features=torch.arange(200).float()[:,None,None].expand(-1,5,384)
        a=list(speech.speech_windows(features,49,24))
        b=list(speech.speech_windows(features,49,25))
        self.assertEqual(a[24].shape,(50,384))
        # At one second the same 50 Hz audio position occurs at 24 or 25 frames.
        # MuseTalk's fps-dependent left context is intentionally retained.
        self.assertEqual(float(a[24][30,0]),50)
        self.assertEqual(float(b[25][20,0]),50)

    def test_face_finish_preserves_every_pixel_outside_lower_face(self):
        images=torch.rand(2,96,128,3)
        faces=torch.ones(2,64,64,3)
        boxes=[(24,12,88,76)]*2
        audio={'waveform':torch.zeros(1,1,48000),'sample_rate':48000}
        target=importlib.import_module('ComfyUI_zura_nodes.video')
        with patch.object(target,'video_components',return_value=(images,audio,24)), \
             patch.object(target,'video_output',side_effect=lambda x,a,f:(x,a,f)):
            result,track,fps=speech.ZuraSpeechComposeVideo().compose(images,faces,boxes,object(),24)[0]
        self.assertTrue(torch.equal(result[:,:,:24],images[:,:,:24]))
        self.assertTrue(torch.equal(result[:,76:],images[:,76:]))
        self.assertTrue(torch.equal(result[:,:42],images[:,:42]))
        self.assertGreater(float((result-images).abs().sum()),0)
        self.assertEqual(track['waveform'].shape[-1],4000)
        self.assertEqual(fps,24)

    def test_unusable_face_fails_before_compositing(self):
        target=importlib.import_module('ComfyUI_zura_nodes.video')
        audio={'waveform':torch.zeros(1,1,48000),'sample_rate':48000}
        with patch.object(target,'video_components',return_value=(None,audio,24)):
            with self.assertRaisesRegex(ValueError,'visible human face'):
                speech.ZuraSpeechComposeVideo().compose(torch.zeros(1,64,64,3),torch.zeros(1,32,32,3),[(0,0,0,0)],object())

    def test_soundtrack_mode_does_not_add_models_or_speech_processing(self):
        graph={'shot':{'class_type':'GenjLoadReviewedShot','inputs':{}},
               'save':{'class_type':'GenjRestoreSoundtrack','inputs':{'video':['render',0]}}}
        p={'config':{'lip_sync':False},'audio':{'sha':'audio'}}
        self.assertEqual(speech.add_finish(copy.deepcopy(graph),p),graph)

    def test_shared_finish_connects_replacement_audio_and_actual_generation_fps(self):
        graph={'shot':{'class_type':'GenjLoadReviewedShot','inputs':{}},
               'save':{'class_type':'GenjRestoreSoundtrack','inputs':{'video':['render',0]}}}
        speech.add_finish(graph,{'audio':{},'config':{'lip_sync':True,'seed':42}})
        self.assertNotIn('zura_speech_model',graph,'An absent audio asset is soundtrack mode')
        speech.add_finish(graph,{'audio':{'sha':'audio'},'config':{'lip_sync':True,'seed':42}})
        self.assertEqual(graph['save']['inputs']['video'],['zura_speech_0video',0])
        self.assertEqual(graph['zura_speech_0faces']['inputs']['audio'],['zura_speech_reference',1])
        self.assertEqual(graph['zura_speech_0faces']['inputs']['fps'],['zura_speech_0frames',2])

    def test_lip_sync_is_optional_for_silent_video_and_legacy_projects(self):
        self.assertFalse(studio.clean_config({})['lip_sync'])
        self.assertFalse(studio.clean_config({'lip_sync':True})['lip_sync'])
        self.assertTrue(studio.clean_config({'audio_id':'a'*32,'lip_sync':True})['lip_sync'])

    def test_text_to_speech_does_not_request_a_clone_sample(self):
        store=types.SimpleNamespace(load=lambda _:self.fail('TTS must not load a reference'))
        graph=voice.voice_graph({'mode':'Text to speech','script':'Welcome to the studio.'},store,'a'*32)
        self.assertNotIn('sample',graph)
        self.assertNotIn('reference_audio',graph['voice']['inputs'])

    def test_cloning_uses_sample_and_transcript_without_changing_script(self):
        asset={'asset_kind':'audio','file':'example_voice.wav'}
        store=types.SimpleNamespace(load=lambda _:asset)
        body={'mode':'Clone a voice','script':'Welcome to the studio.','reference_transcript':'This is my voice.','reference_id':'b'*32}
        with patch.object(studio,'check_asset'):
            graph=voice.voice_graph(body,store,'a'*32)
        self.assertEqual(graph['voice']['inputs']['reference_audio'],['sample',0])
        self.assertEqual(graph['voice']['inputs']['reference_transcript'],body['reference_transcript'])
        self.assertEqual(graph['voice']['inputs']['script'],body['script'])

    def test_invalid_voice_request_never_builds_a_generation(self):
        store=types.SimpleNamespace(load=lambda _:self.fail('Do not read samples for invalid requests'))
        for body in [{'mode':'unknown','script':'Hello'}, {'mode':'Text to speech','script':''},
                     {'mode':'Text to speech','script':'Hello','pace':float('nan')},
                     {'mode':'Clone a voice','script':'Hello','reference_transcript':''}]:
            with self.assertRaises(ValueError):voice.voice_graph(body,store,'a'*32)

    def test_stage_hand_off_preserves_tensor_identity_without_copying(self):
        frames = torch.rand(2, 16, 16, 3)
        first = signals.ZuraStudioSignals().pack('["frames"]', value_0=frames)[0]
        second = signals.ZuraStudioSignals().pack('["fps"]', previous=first, value_0=24)[0]
        self.assertIs(signals.ZuraStudioReadSignal().read(second, 'frames')[0], frames)
        self.assertEqual(signals.ZuraStudioReadSignal().read(second, 'fps')[0], 24)
        self.assertNotIn('fps', first)
        with self.assertRaises(ValueError):
            signals.ZuraStudioReadSignal().read(second, 'missing')
        with self.assertRaises(ValueError):
            signals.ZuraStudioSignals().pack('["frames", "frames"]', value_0=frames)

    def test_completed_voice_recovers_after_history_is_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            store = studio.Store(directory)
            asset_id, job_id = 'a'*32, 'b'*32
            store.save({'id':asset_id, 'kind':'asset', 'asset_kind':'audio', 'file':'speech.wav'})
            store.save({'id':job_id, 'kind':'voice_job', 'asset_id':asset_id, 'state':'queued',
                        'server_address':'local'})
            target = types.SimpleNamespace(store=store, server_address='local')
            with patch.object(studio, 'check_asset') as check:
                job = voice.collect_voice(target, job_id)
            self.assertEqual(job['state'], 'complete')
            self.assertEqual(job['audio']['id'], asset_id)
            check.assert_called_once()

    def test_repeated_voice_request_does_not_submit_another_job(self):
        with tempfile.TemporaryDirectory() as directory:
            store = studio.Store(directory)
            key = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
            store.save({'id':'a'*32, 'kind':'voice_job', 'prompt_id':'existing', 'state':'queued'})
            # No runtime or queue is needed when this request already exists.
            target = types.SimpleNamespace(store=store)
            execution = types.ModuleType('execution')
            with patch.dict(sys.modules, {'execution':execution}):
                job = asyncio.run(voice.create_voice(target, {'request_key':key}))
            self.assertEqual(job['prompt_id'], 'existing')


if __name__=='__main__':unittest.main()
