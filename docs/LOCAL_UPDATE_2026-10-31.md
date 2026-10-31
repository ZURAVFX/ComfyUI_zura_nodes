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
- Two-stage needs longer visual quality checks and an audio-reference GPU check
  before promoting it beyond preview. No speed gain has been claimed.
- Long HDR sections retain exact duration/audio but temporal joins can remain
  shot-dependent. Existing HDR edge/flicker limitations remain documented.

Local install backup/receipt:
`release-check-1.3.38/panorama-navigation-final-20261031-194443`.
The installed package root entry point was preserved.
