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
    def test_native_detector_leading_foot_point_is_excluded(self):
        face = torch.arange(68*3, dtype=torch.float32).reshape(68,3)
        native = torch.cat((torch.tensor([[-5., -5., 0.]]), face))
        self.assertTrue(torch.equal(speech.native_face_landmarks({'keypoints_face': native}), face))
        self.assertTrue(torch.equal(speech.native_face_landmarks({'keypoints_face': face}), face))
        appended = torch.cat((face, torch.zeros(2,3)))
        self.assertTrue(torch.equal(speech.native_face_landmarks({'keypoints_face': appended}), face))

    def test_automatic_prefers_sharp_and_preserves_explicit_fast_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with patch.object(speech, 'bundle_path', return_value=base), patch.object(speech.importlib.util, 'find_spec', return_value=object()), patch.object(torch.cuda,'is_available',return_value=True):
                for name in speech.model_files('MuseTalk 1.5'):
                    path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
                self.assertEqual(speech.readiness()['model'],'MuseTalk 1.5')
                for name in speech.model_files('LatentSync 1.6'):
                    path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
                self.assertEqual(speech.readiness()['model'],'LatentSync 1.6')
                self.assertEqual(speech.ZuraSpeechModelLoader().load('MuseTalk 1.5')[0]['model'],'MuseTalk 1.5')
                with patch.object(torch.cuda,'is_available',return_value=False):
                    self.assertEqual(speech.readiness()['model'],'MuseTalk 1.5')

    def test_sharp_audio_windows_use_actual_fps_and_repeat_boundary_features(self):
        from ComfyUI_zura_nodes.artist_studio.speech_latentsync import audio_windows
        features=torch.arange(100)[:,None,None].expand(-1,5,384)
        at24=list(audio_windows(features,48,24));at25=list(audio_windows(features,48,25))
        self.assertEqual(at24[0].shape,(50,384))
        self.assertEqual(int(at24[0][0,0]),0)
        self.assertEqual(int(at24[24][0,0]),46)
        self.assertEqual(int(at25[24][0,0]),44)
        self.assertEqual(int(at24[47][-1,0]),99)

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

    def test_silent_lead_in_never_looks_ahead_to_speech(self):
        # Half a second of silence, quiet speech, then a long silent tail.
        wave=torch.zeros(1,1,24000)
        wave[...,12000:16800]=.001
        activity=speech.speech_activity({'waveform':wave,'sample_rate':24000},24,24)
        self.assertEqual(float(activity[:12].sum()),0)
        self.assertEqual(float(activity[12]),1)
        self.assertEqual(float(activity[21:].sum()),0)
        self.assertEqual(float(speech.speech_activity({'waveform':torch.zeros_like(wave),'sample_rate':24000},24,24).sum()),0)

    def test_silence_gate_bridges_short_consonant_gaps_without_stereo_cancellation(self):
        wave=torch.zeros(1,2,24000)
        wave[:,0,4800:19200]=.01
        wave[:,1,4800:19200]=-.01
        wave[...,10080:11040]=0
        activity=speech.speech_activity({'waveform':wave,'sample_rate':24000},24,24)
        self.assertEqual(float(activity[:5].sum()),0)
        self.assertEqual(float(activity[5:20].sum()),15)

    def test_resting_reference_removes_original_mouth_motion_but_keeps_eyes(self):
        faces=torch.zeros(3,100,100,3)
        faces[0]=.2;faces[1]=.6;faces[2]=.9
        points=torch.zeros(68,3)
        points[:,2]=1
        points[36:42,:2]=torch.tensor([.3,.35])
        points[42:48,:2]=torch.tensor([.7,.35])
        points[27:31,:2]=torch.tensor([.5,.5])
        points[48,:2]=torch.tensor([.3,.7]);points[54,:2]=torch.tensor([.7,.7])
        metas=[]
        for gap in (.2,.01,.3):
            value=points.clone()
            value[[61,62,63],:2]=torch.tensor([.5,.7-gap/2])
            value[[67,66,65],:2]=torch.tensor([.5,.7+gap/2])
            metas.append({'keypoints_face':value,'width':100,'height':100})
        result=speech.resting_faces(faces,{'pose_metas_original':metas},[(0,0,100,100)]*3)
        self.assertTrue(torch.equal(result[:,:48],faces[:,:48]))
        self.assertTrue(torch.allclose(result[:,72,50],torch.full((3,3),.6)))
        fallback=speech.resting_faces(faces)
        self.assertTrue(torch.allclose(fallback[:,72,50],torch.full((3,3),.2)))
        quiet={'waveform':torch.zeros(1,1,3000),'sample_rate':24000}
        actual=speech.animate_faces(faces,quiet,{},pose_data={'pose_metas_original':metas},face_boxes=[(0,0,100,100)]*3)
        self.assertTrue(torch.equal(actual,result),'Silence must not run an audio predictor with future context')

    def test_resting_reference_aligns_head_motion_without_following_old_lips(self):
        faces=torch.zeros(2,100,100,3)
        faces[0,65:80,45:55]=1
        points=torch.zeros(68,3);points[:,2]=1
        points[36:42,:2]=torch.tensor([.3,.35]);points[42:48,:2]=torch.tensor([.7,.35])
        points[27:31,:2]=torch.tensor([.5,.5])
        points[48,:2]=torch.tensor([.3,.7]);points[54,:2]=torch.tensor([.7,.7])
        points[[61,62,63],:2]=torch.tensor([.5,.7]);points[[67,66,65],:2]=torch.tensor([.5,.7])
        moved=points.clone();moved[:,:2]+=torch.tensor([.08,0])
        moved[[67,66,65],1]+=.2
        metas=[{'keypoints_face':p,'width':100,'height':100} for p in (points,moved)]
        result=speech.resting_faces(faces,{'pose_metas_original':metas},[(0,0,100,100)]*2)
        self.assertGreater(float(result[1,72,58].mean()),.99)
        self.assertEqual(float(result[1,72,47].sum()),0)

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

    def test_mouth_finish_keeps_cheeks_chin_and_eyes(self):
        mask = speech.mouth_finish_mask(100, 100, (0, 0, 100, 100), (100, 100, 3))
        self.assertEqual(float(mask[:48].sum()), 0)
        self.assertEqual(float(mask[:, :18].sum()), 0)
        self.assertEqual(float(mask[93:].sum()), 0)
        self.assertGreater(float(mask[72, 50]), .99)
        points = torch.zeros(68, 3)
        points[48:68, :2] = torch.tensor([.65, .65])
        points[48, 0], points[49, 0] = .55, .75
        shifted = speech.mouth_finish_mask(100, 100, (0, 0, 100, 100), (100, 100, 3), {'keypoints_face':points})
        self.assertGreater(float(shifted[62, 75]), float(mask[62, 75]))

    def test_mouth_detail_is_bounded_and_does_not_invent_flat_texture(self):
        flat = torch.full((32, 32, 3), .5)
        self.assertTrue(torch.equal(speech.recover_mouth_detail(flat), flat))
        face = torch.rand(32, 32, 3)
        restored = speech.recover_mouth_detail(face)
        self.assertLessEqual(float((restored - face).abs().max()), .01401)
        self.assertGreater(float((restored - face).abs().sum()), 0)
        self.assertIs(speech.recover_mouth_detail(face, 0), face)
        for strength in (-1, float('nan'), 2):
            with self.assertRaises(ValueError):speech.recover_mouth_detail(face, strength)

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
        self.assertEqual(graph['zura_speech_0faces']['inputs']['pose_data'],['zura_speech_0detect',0])
        self.assertEqual(graph['zura_speech_0faces']['inputs']['face_boxes'],['zura_speech_0detect',4])
        self.assertEqual(graph['zura_speech_0video']['inputs']['pose_data'],['zura_speech_0detect',0])

    def test_lip_sync_is_optional_for_silent_video_and_legacy_projects(self):
        self.assertFalse(studio.clean_config({})['lip_sync'])
        self.assertFalse(studio.clean_config({'lip_sync':True})['lip_sync'])
        self.assertTrue(studio.clean_config({'audio_id':'a'*32,'lip_sync':True})['lip_sync'])
        self.assertFalse(studio.clean_config({})['refine_lips'])
        self.assertFalse(studio.clean_config({'refine_lips':True})['refine_lips'])
        self.assertTrue(studio.clean_config({'audio_id':'a'*32,'lip_sync':True,'refine_lips':True})['refine_lips'])

    def test_native_speech_has_no_post_pass_unless_requested(self):
        graph={'shot':{'class_type':'GenjLoadReviewedShot','inputs':{}},
               'save':{'class_type':'GenjRestoreSoundtrack','inputs':{'video':['render',0]}}}
        p={'audio':{'sha':'audio'},'config':{'lip_sync':True,'seed':42}}
        self.assertEqual(speech.add_finish(copy.deepcopy(graph),p,native_speech=True),graph)
        p['config']['refine_lips']=True
        result=speech.add_finish(copy.deepcopy(graph),p,native_speech=True)
        self.assertEqual(result['save']['inputs']['video'],['zura_speech_0video',0])
        # Engines without a native face guide still use the common finish.
        p['config']['refine_lips']=False
        self.assertIn('zura_speech_0video',speech.add_finish(copy.deepcopy(graph),p))

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
