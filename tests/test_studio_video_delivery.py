from fractions import Fraction
from pathlib import Path
import sys
import tempfile
import unittest
import hashlib
import av
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfylink.studio_direct_video import prepare_video_delivery, inspect_video_master


class VideoDeliveryTests(unittest.TestCase):
    def test_real_movies_retain_frames_and_follow_ae_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.mp4'
            with av.open(str(source),'w') as movie:
                stream=movie.add_stream('libx264',rate=24)
                stream.width=64;stream.height=48;stream.pix_fmt='yuv420p'
                for i in range(5):
                    pixels=np.full((48,64,3),32+i*20,dtype=np.uint8)
                    frame=av.VideoFrame.from_ndarray(pixels,format='rgb24')
                    for packet in stream.encode(frame):movie.mux(packet)
                for packet in stream.encode():movie.mux(packet)
            original=hashlib.sha256(source.read_bytes()).hexdigest()
            rate={'numerator':30000,'denominator':1001}
            for precision,extension,codec in [('sdr8','.mov','prores4444'),('prores12','.mov','prores4444')]:
                with self.subTest(precision=precision):
                    path=prepare_video_delivery(source,root,precision=precision,width=64,height=48,frame_count=5,frame_rate=rate)
                    self.assertEqual(path.suffix,extension)
                    info=inspect_video_master(path,width=64,height=48,frame_count=5,frame_rate=rate)
                    self.assertEqual(info['codec'],codec)
                    self.assertEqual(info['bitDepth'],12)
                    self.assertEqual(prepare_video_delivery(source,root,precision=precision,width=64,height=48,frame_count=5,frame_rate=rate),path)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),original)
            with self.assertRaisesRegex(ValueError,'missing'):
                prepare_video_delivery(source,root,precision='sdr8',width=64,height=48,frame_count=6,frame_rate=rate)


if __name__=='__main__':unittest.main()
