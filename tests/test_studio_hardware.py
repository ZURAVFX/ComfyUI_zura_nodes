import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("studio_hardware", Path(__file__).parents[1] / "artist_studio/hardware.py")
hardware = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hardware)

class HardwareGuidanceTests(unittest.TestCase):
    def snapshot(self, kind, total):
        mm = SimpleNamespace(get_torch_device=lambda: SimpleNamespace(type=kind),
                             get_torch_device_name=lambda device: "Test device",
                             get_total_memory=lambda device: total * 2**30)
        memory = SimpleNamespace(virtual_memory_total=lambda: 64 * 2**30,
                                 virtual_memory_available=lambda: 20 * 2**30)
        with mock.patch.dict(sys.modules, {"comfy": SimpleNamespace(model_management=mm, system_memory=memory)}):
            return hardware.snapshot()

    def test_cpu_ram_is_not_reported_as_vram(self):
        result = self.snapshot("cpu", 64)
        self.assertIsNone(result["hardware"]["vram_gib"])
        self.assertTrue(result["hardware"]["shared_memory"])

    def test_mps_is_shared_memory(self):
        self.assertIsNone(self.snapshot("mps", 64)["hardware"]["vram_gib"])

    def test_gpu_capacity_is_read_only_guidance(self):
        result = self.snapshot("cuda", 16)
        self.assertEqual(result["hardware"]["vram_gib"], 16)
        self.assertEqual(result["model_guidance"]["h3"]["start_resolution"], 1280)
        self.assertEqual(result["model_guidance"]["local"]["workflow_max_custom_seconds"], 5)

    def test_lower_vram_does_not_invent_a_hard_size_limit(self):
        result = self.snapshot("cuda", 8)
        self.assertEqual(result["model_guidance"]["wan"]["start_resolution"], 512)
        self.assertNotIn("max_resolution", result["model_guidance"]["wan"])
        self.assertEqual(result["model_guidance"]["h3"]["start_resolution"], 1280)

    def test_unavailable_probe_preserves_guidance(self):
        with mock.patch.dict(sys.modules, {"comfy": None}):
            result = hardware.snapshot()
        self.assertIsNone(result["hardware"]["vram_gib"])
        self.assertIn("seedance", result["model_guidance"])

    def test_h3_speed_is_qualified_by_sampling_recipe(self):
        guide = hardware.guidance({"vram_gib": 16})["h3"]
        self.assertEqual(guide["recommended_quality"], "fast")
        self.assertEqual(guide["quality_guidance"]["fast"]["sampling_steps"], 8)
        self.assertEqual(guide["quality_guidance"]["detailed"]["sampling_steps"], 40)
        self.assertIn("not separately benchmarked", guide["quality_guidance"]["fast"]["reference_speed"])
        self.assertIn("No measured time guarantee", guide["quality_guidance"]["detailed"]["reference_speed"])
        self.assertIn("every sampling step", guide["speed_warning"])

if __name__ == "__main__":
    unittest.main()
