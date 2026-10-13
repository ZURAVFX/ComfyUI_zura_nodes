"""Optional attention availability and saved-project settings; no GPU."""
import importlib
import sys
import types
import unittest

import v2_bootstrap

NAME = "ComfyUI_zura_nodes.artist_studio"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[NAME] = package
studio = importlib.import_module(NAME + ".studio")


class AttentionSettingsTests(unittest.TestCase):
    def test_legacy_projects_keep_native_and_selected_backend_roundtrips(self):
        self.assertEqual(studio.clean_config({"engine": "h3"})["h3_attention"], "native")
        for backend in ("native", "kitchen", "sage_sol"):
            config = studio.clean_config({"engine": "h3", "h3_attention": backend})
            self.assertEqual(studio.clean_config(config)["h3_attention"], backend)
        with self.assertRaisesRegex(ValueError, "h3_attention"):
            studio.clean_config({"h3_attention": "unknown"})

    def test_availability_requires_complete_optional_stack(self):
        self.assertEqual(studio.h3_attention_capabilities({}),
                         {"native": True, "kitchen": False, "sage_sol": False})
        for name in ("PathchSageAttentionKJ", "SolAttnPatch"):
            self.assertFalse(studio.h3_attention_capabilities({name: object()})["sage_sol"])
        self.assertEqual(studio.h3_attention_capabilities({name: object() for name in
                         ("ModelAttentionBackend", "PathchSageAttentionKJ", "SolAttnPatch")}),
                         {"native": True, "kitchen": True, "sage_sol": True})
