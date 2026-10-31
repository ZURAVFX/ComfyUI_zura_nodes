"""Real HDR ingest regression using synthetic, independently calculated swatches.

No model inference is involved. Requires ffmpeg/ffprobe with libx265 and ComfyUI.
"""
import importlib
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
from scipy.signal import correlate, correlation_lags
import v2_bootstrap

for name, path in [('ComfyUI_zura_nodes.artist_studio', 'artist_studio'),
                   ('ComfyUI_zura_nodes.paintout', 'paintout')]:
    if name not in sys.modules:
        module = types.ModuleType(name)
        module.__path__ = [str(v2_bootstrap.ROOT / path)]
        sys.modules[name] = module
native = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_native_source')
paintout = importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')
chunks = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunks')
storage = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_store')
delivery = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_video')
studio = importlib.import_module('ComfyUI_zura_nodes.artist_studio.studio')
hdr_source = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_source')


def expected_linear(signal, transfer):
    """BT.2100 neutral luminance relative to the 203-nit SDR white."""
    if transfer == 'smpte2084':
        m1, m2 = 2610 / 16384, 2523 / 32
        c1, c2, c3 = 3424 / 4096, 2413 / 128, 2392 / 128
        power = signal ** (1 / m2)
        return 10000 / 203 * (max(power - c1, 0) / (c2 - c3 * power)) ** (1 / m1)
    a, b, c = .17883277, .28466892, .55991072928
    scene = signal * signal / 3 if signal <= .5 else (math.exp((signal - c) / a) + b) / 12
    return 1000 / 203 * scene ** 1.2


