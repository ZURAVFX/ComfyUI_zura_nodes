"""HDR colour guards, view-based frame edits and exact-raster conversion adapters."""
import base64
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import torch
from scipy.ndimage import maximum_filter


ROOT = Path(__file__).resolve().parents[2]
package = types.ModuleType('zura_hdr_test')
package.__path__ = [str(ROOT / 'paintout')]
sys.modules[package.__name__] = package
core = importlib.import_module('zura_hdr_test.paintout')
editor = importlib.import_module('zura_hdr_test.frame_editor')
hdr = importlib.import_module('zura_hdr_test.hdr')
with patch.dict(sys.modules, {'server': types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=None))}):
    browser = importlib.import_module('zura_hdr_test.browser')


def mask_png(mask):
    buffer = io.BytesIO()
    Image.fromarray((mask * 255).astype(np.uint8)).save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


class HDRAdaptersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use the installed native colour transform, without running a model.
        comfy = Path(sys.executable).resolve().parents[2]
        if not (comfy / 'comfy_extras/nodes_images.py').exists():
            raise unittest.SkipTest('Run with the ComfyUI Python environment for native HDR colour checks.')
        sys.path.insert(0, str(comfy))
        cls.native_images = importlib.import_module('comfy_extras.nodes_images')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_shape_preserves_raster_by_stretch_and_exact_frame_tail(self):
        self.assertEqual(hdr.conversion_shape(370, 210, 14), (384, 256, 17))
        self.assertEqual(hdr.conversion_shape(125, 73, 1), (128, 128, 9))
        for values in ((1920, 1080, 81), (384, 224, 122), (True, 64, 9), (64, 64, 0)):
            with self.assertRaises(ValueError):
                hdr.conversion_shape(*values)

    def test_filename_gateways_match_native_unet_combo_type(self):
        from comfy_execution.validation import validate_node_input
        self.assertFalse(validate_node_input('STRING','COMBO'))
        self.assertTrue(validate_node_input(hdr.ZuraPaintoutHDRResume.RETURN_TYPES[2],'COMBO'))
        self.assertTrue(validate_node_input(hdr.ZuraPaintoutHDRPrepare.RETURN_TYPES[7],'COMBO'))

    def test_source_pipeline_guard_catches_mismatch_before_sampling(self):
        source = self.root / 'source.mp4'
        source.write_bytes(b'fixture')
        sdr = dict(kind='video', width=1920, height=1080, count=81, transfer='bt709', primaries='bt709')
        native = dict(sdr, transfer='smpte2084', primaries='bt2020')
        node = hdr.ZuraPaintoutColourCheck()
        with patch.object(hdr, 'describe', return_value=sdr):
            self.assertEqual(node.check(str(source), 'auto', 'sdr_sdr', 81), (str(source.resolve()),))
            with self.assertRaisesRegex(ValueError, 'HDR to HDR needs'):
                node.check(str(source), 'auto', 'hdr_hdr', 81)
            with self.assertRaisesRegex(ValueError, '40 million'):
                node.check(str(source), 'auto', 'sdr_hdr', 81)
        with patch.object(hdr, 'describe', return_value=native):
            self.assertEqual(node.check(str(source), 'auto', 'hdr_hdr', 81), (str(source.resolve()),))
            with self.assertRaisesRegex(ValueError, 'Choose HDR to HDR'):
                node.check(str(source), 'auto', 'sdr_hdr', 81)

    def test_native_hlg_and_pq_keep_highlights_above_reference_white(self):
        linear = torch.full((2, 8, 8, 3), 4.0)
        for space, native in [('hlg_rec2020', 'HDR'), ('pq_rec2020', 'HDR PQ')]:
            encoded = core.native_colour(linear, 'linear ACEScg', native)
            restored = core.to_linear(encoded, space)
            self.assertTrue(torch.isfinite(restored).all())
            self.assertGreater(float(restored.max()), 3.9)
            torch.testing.assert_close(restored, linear, atol=.002, rtol=.002)

    def test_sdr_prepare_uses_actual_native_acescct_and_holds_tail(self):
        source = self.root / 'repaired'
        source.mkdir()
        # These are the same ACEScg master samples exported by SDR paintout.
        a = core.to_linear(torch.full((73, 125, 3), .4), 'srgb_display').numpy()
        b = core.to_linear(torch.full((73, 125, 3), .7), 'srgb_display').numpy()
        core.save_exr(source/'frame_000003.exr', a, 'acescg', False)
        core.save_exr(source/'frame_000004.exr', b, 'acescg', False)
        plate = dict(processing='SDR (sRGB)', space='srgb_display', count=2, fps=24000/1001,
                     fps_rational='24000/1001', source=dict(width=125, height=73), start=3)
        guide, take, width, height, count, fps, window, model_name = hdr.ZuraPaintoutHDRPrepare().prepare(str(source), plate)
        self.assertEqual((width, height, count), (128, 128, 9))
        self.assertEqual(tuple(guide.shape), (9, 128, 128, 3))
        self.assertEqual(take['plate']['fps_rational'], '24000/1001')
        self.assertEqual((take['width'], take['height'], take['count']), (125, 73, 2))
        reference = core.native_colour(torch.full((1, 128, 128, 3), .7), 'sRGB', 'HDR ACEScct')
        torch.testing.assert_close(guide[1:], reference.expand(8, -1, -1, -1), atol=3e-6, rtol=3e-6)
        self.assertEqual(fps, 24000/1001)
        self.assertEqual(window, 0)
        self.assertEqual(model_name, hdr.DEFAULT_HDR_MODEL)
        high_rate = dict(plate, fps=60000/1001, fps_rational='60000/1001')
        high_fps = hdr.ZuraPaintoutHDRPrepare().prepare(str(source), high_rate)[5]
        self.assertEqual(high_fps, 60.)
        self.assertEqual(high_rate['fps_rational'], '60000/1001')
        with self.assertRaisesRegex(ValueError, 'expects an SDR'):
            hdr.ZuraPaintoutHDRPrepare().prepare(str(source), dict(plate, space='acescg'))

    def test_hdr_frame_edit_preserves_highlights_and_negative_pixels_outside_support(self):
        original = np.full((73, 125, 3), 4.0, np.float32)
        original[0, 0] = [-.02, 12., .1]
        original[30:35, 50:70] = [3., 7., 2.]
        path = self.root/'source.exr'
        core.save_exr(path, original, 'acescg', False)
        mask = np.zeros((73, 125), np.float32)
        mask[28:42, 50:70] = 1
        crop, _, data, *_ = editor.ZuraPaintoutFrameCrop().prepare(str(path), 0, 'acescg', mask_png(mask), 3, 0, 32, 256)
        self.assertEqual(data['colour_space'], 'acescg')
        self.assertLessEqual(float(crop.max()), 1.)
        self.assertGreaterEqual(float(crop.min()), 0.)
        result = editor.composite_patch(data, torch.full_like(crop, .6), False)
        outside = ~maximum_filter(mask > .001, size=7)
        np.testing.assert_array_equal(result[outside], original[outside])
        self.assertTrue(np.isfinite(result).all())
        self.assertTrue(np.any(result[mask > .001] != original[mask > .001]))
        self.assertGreater(float(result[outside].max()), 1.)
        # Foreground protection must remain exact even inside a grown repair.
        data['delivery_protection'] = np.zeros_like(mask)
        data['delivery_protection'][30:35, 60:65] = 1
        protected = editor.composite_patch(data, torch.full_like(crop, .5), False)
        np.testing.assert_array_equal(protected[30:35, 60:65], original[30:35, 60:65])

    def test_hdr_candidate_is_acescg_master_and_sdr_png_preview(self):
        import OpenImageIO as oiio
        original = np.full((64, 64, 3), 8., np.float32)
        source = self.root/'source.exr'
        core.save_exr(source, original, 'acescg', False)
        mask = np.zeros((64, 64), np.float32)
        mask[20:40, 20:40] = 1
        crop, _, data, *_ = editor.ZuraPaintoutFrameCrop().prepare(str(source), 0, 'acescg', mask_png(mask), 0, 0, 16, 128)
        with patch.dict(sys.modules, {'folder_paths': types.SimpleNamespace(get_output_directory=lambda: str(self.root))}):
            result = editor.ZuraPaintoutFrameComposite().save(data, crop, False)
        row = result['ui']['zura_frame'][0]
        self.assertEqual(row['colour_space'], 'acescg')
        self.assertEqual(row['preview_colour_space'], 'srgb_display')
        master = core.read_image(row['file'])
        np.testing.assert_array_equal(master[mask == 0], original[mask == 0])
        reader = oiio.ImageInput.open(row['file'])
        try:
            # OIIO may canonicalise the ACEScg name to its OCIO scene role.
            self.assertIn(reader.spec().getattribute('oiio:ColorSpace'), ('ACEScg', 'lin_ap1_scene'))
        finally:
            reader.close()
        preview = core.read_image(row['png_file'])
        self.assertTrue(np.isfinite(preview).all())
        self.assertLessEqual(float(preview.max()), 1.)
        self.assertGreater(float(preview.mean()), .8)

    def test_hdr_save_restores_exact_raster_count_clock_and_linear_highlights(self):
        media = importlib.import_module('zura_hdr_test.media')
        collected = []
        class Delivery:
            def __init__(self, target, plate, format, preview): self.plate = plate
            def append(self, image): collected.append(image.clone())
            def finish(self): return {}
        take = dict(width=125, height=73, count=2, padded=[128, 128], padded_count=9,
                    plate=dict(count=2, start=7, fps=24000/1001, fps_rational='24000/1001',
                               source=dict(kind='video', path='source.mp4', width=125, height=73)))
        images = core.encode_ct(torch.full((9, 128, 128, 3), 5.))
        with patch.dict(sys.modules, {'folder_paths': types.SimpleNamespace(get_output_directory=lambda: str(self.root))}), patch.object(media, 'Delivery', Delivery):
            output = hdr.ZuraPaintoutHDRSave().save(images, take, 'paintout/test', 'float32', 'EXR sequence')
        directory = Path(output['result'][0])
        files = sorted(directory.glob('*.exr'))
        self.assertEqual([p.name for p in files], ['frame_000007.exr', 'frame_000008.exr'])
        self.assertEqual(len(collected), 2)
        self.assertEqual(tuple(collected[0].shape), (73, 125, 3))
        np.testing.assert_allclose(core.read_image(files[0]), 5., rtol=3e-6)
        metadata = json.loads((directory/'paintout.json').read_text())
        self.assertEqual(metadata['plate']['fps_rational'], '24000/1001')
        self.assertEqual(metadata['pipeline'], 'sdr_hdr')

    def test_media_info_reports_colour_without_refusing_unknown_tags(self):
        source = self.root/'source.mp4'
        source.write_bytes(b'fixture')
        d = dict(path=str(source), kind='video', width=64, height=64, count=9,
                 fps=25, transfer='arib-std-b67', primaries='bt2020')
        with patch.object(core, 'describe', return_value=d):
            info = browser.describe_media(str(source))
            self.assertEqual(info['resolved_colour'], 'hlg_rec2020')
        with patch.object(core, 'describe', return_value=dict(d, transfer=None)):
            info = browser.describe_media(str(source))
            self.assertNotIn('resolved_colour', info)
            self.assertIn('Choose its actual colour space', info['colour_error'])


if __name__ == '__main__':
    unittest.main()
