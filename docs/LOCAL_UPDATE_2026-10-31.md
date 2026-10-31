# Local Studio update, 31 October 2026

This checkpoint is installed locally. It has not been published.

## Included

- Shared **Start over** in the same header position across Image, Video,
  First/last frame, Reference to video, Paintout/Inpaint, Frame extension,
  Convert to HDR and Panorama camera. Clears the current workspace only;
  saved files/history and other workspaces stay available. Active owned jobs
  must stop before their inputs or ownership are cleared.
- Earlier main-video stages are clickable and show the corresponding source
  or image preview. Running jobs and unavailable forward stages remain locked.
- The H3 video-model selector stays visible while choosing a starting image.
- Studio opens to Video. Image, Video and model downloads share the header.
  **Convert to HDR** is a normal video-workflow choice.
- HDR uses the shared timeline trimmer, exact source FPS, precise frame fields
  and automatic bounded SDR sections above the single-window capacity. SDR
  readiness and planning now use the same actual 32-pixel model raster.
- Panorama camera uses the native 3D popout with Apply/Cancel, cached full-video
  MoGe geometry, reviewed warp guidance and the approved H3 CrossView recipe.
- LTX first/last frame offers **Two-stage · preview** in advanced settings,
  default off. It performs low-resolution sampling, latent x2 upscale,
  endpoint re-anchoring and a three-step refine pass. Fast remains separate.

## Two-stage scope

See `LTX_25_TWO_STAGE_MATRIX.md`. Inpaint and native masked outpaint already
have mandatory two-stage recipes, so a misleading off switch is not added.
The accepted black-video canvas-expansion path remains its approved single-stage
preview. SDR-to-HDR conversion has its own single-stage recipe. H3 and Wan do
not acquire LTX-only controls.

## Verification

- HDR chunk planning: 10 tests; native/SDR chunk jobs: 5; service: 9. All pass
  using the actual ComfyUI Python environment, including EXR exports.
- Panorama camera graph: 8 tests; native popout Apply/Cancel DOM checks pass.
- Shared Studio, restart/navigation, reset, trimming, HDR, LTX Fast/two-stage,
  native HDR endpoints and delivery regression suites pass.
- An isolated CPU ComfyUI probe loaded the Panorama routes and graph nodes,
  accepted an upload and built the geometry graph without inference.
- A real 46-node LTX two-stage graph completed on the RTX 4080: 768 x 448,
  9 frames, 24 fps, both endpoints, generated audio. Execution took 73.902
  seconds including model loads. This is a smoke test, not a speed comparison
  or artist quality approval.
- Changed UI detector pass returned no findings. Installed files passed syntax
  checks and were merged with existing installed changes, with backups/hashes.

## Remaining verification

- Restart ComfyUI manually to load the changed backend. Automatic approval
  review blocked the attempted restart; the existing server was left running.
- Native Panorama popout needs visual checking in Comfy Desktop and one fresh
  end-to-end Studio camera render. The supplied approved camera result remains
  recipe quality evidence, not a new integration render.
- First/Last Normal, Fast and Two-stage now have matched 49-frame endpoint
  and audio-reference GPU checks. Warm Normal took 43.435 seconds, Fast 41.450
  and Two-stage 57.872 at 448 x 768. Fast is softer and only 4.6% faster here;
  neither preview is promoted or advertised as universally faster. Longer
  visual qualification remains separate.
- Long HDR sections retain exact duration/audio but temporal joins can remain
  shot-dependent. Existing HDR edge/flicker limitations remain documented.

Local install backup/receipt:
`release-check-1.3.38/panorama-navigation-final-20261031-194443`.
The installed package root entry point was preserved.

## Follow-up checks and installation

- Runtime model reuse is installed: compatible LTX sampling/upscale/refine
  handoffs keep models when memory permits. Initial preparation, speech and
  memory-pressure boundaries retain full cleanup. Nine tests pass against
  both source and installed modules; no end-to-end speed gain is claimed.
- H3/OpenJutsu/LTX held-tail contracts and Wan preparation/cache fixes are
  reconciled with the installed package. The source and installed 69-test
  focused set and 13 real-environment Wan preparation tests pass.
- The missing Z-Image Turbo download package is restored; 13 backend and the
  shared model-download UI checks pass without downloading model files.
- Actual frame-8 inpainting completed in 82.508 seconds, delivering all 17
  source frames and zero-lag original audio. Independent first/refine noise
  follows the official recipe. It remains a preview.

Backups and hashes are in the additional `memory-handoff-install-20261031-195430`,
`inpaint-noise-install-20261031-201351` and `timing-cache-install-20261031-201615`
receipts. These installed Python updates require a normal restart; the root
entry point was preserved. No process was stopped and no release was pushed.

## Matched diagnostic results

The native-HDR masked outpaint and SDR-outpaint-then-HDR graphs both completed
the same 17-frame fixture, with validated 10-bit HLG, ACEScg EXRs and identical
audio. Neither preserves original plate pixels exactly; preview labels and
artist compositing layers remain. See `LTX_HDR_MATCHED_COMPARISON_2026-10-31.md`.

A real three-way microphone diagnostic also completed: local maskless H3, H3
with OpenJutsu native mask conditioning, and LTX inpaint. Different native
frame grids are disclosed. The short outputs do not establish longer stability
or justify promoting object swap; it stays hidden. See
`OBJECT_SWAP_MATCHED_COMPARISON_2026-10-31.md`.

The consolidated receipt verifies all 41 touched installed files against their
latest expected hashes. All 28 standalone Paintout import files remain unchanged.
Evidence is in `consolidated-local-install-20261031.json` and
`standalone-preservation-20261031.json` under `release-check-1.3.38`.

The remaining main-Studio integration check needs the requested manual restart
and desktop visual review. Automatic approval review rejected the attempted
test-server restart; no alternative restart or hot reload was used.
