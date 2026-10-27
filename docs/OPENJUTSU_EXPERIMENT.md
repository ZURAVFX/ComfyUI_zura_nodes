# OpenJutsu character replacement: local experiment

OpenJutsu is the recommended method for **new full-character shots** in the local
experimental Studio installation. It is not published to the Registry yet.
Saved projects keep their prior H3/Wan/LTX recipes. Relight is unchanged.

Choose one character image or reference sheet and a single clear performer:

- **Keep original background**: use references directly, review the selected
  person, then generate. No image model or starting-frame generation is required.
  Building or uploading a starting frame remains optional.
- **Replace character + background**: create or upload a complete starting frame,
  review its identity, setting and framing, then animate. The native full-frame
  branch disables the edit mask; it does not invert a person mask.

Both choices use eight steps, Comfy Kitchen attention and source audio. Start with
480 tier on a 16 GB card. 768 uses substantially more time and memory. Current
qualification is up to five seconds, one automatically selected person and one
reference sheet, with an optional first-frame scene anchor. Manual/multiple-person
selection, arbitrary object edits, text removal, last-frame anchors and replacement
speech are not claimed by this route. Choose Legacy H3 for its approved dubbing
pipeline, or the existing Wan/LTX routes for their distinct functions.

## Provenance and installation

