"""Enabled Studio recipes, retaining model-specific preservation boundaries."""

UNAVAILABLE = ("This setup is not available in Studio. Choose character replacement "
               "with Wan or H3, performance recreation with LTX, or Viewport to final "
               "with H3. Saved results are still available.")


def viewport_setup(config):
    return (config.get("workflow_mode") == "viewport"
            and config.get("edit_area") == "scene"
            and config.get("engine") == "h3"
            and not config.get("preserve_people")
            and not config.get("refine_lips")
            and not config.get("audio_id")
            and not config.get("lip_sync"))


def head_swap_setup(config):
    return (bool(config.get("h3_head_swap")) and config.get("engine") == "h3"
            and config.get("workflow_mode") == "swap" and config.get("scope") == "head"
            and config.get("edit_area") == "mask" and config.get("mask_method") == "auto"
            and not any(config.get(k) for k in ("audio_id", "lip_sync", "refine_lips", "preserve_people", "remove_text"))
            and config.get("delivery_mode", "native") == "native")


def verified_setup(config):
    if config.get("engine") == "wan2":
        return (config.get("workflow_mode") == "motion" and config.get("edit_area") == "scene"
                and not any(config.get(k) for k in ("audio_id", "lip_sync", "refine_lips", "preserve_people", "remove_text", "h3_head_swap")))
    if config.get("h3_head_swap"):
        return head_swap_setup(config)
    if viewport_setup(config):
        return True
    if config.get("preserve_people") or config.get("refine_lips"):
        return False
    if (config.get("engine") == "local"
            and config.get("workflow_mode") == "motion"
            and config.get("edit_area") == "scene"
            and config.get("subject_mode", "auto") in ("auto", "people")):
        # The qualified Union/pose route regenerates the complete frame. It
        # must not be advertised or dispatched as precise masked inpainting.
        return True
    return (config.get("engine") in ("wan", "h3")
            and config.get("workflow_mode") == "swap"
            and config.get("edit_area") == "mask"
            and config.get("mask_method") == "auto"
            and config.get("scope") in ("person", "head")
            and config.get("subject_mode", "auto") in ("auto", "people"))


def require_verified_setup(config, stage=None):
    if not verified_setup(config):
        raise ValueError(UNAVAILABLE)
    stages = {"auto", "prepare", "approve", "design", "animate", "create_look"}
    if head_swap_setup(config):
        if stage is not None and stage not in ("auto", "animate", "h3"):
            raise ValueError("Head & face uses your portrait directly. Choose its H3 animation graph.")
        return
    if config.get("engine") == "wan2":
        stages.add("wan2")
        if stage is not None and stage not in stages:
            raise ValueError("Choose the Wan Animate 2 full-frame workflow.")
        return
    stages.update(({"h3"} if viewport_setup(config) else {"h3", "h3_enhance"}) if config["engine"] == "h3" else
                  {"background", "restyle"} if config["engine"] == "local" else
                  {"wan", "wan_speech"})
    if stage is not None and stage not in stages:
        raise ValueError("This stage is not available for the selected Studio task.")
