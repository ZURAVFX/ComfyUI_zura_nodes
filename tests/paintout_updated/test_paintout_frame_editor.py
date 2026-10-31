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


ROOT = pathlib.Path(__file__).resolve().parents[2]
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
    def test_rgb16_video_retains_sub_eight_bit_precision(self):
        import subprocess
        core=sys.modules['zura_frame_test.paintout']
        pixels=np.empty((2,64,64,3),dtype='<u2')
        pixels[0]=[1,32769,65535]
        pixels[1]=[4097,19001,62003]
        with tempfile.TemporaryDirectory() as directory:
            path=pathlib.Path(directory)/'rgb16.mkv'
            subprocess.run(['ffmpeg','-v','error','-f','rawvideo','-pixel_format','rgb48le','-video_size','64x64','-framerate','25','-i','pipe:0','-c:v','ffv1','-pix_fmt','gbrp16le','-y',str(path)],input=pixels.tobytes(),capture_output=True,check=True)
            info=core.describe(str(path))
            self.assertEqual(info['pixel_format'],'gbrp16le')
            np.testing.assert_array_equal(np.stack(list(core.frames(info,0,2))),pixels.astype(np.float32)/65535.)

    def test_rgb8_video_keeps_exact_encoded_levels_and_cached_frame_order(self):
        import subprocess
        core=sys.modules['zura_frame_test.paintout']
        pixels=np.zeros((3,64,64,3),dtype=np.uint8)
        pixels[0]=255
        pixels[1]=[17,128,254]
        pixels[2]=[230,91,37]
        with tempfile.TemporaryDirectory() as directory:
            path=pathlib.Path(directory)/'rgb8.mkv'
            subprocess.run(['ffmpeg','-v','error','-f','rawvideo','-pixel_format','rgb24','-video_size','64x64','-framerate','24000/1001','-i','pipe:0','-c:v','ffv1','-y',str(path)],input=pixels.tobytes(),capture_output=True,check=True)
            info=core.describe(str(path))
            self.assertIn(info['pixel_format'],('bgr0','rgb24','gbrp'))
            expected=pixels.astype(np.float32)/255.
            np.testing.assert_array_equal(np.stack(list(core.frames(info,0,3))),expected)
            np.testing.assert_array_equal(np.stack(list(core.frames(info,0,3))),expected)
            np.testing.assert_array_equal(np.stack(list(core.frames(info,1,2))),expected[1:])
            with mock_patch.object(core.shutil,'disk_usage',return_value=types.SimpleNamespace(free=0)):
                np.testing.assert_array_equal(np.stack(list(core.frames(info,2,1))),expected[2:])

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
    def test_untagged_source_preview_matches_frame_edit_decoder(self):
        import importlib, subprocess
        core = sys.modules['zura_frame_test.paintout']
        with mock_patch.dict(sys.modules, {'server': types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=None))}):
            browser = importlib.import_module('zura_frame_test.browser')
        pixels = np.zeros((64, 64, 3), dtype=np.uint8)
        pixels[:, :32] = [230, 91, 37]
        pixels[:, 32:] = [39, 174, 229]
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'untagged.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', '64x64', '-framerate', '25', '-i', 'pipe:0', '-frames:v', '1', '-c:v', 'ffv1', '-pix_fmt', 'yuv444p', '-y', str(source)], input=pixels.tobytes(), capture_output=True, check=True)
            description = core.describe(str(source))
            self.assertIn(description.get('matrix'), (None, 'unknown', 'unspecified'))
            space = core.selected_space(description, 'srgb_display')
            original = core.working(torch.from_numpy(next(core.frames(description, 0, 1)))[None], space, 'SDR (sRGB)')[0].numpy()
            expected = (np.clip(original, 0, 1)*255).round().astype(np.uint8)
            with mock_patch.object(browser, 'checked_path', return_value=source):
                preview = np.asarray(Image.open(io.BytesIO(browser.thumbnail(str(source), 'srgb_display', 0, 64))))
            np.testing.assert_array_equal(preview, expected)

    def test_hdr_auto_matrix_is_resolved_before_decode_and_view_before_resize(self):
        import importlib
        core = sys.modules['zura_frame_test.paintout']
        with mock_patch.dict(sys.modules, {'server': types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=None))}):
            browser = importlib.import_module('zura_frame_test.browser')
        description = dict(kind='video', count=1, width=64, height=64, primaries='bt2020', transfer='arib-std-b67', matrix=None)
        calls = []
        def decode(info, frame, count):
            self.assertEqual(info['matrix'], 'bt2020nc')
            calls.append('decode')
            yield np.ones((64, 64, 3), np.float32)*.5
        def view(image, space, processing):
            self.assertEqual(space, 'hlg_rec2020')
            self.assertEqual(tuple(image.shape[1:3]), (64, 64))
            calls.append('view')
            return image
        def downsample(image, height, width):
            self.assertEqual(calls, ['decode', 'view'])
            return torch.zeros((1, height, width, 3))
        with mock_patch.object(browser, 'checked_path', return_value=pathlib.Path('unused.mp4')), mock_patch.object(core, 'describe', return_value=description), mock_patch.object(core, 'frames', side_effect=decode), mock_patch.object(core, 'working', side_effect=view), mock_patch.object(core, 'resize', side_effect=downsample):
            preview = Image.open(io.BytesIO(browser.thumbnail('unused.mp4', 'auto', 0, 32)))
        self.assertEqual(preview.size, (32, 32))

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
    def test_wider_context_adds_real_scene_without_expanding_the_edit(self):
        original=np.random.default_rng(7).random((600,900,3),dtype=np.float32)
        mask=np.zeros((600,900),np.float32);mask[240:310,740:850]=1
        narrow=editor.plan_crop(mask,context=128)
        image,_,patch=editor.prepare_patch(original,mask,context=256)
        self.assertGreater(patch['rect'][2],narrow['rect'][2])
        self.assertGreater(patch['rect'][3],narrow['rect'][3])
        x,y,width,height=patch['rect']
        self.assertLessEqual(x+width,900)
        self.assertLessEqual(y+height,600)
        expected=editor.resize(torch.from_numpy(original[y:y+height,x:x+width])[None],*patch['resized'])
        torch.testing.assert_close(image,expected,rtol=0,atol=0)
        result=editor.composite_patch(patch,torch.ones_like(image),False)
        np.testing.assert_array_equal(result[mask==0],original[mask==0])

    def test_frame_node_annotation_uses_the_effective_model_mask(self):
        mask = np.zeros((73, 125), np.float32)
        mask[25:38, 50:66] = 1
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'source.png'
            Image.new('RGB', (125, 73), (64, 64, 64)).save(source)
            with mock_patch.dict(sys.modules, {'zura_frame_test.browser': types.SimpleNamespace(checked_path=lambda path: source)}):
                image, model_mask, patch, width, height, selection, erased = editor.ZuraPaintoutFrameCrop().prepare(str(source), 0, 'srgb_display', png_mask(mask), 5, 0, 20, 256)
        coverage = model_mask[..., None]*.45
        expected = image*(1-coverage)+torch.tensor([1., .05, .05])*coverage
        torch.testing.assert_close(selection, expected, rtol=0, atol=0)
        self.assertEqual((width, height), (image.shape[2], image.shape[1]))
        self.assertGreater(int(model_mask.count_nonzero()), int(mask.sum()))
        np.testing.assert_array_equal(patch['delivery_mask'], mask)

    def test_model_mask_grows_and_respects_protection_without_baking_composite_growth(self):
        original = np.full((128, 160, 3), .25, np.float32)
        mask = np.zeros((128, 160), np.float32)
        mask[52:61, 73:81] = 1
        protection = np.zeros_like(mask)
        protection[40:74, 78:80] = 1
        image, model_mask, patch = editor.prepare_patch(original, mask, 7, 0, 20, 256, protection=protection)
        grown = maximum_filter(mask > .001, size=15).astype(np.float32)
        grown[protection > .001] = 0
        x, y, width, height = patch['rect']
        expected = np.zeros(patch['padded'], np.float32)
        expected[:height, :width] = grown[y:y+height, x:x+width]
        np.testing.assert_array_equal(model_mask[0].numpy(), expected)
        self.assertGreater(np.count_nonzero(expected), np.count_nonzero(mask))
        np.testing.assert_array_equal(patch['mask'], mask)
        self.assertEqual(patch['grow'], 7)
        result = editor.composite_patch(patch, torch.ones_like(image), False)
        np.testing.assert_array_equal(result[grown == 0], original[grown == 0])

    def test_model_mask_zero_grow_preserves_source_mask_through_grid_resize(self):
        original = np.full((91, 137, 3), .25, np.float32)
        mask = np.zeros((91, 137), np.float32)
        mask[30:41, 60:73] = 1
        _, model_mask, patch = editor.prepare_patch(original, mask, 0, 0, 10, 256)
        x, y, width, height = patch['rect']
        expected = editor.resize(torch.from_numpy(mask[y:y+height, x:x+width])[None, :, :, None], *patch['resized'], 'nearest-exact')[0, :, :, 0].numpy()
        np.testing.assert_array_equal(model_mask[0].numpy(), expected)
        np.testing.assert_array_equal(patch['mask'], mask)
        self.assertEqual(patch['grow'], 0)

    def test_right_edge_crop_takes_real_left_context_instead_of_a_replicated_band(self):
        # The reported 786-pixel crop at x=1134 previously repeated its final
        # source column fourteen times to reach the model's 800-pixel grid.
        height, width = 1088, 1920
        x_ramp = np.broadcast_to(np.arange(width, dtype=np.float32)/width, (height, width))
        y_ramp = np.broadcast_to(np.arange(height, dtype=np.float32)[:, None]/height, (height, width))
        original = np.stack([x_ramp, y_ramp, x_ramp*.3+y_ramp*.7], axis=-1)
        mask = np.zeros((height, width), np.float32)
        mask[196:548, 1262:1901] = 1
        image, _, patch = editor.prepare_patch(original, mask, 0, 0, 128, 1024)
        self.assertEqual(patch['rect'], [1120, 68, 800, 608])
        self.assertEqual(patch['resized'], [608, 800])
        self.assertEqual(patch['padded'], patch['resized'])
        np.testing.assert_array_equal(image[0].numpy(), original[68:676, 1120:1920])
        self.assertEqual(np.unique(image[0, 0, -15:, 0].numpy()).size, 15)
        # Exercise the actual 1920x1080 plate -> 1920x1088 processing path too.
        source, source_mask = original[:1080], mask[:1080]
        plate_image, _, plate_patch = editor.prepare_plate_patch(source, source_mask, 0, 0, 128, 1024)
        self.assertEqual(plate_patch['plate_processing_size'], [1920, 1088])
        x, y, crop_width, crop_height = plate_patch['rect']
        self.assertEqual(x+crop_width, 1920)
        self.assertEqual(plate_patch['resized'], [crop_height, crop_width])
        real_plate = editor.resize(torch.from_numpy(source)[None], 1088, 1920)
        torch.testing.assert_close(plate_image, real_plate[:, y:y+crop_height, x:x+crop_width], rtol=0, atol=0)
        self.assertEqual(np.unique(plate_image[0, 0, -15:, 0].numpy()).size, 15)
        result = editor.composite_patch(plate_patch, torch.ones_like(plate_image), False)
        np.testing.assert_array_equal(result[source_mask == 0], source[source_mask == 0])

    def test_all_plate_borders_use_real_grid_aligned_context(self):
        height, width = 384, 640
        x_ramp = np.broadcast_to(np.arange(width, dtype=np.float32)/width, (height, width))
        y_ramp = np.broadcast_to(np.arange(height, dtype=np.float32)[:, None]/height, (height, width))
        original = np.stack([x_ramp, y_ramp, x_ramp*.3+y_ramp*.7], axis=-1)
        for edge, bounds in [('left', (60, 100, 0, 143)), ('right', (60, 100, 498, 640)), ('top', (0, 103, 180, 270)), ('bottom', (282, 384, 180, 270))]:
            with self.subTest(edge=edge):
                mask = np.zeros((height, width), np.float32)
                top, bottom, left, right = bounds
                mask[top:bottom, left:right] = 1
                image, _, patch = editor.prepare_patch(original, mask, 0, 0, 20, 1024)
                x, y, crop_width, crop_height = patch['rect']
                self.assertEqual((crop_width % 16, crop_height % 16), (0, 0))
                self.assertEqual(patch['resized'], [crop_height, crop_width])
                self.assertEqual(patch['padded'], patch['resized'])
                np.testing.assert_array_equal(image[0].numpy(), original[y:y+crop_height, x:x+crop_width])
                result = editor.composite_patch(patch, torch.ones_like(image), False)
                np.testing.assert_array_equal(result[mask == 0], original[mask == 0])

    def test_downscaled_crop_uses_whole_grid_resize_and_restores_source_bounds(self):
        height, width = 720, 1920
        ramp = np.broadcast_to(np.arange(width, dtype=np.float32)/width, (height, width))
        original = np.stack([ramp, ramp*.7, ramp*.3], axis=-1)
        mask = np.zeros((height, width), np.float32)
        mask[173:551, 289:1813] = 1
        image, model_mask, patch = editor.prepare_patch(original, mask, 5, 0, 128, 512)
        self.assertEqual(patch['resized'], patch['padded'])
        self.assertLessEqual(max(patch['resized']), 512)
        self.assertEqual(tuple(image.shape[1:3]), tuple(patch['resized']))
        self.assertEqual(tuple(model_mask.shape[1:]), tuple(patch['resized']))
        x, y, crop_width, crop_height = patch['rect']
        expected = editor.resize(torch.from_numpy(original[y:y+crop_height, x:x+crop_width])[None], *patch['resized'])
        torch.testing.assert_close(image, expected, rtol=0, atol=0)
        self.assertGreater(float((image[0, :, -1]-image[0, :, -2]).abs().max()), 0)
        result = editor.composite_patch(patch, torch.ones_like(image), False)
        self.assertEqual(result.shape, original.shape)
        outside = ~maximum_filter(mask > .001, size=11)
        np.testing.assert_array_equal(result[outside], original[outside])

    def test_tiny_non_grid_source_resizes_without_synthetic_edge_pixels(self):
        height, width = 31, 47
        ramp = np.broadcast_to(np.arange(width, dtype=np.float32)/width, (height, width))
        original = np.stack([ramp, ramp*.7, ramp*.3], axis=-1)
        mask = np.zeros((height, width), np.float32)
        mask[12:19, 20:28] = 1
        image, _, patch = editor.prepare_patch(original, mask, 0, 0, 20, 64)
        self.assertEqual(patch['rect'], [0, 0, width, height])
        self.assertEqual(patch['padded'], patch['resized'])
        expected = editor.resize(torch.from_numpy(original)[None], *patch['resized'])
        torch.testing.assert_close(image, expected, rtol=0, atol=0)
        self.assertGreater(float((image[0, :, -1]-image[0, :, -2]).abs().max()), 0)
        result = editor.composite_patch(patch, torch.ones_like(image), False)
        self.assertEqual(result.shape, original.shape)
        np.testing.assert_array_equal(result[mask == 0], original[mask == 0])

    def test_plate_model_mask_transforms_the_visible_source_boundary_and_protected_holes(self):
        original = np.full((73, 125, 3), .25, np.float32)
        mask = np.zeros((73, 125), np.float32)
        mask[25:38, 50:66] = 1
        protection = np.zeros_like(mask)
        protection[20:45, 60:64] = 1
        for grow in (0, 5):
            crop, model_mask, patch = editor.prepare_plate_patch(original, mask, grow, 0, 20, 96, protection)
            expected = maximum_filter(mask > .001, size=2*grow+1).astype(np.float32)
            expected[protection > .001] = 0
            # Follow the actual plate grid, context crop, model resize and pad.
            pw, ph = patch['plate_processing_size']
            expected = editor.resize(torch.from_numpy(expected)[None, :, :, None], ph, pw, 'nearest-exact')
            x, y, width, height = patch['rect']
            rh, rw = patch['resized']
            expected = editor.resize(expected[:, y:y+height, x:x+width], rh, rw, 'nearest-exact')[0, :, :, 0].numpy()
            padded = np.zeros(patch['padded'], np.float32)
            padded[:rh, :rw] = expected
            np.testing.assert_array_equal(model_mask[0].numpy(), padded)
            np.testing.assert_array_equal(patch['delivery_mask'], mask)
            self.assertEqual(patch['delivery_grow'], grow)
            result = editor.composite_patch(patch, torch.ones_like(crop), False)
            allowed = maximum_filter(mask > .001, size=2*grow+1)
            allowed[protection > .001] = False
            np.testing.assert_array_equal(result[~allowed], original[~allowed])

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


