"""Bounded worker handoffs without discarding every reusable model object."""


def release_policy(project, memory=None):
    actions = project.get("actions", [])
    action = actions[-1] if actions else {}
    previous = actions[-2] if len(actions) > 1 else {}
    # Initial handoff and large frame/guide producers retain their proven
    # full reset. Never weaken Wan's bounded preparation or speech boundary.
    compatible = (action.get("stage") == "ltx25_cleanup"
                  and previous.get("stage") in
                  ("ltx25_text", "ltx25_stage1", "ltx25_upscale", "ltx25_refine")
                  and previous.get("state") == "complete")
    if not compatible:
        return {"purge_cache": True, "reason": "large_tensor_boundary"}
    try:
        if memory is None:
            import psutil
            memory = psutil.virtual_memory()
        reserve = max(8 * 1024**3, memory.total * .12)
        if memory.available < reserve:
            return {"purge_cache": True, "reason": "system_memory_pressure"}
    except (ImportError, AttributeError, OSError):
        return {"purge_cache": True, "reason": "memory_unavailable"}
    # unload_models offloads GPU weights; free_memory additionally resets
    # Comfy's complete execution cache. The native RAM-pressure cache can
    # evict inactive tensors without forcing a model reread from disk here.
    return {"purge_cache": False, "reason": "reuse_model_cache"}
