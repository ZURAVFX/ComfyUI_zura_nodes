import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("custom_loras", Path(__file__).parents[1] / "artist_studio" / "custom_loras.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CustomLoraTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "character.safetensors"
        self.write_header({"__metadata__": {"base_model": "minimax_h3_ref2va"},
                           "diffusion_model.layer.lora_up.weight": {}})
        self.lookup = lambda folder, name: str(self.path) if name == self.path.name else None
        self.graph = {"base": {"class_type": "UNETLoader", "inputs":
                              {"unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors"}},
                      "shift": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["base", 0]}},
                      "other": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sam.safetensors"}}}

    def tearDown(self):
        self.tmp.cleanup()

    def write_header(self, data):
        raw = json.dumps(data).encode()
        self.path.write_bytes(len(raw).to_bytes(8, "little") + raw)

    def patch(self, family="h3", selection=None):
        selection = selection or {"name": self.path.name, "strength": .75}
        return module.apply_to_graph(self.graph, family, [selection], [self.path.name], self.lookup)

    def test_patches_model_input_without_changing_original_or_sam(self):
        patched = self.patch()
        self.assertEqual(self.graph["shift"]["inputs"]["model"], ["base", 0])
        self.assertEqual(patched["shift"]["inputs"]["model"], ["zura_custom_lora_0_0", 0])
        self.assertEqual(patched["zura_custom_lora_0_0"]["inputs"]["model"], ["base", 0])
        self.assertEqual(patched["other"], self.graph["other"])

    def test_incompatible_and_unknown_need_explicit_decision(self):
        self.write_header({"__metadata__": {"base_model": "wan2.2"}})
        with self.assertRaisesRegex(ValueError, "incompatible"):
            self.patch()
        self.write_header({"__metadata__": {}})
        with self.assertRaisesRegex(ValueError, "Confirm compatibility"):
            self.patch()
        self.patch(selection={"name": self.path.name, "confirm_unknown": True})

    def test_blocks_text_encoder_and_unregistered_files(self):
        self.write_header({"lora_te_text_model.foo": {}})
        with self.assertRaisesRegex(ValueError, "text-encoder"):
            self.patch(selection={"name": self.path.name, "confirm_unknown": True})
        with self.assertRaisesRegex(ValueError, "registered"):
            self.patch(selection={"name": "../elsewhere.safetensors"})

    def test_unsupported_graph_does_not_fake_success(self):
        self.graph.pop("base")
        with self.assertRaisesRegex(ValueError, "native model loader"):
            self.patch()

    def test_partial_file_and_strength_are_rejected(self):
        self.path.write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.patch()
        self.write_header({"__metadata__": {"base_model": "minimax_h3"}})
        with self.assertRaisesRegex(ValueError, "strength"):
            self.patch(selection={"name": self.path.name, "strength": float("nan")})

    def test_family_mapping_prevents_cross_family_model_patch(self):
        self.assertEqual(module.model_family("Wan2_2-Animate-14B_fp8.safetensors"), "wan22")
        self.assertEqual(module.model_family("wan_animate_2_distill_int8.safetensors"), "wan_animate2")
        self.assertEqual(module.model_family("flux-2-klein-9b-fp8.safetensors"), "flux2_klein9b")
        with self.assertRaisesRegex(ValueError, "incompatible"):
            self.patch("wan22")

    def test_image_validation_requires_correct_family_and_confirmation(self):
        selection = {"name": self.path.name, "strength": 0.8}
        self.write_header({"__metadata__": {"base_model": "flux-2-klein-9b"}})
        validated = module.validate_image_loras("klein9b", [selection], [self.path.name], self.lookup)
        self.assertEqual(validated, [{"name": self.path.name, "strength": 0.8}])
        with self.assertRaisesRegex(ValueError, "incompatible"):
            module.validate_image_loras("qwen2511", [selection], [self.path.name], self.lookup)
        self.write_header({"__metadata__": {}})
        with self.assertRaisesRegex(ValueError, "Confirm compatibility"):
            module.validate_image_loras("flux3", [selection], [self.path.name], self.lookup)
        module.validate_image_loras("flux3", [{**selection, "confirm_unknown": True}], [self.path.name], self.lookup)


if __name__ == "__main__":
    unittest.main()
