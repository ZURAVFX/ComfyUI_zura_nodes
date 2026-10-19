import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('zura_h3_camera_test', ROOT/'artist_studio/h3_camera.py')
camera = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = camera
spec.loader.exec_module(camera)


class CameraGraphTests(unittest.TestCase):
    def request(self, **kw):
        return camera.CameraRequest('source.mp4', camera_image='approved.png', **kw)

    def test_native_distilled_sampling_and_weights(self):
        graph = camera.build_graph(self.request())
        self.assertEqual(graph['model']['inputs']['unet_name'], 'minimax_h3_ref2va_pruned_int8_convrot.safetensors')
        self.assertEqual(graph['turbo']['inputs']['lora_name'], 'minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors')
        self.assertEqual(graph['turbo']['inputs']['strength_model'], 1.)
        self.assertEqual(graph['attention']['inputs']['attention'], 'comfy kitchen attention')
        self.assertEqual(graph['sampler']['inputs']['sampler_name'], 'res_multistep')
        self.assertEqual(graph['sigmas']['inputs']['steps'], 8)
        self.assertEqual(graph['shift']['inputs']['shift_audio'], 3.)
        self.assertNotIn('still_model', graph)

    def test_approved_camera_route_anchors_the_still_without_geometry_warp(self):
        graph = camera.build_graph(self.request(prompt='Keep the hat visible.'))
        kinds = {n['class_type'] for n in graph.values()}
        self.assertTrue(kinds.isdisjoint({'LoadMoGeModel', 'MoGeInference', 'CrossViewWarp'}))
        self.assertEqual(graph['image_guide']['inputs']['image'], ['camera_size', 0])
        self.assertEqual(graph['crossview_lora']['inputs']['strength_model'], .8)
        self.assertEqual(graph['turbo']['inputs']['model'], ['model', 0])
        self.assertEqual(graph['shift']['inputs']['model'], ['turbo', 0])
        self.assertEqual(graph['crossview_lora']['inputs']['model'], ['shift', 0])
        self.assertEqual(graph['attention']['inputs']['model'], ['crossview_lora', 0])
        self.assertEqual(graph['references']['inputs']['ref_images.ref_image_0'], ['camera_size', 0])
        self.assertTrue(graph['references']['inputs']['prompt'].startswith('crossview.'))
        self.assertEqual(graph['start_encode']['inputs']['pixels'], ['camera_size', 0])
        self.assertIn('Keep the hat visible.', graph['references']['inputs']['prompt'])
        self.assertEqual(graph['audio_lock']['inputs']['latent'], ['start_lock', 0])

    def test_performance_audio_and_still_are_independent_native_guides(self):
        graph = camera.build_graph(self.request(start_seconds=1.5))
        refs = graph['references']['inputs']
        self.assertEqual(refs['ref_images.ref_image_0'], ['camera_size', 0])
        self.assertEqual(refs['ref_videos.ref_video_0'], ['performance_pad', 0])
        self.assertEqual(refs['ref_video_audios.ref_video_audio_0'], ['components', 1])
        self.assertEqual(graph['image_guide']['inputs']['latent'], ['references', 1])
        self.assertEqual(graph['audio_guide']['inputs']['latent'], ['references', 1])
        self.assertEqual(graph['guider']['inputs']['conditioning'], ['audio_guide', 0])
        self.assertEqual(graph['start_lock']['inputs']['latent'], ['references', 1])
        self.assertEqual(graph['audio_lock']['inputs']['latent'], ['start_lock', 0])
        self.assertEqual(graph['sample']['inputs']['latent_image'], ['audio_lock', 0])
        self.assertEqual(graph['select']['inputs']['start_seconds'], 1.5)
        self.assertFalse(any('ControlNet' in n['class_type'] or 'SAM' in n['class_type'] for n in graph.values()))

    def test_two_second_padding_and_output_interval(self):
        graph = camera.build_graph(self.request())
        self.assertEqual(graph['references']['inputs']['length'], 56)
        self.assertEqual(graph['trim']['inputs']['length'], 48)
        self.assertEqual(graph['video']['inputs']['audio'], ['components', 1])
        self.assertEqual(graph['export']['class_type'], 'GenjRestoreSoundtrack')
        self.assertEqual(graph['export']['inputs']['clip_details'], ['select', 1])

    def test_camera_still_stage_does_not_load_h3_and_only_reads_one_frame(self):
        r = camera.CameraRequest('source.mp4', source_path='input/source.mp4', start_seconds=1.5)
        graph = camera.build_still_graph(r)
        self.assertEqual(graph['source_still']['inputs']['frame_load_cap'], 1)
        self.assertEqual(graph['source_still']['inputs']['skip_first_frames'], 36)
        self.assertEqual(graph['still_sample']['inputs']['steps'], 16)
        self.assertEqual(graph['still_sample']['inputs']['cfg'], 1.)
        self.assertEqual(graph['still_latent']['inputs']['width'], 1024)
        self.assertFalse(any('minimax' in str(n['inputs']) for n in graph.values()))

    def test_uploaded_camera_still_omits_all_inference(self):
        graph = camera.build_still_graph(self.request())
        self.assertEqual({n['class_type'] for n in graph.values()}, {'LoadImage', 'SaveImage'})

    def test_optional_references_keep_aspect_ratio_and_roles(self):
        r = self.request(references=(camera.CameraReference('face.png', 1200, 1600), camera.CameraReference('room.png', 1600, 900, 'scene')))
        graph = camera.build_graph(r)
        self.assertEqual(graph['ref_size_0']['inputs']['width'], 512)
        self.assertEqual(graph['ref_size_0']['inputs']['height'], 683)
        self.assertEqual(graph['ref_size_1']['inputs']['width'], 640)
        self.assertEqual(graph['ref_size_1']['inputs']['height'], 360)
        self.assertEqual(graph['references']['inputs']['ref_images.ref_image_2'], ['ref_size_1', 0])
        self.assertIn('<Picture 3> supplies scene geometry only', graph['references']['inputs']['prompt'])

    def test_invalid_intervals_and_silent_video_are_actionable(self):
        for kw in ({'duration_seconds':6}, {'start_seconds':float('nan')}, {'source_has_audio':False}):
            with self.assertRaises(ValueError):
                camera.build_graph(self.request(**kw))

    def test_readiness_separates_image_and_video_dependencies(self):
        kinds = {n['class_type'] for n in camera.build_graph(self.request()).values()}
        report = camera.readiness(dict.fromkeys(kinds), lambda folder,name: '/models/'+name)
        self.assertTrue(report['video']['ready'])
        self.assertFalse(report['still']['ready'])
        self.assertTrue(report['quality_verified_locally'])
        self.assertEqual(report['verified_seconds'], 2)
        self.assertEqual(report['max_seconds'], 5)

    def test_missing_crossview_adapter_blocks_video_only(self):
        kinds = {n['class_type'] for n in camera.build_graph(self.request()).values()}
        kinds.update(n['class_type'] for n in camera.build_still_graph(camera.CameraRequest('source.mp4')).values())
        report = camera.readiness(dict.fromkeys(kinds), lambda folder, name: None if name == camera.MODELS['crossview'][1] else '/models/'+name)
        self.assertTrue(report['still']['ready'])
        self.assertFalse(report['video']['ready'])

    def test_graph_has_only_existing_dependencies(self):
        for graph in (camera.build_graph(self.request()), camera.build_still_graph(camera.CameraRequest('source.mp4'))):
            for node in graph.values():
                for value in node['inputs'].values():
                    if isinstance(value,list) and len(value)==2:
                        self.assertIn(value[0], graph)

    def test_unapproved_studio_camera_still_is_rejected_before_asset_io(self):
        with self.assertRaisesRegex(ValueError, 'Approve'):
            camera.build_studio_graph({'opening_key':'new','opening_approval':'old'}, lambda asset: self.fail('must reject first'))


class StartFrameAnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import torch
            from comfy.nested_tensor import NestedTensor
        except ImportError:
            raise unittest.SkipTest("Requires the native Comfy Python runtime.")
        cls.torch, cls.NestedTensor = torch, NestedTensor
        spec = importlib.util.spec_from_file_location('zura_start_frame_test', ROOT/'h3_start_frame.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.anchor = module.ZuraH3LockStartFrame()

    def latent(self):
        t = self.torch
        return {'samples': self.NestedTensor((t.zeros(1,24,4,2,3), t.zeros(1,32,2,20)))}

    def test_only_first_video_frame_is_locked_and_audio_remains_available(self):
        t = self.torch
        result = self.anchor.lock(self.latent(), {'samples': t.ones(1,24,1,2,3)})[0]
        video, audio = result['samples'].tensors
        video_mask, audio_mask = result['noise_mask'].tensors
        self.assertTrue(t.all(video[:,:,:1] == 1))
        self.assertTrue(t.all(video[:,:,1:] == 0))
        self.assertTrue(t.all(video_mask[:,:,:1] == 0))
        self.assertTrue(t.all(video_mask[:,:,1:] == 1))
        self.assertTrue(t.all(audio_mask == 1))
        self.assertTrue(t.all(audio == 0))

    def test_previous_audio_lock_is_preserved(self):
        t = self.torch
        latent = self.latent()
        video, audio = latent['samples'].tensors
        latent['noise_mask'] = self.NestedTensor((t.ones_like(video), t.zeros_like(audio)))
        result = self.anchor.lock(latent, {'samples': t.ones(1,24,1,2,3)})[0]
        self.assertTrue(t.all(result['noise_mask'].tensors[1] == 0))
        self.assertTrue(t.all(latent['samples'].tensors[0] == 0))

    def test_wrong_canvas_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            self.anchor.lock(self.latent(), {'samples': self.torch.ones(1,24,1,3,2)})


if __name__ == '__main__':
    unittest.main()
