# Studio implementation and installation audit

This is a file-level audit of the development checkout and the installed
`comfyui-zura-nodes` package on 31 October 2026. It distinguishes implemented
code, installed code and render qualification. Older checklist completion notes
are not proof that a later selective installation included every file.

## Restored in this change

- **Inpaint · preview** in the main Video workflow selector. This opens the
  shared Paintout workspace in object-addition mode, with selection, object
  references and reference frames tied to their original source-frame IDs.
- The missing inpainting recipe and the matching editor/workspace files.
- Correct model packages for SDR and HDR inpainting. They reuse LTX 2.5,
  its encoders and VAEs, with the official in/outpainting adapter instead of
  the removal-only Remova adapter. The compatible adapter's filename includes
  `2.3`; this does not download an LTX 2.3 base model.
- Package completeness checks now require the integrated inpainting assets.
- Frame-extension footage sizing now spans **5% to 1000%**, with an editable
  percentage and **Fit** at 100%. Larger sources are cropped at the output
  boundary, with the same signed geometry in preview, review and generation.
  Only the visible source area is sampled when enlarged, avoiding oversized
  intermediate images. Panning works for both smaller and larger sources.
  SDR, native HDR canvas preparation and HDR layer export accept this geometry.

Inpainting passed recipe/UI tests and an installed `/object_info` inspection:
no missing nodes, models or required inputs, and no invalid required combo
values. **No inpainting model render was run in this change.** It remains a
preview, not an approved production route. The separate contest Paintout
checkout was not modified.

## LTX two-stage: precise current status

“Two-stage” here means low-resolution diffusion, upscale, then a second
diffusion/refinement pass. Merely upscaling a sampled latent is different.

| LTX workflow | Current implementation | Simple Fast/Normal toggle |
| --- | --- | --- |
| Character/performance | Installed staged pipeline: initial sampling, learned latent upscale, refinement, decode | No common toggle; two-stage is already part of this pipeline |
| Object inpainting | Two-stage recipe restored as a preview: low-resolution sampling, pixel upscale/re-encode, high-resolution refinement, masked blend | No; inherent to this preview recipe; needs a real render check |
| Paintout/clean plate | Existing approved removal recipes | No lower-resolution two-stage alternative implemented |
| First/last frame | Normal, optional Fast (low-resolution sample and learned latent upscale), and optional true Two-stage (sample, upscale and refinement) are installed | Fast and Two-stage are separate, mutually exclusive previews. All three have real matched 49-frame render checks; see `LTX_FRAME_TWO_STAGE_AUDIT.md` |
| Short frame extension: expand canvas | Approved black-video guidance path | No Fast/Normal toggle |
| Black-area extension and longer masked sections | Mask-aware two-stage paths already implemented | No common toggle; preserve the approved short black-guide path |
| HDR processing | Native HDR two-stage code exists behind experimental gates; SDR-to-HDR conversion uses its separate single-stage recipe | No global toggle; HDR conversion is not equivalent to low-resolution generation |

A common **Fast** control is feasible for the LTX routes that have a working
alternative. It must select a real recipe per task, retain anchors/masks/audio
and the output raster, and state the quality tradeoff. It is not integrated
globally and has not been timed globally. Do not expose a toggle that merely
changes a label or promise a speed gain without a matched render.

## Other differences requiring a deliberate follow-up

These were found in development but differ from the installed files. They were
not silently merged as part of restoring inpainting and footage sizing:

- Selective LTX model reuse across compatible sampling/upscale/refinement
  stages (`artist_studio/memory_policy.py` together with `studio.py`). The
  installed version still unloads models at more stage boundaries. This can
  contribute to overhead, but no timing measurement was made in this audit.
- Additional rounded-up frame selection, held-tail and matching audio fixes
  across H3, OpenJutsu, LTX and Wan. Compare the paths individually before
  updating them; the already approved relight fixture does not establish
  coverage of every engine.
