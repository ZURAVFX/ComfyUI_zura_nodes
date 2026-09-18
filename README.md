# Zura nodes (ComfyUI_zura_nodes)

A minimal four-node Wan 2.2 Animate pack: drive a source clip, mask the
performer, render it in looped chunks, and pick the model branch. It coexists
with the original `comfyui_trend_studio` pack — class names, wire types and
server routes are separate, so both can stay installed.

## Nodes

| Node | Purpose |
| --- | --- |
| **Zura Load Video** | Local file or direct URL, trimmed to start/duration, decoded at 24 fps. Outputs an ordinary `VIDEO` — frames plus the original audio, understood by any ComfyUI video node — and the decoded frames. **Choose local video** uploads into ComfyUI's input folder and selects the file automatically. |
| **Zura Mask** | Takes **any** `VIDEO` wire, so it works outside the Wan pipeline too. One dropdown for the replacement area — **Whole character**, **Whole head** (hair, forehead and ears, cut at the neck), or **Face only** — plus mask expansion and a **Blockify mask** switch with a free **block size** integer (8–512 px, step 1, KJNodes `BlockifyMask` parity; it delegates to the installed KJNodes node and reproduces its bbox block-grid algorithm exactly as fallback). Inputs: `video`. Outputs: `mask_preview` (red-tinted control video), `masked_footage` (the payload the sampler consumes) and `mask` (the replacement mask itself, as a native `MASK`). |
| **Zura Wan 2.2 Looped Chunks Sampler** | The looped `WanAnimateToVideo` renderer: native `continue_motion` continuation between chunks, hard reset at detected or manual cuts. `steps` and `cfg` are plain widgets the Turbo Switch node can override. Outputs generated frames **and** a finished `VIDEO` with the original audio and exact timing — no separate finish node. |
| **Zura Wan 2.2 Turbo Switch** | Lazy base/accelerated model selector emitting model/steps/cfg. Wan 2.2 specific: turbo runs the accelerated branch at 4–8 steps with cfg 1.0, quality runs the base branch at 40 steps with cfg 5.0. LoRA branches stay visible in the graph (Power LoRA Loaders or similar). |

Every wire is a standard ComfyUI type except one: `masked_footage` from Zura Mask
into the sampler, which has to carry the pose, face and mask tensors a video
wire cannot. Load Video and Mask speak plain `VIDEO`, the mask is a real `MASK`,
and the reference character goes straight into the sampler's `reference_image`
input from any LoadImage node.

## Example workflow

`workflows/Zura_Wan_2.2_Character_Replacement_Workflow.json` is the example
graph titled **Zura Wan 2.2 Character Replacement Workflow (Face, Head, Body or
Full Character Replacement)**, showing all four nodes wired
together, including driving-clip, mask-check and raw-mask preview nodes. The
mask leaves on a native `MASK` slot wired to ComfyUI's own **Preview Mask**.
The graph is a starting point: replace the `example_clip.mp4` and
`example_character.png` placeholders with your own input video and reference
image, and confirm that the named model and LoRA files exist in your ComfyUI
installation before running it.

The example uses **Power Lora Loader (rgthree)** so the three named Wan LoRA
weights remain visible in the graph. Install rgthree-comfy, or replace that
node with an equivalent loader while keeping the model and CLIP connections.
Load it from ComfyUI's Workflows menu (copy it into `user/default/workflows/`)
or open the file directly.

## Recommended LoRA stack

Measured on one 41-frame chunk of real footage, same seed, only the LoRA stack
changed. This is the stack the example ships with:

| LoRA | Strength |
| --- | --- |
| `wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise` | 0.70 |
| `lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16` | 0.60 |
| `wan2.2_animate_14B_relight_lora_bf16` | 1.00 |

**6 steps, cfg 1.0** at these settings (the Turbo Switch node's default). What the sweep
found, in case you want to trade speed for detail:

- The official bf16 relight LoRA beats the resized fp16 conversion: brighter, more
  saturated, no loss of detail, and one less derived file to keep around.
- `Wan14B_RealismBoost` is a taste knob, not a quality knob - it *lowers* measured
  edge detail. The example keeps the row wired but switched off.
- LoRA wiring order makes no measurable difference.
- Step count is the only real speed lever: 4 steps is about a third faster than 6
  for roughly 6% less edge detail. 5 steps buys nothing over either neighbour.

## How chunk continuation works

Long clips render in 41-frame windows. At every chunk border the renderer uses
**native continuation plus a cross-fade**, which is the same mechanism a
hand-built Wan 2.2 Animate loop uses (`continue_motion` → sampler →
`trim_image`):

1. **The previous chunk's real frames are handed over as `continue_motion`.**
   The next chunk's sampling window starts on those exact frames, and the
   source conditioning (pose / face / background / mask) is aligned to the same
   absolute frames, so the model samples motion it has genuinely seen instead of
   inventing a fresh take. A graph loop drops the frames the native node reports
   as `trim_image` because they only repeat output it already emitted; here they
   are kept, because they are the cross-fade partner (step 2).
2. **The join is a flat-ended Hann cross-fade.** Those shared frames now hold
   two renditions of the same absolute frames: the predecessor's real pixels
   and this chunk's rendition of them, produced with those pixels in its
   context. Because the two agree closely by construction, ramping between them
   has almost nothing to hide — but whatever difference remains is spread across
   the whole zone rather than stepping at one frame boundary. The zone's first
   frame is exactly the predecessor's frame and its last frame is exactly this
   chunk's own continuation, which the following frame continues in the same
   pass: neither edge steps.

Because continuation is driven by real pixels, the cross-fade is between two
versions of the same motion and should reduce visible boundary artefacts. The
result still depends on the source clip, mask, conditioning, model, and
sampling settings; inspect the preview and joins for each render.

`overlap_frames` (default 5, must be 4n+1 and at most half of `chunk_frames`)
is the length of both the continuation anchor and the cross-fade zone; raise it
to 9 for a tighter hold on fast movement. A full continuation chunk's window is
still exactly `chunk_frames` frames, so the continuation costs no extra sampling.
Every chunk logs `mean |real - rendition|` for the frames it was given
(`continuation_delta`, also in the receipt) — near zero means a true
continuation; a large value means raise `overlap_frames`.

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
- `media_source.py` — local/URL/download, 24 fps decode, YouTube discovery + preview (routes `/zura/video_candidates`, `/zura/preview_video`).
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
`PATH` when using YouTube discovery or downloads, because yt-dlp uses it as a
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
VAE, CLIP Vision encoder, and three LoRAs explicitly. Replace those widget
values with the filenames installed in your own model folders. The workflow
also contains user input placeholders as described above.

## Updates

Install available releases through ComfyUI Manager and restart ComfyUI.
For contributors and maintainers, [RELEASING.md](RELEASING.md) explains how
GitHub releases are published automatically to the Comfy Registry.

## Licence

Zura Nodes' original code is released under AGPL-3.0-only. See [LICENSE](LICENSE)
and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the KJNodes-derived
component and other upstream dependencies. Model weights are downloaded
separately and retain their own licences.

## Additional workflow

`workflows/Zura_Gemma_4_Prompt_Enhancer.json` is a compact Gemma 4 prompt
enhancement workflow for everyday use. Its optional image input is the
placeholder `example_reference.png`; no reference image is included in the
node pack. It expects the matching Gemma model and the ComfyUI installation
that provides the prompt-enhancer subgraph used by the workflow.
