# Frame extension recipe

SDR frame extension uses the artist-approved, full-resolution black-video
guidance recipe with LTX 2.5. It uses the LTX 2.5 distilled INT8 convrot
transformer, the `ltx-2.3-22b-ic-lora-outpaint.safetensors` adapter at strength
1, `euler_ancestral_cfg_pp`, CFG 1 and eight manual sigma steps. The adapter's
name refers to its release; no LTX 2.3 base model is required. The source is
placed on the expanded canvas and used as the video guide. The model can
change the original scene as well as fill the empty area.

Both short clips and long-clip sections use this same recipe. Long clips use
overlapping sections, guide each following section with the matching generated
frame from the preceding section, and blend their overlaps. Source cadence and
audio are preserved, with a held final frame where the model requires padding.
Large canvases are processed in bounded sections when needed; their output
resolution is not reduced by the section planner.

The 65-frame 1088 × 1088, 30 fps comparison was approved for its appearance.
For the release, a short production-built sampling graph and an anchored second
section rendered successfully at the same raster and frame rate; assembly
returned 25 frames at 30 fps with audio. These checks establish the graph and
timing, not a guarantee that every scene or transition will look seamless.
HDR frame extension keeps its separate preview pipeline and colour handling.
