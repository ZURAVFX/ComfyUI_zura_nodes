"""Long HDR review copies retain frame timing and never publish partials."""
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
import av
import numpy as np
import torch
import v2_bootstrap

for name,path in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/path)];sys.modules[name]=module
chunk=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunks')
storage=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_store')
preview=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_preview')

class HDRPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.ffmpeg=shutil.which('ffmpeg') or 'D:/ComfyUI/python_embeded/ffmpeg-bin/ffmpeg.exe'
        if not Path(self.ffmpeg).exists():self.skipTest('FFmpeg not installed')
        plan=[chunk.HDRChunk(10,9,0),chunk.HDRChunk(15,9,4)]
        self.stage=storage.HDRChunkStore(self.tmp.name,'a'*32,plan,32,32,create=True)
        for i in range(2):self.stage.write(i,torch.full((9,32,32,3),.3))
        self.audio=Path(self.tmp.name)/'source.wav'
        with wave.open(str(self.audio),'wb') as wav:
            wav.setparams((1,2,48000,144000,'NONE','not compressed'))
            wav.writeframes(b''.join(struct.pack('<h',int(16000*math.sin(2*math.pi*(440 if i<48000 else 880)*i/48000))) for i in range(144000)))

    def test_review_copy_retains_frames_and_trimmed_audio(self):
        path=preview.export_sdr_preview(self.stage,self.tmp.name,'shot',fps=10,
            audio_source=self.audio,audio_start_frame=10,ffmpeg=self.ffmpeg)
        with av.open(str(path)) as stream:
            self.assertEqual(stream.streams.video[0].codec_context.format.name,'yuv420p')
            self.assertEqual(sum(1 for _ in stream.decode(video=0)),14)
        with av.open(str(path)) as stream:
            samples=np.concatenate([frame.to_ndarray().reshape(-1) for frame in stream.decode(audio=0)])
        spectrum=np.abs(np.fft.rfft(samples[:48000]));self.assertGreater(spectrum[880],spectrum[440]*3)

    def test_cancel_does_not_publish_preview(self):
        def stop(index,total):
            if index==3:self.stage.cancel()
        with self.assertRaises(storage.HDRChunkCancelled):
            preview.export_sdr_preview(self.stage,self.tmp.name,'cancelled',fps=10,ffmpeg=self.ffmpeg,progress=stop)
        self.assertEqual(list((Path(self.tmp.name)/'genj'/'hdr').iterdir()),[])

if __name__=='__main__':unittest.main()
