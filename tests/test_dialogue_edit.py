"""CPU checks for exact-word boundaries and the drawn face tracker."""
import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch

import v2_bootstrap
import cv2
import numpy as np

try:
    from comfy_api.latest import InputImpl
except ImportError:
    api = types.ModuleType('comfy_api.latest')
    api.InputImpl = types.SimpleNamespace(VideoFromFile=lambda path: path)
    sys.modules['comfy_api.latest'] = api

dialogue = importlib.import_module('ComfyUI_zura_nodes.dialogue_edit')


class DialogueTests(unittest.TestCase):
    def test_source_timing_ignores_stale_half_second_selection(self):
        edit={'word_start':.964,'word_end':1.973,'first':0,'meta':{'fps':30}}
        self.assertEqual(dialogue.resolve_timing(edit,0,.5),(.964,1.973))
        edit.update(first=15)
        np.testing.assert_allclose(dialogue.resolve_timing(edit,0,.5),(.464,1.473))

    def test_manual_timing_refuses_stretch_and_keeps_exact_source_duration(self):
        edit={'word_start':.964,'word_end':1.973,'first':0,'meta':{'fps':30}}
        with self.assertRaisesRegex(ValueError,'same duration'):
            dialogue.resolve_timing(edit,0,.5,'manual')
        np.testing.assert_allclose(dialogue.resolve_timing(edit,1,2,'manual'),(1,2.009))
        for mode in ['fit','unknown']:
            with self.assertRaises(ValueError):dialogue.resolve_timing(edit,0,.5,mode)

    def test_video_audio_splice_uses_exact_samples_without_tempo_processing(self):
        rate=48000;rng=np.random.default_rng(9)
        original=rng.normal(0,.1,(rate*2,2)).astype(np.float32)
        generated=rng.normal(0,.1,(rate*2,2)).astype(np.float32)
        with patch.object(dialogue,'ffmpeg',side_effect=AssertionError('No tempo filter for video')):
            out,gain=dialogue.blend_audio(original,generated,.75,1.25,.5,1,0,rate,allow_retime=False)
        np.testing.assert_array_equal(out[:36000],original[:36000])
        np.testing.assert_array_equal(out[60000:],original[60000:])
        np.testing.assert_allclose(out[36000:60000],generated[24000:48000]*gain)

    def test_ltx_geometry_pads_up_and_bounds_local_profile(self):
        self.assertEqual(dialogue.ltx_geometry(512,430,430,68),(512,512,73))
        self.assertEqual(dialogue.ltx_geometry(385,430,300,9),(448,320,9))
        for n in range(1,242):
            w,h,count=dialogue.ltx_geometry(384,430,430,n)
            self.assertGreaterEqual(count,n)
            self.assertEqual((count-1)%8,0)
            self.assertEqual(w%64,0);self.assertEqual(h%64,0)
        for values in [(769,200,600,68),(512,430,430,242),(float('nan'),430,430,68)]:
            with self.assertRaises(ValueError):dialogue.ltx_geometry(*values)

    def test_portrait_and_landscape_fit_each_detail_without_stretching(self):
        for edge in (384,512,640,768):
            for cw,ch in [(254,262),(339,367),(200,600),(600,200),(50,1000),(1000,50)]:
                w,h,count=dialogue.ltx_geometry(edge,cw,ch,135)
                self.assertEqual(max(w,h),edge)
                self.assertEqual(w%64,0);self.assertEqual(h%64,0)
                self.assertEqual(count,137)
                yy,xx=np.mgrid[:ch,:cw]
                crop=np.stack([xx/cw,yy/ch,(xx+yy)/(cw+ch)],axis=-1).astype(np.float32)
                padded,fit=dialogue.fit_reference(crop,w,h)
                self.assertEqual(padded.shape[1]*h,padded.shape[0]*w)
                self.assertGreaterEqual(padded.shape[0],ch);self.assertGreaterEqual(padded.shape[1],cw)
                generated=cv2.resize(padded,(w*2,h*2),interpolation=cv2.INTER_LINEAR)
                restored=dialogue.restore_face(generated,fit,cw,ch)
                np.testing.assert_allclose(restored,crop,atol=.02)

    def test_long_context_is_bounded_and_keeps_all_selected_frames(self):
        for fps in (24,25,30,29.97):
            meta={'fps':fps,'frames':round(65*fps)}
            # The reported failure had 33 seconds of context around four seconds of speech.
            first,last=dialogue.context_window(meta,29.223,33.666,27,60.435)
            self.assertLessEqual(last-first,241)
            self.assertLessEqual(first,29.223*fps)
            self.assertGreaterEqual(last,33.666*fps)
            _,_,count=dialogue.ltx_geometry(768,254,262,last-first)
            self.assertGreaterEqual(count,last-first);self.assertLessEqual(count,241)
        self.assertEqual(dialogue.context_window({'fps':30,'frames':300},1,1.5,0,2),(0,60))
        for a,b in [(0,.5),(64,65)]:
            first,last=dialogue.context_window({'fps':30,'frames':1950},a,b,0,65)
            self.assertGreaterEqual(first,0);self.assertLessEqual(last,1950)
        with self.assertRaisesRegex(ValueError,'No words were removed or retimed'):
            dialogue.context_window({'fps':30,'frames':1950},1,12,0,65)
        with self.assertRaisesRegex(ValueError,'No words were removed or retimed'):
            dialogue.context_window({'fps':60,'frames':3900},29.223,33.666,27,60.435)

    def test_wrong_generation_geometry_and_time_are_rejected(self):
        edit={'meta':{'fps':30},'generation':{'frames':73,'width':1024,'height':1024}}
        dialogue.validate_generated(edit,(73,1024,1024,3),1.165,1.6)
        for shape in [(72,1024,1024,3),(73,768,768,3),(73,1024,1024,4)]:
            with self.assertRaises(ValueError):dialogue.validate_generated(edit,shape,1.165,1.6)
        for times in [(1.6,1.1),(-.1,.5),(0,3),(float('nan'),1)]:
            with self.assertRaises(ValueError):dialogue.validate_generated(edit,(73,1024,1024,3),*times)

    def test_export_rejects_wrong_size_count_or_fps(self):
        meta={'frames':68,'width':1080,'height':1080,'fps':30,'duration':68/30}
        for key,value in [('frames',73),('width',1024),('fps',24)]:
            wrong={**meta,key:value}
            with patch.object(dialogue,'inspect',return_value=wrong):
                with self.assertRaisesRegex(RuntimeError,'not accepted'):dialogue.verify_export('test.mp4',meta)
        with patch.object(dialogue,'inspect',return_value=meta):
            self.assertEqual(dialogue.verify_export('test.mp4',meta),meta)

    def test_variable_rate_and_nonzero_timestamps_are_rejected(self):
        for pts,accepted in [([0,1/30,2/30],True),([0,.02,.08],False),([1,1+1/30,1+2/30],False)]:
            data=json.dumps({'packets':[{'pts_time':v} for v in pts]}).encode()
            with patch.object(dialogue.subprocess,'run',return_value=types.SimpleNamespace(stdout=data)):
                if accepted:dialogue.validate_source_cadence('test.mp4',{'fps':30,'frames':3})
                else:
                    with self.assertRaises(ValueError):dialogue.validate_source_cadence('test.mp4',{'fps':30,'frames':3})

    def test_only_selected_audio_samples_change_when_word_is_retimed(self):
        rate=48000;t=np.arange(rate*2)/rate
        original=np.column_stack((np.sin(t*1200),np.sin(t*1800))).astype(np.float32)*.2
        generated=np.column_stack((np.sin(t*2200),np.sin(t*2800))).astype(np.float32)*.1
        out,gain=dialogue.blend_audio(original,generated,.75,1.1,.8,1.25,12,rate)
        np.testing.assert_array_equal(out[:36000],original[:36000])
        np.testing.assert_array_equal(out[52800:],original[52800:])
        self.assertGreater(float(np.abs(out[37000:52000]-original[37000:52000]).mean()),.02)
        self.assertTrue(np.isfinite(out).all());self.assertGreater(gain,0)

    def test_stale_selection_and_mouth_outside_crop_are_rejected(self):
        meta={'identity':'new','width':100,'height':100}
        data={'identity':'old','box':[10,10,50,50],'mouth':[35,40,8,6]}
        with self.assertRaisesRegex(ValueError,'source changed'):
            dialogue.selection_data(json.dumps(data),meta)
        data.update(identity='new',mouth=[90,90,8,6])
        with self.assertRaisesRegex(ValueError,'inside'):
            dialogue.selection_data(json.dumps(data),meta)

    def test_face_tracking_follows_translation_both_directions(self):
        rng=np.random.default_rng(8)
        image=np.zeros((180,220,3),np.uint8);image[30:110,45:125]=rng.integers(0,256,(80,80,3),dtype=np.uint8)
        frames=[cv2.warpAffine(image,np.float32([[1,0,i*3],[0,1,i*2]]),(220,180)) for i in range(9)]
        centres=dialogue.track_points(frames,4,[20,10,150,150],[97,113,28,22],True)
        expected=np.array([[97+(i-4)*3,113+(i-4)*2] for i in range(9)])
        np.testing.assert_allclose(centres,expected,atol=.6)

    def test_word_bounds_cannot_extend_past_generated_audio(self):
        a=np.ones((48000,2),np.float32)
        with self.assertRaisesRegex(ValueError,'generated audio'):
            dialogue.blend_audio(a,a,.1,.2,.9,1.1)


if __name__=='__main__':unittest.main()
