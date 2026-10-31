import copy
import importlib
import unittest
import test_artist_studio

split = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_text_split')
exp = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_experiment')

class PromptSplitTests(unittest.TestCase):
    def test_real_graph_keeps_prompt_and_conditioning_without_model_in_video_phase(self):
        graph = exp.build_sdr_first_stage('source.mp4', start_frame=0, frame_count=9, width=512, height=512,
                                          left=32, top=32, right=32, bottom=32, prompt='warm light')
        before = copy.deepcopy(graph)
        text, video = split.split_prompt_graph(graph, 'a'*64)
        self.assertEqual(graph, before)
        self.assertEqual(text['positive']['inputs']['text'], 'warm light')
        self.assertEqual(text['negative'], before['negative'])
        self.assertEqual(video['conditioning']['inputs']['positive'], ['load_text', 0])
        self.assertEqual(video['conditioning']['inputs']['negative'], ['load_text', 1])
        self.assertEqual(video['conditioning']['inputs']['frame_rate'], before['conditioning']['inputs']['frame_rate'])
        for key in ('encoder', 'positive', 'negative'): self.assertNotIn(key, video)
        for name, node in video.items():
            for value in node['inputs'].values():
                if isinstance(value, list) and len(value)==2 and isinstance(value[0], str):
                    self.assertIn(value[0], video, name)

    def test_rejects_unexpected_consumers_and_invalid_key(self):
        graph = exp.build_sdr_first_stage('source.mp4', start_frame=0, frame_count=9, width=512, height=512)
        with self.assertRaisesRegex(ValueError, 'cache key'): split.split_prompt_graph(graph, '../x')
        graph['unexpected'] = {'class_type': 'Anything', 'inputs': {'x': ['positive', 0]}}
        with self.assertRaisesRegex(ValueError, 'unexpected consumers'): split.split_prompt_graph(graph, 'b'*64)
