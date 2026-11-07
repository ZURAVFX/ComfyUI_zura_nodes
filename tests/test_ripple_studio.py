"""CPU contracts for source-sized Ripple delivery, without model inference."""
import importlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ripple_studio_test', ROOT/'paintout'/'ripple_studio.py')
ripple = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ripple)
package = types.ModuleType('ripple_studio_plate_test')
package.__path__ = [str(ROOT/'paintout')]
sys.modules.setdefault(package.__name__, package)
native = importlib.import_module(package.__name__ + '.paintout')


class RippleStudioTimingTests(unittest.TestCase):
    def test_processing_size_rounds_up_each_axis_at_each_requested_scale(self):
        self.assertEqual(ripple.ripple_working_size(1921, 1081, 1, 'h3'), (1952, 1088))
        self.assertEqual(ripple.ripple_working_size(1921, 1081, .75, 'h3'), (1472, 832))
        self.assertEqual(ripple.ripple_working_size(1921, 1081, .5, 'h3'), (992, 544))
        self.assertEqual(ripple.ripple_working_size(1921, 1081, .25, 'h3'), (512, 288))
        self.assertEqual(ripple.ripple_working_size(1921, 1081, 1, 'ltx'), (1984, 1088))
        self.assertEqual(ripple.ripple_working_size(1921, 1081, .25, 'ltx'), (512, 320))
        with self.assertRaisesRegex(ValueError, 'smaller processing size'):
            ripple.ripple_working_size(4097, 1080, 1, 'h3')

    def test_h3_padding_keeps_every_source_frame_and_holds_the_real_last(self):
        self.assertEqual([ripple.h3_working_frames(n) for n in (1, 5, 6, 22, 23, 94)],
                         [5, 5, 22, 22, 39, 107])
        images = torch.arange(97, dtype=torch.float32).reshape(97, 1, 1, 1).expand(-1, 64, 96, 3).clone()
        images[94:] = 999  # LTX's earlier padding is never authoritative.
        plate = dict(_work_images=images, count=94, start=37, fps=30000/1001,
                     fps_rational='30000/1001', source={'path':'clip.mov'},
                     processing='SDR (sRGB)', space='srgb_display',
                     framing_mode='Full frame (stretch to working size)')
        first = torch.full_like(images[:1], 500)
        last = torch.full_like(images[:1], 800)
        context, edited, inference = ripple.ZuraRippleH3Guide().prepare(
            plate, [(93, last, 1), (3, first, 1)])
        self.assertEqual(inference, 107)
        torch.testing.assert_close(context['window'][:94], images[:94])
        torch.testing.assert_close(context['window'][94:], images[93:94].expand(13, -1, -1, -1))
        self.assertEqual([m['frame'] for m in context['markers']], [3, 93])
        self.assertEqual([m['id'] for m in context['markers']], [1, 2])
        torch.testing.assert_close(edited, torch.cat((first, last)))
        self.assertEqual(context['fps'], 30000/1001)
        self.assertEqual(plate['fps_rational'], '30000/1001')
        self.assertEqual(context['window_start'], 37)
        self.assertEqual(context['geometry']['content_rect'], [0, 0, 96, 64])
        self.assertNotIn('window_key', context, 'Never reuse another source latent by stale cache key')

    def test_invalid_keyframes_are_rejected_instead_of_silently_moved(self):
        images = torch.zeros(9, 64, 96, 3)
        plate = dict(_work_images=images, count=9, start=0, fps=25,
                     processing='SDR (sRGB)', space='srgb_display',
                     framing_mode='Full frame (stretch to working size)')
        guide = ripple.ZuraRippleH3Guide()
        for invalid in ([], [(9, images[:1], 1)], [(3, images[:1], 1), (3, images[:1], 1)],
                        [(0, images[:1], .5)], [(0, images[:1, :32], 1)]):
            with self.assertRaises(ValueError):
                guide.prepare(plate, invalid)
        with self.assertRaisesRegex(ValueError, 'SDR'):
            guide.prepare({**plate, 'space':'hlg_rec2020'}, [(0, images[:1], 1)])

    def test_fullframe_stretches_to_selected_working_size_not_source_grid(self):
        # The original 130x70 source encloses to 192x128 on the old 64px path.
        # A 96x64 working canvas must remain 96x64, without a crop or pad.
        pixels = np.random.default_rng(2).random((70, 130, 3), dtype=np.float32)
        data = dict(kind='sequence', width=130, height=70, count=3, fps=30000/1001,
                    fps_rational='30000/1001', files=['a.png','b.png','c.png'])
        with patch.object(native, 'describe', return_value=data), \
             patch.object(native, 'frames', side_effect=lambda *args: iter([pixels] * 3)), \
             patch.object(native, 'working', side_effect=lambda image, *args: image):
            result = native.ZuraPaintoutFullFrame().prepare(
                'source.mov', 'srgb_display', 0, 3, 25, 128, 768, 0, 0,
                'SDR (sRGB)', 'Full frame (stretch to working size)', 96, 64)
        image, _, plate, width, height, padded, fps, _ = result
        self.assertEqual((width, height, padded), (96, 64, 9))
        self.assertEqual(plate['rect'], [0, 0, 130, 70])
        self.assertEqual(plate['resized'], [64, 96])
        self.assertEqual(plate['fps_rational'], '30000/1001')
        self.assertEqual(fps, 30000/1001)
        torch.testing.assert_close(image[3:], image[2:3].expand(6, -1, -1, -1))

    def test_h3_delivery_discards_held_tail_and_restores_source_raster_and_clock(self):
        originals = [np.full((70, 130, 3), i/20, dtype=np.float32) for i in range(7)]
        data = dict(kind='sequence', width=130, height=70, count=7, fps=30000/1001,
                    fps_rational='30000/1001', files=[str(i) for i in range(7)])
        received = []
        class CaptureDelivery:
            def __init__(self, target, plate, format, preview):
                self.plate = plate
                self.target = target
            def append(self, image):
                received.append(image.clone())
            def finish(self):
                return {}
        fake_media = types.ModuleType(package.__name__ + '.media')
        fake_media.Delivery = CaptureDelivery
        with tempfile.TemporaryDirectory() as folder, \
             patch.dict(sys.modules, {
                 'folder_paths': types.SimpleNamespace(get_output_directory=lambda: folder),
                 fake_media.__name__: fake_media}), \
             patch.object(native, 'describe', return_value=data), \
             patch.object(native, 'frames', side_effect=lambda source, start, count: iter(originals[start:start+count])), \
             patch.object(native, 'working', side_effect=lambda image, *args: image), \
             patch.object(native, 'unworking', side_effect=lambda image, *args: image), \
             patch.object(native, 'to_linear', side_effect=lambda image, *args: image), \
             patch.object(native, 'from_linear', side_effect=lambda image, *args: image):
            _, _, plate, *_ = native.ZuraPaintoutFullFrame().prepare(
                'source.mov', 'srgb_display', 2, 4, 25, 128, 768, 0, 0,
                'SDR (sRGB)', 'Full frame (stretch to working size)', 96, 64)
            context, _, working_count = ripple.ZuraRippleH3Guide().prepare(
                plate, [(3, plate['_work_images'][3:4].clone(), 1)])
            self.assertEqual(working_count, 5)
            saved = native.ZuraPaintoutUncrop().save(context['window'], plate, 'ripple/test',
                                                     'float32', False, 'SDR video', False)
            self.assertTrue(Path(saved['result'][0]).is_dir())
        self.assertEqual(len(received), 4)
        self.assertEqual(tuple(received[0].shape), (70, 130, 3))
        self.assertEqual(plate['fps_rational'], '30000/1001')
        self.assertEqual(plate['start'], 2)
        for offset, image in enumerate(received):
            torch.testing.assert_close(image, torch.full_like(image, (offset+2)/20), atol=1e-6, rtol=0)


if __name__ == '__main__':
    unittest.main()
