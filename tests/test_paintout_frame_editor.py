"""CPU checks for source-coordinate integrity and contained frame composites."""
import base64
import importlib.util
import io
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch as mock_patch

import numpy as np
import torch
from PIL import Image
from scipy.ndimage import distance_transform_edt, maximum_filter


ROOT = pathlib.Path(__file__).resolve().parents[1]
# Load only the pure processing modules, without registering the running Comfy server.
package = types.ModuleType('zura_frame_test')
package.__path__ = [str(ROOT / 'paintout')]
sys.modules.setdefault('zura_frame_test', package)
for module in ('paintout', 'frame_editor'):
    spec = importlib.util.spec_from_file_location(f'zura_frame_test.{module}', ROOT / 'paintout' / f'{module}.py')
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
editor = sys.modules['zura_frame_test.frame_editor']


class ContainerFrameCountTests(unittest.TestCase):
    def test_matroska_without_frame_metadata_has_exact_decoded_count(self):
        import subprocess
        core=sys.modules['zura_frame_test.paintout']
        with tempfile.TemporaryDirectory() as directory:
            path=pathlib.Path(directory)/'mask.mkv'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=black:s=64x64:r=24000/1001','-frames:v','9','-c:v','ffv1',str(path)],capture_output=True,check=True)
            info=core.describe(str(path))
            self.assertEqual(info['count'],9)
            self.assertEqual(info['fps_rational'],'24000/1001')


class ExternalFrameReferenceTests(unittest.TestCase):
    def test_export_records_exact_frame_clock_colour_and_source_identity(self):
        import json, subprocess
        spec=importlib.util.spec_from_file_location('zura_frame_test.browser',ROOT/'paintout'/'browser.py')
        browser=importlib.util.module_from_spec(spec)
        with mock_patch.dict(sys.modules,{'server':types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=None))}):
            spec.loader.exec_module(browser)
        with tempfile.TemporaryDirectory() as directory:
            source=pathlib.Path(directory)/'plate.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc=size=64x64:rate=24000/1001','-frames:v','9','-pix_fmt','yuv420p',str(source)],capture_output=True,check=True)
            folders=types.SimpleNamespace(get_output_directory=lambda:directory)
            with mock_patch.dict(sys.modules,{'folder_paths':folders}):
                result=browser.export_source_frame(str(source),4,'srgb_display')
            reference=result['reference']
            self.assertEqual(reference['source_frame'],4)
            self.assertEqual((reference['width'],reference['height']),(64,64))
            self.assertEqual(reference['fps_rational'],'24000/1001')
            self.assertEqual(reference['source_colour_space'],'srgb_display')
            self.assertEqual(reference['edit_colour_space'],'srgb_display')
            self.assertEqual(reference['source']['count'],9)
            self.assertEqual(len(reference['source']['fingerprint']),64)
            self.assertEqual(reference['image_file'],result['download_name'])
            self.assertEqual(json.loads(pathlib.Path(result['reference_path']).read_text()),reference)


