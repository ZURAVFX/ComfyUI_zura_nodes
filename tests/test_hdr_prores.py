"""Real ProRes output: codec, working RGB, exact cadence and float limits."""
import importlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from fractions import Fraction
from unittest.mock import patch

import av
import numpy as np
import v2_bootstrap

name='ComfyUI_zura_nodes.artist_studio'
if name not in sys.modules:
    package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/'artist_studio')];sys.modules[name]=package
prores=importlib.import_module(name+'.hdr_prores')

@unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
class ProResTests(unittest.TestCase):
    def test_raw_rgb_and_fractional_cadence(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'master.mov'
            pixels=np.full((32,32,3),.3,dtype=np.float32)
            pixels[:16,:16]=[.2,.6,.8];pixels[16:,16:]=[.9,.4,.1]
            prores.write_prores4444([pixels]*3,output,width=32,height=32,count=3,fps=30000/1001,source_space='acescg')
            prores.inspect_prores4444(output)
            with av.open(str(output)) as container:
                stream=container.streams.video[0];self.assertEqual(stream.average_rate,Fraction(30000,1001))
                frames=list(container.decode(video=0));self.assertEqual(len(frames),3)
                actual=frames[0].to_ndarray(format='rgb48le').astype(np.float32)/65535
                self.assertLess(float(np.max(np.abs(actual-pixels))),.004,'No HLG/gamma transform may change working samples')
            info=json.loads(output.with_suffix('.mov.json').read_text())
            self.assertEqual(info['colour'],{'encoding':'acescg','sceneLinear':True})
            self.assertEqual(info['clippedSamples'],0)

    def test_float_limit_is_explicit_not_a_hidden_colour_mapping(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'master.mov';pixels=np.full((32,32,3),.5,dtype=np.float32)
            pixels[0,0,0]=-1;pixels[0,0,1]=2
            prores.write_prores4444([pixels],output,width=32,height=32,count=1,fps=24)
            self.assertEqual(json.loads(output.with_suffix('.mov.json').read_text())['clippedSamples'],2)

    def test_bad_frame_does_not_publish_a_movie(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'master.mov'
            with self.assertRaises(ValueError):prores.write_prores4444([np.full((32,32,3),np.nan)],output,width=32,height=32,count=1,fps=24)
            self.assertFalse(output.exists())

    def test_rgba_keeps_alpha(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'alpha.mov';pixels=np.full((32,32,4),.3,dtype=np.float32);pixels[:,:,3]=.25
            prores.write_prores4444([pixels],output,width=32,height=32,count=1,fps=24,channels=4)
            with av.open(str(output)) as container:
                self.assertIn('yuva444',container.streams.video[0].codec_context.format.name)
                actual=next(container.decode(video=0)).to_ndarray(format='rgba64le')[:,:,3]/65535
                self.assertLess(float(np.max(np.abs(actual-.25))),.002)

    def test_sdr_video_node_writes_mov_master_and_separate_browser_preview(self):
        import torch
        import folder_paths
        with tempfile.TemporaryDirectory() as folder:
            frames=torch.full((2,32,32,3),.3)
            components=types.SimpleNamespace(images=frames,frame_rate=Fraction(24),audio=None,alpha=None)
            video=types.SimpleNamespace(get_components=lambda:components)
            latest=types.SimpleNamespace(InputImpl=types.SimpleNamespace(VideoFromFile=lambda path:path))
            with patch.dict(sys.modules,{'comfy_api.latest':latest}),patch.object(folder_paths,'get_output_directory',return_value=folder,create=True),patch.object(folder_paths,'get_save_image_path',return_value=(folder,'result',1,'',None),create=True):
                result=prores.ZuraSaveProRes4444().save(video,'result')
            ref=result['ui']['images'][0]
            self.assertTrue(ref['filename'].endswith('.mov'));self.assertTrue(ref['preview']['filename'].endswith('_preview.mp4'))
            self.assertTrue((Path(folder)/ref['preview']['filename']).is_file())
            prores.inspect_prores4444(Path(folder)/ref['filename'])
