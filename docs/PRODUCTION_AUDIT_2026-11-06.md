# Studio integration and production audit · 6 November 2026

This pass integrates the installed P-H3 Image editor and audits interaction,
state recovery, responsive layout and model setup. It does not qualify AI
output quality or declare every hardware/plugin combination production-ready.

## Checklist

- [x] Identify the installed P-H3 model and use its publisher's edit recipe.
- [x] Expose P-H3 in Image → Edit image and supported video starting-frame stages.
- [x] Keep the original frame as Image 1, with up to seven additional references.
- [x] Use the dedicated image adapter, encoder, VAE, prompt upsampler and eight-step schedule.
- [x] Validate the graph against the running ComfyUI's native node contracts.
- [x] Include every required file in the one-click model package; reuse installed files.
- [x] Give missing native P-H3 nodes ComfyUI update guidance.
- [x] Preserve original pixels outside reviewed masks at native source dimensions.
- [x] Audit navigation, reset, stale responses, model selection, setup, progress and results.
- [x] Check Image, main Video, first/last frame, references, Paintout, Watermark,
      Ripple, Inpaint, frame extension, Panorama and HDR layout/stage fixtures.
- [x] Run CPU/backend, browser/DOM and package/documentation regressions.
- [ ] Complete the separate AI render-quality and hardware-memory acceptance phase.
- [ ] Qualify a clean team installation, including real gated-provider sign-in and downloads.

## P-H3 integration

The [official P-H3 edit workflow](https://huggingface.co/PrunaAI/P-H3-Image-Comfy/blob/main/workflows/p-h3-image_lora_edit.json)
uses the H3 **FL2VA** diffusion model with the dedicated P-H3 image adapter,
not the reference-video checkpoint. Studio follows its bypass adapter loader,
1/1 sigma shift, ordered image conditioning, prompt expansion and eight-step
manual sigma schedule. Source dimensions align to the 32-pixel model grid;
video opening stages restore the exact original output dimensions afterwards.
P-H3's nested latent does not accept the older image-only latent-noise mask.
The reviewed mask instead controls the final native-resolution composite.

The verified download package includes the base diffusion model, adapter,
text encoder, prompt upsampler and VAE, with pinned revisions, file sizes and
SHA-256 hashes. Existing files are reused. The full BF16 Klein packages now
also include their shared encoder and VAE dependencies for fresh installations.
Custom image-LoRA validation now recognises P-H3's H3 base and Flux 3 Edit.

The camera workflow's local image path remains Flux 3; its picker now shows
only that local recipe and the supported browser methods. It no longer offers
local choices that the camera graph would silently ignore.

## Behaviour fixes

- Create/Edit changes during model refresh no longer restore a model for the old task.
- Delayed frame-extension preview responses cannot overwrite a newly loaded source.
- First-frame guide uploads/imports are discarded after a source, canvas, reset or workspace change.
- Returning from guide generation restores the selected image by file identity, even when history gains a new result.
- Start over recognises HDR preparation as an active operation before a queue job exists.
- Manual-only missing-model setups keep Check setup available after files are installed.
- Switching model packages clears the old gated-download retry intent.
- Old model-folder responses cannot overwrite a newly saved download location.
- A failed model-status refresh no longer reports a successfully saved folder as a failed save.
- Shared preview space is larger during setup/progress; menus and controls remain reachable at smaller sizes.

## Verification and limits

The broad regression pass ran 91 JavaScript suites and 902 reported Python
tests (two skipped), plus package and documentation checks. The two suites
requiring OpenImageIO passed in the installed ComfyUI Python environment.
Focused final checks include the new P-H3 graph, opening-mask restoration,
guide-race, model-selection and setup tests. The new P-H3 and guide-race suites
are included in the release workflow.

The real native TextGenerate input expansion and execute path were checked
with a stub encoder, without loading AI weights. Its flat `sampling_mode: off`
input is correctly expanded by ComfyUI into the nested selector expected at
execution. Live node/file/schema checks passed for P-H3's image and video
opening graphs. No render was submitted by this audit.

The isolated browser audit covers four sizes: 1440 × 900, 1280 × 720,
900 × 700 and 600 × 800. All 75 tested floating menus fit the viewport;
visible controls remain scroll-reachable. Small windows may require workspace
scrolling to preserve preview space. See
[the layout audit](UI_PRODUCTION_LAYOUT_2026-11-06.md) for measurements and
Unslop attribution. Private fixtures, captures and detailed logs stay outside
the release package in the sibling work folders.
