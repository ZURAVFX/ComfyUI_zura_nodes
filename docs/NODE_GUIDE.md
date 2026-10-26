# Node and workflow guide

Detailed controls for the standalone nodes and example graphs. For Studio, start with the [installation guide](../INSTALL_STUDIO.md) and [artist guide](../ARTIST_STUDIO.md).

## Nodes

| Node | Purpose |
| --- | --- |
| **Zura Load Video** | Uploaded local file, trimmed to start/duration, decoded at 24 fps. Outputs an ordinary `VIDEO` with frames and original audio, and the decoded frames. **Choose local video** uploads and selects the file automatically. Existing files must be inside ComfyUI's input/output/temp folders. Download remote clips yourself before uploading; the legacy URL field no longer fetches videos. |
| **Zura Mask** | Takes **any** `VIDEO` wire, so it works outside the Wan pipeline too. One dropdown for the replacement area — **Whole character**, **Whole head** (hair, forehead and ears, cut at the neck), or **Face only** — plus mask expansion and a **Blockify mask** switch with a free **block size** integer (8–512 px, step 1, KJNodes `BlockifyMask` parity; it delegates to the installed KJNodes node and reproduces its bbox block-grid algorithm exactly as fallback). Inputs: `video`. Outputs: `mask_preview` (red-tinted control video), `masked_footage` (the payload the sampler consumes) and `mask` (the replacement mask itself, as a native `MASK`). |
| **Zura Wan 2.2 Looped Chunks Sampler** | The looped `WanAnimateToVideo` renderer: native `continue_motion` continuation between chunks, hard reset at detected or manual cuts. `steps` and `cfg` are plain widgets the Turbo Switch node can override. Outputs generated frames **and** a finished `VIDEO` with the original audio and exact timing — no separate finish node. |
| **Zura Wan 2.2 Turbo Switch** | Lazy base/accelerated model selector emitting model/steps/cfg. Wan 2.2 specific: turbo runs the accelerated branch at 4–8 steps with cfg 1.0, quality runs the base branch at 40 steps with cfg 5.0. LoRA branches stay visible in the graph (Power LoRA Loaders or similar). |

### Camera and scene controls

| Node | Purpose |
| --- | --- |
| **Zura Klein Look Presets** and **Zura Optional Image Edit** | Simple lighting, background, and environment prompts with a lazy on/off switch. |
| **Zura V3 · Pick camera angles** | Nine visual camera previews, a per-shot timeline, angle choices, optional segment prompts, and a visible Plan/Render switch. |
| **Zura · Clip duration (24 fps)** | A frame-exact short take from 0.5 to 5 seconds, with a four-second default. The simple camera workflow links the decoded frame count to the picker so one camera covers the whole take. |
| **Zura H3 multicam V3** | Generates only selected non-source camera intervals from the original video and reassembles them at the source timing. Other V3 planning and prompt nodes support this workflow. |
| **H3 · Render selected camera angle** | Renders one selected camera still against the original 24 fps performance and speech, and sends the unmodified source audio to the video export. |
| **Clean relight · multicam V4** | Optional Klein start-frame relight and Wan IDV2V motion-guided render, passing through the original source audio. When Look is off, it returns the H3 result without loading the image/video models. |
| **Zura · Match Mouth Motion** and **Zura · Person Motion Control** | Pre-generation control helpers for the V4 relight path. They are not a post-render performer composite. |

Start with [the simple single-camera example](<../workflows/Video - Change Camera (H3).json>)
to change the camera on a short performance. It uses the same local Qwen Edit
2511 four-step camera previews and H3 CrossView-Warp path as the advanced
multicam workflow. The source loads once, is decoded at 24 fps, and supplies
both the performance guide and original speech. Clip duration is 0.5–5 seconds,
with four seconds selected by default.

1. Select your video and clip duration. Leave the picker in **Plan previews** and click ComfyUI **Run** to make the nine previews.
2. Choose one camera in the visual picker. Add an optional movement prompt if needed.
3. Choose **Render video** in the picker, then click ComfyUI **Run** again. H3 renders the selected view and exports it with the original audio.

Both passes run with local model weights and use no Comfy credits. The picker
caches its camera stills, so the render pass reuses them. There is no Gaussian
reconstruction or Qwen Image 2.1 stage in this example. **Delivery shape and size**
crops/resizes the finished frames; it does not change the H3 generation resolution.

