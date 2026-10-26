# Release notes

## Unreleased - Repository maintenance

- Simplify the README and add indexed guides and contributor checks.
- Archive the 1.3.24 candidate, label dated scope evidence and correct stale installation/testing version labels.
- Remove the obsolete metadata template; verify runtime dependency manifests match.
- Share package checks between release and repository CI, update GitHub Actions and exclude authoring files from Registry archives.
- Update the PostCSS build dependency to 8.5.31, clear its reported advisories and check frontend builds in CI.

## 1.3.32 - 26 October 2026 (testing release)

- Integrate the updated Paintout tool into Zura Studio Video > Paintout / clean plate, sharing its working page and controller with the separate contest showcase entry point.
- Add separate Paintout Studio with a guided mask / clean frames / render workspace, interactive trim, hard per-frame painting, custom mask-video import, independent tracking segments and clean-frame masks.
- Show accepted clean-frame mask expansion immediately; preserve separate raw seeds when adding masks and repairing tracking.
- Add menu commands and optional Open Zura Studio / Open Paintout Studio nodes. Remove permanent canvas launch buttons. Existing Studio stays separate.
- Stretch plate, guides and masks to the nearest larger supported 64-pixel processing grid and restore exact source dimensions, rational frame rate and selected frame count. Include model setup and manual-testing notes.
- Testing build: representative shot quality and fresh-machine setup still need artist feedback. Submitted to Comfy Registry for processing; approval and Manager availability remain external checks.


## 1.3.31 - 25 October 2026

- Add guided Studio Paintout / clean plate with source-frame scrubbing, full-resolution paint exports, compact painted-anchor cards and editable original frame numbers.
- Fix FFmpeg 7 dropping high-frame-rate source frames before generation. Expose processing presets, megapixel budgets, custom dimensions and source-resolution padding without resizing. Saved output retains source dimensions.
- Present completed paintout clips in the main viewer and restore them when reopened. Show owned-job submission, queue position, real preparation/export frame counts, sampling steps, stage timing, cancellation and final file/audio saving.
- Add native H3 Reference to Video with image/video/audio inputs, explicit vocal direction and optional Picture 1 first-frame anchoring. Extend native first/last-frame options to Wan 2.2 and LTX 2.5, with supported lengths up to 15 seconds.
- Restore Flux 3 Klein starting-image selection; add independent Klein 9B and Qwen editing options, source-bound regeneration and optional finished lighting images. Add original-versus-modified image comparisons and align previews with the compact composer.
- Include live sample handling, clearer workflow/popover controls and saved reference inputs. Experimental image routes and new GPU quality validation remain documented rather than implied to be artist-approved.


## 1.3.30 - 25 October 2026

- Integrate the LTX 2.5 targeted Obscura anchor paintout and official full-scene Clean Plate workflows into Zura Nodes, preserving existing paintout node IDs.
- Add Windows file browsing, separate video/image-sequence choices, sequence-only frame-rate controls, and painted-frame cards with thumbnails, frame indices and strengths.
- Add matched SDR/HDR working conversions, float32 VAE execution, original-plate compositing, EXR/HLG/SDR delivery, trimmed source audio and motion previews.
- Include two portable example graphs and their model/setup guide in the reviewed template catalogue and Registry package. No media or model weights are bundled.
- Retain the tested INT8, eight-step Euler sampler and memory-bounded native guide-attention path. Smart cropping remains experimental.

## 1.3.29 - 23 October 2026

