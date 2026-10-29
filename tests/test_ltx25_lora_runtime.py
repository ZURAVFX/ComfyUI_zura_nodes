"""Studio resolves installed LTX adapters into each immutable native plan."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import test_ltx25_studio_runtime as fixture

studio = fixture.studio
package = fixture.package


class LtxLoraRuntimeTests(unittest.TestCase):
    def test_runtime_pins_and_revalidates_adapter(self):
        project, _ = fixture.example()
        project["config"]["custom_loras"] = [{"name": "style.safetensors", "strength": .65, "confirm_unknown": False}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.mp4").write_bytes(b"source")
            def write_header(path, data):
                raw = json.dumps(data).encode()
                path.write_bytes(len(raw).to_bytes(8, "little") + raw)
            union = root / "union.safetensors"
            write_header(union, {"__metadata__": {"reference_downscale_factor": "2"}})
            adapter = root / "style.safetensors"
            write_header(adapter, {"__metadata__": {"base_model": "ltx-2.5"}, "diffusion_model.x": {}})
            detector_root = root / "custom"
            for relative in studio.LTX25_DETECTORS.values():
                path = detector_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"detector")
            manifest = {"clip": {"frames": 48, "fps": 24, "start": 0, "has_audio": True}}
            container = types.SimpleNamespace(streams=types.SimpleNamespace(video=[types.SimpleNamespace(width=704, height=1280)], audio=[object()]))
            class Context:
                def __enter__(self): return container
                def __exit__(self, *args): return None
            get_path = lambda folder, name: str(adapter if folder == "loras" and name == adapter.name else union)
            with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset", return_value=root / "source.mp4"), \
                    patch.object(package, "verify_review", return_value=(root, manifest), create=True), \
                    patch.object(studio.av, "open", return_value=Context()), \
                    patch.object(studio.folder_paths, "get_full_path", side_effect=get_path), \
                    patch.object(studio.folder_paths, "get_folder_paths", return_value=[str(detector_root)], create=True), \
                    patch.object(studio.folder_paths, "get_filename_list", return_value=[adapter.name], create=True):
                first = studio.ltx25_native_plan(project)
                self.assertEqual(first["basis"]["custom_loras"][0]["pin"]["path"], str(adapter.resolve()))
                for phase in ("stage1", "refine"):
                    self.assertEqual(first["phases"][phase]["custom_lora_0"]["inputs"]["strength_model"], .65)
                write_header(adapter, {"__metadata__": {"base_model": "ltx-2.5"}, "diffusion_model.changed": {}})
                changed = studio.ltx25_native_plan(project)
                self.assertNotEqual(first["key"], changed["key"])
                write_header(adapter, {"__metadata__": {"base_model": "minimax_h3"}, "diffusion_model.x": {}})
                with self.assertRaisesRegex(ValueError, "incompatible"):
                    studio.ltx25_native_plan(project)


if __name__ == "__main__":
    unittest.main()
