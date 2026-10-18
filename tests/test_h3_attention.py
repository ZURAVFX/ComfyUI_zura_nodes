"""Attention choices retain H3 references, motion controls and audio; CPU only."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch

import v2_bootstrap

NAME = "ComfyUI_zura_nodes.artist_studio"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[NAME] = package
package = sys.modules[NAME]
studio = importlib.import_module(NAME + ".studio")
h3 = importlib.import_module(NAME + ".h3")


class H3AttentionTests(unittest.TestCase):
    def build(self, backend=None, viewport=False):
        config = studio.clean_config({"engine": "h3", "duration": 2, "resolution": 1280,
                                      "quality": "fast", "workflow_mode": "viewport" if viewport else "motion"})
        if backend is not None:
            # The graph contract is independent of the UI/config whitelist.
            config["h3_attention"] = backend
        project = {"id": "a" * 32, "source": {"file": "source.mp4", "sha": "source"},
                   "character": {"file": "character.png", "sha": "character"}, "config": config,
                   "review": "shot_" + "a" * 16, "opening_key": "look", "opening_approval": "look",
                   "opening_input": {"file": "opening.png", "sha": "look"}}
        if viewport:
            refs = [{"file": "scene.png", "sha": "scene", "role": "environment"}]
            project.update(viewport_render=True, references=refs, viewport_references=refs)
        manifest = {"clip": {"frames": 48}, "files": {"source.mp4": "0" * 64, "mask.mp4": "1" * 64}}

        class Container:
            streams = types.SimpleNamespace(video=[types.SimpleNamespace(duration=2, time_base=1)])
            duration = 2_000_000
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False

        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                patch.object(package, "verify_review", return_value=(None, manifest), create=True), \
                patch.object(h3, "cache_key", return_value="c" * 64), \
                patch.object(h3, "cache_valid", return_value=False), \
                patch("av.open", return_value=Container()):
            return h3.build_h3_graph(project, use_cache=False)

    def test_native_default_preserves_both_approved_graphs(self):
        for viewport in (False, True):
            with self.subTest(viewport=viewport):
                self.assertEqual(self.build(viewport=viewport), self.build("native", viewport))
                self.assertNotIn("h3_attention", self.build(viewport=viewport))

    def test_patches_retain_all_conditioning_and_native_sampler_inputs(self):
        for viewport in (False, True):
            native = self.build(viewport=viewport)
            consumer = "h3_guider" if viewport else "h3_inpaint"
            for backend in ("kitchen", "sage_sol"):
                with self.subTest(viewport=viewport, backend=backend):
                    graph = self.build(backend, viewport)
                    self.assertEqual(graph[consumer]["inputs"]["model"], ["h3_attention", 0])
                    patch_node = graph["h3_attention"]
                    if backend == "kitchen":
                        self.assertEqual(patch_node, {"class_type": "ModelAttentionBackend", "inputs": {
                            "model": ["h3_shift", 0], "attention": "comfy kitchen attention"}})
                    else:
                        self.assertEqual(graph["h3_sage_attention"], {"class_type": "PathchSageAttentionKJ",
                            "inputs": {"model": ["h3_shift", 0], "sage_attention": "auto", "allow_compile": False}})
                        self.assertEqual(patch_node["class_type"], "SolAttnPatch")
                        self.assertEqual(patch_node["inputs"], {"model": ["h3_sage_attention", 0],
                            "tau": 1.5, "start_percent": 0.2, "end_percent": 0.9,
                            "min_tokens": 4096, "int8_qk": True, "sink_conditioning": "exact_kv",
                            "morton": False, "morton_curve": "3d", "int8_pv": False,
                            "verbose": False, "use_tma": False, "dense_blocks": ""})
                    # Undo only the inserted model patch chain, then compare every
                    # guide, reference, latent, scheduler and export input.
                    del graph["h3_attention"]
                    graph.pop("h3_sage_attention", None)
                    graph[consumer]["inputs"]["model"] = ["h3_shift", 0]
                    if viewport:
                        graph["h3_schedule"]["inputs"]["model"] = ["h3_shift", 0]
                    self.assertEqual(graph, native)

    def test_unknown_choice_does_not_silently_fall_back(self):
        for invalid in ("unknown", "", None, True):
            with self.subTest(value=invalid), self.assertRaisesRegex(ValueError, "H3 attention"):
                h3.apply_attention_backend(lambda *_args, **_kwargs: None, ["h3_shift", 0],
                                           {"h3_attention": invalid})


if __name__ == "__main__":
    unittest.main()
