"""Streaming HLG video keeps frame count, metadata and source audio."""
import importlib
import math
import shutil
import struct
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import av
import numpy as np
import torch
import v2_bootstrap

for name,path in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/path)];sys.modules[name]=module
chunk=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunks')
storage=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_store')
video=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_video')
paintout=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


class HDRChunkVideoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.ffmpeg=shutil.which('ffmpeg') or 'D:/ComfyUI/python_embeded/ffmpeg-bin/ffmpeg.exe'
        if not Path(self.ffmpeg).exists():self.skipTest('FFmpeg not installed')
        self.plan=[chunk.HDRChunk(10,9,0),chunk.HDRChunk(15,9,4)]
        self.stage=storage.HDRChunkStore(self.tmp.name,'a'*32,self.plan,32,32,create=True)
        self.stage.write(0,torch.full((9,32,32,3),.3));self.stage.write(1,torch.full((9,32,32,3),.3))
        self.audio=Path(self.tmp.name)/'source.wav'
        with wave.open(str(self.audio),'wb') as wav:
            wav.setparams((1,2,48000,144000,'NONE','not compressed'))
            # 440 Hz for the first second; 880 Hz after it. The selected
            # range starts at 1 second and must retain the latter section.
            wav.writeframes(b''.join(struct.pack('<h',int(16000*math.sin(2*math.pi*(440 if i<48000 else 880)*i/48000))) for i in range(144000)))

    def test_hlg_video_metadata_frame_count_and_audio_offset(self):
        with patch.object(paintout,'native_colour',side_effect=lambda frames,*args:frames):
            path=video.export_hlg_video(self.stage,self.tmp.name,'hlg',fps=10,
                audio_source=self.audio,audio_start_frame=10,ffmpeg=self.ffmpeg)
        with av.open(str(path)) as container:
            stream=container.streams.video[0]
            self.assertEqual((stream.width,stream.height),(32,32))
            self.assertEqual(stream.codec_context.format.name,'yuv420p10le')
            self.assertEqual((stream.codec_context.color_primaries,stream.codec_context.color_trc,stream.codec_context.colorspace),(9,18,9))
            self.assertEqual(sum(1 for _ in container.decode(video=0)),14)
        with av.open(str(path)) as container:
            samples=np.concatenate([frame.to_ndarray().reshape(-1) for frame in container.decode(audio=0)])
            self.assertGreaterEqual(len(samples),int(1.4*48000)-1024)
            spectrum=np.abs(np.fft.rfft(samples[:48000]))
            self.assertGreater(spectrum[880],spectrum[440]*3)

    def test_cancellation_does_not_publish_partial_video(self):
        def stop(frame,total):
            if frame==3:self.stage.cancel()
        with patch.object(paintout,'native_colour',side_effect=lambda frames,*args:frames):
            with self.assertRaises(storage.HDRChunkCancelled):
                video.export_hlg_video(self.stage,self.tmp.name,'cancelled',fps=10,ffmpeg=self.ffmpeg,progress=stop)
        self.assertEqual(list((Path(self.tmp.name)/'genj'/'hdr').iterdir()),[])


if __name__=='__main__':unittest.main()
