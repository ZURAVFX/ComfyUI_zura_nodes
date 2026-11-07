import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("zura_attention_test", Path(__file__).resolve().parents[1] / "artist_studio" / "attention.py")
attention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(attention)


class Kitchen:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"attention": (["pytorch attention", "comfy kitchen attention"],)}}


class TorchOnly:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"attention": ("COMBO", {"options": ["pytorch attention"]})}}


class AttentionFallbackTests(unittest.TestCase):
    def graph(self):
        return {
            "model": {"class_type": "UNETLoader", "inputs": {}},
            "attention": {"class_type": "ModelAttentionBackend", "inputs": {"model": ["model", 0], "attention": "comfy kitchen attention"}},
            "guide": {"class_type": "BasicGuider", "inputs": {"model": ["attention", 0]}},
            "scheduler": {"class_type": "BasicScheduler", "inputs": {"model": ["attention", 0]}},
        }

    def test_kitchen_kept_torch_selected_and_native_reconnected(self):
        for cls, expected in ((Kitchen, "comfy kitchen attention"), (TorchOnly, "pytorch attention")):
            graph = attention.adapt_attention(self.graph(), {"ModelAttentionBackend": cls})
            self.assertEqual(graph["attention"]["inputs"]["attention"], expected)
            self.assertEqual(graph["guide"]["inputs"]["model"], ["attention", 0])
        graph = attention.adapt_attention(self.graph(), {})
        self.assertNotIn("attention", graph)
        self.assertEqual(graph["guide"]["inputs"]["model"], ["model", 0])
        self.assertEqual(graph["scheduler"]["inputs"]["model"], ["model", 0])


if __name__ == "__main__":
    unittest.main()
