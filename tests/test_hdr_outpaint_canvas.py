"""CPU checks for experimental HDR canvas preparation, without inference."""
import importlib
import sys
import types
import unittest

import torch
import v2_bootstrap

for name, folder in [('ComfyUI_zura_nodes.artist_studio', 'artist_studio'),
                     ('ComfyUI_zura_nodes.paintout', 'paintout')]:
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(v2_bootstrap.ROOT / folder)]
        sys.modules[name] = package

canvas = importlib.import_module('ComfyUI_zura_nodes.artist_studio.ltx_outpaint')
colour = importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')
experiment = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_experiment')
outpaint = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_studio')
native = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_native_source')


class HDRCanvasTests(unittest.TestCase):
    def test_reviewed_sdr_first_keeps_selection_and_holds_tail(self):
        source = {'sha': 'a' * 64, 'file': 'source.mp4', 'duration': 4, 'width': 128, 'height': 128, 'asset_kind': 'video'}
        selection = outpaint.plan(source, start=.517, duration=.5, mode='expand', width=192, height=192,
                                  left=32, top=32, right=32, bottom=32)
        key = experiment.hdr_review_key(selection, 'pq_rec2020')
        kwargs = dict(review_key=key, colour_space='pq_rec2020')
        stage = experiment.build_reviewed_sdr_first_stage(source, selection, **kwargs)
        final = experiment.build_reviewed_sdr_first_composite(source, selection, 'intermediate.mp4', **kwargs, has_audio=True)
        self.assertEqual(stage['hdr_source']['inputs']['start_seconds'], .517)
        self.assertEqual(stage['hdr_source']['inputs']['frame_count'], 12)
        self.assertEqual(stage['tone_map_source']['inputs']['image'], ['hdr_input_hold', 0])
        self.assertEqual(final['native_original']['inputs']['frame_count'], 12)
        self.assertEqual(final['native_original']['inputs']['start_seconds'], .517)
        self.assertEqual(final['hdr_original_length']['inputs']['length'], 12)
        self.assertEqual(final['hdr_delivery_hold']['inputs']['stride'], 8)
        self.assertEqual(final['original_audio']['inputs']['start_seconds'], .517)
        self.assertEqual(final['hdr_audio_hold']['inputs']['frames'], ['hdr_delivery_hold', 1])
        self.assertEqual(final['zura_hdr_hlg']['inputs']['image'], ['hdr_delivery_hold', 0])
        self.assertEqual(final['zura_hdr_archive']['inputs']['images'], ['hdr_delivery_hold', 0])
        for graph in (stage, final):
            for node in graph.values():
                for value in node['inputs'].values():
                    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                        self.assertIn(value[0], graph, f'Dangling connection {value}')
        with self.assertRaisesRegex(ValueError, 'approve'):
            experiment.build_reviewed_sdr_first_stage(source, selection, review_key='wrong', colour_space='pq_rec2020')
        with self.assertRaisesRegex(ValueError, 'Review the selection again'):
            experiment.build_reviewed_sdr_first_stage(source, {**selection, 'left': 31}, **kwargs)
        large_source = {**source, 'width': 3840, 'height': 2160}
        large_selection = outpaint.plan(large_source, start=.517, duration=.5, mode='expand', width=192, height=192,
                                        left=32, top=32, right=32, bottom=32)
        large_key = experiment.hdr_review_key(large_selection, 'pq_rec2020')
        with self.assertRaisesRegex(ValueError, 'source selection exceeds'):
            experiment.build_reviewed_sdr_first_stage(large_source, large_selection, review_key=large_key, colour_space='pq_rec2020')

    def test_reviewed_hdr_graph_uses_exact_timeline_and_unpads_delivery(self):
        source = {'sha':'a'*64, 'file':'fixture.mov', 'duration':4, 'width':190, 'height':130}
        selection = outpaint.plan(source, start=.5, duration=1, mode='black', width=190, height=130)
        review, review_key = experiment.build_hdr_review_experiment(source, selection)
        for audio in (False, True):
            graph = experiment.build_reviewed_hdr_experiment(source, selection, review_key=review_key, has_audio=audio)
            self.assertEqual(review['hdr_source'], graph['hdr_source'])
            self.assertEqual({k:v for k,v in review['canvas']['inputs'].items() if k != 'images'},
                             {k:v for k,v in graph['canvas']['inputs'].items() if k != 'images'})
            self.assertEqual(review['overlay']['inputs']['mask'], ['canvas', 1])
            self.assertEqual(graph['hdr_source']['inputs']['start_seconds'], .5)
            self.assertEqual(graph['hdr_source']['inputs']['frame_count'], 24)
            self.assertEqual(graph['hdr_trim']['inputs']['length'], 24)
            self.assertEqual(graph['hdr_unpad']['inputs']['width'], 190)
            self.assertEqual(graph['hdr_preview']['inputs']['image'], ['hdr_unpad', 0])
            self.assertEqual(graph['hdr_experiment_exr']['inputs']['images'], ['hdr_unpad', 0])
            self.assertEqual(graph['hdr_experiment_hlg']['inputs']['image'], ['hdr_unpad', 0])
            if audio:
                self.assertEqual(graph['hdr_audio']['inputs']['start_seconds'], .5)
                self.assertEqual(graph['audio_encoded']['inputs']['audio'], ['hdr_audio_hold', 1])
                self.assertEqual(graph['hdr_preview_video']['inputs']['audio'], ['hdr_audio', 0])
            for item in graph.values():
                for value in item['inputs'].values():
                    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                        self.assertIn(value[0], graph, f'Dangling graph connection {value}')
        changed = dict(selection, start=1.)
        with self.assertRaisesRegex(ValueError, 'Review the selection again'):
            experiment.build_reviewed_hdr_experiment(source, changed, review_key=review_key)
        with self.assertRaisesRegex(ValueError, 'approve'):
            experiment.build_reviewed_hdr_experiment(source, selection, review_key='bad')
        with self.assertRaisesRegex(ValueError, 'approve'):
            experiment.build_reviewed_hdr_experiment(source, selection, review_key=review_key, colour_space='pq_rec2020')
        large_source = dict(source, width=1280, height=720, duration=6)
        large = outpaint.plan(large_source, start=0, duration=5, mode='black', width=1280, height=720)
        with self.assertRaisesRegex(ValueError, 'memory budget'):
            experiment.build_hdr_review_experiment(large_source, large)

    def test_sdr_first_hdr_candidate_uses_original_native_centre(self):
        params = dict(start_frame=0, frame_count=25, width=448, height=704,
                      left=44, right=44, top=32, bottom=32, colour_space='pq_rec2020')
        stage = experiment.build_sdr_first_stage('/native-pq.mp4', **params)
        self.assertEqual(stage['tone_map_source']['inputs']['image'], ['hdr_source', 0])
        self.assertEqual(stage['canvas']['class_type'], 'ZuraLTXOutpaintCanvas')
        self.assertEqual(stage['canvas']['inputs']['images'], ['tone_map_source', 0])
        self.assertEqual(stage['stage_video']['inputs']['images'], ['trim_result', 0])
        self.assertNotIn('hdr_vae', stage)
        graph = experiment.build_sdr_first_hdr_composite('/native-pq.mp4', '/intermediate.mp4', **params)
        self.assertEqual(graph['native_canvas']['inputs']['images'], ['native_original', 0])
        self.assertEqual(graph['final_hdr_composite']['inputs']['generated'], ['hdr_unpad_raster', 0])
        self.assertEqual(graph['final_hdr_composite']['inputs']['source'], ['native_canvas', 0])
        self.assertEqual(graph['final_hdr_composite']['inputs']['mask'], ['native_canvas', 1])
        self.assertEqual(graph['final_hdr_composite']['inputs']['colour_match'], 1.0)
        self.assertEqual(graph['zura_hdr_hlg']['inputs']['image'], ['final_hdr_composite', 0])
        self.assertEqual(graph['zura_hdr_archive']['inputs']['images'], ['final_hdr_composite', 0])
        timed = experiment.build_sdr_first_hdr_composite('/native-pq.mp4', '/intermediate.mp4',
            **{**params, 'start_frame': 15}, source_fps=30., has_audio=True)
        self.assertEqual(timed['native_original']['inputs']['start_seconds'], .5)
        self.assertEqual(timed['native_original']['inputs']['output_fps'], 24.)
        self.assertEqual(timed['original_audio']['inputs']['start_seconds'], .5)
        precise = {**params, 'start_frame': 15, 'source_fps': 30., 'start_seconds': .517}
        precise_stage = experiment.build_sdr_first_stage('/native-pq.mp4', **precise)
        precise_composite = experiment.build_sdr_first_hdr_composite('/native-pq.mp4', '/intermediate.mp4', **precise, has_audio=True)
        self.assertEqual(precise_stage['hdr_source']['inputs']['start_seconds'], .517)
        self.assertEqual(precise_composite['native_original']['inputs']['start_seconds'], .517)
        self.assertEqual(precise_composite['original_audio']['inputs']['start_seconds'], .517)
        for invalid in (-1, float('nan'), True):
            with self.assertRaisesRegex(ValueError, 'start time'):
                experiment.build_sdr_first_stage('/native-pq.mp4', **{**params, 'start_seconds': invalid})
        self.assertEqual(timed['zura_hdr_video']['inputs']['audio'], ['original_audio', 0])
        self.assertEqual(timed['zura_hdr_preview_video']['inputs']['audio'], ['original_audio', 0])
        self.assertFalse(any(node['class_type'].startswith('H3') for node in graph.values()))
        with self.assertRaisesRegex(ValueError, 'HDR video colour'):
            experiment.build_sdr_first_hdr_composite('/native-pq.mp4', '/intermediate.mp4', **{**params, 'colour_space':'acescg'})

    def test_hdr_hold_is_removed_from_delivered_length(self):
        images = torch.arange(24, dtype=torch.float32).reshape(24, 1, 1, 1).expand(-1, 2, 2, 3)
        padded, = native.ZuraHDRTemporalHold().hold(images)
        self.assertEqual(len(padded), 25)
        torch.testing.assert_close(padded[:24], images)
        torch.testing.assert_close(padded[-1], images[-1])

    def test_exr_review_binds_manifest_colour_and_sequence_rate(self):
        source = {'sha':'a'*64, 'file':'genj_studio/take/hdr_sequence.json', 'asset_kind':'hdr_sequence',
                  'duration':4, 'width':190, 'height':130}
        selection = outpaint.plan(source, start=.5, duration=1, mode='black', width=190, height=130)
        validate = lambda _: '/input/genj_studio/take/hdr_sequence.json'
        review, key = experiment.build_hdr_review_experiment(source, selection, colour_space='acescg',
                                                             sequence_fps=30, check_asset=validate)
        graph = experiment.build_reviewed_hdr_experiment(source, selection, review_key=key,
                                                         colour_space='acescg', sequence_fps=30,
                                                         check_asset=validate)
        self.assertEqual(review['hdr_source'], graph['hdr_source'])
        self.assertEqual(graph['hdr_source']['inputs']['manifest'], validate(source))
        self.assertEqual(graph['hdr_source']['inputs']['manifest_sha'], source['sha'])
        self.assertEqual(graph['hdr_source']['inputs']['sequence_fps'], 30)
        self.assertNotIn('hdr_audio', graph)
        with self.assertRaisesRegex(ValueError, 'approve'):
            experiment.build_reviewed_hdr_experiment(source, selection, review_key=key,
                                                      colour_space='acescg', sequence_fps=24, check_asset=validate)
        with self.assertRaisesRegex(ValueError, 'embedded audio'):
            experiment.build_reviewed_hdr_experiment(source, selection, review_key=key, has_audio=True,
                                                      colour_space='acescg', sequence_fps=30, check_asset=validate)
        with self.assertRaisesRegex(ValueError, 'colour space'):
            experiment.build_hdr_review_experiment(source, selection, colour_space='pq_rec2020', check_asset=validate)

    def test_black_guide_experiment_reuses_approved_unmasked_recipe(self):
        graph = experiment.build_black_guide_experiment('/source.mov', start_frame=7,
            frame_count=9, width=192, height=128, left=48, top=32, right=48, bottom=32)
        self.assertEqual(graph['adapter']['inputs']['lora_name'], 'ltx-2.3-22b-ic-lora-outpaint.safetensors')
        self.assertEqual(graph['guide']['class_type'], 'LTXAddVideoICLoRAGuide')
        self.assertNotIn('attention_mask', graph['guide']['inputs'])
        self.assertEqual(graph['canvas']['class_type'], 'ZuraLTXOutpaintHDRCanvas')
        self.assertEqual(graph['canvas']['inputs']['images'], ['hdr_source', 0])
        self.assertEqual(graph['hdr_source']['inputs']['start_frame'], 7)
        self.assertEqual(graph['hdr_experiment_exr']['inputs']['images'], ['trim_result', 0])
        for node in graph.values():
            for value in node['inputs'].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    self.assertIn(value[0], graph, f'Dangling graph connection {value}')
        with self.assertRaises(ValueError):
            experiment.build_black_guide_experiment('/source.mov', start_frame=0, frame_count=10, width=192, height=128)

    def test_candidate_graph_uses_hdr_guide_and_only_sdr_preview(self):
        for audio in (False, True):
            graph = experiment.build_experimental_graph('/source.mov', start_frame=7, frame_count=9,
                fps=24, width=128, height=128, mode='expand', left=32, right=32,
                has_audio=audio, prefix='genj/hdr_outpaint/test')
            self.assertEqual(graph['hdr_source']['inputs']['start_frame'], 7)
            self.assertEqual(graph['conditioning']['inputs']['frame_rate'], ['hdr_source', 1])
            self.assertEqual(graph['hdr_preview_save']['inputs']['fps'], ['hdr_source', 1])
            self.assertEqual(graph['canvas']['class_type'], 'ZuraLTXOutpaintHDRCanvas')
            self.assertEqual(graph['video_vae']['inputs']['vae_name'], 'ltx-2.5-video-vae-bf16.safetensors')
            self.assertEqual(graph['canvas']['inputs']['images'], ['hdr_source', 0])
            self.assertEqual(graph['guide']['inputs']['vae'], ['hdr_vae', 0])
            self.assertEqual(graph['hdr_preview']['inputs']['image'], ['hdr_composite', 0])
            self.assertEqual(graph['hdr_composite']['inputs']['source'], ['canvas', 0])
            self.assertIn('sdr_preview', graph['hdr_preview_save']['inputs']['filename_prefix'])
            self.assertEqual(graph['audio_encoded']['class_type'], 'VAEEncodeAudio' if audio else 'LTXVEmptyLatentAudio')
            self.assertEqual(graph['hdr_audio']['inputs']['fps'] if audio else graph['audio_encoded']['inputs']['frame_rate'], ['hdr_source', 1])
            for node in graph.values():
                for value in node['inputs'].values():
                    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                        self.assertIn(value[0], graph, f'Dangling graph connection {value}')
            self.assertFalse(any(n['class_type'] == 'ZuraHDRPackageACEScct' for n in graph.values()))
        with self.assertRaises(ValueError):
            experiment.build_experimental_graph('/source.mov', start_frame=0, frame_count=10,
                fps=24, width=128, height=128, mode='black')
        candidate = experiment.build_experimental_graph('/source.mov', start_frame=0, frame_count=9,
            fps=24, width=128, height=128, mode='black', unverified_exr=True, unverified_hlg=True,
            has_audio=True)
        self.assertEqual(candidate['hdr_experiment_exr']['inputs']['images'], ['hdr_composite', 0])
        self.assertTrue(candidate['hdr_experiment_exr']['inputs']['prefix'].startswith('unverified_outpaint_'))
        self.assertEqual(candidate['hdr_experiment_hlg']['inputs'], {'image':['hdr_composite',0],
                         'source':'HDR ACEScct','destination':'HDR'})
        self.assertEqual(candidate['hdr_experiment_video']['inputs']['bit_depth'], 10)
        self.assertEqual(candidate['hdr_experiment_video']['inputs']['audio'], ['hdr_audio',0])
        self.assertEqual(candidate['hdr_experiment_save']['inputs']['fps'], ['hdr_source',1])
        self.assertIn('unverified', candidate['hdr_experiment_save']['inputs']['filename_prefix'])
        for node in candidate.values():
            for value in node['inputs'].values():
                if isinstance(value,list) and len(value)==2 and isinstance(value[0],str):
                    self.assertIn(value[0],candidate)
        with self.assertRaises(ValueError):
            experiment.build_experimental_graph('/source.mov', start_frame=0, frame_count=9,
                fps=24, width=128, height=128, mode='black', unverified_hlg='true')

    def test_black_mask_uses_linear_black_not_acescct_code_zero(self):
        linear = torch.full((1, 64, 64, 3), 2.0)
        linear[:, :8] = 0
        result, mask = canvas.prepare_hdr_canvas(colour.encode_ct(linear), 'black', 64, 64)
        self.assertEqual(int(mask.sum()), 8 * 64)
        torch.testing.assert_close(colour.decode_ct(result), linear, atol=1e-5, rtol=1e-5)

    def test_hdr_composite_preserves_source_and_feathers_in_linear_light(self):
        source = colour.encode_ct(torch.full((1, 64, 64, 3), 2.0))
        generated = colour.encode_ct(torch.full_like(source, 8.0))
        mask = torch.zeros((1, 64, 64)); mask[:, :, 32:] = 1
        result = canvas.composite_hdr_outpaint(generated, source, mask, 4)
        self.assertTrue(torch.equal(result[:, :, :28], source[:, :, :28]))
        self.assertTrue(torch.equal(result[:, :, 36:], generated[:, :, 36:]))
        seam = colour.decode_ct(result[0, 32, 31, 0])
        self.assertAlmostEqual(seam.item(), 8.0, places=4)
        boundary_jump = torch.abs(colour.decode_ct(result[0, 32, 32, 0]) - seam)
        self.assertLess(boundary_jump.item(), 1e-5, 'The inner edge must meet the generated side without a jump')
        self.assertTrue(torch.equal(result[:, :, 32:], generated[:, :, 32:]),
                        'The generated area must not mix with black source padding')
        with self.assertRaises(ValueError):
            canvas.composite_hdr_outpaint(generated, source, mask[:, :-1], 4)

    def test_hdr_composite_has_no_jump_on_any_edge_or_corner(self):
        source = colour.encode_ct(torch.full((1, 64, 64, 3), 2.0))
        generated = colour.encode_ct(torch.full_like(source, 8.0))
        mask = torch.ones((1, 64, 64)); mask[:, 16:48, 16:48] = 0
        result = colour.decode_ct(canvas.composite_hdr_outpaint(generated, source, mask, 4))[0, :, :, 0]
        for source_pixel, outside_pixel in [((16, 32), (15, 32)), ((47, 32), (48, 32)),
                                            ((32, 16), (32, 15)), ((32, 47), (32, 48)),
                                            ((16, 16), (15, 15)), ((47, 47), (48, 48))]:
            self.assertLess(abs(float(result[source_pixel] - result[outside_pixel])), 1e-5)
        self.assertTrue(torch.equal(result[20:44, 20:44], colour.decode_ct(source)[0, 20:44, 20:44, 0]))

    def test_expand_uses_encoded_scene_black_and_retains_hdr_highlights(self):
        linear = torch.full((1, 32, 64, 3), 4.0)
        result, mask = canvas.prepare_hdr_canvas(colour.encode_ct(linear), 'expand', 128, 128, 32, 16, 32, 16)
        restored = colour.decode_ct(result)
        self.assertTrue(torch.allclose(restored[:, :48], torch.zeros_like(restored[:, :48]), atol=1e-6))
        torch.testing.assert_close(restored[:, 48:80, 32:96], linear, atol=1e-5, rtol=1e-5)
        self.assertEqual(int((mask == 0).sum()), 32 * 64)


if __name__ == '__main__':
    unittest.main()
