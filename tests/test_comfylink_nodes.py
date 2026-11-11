"""Tests real tensor/image operations; folder_paths is mocked, not a live ComfyUI."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from PIL import Image
import torch

ROOT = Path(__file__).resolve().parents[1]

class BatchInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = "ComfyLink/" + "a" * 32
        self.path = self.root / self.folder
        self.path.mkdir(parents=True)
        sys.modules["folder_paths"] = types.SimpleNamespace(get_input_directory=lambda: str(self.root))
        spec = importlib.util.spec_from_file_location("comfylink_node_test", ROOT / "comfylink/nodes.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        for i in range(1, 3):
            Image.new("RGBA", (4, 3), (10*i, 40, 80, 64)).save(self.path / f"{i:06d}.png")

    def test_batch_shape_dtype_fps_alpha(self):
        images, masks, fps, count = self.module.ComfyLinkLoadFrames().load(self.folder, 23.976)
        self.assertEqual(tuple(images.shape), (2, 3, 4, 3))
        self.assertEqual(tuple(masks.shape), (2, 3, 4))
        self.assertEqual(images.dtype, torch.float32)
        self.assertAlmostEqual(float(masks[0, 0, 0]), 1.0 - 64/255, places=6)
        self.assertAlmostEqual(float(images[1, 0, 0, 0]), 20/255, places=6)
        self.assertEqual(fps, 23.976)
        self.assertEqual(count, 2)

    def test_reject_arbitrary_directory_and_traversal(self):
        for folder in ["../secret", str(self.root), "ComfyLink/../../secret", "", "ComfyLink/not-a-job"]:
            with self.subTest(folder=folder), self.assertRaises(ValueError):
                self.module.frame_paths(folder)

    def test_missing_frame_rejected(self):
        (self.path / "000001.png").unlink()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.module.frame_paths(self.folder)

    def test_dimension_mismatch_rejected(self):
        Image.new("RGBA", (6, 3)).save(self.path / "000002.png")
        with self.assertRaisesRegex(ValueError, "same dimensions"):
            self.module.ComfyLinkLoadFrames().load(self.folder, 25)

    def test_symlink_rejected(self):
        p = self.path / "000001.png"
        p.unlink()
        outside = self.root / "outside.png"
        Image.new("RGBA", (4, 3)).save(outside)
        try:
            p.symlink_to(outside)
        except OSError:
            self.skipTest("Symbolic links are not permitted on this Windows account")
        with self.assertRaisesRegex(ValueError, "unsafe"):
            self.module.frame_paths(self.folder)

    def test_cache_key_changes(self):
        cls = self.module.ComfyLinkLoadFrames
        before = cls.IS_CHANGED(self.folder, 25)
        Image.new("RGBA", (4, 3), (250, 0, 0, 255)).save(self.path / "000001.png")
        self.assertNotEqual(before, cls.IS_CHANGED(self.folder, 25))

if __name__ == "__main__":
    unittest.main(verbosity=2)
