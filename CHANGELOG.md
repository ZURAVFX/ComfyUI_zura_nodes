# Release notes

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
