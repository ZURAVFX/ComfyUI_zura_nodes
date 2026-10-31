import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('panorama_camera_test', Path(__file__).resolve().parents[1]/'artist_studio/panorama_camera.py')
camera = importlib.util.module_from_spec(spec)
spec.loader.exec_module(camera)


class PanoramaCameraTests(unittest.TestCase):
    source = {'sha': 'a'*64, 'duration': 10, 'has_audio': True, 'file': 'genj_studio/example/source.mp4'}

    def selection(self, **config):
        return camera.plan(self.source, {'start': 1.5, 'duration': 2, **config})

    def graph(self, **kw):
        p = self.selection()
        return camera.build_graph(self.source, p, None, 'render', warp='warp.mp4 [output]', **kw)

    def test_full_temporal_warp_reaches_native_addguide(self):
        g = self.graph()
        self.assertEqual(g['warp_guide']['inputs']['image'], ['warp_pad', 0])
        self.assertEqual(g['warp_pad']['inputs']['image1'], ['warp_size', 0])
        self.assertEqual(g['warp_size']['inputs']['image'], ['warp_components', 0])
        self.assertEqual(g['warp_last']['inputs']['batch_index'] if 'warp_last' in g else g['warp_pad_last']['inputs']['batch_index'], 47)
        self.assertEqual(g['references']['inputs']['ref_videos.ref_video_0'], ['performance_pad', 0])
        self.assertEqual(g['references']['inputs']['length'], 56)
        self.assertNotIn('ZuraH3LockStartFrame', {n['class_type'] for n in g.values()})

    def test_approved_sampling_and_final_crop(self):
        g = self.graph()
        self.assertEqual(g['model']['inputs']['unet_name'], camera.MODELS['h3'][1])
        self.assertEqual(g['turbo']['inputs']['strength_model'], 1)
        self.assertEqual(g['crossview']['inputs']['strength_model'], .8)
        self.assertEqual(g['sampler']['inputs']['sampler_name'], 'res_multistep')
        self.assertEqual(g['sigmas']['inputs']['steps'], 8)
        self.assertEqual(g['crop']['inputs'], {'image': ['trim', 0], 'width': 1920, 'height': 1080, 'x': 0, 'y': 4})
        self.assertEqual(g['trim']['inputs']['length'], 48)
        for node in ['audio_lock', 'audio_guide', 'video']:
            self.assertEqual(g[node]['inputs']['audio'], ['components', 1])

    def test_soft_look_adds_to_full_video_guide(self):
        g = self.graph(look='look.png')
        self.assertEqual(g['look_guide']['inputs']['positive'], ['warp_guide', 0])
        self.assertEqual(g['audio_guide']['inputs']['positive'], ['look_guide', 0])
        self.assertEqual(g['references']['inputs']['ref_images.ref_image_1'], ['identity', 0])

    def test_camera_changes_do_not_invalidate_geometry(self):
        p = self.selection()
        state = json.loads(camera.camera_state(None, p))
        state['camera']['rotation']['value']['yaw_deg'] = 22
        graph = camera.build_graph(self.source, p, state, 'warp')
        self.assertEqual(graph['cached_geometry']['inputs']['cache_key'], p['key'])
        self.assertNotIn('MoGeInference', {n['class_type'] for n in graph.values()})
        self.assertNotEqual(self.selection(start=2)['key'], p['key'])
        self.assertNotEqual(self.selection(width=1280, height=720)['key'], p['key'])

    def test_non24fps_duration_rounds_up_then_trims(self):
        p = self.selection(duration=2.01)
        self.assertEqual(p['frames'], 49)
        self.assertEqual(p['padded'], 56)
        graph = camera.build_graph(self.source, p, None, 'render', warp='warp.mp4')
        self.assertTrue(graph['select']['inputs']['round_up'])
        self.assertEqual(graph['trim']['inputs']['length'], 49)
        self.assertEqual(graph['warp_pad_hold']['inputs']['amount'], 7)

    def test_native_camera_state_preserves_keyframes(self):
        p = self.selection()
        state = json.loads(camera.camera_state(None, p))
        state['camera']['fov']['keyframes'] = [{'frame': 24, 'value': 75}]
        result = json.loads(camera.camera_state(state, p))
        self.assertEqual(result['camera']['fov']['keyframes'], state['camera']['fov']['keyframes'])
        self.assertEqual(result['timeline'], {'fps': 24, 'length': 48})
        state['camera']['fov']['value'] = float('nan')
        with self.assertRaises(ValueError): camera.camera_state(state, p)

    def test_interval_and_grid_rejected_before_inference(self):
        for config in [{'duration': 6}, {'start': 9}, {'width': 1919}, {'width': 3840, 'height': 2160}]:
            with self.assertRaises(ValueError): self.selection(**config)

    def test_all_links_resolve(self):
        for stage in ['geometry', 'warp', 'render']:
            g = camera.build_graph(self.source, self.selection(), None, stage, warp='warp.mp4')
            for node in g.values():
                for v in node['inputs'].values():
                    if isinstance(v, list): self.assertIn(v[0], g)


if __name__ == '__main__': unittest.main()
