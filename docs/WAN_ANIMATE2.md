# Wan Animate 2: character and background

Choose **Character performance → Wan Animate 2 (Character + background)**
to recreate the complete frame from a finished starting look and the source
performer's movement. Generate or upload the starting frame, approve it, then
create the video. The model changes the background too. Use Wan 2.2 instead
when the original background must remain outside a precise performer mask.

This route is visible with a model setup gate. Its native graph and Studio
adapter are CPU tested; a local output has not yet been approved. It is separate
from the approved Wan 2.2 character replacement route.

## Setup

Update ComfyUI to a version containing `WanAnimate2ToVideo` and
`WanAnimate2Cache`. Zura's setup status lists missing nodes and files.
Install these [official Comfy assets](https://huggingface.co/Comfy-Org/Wan-Animate-2/tree/main):

| Folder under `ComfyUI/models` | Filename |
| --- | --- |
| `diffusion_models` | `wan_animate_2_distill_int8_convrot.safetensors` |
| `text_encoders` | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` |
| `clip_vision` | `clip_vision_h.safetensors` |
| `vae` | `Wan2_1_VAE_bf16.safetensors` |

The diffusion checkpoint is approximately 16.65 GB. Model weights are separate
downloads and are never included in the Zura source package. Shared existing
text, vision and VAE weights can be reused.

## Current limits

- Human character and complete background replacement; no spatial mask.
- One approved finished starting frame. Additional look references can be
  consolidated into that frame before animation.
- 5–81 frames at 24 fps: approximately 0.21–3.375 seconds.
- 480p-class output, up to 832 pixels on the long edge and 399,360 pixels total.
  Portrait and square sources retain their aspect ratio on a 16-pixel grid.
- Original performance and source soundtrack. Replacement dialogue, separate
  lip-sync generation, text removal and viewport rendering are not qualified.
- Longer clips and seamless multi-window continuation are future work.

The source is trimmed before conditioning and padded to the temporal model
grid. Generated padding is removed before the original selected soundtrack is
restored. Output appears in the normal Studio takes list and `output/genj/final`.

## Sampling and memory

The adapter follows Comfy's [distilled blueprint](https://github.com/Comfy-Org/workflow_templates/blob/main/blueprints/motion_transfer_wan_animate_2_distilled.json):
10 LCM steps, CFG 1, simple scheduler and shift 5. Pose activations are cached
with `WanAnimate2Cache`, using CPU storage and INT8 cache precision to avoid
holding the pose cache alongside the model in VRAM. This trades system RAM and
transfer overhead for lower VRAM pressure. Local speed and peak memory still
need measurement; do not interpret the setup-ready indicator as a benchmark.
