"""Final HLG tags survive native-style remuxing and source audio attachment."""
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest

package=types.ModuleType('zura_hdr_media_test')
package.__path__=[str(Path(__file__).resolve().parents[2]/'paintout')]
sys.modules[package.__name__]=package
media=importlib.import_module('zura_hdr_media_test.media')

def ffmpeg(*args):
    return subprocess.run(['ffmpeg','-v','error','-y',*map(str,args)],capture_output=True,check=True).stdout

class HLGDeliveryTests(unittest.TestCase):
    def test_final_hlg_tags_clock_and_pixels_survive_audio_mux_for_odd_and_even_rasters(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'audio.mov'
            ffmpeg('-f','lavfi','-i','testsrc=size=128x74:rate=24000/1001',
                   '-f','lavfi','-i','sine=frequency=440:sample_rate=48000',
                   '-frames:v',9,'-c:v','libx264','-pix_fmt','yuv444p10le','-c:a','pcm_s16le',source)
            for width,height in [(125,73),(128,74)]:
                with self.subTest(raster=(width,height)):
                    target=root/f'{width}x{height}.mp4'
                    ffmpeg('-f','lavfi','-i',f'testsrc=size={width}x{height}:rate=24000/1001',
                           '-frames:v',9,'-c:v','libx264','-pix_fmt','yuv444p10le','-bf',0,target)
                    original_yuv=ffmpeg('-i',target,'-map','0:v:0','-pix_fmt','yuv444p10le','-vsync',0,'-f','rawvideo','pipe:1')
                    media.correct_video_clock(target,'24000/1001',hdr=True)
                    self.assertTrue(media.copy_source_audio(target,dict(source=dict(kind='video',path=str(source)),
                                    start=0,count=9,fps=24000/1001)))
                    # HLG metadata changes RGB interpretation; decode raw YUV
                    # to verify that setting colour tags never changes samples.
                    tagged_yuv=ffmpeg('-i',target,'-map','0:v:0','-pix_fmt','yuv444p10le','-vsync',0,'-f','rawvideo','pipe:1')
                    self.assertEqual(original_yuv,tagged_yuv)
                    data=json.loads(subprocess.run(['ffprobe','-v','error','-count_frames','-show_streams','-of','json',str(target)],
                                                   capture_output=True,text=True,check=True).stdout)
                    video=next(s for s in data['streams'] if s['codec_type']=='video')
                    self.assertEqual((video['width'],video['height'],video['r_frame_rate'],video['avg_frame_rate'],int(video['nb_read_frames'])),
                                     (width,height,'24000/1001','24000/1001',9))
                    self.assertEqual((video['color_primaries'],video['color_transfer'],video['color_space']),
                                     ('bt2020','arib-std-b67','bt2020nc'))
                    self.assertTrue(any(s['codec_type']=='audio' for s in data['streams']))

if __name__=='__main__':unittest.main()
