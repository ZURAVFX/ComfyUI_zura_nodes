"""Data-only H3 reference assembly matches the installed native payload contract."""
import copy
import importlib
import unittest

import torch

import v2_bootstrap

module = importlib.import_module("ComfyUI_zura_nodes.h3_reference_data")
node_helpers = importlib.import_module("node_helpers")


def latent(shape, value=0.25):
    return {"samples": torch.full(shape, value, dtype=torch.float32)}


class H3ReferenceDataTests(unittest.TestCase):
    def setUp(self):
        self.embedding = torch.zeros(1, 3, 5120, dtype=torch.float32)
        self.tags = torch.tensor([1, 4, 7], dtype=torch.int64)
        self.keyframes = [{"resolved_frame_index": 0, "latent": torch.ones(1, 24, 1, 2, 4)}]
        self.metadata = {"minimax_token_tags": self.tags, "minimax_keyframes": self.keyframes,
                         "existing_artist_note": {"keep": True}}
        self.positive = [[self.embedding, self.metadata]]
        self.opening = latent((1, 24, 1, 4, 6))
        self.character = latent((1, 24, 1, 6, 8), 0.5)
        self.audio = latent((1, 32, 2, 19), 0.75)
        self.node = module.ZuraH3AttachEncodedReferences()

    def test_reference_blocks_match_native_payload_order_and_preserve_tensor_identity(self):
        before_metadata = copy.deepcopy(self.metadata)
        result, = self.node.attach(self.positive, self.opening, self.character, self.audio)
        blocks = result[0][1]["minimax_refs"]
        expected = [
            {"kind": "image", "latent_h": 4, "latent_w": 6, "latent": self.opening["samples"]},
            {"kind": "image", "latent_h": 6, "latent_w": 8, "latent": self.character["samples"]},
            {"kind": "audio", "ref_audio_t": 19, "audio_latent": self.audio["samples"]},
        ]
        self.assertEqual(len(blocks), len(expected))
        for actual, wanted in zip(blocks, expected):
            self.assertEqual({key: value for key, value in actual.items() if not isinstance(value, torch.Tensor)},
                             {key: value for key, value in wanted.items() if not isinstance(value, torch.Tensor)})
            tensor_key = "audio_latent" if actual["kind"] == "audio" else "latent"
            self.assertIs(actual[tensor_key], wanted[tensor_key])
        self.assertEqual(set(self.metadata), set(before_metadata))
        self.assertEqual(self.metadata["existing_artist_note"], before_metadata["existing_artist_note"])
        self.assertIs(self.metadata["minimax_token_tags"], self.tags)
        self.assertIs(self.metadata["minimax_keyframes"], self.keyframes)
        self.assertNotIn("minimax_refs", self.metadata)
        self.assertIs(result[0][0], self.embedding)
        self.assertIs(result[0][1]["minimax_token_tags"], self.tags)
        self.assertIs(result[0][1]["minimax_keyframes"], self.keyframes)
        self.assertEqual(result[0][1]["existing_artist_note"], {"keep": True})

    def test_image_only_references_match_native_conditioning_set_values(self):
        # Differential check against the exact helper used by native H3.
        reference_blocks = [
            {"kind": "image", "latent_h": 4, "latent_w": 6, "latent": self.opening["samples"]},
            {"kind": "image", "latent_h": 6, "latent_w": 8, "latent": self.character["samples"]},
        ]
        expected = node_helpers.conditioning_set_values(self.positive, {"minimax_refs": reference_blocks})
        actual, = self.node.attach(self.positive, self.opening, self.character)
        self.assertEqual(actual[0][1].keys(), expected[0][1].keys())
        for key in ("minimax_token_tags", "minimax_keyframes", "existing_artist_note"):
            self.assertIs(actual[0][1][key], expected[0][1][key])
        actual_blocks = actual[0][1]["minimax_refs"]
        expected_blocks = expected[0][1]["minimax_refs"]
        self.assertEqual(len(actual_blocks), len(expected_blocks))
        for actual_block, expected_block in zip(actual_blocks, expected_blocks):
            self.assertEqual({key: value for key, value in actual_block.items() if not isinstance(value, torch.Tensor)},
                             {key: value for key, value in expected_block.items() if not isinstance(value, torch.Tensor)})
            self.assertIs(actual_block["latent"], expected_block["latent"])
        self.assertIs(actual[0][1]["minimax_refs"][0]["latent"], self.opening["samples"])

    def test_existing_token_tags_and_keyframes_are_not_replaced_or_mutated(self):
        result, = self.node.attach(self.positive, self.opening, self.character)
        self.assertIs(result[0][1]["minimax_token_tags"], self.tags)
        self.assertIs(result[0][1]["minimax_keyframes"], self.keyframes)
        self.assertEqual(self.keyframes[0]["resolved_frame_index"], 0)

    def test_populated_or_malformed_existing_references_are_rejected(self):
        for existing in ([{"kind": "image"}], {"kind": "image"}, None):
            positive = [[self.embedding, {"minimax_refs": existing}]]
            with self.subTest(existing=existing), self.assertRaises(ValueError):
                self.node.attach(positive, self.opening, self.character)

    def test_unknown_reference_metadata_is_rejected_without_losing_it(self):
        positive = [[self.embedding, {"minimax_ref_video_notes": ["future metadata"]}]]
        with self.assertRaisesRegex(ValueError, "unsupported reference metadata"):
            self.node.attach(positive, self.opening, self.character)
        self.assertIn("minimax_ref_video_notes", positive[0][1])

    def test_malformed_conditioning_is_rejected(self):
        cases = [[], ((self.embedding,),), [[self.embedding, "metadata"]],
                 [[torch.zeros(1, 2, 8), {}]], [[torch.zeros(2, 2, 5120), {}]],
                 [[torch.full((1, 2, 5120), float("nan")), {}]],
                 [[torch.empty_strided((1, 4097, 5120), (0, 0, 0), dtype=torch.float16), {}]]]
        for positive in cases:
            with self.subTest(shape=type(positive).__name__), self.assertRaises(ValueError):
                self.node.attach(positive, self.opening, self.character)

    def test_invalid_image_latents_are_rejected(self):
        cases = [None, {"samples": torch.zeros(1, 24, 1, 2, 0)},
                 {"samples": torch.zeros(1, 23, 1, 2, 2)},
                 {"samples": torch.zeros(1, 24, 2, 2, 2)},
                 {"samples": torch.zeros(1, 24, 1, 3, 2)},
                 {"samples": torch.zeros(1, 24, 1, 2, 3)},
                 {"samples": torch.zeros(1, 24, 1, 4097, 1)},
                 {"samples": torch.empty_strided((1, 24, 1, 4096, 4096), (0, 0, 0, 0, 0))},
                 {"samples": torch.zeros(1, 24, 1, 2, 2, dtype=torch.int32)},
                 {"samples": torch.sparse_coo_tensor(torch.zeros((5, 0), dtype=torch.int64),
                                                      torch.zeros((0,)), (1, 24, 1, 2, 2))},
                 {"samples": torch.full((1, 24, 1, 2, 2), float("inf"))}]
        for value in cases:
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                self.node.attach(self.positive, value, self.character)

    def test_invalid_audio_latents_are_rejected(self):
        cases = [{"samples": torch.zeros(1, 32, 1, 5)},
                 {"samples": torch.zeros(1, 32, 2, 0)},
                 {"samples": torch.full((1, 32, 2, 5), float("nan"))},
                 {"samples": torch.zeros(1, 32, 2, 4097)}]
        for value in cases:
            with self.subTest(shape=tuple(value["samples"].shape)), self.assertRaises(ValueError):
                self.node.attach(self.positive, self.opening, self.character, value)

    def test_latent_dictionary_with_unconsumed_metadata_is_rejected(self):
        opening = {"samples": self.opening["samples"], "noise_mask": torch.ones(1, 1, 1, 3, 4)}
        # A latent-side metadata field must not be silently discarded.
        with self.assertRaises(ValueError):
            self.node.attach(self.positive, opening, self.character)


if __name__ == "__main__":
    unittest.main()
