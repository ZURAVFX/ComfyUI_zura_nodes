"""Zura nodes · Zura Wan 2.2 Turbo Switch: choose an explicit model branch.

Wan 2.2 only: the turbo/quality branch ratios (LightX2V at 4-8 steps versus a
full-schedule run) are tuned for Wan 2.2 Animate.  Never loads hidden LoRAs.
Wire the turbo (accelerated) branch and the quality (base) branch in
separately — this node selects one and emits the matching steps/cfg,
overriding the render node's own widget values.
"""
from __future__ import annotations


class ZuraWan22TurboSwitch:
    CATEGORY = "Zura"
    FUNCTION = "select"
    RETURN_TYPES = ("MODEL", "INT", "FLOAT")
    RETURN_NAMES = ("model", "steps", "cfg")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "base_model": ("MODEL", {"lazy": True}),
            "accelerated_model": ("MODEL", {"lazy": True}),
            "turbo": ("BOOLEAN", {"default": True, "label_on": "Turbo (LightX2V)", "label_off": "Quality (40 steps)",
                                  "tooltip": "Turbo runs the accelerated branch at 4-8 steps with cfg 1.0; "
                                             "quality runs the base branch at 40 steps with cfg 5.0. "
                                             "Tuned for Wan 2.2 Animate."}),
            "accelerated_steps": ([4, 6, 8], {"default": 6,
                                              "tooltip": "Steps for the turbo branch. 6 is the tested default; "
                                                         "4 is about a third faster for slightly less edge detail."}),
        }}

    def check_lazy_status(self, turbo=True, base_model=None, accelerated_model=None, **kwargs):
        name = "accelerated_model" if turbo else "base_model"
        return [name] if (accelerated_model if turbo else base_model) is None else []

    def select(self, turbo=True, accelerated_steps=6, base_model=None, accelerated_model=None):
        model = accelerated_model if turbo else base_model
        if model is None:
            raise ValueError("Connect the selected model branch before running.")
        return model, int(accelerated_steps) if turbo else 40, 1.0 if turbo else 5.0


# Class IDs are the workflow contract: these keys are kept from the pack's
# previous name so graphs saved before the Zura rename still load.
NODE_CLASS_MAPPINGS = {"TrendStudioV2Speed": ZuraWan22TurboSwitch}
NODE_DISPLAY_NAME_MAPPINGS = {"TrendStudioV2Speed": "Zura Wan 2.2 Turbo Switch"}
