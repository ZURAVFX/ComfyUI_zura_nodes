import copy
import importlib
import unittest

import torch
import test_artist_studio as fixtures

module = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_studio')


class StudioOutpaintTests(unittest.TestCase):
    def setUp(self):
        self.source = {'file': 'genj_studio/abc/source.mp4', 'sha': 'a'*64,
                       'duration': 8, 'width': 768, 'height': 432}
        self.options = dict(start=1.0, duration=2.0, mode='expand', width=1152,
                            height=640, left=128, right=128)

    def test_actual_frame_count_and_user_approval_gate(self):
        p = module.plan(self.source, **self.options)
        self.assertEqual((p['frames'], p['padded_frames'], p['duration']), (48, 49, 2.0))
        with self.assertRaisesRegex(ValueError, 'approve'):
            module.build_studio_graph(self.source, p, review_key='no', output_prefix='genj/outpaint/test')
        g = module.build_studio_graph(self.source, p, review_key=p['review_key'], output_prefix='genj/outpaint/test')
        self.assertEqual(g['empty']['inputs']['length'], 49)
        self.assertEqual(g['source_range']['inputs']['duration_seconds'], 2)
        self.assertEqual(g['trim_result']['inputs']['length'], 48)
        self.assertEqual(g['assemble']['inputs']['audio'], ['components', 1])
        self.assertEqual(g['audio_empty']['inputs']['frames_number'], 49)
        self.assertEqual(g['adapter']['inputs']['lora_name'], 'ltx-2.3-22b-ic-lora-outpaint.safetensors')
        self.assertEqual(g['guide']['inputs']['image'], ['canvas', 0])
        self.assertNotIn('blend_high', g, 'The selected black-guide method can redraw the original scene')
        changed = copy.deepcopy(p); changed['left'] += 1
        with self.assertRaisesRegex(ValueError, 'changed'):
            module.build_studio_graph(self.source, changed, review_key=p['review_key'], output_prefix='genj/outpaint/test')

    def test_hold_repeats_last_frame_without_lengthening_output_audio(self):
        video = torch.rand(10, 8, 8, 3)
        audio = {'waveform': torch.ones(1, 2, 20000), 'sample_rate': 48000}
        held, padded_audio, count = module.hold_video_audio(video, audio, 10)
        self.assertEqual((len(held), count), (17, 10))
        self.assertTrue(torch.equal(held[-1], video[-1]))
        self.assertEqual(padded_audio['waveform'].shape[-1], 34000)
        self.assertEqual(audio['waveform'].shape[-1], 20000)
        with self.assertRaisesRegex(ValueError, 'frame count'):
            module.hold_video_audio(video, audio, 9)

    def test_review_shows_actual_mask_and_tracks_source(self):
        p = module.plan(self.source, **self.options)
        graph = module.build_review_graph(self.source, p, output_prefix='genj/outpaint/review')
        self.assertEqual(graph['canvas']['inputs']['images'], ['components', 0])
        self.assertEqual(graph['overlay']['inputs']['mask'], ['canvas', 1])
        image = torch.zeros((1, 2, 2, 3))
        mask = torch.tensor([[[0., 1.], [1., 0.]]])
        shown = module.ZuraOutpaintReviewOverlay().make(image, mask)[0]
        self.assertTrue(torch.equal(shown[0, 0, 0], image[0, 0, 0]))
        self.assertGreater(shown[0, 0, 1, 0], 0)
        changed = dict(p, width=1024)
        with self.assertRaisesRegex(ValueError, 'changed'):
            module.build_review_graph(self.source, changed, output_prefix='genj/outpaint/review')

    def test_selection_bounds_and_black_source_dimensions(self):
        for extra in ({'duration': 6}, {'start': 7}, {'width': 1001}, {'mode': 'black'}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                module.plan(self.source, **{**self.options, **extra})
        black = module.plan(self.source, **{**self.options, 'mode': 'black', 'width': 768,
                                            'height': 432, 'left': 0, 'right': 0})
        self.assertEqual(black['mode'], 'black')
        self.assertEqual((black['padded_width'], black['padded_height']), (768, 448))
        g = module.build_studio_graph(self.source, black, review_key=black['review_key'], output_prefix='genj/outpaint/black')
        self.assertEqual(g['unpad_result']['inputs']['height'], 432)
        image = torch.ones((1, 130, 130, 3)); image[:, :, :10] = 0
        canvas = importlib.import_module('ComfyUI_zura_nodes.artist_studio.ltx_outpaint')
        padded, mask = canvas.prepare_canvas(image, 'black', 192, 192)
        self.assertEqual(padded.shape, (1, 192, 192, 3))
        self.assertTrue(torch.equal(padded[:, :130, :130], image))
        self.assertTrue(bool(mask[:, 130:, :].all()))


if __name__ == '__main__':
    unittest.main()
