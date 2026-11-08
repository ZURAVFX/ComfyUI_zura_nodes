# Release notes

## 1.3.53 - 8 November 2026

- Show completed image edits and images selected from History by clearing the source-view and comparison state as well as closing the paint overlay. Keep the painted selection for further edits.
- Process small painted crops at approximately 1 MP in Auto, while retaining larger native crops within model limits. Restore the final image to the original source dimensions.
- Use CFG 1 for Qwen Image Edit 2511's four-step Lightning recipe, matching ComfyUI's supplied blueprint.
- Show the number of additional reference images beside the paint control.
- Cover result activation, source preservation, Auto crop sizing and Ripple handoff with regression tests. Local Flux 3 and Qwen shot tests confirmed rendering and compositing; replacement quality remains prompt- and model-dependent. Prompts are sent unchanged.

## 1.3.52 - 8 November 2026

- Fix OpenJutsu setup when the finished starting image is supplied as the character image and no separate reference list is present.
- Make Ripple's paint-area editor visible and clearly actionable, and keep it beside the main image before optional references.
- Show the finished image after a painted edit completes, while keeping its paint mask available to reopen.
- Verify the OpenJutsu fix with a live Studio render and add regression coverage for the UI fixes.

## 1.3.51 - 7 November 2026

- Add a dedicated Ripple editing timeline with H3 and LTX, thumbnail keyframes, shared image/video prompts, external image editing and source-matched resolution, frame rate, frame count and audio delivery.
- Preserve edited frames and trim settings when switching Ripple engines. LTX uses one selected edited image as a whole-clip visual reference; H3 supports timed anchors. Adding a keyframe uses the current playhead. Edited thumbnails open a large preview with keyboard dismissal and reduced-motion support.
- Expose **Paint edit area** beside the main image and references in Image editing and Ripple. Native crop-and-stitch processing restores the edit at the original image dimensions and preserves pixels outside the painted selection. Smart Image Crop and Stitch is required for painted edits.
- Integrate P-H3 Image editing with its dedicated image adapter and complete model package. Add full BF16 Klein test options and their shared dependencies. Generation quality and memory use vary by model and still need separate shot testing.
- Add LTX 2.5 crop-based subtitle repair with Zarxrax as the visually approved default and JoyFox as an alternative. Keep source dimensions, timing and audio; short SDR tests completed, with broader shot coverage still outstanding.
- Protect Paintout preview space, fix stale image/model/download responses, and make optional attention acceleration fall back cleanly where unsupported. The old Inpaint picker entry opens Ripple; existing masked-Inpaint data and backend support remain available.
- Package and documentation checks, CPU regressions, frontend tests and isolated browser interaction checks cover this update. No new AI quality generations were run for the final Ripple UI fixes. Non-start LTX visual references still need render-quality comparison; they are not guaranteed timed anchors.

- Start ChatGPT and Gemini sign-in with the system's default supported browser, including Firefox, rather than a fixed Chrome-first order. Preserve explicitly selected browsers for reconnection.
- Read Windows HTTP/HTTPS associations, macOS web handlers and Linux desktop browser settings without opening a browser or reading account data. Keep installed-browser fallbacks when detection is unavailable.

## 1.3.50 - 5 November 2026

- Unify Image and Video layouts, workspace controls and Start over placement. Keep previews usable during setup and generation, with progress below the image.
- Keep dropdowns inside the window, simplify model setup controls and remove repeated headings and unnecessary nested scrolling.
- Add Qwen Image 2.1 and full FLUX.2 dev as local image-edit previews with model downloads and compatible LoRA selection. Generation-quality testing is still outstanding for these new options.
- Correct FLUX.2 Klein 9B edit conditioning. Removed main images and cleared results stay cleared when switching modes.
- Keep Ripple's prompt and mask between stages, expose its processing resolution and retain workflow switching during trimming. Restore multi-frame wording in Paintout.
- Remove ProPainter from Watermark removal and migrate saved selections to LTX. Expand shared resolution controls up to 8.35 MP where supported.
- Validate UI layouts in isolated browser fixtures across four window sizes, including 75 popup checks, plus targeted UI, recipe, download and LoRA regressions. No new GPU generations were run for this release. See the [UI audit](docs/UI_COHESION_AUDIT_2026-11-05.md).


