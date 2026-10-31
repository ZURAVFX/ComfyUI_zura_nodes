import importlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch
import wave

import test_artist_studio

planner=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_long_plan')
conversion=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_long_conversion')


class ConversionTests(unittest.TestCase):
    def test_real_media_preflight_binds_sections_and_audio(self):
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:self.skipTest('FFmpeg is required.')
        source={'file':'source.mp4','sha':'a'*64,'asset_kind':'video','duration':3,'width':1920,'height':1080}
        selection,parts,_=planner.plan_hdr_windows(source,start=.517,duration=1.,width=192,height=192,
            left=32,top=32,right=32,bottom=32,colour_space='pq_rec2020')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); intermediate=root/'assembled.mp4';audio=root/'source.wav'
            subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=c=blue:s=192x192:r=24',
                            '-frames:v','25','-c:v','libx264','-pix_fmt','yuv420p',str(intermediate)],check=True)
            with wave.open(str(audio),'wb') as wav:
                wav.setparams((1,2,48000,96000,'NONE','not compressed'));wav.writeframes(bytes(192000))
            with patch.object(conversion,'staging_root',return_value=root/'staging'), patch('ComfyUI_zura_nodes.artist_studio.hdr_package.preflight_archive'):
                job,details=conversion.create_long_hdr_conversion(types.SimpleNamespace(),source,selection,intermediate,
                    review_key=selection['review_key'],output_root=root,check_asset=lambda _:audio,ffmpeg=ffmpeg)
                self.assertEqual(details['frames'],25);self.assertTrue(details['has_audio']);self.assertEqual(details['sections'],len(parts))
                graph=job.render.__self__.make_graph(parts[1])
                self.assertEqual(graph['zura_hdr_source']['inputs']['start_frame'],parts[1].start)
                self.assertAlmostEqual(graph['native_original']['inputs']['start_seconds'],.517+parts[1].start/24)
                job.store.cleanup()
                with self.assertRaisesRegex(ValueError,'selection changed'):
                    conversion.create_long_hdr_conversion(types.SimpleNamespace(),source,selection,intermediate,
                        review_key='wrong',output_root=root,check_asset=lambda _:audio,ffmpeg=ffmpeg)
                with self.assertRaisesRegex(ValueError,'intermediate is unavailable'):
                    conversion.create_long_hdr_conversion(types.SimpleNamespace(),source,selection,root/'../outside.mp4',
                        review_key=selection['review_key'],output_root=root,check_asset=lambda _:audio,ffmpeg=ffmpeg)