class HDRSwatchFixtureTests(unittest.TestCase):
    def test_fractional_rate_hdr_input_and_trimmed_audio_share_timing(self):
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg or not shutil.which('ffprobe'):
            self.skipTest('ffmpeg and ffprobe are required')
        fps = 24000 / 1001
        samples_per_frame, start, count = 2002, 7, 9
        rng = np.random.default_rng(904)
        audio = (rng.standard_normal(30 * samples_per_frame) * .08).astype('<f4')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); sound = root / 'audio.f32'; video = root / 'hlg.mov'
            sound.write_bytes(audio.tobytes())
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                'testsrc2=size=96x64:rate=24000/1001', '-f', 'f32le', '-ar', '48000', '-ac', '1', '-i', str(sound),
                '-frames:v', '30', '-c:v', 'libx265', '-x265-params',
                'log-level=error:pools=1:frame-threads=1:colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc',
                '-pix_fmt', 'yuv420p10le', '-color_primaries', 'bt2020', '-color_trc', 'arib-std-b67',
                '-colorspace', 'bt2020nc', '-color_range', 'tv', '-c:a', 'pcm_s16le', '-y', str(video)],
                capture_output=True, check=True)
            images, actual_fps = native.load_native_hdr_frames(str(video), start, count)
            self.assertEqual(len(images), count)
            self.assertAlmostEqual(actual_fps, fps, places=6)
            selected = hdr_source.load_hdr_audio_range(str(video), start, count, actual_fps, 121)[0]['waveform'][0, 0].numpy()
            expected = audio[start * samples_per_frame:(start + count) * samples_per_frame]
            self.assertEqual(len(selected), len(expected))
            correlation = correlate(selected, expected, method='fft')
            lag = correlation_lags(len(selected), len(expected))[int(np.argmax(correlation))]
            self.assertLessEqual(abs(int(lag)), 2)
            self.assertGreater(float(np.corrcoef(selected, expected)[0, 1]), .99)

    def test_tagged_display_p3_pq_video_is_converted_to_acescg(self):
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg or not shutil.which('ffprobe'):
            self.skipTest('ffmpeg and ffprobe are required')
        encoders=subprocess.run([ffmpeg,'-hide_banner','-encoders'],capture_output=True,text=True,check=True).stdout
        if 'libx265' not in encoders:self.skipTest('libx265 is required')
        y,cb,cr=500,460,600
        frame=np.full((32,32),y,dtype='<u2').tobytes()+np.full((16,16),cb,dtype='<u2').tobytes()+np.full((16,16),cr,dtype='<u2').tobytes()
        with tempfile.TemporaryDirectory() as directory:
            raw=Path(directory)/'p3.yuv';raw.write_bytes(frame)
            output=Path(directory)/'p3.mp4'
            subprocess.run([ffmpeg,'-v','error','-f','rawvideo','-pix_fmt','yuv420p10le','-color_range','tv','-colorspace','bt709','-s','32x32','-r','24','-i',str(raw),'-frames:v','1','-c:v','libx265','-x265-params','lossless=1:log-level=error:pools=1:colorprim=smpte432:transfer=smpte2084:colormatrix=bt709','-pix_fmt','yuv420p10le','-color_primaries','smpte432','-color_trc','smpte2084','-colorspace','bt709','-color_range','tv','-y',str(output)],capture_output=True,check=True)
            info=paintout.describe(str(output))
            self.assertEqual((info['primaries'],info['transfer'],info['matrix']),('smpte432','smpte2084','bt709'))
            handoff=studio.paintout_hdr_asset_info(output,'auto',paintout.describe,paintout.selected_space,lambda path:{'path':path,'kind':'video'})
            self.assertEqual(handoff['colour_space'],'auto','Display-P3 PQ remains tag-detected in paintout')
            encoded,_=native.load_native_hdr_frames(str(output),0,1)
            result=paintout.decode_ct(encoded)[0,16,16].numpy()
            luma=(y-64)/876;blue=(cb-512)/896;red=(cr-512)/896
            rgb=np.array([luma+1.5748*red,luma-.187324*blue-.468124*red,luma+1.8556*blue])
            linear=np.array([expected_linear(v,'smpte2084') for v in rgb])
            matrix=np.array(((.73579791,.21216649,.05203560),(.04717988,.93804570,.01477441),(.00356366,.04114189,.95529445)))
            np.testing.assert_allclose(result,matrix @ linear,rtol=.04,atol=.01)

    def test_lossless_encoded_pq_and_hlg_are_tagged_and_preserve_highlights(self):
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg or not shutil.which('ffprobe'):
            self.skipTest('ffmpeg and ffprobe are needed for the HDR fixture')
        encoders = subprocess.run([ffmpeg, '-hide_banner', '-encoders'], capture_output=True, text=True, check=True).stdout
        if 'libx265' not in encoders:
            self.skipTest('ffmpeg libx265 is needed for 10-bit lossless fixture encoding')
        signals = [.15, .35, .5, .65, .75, .85]
        codes = [round(64 + 876 * value) for value in signals]
        y = np.tile(np.repeat(np.array(codes, dtype='<u2'), 16), (32, 1))
        chroma = np.full((16, 48), 512, dtype='<u2')
        frame = y.tobytes() + chroma.tobytes() * 2
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / 'swatches.yuv'
            raw.write_bytes(frame * 2)
            for transfer in ('smpte2084', 'arib-std-b67'):
                with self.subTest(transfer=transfer):
                    output = Path(directory) / (transfer + '.mp4')
                    subprocess.run([ffmpeg, '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'yuv420p10le',
                                    '-s', '96x32', '-r', '24', '-i', str(raw), '-frames:v', '2',
                                    '-c:v', 'libx265', '-x265-params',
                                    f'lossless=1:log-level=error:pools=1:colorprim=bt2020:transfer={transfer}:colormatrix=bt2020nc',
                                    '-pix_fmt', 'yuv420p10le', '-color_primaries', 'bt2020',
                                    '-color_trc', transfer, '-colorspace', 'bt2020nc', '-color_range', 'tv',
                                    '-y', str(output)], capture_output=True, check=True)
                    info = paintout.describe(str(output))
                    self.assertEqual((info['primaries'], info['transfer'], info['matrix'], info['range']),
                                     ('bt2020', transfer, 'bt2020nc', 'tv'))
                    self.assertEqual(info['pixel_format'], 'yuv420p10le')
                    handoff=studio.paintout_hdr_asset_info(output,'auto',paintout.describe,paintout.selected_space,lambda path:{'path':path,'kind':'video'})
                    self.assertEqual(handoff['colour_space'],'pq_rec2020' if transfer=='smpte2084' else 'hlg_rec2020')
                    if transfer=='arib-std-b67':
                        image,mask,plate,*_=paintout.ZuraPaintoutFullFrame().prepare(str(output),handoff['colour_space'],0,2,24,0,768,0,0,
                            processing_mode='HDR (ACEScct)',framing_mode='Source resolution (pad, no resize)',render_width=128,render_height=64)
                        self.assertEqual(plate['space'],'hlg_rec2020');self.assertEqual(plate['processing'],'HDR (ACEScct)')
                        import folder_paths
                        with patch.object(folder_paths,'get_output_directory',return_value=str(directory),create=True):
                            result=paintout.ZuraPaintoutUncrop().save(image,plate,'handoff-check','float32',False,export_format='EXR + HLG video',motion_preview=False)
                        target=Path(result['result'][0]);self.assertEqual(len(list(target.glob('frame_*.exr'))),2)
                        delivered=paintout.describe(str(target/'paintout_HLG_10bit.mp4'))
                        self.assertEqual((delivered['transfer'],delivered['primaries'],delivered['count']),('arib-std-b67','bt2020',2))
                    encoded, fps = native.load_native_hdr_frames(str(output), 0, 2)
                    self.assertEqual(fps, 24)
                    linear = paintout.decode_ct(encoded).cpu().numpy()
                    self.assertEqual(linear.shape, (2, 32, 96, 3))
                    for index, code in enumerate(codes):
                        expected = expected_linear((code - 64) / 876, transfer)
                        for value in linear[0, 16, 8 + index * 16]:
                            self.assertAlmostEqual(float(value), expected, delta=max(.025, expected * .04),
                                                   msg=f'{transfer}, code {code}')
                    self.assertGreater(float(linear[0, 16, 88, 0]), 1.0)
                    np.testing.assert_allclose(linear[0], linear[1], atol=1e-5)
                    if transfer == 'arib-std-b67':
                        stage = storage.HDRChunkStore(directory, 'b' * 32,
                                                      [chunks.HDRChunk(0, 2, 0)], 96, 32, create=True)
                        stage.write(0, encoded)
                        result = delivery.export_hlg_video(stage, directory, 'roundtrip', fps=24, ffmpeg=ffmpeg)
                        delivered = paintout.describe(str(result))
                        self.assertEqual((delivered['primaries'], delivered['transfer'], delivered['matrix'],
                                          delivered['range'], delivered['pixel_format'], delivered['count']),
                                         ('bt2020', 'arib-std-b67', 'bt2020nc', 'tv', 'yuv420p10le', 2))
                        roundtrip, _ = native.load_native_hdr_frames(str(result), 0, 2)
                        output_linear = paintout.decode_ct(roundtrip).cpu().numpy()
                        for index, code in enumerate(codes):
                            expected = expected_linear((code - 64) / 876, transfer)
                            for value in output_linear[0, 16, 8 + index * 16]:
                                self.assertAlmostEqual(float(value), expected, delta=max(.035, expected * .08),
                                                       msg=f'HLG delivery, code {code}')
                        self.assertGreater(float(output_linear[0, 16, 88, 0]), 1.0)


if __name__ == '__main__':
    unittest.main()
