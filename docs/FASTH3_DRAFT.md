# Optional FastH3 draft in Studio

Open **Video → Reference to video**. The preset selector beside MiniMax H3 offers:

- **Normal H3 · 8 steps**: the established accelerated H3 recipe. This remains the default.
- **FastH3 · draft**: progressive sampling for quick image-reference drafts.
- **Quality H3**: the existing full-sampling recipe, with its step control in settings.

FastH3 starts with four low-resolution steps, uses a learned latent upscaler, then finishes with four full-resolution steps. Fine details may be softer and framing or camera movement can change. It is useful for exploring an idea before a normal render. It does not produce an identical image more quickly.

## Current scope

FastH3 draft accepts image references and a text prompt, with output lengths from 56 to 124 frames at 24 fps (2.33–5.17 seconds). It uses Match output reference sizing. The normal resolution controls remain available, subject to the existing 32-pixel grid and H3 pixel limit.

Video/audio references, vocal driving, first-frame guidance and the Viggle checkpoint use normal H3. Studio explains the mismatch before generation if those settings are selected with FastH3. Existing inputs are retained when switching presets. Other shot modes, including masks, camera transfer and first/last frame, retain their approved recipes.

## Local setup

1. Install [ComfyUI SelfLift](https://github.com/facok/comfyui-SelfLift). The tested revision is `835c3cf7919410f71f414688f049c6ca497789d0`.
2. Put `fasth3_omniref_8step_pruned_int8_convrot.safetensors` from [FastH3 Omni Comfy](https://huggingface.co/FastVideo/FastH3-Omni-Comfy) in `models/diffusion_models`.
3. Put `minimax_h3_latent_upscaler_3d_conv_v1_bf16.safetensors` from [the H3 latent upscaler](https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler) in `models/latent_upscale_models`. Shared model folders must be listed in ComfyUI's extra model paths.
4. Use a ComfyUI version with native H3 reference conditioning, Comfy Kitchen and Block Sparse Attention with VSA. The tested core revision is `483dae4326356b81de05d27aca3f433dd323cc25`, with Comfy Kitchen `0.2.39`.
5. Restart ComfyUI, then use **Refresh installed models** in Studio's generation settings.

The existing H3 text encoder and video/audio VAEs are reused. Do not add the older H3 Turbo LoRA to this already distilled checkpoint. Studio checks the new checkpoint, latent upscaler, sampler, scheduler and VSA nodes independently, so a missing FastH3 dependency does not disable normal H3.

The tested recipe uses Euler/beta, guidance 1, video/audio shifts 12/3, spatial scale 0.4 and a transition after step 4. VSA keeps 10% with start/end 0.2/1.0. SelfLift uses rho 0, no high-resolution tiling, and unloads the upscaler before full-resolution sampling. Progress identifies the two sampling stages; its time estimates refer to the active stage.

## Measured performance

On an RTX 4080 16 GB with 64 GB system RAM, at 1344 × 768:

| Output length | Normal H3, 8 steps | FastH3 draft | Less total time |
| --- | ---: | ---: | ---: |
| 2.33 seconds | 48.7 seconds | 31.8 seconds | 35% |
| 5.17 seconds | 127.7 seconds | 68.1 seconds | 47% |

These are individual matched warm runs with one image reference, including decoding and MP4 encoding. Loading, references, hardware and memory pressure affect actual time. They are not universal speed promises. Both pipelines used the same prompt, reference, resolution, frame count and seed. The longer FastH3 result moved into a close-up despite a fixed-camera prompt.

The integrated Studio graph was also submitted to ComfyUI and completed successfully in 46.3 seconds, including the first model load in that process. Its MP4 was verified as 56 frames at 1344 × 768, with H.264 video and AAC audio. Interface tests cover preset persistence, switching back to normal H3, unsupported inputs, dependency checks and progress through both sampling phases.

Keep enough system RAM free. A mixed-checkpoint session under memory pressure was slower than normal H3; restarting the benchmark process released the retained host allocations. The draft option does not restart ComfyUI or interrupt another job to reclaim memory.

The full benchmark, graphs and output comparisons are recorded in the private development backup under `Zura-Nodes/research/2026-10-26-fasth3`.