The experimental AnyAngle example is no longer bundled in the public templates. Existing saved graphs and node classes remain supported.

For several cuts, use [the advanced multicam example](<../workflows/Video - Multicam (H3 Advanced).json>).
Choose angles and timing in the planning section before enabling the H3
render. Its stage subgraphs keep model setup apart from artist controls.
The examples use `example_performance.mp4` as a placeholder; select your own
input clip after loading either workflow.

The advanced V3/V4 workflow needs a 24 fps source clip, suitable local MiniMax H3,
FLUX.2 Klein, and Wan models and LoRAs, plus its other visible custom-node
dependencies (including CrossViewWarp, VideoHelperSuite, and KJNodes). The
scene-control node uses a person-segmentation YOLO weight in
`models/ultralytics/segm/`; the mouth-control node uses `face-alignment==1.4.1`
and downloads its landmark weights on first use. Model-loading nodes and the
example workflows are bundled, but model weights are not. A
structurally valid graph does not guarantee visual identity or perfect lip
sync; review a short test before processing a full clip. The new-angle still
can drift from the source face; use a modest camera change for the first pass.

Every wire is a standard ComfyUI type except one: `masked_footage` from Zura Mask
into the sampler, which has to carry the pose, face and mask tensors a video
wire cannot. Load Video and Mask speak plain `VIDEO`, the mask is a real `MASK`,
and the reference character goes straight into the sampler's `reference_image`
input from any LoadImage node.

## Example workflow

`workflows/Video - Replace a Character (Wan 2.2).json` is the example
graph titled **Zura Wan 2.2 Character Replacement Workflow (Face, Head, Body or
Full Character Replacement)**, showing all four nodes wired
together, including driving-clip, mask-check and raw-mask preview nodes. The
mask leaves on a native `MASK` slot wired to ComfyUI's own **Preview Mask**.
The graph is a starting point: replace the `example_clip.mp4` and
`example_character.png` placeholders with your own input video and reference
image, and confirm that the named model and LoRA files exist in your ComfyUI
installation before running it.

The example uses **Power Lora Loader (rgthree)** so the two named Wan LoRA
weights remain visible in the graph. Install rgthree-comfy, or replace that
node with an equivalent loader while keeping the model and CLIP connections.
Load it from ComfyUI's Workflows menu (copy it into `user/default/workflows/`)
or open the file directly.

## Fast Animate recipe

