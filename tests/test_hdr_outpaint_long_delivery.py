import asyncio
import importlib
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave
import zipfile

import av
import numpy as np
import torch
import test_artist_studio

delivery=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_long_delivery')
chunks=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunks')
storage=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_store')
paintout=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


class LongHDRDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_export_holds_last_frame_and_exact_audio(self):
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg: self.skipTest('FFmpeg required.')
        from scipy.signal import correlate,correlation_lags
        with tempfile.TemporaryDirectory() as folder:
            plan=[chunks.HDRChunk(0,17,0),chunks.HDRChunk(9,15,8)]
            stage=storage.HDRChunkStore(folder,'a'*32,plan,32,32,create=True)
            stage.write(0,torch.full((17,32,32,3),.3));stage.write(1,torch.full((15,32,32,3),.3))
            audio=Path(folder)/'audio.wav'; samples=np.random.default_rng(71).integers(-14000,14000,144000,dtype=np.int16)
            with wave.open(str(audio),'wb') as w:
                w.setparams((1,2,48000,len(samples),'NONE','not compressed'));w.writeframes(samples.tobytes())
            with patch.object(paintout,'native_colour',side_effect=lambda frames,*args:frames):
                result=await delivery.export_long_hdr_outpaint(stage,folder,'test',source_path=str(audio),has_audio=True,start_seconds=.517,source_duration=.93,ffmpeg=ffmpeg)
            self.assertEqual(result['frames'],25)
            with zipfile.ZipFile(result['files'][0]) as archive:self.assertEqual(len(archive.namelist()),25)
            for path in (result['files'][1],result['preview']):
                with av.open(path) as container:self.assertEqual(sum(1 for _ in container.decode(video=0)),25)
                with av.open(path) as container:actual=np.concatenate([f.to_ndarray().reshape(-1) for f in container.decode(audio=0)])
                expected=samples[round(.517*48000):round(.517*48000)+round(.93*48000)].astype(np.float32)/32768
                actual=actual[:len(expected)];c=correlate(actual,expected,mode='full',method='fft');lags=correlation_lags(len(actual),len(expected),mode='full');near=np.abs(lags)<=4800
                self.assertLessEqual(abs(int(lags[near][np.argmax(c[near])])),1)
                with av.open(path) as container:all_audio=np.concatenate([f.to_ndarray().reshape(-1) for f in container.decode(audio=0)])
                tail=all_audio[round((.93+.01)*48000):];self.assertGreater(len(tail),0);self.assertLess(float(np.sqrt(np.mean(tail**2))),.002, 'Audio after the exact selected duration must be silent')

    async def test_cancel_waits_for_export_and_removes_owned_output(self):
        from unittest.mock import patch
        started,release=threading.Event(),threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            staged=type('Stage',(),{'width':32,'height':32,'cancelled':threading.Event(),
                'plan':[chunks.HDRChunk(0,9,0)]})()
            path=Path(folder)/'owned.zip'
            def slow(*args,**kwargs):
                started.set();release.wait(5);path.write_bytes(b'created');return path
            with patch('ComfyUI_zura_nodes.artist_studio.hdr_chunk_exr.export_exr_zip',slow):
                task=asyncio.create_task(delivery.export_long_hdr_outpaint(staged,folder,'test',source_path=None,has_audio=False,start_seconds=0))
                self.assertTrue(await asyncio.to_thread(started.wait,2));task.cancel();release.set()
                with self.assertRaises(asyncio.CancelledError):await task
            self.assertTrue(staged.cancelled.is_set());self.assertFalse(path.exists())