- Rebuild the prompt composer around left-aligned video/reference attachments, one writing surface and a bottom row for the real model, resolution, clip length, audio and advanced controls. Replace the cramped workflow grid with one selector. Controls and history open over the full-size viewer; light/dark preferences remain saved.
- Add First & last frame using the approved H3 FL2VA INT8 / Turbo 8-step / Kitchen / res_multistep-simple recipe. A first frame is required; the last frame is optional. Audio reference is an explicit switch; switching off retains the upload locally while removing it from the graph and generating native H3 audio. Native 24 fps lengths preserve the last keyframe when supplied. First-only and first/last audio variants pass live ComfyUI schema validation; integration GPU render approval is pending.
- Fix first-frame-only generation being blocked by a mandatory-last-frame check. Add resolution presets and saved custom dimensions, visible setup/input blockers, optional-last-frame removal and direct workflow navigation that preserves drafts. Explicit page visibility prevents inactive workspaces covering navigation.
- Keep one shared workflow selector immediately beside the model in every video composer, including First & last frame. Remove the separate Back to video control. Add standard shapes with a megapixel picker and visible 32-pixel snapping for custom sizes and saved drafts, fixing Generate being blocked by a saved 720px side. Both endpoint images now scale proportionally and crop centrally before H3 encoding, preventing stretched first frames.
- Make first and last frames compact thumbnail tiles with individual corner X controls. Removing either frame keeps the other inputs and settings; ready-state status text is hidden to keep the composer compact.
- Give the current image, video or live sample the main central canvas. Takes, history, view choices and trimming open from the viewer toolbar. Keep a compact prompt and one primary action beneath the canvas, with no document scrolling.
- Keep the approved starting image visible during video generation and after a stopped job. Stopped progress is hidden; recovery messages can be dismissed.
- Replace H3 relight video with the artist-supplied Wan 2.1 chained recipe. Saved H3 relight selections migrate when edited; active jobs are never resubmitted. Klein creates the lighting image for review; H3 models are not required.
- Add Image > Edit image with Qwen Image Edit 2511 (INT8, Lightning 4-step) and FLUX Klein 9B (FP8, native four-step schedule and reference KV cache). Image 1 is the source; later images are references. Both graphs pass live local schema validation; new GPU render approval is pending.
- Accept current and legacy ComfyUI model-option schemas when checking installed models.
- Guide image-to-video generation through Create image, Approve image, then Direct video. Image approval opens video controls without starting a render. Regeneration returns to image review and retains the separate video direction.
- Fix Wan relight's reviewed-source loader receiving a preparation hash instead of the approved shot ID. Source and lighting-image approval checks remain enforced.

## 1.3.28 - 22 October 2026

- Add Wan 2.1 Chained Relight as an alternate to H3. Build and review the lighting frame first, then run the artist-supplied four-step recipe in 81-frame sections at 720p, preserving the source soundtrack. H3 remains available for short relights.
- Simplify the Studio entry point into Image and Video workspaces with the Artify-inspired canvas layout, saved dark/light themes, precise image sizing, native references, prompt-first generation and clearable history.
- Improve Wan relight setup reporting, fixed-recipe controls, graph export and memory handoff from H3 to Wan 2.1. Keep the approved source workflow’s private media and local filenames out of the release.

## Unreleased - Image / Video Studio

- Add saved dark/light appearances using neutral surfaces and Artify-inspired lime accents.
- Add exact image width/height, swap, dimension validation and a memory notice above the tested size.
- Add drag-and-drop native reference conditioning, numbered thumbnails, removal, reordering and explicit per-model limits.
- Add Clear history and Undo without deleting output or reference files.

- Add a simple Image / Video home screen and a charcoal, canvas-first workspace inspired by the supplied Artify reference, retaining Zura's logo and violet accent.
- Add native Flux 3 Klein INT8, Flux 2 Klein 4B FP8 and Z-Image Turbo image generation, each rendered and inspected locally at 1024px on a 16 GB RTX 4080.
- Keep a persistent image prompt and Generate button, local output gallery, downloads, reusable prompts/seeds, targeted cancellation and recovery of an active run.
- Preserve all approved video recipes while moving the primary action beside the prompt and collapsing generation settings and trimming into clear disclosures.
- Add DOM coverage for workspace switching, model readiness, duplicate submission prevention, targeted cancellation, history and failure recovery.

## 1.3.27 - 19 October 2026

- Add a source filmstrip with draggable trim handles, frame-level keyboard adjustments and optional precise timing. Submit the selected range once when a drag ends.
- Keep a main prompt composer at the bottom of the desktop workspace for every generation route, with separate image/video text and a camera prompt that remains visible with uploaded stills.
- Show the changed camera still directly without requiring a mask-review record, and add fullscreen viewing for camera stills and video results.
- Fix Studio jumping downwards and exposing blank space below its panels. Desktop navigation now scrolls only the relevant panel, with focus prevented from scrolling the outer shell.
- Keep the desktop header and stage controls in place, retain mobile page scrolling and clear an old outer scroll offset when reopening Studio on desktop.
- Add navigation regression coverage for panel scrolling, focus, mobile behaviour and desktop reopening.

