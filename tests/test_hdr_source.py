"""HDR delivery source ranges and EXR packaging: no GPU or network."""
import importlib
import tempfile
import shutil
import subprocess
import sys
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch
import v2_bootstrap

for name, path in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/path)];sys.modules[name]=module
source=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_source')
package=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_package')
hdr_studio=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_studio')
paintout=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


class HDRSourceTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'requires FFmpeg')
    def test_real_trimmed_video_and_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'source.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=24:duration=1',
                            '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1',
                            '-c:v','libx264','-pix_fmt','yuv420p','-x264-params','colorprim=bt709:transfer=bt709:colormatrix=bt709','-color_primaries','bt709','-color_trc','bt709',
                            '-colorspace','bt709','-c:a','aac','-shortest',str(path)],check=True)
            images,fps=source.load_sdr_frames(str(path),5,10)
            audio=source.ZuraHDRLoadAudioRange().load(str(path),5,10,fps)[0]
            self.assertEqual(tuple(images.shape),(10,64,64,3))
            self.assertEqual(audio['waveform'].shape,(1,2,20000))
            self.assertEqual(audio['sample_rate'],48000)
            graph,details=hdr_studio.build_asset_graph({'asset_kind':'video'},
                {'start_frame':5,'frame_count':10,'output':'hlg_and_exr'},lambda asset:path)
            self.assertEqual(details['frames'],10)
            self.assertTrue(details['has_audio'])
            self.assertEqual(graph['zura_hdr_audio_source']['inputs']['start_frame'],5)
            with self.assertRaisesRegex(ValueError,'past the source'):
                hdr_studio.build_asset_graph({'asset_kind':'video'},{'start_frame':23,'frame_count':10},lambda asset:path)

    def test_exact_range_and_sdr_colour_conversion(self):
        info={'kind':'video','count':10,'width':32,'height':32,'fps':24,'transfer':'bt709'}
        frames=[np.full((32,32,3),i/10,np.float32) for i in range(3)]
        with patch.object(paintout,'describe',return_value=info), \
             patch.object(paintout,'selected_space',return_value='rec709_oetf'), \
             patch.object(paintout,'frames',return_value=iter(frames)) as read:
            result,fps=source.load_sdr_frames('source.mp4',4,3)
        read.assert_called_once_with(info,4,3)
        self.assertEqual(tuple(result.shape),(3,32,32,3))
        self.assertEqual(fps,24)
        self.assertGreater(float(result[1,0,0,0]),.1) # Rec.709 transfer was converted to sRGB.

    def test_rejects_hdr_unknown_and_unbounded(self):
        info={'kind':'video','count':200,'width':1920,'height':1080,'fps':24,'transfer':'smpte2084'}
        with patch.object(paintout,'describe',return_value=info), self.assertRaisesRegex(ValueError,'tagged HDR'):
            source.load_sdr_frames('source.mp4',0,1,'srgb_display')
        info['transfer']='bt709'
        with patch.object(paintout,'describe',return_value=info), self.assertRaisesRegex(ValueError,'too large'):
            source.load_sdr_frames('source.mp4',0,121)
        with patch.object(paintout,'describe',return_value={**info,'width':32,'height':32}), \
             patch.object(paintout,'selected_space',side_effect=ValueError('unknown')), self.assertRaisesRegex(ValueError,'unknown'):
            source.load_sdr_frames('source.mp4',0,1)

    def test_archive_is_exact_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)/'genj'/'hdr'/'shot_a';directory.mkdir(parents=True)
            for i in range(3):(directory/f'frame_{i:05}.exr').write_bytes(bytes([i]))
            result=package.package_sequence(temp,'shot_a',3)
            with zipfile.ZipFile(result) as archive:
                self.assertEqual(archive.namelist(),[f'frame_{i:05}.exr' for i in range(3)])
                self.assertEqual(archive.read('frame_00002.exr'),b'\x02')
            with self.assertRaises(FileExistsError):package.package_sequence(temp,'shot_a',3)
            with self.assertRaises(ValueError):package.package_sequence(temp,'../escape',1)

    def test_archive_uses_no_overwrite_rename_when_hardlinks_unsupported(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)/'genj'/'hdr'/'shot_b';directory.mkdir(parents=True)
            (directory/'frame_00000.exr').write_bytes(b'frame')
            with patch('os.link',side_effect=OSError('hard links unsupported')):
                package.preflight_archive(temp)
                archive=package.package_sequence(temp,'shot_b',1)
                with self.assertRaises(FileExistsError):package.package_sequence(temp,'shot_b',1)
            with zipfile.ZipFile(archive) as z:self.assertEqual(z.read('frame_00000.exr'),b'frame')
            self.assertFalse(list(directory.parent.glob('*.partial')))

    def test_preflight_reports_unsupported_output_filesystem(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(package,'_publish_verified',side_effect=OSError('unsupported')):
            with self.assertRaisesRegex(ValueError,'output folder'):package.preflight_archive(temp)
            self.assertEqual(list((Path(temp)/'genj'/'hdr').iterdir()),[])

    def test_graph_keeps_audio_selection_and_packages_exr_after_native_writer(self):
        graph=hdr_studio.build_hdr_graph(source='input.mp4',start_frame=7,frame_count=25,fps=24,
                  has_audio=True,output='hlg_and_exr',prefix='job_1')
        self.assertEqual(graph['zura_hdr_source']['inputs']['start_frame'],7)
        self.assertEqual(graph['zura_hdr_audio_source']['inputs']['start_frame'],7)
        self.assertEqual(graph['zura_hdr_archive']['inputs']['images'],['zura_hdr_exr',0])
        self.assertEqual(graph['zura_hdr_preview_video']['inputs']['audio'],['zura_hdr_trim_audio',0])
        with self.assertRaises(ValueError):hdr_studio.build_hdr_graph(source='x',start_frame=0,frame_count=122,fps=24,prefix='x')


if __name__=='__main__':unittest.main()
