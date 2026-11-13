"""Starting image model switching preserves original-frame editing contracts."""
import copy
import importlib.util
import json
import math
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

    def test_explicit_source_raster_retargets_klein_and_cloned_references(self):
        graph = self.graph()
        graph["zura_reference_2"] = {
            "class_type": "LoadImage",
            "inputs": {"image": "second.png"},
            "_meta": {"title": "Appearance reference 2"},
        }
        graph["zura_reference_2_scale"] = copy.deepcopy(graph["92:85"])
        graph["zura_reference_2_scale"]["inputs"]["image"] = ["zura_reference_2", 0]

        models.apply_model(graph, "klein9b", dimensions=(1936, 1088))

        for identity, image in (("92:111", ["125", 0]),
                                ("92:85", ["121", 0]),
                                ("zura_reference_2_scale", ["zura_reference_2", 0])):
            with self.subTest(identity=identity):
                node = graph[identity]
                self.assertEqual(node["class_type"], "ImageScale")
                self.assertEqual(node["inputs"]["image"], image)
                self.assertEqual(node["inputs"]["width"], 1936)
                self.assertEqual(node["inputs"]["height"], 1088)
                self.assertEqual(node["inputs"]["crop"], "disabled")

    def test_flux3_reuses_native_int8_image_recipe_with_original_first(self):
        graph = models.apply_model(self.graph(), "flux3", [{"file": "character.png"}])
        self.assertEqual(graph["92:107"]["inputs"]["unet_name"], "flux3-image-klein-int8-convrot.safetensors")
        self.assertEqual(graph["92:108"]["inputs"]["type"], "flux3")
        self.assertEqual(graph["92:102"]["inputs"]["steps"], 16)
        self.assertEqual(graph["zura_flux3_references"]["inputs"]["images.image0"], ["92:111", 0])
        self.assertEqual(graph["zura_flux3_reference_1"]["inputs"]["image"], "character.png")
        self.assertEqual(graph["92:104"]["inputs"]["latent_image"], ["92:113", 0])
        self.assertEqual(graph["zura_flux3_upsampler"]["inputs"]["clip_name"], "qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors")
        self.assertEqual(graph["92:109"]["inputs"]["text"], ["zura_flux3_prompt", 0])
        prompt = graph["zura_flux3_prompt"]["inputs"]
        self.assertEqual(prompt["system_prompt"], models.FLUX3_PROMPT_SYSTEMS["i2i"])
        self.assertEqual(prompt["max_length"], 3584)
        self.assertEqual(prompt["sampling_mode.seed"], 42)
        self.assertEqual(prompt["mtp"], "off")
        self.assertEqual(prompt["image"], ["zura_flux3_prompt_images", 0])
        batch = graph["zura_flux3_prompt_images"]["inputs"]
        self.assertEqual(batch["images.image0"], ["92:111", 0])
        self.assertEqual(batch["images.image1"], ["zura_flux3_reference_scale_1", 0])
        donor = graph["zura_flux3_reference_scale_1"]
        self.assertEqual(donor["class_type"], "ImageScale")
        self.assertEqual(donor["inputs"]["image"], ["zura_flux3_reference_1", 0])
        self.assertEqual((donor["inputs"]["width"], donor["inputs"]["height"]), (["92:114", 0], ["92:114", 1]))
        self.assertEqual(donor["inputs"]["crop"], "disabled")
        self.assertEqual(graph["zura_flux3_references"]["inputs"]["resolution"], "keep resolution")
        self.assertNotIn("resolution.megapixels", graph["zura_flux3_references"]["inputs"])
        shift = graph["zura_flux3_sampling"]["inputs"]
        self.assertEqual(shift["max_shift"], math.log(16))
        self.assertEqual(shift["base_shift"], math.log(16))
        self.assertEqual(graph["92:102"]["inputs"]["model"], ["zura_flux3_sampling", 0])
        self.assertEqual(graph["92:103"]["inputs"]["model"], ["zura_flux3_sampling", 0])
        self.assertEqual(graph["92:103"]["inputs"]["cfg"], 1)

    def test_qwen_uses_original_first_and_references_in_order(self):
        graph = models.apply_model(self.graph(), "qwen2511", [{"file": "one.png"}, {"file": "two.png"}])
        positive, negative = graph["92:109"]["inputs"], graph["92:86"]["inputs"]
        self.assertEqual(positive["image1"], ["92:111", 0])
        self.assertEqual(positive["prompt"], ["127", 0])
        self.assertEqual(negative["prompt"], "")
        for name in ("image1", "image2", "image3"):
            self.assertEqual(positive[name], negative[name])
        self.assertNotIn("vae", positive)
        self.assertNotIn("vae", negative)
        self.assertEqual(graph[positive["image2"][0]]["inputs"]["image"], ["zura_qwen_reference_2", 0])
        self.assertEqual(graph[graph[positive["image2"][0]]["inputs"]["image"][0]]["inputs"]["image"], "one.png")
        self.assertEqual(graph[positive["image3"][0]]["inputs"]["image"], ["zura_qwen_reference_3", 0])
        self.assertEqual(graph[graph[positive["image3"][0]]["inputs"]["image"][0]]["inputs"]["image"], "two.png")
        self.assertEqual(graph["92:104"]["inputs"]["latent_image"], ["92:127", 0])
        self.assertEqual(graph["92:127"]["class_type"], "VAEEncode")
        self.assertEqual(graph["92:127"]["inputs"]["pixels"], ["92:111", 0])
        self.assertEqual(graph["92:103"]["inputs"]["positive"], ["zura_qwen_positive_reference_3", 0])
        self.assertEqual(graph["92:103"]["inputs"]["negative"], ["zura_qwen_negative_reference_3", 0])
        self.assertEqual(graph["92:103"]["inputs"]["cfg"], 1.0)
        self.assertEqual(graph["zura_qwen_positive_reference_1"]["class_type"], "ReferenceLatent")
        self.assertEqual(graph["zura_qwen_negative_reference_1"]["class_type"], "ReferenceLatent")
        self.assertEqual(graph["92:110"]["inputs"]["vae_name"], "qwen_image_vae.safetensors")
        self.assertFalse(any(node["class_type"] in ("ZuraQwenEditLatent", "FluxKontextMultiReferenceLatentMethod",
                                                   "Flux2Scheduler", "EmptyFlux2LatentImage") for node in graph.values()))

    def test_qwen_retains_native_mask_and_output_ids(self):
        graph = self.graph()
        graph["zura_original_size"] = {"class_type": "GetImageSize", "inputs": {"image": ["125", 0]}}
        graph["zura_opening_latent_mask"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["92:127", 0], "mask": ["original_mask", 0]}}
        graph["original_mask"] = {"class_type": "SolidMask", "inputs": {"value": 1.0, "width": 512, "height": 512}}
        graph["92:104"]["inputs"]["latent_image"] = ["zura_opening_latent_mask", 0]
        models.apply_model(graph, "qwen2511", [])
        self.assertEqual(graph["92:104"]["inputs"]["latent_image"], ["zura_opening_latent_mask", 0])
        self.assertEqual(graph["zura_opening_latent_mask"]["inputs"]["samples"], ["92:127", 0])
        self.assertEqual(graph["92:127"]["class_type"], "VAEEncode")
        self.assertEqual(graph["92:127"]["inputs"]["pixels"], ["92:111", 0])
        self.assertEqual(graph["zura_qwen_positive_reference_1"]["inputs"]["latent"], ["92:127", 0])
        self.assertEqual(graph["zura_qwen_negative_reference_1"]["inputs"]["latent"], ["92:127", 0])
        self.assertEqual(graph["zura_qwen_decoded"]["inputs"]["vae"], ["92:110",0])
        self.assertEqual(graph["92:105"]["class_type"],"ImageScale")
        self.assertEqual(graph["92:105"]["inputs"]["crop"],"disabled")
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

    def test_ph3_uses_original_frame_and_references_with_native_av_latent(self):
        graph = self.graph()
        graph["zura_opening_latent_mask"] = {"class_type": "SetLatentNoiseMask", "inputs": {
            "samples": ["92:127", 0], "mask": ["source_mask", 0]}}
        graph["source_mask"] = {"class_type": "SolidMask", "inputs": {"value": 1.0, "width": 512, "height": 512}}
        graph["92:104"]["inputs"]["latent_image"] = ["zura_opening_latent_mask", 0]
        graph["zura_masked_look"] = {"class_type": "ImageCompositeMasked", "inputs": {
            "destination": ["125", 0], "source": ["92:105", 0], "mask": ["source_mask", 0],
            "x": 0, "y": 0, "resize_source": False}}
        graph["122"]["inputs"]["images"] = ["zura_masked_look", 0]
        result = models.apply_model(graph, "ph3", [{"file": "one.png"}, {"file": "two.png"}])
        self.assertEqual(result["92:107"]["inputs"]["unet_name"], "minimax_h3_fl2va_pruned_int8_convrot.safetensors")
        self.assertEqual(result["zura_ph3_adapter"]["class_type"], "LoraLoaderBypassModelOnly")
        self.assertEqual(result["zura_ph3_shift"]["inputs"]["shift_video"], 1.0)
        conditioning = result["92:109"]["inputs"]
        self.assertEqual(conditioning["images.image_1"], ["92:111", 0])
        self.assertEqual(result[conditioning["images.image_2"][0]]["inputs"]["image"], ["zura_ph3_reference_2", 0])
        self.assertEqual(result[conditioning["images.image_3"][0]]["inputs"]["image"], ["zura_ph3_reference_3", 0])
        self.assertEqual(result["zura_ph3_reference_2"]["inputs"]["image"], "one.png")
        self.assertEqual(result["zura_ph3_reference_3"]["inputs"]["image"], "two.png")
        self.assertEqual(result["zura_ph3_prompt_source"]["class_type"], "ImageScale")
        self.assertEqual(result["zura_ph3_prompt_source"]["inputs"]["crop"], "disabled")
        self.assertFalse(any(node["class_type"] in ("ImageScaleToTotalPixels", "ResizeAndPadImage")
                             for node in result.values()))
        self.assertEqual(result["92:104"]["inputs"]["latent_image"], ["92:109", 1])
        self.assertEqual(result["92:103"]["class_type"], "BasicGuider")
        self.assertEqual(result["92:102"]["class_type"], "ManualSigmas")
        self.assertEqual(result["zura_ph3_prompt"]["inputs"]["sampling_mode"], "off")
        self.assertIn("<Picture 3>", result["zura_ph3_prompt"]["inputs"]["prompt"])
        self.assertIn("zura_masked_look", result, "The artist's reviewed mask still controls the final composite")
        self.assertNotIn("zura_opening_latent_mask", result, "An image-only latent cannot drive the nested P-H3 sampler")
        self.assertFalse(any(node["class_type"] == "EmptyFlux2LatentImage" for node in result.values()))
        with self.assertRaisesRegex(ValueError, "seven appearance references"):
            models.apply_model(self.graph(), "ph3", [{"file": "ref.png"}] * 8)

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
        kinds.update({node["class_type"]: object for node in models.apply_model(self.graph(), "ph3", [{"file": "ref.png"}]).values()})
        kinds.update({'ZuraChatGPTImage': object, 'ZuraGeminiImage': object, 'GetImageSize': object})
        files = {pair for model in models.MODELS.values() for pair in model["files"]}
        status = models.readiness(kinds, lambda folder, name: "installed" if (folder, name) in files else None)
        self.assertTrue(all(m["ready"] for m in status.values()))
        self.assertEqual(status["qwen2511"]["raster_limits"]["max_pixels"], 8_388_608)
        self.assertEqual(status["ph3"]["raster_limits"]["max_pixels"], 16_777_216)
        with self.assertRaisesRegex(ValueError, "16-pixel raster grid"):
            models.apply_model(self.graph(), "klein9b", dimensions=(1921, 1081))
        with self.assertRaisesRegex(ValueError, "supported raster"):
            models.apply_model(self.graph(), "klein9b", dimensions=(4096, 4096))
        absent_upsampler = models.readiness(kinds, lambda folder, name: None if name == "qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors" else "installed")
        self.assertFalse(absent_upsampler["flux3"]["ready"])
        self.assertTrue(absent_upsampler["ph3"]["ready"])
        missing_expander = models.readiness({k: v for k, v in kinds.items() if k != "TextGenerate"}, lambda folder, name: "installed")
        self.assertFalse(missing_expander["flux3"]["ready"])
        self.assertIn("TextGenerate", missing_expander["flux3"]["missing_nodes"])
        kinds.pop("TextEncodeQwenImageEditPlus")
        status = models.readiness(kinds, lambda folder, name: "installed")
        self.assertTrue(status["klein9b"]["ready"])
        self.assertFalse(status["qwen2511"]["ready"])
        self.assertIn("TextEncodeQwenImageEditPlus", status["qwen2511"]["missing_nodes"])


if __name__ == "__main__":
    unittest.main()
