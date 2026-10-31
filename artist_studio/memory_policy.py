"""Bounded worker handoffs without discarding every reusable model object."""

import math


def release_policy(project, memory=None):
    actions = project.get("actions", [])
    action = actions[-1] if actions else {}
    previous = actions[-2] if len(actions) > 1 else {}
    # Only consecutive sampler, upscale and decode handoffs can reuse a
    # loaded model. Motion preparation can load large pose/guide networks, so
    # even the preceding text -> motion transition remains a full reset.
    # Older or ambiguous project records fail closed to their original reset.
    next_stages = {"ltx25_stage1": "ltx25_upscale",
                   "ltx25_upscale": "ltx25_refine",
                   "ltx25_refine": "ltx25_decode"}
    expected = next_stages.get(previous.get("stage"))
    run = project.get("ltx25_run") or {}
    if not isinstance(run, dict):
        run = {}
    compatible = (action.get("stage") == "ltx25_cleanup" and expected is not None
                  and previous.get("state") == "complete"
                  and previous.get("next_stage") == "ltx25_cleanup"
                  and action.get("next_stage") == expected
                  and run.get("next_phase") == expected.removeprefix("ltx25_"))
    if not compatible:
        return {"unload_models": True, "purge_cache": True, "reason": "large_tensor_boundary"}
    try:
        if memory is None:
            import psutil
            memory = psutil.virtual_memory()
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in (memory.total, memory.available)) or memory.total <= 0 or not 0 <= memory.available <= memory.total:
            raise ValueError("Memory information is invalid")
        reserve = max(8 * 1024**3, memory.total * .12)
        if memory.available < reserve:
            return {"unload_models": True, "purge_cache": True, "reason": "system_memory_pressure"}
    except Exception:
        # psutil can raise platform-specific exceptions while probing memory.
        # A failed probe must never disable the conservative release.
        return {"unload_models": True, "purge_cache": True, "reason": "memory_unavailable"}
    # Comfy's native model loader frees/offloads VRAM on demand. Avoid a
    # forced global offload or graph cache reset at this compatible handoff.
    return {"unload_models": False, "purge_cache": False, "reason": "reuse_model_cache"}