- Larger Wan preparation validation and newer cache-key variants in
  `wan_preparation_parts.py`, `wan_preparation_runtime.py` and
  `artist_studio/__init__.py`.
- The pinned Z-Image Turbo model-download package in the shared Studio model
  catalogue. This is a setup-package omission, not a missing generation recipe.
- The first/last-frame Fast preview described above needs matched timing and
  visual checks before promotion or installation.

Source-only HDR outpaint/preflight helpers are research code without a new
approved user route. A missing `browser_image_routes.py` in the installed pack
does **not** mean browser image generation is missing: that installation has
equivalent inline routes and registrations. Preserve those when merging.

## Remaining checks

- [x] Render an arbitrary-frame inpainting diagnostic. The frame-8 balloon
  reference persists through 17 frames. See the engineering results below;
  broader object replacement and occlusion remain unqualified.
- [x] Reconcile and test the specific installation differences listed above.
  Source/installed checks pass; running Python modules still need a restart.
- [x] Time the installed First/Last Fast and Two-stage alternatives against
  warmed Normal. Preserve the accepted recipes and preview labels elsewhere.
- [ ] Check the main Studio after restart. The signed outpaint offsets and
  inpainting model catalogue need a backend restart; refreshing alone updates
  only frontend assets. Do not interrupt an active generation to do this.
- [ ] Public release when requested. This local change is not a new release.

## Follow-up installation and render verification, 31 October evening

The earlier installation-difference list is a snapshot, not the current state:

- Selective model reuse is now installed together with its matching controller
  handoff. The complete nine-test runtime-efficiency suite passes against both
  development and installed modules. Initial preparation, speech boundaries,
  ambiguous records and low-memory conditions still request a complete release.
  Compatible sampler/upscale/refine handoffs keep reusable model objects and
  recheck available memory after waiting. This change has no measured timing
  claim yet.
- The missing pinned Z-Image Turbo package and shared model-download selector
  entry are installed. All 13 download-contract checks and the shared model
  download UI suite pass. Browser-account models remain separate from local
  model downloads.
- First/last Normal, Fast and Two-stage each completed actual production
  49-frame renders with both endpoints and reference audio. The warmed Normal
  and Fast timings were 43.435 and 41.450 seconds at 448 x 768. Fast is only
  modestly quicker here and visibly softer. Two-stage took 57.872 seconds.
  Output dimensions, frame counts, audio alignment and silent extension of a
  short soundtrack passed. These optional alternatives remain previews.

Private installation backup and hashes:
`release-check-1.3.38/memory-handoff-install-20261031-195430`.
The backend files require a normal ComfyUI restart. The running instance has
not been silently hot-reloaded or restarted.

## Installed timing and inpainting follow-up

The installation now includes the audited H3, OpenJutsu and LTX held-tail
contracts, explicit Wan streamed-delivery stride, enlarged Wan preparation
validation and accepted cache variants. Full diffs were checked before copying;
the installed root entry point and its browser-account registration were
preserved. The focused 69-check set passes against both source and installed
modules, and the 13 real-environment Wan preparation checks pass separately.
Panorama routes retain both `/zura/studio/` and legacy `/genj/studio/` aliases.

Inpainting now uses independent low/refinement noise, seed 43/42 at default
seed 42, matching the official two-stage example. A real frame-8 reference
render completed in 82.508 seconds: 17 frames at 24 fps, 1152 x 640 processing,
512 x 288 delivery. First/middle/last frames and target coverage were inspected;
audio correlation was 0.999985 at zero sample lag. Encoded pixels outside the
mask are not bit-exact (8-bit MAE 2.345), so no lossless-plate claim is made.
This is a short object-addition diagnostic, not qualification of all swaps.

Further private backup receipts: `timing-cache-install-20261031-201615` and
`inpaint-noise-install-20261031-201351` under `release-check-1.3.38`.
