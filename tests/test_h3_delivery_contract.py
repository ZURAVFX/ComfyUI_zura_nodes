"""H3 queue/collector contracts include the same held tail as the native graph."""
import sys
import tempfile
import types
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import av
import numpy as np

import test_artist_studio as fixtures
import test_h3_enhanced1080 as enhanced

s, delivery = fixtures.studio, enhanced.enhancement


class H3DeliveryContracts(fixtures.unittest.IsolatedAsyncioTestCase):
    async def test_every_h3_route_records_the_encoded_length_before_queueing(self):
        camera = __import__(s.__package__ + '.h3_camera', fromlist=['selected_frame_count'])
        head = __import__(s.__package__ + '.h3_head_swap', fromlist=['selected_frame_count'])
        review = sys.modules[s.__package__]
        for route in ('viewport', 'character', 'openjutsu', 'camera', 'head'):
            for selected, expected in ((5, 5), (48, 56), (72, 73), (120, 124)):
                with self.subTest(route=route, selected=selected):
                    p = fixtures.SharedEngineTests().project()
                    p['config'].update(engine='h3', workflow_mode='viewport' if route == 'viewport' else 'motion',
                                       h3_character_method='openjutsu' if route == 'openjutsu' else 'control')
                    c = s.Studio.__new__(s.Studio)
                    c.collect = lambda p: p
                    c.store = types.SimpleNamespace(save=Mock())
                    c.start_watcher = Mock()
                    c.server_address = 'test'
                    queued = Mock()
                    c.server = types.SimpleNamespace(number=0, prompt_queue=types.SimpleNamespace(put=queued),
                        trigger_on_prompt=lambda body: body,
                        node_replace_manager=types.SimpleNamespace(apply_replacements=lambda graph: None))
                    execution = types.SimpleNamespace(validate_prompt=AsyncMock(return_value=(True, None, ['h3_export'], {})))
                    with patch.dict(sys.modules, {'execution': execution}), \
                         patch.object(s, 'build_graph', return_value={'h3_export': {'class_type': 'TestOutput', 'inputs': {}}}), \
                         patch.object(s, 'validate_selection'), \
                         patch.object(s, '_needs_h3_reference_stage', return_value=False), \
                         patch.object(s, 'camera_setup', return_value=route == 'camera'), \
                         patch.object(s, 'head_swap_setup', return_value=route == 'head'), \
                         patch.object(s, 'h3_render_rasters', return_value=({'width':1280,'height':736}, {'width':1280,'height':720})), \
                         patch.object(review, 'verify_review', return_value=(None, {'clip': {'frames': selected}}), create=True), \
                         patch.object(camera, 'selected_frame_count', return_value=selected), \
                         patch.object(head, 'selected_frame_count', return_value=selected):
                        await c.action(p, 'h3', {'request_key': str(uuid.uuid4())})
                    self.assertEqual(p['actions'][-1]['expected_frames'], expected)
                    self.assertEqual(queued.call_count, 1)
                    self.assertEqual(p['actions'][-1]['state'], 'queued')

    def test_padding_is_bounded_and_never_shortens_a_selection(self):
        for selected in range(5, 121):
            result = delivery.h3_delivery_frames(selected)
            self.assertGreaterEqual(result, selected)
            self.assertLessEqual(result - selected, 16)
            self.assertEqual(result % 17, 5)
        for invalid in (True, 0, 4, 121, 72.0, '72', None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                delivery.h3_delivery_frames(invalid)

    def test_five_second_enhancement_accepts_124_frame_padded_base(self):
        p = fixtures.SharedEngineTests().project()
        p['config'].update(engine='h3', delivery_mode='enhanced1080')
        action = {'id':'action', 'studio_action_tag':'action', 'delivery_mode':'enhanced1080',
                  'expected_frames':124, 'base_output_raster':{'width':1280,'height':720}}
        asset = {'type':'output','subfolder':'genj/studio_intermediate','filename':'base.mp4'}
        history = {'outputs':{'h3_export':{'gifs':[asset]}}}
        c = s.Studio.__new__(s.Studio)
        c._history_has_action_tag = lambda *args: True
        c.store = types.SimpleNamespace(save=Mock())
        c.schedule_resume = Mock()
        actual = {'width':1280,'height':720,'frames':124,'fps':24,'audio_tracks':0}
        with patch.object(sys.modules[s.__package__], 'verify_review', return_value=(None, {'clip':{'frames':120,'has_audio':False}}), create=True), \
             patch.object(delivery, 'checked_output_path', return_value=Path('base.mp4')), \
             patch.object(delivery, 'inspect_video', return_value=actual), \
             patch.object(s, 'sha', return_value='verified'), \
             patch.object(s, 'h3_render_rasters', return_value=(None, {'width':1920,'height':1080})):
            self.assertTrue(c._collect_h3_base(p, action, history))
        self.assertEqual(p['h3_enhancement_base']['frames'], 124)
        self.assertEqual(action['state'], 'complete')
        c.schedule_resume.assert_called_once()

    def test_real_73_frame_mp4_is_presented_once_and_wrong_length_still_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root/'genj/final/take.mp4'
            output.parent.mkdir(parents=True)
            with av.open(str(output), 'w') as container:
                stream = container.add_stream('libx264', rate=24)
                stream.width = stream.height = 32
                stream.pix_fmt = 'yuv420p'
                for frame in range(73):
                    image = av.VideoFrame.from_ndarray(np.full((32,32,3), frame, dtype=np.uint8), format='rgb24')
                    for packet in stream.encode(image): container.mux(packet)
                for packet in stream.encode(): container.mux(packet)
            asset = {'type':'output','subfolder':'genj/final','filename':'take.mp4'}
            history = {'render':{'status':{'status_str':'success'},'outputs':{'h3_export':{'gifs':[asset]}}}}
            c = s.Studio.__new__(s.Studio)
            c.store = s.Store(root/'projects')
            c.server_address = 'test'
            c.server = types.SimpleNamespace(prompt_queue=enhanced.FakeQueue(history=history))
            for expected, phase in ((73, 'done'), (72, 'error')):
                p = {'id':'b'*32,'config':{'engine':'h3'},'phase':'working','results':[],
                     'actions':[{'id':'render','stage':'h3','state':'queued','server_address':'test',
                                 'delivery_mode':'native','duration':3,'expected_frames':expected,
                                 'base_output_raster':{'width':32,'height':32}}]}
                with patch('folder_paths.get_output_directory', return_value=str(root), create=True):
                    c.collect(p)
                    c.collect(p)
                self.assertEqual(p['phase'], phase)
                if phase == 'done':
                    self.assertEqual(len(p['results']), 1)
                    self.assertEqual(p['results'][0]['output_raster']['frames'], 73)
                    self.assertEqual(p['results'][0]['duration'], 73/24)
                else:
                    self.assertEqual(p['results'], [])
                    self.assertIn('73 frames; 72 were expected', p['error'])


if __name__ == '__main__':
    fixtures.unittest.main()