class ErasedReferenceTests(unittest.TestCase):
    def test_neighbour_fill_hides_subject_and_holes_but_retains_protection(self):
        image = torch.full((1, 96, 96, 3), .25)
        image[:, 25:70, 25:70] = torch.tensor([1., 0., 0.])
        mask = torch.zeros((1, 96, 96)); mask[:, 25:70, 25:70] = 1
        mask[:, 40:45, 40:45] = 0
        protection = np.zeros((96, 96), np.float32); protection[55:60, 55:60] = 1
        original, original_mask = image.clone(), mask.clone()
        result = editor.erased_reference(image, mask, protection)
        torch.testing.assert_close(result[0, 40:45, 40:45], torch.full((5, 5, 3), .25))
        torch.testing.assert_close(result[0, 55:60, 55:60], original[0, 55:60, 55:60])
        torch.testing.assert_close(image, original); torch.testing.assert_close(mask, original_mask)
        torch.testing.assert_close(result[0, 25:40, 25:70], torch.full((15, 45, 3), .25))

    def test_grown_crop_erasure_and_final_boundary_are_independent(self):
        original = np.full((101, 155, 3), .25, np.float32)
        original[35:65, 60:90] = [1, 0, 0]
        mask = np.zeros((101, 155), np.float32); mask[35:65, 60:90] = 1
        protection = np.zeros_like(mask); protection[45:50, 70:75] = 1
        crop, matte, patch = editor.prepare_plate_patch(original, mask, grow=9, protection=protection)
        result = editor.erased_reference(crop, matte, patch['model_protection'])
        support = matte[0].numpy() > .001
        np.testing.assert_allclose(result[0].numpy()[support], .25)
        protected = patch['model_protection'] > .001
        np.testing.assert_array_equal(result[0].numpy()[protected], crop[0].numpy()[protected])
        final = editor.composite_patch(patch, result, False)
        effective = editor.effective_edit_mask(mask, 9, 0, protection)
        np.testing.assert_array_equal(final[effective == 0], original[effective == 0])
        np.testing.assert_array_equal(mask[45:50, 70:75], 1)

    def test_output_ports_are_appended(self):
        self.assertEqual(editor.ZuraPaintoutFrameCrop.RETURN_NAMES[:6],
                         ('context_image', 'edit_mask', 'patch', 'width', 'height', 'selection_preview'))
        self.assertEqual(editor.ZuraPaintoutFrameCrop.RETURN_NAMES[6], 'erased_reference')




