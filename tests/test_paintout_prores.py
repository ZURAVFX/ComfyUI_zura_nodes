"""Real streaming Paintout MOV publication, without a running ComfyUI."""
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from fractions import Fraction
import av
import numpy as np
import torch
import v2_bootstrap

for part in ('paintout','artist_studio'):
    name='ComfyUI_zura_nodes.'+part
    if name not in sys.modules:
        package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/part)];sys.modules[name]=package
media=importlib.import_module('ComfyUI_zura_nodes.paintout.media')

@unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
class PaintoutProResTests(unittest.TestCase):
    def test_streaming_rgb_movie_at_original_clock(self):
        import folder_paths
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'plate';target.mkdir()
            plate={'fps':30000/1001,'fps_rational':Fraction(30000,1001),'source':{'kind':'sequence'},'space':'acescg','start':0,'count':9}
            delivery=media.Delivery(target,plate,'HLG video',False)
            with patch.object(folder_paths,'get_output_directory',return_value=folder,create=True):
                for _ in range(9):delivery.append(torch.full((32,32,3),.4))
                result=delivery.finish()
            self.assertEqual(result['images'][0]['filename'],'paintout_ProRes4444.mov')
            with av.open(str(target/'paintout_ProRes4444.mov')) as container:
                self.assertEqual(container.streams.video[0].average_rate,Fraction(30000,1001))
                self.assertEqual(container.streams.video[0].codec_context.name,'prores')
                self.assertNotEqual(container.streams.video[0].codec_context.color_trc,18)
                frames=list(container.decode(video=0));self.assertEqual(len(frames),9)
                self.assertLess(float(np.max(np.abs(frames[0].to_ndarray(format='rgb48le')/65535-.4))),.004)
            self.assertFalse(list(target.glob('.prores*')))
