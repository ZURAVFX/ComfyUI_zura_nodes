"""Compare actual preview pixels with OCIO, independently of HDR inference."""
import importlib
from pathlib import Path
import sys
import types
import unittest

import numpy as np
import PyOpenColorIO as ocio
import torch
import v2_bootstrap

for name, folder in [('ComfyUI_zura_nodes.artist_studio', 'artist_studio'), ('ComfyUI_zura_nodes.paintout', 'paintout')]:
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(v2_bootstrap.ROOT / folder)]
        sys.modules[name] = package
colour = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_preview_colour')
paint = importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


def reference(linear):
    # Independent OCIO CG configuration has the same qualified AP1/D60 and
    # Rec.709/D65 spaces; no model, mock processor or hand-coded matrix.
    config = ocio.Config.CreateFromFile('ocio://cg-config-latest')
    value = np.array(linear, dtype=np.float32, order='C', copy=True)
    config.getProcessor('ACEScg', 'Linear Rec.709 (sRGB)').getDefaultCPUProcessor().applyRGB(value)
    value = np.maximum(value, 0)
    value = value / (1 + value)
    return np.clip(np.where(value <= .0031308, value * 12.92,
                            1.055 * np.maximum(value, .0031308) ** (1 / 2.4) - .055), 0, 1)


class HDRPreviewColourTests(unittest.TestCase):
    def test_ap1_primaries_neutral_hdr_and_negative_samples_match_real_ocio(self):
        pixels = np.array([[[1, 0, 0], [0, 1, 0], [0, 0, 1], [.18, .18, .18],
                            [-.005123, .180123, 2.123456], [12.5, 4.25, .03], [0, 0, 0]]], np.float32)
        original = pixels.tobytes()
        actual = colour.acescg_sdr_preview(pixels)
        np.testing.assert_allclose(actual, reference(pixels), rtol=2e-6, atol=2e-6)
        self.assertEqual(actual.dtype, np.float32)
        self.assertEqual(actual.shape, pixels.shape)
        self.assertEqual(pixels.tobytes(), original, 'Display conversion never changes original negative/HDR samples')
        self.assertLess(float(pixels.min()), 0)
        self.assertGreater(float(pixels.max()), 1)

    def test_red_wall_keeps_rec709_colour_instead_of_treating_ap1_as_srgb(self):
        config = ocio.Config.CreateFromFile('ocio://studio-config-latest')
        wall = np.array([[[.8, .24, .08]]], np.float32)
        config.getProcessor('sRGB Encoded Rec.709 (sRGB)', 'ACEScg').getDefaultCPUProcessor().applyRGB(wall)
        actual = colour.acescg_sdr_preview(wall)
        np.testing.assert_allclose(actual, reference(wall), rtol=2e-6, atol=2e-6)
        legacy_linear = np.maximum(wall, 0) / (1 + np.maximum(wall, 0))
        legacy = np.where(legacy_linear <= .0031308, legacy_linear * 12.92,
                          1.055 * np.maximum(legacy_linear, .0031308) ** (1 / 2.4) - .055)
        self.assertGreater(float(actual[0, 0, 0] - legacy[0, 0, 0]), .05)
        self.assertGreater(float(legacy[0, 0, 1] - actual[0, 0, 1]), .05)

    def test_node_keeps_float_master_tensor_bytes_and_uses_full_raster(self):
        linear = torch.tensor([[[[-.005123, .180123, 2.123456], [.4, .02, .01]],
                                [[12.5, 4.25, .03], [.18, .18, .18]]]], dtype=torch.float32)
        source = paint.encode_ct(linear)
        before = source.numpy().tobytes()
        actual, = colour.ZuraHDRSDRPreview().preview(source)
        self.assertEqual(tuple(actual.shape), tuple(source.shape))
        self.assertEqual(actual.dtype, torch.float32)
        np.testing.assert_allclose(actual[0].numpy(), reference(paint.decode_ct(source)[0].numpy()), rtol=2e-6, atol=2e-6)
        self.assertEqual(source.numpy().tobytes(), before)
        restored = paint.decode_ct(source)
        self.assertLess(float(restored.min()), 0)
        self.assertGreater(float(restored.max()), 12)

    def test_nonfinite_preview_is_rejected_without_changing_source(self):
        with self.assertRaises(ValueError):
            colour.acescg_sdr_preview(np.array([[[np.nan, 0, 1]]], np.float32))
        with self.assertRaises(ValueError):
            colour.ZuraHDRSDRPreview().preview(torch.full((1, 2, 2, 3), float('inf')))


class HDRPreviewGraphTests(unittest.TestCase):
    def test_viewing_branch_never_replaces_float_archive_or_hlg_master_input(self):
        sdr = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_studio')
        native = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_native_graph')
        for mode in ('sdr', 'native'):
            for output in ('acescg_exr', 'hlg_video', 'hlg_and_exr'):
                for precision in ('half', 'float32'):
                    with self.subTest(mode=mode, output=output, precision=precision):
                        args = dict(source='source.mp4', start_frame=0, frame_count=9, fps=24,
                                    output=output, prefix='preview', exr_storage=precision)
                        graph = (sdr.build_hdr_graph(**args) if mode == 'sdr' else
                                 native.build_native_video_graph(**args, width=512, height=512))
                        original = ['hdr_detail' if mode == 'sdr' else 'trim_raster', 0]
                        key = 'zura_hdr_exr' if output != 'hlg_video' else 'zura_hdr_preview_tonemap'
                        self.assertEqual(graph[key], {'class_type': 'ZuraHDRSDRPreview', 'inputs': {'image': original,**({'source_space':'acescg'} if mode=='sdr' else {})}})
                        self.assertEqual(graph['zura_hdr_preview_video']['inputs']['images'], [key, 0])
                        if output != 'hlg_video':
                            master = graph['zura_hdr_archive']['inputs']
                            self.assertEqual(master['images'], original)
                            self.assertEqual(master.get('exr_storage', 'half'), precision)
                        if output != 'acescg_exr':
                            self.assertEqual(graph['zura_hdr_hlg']['inputs'], {'image': original, 'source': 'linear ACEScg' if mode=='sdr' else 'HDR ACEScct', 'destination': 'HDR'})
                            self.assertEqual(graph['zura_hdr_video']['inputs']['bit_depth'], 10)


if __name__ == '__main__':
    unittest.main()