## 1.3.49

- ChatGPT and Gemini sign-in now offer an installed-browser selector in Studio and in their standalone nodes. Chrome, Edge, Brave, Vivaldi, Chromium and Opera use a dedicated sign-in window; Safari uses its macOS session; Firefox works across Windows, macOS and Linux.
- The selected browser opens and supplies the session. Zura no longer opens a default browser while silently checking Firefox.
- Pending sign-ins can be cancelled. Browser switches and cancelled attempts cannot restore an older account connection.
- Safari permission errors explain the macOS setting and offer another browser. Provider cookies stay scoped and outside workflows, logs and status responses.


## 1.3.48 - 5 November 2026

- Add model setup directly to Change camera angle, including the missing MoGe 3 download and all six H3 render files. Only missing files for the chosen mode are downloaded; existing files are reused.
- Check every node in the camera geometry, preview and render graphs before marking setup ready. Explain Panorama installation and ComfyUI updates with a Check setup action after restarting.
- Check access to all selected gated files before beginning large downloads. Show the relevant publisher terms, browser sign-in, account switching and retry controls across Image, Video, HDR and Paintout tools. Publisher approval is still required.
- Keep setup tied to the selected mode, prevent stale catalogue responses from restoring another mode, and cancel a pending install intent when the mode changes during an access check.
- Include geometry models in shared-folder discovery and refresh readiness after completed, cancelled or failed downloads.
- See [setup instructions and validation](docs/STUDIO_1348_VALIDATION.md). GPU output quality and existing experimental-mode limits are unchanged.

## 1.3.47 - 3 November 2026

- Keep edit-source and generated images inside their preview instead of allowing large images to push the controls off-screen.
- Align Image and Video preview widths, toolbar grouping and responsive prompt sizing. Protect attachment/action rows from shrinking and remove conflicting Watermark and Frame Extension page-scrolling rules.
- Keep model management in the top bar, with workflow installation controls shown when models are missing.
- Raise first/last-frame SDR and H3 reference-video resolution controls to an 8.35 MP slider range within the shared 4096-pixel-side / 8,388,608-pixel canvas budget. Actual model and GPU limits still apply; native HDR retains separate limits.
- Preserve decimal megapixel selections and show the actual sampling resolution for LTX Fast and two-stage modes.
- Correct LTX starting-image conditioning to the official in-place I2V approach and use Euler for the refinement pass.
- Rename H3's unanchored Start option to Reference only and explain choosing Picture 1 to preserve its initial composition. This does not guarantee exact text rendering.
- See [validation and remaining limits](docs/STUDIO_1347_VALIDATION.md). The revised layout has code/DOM checks but no final visual sign-off.

## 1.3.46 - 3 November 2026

- Add shared browser sign-in for gated Hugging Face model downloads, with automatic retry, cancellation and a popup-blocked fallback. Read tokens remain an advanced option. Publisher approval is still required.
- Let users select missing starting-image generators and see the matching installation requirements. Keep generation disabled until setup is ready.
- Fix overlapping model-catalogue refreshes and stop abandoned sign-in requests when setup panels close or rebuild.
- Keep HDR trimming visible in the composer, improve download controls in light mode and prevent unrelated workspaces from showing the previous video model's readiness label.
- Improve floating-menu keyboard navigation and add accessible progress labels.
- Validated with 95 frontend suites and 30 backend/model-installation tests, without AI generations. Real-account OAuth approval/download and visual browser sign-off remain pending; see the UI audit.

## 1.3.45 - 3 November 2026

- Fix the shared Start over action in Watermark removal. Save the previous project, clear the clip, masks, optional guide and result, and return to the first step. Add Back to video and protect active renders from accidental resets.
- Keep the watermark preview large while generating. Move progress beneath the picture so stage details never cover the footage.
- Use Blender-style camera navigation in Change camera angle: middle mouse to orbit, Shift + middle mouse to pan, wheel or Ctrl + middle mouse to dolly, Home to frame the scene and I to key all camera properties. Retain native camera interpolation, Undo, locking and the source-view reset.