## 1.3.26 - 19 October 2026

- Integrate the artist-approved H3 CrossView camera recipe: Ref2VA INT8, matching 8-step Turbo adapter, CrossView LoRA at 0.8 and the approved still as the image guide and locked first frame.
- Guide camera changes through Source, Camera still, Review & render and Result. Keep one camera prompt, optional Person / Room references and one clear approval action.
- Fix camera-still regeneration and require an updated still after changing the camera direction. Preserve original performance and audio, with no mask or geometry-warp pass.
- Qualify a two-second 768 × 448, 24 fps local render and add graph-contract and interface regression coverage. Takes up to five seconds remain available but need review for drift.

## 1.3.25 - 18 October 2026

- Reduce Studio handoff overhead with bounded file and project-record caches, responsive graph preparation, and adaptive Comfy memory handoffs.
- Clarify progress across model loading, preparation and sampling, with current-stage estimates.
- Add a preview-only guided H3 camera-angle workflow with still review and original-audio preservation. Angle retention remains experimental.
- Keep the private H3 character-swap experiment and all private test media out of the public release.

## 1.3.24 - 18 October 2026

- Simplified character flow: source and references → starting frame → video settings → result. Tracking and image generation share one action; frame regeneration and selection review remain available.
- Added the separate Wan Animate 2 full-frame character/background integration with setup checks and native distilled sampling. Its local quality/speed remain unqualified.
- Restore approved Wan, H3 and LTX character-performance routes, including original audio, uploaded replacement dialogue and silent footage. Keep rejected viewport routes and unqualified object/lighting modes out of Studio.
- Add the artist-approved H3 Head & face recipe: direct portrait, original audio, eight-step Kitchen sampling and tracked crop compositing, up to two seconds.
- Fix the upload lock caused by rebuilding model-status elements during rendering. Keep busy-state cleanup, responsive large-file uploads, source thumbnails and explicit errors.
- Improve editable graph routing and preserve the current workflow when imports fail. Retain cancellation, reset, progress and source/render comparison.
- Correct H3 temporal padding so head-swap exports keep every selected frame and the original soundtrack.

## Earlier Studio development notes

- Add H3 Relight with a generated lighting frame for review, plus scene transformation with original people protected during sampling.
- Offer H3 viewport references directly alongside generated or supplied finished frames. Correct replacement-audio routing, enhanced-delivery sizing and reference-grid padding.
- Keep candidate visual qualification and known camera-retention limitations documented separately from CPU test results.

- Add a visible H3 sampling-step control, saved with each shot and passed to both native H3 schedulers. Preserve legacy 8/40 defaults and label custom counts unbenchmarked.


- Rebuild Studio around source/look, real preview and shot-settings panels with the user-approved navy/violet styling.
- Make oversized original-length recovery actionable without queuing a render, and expose Cancel run beside live progress.
- Preserve visible native image loaders and their exact file paths when opening an editable graph.
- Explain H3 Fast 8-step versus Detailed 40-step costs, retaining reference detail and explicit quality choices.


- Show native sampling steps, stage progress, elapsed time and measured stage estimates; unknown loading stages remain indeterminate.
- Simplify Studio controls and keep progress below the preview on mobile.
- Add local CPU subject checks and manual People / Objects overrides. Explicit LTX objects use Canny guidance; Wan Animate explains its human-performance requirement.


- Recommend H3 for Viewport to final and select it when entering that mode.
- Remove Wan from viewport choices after the whole-scene quality review;
  preserve its motion-transfer, swap and speech routes.
- Mark LTX viewport quality experimental. Match the official ancestral
  refinement sampler and full-canvas guide encoding, with fresh cache keys.
- H3's viewport example is artist-approved. Wan and LTX's earlier viewport
  integration renders were rejected; successful execution was not approval.
## 1.3.24