class ContextBrightnessTests(unittest.TestCase):
    def context_fixture(self):
        y,x=np.mgrid[:160,:192]
        original=np.repeat((.18+.45*x/191+.06*y/159)[...,None],3,axis=-1).astype(np.float32)
        mask=np.zeros((160,192),np.float32);mask[45:115,65:135]=1
        return original,mask

    def test_raw_context_corrects_scalar_exposure_without_using_removed_subject(self):
        from zura_frame_test.frame_layers import adjust_brightness
        original,mask=self.context_fixture()
        generated=adjust_brightness(original,-.6)
        original[mask>0]=.97
        generated[mask>0]=.2
        adjusted,ev,samples=editor.match_patch_brightness(original,generated,mask)
        self.assertAlmostEqual(ev,.6,places=5);self.assertGreater(samples,64)
        np.testing.assert_allclose(adjusted[mask==0],original[mask==0],atol=2e-7)
        np.testing.assert_allclose(adjusted[mask>0],adjust_brightness(np.array([.2],np.float32),.6)[0],atol=2e-7)

    def test_context_outliers_do_not_turn_auto_match_into_subject_fitting(self):
        from zura_frame_test.frame_layers import adjust_brightness
        original,mask=self.context_fixture();generated=adjust_brightness(original,-.4)
        generated[:25]=.95
        adjusted,ev,samples=editor.match_patch_brightness(original,generated,mask)
        self.assertAlmostEqual(ev,.4,places=5);self.assertGreater(samples,64)
        self.assertTrue(np.isfinite(adjusted).all())

    def test_insufficient_clipped_or_inconsistent_context_leaves_neutral(self):
        original,mask=self.context_fixture()
        for source,generated,matte in [(original,original*.5,np.ones_like(mask)),(np.ones_like(original),original,mask)]:
            with self.subTest(full=bool(matte.all())):
                output,ev,samples=editor.match_patch_brightness(source,generated,matte)
                self.assertEqual((ev,samples),(0.,0));np.testing.assert_array_equal(output,generated)
        rng=np.random.default_rng(47)
        source=rng.uniform(.08,.9,size=original.shape).astype(np.float32)
        generated=rng.uniform(.08,.9,size=original.shape).astype(np.float32)
        output,ev,samples=editor.match_patch_brightness(source,generated,mask)
        self.assertEqual((ev,samples),(0.,0));np.testing.assert_array_equal(output,generated)

    def test_auto_fit_is_bounded_and_does_not_change_outside_composite_or_protection(self):
        from zura_frame_test.frame_layers import adjust_brightness
        original,mask=self.context_fixture();protection=np.zeros_like(mask);protection[60:70,80:90]=1
        crop,_,patch=editor.prepare_patch(original,mask,context=0,max_side=256,protection=protection)
        generated=adjust_brightness(crop.numpy(),-1.5)
        result=editor.composite_patch(patch,torch.from_numpy(generated),True)
        self.assertEqual(patch['auto_brightness_ev'],1.)
        self.assertGreater(patch['auto_brightness_samples'],64)
        np.testing.assert_array_equal(result[(mask==0)|(protection>0)],original[(mask==0)|(protection>0)])

    def test_disabling_auto_match_retains_uncorrected_generation(self):
        original,mask=self.context_fixture();crop,_,patch=editor.prepare_patch(original,mask,context=0,max_side=256)
        generated=crop*.8
        result=editor.composite_patch(patch,generated,False)
        self.assertEqual(patch['auto_brightness_ev'],0.)
        self.assertEqual(patch['auto_brightness_samples'],0)
        np.testing.assert_array_equal(result[mask==0],original[mask==0])
        self.assertLess(result[80,90,0],original[80,90,0])

    def test_hdr_auto_match_preserves_extended_master_outside_and_protected_pixels(self):
        from zura_frame_test.frame_layers import adjust_brightness
        original,mask=self.context_fixture()
        protection=np.zeros_like(mask);protection[60:70,80:90]=1
        crop,_,patch=editor.prepare_patch(original,mask,context=0,max_side=256,protection=protection)
        master=original*30-1
        master[0,0]=[-.2,12,24]
        patch.update(hdr_original=master.copy(),hdr_source_space='Linear (ACEScg)')
        # Isolate the HDR reconstruction contract from the colour transform:
        # edited pixels can exceed one and untouched master samples remain exact.
        with mock_patch.object(editor,'unworking',side_effect=lambda values,*args: values*10):
            result=editor.composite_patch(patch,torch.from_numpy(adjust_brightness(crop.numpy(),-.4)),True)
        self.assertAlmostEqual(patch['auto_brightness_ev'],.4,places=5)
        untouched=(mask==0)|(protection>0)
        np.testing.assert_array_equal(result[untouched],master[untouched])
        self.assertGreater(result[80,100,0],1.)
        self.assertLess(result.min(),0.)


if __name__ == '__main__':
    unittest.main()