The graph is the MIT-licensed official
[Comfy OpenJutsu recipe](https://github.com/Comfy-Org/comfy-openjutsu/blob/70ec62df0eda7c58697ea3ac2050588513651583/workflows/swap.api.json),
revision `70ec62df0eda7c58697ea3ac2050588513651583`.
The accompanying `OpenJutsu_LICENSE` preserves its licence. Zura adapts filenames,
trim, seed, prompt, selected tier and result saving. The optional anchor uses the
approved local starting image. The separate GPT Image anchor API used by the web
demo is never called. The benchmark also tests the supported no-anchor branch.

The separately installed runtime is Akatz's GPL-3.0 `h3_character_swap` pack from
`akatz-labs/h3-character-swap-tool`, revision
`0670e4fdf95adf2262caa4b81afed2a9c4ae4b7b`, directory
`worker_nodes/h3_character_swap`. Apply the official OpenJutsu
`build/h3_character_swap.patch` to that directory before installing it in Comfy's
custom_nodes. Do not copy an arbitrary current checkout: the directory has since
moved. This experiment does not vendor or silently install its runtime code.

Exact weights:

- `minimax_h3_ref2va_pruned_int8_convrot.safetensors`
- `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`
- `minimax_h3_video_vae_fp16.safetensors`
- `minimax_h3_audio_vae_fp32.safetensors`
- `h3_character_swap_v1.5.safetensors`
- `minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors`
- `sam3.1_multiplex_fp16.safetensors`

The local setup already contains those weights. The node pack was installed with
the official Windows/PyAV/FFmpeg compatibility patch. No model upgrades or paid
services were required. On this Comfy core, SelectCLIPDevice uses `default` for
the active GPU rather than the web recipe's `gpu:0` string.

## Benchmark protocol

Use source `ZXcxxi65Usk`, source time **00:03–00:08**, 120 frames at 24 fps, and
the user's original `beme.png` sheet. The source is a continuous performance with
mouth movement, hand gestures, a microphone and visible background lettering.
All existing routes receive the same character sheet, source interval and seed
`20261027`. A single locally generated starting image is shared by the existing
routes and the anchored OpenJutsu integration test. The first OpenJutsu run uses
the official no-anchor path. Different native resolution grids and preparation
requirements must be reported explicitly; do not claim a speed win by comparing
different pixel budgets without qualification.

Hardware: RTX 4080 16 GB, 64 GB RAM. Comfy core:
`483dae4326356b81de05d27aca3f433dd323cc25`. Runs are serial on an isolated local
server. Timings include model loading unless explicitly labelled sampling only.
User media, outputs, API history and raw benchmark logs remain outside Git under
`work/openjutsu-benchmark` in the parent development checkout.

The 480 no-anchor run completed in **248.311 seconds**, sampling **150.7 seconds**,
at **512 × 928**, delivering exactly **120 frames / 5 seconds** with source audio.
Peak observed GPU allocation was **15,447 MiB** (whole-device nvidia-smi reading).
These are one-run observations, not an averaged benchmark or a minimum VRAM claim.

The experiment deliberately skips Zura's legacy H3 reference-cache stage: the
upstream controller handles its own VAE → Qwen → diffusion memory hand-offs.
Its original SAM tracking is retained for fidelity to the recipe. A future
optimisation could reuse the reviewed Studio track after a separate equivalence
test; the current integration can therefore perform tracking twice.

## Results and what remains useful

Five-second character comparison on RTX 4080 16 GB (single runs):

| Route | Actual output | Video-stage wall time | Observation |
| --- | --- | --- | --- |
| OpenJutsu, no anchor, 480 tier | 512 × 928 | 4:08 | User selected it as the best character result |
| OpenJutsu, approved anchor, 768 tier | 736 × 1344 | 9:40 | Face/jacket good; source accessory remains; not a clear improvement |
| Legacy H3 | 720 × 1280 | 4:59 | Weaker identity and source outfit leaks; retain dubbing/specialised routes |
| Wan 2.2 | 540 × 960 | 8:06 | Retain precise masks, longer/chunked shots and speech guidance |
| LTX 2.5 | 720 × 1280 | 1:59 | Fastest; full-frame recreation with weaker identity/performance |

Pixel budgets differ, so this is a practical route comparison, not an equal-cost
model benchmark. The initial no-anchor OpenJutsu time includes its SAM/model
loading. The existing Studio video times exclude the shared image and reviewed
selection stages. Cold/warm model states also differ.

The full-frame OpenJutsu background test delivered 512 × 928 / 120 frames / 24 fps
with audio in **186.39 seconds**. The user accepted it **for this preview**. The new
wood studio persists, with good gestures and facial performance. Its generated
anchor widened the framing, so this is not evidence of exact camera preservation.
Artists must check the opening frame before approving it.

The new direct-reference Studio flow was exercised end to end at two seconds:
prepare → approve → animate → automatically collected playable result. It took
**94.20 seconds** from Animate, with no design or duplicate H3-reference stage.
This verifies orchestration; it is not a new five-second quality sign-off.

### Native masking lessons

The upstream masked-regeneration node VAE-encodes source frames as the target
video latent and attaches a native video/audio `noise_mask`. The sampler preserves
outside-mask source latents and fully denoises inside. This is stronger spatial
conditioning than merely supplying a mask/depth image as a reference. It is still
VAE-space preservation, not a promise of identical source RGB pixels. It is a
useful application of H3's native masked sampling, not a new H3 model.

- **Objects, unapproved**: removing the character LoRA and masking the microphone
  preserved the scene but barely replaced it (two-second video: 80.32 seconds).
  A Qwen-edited first-frame anchor produced a gold microphone throughout, but the
  user rejected its movement/stability. Keep these tests out of Studio. Next test:
  a tracked regional crop at higher object pixel density, with source motion
  guidance and native mask conditioning before sampling. Do not apply the
  people-trained Character Swap LoRA blindly to objects.
- **Head-only, unapproved**: a native head mask plus the character LoRA mixed the
  source cap and reference beanie. Retain the already approved regional head/face
  workflow. No replacement or superiority claim is justified.
- **Relight**: intentionally not tested or modified, per the user's request.
- **Viewport and dubbing**: retain their approved specialised pipelines. A
  character-trained adapter is not a replacement for whole-scene blockout rendering
  or audio injection.

Pending before a public release: optional runtime installer/update path, desktop
visual confirmation, a cancellation/retry check with expanded dynamic jobs, more
clips and multiple-person tracking equivalence. Reusing Studio's reviewed mask
instead of independently retracking should be tested before claiming that review
controls the exact native OpenJutsu selection. Longer shots and cuts remain gated.

## Matched character + background comparison

The user then requested Wan Animate 2 against OpenJutsu. Both received the same
source time 00:03-00:06, same character sheet, same accepted wood-studio anchor,
same seed, original source audio, and a 72-frame / 24 fps / three-second output.
The shorter range fits Animate 2's current 81-frame Studio limit.

| Route | Native raster | Video button to final result |
| --- | --- | --- |
| Wan Animate 2 distilled INT8, 10 LCM steps, CPU INT8 pose cache | 464 x 832 | 162.323 s |
| H3 OpenJutsu INT8, Kitchen, Turbo 8 steps, unmasked scene branch | 512 x 928 | 103.023 s |

Single sequential runs, with normal offloading and existing caches, not a
cold-start controlled or averaged benchmark. H3 was about 37% quicker in this run
while rendering more pixels. Do not generalise that speed difference to all shots.
OpenJutsu shows more facial/mouth expression and pushes in towards the performer;
Animate 2 holds the wider approved framing more closely but has less facial
variation. Both retain the new wood studio. Show the side-by-side MP4 for the
user's judgement rather than claiming one always wins.

Artifacts: `work/openjutsu-benchmark/wan2-vs-openjutsu-background.mp4`, per-route
project/result JSON and `background-comparison-summary.json` in the parent checkout.
User rejected the microphone object preview specifically for movement/stability;
it remains excluded from Studio. Background replacement remains accepted only as
a preview. No public release was requested for these changes.