- Correct face-crop overlay alignment at every graph zoom. Keep crop drawing active until the artist chooses the mouth tool; preserve the old crop after an accidental click and restore it on cancelled drags. Refuse drawing on an unloaded or out-of-reference video frame.
- Video speech editing now recognises source words with local Parakeet and fills the full phrase automatically. Original selections and changed words have separate visual highlights. Existing drafts survive delayed transcription, refreshes and reference changes.
- Split the first node into Clip and face / Select words views. Added draggable reference IN/OUT, a word waveform zoomed to the reference, and click, drag, Shift-click and keyboard transcript selection. No sampling settings or native graph ports changed.
- Draw the mouth oval directly on the video; reset its size relative to the face crop. Reject dot-sized masks and reference frames outside the effective processing clip before sampling, instead of silently clamping the tracking anchor.
- Qualified CPU tests, live native graph export/reload and neutral selection tracking. Generation quality remains model-dependent; this release does not claim a new voice or lip-sync model qualification.

## 1.3.23

- Keep a confirmed mouth placement when redrawing its face crop. Show the replaced area and guide placement on the actual lips. Reject the old automatic crop guess before sampling.
- Move replacement IN and OUT together, retaining the original selection duration without retiming. Describe original timestamps as an initial selection rather than automatic speech alignment.
- State the experimental LTX 2.5 / Dub-It 2.3 compatibility in the artist controls. A neutral tracked INT8 GPU regression test changed the spoken word and final mouth poses; voice identity across other clips remains unqualified.

## 1.3.22

- Fit portrait and landscape face crops automatically inside the selected detail size. Preserve face proportions with native-resolution padding and remove it before compositing.
- Add 1280 and 1536 pixel detail options alongside 768 and 1024. These are longest-edge limits; the finished video retains its original dimensions.
- Bound long context ranges around the selected words automatically, with valid 8n+1 frame padding and a 241-frame local limit. Keep every selected frame and the original playback speed.
- Display the effective context and padded frame count in the source editor. Preparation was checked on the reported clip at all four detail settings; larger GPU renders remain unqualified.

## 1.3.19

- Save the four-stage LongCat editor with manual IN/OUT selection as the default.
- Clear the example actor dialogue and test cuts from the tracked LTX INT8 template.
- Both dialogue templates remain available through ComfyUI Browse Templates.

## 1.3.18

- Fix OUT handles at the end of audio: a half-millisecond rounding tolerance snaps to the final sample.
- Keep larger out-of-range selections invalid, and pass sample-aligned cuts from the selection editor to the final blend.


## 1.3.17

- Select the original and replacement sections together on two labelled waveforms.
- Separate final audio node with highlighted insert, playback, Download WAV and Update final audio.
- Reuse the retained LongCat take for cut and blend changes; hide stale final previews.
- Refuse final export when automatic selection fails, and retain the combined editor for older workflows.


## 1.3.16

- Adds a direct Download WAV action for successfully blended audio.
- Hides original-reference trim controls when only the additional recording is used.
- Clarifies that changing the take requires Run and shows immediate feedback.
- Recognises the standard Windows Parakeet runtime when LOCALAPPDATA is absent, with clearer launch errors.

## 1.3.13

- Adds **Viewport to final** for turning a grey 3D blockout into a finished
  scene, with an optional mask to limit the changed area.
- Routes the source through each engine's own guidance: LTX 2.5 uses its raw
  layout adapter, MiniMax H3 uses the source as a reference video, and Wan 2.2
  prepares pose guidance.
- LTX preserves the exact selected duration by padding the guide for sampling
  and trimming the decoded result back to the source frame count.
- Supports up to fifteen seconds for LTX Viewport to final. Other LTX Studio
  routes and MiniMax H3 remain limited to five seconds; Wan processes longer
  clips in sections.
- Does not add a blanket Canny or depth pass. In the tested LTX scene, depth
  guidance softened the image and shifted details. The raw layout route stays
  the default; Canny has not been qualified.

Install or update **Zura Nodes** through ComfyUI Manager by searching for
**Zura Nodes** from **ZURAVFX**, then restart ComfyUI. Model weights are separate
downloads. See [the Studio install guide](INSTALL_STUDIO.md) for the exact files
and setup steps.

The three local viewport routes completed five-second, 720p integration runs.
The exact viewport outputs still need separate artist review; they are not
included with the package. No private source media or audio is included.
