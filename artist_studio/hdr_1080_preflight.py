"""Private resource gate for the measured 25-frame 1080p HDR experiment.

This adapter does not change Studio's public pixel/frame limits, start jobs,
inspect devices or cancel other applications. Values must come from fresh,
trusted system and queue measurements immediately before the test submission.
One successful run is not a general 1080p capability or quality guarantee.
"""
from __future__ import annotations

GIB=1024**3
MIB=1024**2
MIN_AVAILABLE_RAM=32*GIB
MIN_TOTAL_VRAM=15_500*MIB
MIN_FREE_VRAM=14_500*MIB
MIN_DISK=10*GIB
CRITICAL_AVAILABLE_RAM=6*GIB


def check_1080_experiment(*, width, height, frames, available_ram, total_vram,
                          free_vram, temp_free, output_free, queue_idle):
    """Fail closed when measurements or the tested configuration differ."""
    if (type(width) is not int or type(height) is not int or (width,height)!=(1920,1080)
            or type(frames) is not int or not 18<=frames<=25):
        raise ValueError('The private 1080p experiment supports only 1920 × 1080 and 18–25 selected frames.')
    if queue_idle is not True:
        raise ValueError('Wait until the target ComfyUI queue is idle before the 1080p HDR test.')
    metrics=(available_ram,total_vram,free_vram,temp_free,output_free)
    if any(type(value) is not int or value<0 for value in metrics):
        raise ValueError('Could not verify current RAM, GPU memory and disk space. The 1080p HDR test was not started.')
    if available_ram<MIN_AVAILABLE_RAM:
        raise ValueError('The 1080p HDR test needs at least 32 GiB of currently available system RAM.')
    if total_vram<MIN_TOTAL_VRAM or free_vram<MIN_FREE_VRAM or free_vram>total_vram:
        raise ValueError('The 1080p HDR test needs a GPU with at least 15,500 MiB total and 14,500 MiB currently free VRAM.')
    if temp_free<MIN_DISK or output_free<MIN_DISK:
        raise ValueError('The 1080p HDR test needs at least 10 GiB free on both temporary and output storage.')
    return {'padded_frames':25,'temporal_window':17,'vae_temporal_size':32,
            'vae_temporal_overlap':8,'experimental':True}


def should_cancel_for_memory(available_ram, *, own_prompt_running):
    """Only signal the caller's own active prompt; never interrupt other jobs."""
    if own_prompt_running is not True:
        return False
    if type(available_ram) is not int or available_ram<0:
        raise ValueError('Current available memory could not be verified.')
    return available_ram<CRITICAL_AVAILABLE_RAM