The example's accelerated branch uses the Wan2.1 I2V LightX2V adapter at
strength **0.60**, followed by the Wan Animate relighting LoRA at **1.00**.
It excludes the Wan2.2 high-noise I2V LightX2V adapter. The [Wan2.2 project
guidance](https://github.com/Wan-Video/Wan2.2#run-wan-animate) warns that
LoRAs trained on Wan2.2 can behave unexpectedly with Wan-Animate. Kijai's
[Wan Animate example](https://github.com/kijai/ComfyUI-WanVideoWrapper/blob/main/example_workflows/wanvideo_WanAnimate_example_01.json)
also pairs the Wan2.1 I2V LightX2V adapter with the Animate relighting LoRA;
its strengths differ from this workflow's settings. Comfy's [official Animate
template](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_wan2_2_14B_animate.json)
lists the same Wan2.1 LightX2V file as its four-step acceleration adapter.

The Turbo Switch runs this branch at **6 steps, CFG 1.0**. Its detailed
branch uses the base Animate model at **40 steps, CFG 5.0**. These are graph
settings, not a measured speed or quality guarantee. Earlier sweep claims
were removed because they were measured with the now-excluded high-noise
adapter, so they do not establish results for this recipe.

The integrated Zura Studio has a separate native Animate graph and model
stack. Its fast route uses the Wan2.1 LightX2V adapter at **0.60**, while its
relight and realism LoRAs are loaded at **1.00**; do not read the standalone
workflow's BF16 relight choice as the Studio's exact stack.

## How chunk continuation works

This standalone example renders long clips in 41-frame windows; the integrated
Zura Studio uses 81-frame windows. At every chunk border the renderer uses
**native continuation** by default, following a hand-built Wan 2.2 Animate
loop (`continue_motion` → sampler → `trim_image`). The optional **Soft blend**
setting adds a cross-fade between decoded versions of the shared frames:

1. **The previous chunk's real frames are handed over as `continue_motion`.**
   The next chunk's sampling window starts on those exact frames, and the
   source conditioning (pose / face / background / mask) is aligned to the same
   absolute frames, so the model samples motion it has genuinely seen instead of
   inventing a fresh take. A graph loop drops the frames the native node reports
   as `trim_image` because they only repeat output it already emitted. Native
   continuation keeps the predecessor's decoded frames and discards this
   repeated context, avoiding a blend of moving faces.
2. **Soft blend uses a flat-ended Hann cross-fade.** Those shared frames hold
   two renditions of the same absolute frames: the predecessor's real pixels
   and this chunk's rendition of them, produced with those pixels in its
   context. Ramping between them spreads any difference across the zone, but
   disagreement can soften or double moving features. The zone's first
   frame is exactly the predecessor's frame and its last frame is exactly this
   chunk's own continuation, which the following frame continues in the same
   pass.

Continuation is driven by the previous generated pixels. The result still
depends on the source clip, mask, conditioning, model, and sampling settings;
inspect the preview and joins for each render. Use Native continuation when
blending makes mouth detail softer.

`overlap_frames` (default 5, must be 4n+1 and at most half of `chunk_frames`)
is the length of the continuation anchor and, in Soft blend, the cross-fade zone; raise it
to 9 for a tighter hold on fast movement. A full continuation chunk's window is
still exactly `chunk_frames` frames, so the continuation costs no extra sampling.
Every chunk logs `mean |real - rendition|` for the frames it was given
(`continuation_delta`, also in the receipt). A small value indicates similar
decoded context; a large value warrants inspecting the join before adjusting
the overlap or conditioning.

### Shots

`shot_mode` decides where continuation restarts:

- **Continuous** — the whole clip is one shot; every border is a continuation.
- **Detect cuts** — automatic structural cut detection; within a shot chunks
  continue from each other, and at a cut the new shot starts with
  unconditioned frames, so the cut stays a hard cut.
- **Manual cuts** — the same, with frame numbers you type (comma separated).

A sampling window never spans a cut and continuation never reaches back past the
start of its own shot, so a detected or manual cut is always reproduced exactly.
The receipt lists the resolved shot ranges (`shots`) next to the detected `cuts`,
and the progress panel shows which shot and frame range is rendering.

## Files

- `driving_clip.py`, `mask_performer.py`, `render.py`, `speed.py` — the four nodes (Zura Load Video, Zura Mask, Zura Wan 2.2 Looped Chunks Sampler, Zura Wan 2.2 Turbo Switch).
- `media_source.py` — contained local media, 24 fps decode, YouTube source links and local previews (routes `/zura/video_candidates`, `/zura/preview_video`). Remote video fetching is disabled.
- `planning.py`, `cut_detection.py` — frame planner and adaptive cut detector (unchanged from v1).
- `segmentation.py` — CPU YOLO person mask.
- `video.py` — native `VideoFromComponents` assembly with a test fallback.
- `web/` — picker UI and the render progress panel.

### Naming

Class IDs (`TrendStudioV2DrivingClip`, `TrendStudioV2MaskPerformer`,
`TrendStudioV2Render`, `TrendStudioV2Speed`) are the workflow contract, so they
are kept from the pack's pre-Zura name: graphs saved earlier still load and run.
Everything user-visible — display names, node category, wire type, routes and
docs — is Zura.

## Install

Search for **Zura Nodes** in ComfyUI Manager, or clone the
[Zura Nodes repository](https://github.com/ZURAVFX/ComfyUI_zura_nodes)
into `ComfyUI/custom_nodes/ComfyUI_zura_nodes/` and restart ComfyUI. Install
the Python extras from `requirements.txt` into the same Python environment
that runs ComfyUI (`requests`, `yt-dlp`, and `ultralytics`).

Zura Mask also requires the WanAnimate preprocessing custom node:
<https://github.com/kijai/ComfyUI-WanAnimatePreprocess>. It supplies the
`OnnxDetectionModelLoader`, `PoseAndFaceDetection`, and `DrawViTPose` nodes
used for pose and face conditioning. Install it through ComfyUI Manager or
clone it into the same `custom_nodes` directory, then restart ComfyUI.

Put `ffmpeg` and `ffprobe` on the system `PATH`. They are used to decode and
assemble video, including local clips. Node.js must also be available on
`PATH` when using YouTube source discovery, because yt-dlp uses it as a
JavaScript runtime for YouTube extraction. Local clips do not need YouTube or
Node.js.

Place the model files in these standard ComfyUI model directories:

- `ComfyUI/models/ultralytics/segm/person_yolov8m-seg.pt` for the CPU person
  segmentation pass. ComfyUI Impact Subpack can download this file through
  its model installer; the [upstream model file is also available from
  Bingsu's ADetailer repository](https://huggingface.co/Bingsu/adetailer/resolve/main/person_yolov8m-seg.pt).
- `ComfyUI/models/detection/vitpose-l-wholebody.onnx` for ViTPose whole-body
  pose estimation.
- `ComfyUI/models/detection/yolov10m.onnx` for the WanAnimate detector.

The latter two files are the names selected by Zura's preprocessing call and
are loaded from the `detection` directory registered by
ComfyUI-WanAnimatePreprocess. The [YOLO file is in the Wan 2.2 Animate process
checkpoint](https://huggingface.co/Wan-AI/Wan2.2-Animate-14B/blob/main/process_checkpoint/det/yolov10m.onnx),
and the [Large whole-body ViTPose release is linked by the preprocessing
project](https://huggingface.co/JunkyByte/easy_ViTPose/tree/main/onnx/wholebody).
Follow that project's current model instructions if its filenames or locations
change.

The example workflow names the Wan 2.2 Animate UNet, UMT5 text encoder, Wan
VAE, CLIP Vision encoder, and two LoRAs explicitly. Replace those widget
values with the filenames installed in your own model folders. The workflow
also contains user input placeholders as described above.

## Additional workflow

`workflows/Utility - Improve a Prompt (Gemma 4).json` is a compact Gemma 4 prompt
enhancement workflow for everyday use. Its optional image input is the
placeholder `example_reference.png`; no reference image is included in the
node pack. It expects the matching Gemma model and the ComfyUI installation
that provides the prompt-enhancer subgraph used by the workflow.

## Additional workflow examples

The pack also includes three reference workflows with their original graph
layouts preserved:

- `workflows/Reference - Mask and Roto (SAM3).json` — SAM 3 text-prompt
  masking and roto preview.
- `workflows/Reference - Head and Face Swap (H3).json` — MiniMax H3 head and face
  replacement with SAM 3 masking.
- `workflows/Reference - Speedboost Comparison (H3).json` — MiniMax H3 reference
  to video with the supplied speed-boost and LoRA branches.

These files contain placeholder media names only. The source images and videos
used to create them are not bundled or shared. They depend on the ComfyUI and
custom-node packs represented by their node classes, plus the model files named
inside each graph.

### Starting images in node view

- [Build a starting frame](<../workflows/Image - Build a Starting Frame.json>): source opening image, one appearance reference and an editable prompt.
- [Build with three references](<../workflows/Image - Build a Starting Frame (3 References).json>): three separate native image-conditioning inputs.
- [Use a finished frame](<../workflows/Image - Use a Finished Starting Frame.json>): load and preview without generation.

Open the native subgraphs for sampling and model controls. These starting-image
workflows run without a Studio project. For video, Studio's **Graph view** exports
the current model stage with editable native nodes. See [the artist guide](../ARTIST_STUDIO.md#studio-and-graph-view).

In Zura Studio, the shared **Prompt** field is available for every model and
with either starting-image option. It guides LTX, H3, Wan and Seedance, and also
guides the starting image when you build one from references.

Choose **Motion transfer** to rebuild the scene around the source movement, or
**Object swap** to mask a person or object and preserve the rest of the shot.

### Simpler character flow

Upload the video and character references, describe the starting look, then select **Create starting frame**. Tracking runs automatically. Review or regenerate the frame, inspect the selection, then choose video settings and **Generate video**.

**Wan Animate 2** is a separate **Character + background** choice for whole-frame motion transfer. It uses its native distilled recipe, without a spatial mask. This new local integration is setup-gated and not yet visually qualified. See [setup and limits](WAN_ANIMATE2.md).