## 1.3.44 - 3 November 2026

- Share a validated Hugging Face connection across all Studio model installers. Offer optional local credential storage, clear model terms links and retry of missing files after connecting.
- Add token-free browser download and verified streamed import to Image, Video, HDR and the integrated Paintout tools. Reuse the chosen models folder, keep original downloads and reject incorrect or incomplete files without overwriting installed models.
- Fix Watermark removal getting stuck with an empty optional first-frame guide. Choosing Use reference now opens the image picker; cancelling keeps the guide off.
- Use ComfyUI workflow readiness for the model setup banner, so installed models do not trigger contradictory missing-download warnings. Keep genuinely missing extensions and model files separate.

## 1.3.43 - 3 November 2026

- Make the Watermark removal model label a dropdown in the main toolbar. Switch between LTX 2.5 Quality and ProPainter Light without losing source footage, mask layers or the current step.
- Keep the model selector locked during a render and mark ProPainter as SDR-only for HDR footage. Remove the duplicate repair-model selector from Settings.


## 1.3.42 - 3 November 2026

- Improve Watermark removal with clearer static mask layers and an optional clean first-frame guide for Quality mode, including crop and HDR colour handling. Keep guided Paintout separate.
- Share one-click model installation across Image, Video, Paintout and Watermark removal. Show missing download sizes, reuse configured model folders and let users choose a destination from multiple saved folders.
- Offer browser download and verified local import for gated Watermark/Paintout models, without requiring an API token. Publisher sign-in and licence acceptance still apply.
- Distinguish missing extensions from missing model files. Replace the disabled Models ready action with Back to workflow, and avoid opening downloads for extension-only setup.
- Keep the mode selector beside the model across workspaces and stages. Fix the clipped Models menu and model-install button contrast.
- Retain Ripple object replacement, the approved original full-resolution LTX 2.5 SDR outpaint recipe and original-rate Wan 2.1 Relight delivery.

## 1.3.41 - 1 November 2026

- Add Video > Object replacement · Ripple with a guided first-frame mask, replacement-image creation or import, explicit review and original-frame-rate/audio delivery. Reuse Paintout selection tools and expose the Ripple model download package. This mode is SDR and first-frame only; video propagation is maskless and surrounding details may change.
- Keep the Studio-wide interface polish and the approved original full-resolution LTX 2.5 SDR outpaint recipe from 1.3.40.
- Restore legacy route aliases for the new outpaint first-frame and source-info endpoints so existing Studio projects and the Registry compatibility checks remain supported.

## 1.3.40 - 1 November 2026

- Apply the approved Studio interface polish across Image, Video, HDR conversion, Paintout, frame extension, camera controls and shared settings. Use neutral surfaces, consistent Manrope typography, clearer control groups, larger multiline prompts and matching focus and selection states in both themes.
- Give Image editing a dedicated Main image attachment and a separate References disclosure using the Video attachment layout. Keep model, resolution and Settings together below the prompt, with History, Compare and More beside the canvas. Preserve reference order when replacing or removing the main image.
- Include the signed-off original full-resolution SDR outpaint recipe on LTX 2.5. Keep HDR processing separate. Include the latest outpaint delivery, retry and optional first-frame guidance improvements.
- Keep experimental Ripple object replacement outside this stable release. Existing preview routes retain their labels and limitations.

## 1.3.39 - 1 November 2026

- Preserve the original frame rate and selected frame count in Wan 2.1 Relight, including fractional rates such as 29.97. Reload original source frames instead of the 24 fps review proxy, keep the original soundtrack aligned and remove internal model-padding frames from delivery.
- Add ChatGPT and Gemini browser sign-in image generation and editing, including the starting-image stages of video workflows such as Relight. Reuse the existing account nodes, show sign-in beside the prompt and explain website allowance and reference uploads. No paid developer API key is required.
- Keep the original video frame as Image 1 when generating or retrying a starting image. Request its proportions and exact target dimensions, then restore the source dimensions without stretching. Provider output sizes remain best effort.
- Add Image Auto sizing, larger resolution controls, optional Image 1 comparison, image saving and a configurable delivery folder under ZURA STUDIO. Skip unnecessary starting-image processing when a finished frame is supplied.
- Fix completed H3 output recovery when the model pads the frame count, and show clearer image-generation and section progress.
- Include the Panorama camera workspace, simpler camera keyframes, uploaded-source preview, shared reset/navigation and LTX two-stage preview improvements. Existing experimental routes retain their preview labels and restrictions.
- Keep the standalone Paintout contest release separate. New browser starting-image routes have CPU and UI regression coverage; actual provider generation and visual sign-off remain separate checks.

