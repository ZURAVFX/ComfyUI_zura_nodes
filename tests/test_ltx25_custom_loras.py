"""Staged LTX adapters remain bound to both sampler and receipt identities."""
import copy
import tempfile
import unittest

from test_ltx25_native_plan import inputs, plan_module, NativePlanTests
from test_ltx25_viewport_plan import viewport_inputs


class Ltx25CustomLoraTests(unittest.TestCase):
    def adapter(self):
        return {"name": "ltx25_style.safetensors", "strength": .7,
                "pin": {"path": "/models/ltx25_style.safetensors", "size": 120,
                        "mtime_ns": "10", "prefix_sha256": "a" * 64}}

    def test_both_sampling_passes_and_cache_keys_include_adapter(self):
        for factory in (inputs, viewport_inputs):
            project, kwargs = factory()
            baseline = plan_module.build_plan(project, **kwargs)
            loras = [self.adapter()]
            plan = plan_module.build_plan(project, **kwargs, custom_loras=loras)
            self.assertNotEqual(plan["key"], baseline["key"])
            for phase in ("stage1", "refine"):
                graph = plan["phases"][phase]
                self.assertEqual(graph["custom_lora_0"]["inputs"], {
                    "model": ["model", 0], "lora_name": loras[0]["name"], "strength_model": .7})
                # The existing native guide adapter must consume our patched model.
                if "union" in graph:
                    self.assertEqual(graph["union"]["inputs"]["model"], ["custom_lora_0", 0])
                elif "layout_adapter" in graph:
                    self.assertEqual(graph["layout_adapter"]["inputs"]["model"], ["custom_lora_0", 0])
                else:
                    self.assertEqual(graph["guider"]["inputs"]["model"], ["custom_lora_0", 0])
            changed = copy.deepcopy(loras)
            changed[0]["strength"] = .8
            self.assertNotEqual(plan["key"], plan_module.build_plan(project, **kwargs, custom_loras=changed)["key"])
            changed = copy.deepcopy(loras)
            changed[0]["pin"]["mtime_ns"] = "11"
            self.assertNotEqual(plan["key"], plan_module.build_plan(project, **kwargs, custom_loras=changed)["key"])

    def test_previous_plan_receipt_is_rejected_after_adapter_change(self):
        project, kwargs = inputs()
        old = plan_module.build_plan(project, **kwargs)
        updated = plan_module.build_plan(project, **kwargs, custom_loras=[self.adapter()])
        fixture = NativePlanTests()
        with tempfile.TemporaryDirectory() as directory:
            old_receipt = fixture.text_receipt(old, directory)
            with self.assertRaisesRegex(ValueError, "another plan"):
                plan_module.bind_phase(updated, "stage1", {"text": old_receipt},
                                       output_directory=directory, input_directory=directory)

    def test_missing_or_unsafe_pin_is_rejected(self):
        project, kwargs = inputs()
        adapter = self.adapter()
        adapter["pin"].pop("prefix_sha256")
        with self.assertRaisesRegex(ValueError, "pinned"):
            plan_module.build_plan(project, **kwargs, custom_loras=[adapter])


if __name__ == "__main__":
    unittest.main()
