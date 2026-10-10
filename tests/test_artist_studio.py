"""Shared-engine contract checks; no GPU, network or paid submissions."""
import copy
import importlib
import json
import sys
import tempfile
import types
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import v2_bootstrap
import torch

NAME = 'ComfyUI_zura_nodes.artist_studio'
package = types.ModuleType(NAME)
package.__path__ = [str(v2_bootstrap.ROOT / 'artist_studio')]
sys.modules[NAME] = package
studio = importlib.import_module(NAME + '.studio')
wan = importlib.import_module(NAME + '.wan')
h3 = importlib.import_module(NAME + '.h3')
adapters = importlib.import_module('ComfyUI_zura_nodes.wan_artist')


class SharedEngineTests(unittest.TestCase):
    def project(self):
        config = studio.clean_config({'engine': 'wan', 'duration': 3, 'resolution': 1280})
        return {'id': 'a' * 32, 'source': {'sha': 'source', 'file': 'source.mp4'}, 'character': {'sha': 'character', 'file': 'character.png'},
            'config': config, 'review': 'shot_' + 'a' * 16, 'opening_key': 'look', 'opening_approval': 'look',
            'opening_input': {'sha': 'look', 'file': 'opening.png'}, 'phase': 'opening', 'actions': []}

    def test_engine_and_output_changes_preserve_review_and_look(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = studio.Store(tmp)
            controller = studio.Studio.__new__(studio.Studio)
            controller.store = store
            controller.collect = lambda p: p
            p = self.project()
            p['approval'] = studio.prep_key(p)
            p['prepared_key'] = p['approval']
            before = (p['review'], p['approval'], copy.deepcopy(p['opening_input']))
            for engine in ('local', 'h3', 'wan', 'seedance', 'wan'):
                controller.configure(p, {**p['config'], 'engine': engine, 'resolution': 1920})
                self.assertEqual((p['review'], p['approval'], p['opening_input']), before)
            controller.configure(p, {**p['config'], 'duration': 2})
            self.assertIsNone(p['review'], 'Changing the selected interval requires a new review')

    def test_old_resolution_migrates(self):
        self.assertEqual(studio.clean_config({'render_size': 1920})['resolution'], 1920)
        self.assertEqual(studio.clean_config({'size': 768})['resolution'], 768)
        self.assertEqual(studio.clean_config({'size': 512, 'resolution': 1280})['size'], 512)

    def test_new_optional_defaults_do_not_reset_finished_legacy_shot(self):
        p = self.project()
        p['phase'] = 'done'
        for key in ('audio_id', 'audio_start', 'length_mode'):
            p['config'].pop(key)
        with tempfile.TemporaryDirectory() as tmp:
            controller = studio.Studio.__new__(studio.Studio)
            controller.store = studio.Store(tmp)
            controller.collect = lambda p: p
            controller.configure(p, dict(p['config']))
        self.assertEqual(p['phase'], 'done')

    def test_h3_uses_selected_resolution_and_full_interval(self):
        p = self.project()
        p['config'] = studio.clean_config({**p['config'], 'engine': 'h3', 'quality': 'detailed'})
        package.verify_review = lambda value: (None, {'clip': {'frames': 72}})
        with patch.object(studio, 'assert_approved'), patch.object(studio, 'check_asset'), \
                patch.object(h3, 'cache_key', return_value='b' * 64), tempfile.TemporaryDirectory() as tmp, \
                patch.object(h3, 'cache_path', return_value=Path(tmp) / 'missing.pt'):
            graph = h3.build_h3_graph(p)
            self.assertEqual(graph['h3_shot']['inputs']['render_long_edge'], 1280)
            self.assertEqual(graph['h3_shot']['inputs']['preview_seconds'], 0)
            self.assertEqual(graph['h3_schedule']['inputs']['steps'], 40)

    def test_wan_native_preparation_and_model_stack(self):
        p = self.project()
        with patch.object(studio, 'assert_approved'), patch.object(studio, 'check_asset'), \
                patch.object(wan, 'cache_key', return_value='a' * 64), tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cache.pt'
            with patch.object(wan, 'cache_path', return_value=path):
                graph = wan.build_wan_graph(p)
                self.assertIn('wan_save', graph)
                self.assertFalse(any(n['class_type'] == 'UNETLoader' for n in graph.values()))
                self.assertEqual(graph['wan_shot']['inputs']['render_long_edge'], 1280)
                self.assertEqual(graph['wan_shot']['inputs']['preview_seconds'], 0)
                self.assertEqual(graph['wan_save']['inputs']['pose'], ['wan_pose_draw', 0])
                self.assertEqual(graph['wan_save']['inputs']['mask'], ['wan_block_mask', 0])
                self.assertEqual(graph['wan_character_crop']['inputs']['mask'], ['wan_character_mask_size', 0])
                self.assertEqual(graph['wan_character_mask_size']['inputs']['resize_type.match'], ['wan_character', 0])
                path.touch()
                fast = wan.build_wan_graph(p)
                p['config']['quality'] = 'detailed'
                detailed = wan.build_wan_graph(p)
                self.assertEqual(fast['wan_render']['inputs']['steps'], 6)
                self.assertEqual(detailed['wan_render']['inputs']['steps'], 40)
                self.assertIn('wan_turbo', fast)
                self.assertNotIn('wan_turbo', detailed)
                self.assertEqual(fast['wan_shift']['inputs']['shift'], 8)
                self.assertEqual(fast['wan_render']['inputs']['reference_image'], ['wan_opening_size', 0])
                self.assertEqual(fast['wan_opening_size']['inputs']['crop'], 'disabled')
                self.assertEqual(fast['wan_render']['inputs']['vision_reference'], ['wan_cached', 1])
                self.assertEqual(fast['wan_render']['inputs']['chunk_frames'], 81)
                self.assertEqual(fast['wan_render']['inputs']['join_mode'], 'Native continuation')

    def test_ltx_speech_reaches_both_sampling_passes(self):
        p = self.project()
        p['config']['engine'] = 'local'
        package.text_cache_path = lambda key: Path('/nonexistent-zura-cache')
        with patch.object(studio, 'assert_approved'), patch.object(studio, 'check_asset'), \
                patch.object(studio, 'text_cache_info', return_value=('cache', {})):
            for stage, guiders, refs, concats in (
                    ('background', ('5410:4828', '5414:5209'), ('5409:5114', '5410:5013'), ('5409:5391', '5413:5396')),
                    ('restyle', ('5516:4828', '5517:4964'), ('9002:5012', '5549'), ('9002:4528', '5517:4969'))):
                graph = studio.build_graph(p, stage)
                self.assertEqual(graph['zura_av_coupling']['class_type'], 'LTXVModalityGuidance')
                self.assertEqual(graph['zura_fixed_audio_mask']['inputs']['value'], 0.0)
                self.assertFalse(any(node['class_type'] == 'LTXVSetAudioRefTokens' for node in graph.values()))
                for index, (guider, ref, concat) in enumerate(zip(guiders, refs, concats)):
                    self.assertEqual(graph[guider]['inputs']['positive'], [ref, 0])
                    self.assertEqual(graph[guider]['inputs']['negative'], [ref, 1])
                    self.assertEqual(graph[guider]['inputs']['model'], ['zura_av_coupling', 0])
                    frozen = 'zura_frozen_audio_' + str(index)
                    self.assertEqual(graph[concat]['inputs']['audio_latent'], [frozen, 0])
                    self.assertEqual(graph[frozen]['class_type'], 'SetLatentNoiseMask')
                    self.assertEqual(graph[frozen]['inputs']['mask'], ['zura_fixed_audio_mask', 0])
                first_audio = ['5409:5389', 0] if stage == 'background' else ['9002:3980', 0]
                self.assertEqual(graph['zura_frozen_audio_0']['inputs']['samples'], first_audio)
                if stage == 'restyle':
                    self.assertEqual(graph['9002:3980']['class_type'], 'VAEEncodeAudio')
                    self.assertEqual(graph['9002:3980']['inputs']['audio'], ['9006', 1])
                else:
                    for identity in ('5408:5379', '5408:5382'):
                        self.assertEqual(graph[identity]['class_type'], 'ThresholdMask')
                        self.assertEqual(graph[identity + '_grow']['class_type'], 'MaskFix+')
                        self.assertEqual(graph[identity + '_grow']['inputs']['blur'], 0)
                        self.assertEqual(graph[identity + '_kernel']['inputs']['expression'], '2*a+1')

    def test_fast_rectangular_mask_growth_matches_original_pooling(self):
        import numpy as np
        from scipy.ndimage import grey_dilation
        from torch.nn.functional import max_pool2d
        rng = np.random.default_rng(7)
        mask = rng.random((3, 13, 17)).astype('float32')
        mask[0] = 0
        mask[0, 0, 0] = 1
        mask[1, -1, -1] = .5
        for radius in (0, 1, 3, 15):
            expected = max_pool2d(torch.from_numpy(mask[:, None]), 2*radius+1,
                stride=1, padding=radius)[:, 0] > .5
            fast = np.stack([grey_dilation(frame, size=(2*radius+1, 2*radius+1)) for frame in mask]) > .5
            self.assertTrue(np.array_equal(fast, expected.numpy()))

    def test_review_frames_masks_and_safe_cache(self):
        images = torch.rand(48, 32, 16, 3)
        masks = torch.zeros(48, 16, 8, 3)
        masks[:, 4:12, 2:6] = 1
        source = {'images': images, 'audio': None, 'frame_rate': 24}
        mask_video = {'images': masks, 'audio': None, 'frame_rate': 24}
        frames, mask, w, h = adapters.ZuraWanReviewedFrames().unpack(source, mask_video)
        self.assertEqual((w, h), (16, 32))
        self.assertEqual(mask.shape, frames.shape[:3])
        self.assertTrue(set(mask.unique().tolist()) <= {0, 1})
        with tempfile.TemporaryDirectory() as tmp, patch.object(adapters, 'cache_path', return_value=Path(tmp) / 'cache.pt'):
            adapters.ZuraWanSavePreparation().save(frames, mask, frames, torch.rand(48, 8, 8, 3), images[:1], 'a' * 64, 'person')
            footage, reference, width, height = adapters.ZuraWanLoadPreparation().load('a' * 64)
            self.assertEqual((width, height), (16, 32))
            self.assertTrue(torch.equal(footage['character_mask'], mask))
            self.assertEqual(footage['replacement_area'], 'Whole character')
            self.assertEqual(reference.shape[0], 1)
        with self.assertRaises(ValueError):
            adapters.ZuraWanReviewedFrames().unpack(source, {**mask_video, 'images': masks[:47]})

    def test_ui_has_one_resolution_and_length_and_all_engines(self):
        text = (v2_bootstrap.ROOT / 'web/studio.js').read_text(encoding='utf8')
        self.assertEqual(text.count('id="gs-resolution"'), 1)
        self.assertEqual(text.count('id="gs-duration"'), 1)
        self.assertNotIn('id="gs-size"', text)
        self.assertNotIn('id="gs-render_size"', text)
        self.assertNotIn('first 2 seconds', text)
        for engine in ('local', 'h3', 'wan', 'seedance'):
            self.assertIn(f'value="{engine}"', text)

    def test_zura_routes_keep_legacy_projects_accessible(self):
        server = types.SimpleNamespace(routes=studio.web.RouteTableDef())
        module = types.ModuleType('server')
        module.PromptServer = types.SimpleNamespace(instance=server)
        with patch.dict(sys.modules, {'server': module}), patch.object(studio, 'Studio'):
            studio.register()
            routes = {(r.method, r.path) for r in server.routes}
            branded = {(method, path.replace('/zura/studio', '/genj/studio'))
                for method, path in routes if path.startswith('/zura/studio')}
            legacy = {(method, path) for method, path in routes if path.startswith('/genj/studio')}
            self.assertEqual(branded, legacy)
            self.assertEqual(len(branded), 11)
            self.assertIn(('GET', '/zura/studio/status'), routes)
            studio.register()
            self.assertEqual(len(server.routes), 22, 'Reloading must not register duplicate routes')

    def test_reference_audio_reaches_preparation_and_invalidates_old_approval(self):
        p = self.project()
        before = studio.prep_key(p)
        p['audio'] = {'file': 'reference.wav', 'sha': 'speech'}
        p['config']['audio_start'] = 1.25
        self.assertNotEqual(studio.prep_key(p), before)
        with patch.object(studio, 'check_asset'):
            graph = studio.build_graph(p, 'prepare')
        self.assertEqual(graph['zura_reference_audio']['class_type'], 'LoadAudio')
        self.assertEqual(graph['3']['inputs']['audio'], ['zura_reference_audio', 0])
        self.assertEqual(graph['3']['inputs']['audio_start_seconds'], 1.25)
        for value in (float('nan'), -1, 86401):
            with self.assertRaises(ValueError):
                studio.clean_config({'audio_start': value})

    def test_graph_export_keeps_native_wan_preparation_editable(self):
        p = self.project()
        p['approval'] = studio.prep_key(p)
        p['opening_approval'] = None
        original = copy.deepcopy(p)
        with patch.object(studio, 'assert_approved'), patch.object(studio, 'check_asset'), \
                patch.object(wan, 'cache_key', return_value='a' * 64):
            graph, stage = studio.editable_graph(p, 'animate')
        self.assertEqual(stage, 'wan')
        self.assertEqual(p, original, 'Export must not approve or queue the saved project')
        self.assertIn('wan_pose_detect', graph)
        self.assertIn('wan_character_detect', graph)
        self.assertIn('wan_render', graph)
        self.assertNotIn('wan_save', graph)
        self.assertEqual(graph['wan_cached']['class_type'], 'ZuraWanPackPreparation')
        self.assertEqual(graph['wan_frames']['inputs']['source'], ['zura_audio_selection', 0])
        self.assertEqual(graph['wan_export']['inputs']['clip_details'], ['zura_audio_selection', 1])
        self.assertEqual(graph['zura_audio_selection']['inputs']['video'], ['wan_shot', 0])

    def test_graph_export_does_not_freeze_h3_prompt_in_cache(self):
        p = self.project()
        p['config']['engine'] = 'h3'
        p['approval'] = studio.prep_key(p)
        p['audio'] = {'file': 'speech.wav', 'sha': 'speech'}
        package.verify_review = lambda value: (None, {'clip': {'frames': 72}})
        with patch.object(studio, 'assert_approved'), patch.object(studio, 'check_asset'), \
                patch.object(h3, 'cache_key', return_value='b' * 64), \
                patch.object(h3, 'cache_path', return_value=Path(__file__)):
            graph, stage = studio.editable_graph(p, 'animate')
        self.assertEqual(stage, 'h3')
        self.assertIn('h3_references', graph)
        self.assertNotIn('h3_cached', graph)
        self.assertEqual(graph['h3_pad']['inputs']['source'], ['zura_audio_selection', 0])
        self.assertEqual(graph['zura_audio_selection']['inputs']['audio'], ['zura_reference_audio', 0])

    def test_original_clip_length_uses_native_full_source_selection(self):
        p = self.project()
        previous = studio.prep_key(p)
        p['config'] = studio.clean_config({**p['config'], 'start': 1, 'length_mode': 'original'})
        self.assertEqual(p['config']['start'], 0)
        self.assertNotEqual(previous, studio.prep_key(p))
        with patch.object(studio, 'check_asset'):
            graph = studio.build_graph(p, 'prepare')
        self.assertTrue(graph['3']['inputs']['use_original_length'])
        self.assertEqual(graph['3']['inputs']['start_seconds'], 0)


class AudioAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        latest = types.ModuleType('comfy_api.latest')
        class FileVideo:
            def __init__(self, path):
                self.path = path
            def get_stream_source(self):
                return self.path
            def get_dimensions(self):
                return 64, 64
        latest.InputImpl = types.SimpleNamespace(VideoFromFile=FileVideo,
            VideoFromComponents=lambda c: types.SimpleNamespace(get_components=lambda: c))
        latest.Types = types.SimpleNamespace(VideoComponents=lambda **kwargs: types.SimpleNamespace(**kwargs))
        cls.ns = {'__name__': 'zura_audio_unit'}
        source = (v2_bootstrap.ROOT / 'artist_studio/__init__.py').read_text(encoding='utf8')
        with patch.dict(sys.modules, {'comfy_api.latest': latest}):
            exec(compile(source.split('NODE_CLASS_MAPPINGS =')[0], 'artist_studio/__init__.py', 'exec'), cls.ns)

    def test_silent_audio_survives_both_ltx_padding_cases(self):
        for count, expected in ((9, 9), (48, 49)):
            components = types.SimpleNamespace(images=torch.zeros(count, 4, 4, 3), audio=None,
                frame_rate=Fraction(24))
            video = types.SimpleNamespace(get_components=lambda: components)
            result = self.ns['GenjLTXFramePad']().pad(video)[0].get_components()
            self.assertEqual(len(result.images), expected)
            self.assertEqual(result.audio['waveform'].shape, (1, 2, round(expected/24*48000)))
            self.assertEqual(float(result.audio['waveform'].abs().max()), 0)

    def test_reference_offset_padding_and_invalid_offset(self):
        import folder_paths
        with tempfile.TemporaryDirectory() as tmp, patch.object(folder_paths, 'get_output_directory', return_value=tmp, create=True):
            audio = {'sample_rate': 8000, 'waveform': torch.ones(1, 1, 8000)*.2}
            selected, details = self.ns['reference_audio']({'duration': 2}, audio, .5)
            self.assertEqual(selected['waveform'].shape[-1], 16000)
            self.assertEqual(float(selected['waveform'][..., 4000:].abs().max()), 0)
            self.assertEqual(details['audio_mode'], 'reference')
            self.assertTrue(Path(details['audio_source']).exists())
            self.assertEqual(self.ns['digest_file'](details['audio_source']), details['audio_hash'])
            for offset in (-1, 1, float('nan')):
                with self.assertRaises(ValueError):
                    self.ns['reference_audio']({'duration': 2}, audio, offset)

    def test_original_length_selects_all_frames_and_adds_silence_track(self):
        import av
        import folder_paths
        with tempfile.TemporaryDirectory() as tmp, patch.object(folder_paths, 'get_output_directory', return_value=tmp, create=True):
            source = Path(tmp) / 'silent.mp4'
            self.ns['encode_frames'](source, torch.zeros(36, 64, 64, 3))
            video = self.ns['InputImpl'].VideoFromFile(str(source))
            selected, details, _ = self.ns['GenjSelectClip']().select(video, .5, .25, 256, use_original_length=True)
            self.assertEqual(details['duration'], 1.5)
            self.assertEqual(details['frames'], 36)
            self.assertEqual(details['start'], 0)
            with av.open(selected.path) as media:
                self.assertEqual(len(media.streams.audio), 1)
                self.assertEqual(sum(1 for _ in media.decode(video=0)), 36)


if __name__ == '__main__':
    unittest.main()
