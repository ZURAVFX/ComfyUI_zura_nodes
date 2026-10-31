"""Native HDR timeline selection must retain colour and source timing."""
import importlib
import json
import sys
import subprocess
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch
import v2_bootstrap

for name, folder in [('ComfyUI_zura_nodes.artist_studio', 'artist_studio'),
                     ('ComfyUI_zura_nodes.paintout', 'paintout')]:
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(v2_bootstrap.ROOT / folder)]
        sys.modules[name] = package
native = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_native_source')
audio = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_source')
canvas = importlib.import_module('ComfyUI_zura_nodes.artist_studio.ltx_outpaint')
package = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_package')
sequence = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_sequence')
paintout = importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


class HDRResampleTests(unittest.TestCase):
    def sample(self, fps, start, count, total=240):
        info = dict(kind='sequence', width=2, height=2, count=total, fps_rational=fps,
                    files=[f'frame_{i}.exr' for i in range(total)])
        def decoded(_, first, length):
            for index in range(first, first + length):
                yield np.full((2, 2, 3), index / 100, dtype=np.float32)
        with patch.object(paintout, 'describe', return_value=info), \
             patch.object(paintout, 'selected_space', return_value='acescg'), \
             patch.object(paintout, 'frames', side_effect=decoded), \
             patch.object(paintout, 'working', side_effect=lambda rgb, *_: rgb * 2):
            return native.resample_native_hdr_frames('fixture', start, count)

    def test_60fps_trim_uses_matching_output_timestamps(self):
        data, fps = self.sample('60', .5, 4)
        self.assertEqual(fps, 24)
        np.testing.assert_allclose(data[:, 0, 0, 0].numpy(), [.60, .64, .70, .74])

    def test_lower_rate_reuses_frames_and_preserves_values_above_one(self):
        data, _ = self.sample('12', 1, 4)
        np.testing.assert_allclose(data[:, 0, 0, 0].numpy(), [.24, .24, .26, .26])
        data, _ = self.sample('60', 1, 4)
        self.assertGreater(float(data[0, 0, 0, 0]), 1)

    def test_fractional_source_rate_does_not_drift(self):
        data, _ = self.sample('24000/1001', 0, 48)
        np.testing.assert_allclose(data[[0, 1, 24, 47], 0, 0, 0].numpy(), [0, 0, .46, .92])

    def test_fractional_source_end_keeps_last_output_sample(self):
        data, _ = self.sample('25', 0, 51, total=53)
        self.assertEqual(len(data), 51)
        self.assertAlmostEqual(float(data[-1, 0, 0, 0]), 1.04, places=5)
        with self.assertRaisesRegex(ValueError, 'past the source'):
            self.sample('25', 0, 52, total=53)

    def test_range_past_end_is_rejected_instead_of_shortened(self):
        with self.assertRaisesRegex(ValueError, 'past the source'):
            self.sample('24', 0, 25, total=24)

    def test_real_60fps_hlg_video_matches_review_cfr_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'hlg.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'testsrc2=s=64x64:r=60', '-frames:v', '90', '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p10le', '-color_primaries', 'bt2020',
                            '-color_trc', 'arib-std-b67', '-colorspace', 'bt2020nc', str(path)], check=True)
            actual, fps = native.resample_native_hdr_frames(str(path), .5, 4, colour_space='hlg_rec2020')
            original, _ = native.load_native_hdr_frames(str(path), 30, 9, colour_space='hlg_rec2020')
            self.assertEqual(fps, 24)
            torch.testing.assert_close(actual, original[[1, 3, 6, 8]], rtol=0, atol=0)

    def test_original_hdr_video_cfr_matches_review_at_fractional_trim(self):
        # Frame-coded lossless RGB allows checking source frame identity across
        # the entire trim, independently of either colour conversion or H.264.
        for rate, expected_first in [('25',8), ('30000/1001',9), ('60',19)]:
            with self.subTest(rate=rate), tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'coded.mkv'
                raw=np.stack([np.full((16,16,3),i*512,dtype='<u2') for i in range(120)])
                subprocess.run(['ffmpeg','-v','error','-y','-f','rawvideo','-pixel_format','rgb48le',
                    '-video_size','16x16','-framerate',rate,'-i','pipe:0','-c:v','ffv1',
                    '-pix_fmt','gbrp16le','-color_primaries','bt2020','-color_trc','arib-std-b67',str(path)],
                    input=raw.tobytes(),check=True,capture_output=True)
                reference=subprocess.check_output(['ffmpeg','-v','error','-ss','0.3','-i',str(path),
                    '-vf','setpts=PTS-STARTPTS,fps=24,tpad=stop_mode=clone:stop=1',
                    '-frames:v','24','-an','-sn','-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb48le','-'])
                expected=np.frombuffer(reference,dtype='<u2').reshape(24,16,16,3).astype(np.float32)/65535.
                with patch.object(paintout,'working',side_effect=lambda rgb,*_:rgb):
                    actual,fps=native.resample_native_hdr_frames(str(path),.3,24,colour_space='hlg_rec2020')
                self.assertEqual(fps,24)
                self.assertEqual(round(float(expected[0,0,0,0])*65535/512),expected_first)
                np.testing.assert_array_equal(actual.numpy(),expected)

    def test_timed_audio_uses_non_frame_aligned_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sound.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'sine=frequency=997:sample_rate=48000:duration=2',
                            '-c:a', 'pcm_s16le', str(path)], check=True)
            result, = audio.ZuraHDRLoadTimedAudio().load(str(path), .375, 24, 24.)
            wave = result['waveform'][0, 0]
            self.assertEqual(wave.numel(), 48000)
            t = torch.arange(48000, dtype=torch.float64) / 48000 + .375
            expected = torch.sin(2 * torch.pi * 997 * t).float()
            correlation = torch.dot(wave, expected) / (torch.linalg.vector_norm(wave) * torch.linalg.vector_norm(expected))
            self.assertGreater(float(correlation), .999)
            fractional, = audio.ZuraHDRLoadTimedAudio().load(str(path), .375, 24, 24., source_duration=.97)
            wave = fractional['waveform'][0, 0]
            self.assertGreater(float(wave[1000:46000].abs().mean()), .01)
            self.assertTrue(torch.all(wave[round(.97*48000):] == 0))
            with self.assertRaisesRegex(ValueError, 'duration'):
                audio.ZuraHDRLoadTimedAudio().load(str(path), .375, 24, 24., source_duration=1.1)

    def test_timed_audio_can_pad_only_the_fractional_final_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sound.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'sine=frequency=997:sample_rate=48000:duration=2.12',
                            '-c:a', 'pcm_s16le', str(path)], check=True)
            with self.assertRaisesRegex(ValueError, 'shorter'):
                audio.ZuraHDRLoadTimedAudio().load(str(path), 0., 51, 24.)
            result, = audio.ZuraHDRLoadTimedAudio().load(str(path), 0., 51, 24., True)
            self.assertEqual(result['waveform'].shape[-1], 102000)
            self.assertTrue(torch.all(result['waveform'][..., -200:] == 0))
            with self.assertRaisesRegex(ValueError, 'shorter'):
                audio.ZuraHDRLoadTimedAudio().load(str(path), 0., 53, 24., True)

    def test_review_and_padded_render_have_identical_hdr_frames_and_masks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'take.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'testsrc2=s=96x64:r=60', '-frames:v', '90', '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p10le', str(path)], check=True)
            selected, _ = native.resample_native_hdr_frames(str(path), .5, 12, colour_space='hlg_rec2020')
            padded, = native.ZuraHDRTemporalHold().hold(selected)
            review_frames, review_mask = canvas.prepare_hdr_canvas(selected, 'expand', 192, 128, 48, 32, 48, 32)
            render_frames, render_mask = canvas.prepare_hdr_canvas(padded, 'expand', 192, 128, 48, 32, 48, 32)
            torch.testing.assert_close(review_frames, render_frames[:12], rtol=0, atol=0)
            torch.testing.assert_close(review_mask, render_mask[:12], rtol=0, atol=0)

    def test_hdr_extension_delivery_keeps_frame_range_and_linear_highlights(self):
        import folder_paths
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'take.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'testsrc2=s=96x64:r=60', '-frames:v', '90', '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p10le', str(path)], check=True)
            selected, _ = native.resample_native_hdr_frames(str(path), .5, 4, colour_space='hlg_rec2020')
            padded, = native.ZuraHDRTemporalHold().hold(selected)
            source, mask = canvas.prepare_hdr_canvas(padded, 'expand', 192, 128, 48, 32, 48, 32)
            generated = paintout.encode_ct(torch.full_like(source, 4.0))
            composite = canvas.composite_hdr_outpaint(generated, source, mask, 4)[:4]
            with patch.object(folder_paths, 'get_output_directory', return_value=tmp):
                result = package.ZuraHDRPackageACEScct().package(composite, 'delivery_test')
            archive = result['result'][0]
            with zipfile.ZipFile(archive) as zf:
                self.assertEqual(zf.namelist(), [f'frame_{i:05d}.exr' for i in range(4)])
                zf.extractall(root / 'frames')
            first = paintout.read_image(root / 'frames' / 'frame_00000.exr')
            self.assertEqual(first.shape, (128, 192, 3))
            np.testing.assert_allclose(first[0, 0], 4., atol=.01)
            expected = paintout.decode_ct(selected[0, 32, 48]).numpy()
            np.testing.assert_allclose(first[64, 96], expected, rtol=.002, atol=.002)

    def test_exr_manifest_timeline_checks_content_and_preserves_highlights(self):
        import folder_paths
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'genj_studio' / 'take' / 'frames'
            directory.mkdir(parents=True)
            entries = []
            for index in range(6):
                path = directory / f'frame_{index:03d}.exr'
                paintout.save_exr(path, np.full((16,16,3), 2.0 + index, dtype=np.float32), 'acescg', False)
                entries.append({'name':path.name, 'sha256':sequence._sha(path)})
            manifest = directory.parent / 'hdr_sequence.json'
            manifest.write_text(json.dumps({'frames':entries}), encoding='utf8')
            digest = sequence._sha(manifest)
            with patch.object(folder_paths, 'get_input_directory', return_value=tmp):
                node = native.ZuraHDRSelectNativeTimeline()
                images, fps = node.load('', 0, 4, 24., 'acescg', 12., str(manifest), digest)
                self.assertEqual(fps, 24)
                linear = paintout.decode_ct(images[:, 0, 0, 0]).numpy()
                np.testing.assert_allclose(linear, [2, 2, 3, 3], rtol=1e-5)
                last = directory / entries[-1]['name']
                original = last.read_bytes(); last.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'frame changed'):
                    node.load('', 0, 4, 24., 'auto', 12., str(manifest), digest)
                last.write_bytes(original)
                (directory / entries[1]['name']).write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'frame changed'):
                    node.load('', 0, 4, 24., 'acescg', 12., str(manifest), digest)


if __name__ == '__main__':
    unittest.main()
