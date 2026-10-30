"""Starting image model switching preserves original-frame editing contracts."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("opening_models", ROOT / "artist_studio/opening_models.py")
models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(models)


class OpeningModelTests(unittest.TestCase):
    def graph(self):
        return json.loads((ROOT / "artist_studio/graphs/01B_Design_Opening_Frame.json").read_text())

    def test_klein_default_is_unchanged(self):
        graph = self.graph()
        before = copy.deepcopy(graph)
        self.assertIs(models.apply_model(graph), graph)
        self.assertEqual(graph, before)

    def test_flux3_reuses_native_int8_image_recipe_with_original_first(self):
        graph = models.apply_model(self.graph(), "flux3", [{"file": "character.png"}])
        self.assertEqual(graph["92:107"]["inputs"]["unet_name"], "flux3-image-klein-int8-convrot.safetensors")
        self.assertEqual(graph["92:108"]["inputs"]["type"], "flux3")
        self.assertEqual(graph["92:102"]["inputs"]["steps"], 16)
        self.assertEqual(graph["zura_flux3_references"]["inputs"]["images.image0"], ["92:111", 0])
        self.assertEqual(graph["zura_flux3_reference_1"]["inputs"]["image"], "character.png")
        self.assertEqual(graph["92:104"]["inputs"]["latent_image"], ["92:113", 0])

    def test_qwen_uses_original_first_and_references_in_order(self):
        graph = models.apply_model(self.graph(), "qwen2511", [{"file": "one.png"}, {"file": "two.png"}])
        positive, negative = graph["92:109"]["inputs"], graph["92:86"]["inputs"]
        self.assertEqual(positive["image1"], ["92:111", 0])
        self.assertEqual(positive["prompt"], ["127", 0])
        self.assertEqual(negative["prompt"], "")
        for name in ("image1", "image2", "image3"):
            self.assertEqual(positive[name], negative[name])
        self.assertEqual(graph[positive["image2"][0]]["inputs"]["image"], "one.png")
        self.assertEqual(graph[positive["image3"][0]]["inputs"]["image"], "two.png")
        self.assertEqual(graph["92:104"]["inputs"]["latent_image"], ["92:127", 0])
        self.assertEqual(graph["92:110"]["inputs"]["vae_name"], "qwen_image_vae.safetensors")
        self.assertFalse(any(node["class_type"] in ("ReferenceLatent", "Flux2Scheduler", "EmptyFlux2LatentImage") for node in graph.values()))

    def test_qwen_retains_native_mask_and_output_ids(self):
        graph = self.graph()
        graph["zura_original_size"] = {"class_type": "GetImageSize", "inputs": {"image": ["125", 0]}}
        graph["zura_opening_latent_mask"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["92:127", 0], "mask": ["original_mask", 0]}}
        graph["original_mask"] = {"class_type": "SolidMask", "inputs": {"value": 1.0, "width": 512, "height": 512}}
        graph["92:104"]["inputs"]["latent_image"] = ["zura_opening_latent_mask", 0]
        models.apply_model(graph, "qwen2511", [])
        self.assertEqual(graph["92:104"]["inputs"]["latent_image"], ["zura_opening_latent_mask", 0])
        self.assertEqual(graph["zura_opening_latent_mask"]["inputs"]["samples"], ["92:127", 0])
        self.assertEqual(graph["92:127"]["inputs"]["vae"], ["92:110", 0])
        for identity in ("122", "125", "127", "92:105", "92:114", "zura_original_size"):
            self.assertIn(identity, graph)

    def test_qwen21_uses_own_conditioning_latent_and_no_old_lora(self):
        graph = models.apply_model(self.graph(), "qwen21", [{"file": "ref.png"}])
        self.assertEqual(graph["92:109"]["class_type"], "TextEncodeQwenImage21")
        self.assertEqual(graph["92:109"]["inputs"]["images.image_1"], ["92:111", 0])
        self.assertEqual(graph["92:109"]["inputs"]["resolution"], 0)
        self.assertEqual(graph["92:104"]["inputs"]["latent_image"], ["92:109", 2])
        self.assertEqual(graph["92:111"]["inputs"]["resolution_steps"], 32)
        self.assertEqual(graph["92:102"]["inputs"]["steps"], 40)
        self.assertEqual(graph["92:105"]["class_type"], "SplitImageWithAlpha")
        self.assertFalse(any(node["class_type"] in ("LoraLoaderModelOnly", "TextEncodeQwenImageEditPlus") for node in graph.values()))
        self.assertEqual(graph["92:108"]["inputs"]["clip_name"], "qwen3vl_8b_int8_convrot.safetensors")
        self.assertEqual(graph["92:108"]["inputs"]["device"], "default", "Allow Comfy to use the GPU and offload as needed")

    def test_unknown_model_and_excess_references_fail_clearly(self):
        with self.assertRaisesRegex(ValueError, "Choose an available"):
            models.apply_model(self.graph(), "unknown")
        with self.assertRaisesRegex(ValueError, "two appearance references"):
            models.apply_model(self.graph(), "qwen2511", [{"file": "ref.png"}] * 3)

    def test_availability_is_independent(self):
        kinds = {node["class_type"]: object for node in self.graph().values()}
        qwen = models.apply_model(self.graph(), "qwen2511", [{"file": "ref.png"}])
        kinds.update({node["class_type"]: object for node in qwen.values()})
        qwen21 = models.apply_model(self.graph(), "qwen21", [{"file": "ref.png"}])
        kinds.update({node["class_type"]: object for node in qwen21.values()})
        kinds.update({node["class_type"]: object for node in models.apply_model(self.graph(), "flux3").values()})
        files = {pair for model in models.MODELS.values() for pair in model["files"]}
        status = models.readiness(kinds, lambda folder, name: "installed" if (folder, name) in files else None)
        self.assertTrue(all(m["ready"] for m in status.values()))
        kinds.pop("TextEncodeQwenImageEditPlus")
        status = models.readiness(kinds, lambda folder, name: "installed")
        self.assertTrue(status["klein9b"]["ready"])
        self.assertFalse(status["qwen2511"]["ready"])
        self.assertIn("TextEncodeQwenImageEditPlus", status["qwen2511"]["missing_nodes"])


if __name__ == "__main__":
    unittest.main()
