import copy
import importlib
import unittest

import torch
import test_artist_studio as fixtures

module = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_studio')


class StudioOutpaintTests(unittest.TestCase):
    def test_enlarged_geometry_is_reviewed_and_forwarded_to_the_canvas(self):
        selection = module.plan(self.source, **{**self.options, 'left': -256, 'right': -256})
        graph = module.build_review_graph(self.source, selection, output_prefix='genj/outpaint/zoom')
        self.assertEqual(graph['canvas']['inputs']['left'], -256)
        self.assertEqual(graph['canvas']['inputs']['right'], -256)
        self.assertNotEqual(selection['review_key'], module.plan(self.source, **self.options)['review_key'])
        with self.assertRaises(ValueError):
            module.plan(self.source, **{**self.options, 'left': -32769})

    def setUp(self):
        self.source = {'file': 'genj_studio/abc/source.mp4', 'sha': 'a'*64,
                       'duration': 8, 'width': 768, 'height': 432}
        self.options = dict(start=1.0, duration=2.0, mode='expand', width=1152,
                            height=640, left=128, right=128)

    def test_original_cadence_and_approved_sampling_are_bound_to_review(self):
        source = dict(self.source, fps_num=30, fps_den=1, has_audio=True)
        selection = module.plan(source, **self.options)
        graph = module.build_studio_graph(source, selection, review_key=selection['review_key'], output_prefix='genj/outpaint/rate')
        self.assertEqual((selection['frames'], selection['fps_num'], selection['fps_den']), (60, 30, 1))
        self.assertEqual(graph['source_range']['class_type'], 'ZuraOutpaintSelectClip')
        self.assertEqual(graph['source_range']['inputs']['expected_frames'], 60)
        self.assertEqual(graph['temporal_hold']['inputs']['fps'], 30)
        self.assertEqual(graph['assemble']['class_type'], 'ZuraOutpaintExactVideo')
        self.assertEqual((graph['assemble']['inputs']['fps_num'], graph['assemble']['inputs']['fps_den']), (30, 1))
        self.assertEqual(graph['empty']['inputs']['width'], selection['padded_width'])
        self.assertEqual(graph['guide']['inputs']['image'], ['canvas', 0])
        self.assertEqual(graph['adapter']['inputs']['lora_name'], 'ltx-2.3-22b-ic-lora-outpaint.safetensors')
        self.assertEqual(graph['adapter']['inputs']['strength_model'], 1)
        self.assertEqual(graph['sampler']['inputs']['sampler_name'], 'euler_ancestral_cfg_pp')
        self.assertEqual(graph['guider']['inputs']['cfg'], 1)
        self.assertEqual(graph['sigmas']['inputs']['sigmas'], '1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0')
        self.assertNotIn('sample_high', graph)
        changed = dict(source, fps_num=24)
        with self.assertRaisesRegex(ValueError, 'changed'):
            module.build_studio_graph(changed, selection, review_key=selection['review_key'], output_prefix='genj/outpaint/rate')
        silent = dict(source, has_audio=False)
        silent_graph = module.build_studio_graph(silent, selection, review_key=selection['review_key'], output_prefix='genj/outpaint/silent', pad_delivery=True)
        self.assertNotIn('audio', silent_graph['assemble']['inputs'])

    def test_fractional_fps_is_not_rounded_in_video_container(self):
        from fractions import Fraction
        import sys
        import types
        from unittest.mock import patch
        exact = Fraction(30000, 1001)
        output = types.SimpleNamespace(VideoFromComponents=lambda components, **kwargs: components)
        api = types.ModuleType('comfy_api.latest')
        api.InputImpl = output
        api.Types = types.SimpleNamespace(VideoComponents=lambda **kwargs: kwargs)
        with patch.dict(sys.modules, {'comfy_api.latest': api}):
            video = module.ZuraOutpaintExactVideo().make(torch.zeros(1, 2, 2, 3), 30000, 1001)[0]
        self.assertEqual(video['frame_rate'], exact)

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
        padded = module.build_studio_graph(self.source, p, review_key=p['review_key'], output_prefix='genj/outpaint/padded', pad_delivery=True)
        self.assertEqual(padded['hold_delivery']['inputs'], {'images': ['trim_result', 0], 'stride': 8})
        self.assertEqual(padded['assemble']['inputs']['audio'], ['temporal_hold', 1])
        self.assertEqual(padded['assemble']['inputs']['images'], ['hold_delivery', 0])
        self.assertEqual(g['audio_empty']['inputs']['frames_number'], 49)
        self.assertEqual(g['adapter']['inputs']['lora_name'], 'ltx-2.3-22b-ic-lora-outpaint.safetensors')
        self.assertEqual(g['guide']['inputs']['image'], ['canvas', 0])
        self.assertNotIn('blend_high', g, 'The selected black-guide method can redraw the original scene')
        changed = copy.deepcopy(p); changed['left'] += 1
        with self.assertRaisesRegex(ValueError, 'changed'):
            module.build_studio_graph(self.source, changed, review_key=p['review_key'], output_prefix='genj/outpaint/test')

    def test_fractional_source_end_rounds_up_and_decoder_holds_tail(self):
        source = dict(self.source, duration=53 / 25)
        options = {**self.options, 'start': 0., 'duration': source['duration']}
        selected = module.plan(source, **options)
        self.assertEqual(selected['frames'], 51)
        rounded = module.plan(source, **{**options, 'duration': selected['duration']}, allow_partial_end=True)
        self.assertNotEqual(selected['review_key'], rounded['review_key'])
        with self.assertRaisesRegex(ValueError, 'past the source'):
            module.plan(source, **{**options, 'duration': source['duration'] + .02})
        graph = module.build_studio_graph(source, selected, review_key=selected['review_key'], output_prefix='genj/outpaint/fractional')
        self.assertEqual(graph['source_range']['inputs']['expected_frames'], selected['frames'])
        self.assertAlmostEqual(graph['source_range']['inputs']['duration_seconds'], 53/25)
        self.assertEqual(graph['temporal_hold']['inputs']['expected_frames'], 51)
        review = module.build_review_graph(source, selected, output_prefix='genj/outpaint/fractional_review')
        self.assertAlmostEqual(review['source_range']['inputs']['duration_seconds'], 53/25)
        black = module.plan(source, start=0., duration=53/25, mode='black', width=768, height=432)
        black_graph = module.build_studio_graph(source, black, review_key=black['review_key'], output_prefix='genj/outpaint/fractional_black')
        self.assertAlmostEqual(black_graph['source_range']['inputs']['duration_seconds'], 53/25)

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
        odd_source = dict(self.source, width=767)
        with self.assertRaisesRegex(ValueError, 'even dimensions'):
            module.plan(odd_source, **{**self.options, 'mode': 'black', 'width': 767,
                                      'height': 432, 'left': 0, 'right': 0})
        self.assertEqual(black['mode'], 'black')
        self.assertEqual((black['padded_width'], black['padded_height']), (768, 448))
        g = module.build_studio_graph(self.source, black, review_key=black['review_key'], output_prefix='genj/outpaint/black')
        self.assertEqual(g['unpad_result']['inputs']['height'], 432)
        self.assertEqual(g['guide']['inputs']['image'], ['canvas', 0])
        self.assertEqual(g['adapter']['inputs']['lora_name'], 'ltx-2.3-22b-ic-lora-outpaint.safetensors')
        self.assertEqual(g['canvas']['inputs']['images'], ['temporal_hold', 0])
        self.assertEqual(g['trim_result']['inputs']['length'], 48)
        self.assertEqual(g['assemble']['inputs']['audio'], ['components', 1])
        image = torch.ones((1, 130, 130, 3)); image[:, :, :10] = 0
        canvas = importlib.import_module('ComfyUI_zura_nodes.artist_studio.ltx_outpaint')
        padded, mask = canvas.prepare_canvas(image, 'black', 192, 192)
        self.assertEqual(padded.shape, (1, 192, 192, 3))
        self.assertTrue(torch.equal(padded[:, :130, :130], image))
        self.assertTrue(bool(mask[:, 130:, :].all()))

    def test_minimum_duration_matches_clip_loader(self):
        with self.assertRaisesRegex(ValueError, '3 frames'):
            module.plan(self.source, **{**self.options, 'duration': 2 / 24})
        selection = module.plan(self.source, **{**self.options, 'duration': 3 / 24})
        graph = module.build_review_graph(self.source, selection, output_prefix='genj/outpaint/minimum')
        self.assertGreaterEqual(graph['source_range']['inputs']['duration_seconds'], .1)


if __name__ == '__main__':
    unittest.main()
