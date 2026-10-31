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
| First/last frame | Installed normal path; development has a Fast preview using low-resolution sampling and learned latent upscale | Source-only Fast control, not installed; this variant has no second diffusion pass |
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

- [ ] Render an arbitrary-frame object inpainting example and review the
  reference identity, movement, edges and untouched area.
- [ ] Reconcile and test the specific installation differences listed above.
- [ ] Add and time task-specific Fast alternatives, then expose the same
  control only for qualified paths. Preserve Normal recipes.
- [ ] Check the main Studio after restart. The signed outpaint offsets and
  inpainting model catalogue need a backend restart; refreshing alone updates
  only frontend assets. Do not interrupt an active generation to do this.
- [ ] Public release when requested. This local change is not a new release.
