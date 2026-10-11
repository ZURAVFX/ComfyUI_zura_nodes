"""Wan Animate fast recipe compatibility checks; graph-only, no GPU required."""
import test_artist_studio as fixtures
from pathlib import Path
from unittest.mock import patch


studio = fixtures.studio
wan = fixtures.wan


class WanFastRecipeTests(fixtures.unittest.TestCase):
    def test_manual_bounded_motion_key_selects_explicit_cache_without_global_patch(self):
        project = fixtures.SharedEngineTests().project()
        manual_key = 'c' * 64
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                patch.object(wan, "cache_key") as ordinary_key, \
                patch.object(wan, "cache_path", return_value=Path(__file__)) as cache:
            graph = wan.build_wan_graph(project, cache_key_override=manual_key)
        ordinary_key.assert_not_called()
        self.assertTrue(all(call.args == (manual_key,) for call in cache.call_args_list))
        self.assertEqual(graph['wan_cached']['inputs']['cache_key'], manual_key)
        self.assertEqual(graph['wan_render']['class_type'], 'ZuraWan22StreamedSampler')
        self.assertEqual(graph['wan_export']['inputs']['video'], ['wan_render', 0])
        self.assertEqual(graph['wan_render']['inputs']['seed'], project['config']['seed'])

    def test_manual_motion_key_cannot_enable_unbounded_or_redirected_cache(self):
        project = fixtures.SharedEngineTests().project()
        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"):
            for key, bounded in [('c' * 64, False), ('../cache', True), ('C' * 64, True), (17, True)]:
                with self.subTest(key=key, bounded=bounded), self.assertRaises(ValueError):
                    wan.build_wan_graph(project, use_cache=bounded, cache_key_override=key)

    def test_fast_recipe_uses_only_the_compatible_low_noise_adapter(self):
        project = fixtures.SharedEngineTests().project()
        project["config"]["quality"] = "fast"

        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                patch.object(wan, "cache_key", return_value="a" * 64):
            graph = wan.build_wan_graph(project, use_cache=False)

        # Studio readiness is derived from WAN_MODELS, so the incompatible
        # optional I2V adapter must not become a required Animate dependency.
        self.assertNotIn("wan_turbo_high", wan.WAN_MODELS)
        self.assertNotIn("wan_turbo_high", graph)

        low_name = "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"
        self.assertEqual(wan.WAN_MODELS["wan_turbo"], ("loras", low_name))
        self.assertEqual(graph["wan_turbo"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(graph["wan_turbo"]["inputs"]["lora_name"], low_name)
        self.assertEqual(graph["wan_turbo"]["inputs"]["strength_model"], .6)
        self.assertEqual(graph["wan_turbo"]["inputs"]["model"], ["wan_model", 0])
        self.assertEqual(graph["wan_relight"]["inputs"]["model"], ["wan_turbo", 0])
        self.assertEqual(graph["wan_relight"]["inputs"]["strength_model"], 1.0)
        self.assertEqual(graph["wan_realism"]["inputs"]["model"], ["wan_relight", 0])
        self.assertEqual(graph["wan_realism"]["inputs"]["strength_model"], 1.0)
        self.assertEqual(graph["wan_model"]["inputs"]["weight_dtype"], "fp8_e4m3fn_fast")
        self.assertEqual(graph["wan_shift"]["inputs"]["model"], ["wan_realism", 0])
        self.assertEqual(graph["wan_shift"]["inputs"]["shift"], 8.0)
        self.assertEqual(graph["wan_render"]["inputs"]["steps"], 6)
        self.assertEqual(graph["wan_render"]["inputs"]["cfg"], 1.0)
        self.assertEqual(graph["wan_render"]["inputs"]["chunk_frames"], 81)
        self.assertEqual(graph["wan_render"]["inputs"]["overlap_frames"], 5)

    def test_detailed_recipe_keeps_full_sampler_without_fast_adapter(self):
        project = fixtures.SharedEngineTests().project()
        project["config"]["quality"] = "detailed"

        with patch.object(studio, "assert_approved"), patch.object(studio, "check_asset"), \
                patch.object(wan, "cache_key", return_value="b" * 64):
            graph = wan.build_wan_graph(project, use_cache=False)

        self.assertNotIn("wan_turbo", graph)
        self.assertNotIn("wan_turbo_high", graph)
        self.assertEqual(graph["wan_realism"]["inputs"]["model"], ["wan_relight", 0])
        self.assertEqual(graph["wan_realism"]["inputs"]["strength_model"], 1.0)
        self.assertEqual(graph["wan_shift"]["inputs"]["shift"], 8.0)
        self.assertEqual(graph["wan_render"]["inputs"]["steps"], 40)
        self.assertEqual(graph["wan_render"]["inputs"]["cfg"], 5.0)
        self.assertEqual(graph["wan_render"]["inputs"]["chunk_frames"], 81)
        self.assertEqual(graph["wan_render"]["inputs"]["overlap_frames"], 5)
