"""CPU-only contract tests for the isolated native Wan Animate 2 prototype."""
import importlib
import sys
import types
import unittest

import v2_bootstrap


PACKAGE_NAME = "ComfyUI_zura_nodes.artist_studio"
if PACKAGE_NAME not in sys.modules:
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[PACKAGE_NAME] = package
animate2 = importlib.import_module(PACKAGE_NAME + ".wan_animate2")


def node_inputs(graph, key):
    return graph[key]["inputs"]


def native_schema_fixture():
    return {
        node_name: {"input": {"required": {name: ["ANY"] for name in inputs}}}
        for node_name, inputs in animate2.NATIVE_NODE_INPUTS.items()
    }


class WanAnimate2GraphTests(unittest.TestCase):
    def build(self, **overrides):
        args = {
            "reference_image": "look.png",
            "driving_video": "motion.mp4",
            "prompt": "A red-haired adult detective in a rainy Tokyo street.",
            "frame_count": 9,
            "width": 832,
            "height": 480,
            "seed": 23,
        }
        args.update(overrides)
        return animate2.build_animate2_graph(**args)

    def test_uses_pinned_new_animate2_checkpoint_and_distilled_recipe(self):
        self.assertTrue(animate2.STUDIO_INTEGRATED)
        graph = self.build()
        by_type = {node["class_type"]: node for node in graph.values()}
        self.assertEqual(
            node_inputs(graph, "animate2_unet"),
            {"unet_name": "wan_animate_2_distill_int8_convrot.safetensors", "weight_dtype": "default"},
        )
        self.assertEqual(
            node_inputs(graph, "animate2_text_encoder"),
            {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"},
        )
        self.assertEqual(animate2.MODEL_FILES["clip_vision"], "clip_vision_h.safetensors")
        self.assertEqual(animate2.MODEL_FILES["vae"], "Wan2_1_VAE_bf16.safetensors")
        self.assertEqual(node_inputs(graph, "animate2_sampling_shift")["shift"], 5.0)
        self.assertEqual(node_inputs(graph, "animate2_sigmas"), {
            "model": ["animate2_sampling_shift", 0], "scheduler": "simple", "steps": 10, "denoise": 1.0,
        })
        self.assertEqual(node_inputs(graph, "animate2_sampler"), {"sampler_name": "lcm"})
        self.assertEqual(node_inputs(graph, "animate2_sample")["cfg"], 1.0)
        self.assertEqual(node_inputs(graph, "animate2_pose_cache")["dtype"], "int8")
        self.assertEqual(node_inputs(graph, "animate2_pose_cache")["device"], "cpu")
        self.assertEqual(by_type["SaveVideo"]["inputs"]["filename_prefix"], "zura_dev/wan_animate2")

    def test_connects_reference_and_raw_driver_frames_to_native_character_transfer(self):
        graph = self.build(frame_count=13)
        self.assertEqual(node_inputs(graph, "driving_video"), {"file": "motion.mp4"})
        self.assertEqual(node_inputs(graph, "driving_video_frames"), {"video": ["driving_video", 0]})
        self.assertEqual(node_inputs(graph, "pose_frames"), {
            "image": ["driving_video_frames", 0], "batch_index": 0, "length": 13,
        })
        self.assertEqual(node_inputs(graph, "animate2_conditioning")["reference_image"], ["reference_image", 0])
        self.assertEqual(node_inputs(graph, "animate2_conditioning")["pose_video"], ["pose_frames", 0])
        self.assertEqual(node_inputs(graph, "animate2_conditioning")["clip_vision_output"], ["reference_vision", 0])
        self.assertEqual(node_inputs(graph, "animate2_conditioning")["clip_vision_output_pose"], ["pose_vision", 0])
        self.assertEqual(node_inputs(graph, "animate2_conditioning")["length"], 13)
        self.assertEqual(node_inputs(graph, "animate2_trim_reference")["trim_amount"], ["animate2_conditioning", 3])
        self.assertEqual(node_inputs(graph, "animate2_decode")["samples"], ["animate2_trim_reference", 0])
        self.assertEqual(node_inputs(graph, "animate2_video"), {"images": ["animate2_decode", 0], "fps": 24.0})

    def test_optional_motion_prompt_is_native_positive_pose_conditioning(self):
        graph = self.build(motion_prompt="Walk slowly, then turn left.")
        self.assertEqual(node_inputs(graph, "motion_prompt"), {
            "clip": ["animate2_text_encoder", 0], "text": "Walk slowly, then turn left."
        })
        self.assertEqual(
            node_inputs(graph, "animate2_conditioning")["positive_pose"], ["motion_prompt", 0]
        )
        without = self.build()
        self.assertNotIn("positive_pose", node_inputs(without, "animate2_conditioning"))

    def test_graph_only_uses_native_nodes_and_has_no_spatial_mask_or_composite(self):
        graph = self.build()
        self.assertTrue({node["class_type"] for node in graph.values()} <= set(animate2.NATIVE_NODE_INPUTS))
        self.assertFalse(any("mask" in key.lower() for key in graph))
        for node in graph.values():
            self.assertFalse(any("mask" in key.lower() or "composite" in key.lower()
                                 for key in node["inputs"]))
        with self.assertRaisesRegex(animate2.WanAnimate2GraphError, "no native spatial-mask input"):
            self.build(spatial_mask="painted-mask.png")

    def test_resolution_frame_and_cache_limits_are_enforced(self):
        self.assertEqual(node_inputs(self.build(), "animate2_conditioning")["length"], 9)
        self.build(width=480, height=832, frame_count=81)
        for dimensions in ((831, 480), (832, 481), (640, 640), (1280, 720)):
            with self.subTest(dimensions=dimensions), self.assertRaisesRegex(
                animate2.WanAnimate2GraphError, "multiples of 16|capped at 832"
            ):
                self.build(width=dimensions[0], height=dimensions[1])
        for frames in (True, 4, 6, 82):
            with self.subTest(frames=frames), self.assertRaises(animate2.WanAnimate2GraphError):
                self.build(frame_count=frames)
        for frames in (5, 9, 81):
            with self.subTest(frames=frames):
                self.build(frame_count=frames)
        with self.assertRaisesRegex(animate2.WanAnimate2GraphError, "Cache device"):
            self.build(cache_device="vram-ish")

    def test_rejects_missing_media_prompt_and_invalid_seed(self):
        for overrides, message in (
            ({"reference_image": ""}, "reference image"),
            ({"driving_video": " "}, "driving video"),
            ({"prompt": " "}, "prompt"),
            ({"seed": -1}, "Seed"),
            ({"seed": True}, "Seed"),
            ({"motion_prompt": " "}, "motion prompt"),
        ):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(
                animate2.WanAnimate2GraphError, message
            ):
                self.build(**overrides)

    def test_native_schema_contract_detects_missing_node_or_input(self):
        schemas = native_schema_fixture()
        self.assertIsNone(animate2.validate_native_schemas(schemas))
        missing_node = dict(schemas)
        del missing_node["WanAnimate2ToVideo"]
        with self.assertRaisesRegex(animate2.WanAnimate2GraphError, "missing native node WanAnimate2ToVideo"):
            animate2.validate_native_schemas(missing_node)
        missing_field = native_schema_fixture()
        del missing_field["WanAnimate2ToVideo"]["input"]["required"]["pose_strength"]
        with self.assertRaisesRegex(animate2.WanAnimate2GraphError, "pose_strength"):
            animate2.validate_native_schemas(missing_field)

    def test_every_emitted_graph_input_matches_declared_native_schema_contract(self):
        graph = self.build(motion_prompt="Lift a hand and wave.")
        for node in graph.values():
            with self.subTest(node=node["class_type"]):
                self.assertLessEqual(set(node["inputs"]), animate2.NATIVE_NODE_INPUTS[node["class_type"]])


if __name__ == "__main__":
    unittest.main()