def png_mask(mask):
    stream = io.BytesIO()
    Image.fromarray((mask * 255).astype(np.uint8)).save(stream, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()


class FrameEditTests(unittest.TestCase):
    def test_real_encoder_retains_odd_dimensions_and_fractional_frame_clock(self):
        import importlib,json,subprocess
        media=importlib.import_module('zura_frame_test.media')
        from fractions import Fraction
        with tempfile.TemporaryDirectory() as temp:
            for rate in ('24','24000/1001','30000/1001','60000/1001'):
                path=pathlib.Path(temp)/'clock.mp4'
                subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'testsrc=size=125x73:rate={rate}','-frames:v','9','-c:v','libx264','-pix_fmt','yuv444p',str(path)],check=True,capture_output=True)
                media.correct_video_clock(path,rate)
                result=subprocess.run(['ffprobe','-v','error','-show_entries','stream=width,height,avg_frame_rate,nb_frames','-of','json',str(path)],check=True,capture_output=True,text=True)
                stream=json.loads(result.stdout)['streams'][0]
                self.assertEqual((stream['width'],stream['height']),(125,73))
                self.assertEqual(Fraction(stream['avg_frame_rate']),Fraction(rate))
                self.assertEqual(int(stream['nb_frames']),9)

    def test_plate_grid_stretches_whole_frame_and_guides_identically(self):
        core=sys.modules['zura_frame_test.paintout']
        self.assertEqual(core.plate_processing_size(1920,1080),(1920,1088))
        self.assertEqual(core.plate_processing_size(961,541),(1024,576))
        self.assertEqual(core.plate_processing_size(1024,576),(1024,576))
        image=np.random.default_rng(10).random((73,125,3),dtype=np.float32)
        c=dict(rect=[0,0,125,73],resized=[128,128],padded=[128,128],framing_mode='Plate resolution (stretch to next grid)',processing='SDR (sRGB)',space='srgb_display',resampler='float32_bicubic_antialias')
        a=core.crop_work(image,c,'srgb_display')
        b=core.crop_work(image.copy(),c,'srgb_display')
        self.assertEqual(tuple(a.shape),(1,128,128,3))
        torch.testing.assert_close(a,b,rtol=0,atol=0)

    def test_plate_frame_edit_restores_exact_delivery_shape_and_exterior(self):
        original=np.random.default_rng(3).random((73,125,3),dtype=np.float32)
        mask=np.zeros((73,125),np.float32);mask[25:40,50:70]=1
        protection=np.zeros_like(mask);protection[30:35,60:80]=1
        crop,_,patch=editor.prepare_plate_patch(original,mask,3,5,20,256,protection)
        result=editor.composite_patch(patch,torch.ones_like(crop),False)
        self.assertEqual(result.shape,original.shape)
        np.testing.assert_array_equal(result[protection>0],original[protection>0])
        grown=maximum_filter(mask>0,size=7);support=grown|(distance_transform_edt(~grown)<5)
        np.testing.assert_array_equal(result[~support],original[~support])

    def test_rotated_video_is_rejected_before_raw_frame_reshape(self):
        core = sys.modules['zura_frame_test.paintout']
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / 'phone.mp4'
            path.write_bytes(b'fixture')
            response = types.SimpleNamespace(stdout='{"streams":[{"width":1920,"height":1080,"side_data_list":[{"rotation":90}]}]}')
            with mock_patch.object(core.subprocess, 'run', return_value=response):
                with self.assertRaisesRegex(ValueError, 'Bake the video rotation'):
                    core.describe(str(path))

    def test_decoded_cache_prunes_old_owned_files_only(self):
        import os, time
        core = sys.modules['zura_frame_test.paintout']
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            old = root / ('a'*64 + '.rgb');old.write_bytes(b'cache')
            other = root / 'personal.rgb';other.write_bytes(b'keep')
            os.utime(old, (time.time()-90000, time.time()-90000))
            core.prune_frame_cache(root)
            self.assertFalse(old.exists())
            self.assertTrue(other.exists())

    def test_import_rejects_orientation_that_changes_source_coordinates(self):
        import OpenImageIO as oiio
        with tempfile.TemporaryDirectory() as temp:
            for orientation in (1, 2, 6):
                path = pathlib.Path(temp) / f'orientation-{orientation}.tif'
                spec = oiio.ImageSpec(16, 16, 3, oiio.UINT8)
                spec.attribute('Orientation', orientation)
                writer = oiio.ImageOutput.create(str(path))
                writer.open(str(path), spec)
                writer.write_image(np.zeros((16, 16, 3), np.uint8))
                writer.close()
                if orientation == 1:
                    editor.validate_edit_orientation(path)
                else:
                    with self.assertRaisesRegex(ValueError, 'rotation or mirroring'):
                        editor.validate_edit_orientation(path)

    def test_crop_preserves_aspect_and_covers_effective_support(self):
        mask = np.zeros((240, 1600), np.float32)
        mask[5:100, 1510:1600] = 1
        plan = editor.plan_crop(mask, grow=16, feather=24, context=128, max_side=512)
        x, y, w, h = plan['rect']
        rh, rw = plan['resized']
        self.assertEqual(x+w, 1600)
        self.assertEqual(y, 0)
        self.assertLess(abs(rw/rh-w/h), .015)
        self.assertEqual(plan['padded'][0] % 16, 0)
        self.assertEqual(plan['padded'][1] % 16, 0)

    def test_outside_feather_support_is_exact(self):
        rng = np.random.default_rng(8)
        original = rng.random((320, 480, 3), dtype=np.float32)
        mask = np.zeros(original.shape[:2], np.float32)
        mask[140:180, 210:250] = 1
        crop, _, patch = editor.prepare_patch(original, mask, 7, 13, 64, 256)
        generated = torch.full_like(crop, .8)
        result = editor.composite_patch(patch, generated, False)
        grown = maximum_filter(mask > .001, size=15)
        active = grown | (distance_transform_edt(~grown) < 13)
        np.testing.assert_array_equal(result[~active], original[~active])
        self.assertTrue(np.any(result[mask > 0] != original[mask > 0]))

    def test_no_mask_leak_for_disconnected_edge_objects(self):
        original = np.full((137, 211, 3), .25, np.float32)
        mask = np.zeros(original.shape[:2], np.float32)
        mask[:4, :5] = 1
        mask[130:, 205:] = 1
        crop, _, patch = editor.prepare_patch(original, mask, 0, 0, 16, 128)
        result = editor.composite_patch(patch, torch.ones_like(crop), False)
        np.testing.assert_array_equal(result[mask == 0], original[mask == 0])

    def test_foreground_protection_survives_growth_and_feather(self):
        original = np.random.default_rng(12).random((128, 160, 3), dtype=np.float32)
        mask = np.zeros(original.shape[:2], np.float32)
        mask[40:80, 55:90] = 1
        protection = np.zeros_like(mask)
        protection[20:100, 75:80] = 1
        crop, _, patch = editor.prepare_patch(original, mask, 12, 15)
        patch['protection'] = protection
        result = editor.composite_patch(patch, torch.ones_like(crop), False)
        np.testing.assert_array_equal(result[protection > 0], original[protection > 0])
        self.assertTrue(np.any(result[50:60, 60:70] != original[50:60, 60:70]))

    def test_decode_requires_full_source_dimensions(self):
        mask = np.zeros((64, 80), np.float32)
        mask[1, 1] = 1
        np.testing.assert_array_equal(editor.decode_mask(png_mask(mask), 80, 64), mask)
        with self.assertRaisesRegex(ValueError, 'match'):
            editor.decode_mask(png_mask(mask), 81, 64)

    def test_empty_and_invalid_mask_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Draw'):
            editor.decode_mask(png_mask(np.zeros((10, 10))), 10, 10)
        with self.assertRaisesRegex(ValueError, 'read'):
            editor.decode_mask('not base64', 10, 10)

    def test_unexpected_generated_geometry_does_not_modify_original(self):
        original = np.full((128, 128, 3), .25, np.float32)
        mask = np.zeros((128, 128), np.float32)
        mask[40:70, 40:70] = 1
        _, _, patch = editor.prepare_patch(original, mask)
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            editor.composite_patch(patch, torch.ones(1, 65, 65, 3))
        np.testing.assert_array_equal(patch['original'], original)

    def test_float_master_roundtrip_retains_untouched_samples(self):
        from zura_frame_test.paintout import read_image
        with tempfile.TemporaryDirectory() as temporary:
            source = pathlib.Path(temporary) / 'source.png'
            Image.new('RGB', (128, 128), (64, 64, 64)).save(source)
            original = np.random.default_rng(9).random((128, 128, 3), dtype=np.float32)
            mask = np.zeros((128, 128), np.float32)
            mask[50:60, 55:65] = 1
            crop, _, metadata = editor.prepare_patch(original, mask, 0, 0)
            description = {'kind': 'sequence', 'files': [str(source)]}
            metadata.update(description=description, identity=editor.source_identity(description), frame=0)
            paths = types.ModuleType('folder_paths')
            paths.get_output_directory = lambda: temporary
            browser = types.ModuleType('zura_frame_test.browser')
            browser.grant = lambda path: '/test/' + pathlib.Path(path).name
            with mock_patch.dict(sys.modules, {'folder_paths': paths, 'zura_frame_test.browser': browser}):
                saved = editor.ZuraPaintoutFrameComposite().save(metadata, torch.ones_like(crop), False)
            row = saved['ui']['zura_frame'][0]
            self.assertTrue(pathlib.Path(row['png_file']).exists())
            master = read_image(row['file'])
            np.testing.assert_array_equal(master[mask == 0], original[mask == 0])
            self.assertEqual(row['colour_space'], 'srgb_display')


if __name__ == '__main__':
    unittest.main()
