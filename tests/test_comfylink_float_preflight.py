import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfylink.preflight import inspect_graph

class FloatWorkflowPreflightTest(unittest.TestCase):
    def setUp(self):
        self.graph = {
            '1': {'class_type': 'ZuraComfyLinkLoadFloatFrames', 'inputs': {'manifest': ''}},
            '2': {'class_type': 'ZuraComfyLinkSaveFloatFrames', 'inputs': {'images': ['1', 0], 'frame_metadata': ['1', 2]}},
            '3': {'class_type': 'LoadImage', 'inputs': {'image': ''}},
        }
        self.available = {node['class_type'] for node in self.graph.values()} | {'SaveImage'}

    def inspect(self, graph):
        return inspect_graph(graph, {'node': '1', 'field': 'manifest'}, {'node': '2'}, self.available)

    def test_accepts_typed_float_workflow(self):
        self.assertTrue(self.inspect(self.graph)['ready'])

    def test_rejects_image_saver_and_disconnected_typed_inputs(self):
        graph = copy.deepcopy(self.graph)
        graph['2']['class_type'] = 'SaveImage'
        self.assertFalse(self.inspect(graph)['ready'])
        for field in ('images', 'frame_metadata'):
            graph = copy.deepcopy(self.graph)
            graph['2']['inputs'][field] = ['3', 0]
            self.assertFalse(self.inspect(graph)['ready'])

if __name__ == '__main__':
    unittest.main()