## 1.3.38 - 31 October 2026

- Add the approved Wan Animate 2 full-character masked preview, with a clear Keep original background or Replace character + background choice. Keep native model conditioning, expand and fill block masks, and lock source latents during sampling. No final RGB composite is used.
- Reuse the reviewed source and selection, preserve original audio, hold the final frame to the model grid and export without stretching. The masked route has a real 49-frame Studio GPU integration test; inspect edges and occlusions on new shots.
- Include the current OpenJutsu character workflows, integrated Paintout tools, LTX delivery controls and Studio media, progress and resolution fixes. Experimental features retain their preview labels and restrictions.
- Preserve the public Wan 2.1 Relight fixes and the separately pinned standalone Paintout release workflow.
- Put the displayed canvas image into Image 1 automatically when choosing Edit image, preserving additional references and avoiding duplicate uploads.
- Give prompts more multiline writing space across image, video, paintout and frame extension, with resizing, keyboard focus and improved wrapping on smaller screens.

## 1.3.37 - 30 October 2026

- Fix Wan 2.1 Relight being blocked by the H3 five-second limit and correct the model and resolution labels. Existing relight projects use Wan 2.1 for their next action; running jobs are not changed.
- Use the first frame for a supplied relight image, matching the Wan 2.1 workflow. Verify longer section joins on your own footage.

## 1.3.35 - 27 October 2026

- Add optional FastH3 draft beside normal H3 in Reference to video. Normal H3 remains the default; draft mode clearly warns about softer detail and possible framing/camera changes.
- Use the tested INT8 FastH3 Omni, native Kitchen/VSA attention and SelfLift progressive sampler for image-reference drafts of 56–124 frames (2.33–5.17 seconds). Check optional dependencies independently so normal H3 remains available.
- Show low- and full-resolution sampling phases separately. Reject unsupported audio/video references and first-frame guides with a clear explanation rather than silently changing the input.
- Add live megapixel sizing and editable custom dimensions across Studio image/video controls, respecting each model's grid and pixel budget. Keep relight image and video resolutions independent.
- Allow frame-range and dimension numbers to be selected and replaced before validation, retaining Paintout setup recovery.
- Preserve the Paintout workspace, masking and import fixes from 1.3.32–1.3.34.

Repository maintenance included in this release:

- Simplify the README and add indexed guides and contributor checks.
- Archive the 1.3.24 candidate, label dated scope evidence and correct stale installation/testing version labels.
- Remove the obsolete metadata template; verify runtime dependency manifests match.
- Share package checks between release and repository CI, update GitHub Actions and exclude authoring files from Registry archives.
- Update the PostCSS build dependency to 8.5.31, clear its reported advisories and check frontend builds in CI.

## 1.3.34 - 26 October 2026 (testing release)

- Fix Clean frames showing an unexpanded mask after the authoritative preview arrived with no guide selected. Preview requests now use the displayed expansion value.
- Reject stale decoded mask previews after changing expansion.
- Simplify masking: keep selection, preview and tracking visible; collapse precise range, direction and combine settings under Advanced tracking options. Repair/add-mask actions appear after a mask exists.
- Restore native text selection and editing shortcuts in cleanup instructions and other mask-panel fields, isolated from graph input handling.

## 1.3.33 - 26 October 2026 (testing release)

- Restore visible Zura Studio and Paintout Studio buttons on the graph. Menu commands and optional launcher nodes remain available.
- Fix Add footage and image-sequence import being blocked by a project save before any source is selected. Existing edits are still saved before replacing footage.
- Add regression coverage for first import, cancellation, failed saves and visible launchers.

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
