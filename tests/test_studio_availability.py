"""Retired UI choices cannot enqueue jobs through saved projects or stale clients."""
import asyncio
import copy
import json
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from test_artist_studio import studio
from ComfyUI_zura_nodes.artist_studio.availability import require_verified_setup, verified_setup


class AvailabilityTests(unittest.TestCase):
    def config(self, **changes):
        return studio.clean_config({"engine": "wan", "workflow_mode": "swap", **changes})

    def test_character_path_and_original_or_replacement_audio_remain_available(self):
        for engine in ("wan", "h3"):
            for extra in ({}, {"audio_id": "a" * 32, "lip_sync": True}, {"scope": "head"}):
                with self.subTest(engine=engine, extra=extra):
                    self.assertTrue(verified_setup(self.config(engine=engine, **extra)))

    def test_ltx_performance_route_allows_original_replacement_and_silent_clips(self):
        # Absence of a selected track permits original audio or a silent source;
        # the native planner inspects the actual media to choose the scenario.
        for subject in ("auto", "people"):
            for audio in ({}, {"audio_id": "a" * 32, "lip_sync": True},
                          {"audio_id": "a" * 32, "lip_sync": False}):
                config = self.config(engine="local", workflow_mode="motion", subject_mode=subject, **audio)
                with self.subTest(subject=subject, audio=audio):
                    self.assertTrue(verified_setup(config))
                    for stage in ("auto", "prepare", "approve", "design", "animate", "background", "restyle"):
                        require_verified_setup(config, stage)
                    for stage in ("h3", "wan", "wan_speech", "draft", "final", "ltx25_decode"):
                        with self.assertRaisesRegex(ValueError, "stage"):
                            require_verified_setup(config, stage)

    def test_relight_original_audio_stages_are_available(self):
        config = self.config(engine="h3", workflow_mode="relight", prompt="Warm sunset")
        self.assertTrue(verified_setup(config))
        self.assertEqual(config["relight_engine"], "wan21")
        for stage in ("prepare", "design", "create_look", "animate", "wan21_relight"):
            require_verified_setup(config, stage)
        with self.assertRaisesRegex(ValueError, "selected Relight video graph"):
            require_verified_setup(config, "h3")
        # An already-running legacy H3 job can still finish on its own backend.
        legacy = {**config, "relight_engine": "h3"}
        require_verified_setup(legacy, "h3")
        with self.assertRaisesRegex(ValueError, "selected Relight video graph"):
            require_verified_setup(legacy, "wan21_relight")
        self.assertFalse(verified_setup({**config, "audio_id": "voice"}))
        self.assertFalse(verified_setup({**config, "engine": "wan"}))

    def test_masked_engines_and_unqualified_tasks_are_blocked(self):
        for extra in ({"engine": "local"}, {"engine": "seedance"},
                      {"workflow_mode": "motion"},
                      {"mask_method": "text"},
                      {"mask_method": "points"}, {"refine_lips": True, "lip_sync": True, "audio_id": "a" * 32}, {"subject_mode": "objects"}):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "not available in Studio"):
                require_verified_setup(self.config(**extra))

        for extra in ({"subject_mode": "objects"}, {"preserve_people": True},
                      {"audio_id": "a" * 32, "lip_sync": True, "refine_lips": True}):
            with self.subTest(ltx=extra), self.assertRaisesRegex(ValueError, "not available in Studio"):
                require_verified_setup({**self.config(engine="local", workflow_mode="motion"), **extra})

    def test_h3_character_stage_boundaries_with_selected_dialogue(self):
        config = self.config(engine="h3", audio_id="a" * 32, lip_sync=True)
        for stage in ("auto", "prepare", "approve", "design", "animate", "h3", "h3_enhance"):
            require_verified_setup(config, stage)
        for stage in ("wan", "wan_speech", "background", "restyle", "draft", "final"):
            with self.subTest(stage=stage), self.assertRaisesRegex(ValueError, "stage"):
                require_verified_setup(config, stage)

    def test_viewport_routes_and_stage_boundaries(self):
        for engine, stage in (("h3", "h3"),):
            config = self.config(engine=engine, workflow_mode="viewport", edit_area="scene")
            self.assertTrue(verified_setup(config))
            require_verified_setup(config, stage)
            with self.assertRaisesRegex(ValueError, "stage"):
                require_verified_setup(config, "wan_speech")
            for changes in ({"edit_area": "mask"}, {"audio_id": "a"*32}, {"lip_sync": True}):
                self.assertFalse(verified_setup({**config, **changes}))

    def test_ltx_viewport_remains_development_only_until_keyframe_workflow_qualifies(self):
        with self.assertRaisesRegex(ValueError, "not available in Studio"):
            require_verified_setup(self.config(engine="local", workflow_mode="viewport"))

    def test_direct_stage_bypass_is_rejected(self):
        for stage in ("h3", "h3_enhance", "draft", "final", "background", "restyle"):
            with self.subTest(stage=stage), self.assertRaisesRegex(ValueError, "stage"):
                require_verified_setup(self.config(), stage)

    def test_real_http_action_handler_blocks_legacy_projects_before_submission(self):
        async def exercise():
            project = {"id": "saved", "config": self.config(engine="h3", mask_method="points"), "phase": "done", "results": [{"url": "private-local-video"}]}
            original = copy.deepcopy(project)
            controller = types.SimpleNamespace(lock=asyncio.Lock(), start_watcher=lambda: None,
                store=types.SimpleNamespace(load=lambda _: project), action=AsyncMock(return_value=project), collect=lambda p: p)
            server = types.SimpleNamespace(routes=studio.web.RouteTableDef())
            module = types.ModuleType("server")
            module.PromptServer = types.SimpleNamespace(instance=server)
            with patch.dict(sys.modules, {"server": module}), patch.object(studio, "Studio", return_value=controller), patch.object(studio, "public_project", side_effect=lambda p: p):
                studio.register()
                route = next(r for r in server.routes if r.path == "/zura/studio/projects/{identity}/action")
                request = types.SimpleNamespace(headers={}, host="local", match_info={"identity": "saved"}, json=AsyncMock(return_value={"action": "animate"}))
                response = await route.handler(request)
                self.assertEqual(response.status, 400)
                self.assertIn("not available in Studio", json.loads(response.text)["error"])
                controller.action.assert_not_awaited()
                self.assertEqual(project, original, "Never rewrite an old recipe into a different mode")
                get = next(r for r in server.routes if r.path == "/zura/studio/projects/{identity}" and r.method == "GET")
                self.assertEqual((await get.handler(request)).status, 200, "Old results remain readable")
                voice = next(r for r in server.routes if r.path == "/zura/studio/voice" and r.method == "POST")
                self.assertEqual((await voice.handler(request)).status, 400, "Hidden voice creation must not enqueue")
                controller.action.assert_not_awaited()
                for config in (self.config(), self.config(engine="h3", audio_id="a" * 32, lip_sync=True),
                               self.config(engine="local", workflow_mode="motion", subject_mode="people",
                                           audio_id="a" * 32, lip_sync=True)):
                    project["config"] = config
                    self.assertEqual((await route.handler(request)).status, 200)
                    controller.action.assert_awaited_with(project, "animate", {"action": "animate"})
                self.assertEqual(controller.action.await_count, 3)
        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
