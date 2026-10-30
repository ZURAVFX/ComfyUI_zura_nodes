"""Exact rational HDR rate retention without video/audio re-encoding."""
import importlib
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import av
import numpy as np
import v2_bootstrap

name='ComfyUI_zura_nodes.artist_studio'
if name not in sys.modules:
    module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/'artist_studio')];sys.modules[name]=module
exact=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_exact_video')


class HDRExactVideoTests(unittest.TestCase):
    def test_rate_reconstructs_common_fractional_rates(self):
        self.assertEqual(exact.exact_rate(24000/1001),Fraction(24000,1001))
        self.assertEqual(exact.exact_rate(30000/1001),Fraction(30000,1001))
        self.assertEqual(exact.exact_rate(23.976),Fraction(2997,125))
        with self.assertRaises(ValueError):exact.exact_rate(float('nan'))

    @unittest.skipUnless(shutil.which('ffmpeg'),'requires FFmpeg')
    def test_saver_cleans_up_failed_ffmpeg_and_publish_without_final_output(self):
        import folder_paths
        from comfy_api.latest import Types  # Import before mocking subprocess.run.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixture=root/'fixture.mp4';output=root/'output';output.mkdir()
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
                'testsrc2=size=64x64:rate=24:duration=1','-c:v','libx264','-pix_fmt','yuv420p',str(fixture)],check=True)
            class Video:
                def get_dimensions(self):return 64,64
                def save_to(self,path,**kwargs):shutil.copy2(fixture,path)
            def fail_ffmpeg(cmd,**kwargs):
                Path(cmd[-1]).write_bytes(b'partial output')
                return types.SimpleNamespace(returncode=1)
            with patch.object(folder_paths,'get_output_directory',return_value=str(output)), \
                 patch.object(folder_paths,'get_save_image_path',return_value=(str(output),'take',1,'genj/hdr','take')):
                with patch.object(exact.subprocess,'run',side_effect=fail_ffmpeg), \
                     self.assertRaisesRegex(ValueError,'frame rate'):
                    exact.ZuraHDRSaveExactRate().save(Video(),'take',24000/1001)
                self.assertEqual(list(output.iterdir()),[])
                def fake_retime(_source,target,_fps):Path(target).write_bytes(b'verified output')
                with patch.object(exact,'retime_without_reencoding',side_effect=fake_retime), \
                     patch.object(exact,'_publish_verified',side_effect=OSError('publication failed')), \
                     self.assertRaisesRegex(OSError,'publication failed'):
                    exact.ZuraHDRSaveExactRate().save(Video(),'take',24000/1001)
                self.assertEqual(list(output.iterdir()),[])

    @unittest.skipUnless(shutil.which('ffmpeg'),'requires FFmpeg')
    def test_real_remux_preserves_frames_colour_audio_and_exact_rate(self):
        with tempfile.TemporaryDirectory() as temp:
            before=Path(temp)/'before.mp4';after=Path(temp)/'after.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=2997/125:duration=2',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2',
                '-frames:v','17','-c:v','libx264','-pix_fmt','yuv420p10le',
                '-x264-params','colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc',
                '-color_primaries','bt2020','-color_trc','arib-std-b67','-colorspace','bt2020nc',
                '-c:a','aac',str(before)],check=True)
            exact.retime_without_reencoding(before,after,24000/1001)
            frames=[];audio=[]
            for path in (before,after):
                with av.open(str(path)) as c:
                    stream=c.streams.video[0]
                    if path==after:
                        self.assertEqual(stream.average_rate,Fraction(24000,1001))
                        self.assertEqual((stream.codec_context.color_primaries,stream.codec_context.color_trc,stream.codec_context.colorspace),(9,18,9))
                    frames.append([f.to_ndarray(format='rgb24') for f in c.decode(video=0)])
                with av.open(str(path)) as c:audio.append(np.concatenate([f.to_ndarray().reshape(-1) for f in c.decode(audio=0)]))
            self.assertEqual((len(frames[0]),len(frames[1])),(17,17))
            self.assertTrue(all(np.array_equal(a,b) for a,b in zip(*frames)))
            self.assertTrue(np.array_equal(*audio))

    @unittest.skipUnless(shutil.which('ffmpeg'),'requires FFmpeg')
    def test_unusual_fractional_rate_preserves_every_frame_with_bounded_rounding(self):
        rate=Fraction(6007500,200273)
        with tempfile.TemporaryDirectory() as temp:
            before=Path(temp)/'before.mp4'; after=Path(temp)/'after.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=29997/1000',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=5',
                '-frames:v','121','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(before)],check=True)
            exact.retime_without_reencoding(before,after,float(rate))
            with av.open(str(before)) as a, av.open(str(after)) as b:
                actual=b.streams.video[0].average_rate
                self.assertLessEqual(abs(Fraction(121,1)/actual-Fraction(121,1)/rate),Fraction(1,1000))
                original=[f.to_ndarray(format='rgb24') for f in a.decode(video=0)]
                delivered=[f.to_ndarray(format='rgb24') for f in b.decode(video=0)]
                self.assertEqual((len(original),len(delivered)),(121,121))
                self.assertTrue(all(np.array_equal(x,y) for x,y in zip(original,delivered)))
            audio=[]
            for path in (before,after):
                with av.open(str(path)) as container:
                    audio.append(np.concatenate([frame.to_ndarray().reshape(-1) for frame in container.decode(audio=0)]))
            self.assertTrue(np.array_equal(*audio))


if __name__=='__main__':unittest.main()
