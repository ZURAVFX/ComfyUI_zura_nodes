"""Saved SDR checkpoint resume and bounded, full-raster tiled HDR preparation."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[2]
package=types.ModuleType('zura_hdr_checkpoint_test');package.__path__=[str(ROOT/'paintout')]
sys.modules[package.__name__]=package
core=importlib.import_module('zura_hdr_checkpoint_test.paintout')
hdr=importlib.import_module('zura_hdr_checkpoint_test.hdr')
with patch.dict(sys.modules,{'server':types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=None))}):
    browser=importlib.import_module('zura_hdr_checkpoint_test.browser')
sys.modules['zura_hdr_checkpoint_test.browser']=browser

class HDRCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.folder=self.root/'repair';self.folder.mkdir()
        for index in (7,8):
            core.save_exr(self.folder/f'frame_{index:06d}.exr',np.full((73,125,3),.18,np.float32),'acescg',False)
        self.plate=dict(processing='SDR (sRGB)',space='srgb_display',start=7,count=2,
                        fps=24000/1001,fps_rational='24000/1001',
                        source=dict(kind='sequence',width=125,height=73,path='original-optional-for-sequence'))
        self.write()

    def write(self):
        (self.folder/'paintout.json').write_text(json.dumps(dict(plate=self.plate)),encoding='utf-8')

    def test_tiled_shape_allows_87_hd_frames_without_smaller_proxy(self):
        self.assertEqual(hdr.conversion_shape(1920,1080,87,'tiled_fusion'),(1920,1088,89))
        self.assertEqual(hdr.conversion_window(1920,1088),17)
        self.assertEqual(hdr.conversion_window(2560,1472),9)
        with self.assertRaisesRegex(ValueError,'40 million'):
            hdr.conversion_shape(1920,1080,87)
        with self.assertRaisesRegex(ValueError,'guide-encode memory'):
            hdr.conversion_shape(3840,2160,87,'tiled_fusion')
        with self.assertRaisesRegex(ValueError,'121'):
            hdr.conversion_shape(1920,1080,122,'tiled_fusion')
        with patch.object(hdr,'MAX_HDR_GUIDE_BYTES',1024):
            with self.assertRaisesRegex(ValueError,'8 GiB'):
                hdr.conversion_shape(125,73,9,'tiled_fusion')

    def test_resume_recovers_exact_clock_range_and_source_metadata(self):
        with patch.object(hdr,'release_model_memory') as release:
            result=hdr.ZuraPaintoutHDRResume().resume(str(self.folder))
        self.assertEqual(result['result'],(str(self.folder.resolve()),self.plate,hdr.DEFAULT_HDR_MODEL))
        self.assertEqual(result['ui']['zura_hdr_checkpoint'][0]['fps_rational'],'24000/1001')
        release.assert_called_once()

    def test_model_gateway_only_returns_after_valid_checkpoint_and_release(self):
        calls=[]
        with patch.object(hdr,'release_model_memory',side_effect=lambda:calls.append('released')):
            result=hdr.ZuraPaintoutHDRResume().resume(str(self.folder),'selected-hdr.safetensors')
        self.assertEqual(calls,['released'])
        self.assertEqual(result['result'][2],'selected-hdr.safetensors')
        with patch.object(hdr,'release_model_memory') as release:
            with self.assertRaises(ValueError):hdr.ZuraPaintoutHDRResume().resume(str(self.folder),' ')
            release.assert_not_called()

    def test_malformed_or_hdr_metadata_rejected_before_unloading(self):
        cases=[dict(count=True),dict(start=-1),dict(fps=25),dict(fps_rational='0/0'),
               dict(space='acescg'),dict(processing='HDR (ACEScct)')]
        for change in cases:
            original=self.plate.copy();self.plate.update(change);self.write()
            with self.subTest(change=change),patch.object(hdr,'release_model_memory') as release:
                with self.assertRaises(ValueError):hdr.ZuraPaintoutHDRResume().resume(str(self.folder))
                release.assert_not_called()
            self.plate=original

    def test_missing_and_misnumbered_frames_do_not_resume(self):
        (self.folder/'frame_000008.exr').rename(self.folder/'frame_000009.exr')
        with self.assertRaisesRegex(ValueError,'original numbering'):
            hdr.checkpoint_plate(str(self.folder))
        (self.folder/'frame_000009.exr').unlink()
        with self.assertRaisesRegex(ValueError,'every original-size'):
            hdr.checkpoint_plate(str(self.folder))

    def test_video_checkpoint_requires_original_audio_source_and_matching_clock(self):
        self.plate['source'].update(kind='video',path=str(self.root/'missing.mkv'));self.write()
        with self.assertRaisesRegex(ValueError,'preserve the source audio'):
            hdr.checkpoint_plate(str(self.folder))
        source=self.root/'source.mkv';source.write_bytes(b'probe fixture')
        self.plate['source']['path']=str(source);self.write()
        real_describe=hdr.describe
        current=dict(kind='video',path=str(source),width=125,height=73,count=12,
                     fps=24000/1001,fps_rational='24000/1001')
        def describe(path):return current if Path(path)==source else real_describe(path)
        with patch.object(hdr,'describe',side_effect=describe):
            _,plate=hdr.checkpoint_plate(str(self.folder))
            self.assertEqual(plate['source'],current)
            current['fps_rational']='25/1'
            with self.assertRaisesRegex(ValueError,'frame rate changed'):
                hdr.checkpoint_plate(str(self.folder))

    def test_model_release_is_scoped_to_queued_helper_and_ordered(self):
        calls=[]
        manager=types.SimpleNamespace(unload_all_models=lambda:calls.append('unload'),
                                      soft_empty_cache=lambda:calls.append('empty'))
        with patch.dict(sys.modules,{'comfy':types.SimpleNamespace(model_management=manager)}),patch.object(hdr.gc,'collect',side_effect=lambda:calls.append('gc')):
            hdr.release_model_memory()
        self.assertEqual(calls,['unload','gc','empty'])

    def test_tiled_source_guard_passes_after_wholeclip_guard_rejects(self):
        source=self.root/'source.mkv';source.write_bytes(b'probe fixture')
        description=dict(kind='video',width=1920,height=1080,count=87,transfer='bt709',primaries='bt709')
        with patch.object(hdr,'describe',return_value=description):
            node=hdr.ZuraPaintoutColourCheck()
            with self.assertRaises(ValueError):node.check(str(source),'auto','sdr_hdr',87)
            self.assertEqual(node.check(str(source),'auto','sdr_hdr',87,'tiled_fusion'),(str(source),))

    @unittest.skipUnless(os.environ.get('ZURA_HDR_HD_GUIDE_TEST')=='1','Set ZURA_HDR_HD_GUIDE_TEST=1 for the 2.2 GB full-raster CPU guide check.')
    def test_real_87_frame_hd_guide_preallocates_and_restores_delivery_bookkeeping(self):
        comfy=Path(sys.executable).resolve().parents[2];sys.path.insert(0,str(comfy))
        importlib.import_module('comfy_extras.nodes_images')
        sequence=self.root/'hd';sequence.mkdir()
        image=core.to_linear(torch.full((1080,1920,3),.4),'srgb_display').numpy()
        first=sequence/'frame_000007.exr';core.save_exr(first,image,'acescg',False)
        for index in range(8,94):os.link(first,sequence/f'frame_{index:06d}.exr')
        plate=dict(self.plate,count=87,source=dict(self.plate['source'],width=1920,height=1080))
        with patch.object(hdr,'release_model_memory') as release:
            guide,take,width,height,count,fps,window,model_name=hdr.ZuraPaintoutHDRPrepare().prepare(str(sequence),plate,'tiled_fusion',True)
        release.assert_called_once()
        self.assertEqual(tuple(guide.shape),(89,1088,1920,3))
        self.assertEqual((width,height,count,window),(1920,1088,89,17))
        self.assertEqual((take['width'],take['height'],take['count'],take['plate']['start']),(1920,1080,87,7))
        self.assertEqual(take['plate']['fps_rational'],'24000/1001')
        self.assertEqual(fps,24000/1001)
        self.assertEqual(guide.device.type,'cpu')
        self.assertEqual(model_name,hdr.DEFAULT_HDR_MODEL)
        self.assertTrue(torch.equal(guide[-1],guide[86]))
        self.assertTrue(torch.isfinite(guide[0]).all())

if __name__=='__main__':unittest.main()
