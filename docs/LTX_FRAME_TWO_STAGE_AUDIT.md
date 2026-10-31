# LTX 2.5 first and last frame two-stage audit

## Source of truth

The branch follows the local Lightricks LTX 2.5 examples:

- `LTX-2.5_T2V_I2V_Two_Stage_Distilled.json`
- `LTX-2.5_A2V_Two_Stage_Distilled.json`

Stage 1 uses the existing INT8 distilled model and schedule:

`1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0`

The latent spatial upscaler then doubles the base canvas. Stage 2 uses the
official short refine schedule:

`0.909375, 0.725, 0.421875, 0.0`

Both samplers use `euler_ancestral` and CFG 1.

## Frontend contract

- Normal mode: existing full-resolution single pass.
- `fast: true`: existing low-resolution single pass, latent upscale, then
  decode. It does not add a refine sampler.
- `twoStage: true`: low-resolution first pass, latent upscale, endpoint
  re-anchoring at final latent size, then the short refine sampler.
- The frontend passes the camel-case `twoStage` field in the recipe config.
- Two-stage defaults off. The label is `Two-stage · preview`.
- Two-stage and Fast are mutually exclusive in the first and last frame UI.

When a requested dimension is on the 32-pixel grid but not the 64-pixel grid,
the graph pads to 64 before halving, upsamples to the padded size, then crops
only the decoded output back to the requested size. Endpoint images are
proportionally fitted and centre cropped before that padding step.

First-frame guides use frame index 0. Last-frame guides use `frames - 1` in
both passes. Stage 2 starts from the unguided text conditioning and re-applies
the endpoint images to the upscaled latent.

Reference audio tokens are encoded and frozen before stage 1. The same noise
mask is applied again to the separated audio latent before stage 2. The
original trimmed waveform is muxed into the result. Generated audio remains
the default when no source audio reference is selected.

## Availability

Two-stage requires these additional nodes:

- `LatentUpscaleModelLoader`
- `LTXVLatentUpsampler`
- `ImagePadForOutpaint`
- `ImageCrop`

It also requires this model:

`ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors`

The existing INT8 transformer, INT8 Gemma encoder, video VAE and audio VAE are
unchanged. This branch does not apply to SDR-to-HDR or native HDR conversion.

## CPU verification

Run:

```powershell
node tests\test_ltx_frame_video_recipes.mjs
```

The test covers normal, Fast and Two-stage graph topology; stage schedules;
first and last frame positions; proportional fitting; 32-grid crop
restoration; audio freezing in both passes; and availability with the
installed ComfyUI model catalog.

## Native GPU smoke test, 31 October 2026

ComfyUI accepted and completed the integrated 46-node two-stage graph with
INT8 LTX 2.5, Kitchen attention, both endpoint images and generated audio.
Output: 768 x 448, 9 frames, 24 fps, 0.375 seconds. Comfy execution timestamps
report 73.902 seconds including model loads. This is an execution check, not a
quality approval or a speed comparison with a warm single-stage render.

Local private receipt: `release-check-1.3.38/ltx-two-stage-validation-job.json`.
No audio-reference GPU test or long-clip quality review was performed here.
