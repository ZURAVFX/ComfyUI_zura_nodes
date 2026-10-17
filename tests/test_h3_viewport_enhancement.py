"""Viewport enhancement must follow the real direct-reference and raster route."""
import copy
import types
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import torch
import test_h3_enhanced1080 as fixtures

studio, enhancement, h3 = fixtures.studio, fixtures.enhancement, fixtures.h3


class ViewportEnhancementTests(fixtures.EnhancementFixture):
    def direct_project(self):
        project = copy.deepcopy(self.project)
        project.pop('opening_input')
        project.pop('opening_key')
        project.pop('character')
        project.update(look_mode='build', references=[{'file': str(self.input), 'sha': 'reference', 'role': 'environment'}])
        project['config'].update(workflow_mode='viewport', h3_viewport_direct=True)
        return project

    def test_complete_enhancement_builder_accepts_openingless_direct_and_checks_real_refs(self):
        project = self.direct_project()
        base = {**self.base, 'generation_key': enhancement.generation_key(project)}
        with ExitStack() as stack:
            for context in self.patch_graph_dependencies():
                stack.enter_context(context)
            checked = stack.enter_context(patch.object(studio, 'check_asset', side_effect=lambda asset: Path(asset['file'])))
            graph = enhancement.build_graph(project, base, run_id='direct')
        self.assertIn(project['references'][0], [call.args[0] for call in checked.call_args_list])
        self.assertIn('h3_enhance_export', graph)
        self.assertEqual(graph['h3_enhance_export']['inputs']['clip_details'], ['h3_enhance_review', 3])
        self.assertEqual(graph['h3_enhance_lanczos']['inputs']['height'], 1920)

    def test_changing_any_viewport_reference_or_role_invalidates_base(self):
        project = self.direct_project()
        original = enhancement.generation_key(project)
        project['references'][0]['sha'] = 'changed'
        self.assertNotEqual(enhancement.generation_key(project), original)
        original = enhancement.generation_key(project)
        project['references'][0]['role'] = 'character'
        self.assertNotEqual(enhancement.generation_key(project), original)

    def test_review_and_enhancement_share_selected_audio_and_offset(self):
        project = self.direct_project()
        project['audio'] = {'id': 'custom', 'file': str(self.input), 'sha': 'custom-audio'}
        project['config'].update(audio_id='custom', audio_start=1.25)
        with patch.object(studio, 'check_asset', return_value=self.input):
            prepare = studio.build_graph(project, 'prepare', use_cache=False)
        self.assertEqual(prepare['3']['inputs']['audio'], ['zura_reference_audio', 0])
        self.assertEqual(prepare['3']['inputs']['audio_start_seconds'], 1.25)
        self.assertEqual(prepare['20']['inputs']['clip_details'], ['3', 1])
        key = studio.prep_key(project)
        project['config']['audio_start'] = 1.5
        self.assertNotEqual(studio.prep_key(project), key)

    def test_viewport_metadata_matches_native_32_pixel_padding_without_upscaling(self):
        project = self.direct_project()
        for width, height, expected_model, expected_output in (
            (1920, 1080, (1280, 736), (1280, 720)),
            (640, 360, (640, 384), (640, 360)),
        ):
            container = fixtures.VideoContainer()
            container.streams.video[0].width, container.streams.video[0].height = width, height
            with patch.object(studio, 'check_asset', return_value=self.input), patch.object(enhancement.av, 'open', return_value=container):
                model, output = studio.h3_render_rasters(project, 1280)
                _, delivery = studio.h3_render_rasters(project, 1920, delivery=True)
            self.assertEqual((model['width'], model['height']), expected_model)
            self.assertEqual((output['width'], output['height']), expected_output)
            self.assertEqual(delivery, {'width': 1920, 'height': 1080})
            images = torch.zeros(5, expected_output[1], expected_output[0], 3)
            video = types.SimpleNamespace(get_components=lambda: types.SimpleNamespace(images=images, frame_rate=24))
            native = h3.GenjH3ViewportFrameData().prepare(video)
            self.assertEqual(native[1:3], expected_model)
            self.assertEqual(native[7:9], expected_output)
