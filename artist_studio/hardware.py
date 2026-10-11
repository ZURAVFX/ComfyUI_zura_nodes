"""Read-only hardware facts and scoped, measured artist guidance."""

def guidance(hardware):
    vram = hardware.get("vram_gib")
    small_gpu = vram is not None and vram < 15.5
    return {
        "wan": {
            "workflow_max_custom_seconds": 30, "original_length_supported": True,
            "start_resolution": 512 if small_gpu else 1280, "start_seconds": 2 if small_gpu else 5,
            "tested": "5 seconds at native 1080p; 23.75 seconds at 720p",
            "reference_speed": "About 25–28 minutes for 5 seconds at native 1080p; preparation and new speech guidance extra",
        },
        "h3": {
            "workflow_max_custom_seconds": 5, "original_length_supported": True,
            "start_resolution": 1280, "start_seconds": 2 if small_gpu else 5,
            "tested": "5 seconds at 720p, enhanced to 1080p; native 1080p unqualified on 16 GB",
            "reference_speed": "About 10 minutes for 5 seconds at Enhanced 1080p; opening design and selection extra",
        },
        "local": {
            "workflow_max_custom_seconds": 5, "original_length_supported": True,
            "start_resolution": 512 if small_gpu else 1280, "start_seconds": 2 if small_gpu else 5,
            "tested": "Whole-scene motion-guided 5-second 1080p Studio run; masked speech remains experimental",
            "reference_speed": "About 3 minutes 23 seconds for 5 seconds at 1080p in the six-phase whole-scene route; opening and selection extra",
        },
        "seedance": {
            "workflow_max_custom_seconds": 30, "original_length_supported": True,
            "start_resolution": 1280, "start_seconds": 5,
            "tested": "Paid service; local VRAM guidance and timings do not apply",
            "reference_speed": "Not benchmarked; depends on the provider queue",
        },
    }


def snapshot():
    hardware = {"device": "Unavailable", "vram_gib": None, "ram_gib": None,
                "available_ram_gib": None, "shared_memory": False}
    try:
        from comfy import model_management, system_memory
        device = model_management.get_torch_device()
        device_type = getattr(device, "type", None)
        hardware["device"] = model_management.get_torch_device_name(device)
        hardware["shared_memory"] = device_type in ("cpu", "mps")
        # CPU/MPS total memory is system RAM, not dedicated GPU VRAM.
        if device_type in ("cuda", "xpu", "npu"):
            hardware["vram_gib"] = round(model_management.get_total_memory(device) / 2**30, 1)
        hardware["ram_gib"] = round(system_memory.virtual_memory_total() / 2**30, 1)
        hardware["available_ram_gib"] = round(system_memory.virtual_memory_available() / 2**30, 1)
    except (ImportError, AttributeError, RuntimeError, OSError, TypeError):
        pass
    return {"hardware": hardware, "model_guidance": guidance(hardware),
            "benchmark_system": "RTX 4080 16 GB VRAM, 64 GB system RAM",
            "benchmark_note": "Measured examples, not a minimum specification or a speed guarantee. Other hardware and masked LTX are unbenchmarked."}
