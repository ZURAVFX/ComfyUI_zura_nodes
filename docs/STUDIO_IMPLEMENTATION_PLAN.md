# Zura Studio: implementation checklist

Goal: preserve the approved character workflows while making the requested media,
generation and viewing controls dependable and easy to discover. Changes are local
until a release is explicitly requested and the relevant flows are verified.

## Object replacement and Wan Animate 2 masks (31 October)

- [x] Audit Kagami against local H3 object replacement and LTX inpaint. It uses
  hosted H3 with prompt/still guidance, not a new native object-mask algorithm.
- [x] Trace Wan 2.1 VACE, Wan 2.2 Animate and Animate 2 conditioning; inspect
  selected community implementations for true spatial-mask support.
- [x] Implement an explicit experimental Zura node for Animate 2 masked source
  conditioning plus optional sampler background locking; eleven CPU tests pass.
- [x] Verify real Comfy conditioning, 36-channel model input layout, mask
  preparation, sampler locking and reference trimming on CPU with test doubles.
- [x] Complete three matched GPU tests and a source VAE round trip. Background
  locking operates at each sample step; spatial conditioning creates a coloured
  fringe and is not visually qualified.
- [x] Add expanded/blockified, hole-filled masks and bounded temporal margins.
  Compare the envelope with official conditioning retained versus modified.
- [x] User approved the full-character sampler-only comparison: “Looks acceptable”.
  Keep the fringe-producing spatial-conditioning ablation disabled.
- [x] Add separate Keep background and Replace background choices for Animate 2.
  The mask route reuses the approved source/mask interval, holds its tail, and
  retains original audio. Head-only and object replacement remain unqualified.
- [x] Complete the actual Studio graph on the GPU: 49 frames, 464×832, 24 fps,
  original audio, 111.73 seconds including preparation through export. Probe
  frame count and dimensions, inspect first/middle/last, and stop the owned server.
- [x] Audit Body Double's latest source/generated mask union, dropout handling,
  alignment and composite. Keep final RGB blending separate from native masking.
- [ ] Compare a Kagami-style local H3 object route with masked H3 and LTX.
  A local adaptation is not a benchmark of Kagami's hosted provider.

See [Object swap and Animate 2 research](OBJECT_SWAP_AND_ANIMATE2_MASK.md).
The approved full-character mask recipe is integrated locally as a preview.
Normal ComfyUI needs a restart to load its node and refreshed interface.
No public release is included in this task.
Split preparation/sampling/decoding allowed actual tests without stopping WSL
or changing native model settings. Baseline, spatial-only and spatial+lock
sampling took 110.49, 109.50 and 108.62 seconds respectively (49 frames,
512×896, fixed seed). Two broader-mask follow-ups are recorded separately.

## Current follow-up: official LTX outpaint, speed and inpaint

- [x] Audit all 17 official LTX 2.5 examples at commit `220e1d45aa0469f518e982102fca4dca92a61862`; record actual active sampling paths rather than assuming every route needs an extra upscale pass.
- [x] Provide an explicit HDR compositing-layer export: original native plate, delivered generated border with straight alpha, and 16-bit matte. Exported the reviewed 41-frame result without inference; installed the five required local files with a backup. Source and installed focused backend suites each pass 100 tests, and the layer UI regression passes. Existing running servers require a restart to register the new endpoint.
- [ ] Compare the existing official native-HDR masked outpaint prototype against the current SDR-guide-then-HDR route using matching source, geometry and duration. Do not claim the official Laplacian blend guarantees untouched plate pixels or removes temporal flicker.
- [ ] Add and time an opt-in lower-resolution Fast path on supported LTX routes. Keep approved Normal recipes; expose only variants with an actual working graph, valid geometry, timing and audio. Explain the detail tradeoff on hover.
- [ ] Add distinct object inpainting using the official in/outpainting adapter and two-stage recipe. Reuse Paintout selection and frame tools without changing the approved removal recipes. Verify arbitrary-frame replacement references in an actual render, separately from structural checks.
- [ ] Check the new flows together in the main Studio before any release or shutdown. The contest standalone must remain unchanged.

Latest local state: the selective compatibility merge is installed with backup
`installed-native-hdr-gated-20261031-071120`. The experimental native-HDR
performance, endpoints and frame-extension code is now carried in the local
package, behind its existing default-off flags. Earlier notes calling those
files source-only describe their previous installation state, not activation.
The normal inline SDR-to-HDR controls and Paintout's existing HDR route remain
available. Installed browser-image registrations and job/setup fixes survive.
All 70 staged frontend suites pass across the run and targeted resolution
rerun, alongside 100 HDR/Paintout/opening and 32 relight/availability tests.
Default desktop/mobile workspaces, native result playback/reopen and actual
HDR black-area review passed on disposable installed-basis servers.

The matched older relight example is now verified in a completed current render.
The initial test stopped at the 12 GiB reserve; a single same-graph retry with
pinned memory and asynchronous offload disabled completed without lowering
that reserve. It took 595.18 seconds at 784 × 1392, with 18.96 GiB minimum free
RAM. This is a reliability result, not evidence that this profile is faster.
The two-section output contains 101 frames at 24 fps (4.208333 seconds),
rounding the selected source up and holding its tail. Audio has zero measured
sample lag at 16 kHz, correlation 0.999948 and a silent final 50 ms; the muxed
audio duration is 4.208 seconds. The older clip's first-pair SIFT/RANSAC affine
anisotropy is -2.900%, versus 0.016% in the current output, with more than
1,000 current inliers. The next two current pairs remain below 0.1%. This
measures width/height distortion; it is distinct from the earlier uniform-scale
or optical-flow figures. The first-two-frame contact sheet was inspected;
the old one-frame stretch is absent in the current comparison. Current crop/
timing regressions passed 128 Python checks (one additional check skipped)
and both UI suites. Evidence: `relight-matched-affine-evidence.json`,
`relight-matched-audio-evidence.json`, `relight-matched-before-after.mp4` and
`verify_relight_matched_geometry.py` under the benchmark folder. This qualifies
the reported fixture and shared contracts, not every possible generated shot.
Native-HDR artist qualification is the remaining broad-checklist gate,
separate from the completed standalone Paintout integration.

31 October integration close-out: Paintout's standalone contest source still
matches all 28 recorded import hashes. The integrated shell, source import,
preview invalidation and all 70 top-level JavaScript suites pass. The installed
pack also passed a fresh desktop/mobile first/last, Paintout and frame-extension
browser check after the setup follow-ups, including HDR readiness and reopen.
No generation or download was submitted by that interface check.

The latest local setup backups are `installed-setup-completion-20261031-061241`
(selectable missing Image models and combined LTX/HDR setup) and
`installed-pose-setup-20261031-062836` (DWPose source links, sizes, destinations
and custom-cache discovery). Pose weights still require an explicit manual
download into ControlNet Aux's cache; the UI explains this rather than offering
an unsupported automatic cache write. LTX's fallback handoff labels now name
the two sampling passes, prompt/guidance preparation and decode, with no invented
percentage or ETA. That change is installed under
`installed-progress-labels-20261031-062426` and passes 11 progress tests.

The native HDR experiments remain source-only and default off. Native video
selection now matches the reviewed SDR guide's FFmpeg seek/CFR policy; all 24
selected frames match at 25, 29.97 and 60 fps with a non-zero trim, alongside
real HLG colour and EXR sequence checks. The long HDR frame-extension path now
uses the short path's seam colour match. Its corrected three-section,
41-frame 1088 x 640 HLG/EXR master is `hdr_outpaint_512ebbec7d374b5fb9f0f7e93da9d464`;
the artist has been asked to review this file, replacing the earlier
feather-only master. Automated edge gradients do not establish visual approval.

The main native HDR workspace also completed the real source-frame flow without
a dummy reference: verified original PQ video, a 0.3-second trim, explicit source
review/approval, selected native appearance frame, then the six LTX phases.
It delivered 17 frames at 512 x 288, 10-bit HLG/BT.2020, 17 ACEScg EXRs and an
audio track matching the selected duration. Preparation took 2.0 seconds and
generation/delivery 78.9 seconds. The source's scene-linear peak is 4.46;
an SDR proxy is not used as its appearance input. This is a short engineering
test on the existing PQ wildlife fixture, not artist approval of appearance or
motion. All 59 combined availability/native-HDR tests pass in one process.
The gated objects/edge route requires verified original HDR bytes; ordinary
SDR object generation stays blocked. Evidence is under
`work/openjutsu-benchmark/native-hdr-video-performance-check`.

Native black-area fill passed real short and two-section GPU engineering
checks: 190 x 130 source geometry is retained through a 192 x 192 model canvas,
the continuation image is padded without resizing, 17 HLG/EXR frames are
delivered, unselected source pixels survive within half-float tolerance, and
held-tail audio is silent. The two-section test uses a deliberately reduced
test capacity and one HDR conversion; it does not qualify all long HDR joins.
These small synthetic-border checks do not establish artist quality or enable
the feature in the installed Studio. Evidence is under
`work/openjutsu-benchmark/hdr-black-gpu-check`.
The source-only black HDR interface also passed a real browser upload, HDR
handoff and HTTP review. The reviewed native source, linear-light black mask,
190 x 130 selection and 192 x 192 internal canvas reached the executed graph;
the approval step remained explicit. The owned CPU test server was stopped.
Its evidence is `work/openjutsu-benchmark/hdr-black-ui-results.json`.

The actual main native-HDR result also passed desktop/mobile playback,
download-link and close/reopen checks without another render or conversion.
Selecting an original HDR source frame now explicitly resets any inherited
Last/custom anchor to frame 1; supplied EXR anchors retain their chosen frame.
The focused anchor regression suites pass. Native-HDR features remain gated.

A shared ProRes preview race is fixed in source and installed Studio. Colour
variants of the same uploaded media share a preview destination, so the proxy
job is now owned by that canonical destination rather than separate asset IDs.
Concurrent original/HDR preview requests therefore have one writer and share
any failure. The six upload/proxy regressions pass, including real ProRes/PCM
conversion. Installed bytes were backed up under
`installed-preview-ownership-20261031-065014` before the selective change.

The remaining checklist gate is native-HDR artist qualification. Workspace
integration, the matched-source opening-frame test and representative
main-workspace progress checks are complete as documented above. Historical
notes below that call workspace entry points or Paintout setup visually
unchecked are superseded by the installed-browser evidence above.

31 October selective installed-delivery follow-up: the updated standalone
Paintout remains integrated inside the main shell and its contest source is
unchanged (28 import hashes checked). The reviewed 33-file overlay was installed
with backup `installed-inline-hdr-20261031-055706`. It preserves installed setup
and job recovery, adds inline SDR-to-HDR output choices to first/last LTX, main
LTX and frame extension, and carries exact fractional selection/held-tail audio
handling through the shared nodes and H3 camera/head adapters. Native HDR
endpoint/performance/outpaint experiments remain excluded from this installation.
The earlier source-only frame-extension note below is historical: its tested
SDR-to-HDR delivery is now installed. Two fresh installed-basis GPU/browser
flows verified actual HLG/EXR masters, audio, final-result presentation and no
duplicate conversion on reopen. Remaining native-HDR and long-clip visual
qualification are separate work; this does not mark the full checklist complete.

31 October setup completion follow-up: actionable node-pack links now cover the
declared whole-scene LTX dependencies and missing built-in Image nodes. The model
catalogue includes both Wan 2.2 first/last FP8 phases, both four-step adapters,
the Wan VAE and shared encoder with pinned sources, sizes and hashes. The four-file
selective patch was installed with a backup under
`installed-shared-setup-20261031-052358`; a fresh installed-pack browser run passed
eight workspace/reopen checks and desktop/mobile setup bounds, without page
errors or generation/download submissions. Third-party node-pack installation
remains user-directed.

31 October frame-extension HDR delivery follow-up (source only): both Expand
canvas and Use black areas now offer SDR, HLG, HLG + EXR or EXR in their composer.
HDR is explicitly an additional conversion pass after the finished SDR render.
Setup is checked first; the server then inspects the actual completed file's
frame count, raster, rate and soundtrack before conversion. Review overlays and
native HDR viewing proxies are rejected. A Windows SaveVideo backslash-folder
mismatch found by the real test was corrected, with six real-media backend
regressions. Owned progress/cancel/recovery and retained SDR downloads are covered;
source or geometry changes clear old HDR results without dropping active work.
Two fresh GPU/browser checks each rendered nine 640 × 512 frames with audio,
then converted to HLG and nine-frame EXR archives in 57.7 and 59.2 seconds total.
FFprobe confirmed 10-bit HLG/BT.2020 and one audio track for both. Reopen submitted
no duplicate job. Final desktop/mobile controls and completed-result layouts
passed without global overflow or page errors; the Impeccable detector reported
no findings. These are short engineering checks, not long-clip or artist colour
qualification. No HDR delivery files from this follow-up were installed or
published. Evidence: `work/openjutsu-benchmark/outpaint-inline-hdr-check`.

31 October setup follow-up: whole-scene LTX with a supplied starting frame no
longer reports SAM3 or image-generation weights as unconditional dependencies.
The model panel can download SAM 3.1 independently, plus the exact Wan 2.2
relight/realism adapters. Preparation disconnects and removes MelBand loader and
sampler nodes when voice pitch processing is off; lazy execution alone did not
prevent Comfy from validating those unused dependencies. Pitch-enabled reviews
retain real separation, and reference-audio selection is unchanged. The focused
preparation, scene, relight, Wan-parts, setup and model-catalogue regression run
passed 107 backend tests. Only these setup changes were selectively installed,
with backups under `installed-setup-reliability-20261031-050357`. The experimental
native HDR paths remain source-only and default off.

31 October submission follow-up: Image, first/last and reference-video runs now
persist exact ownership tokens before submission, recover accepted jobs after a
lost response, block duplicate submission while acceptance is uncertain, and
persist targeted cancellation. Completed results win a cancellation race. The
source passed all 68 top-level JavaScript suites. A selective installed-basis
patch passed four focused suites, excluded the native HDR experiment, and was
installed with SHA verification and a backup under
`owned-jobs-installed-backup-20261031-050742-fccd9d8d`. A fresh installed-pack
browser run passed eight workspace/reopen checks, desktop/mobile setup bounds,
zero page errors and zero render/download requests. The isolated CPU test server
was stopped after the check. This does not add GPU or artist qualification.

31 October native HDR performance experiment: the staged LTX body/edge-guided
planner now has a separate internal HDR adaptation. It reads a caller-verified
EXR appearance reference, uses the full float32 VAE, omits JPEG preprocessing,
resizes in linear ACEScg and emits native HLG/EXR plus an SDR viewing proxy.
Its file, colour and output identities produce separate plan/cache keys, and
SDR receipts are rejected. The approved SDR planner and Studio defaults were
not changed. A real 17-frame, 288 x 512 human-pose test completed all six native
phases with successful provenance checks and source audio. FFprobe confirmed
17 10-bit HLG/BT.2020 frames; all 17 EXRs were finite with ACEScg/AP1 metadata
and extended-range values. The appearance plate was deliberately synthetic
(linearised SDR with increased exposure), so this is engineering evidence,
not camera-HDR, colour-fidelity, identity or motion-quality qualification.
The SDR contact sheet also shows changed appearance/framing; do not promote
this experiment as artist approved. The Union/HDR combination is not an
official LTX recipe. It remains source-only and disabled in Studio by default.
Native main-workspace EXR import, receipt/result collection and UI handoff are
now integrated behind `ZURA_LTX_HDR_PERFORMANCE=1`. A finished EXR keeps its
original verified manifest alongside the display-only PNG; approval includes
both identities and colour interpretation. The runtime pins the full HDR VAE,
rebinds the decode from actual upstream receipts, validates the native files,
and exposes HLG/EXR downloads without a second diffusion conversion. Attempts
to switch this image to SDR, H3, a masked route or an image generator fail
visibly. Ordinary SDR generation retains its existing path.
A real CPU-only browser check uploaded the EXR and created a project, then
replayed the independently revalidated prior GPU result for playback and
download checks at desktop/mobile sizes, without page overflow, errors or
generation submissions. It did not render that newly imported project.
The deliberately restricted server reported its missing DWPose/VHS nodes.
All 67 top-level JavaScript suites and all 86 `test_ltx25*.py` tests pass.
EXR collection now verifies ZIP integrity and decodes every bounded image,
checking its raster, finite pixels and scene-linear ACEScg/AP1 metadata.
The primary and take-card downloads choose the HDR master or EXR archive;
ordinary SDR downloads retain their existing behaviour. An unused EXR in
the supplied-frame slot no longer changes a new Build from references route.
A representative HDR
render and artist review are still required before exposing this by default.
Evidence: `native-hdr-performance-check` in the benchmark folder.
Import/browser evidence: `native-hdr-performance-ui-check`.

A subsequent fresh main-workspace HTTP test completed upload, preparation,
supplied-frame binding, approval, all six native phases and result delivery.
Preparation/binding took 2.04 s and generation/delivery 81.17 s, including loads
and polling. It returned 17 frames at 24 fps, 288 x 512, original audio, native
HLG, 17 validated EXRs and the SDR viewing proxy. No image generation or second
HDR conversion was submitted; the queue was empty. This still used the synthetic
HDR plate, so real-camera HDR and artist qualification remain open. Evidence:
`native-hdr-performance-runtime-check` in the benchmark folder.
The actual stored result also passed desktop/mobile playback, native download
and close/reopen checks without page errors, overflow or another generation.

31 October image setup audit: missing built-in FLUX/Qwen image nodes now link
to ComfyUI updates through the same dependency catalogue as the video and
Paintout workspaces. A real CPU-only browser check deliberately hid FluxKVCache
and verified the guidance at desktop and mobile sizes without page overflow,
errors, generations or downloads. A catalogue size mismatch no longer disables
an otherwise available image recipe: the UI describes an alternate/unverified
local version and still refuses to overwrite it. The installed FLUX VAE's tensor
header accounts for its complete file, but this is not a new compatibility or
quality qualification. Z-Image Turbo now has an explicit downloadable package
for its existing BF16 recipe, with the model, encoder and VAE sizes/hashes pinned
to the publisher revision. No weights were downloaded. All exposed Image recipes
have a package matching their actual graph dependencies. Eleven downloader
tests pass, including non-overwrite/integrity tests and cross-checks against the
JavaScript recipes. These changes are source-only. Evidence and publisher
metadata: `image-node-setup-check` in the benchmark folder.

31 October main LTX delivery follow-up: the performance workspace now offers
SDR, HLG, HLG + EXR and EXR inline in its existing composer. HDR explicitly adds
the same SDR-to-HDR model pass used by first/last delivery. Its preflight merges
HDR dependencies into the existing model setup, preserves the reviewed image,
uses the verified rendered raster, retains the SDR master and resumes the same
accepted job after reopening. A real browser test converted an existing nine-frame
512-square SDR receipt, displayed live steps and the final playable viewing proxy,
and exposed HLG/EXR downloads. Desktop and mobile controls had no page overflow;
reopening did not resubmit. The HLG master and nine EXRs were verified separately.
This does not qualify a new main performance render or native HDR input.
These changes are source-only. Evidence: `main-ltx-hdr-check` in the benchmark
folder; implementation and limits: `LTX_HDR_DEVELOPMENT.md`.

31 October HDR observation follow-up: the shared long-HDR client now keeps one
status request in flight, stops scheduling after a workspace closes, and resumes
the same accepted job on reopening. A terminal result recovered after a lost
submission response is delivered once, without an extra completed-job fetch.
The first/last LTX delivery client uses this explicit resume operation. Four
focused JavaScript suites pass, including delayed responses during close,
repeated reopening, acceptance during closure and completed-request recovery.
These changes are source-only; they do not add native HDR support to the main
LTX performance route or qualify the remaining HDR frame-extension path.

31 October reopen/setup follow-up: temporary Studio closure now retains the
workspace panels and zoom controls instead of disposing them. First/last and
reference-video model setup resumes observation of an existing download; a
single-poll guard prevents competing status loops. The HDR development panel
remains attached on reopen, and frame extension retains its canvas and handlers.
All 64 top-level JavaScript test files pass. A real CPU-only Comfy browser test
on port 8358 covered two close/reopen cycles across five workspaces, including
HDR, with retained controllers/drafts and no generation or download submissions.
The relevant lifecycle fixes were selectively installed with backups. A separate
installed-pack test on port 8359 covered the four installed workspaces and their
setup controls, without adding the unreleased HDR endpoint feature.

Paintout and main Studio now share a dependency-source catalogue. Missing built-in
SAM3/LTX nodes link to ComfyUI updates, Zura-owned helpers to Zura Nodes, and
BlockifyMask to KJNodes. Pinned OpenJutsu runtime/patch guidance is preserved;
unknown requirements remain visible. The installed Paintout model setup was
checked with loaded footage at desktop and mobile sizes. These links do not
automatically install extensions. Evidence is recorded in
`work/openjutsu-benchmark/studio-reopen-check` and
`work/openjutsu-benchmark/studio-reopen-installed-check`.

31 October follow-up: native LTX HDR EXR first/last conditioning is now integrated
behind `ZURA_LTX_HDR_ENDPOINTS=1`, with a graph-derived setup check, original-EXR
asset validation, inline output selection and direct HLG/EXR result delivery.
Real nine-frame browser runs covered first/last and first-only with reference
audio. They verified final playback, 10-bit HLG tags, EXR highlights, duration,
desktop/mobile containment and live pass steps. Generated audio's shorter native
duration is now padded, with a real CPU delivery check confirming matching video
and audio lengths. This remains a bounded, unreleased engineering preview;
the broad HDR checklist item below is still incomplete. Full evidence and limits
are recorded in `LTX_HDR_DEVELOPMENT.md`.

A shared Comfy frontend event mismatch was also fixed: `executing` can be a node
ID string without a prompt ID. Studio now associates it only with an observed
execution-start/progress prompt, preserving job ownership. The real endpoint test
showed model preparation, both sampling passes and saving rather than staying
Queued. The fix covers first/last, reference video, Paintout, frame extension and
the HDR tool. All 63 top-level JavaScript test files pass after the change,
including reference-video cancellation and history. The shared event fix alone
was installed locally with a backup; the native HDR endpoint feature was not.

- [x] Keep H3 OpenJutsu and Wan Animate 2 available for character plus background replacement; retain OpenJutsu's background-preserving route and existing approved workflows.
- [ ] Add LTX-only HDR and SDR processing and delivery following official 2.5 examples. Bounded SDR-to-HDR and HLG-to-HDR previews passed short engineering tests with HLG, EXR and audio. PQ video and ACEScg EXR input passed GPU engineering tests; independently computed PQ/HLG neutral swatches passed ingest and HLG output round-trip checks. Tagged Display-P3/PQ input has independently checked synthetic decoding and colour conversion; unsupported or ambiguous tags are rejected. EXR auto-detection checks every frame. A 121-frame experimental temporal test renders real PQ footage; a 17-frame 1080 × 1920 reference also delivered correctly tagged HLG. Two private SDR-to-HDR GPU tests, with and without a continuation anchor, each rendered a 10-frame synthetic fixture in two sections and delivered ten EXRs and a correctly tagged 10-bit HLG video. An anchored 48-frame real-clip test produced three sections, 48 EXRs and a 10-bit HLG video; source audio cross-correlation measured zero sample lag. Artist review of the joins and longer public workflows remain. HDR previews currently cap runs at 121 frames and often fewer at high resolution. SDR preflight now checks the actual 32-pixel and 8n+1 padding against its software memory budget and reports the frame limit before queuing; for 1920 × 1080 this cap is 17 frames. The HDR panel now requests the limit for the selected source dimensions and displays it before submission, clearly labelled as a software limit rather than a hardware guarantee. When the result dimensions are unknown it does not reuse the source limit.
- [x] Provide an in-app model setup flow showing missing files, dependencies, sizes and download progress, with explicit user initiation. The FLUX.2/3, OpenJutsu, Wan Animate 2 and partial LTX 2.5 packages are implemented; LTX Gemma, clean plate, outpaint, H3 first/last, H3 control, H3 Ref2VA DMD, two head-swap adapters and Wan relight packages are also listed. The newly added primary model and adapter files match installed files by SHA-256; users must review individual source and upstream terms. An installed H3 INT8 VAE uses a different same-named version from the pinned download, so Studio protects it and describes the mismatch without assuming it is broken. Direct setup appears in main video, first/last-frame, reference-video and Paintout workspaces. Main video setup now includes the selected starting-image model where required, and FLUX 3 is present in its downloadable packages; supplied frames and head swaps do not add unnecessary image-model requirements; frame extension reports graph-derived dependencies for short canvas expansion and black-area fill, and separate dependencies for long clips; switching method or duration updates setup. A fresh isolated Comfy instance returned the distinct short and long dependencies and matched its missing files against the download catalogue; the deliberately limited node whitelist reported its missing LTX nodes. This is not a desktop visual check. HDR setup now checks model-file presence and loaded nodes against the selected bounded graph and output, including the full VAE and encoder. It does not certify model contents or hardware capacity. The exact reduced-rank TaoMate adapter is now included with a pinned source and SHA-256 matching the locally approved file. Workspace entry points and Paintout's loaded-source setup have now passed installed desktop/mobile checks. DWPose cache weights have exact manual source links, sizes and destinations, including custom-cache overrides; model-folder packages use the explicit in-app downloader. Third-party node-pack installation remains user-directed. Publisher access and every large package download have not been re-exercised.
- [x] Make ProRes MOV previews playable while retaining the original media for processing; a real isolated-browser test played a synthetic ProRes/PCM MOV via an H.264 proxy while preserving the original file and SHA for processing.
- [x] Find and fix opening-frame aspect changes and duration mismatches. The relight crop paths now match and the UI displays frame-aligned lengths. An exact one-frame shortfall at final mux is held to match the selected duration, with a real FFmpeg 23-to-24-frame test; larger shortfalls still fail visibly. LTX first/last audio now pads short references with silence to the selected video length. A one-second relight GPU test produced 24 frames at 24 fps with aligned original audio and no obvious framing jump. A four-second, two-window relight from 60 fps footage at a non-zero trim produced exactly 96 frames with zero measured soundtrack lag. A separate 23.976 fps, non-zero-trim relight also produced 96 frames and zero measured audio lag; its looped source has discontinuous audio, so it does not establish continuous end-to-end audio coverage. A separate continuous-audio FFmpeg fixture covered the output duration. A 29.97 fps fixture with continuous synthetic audio and a non-zero trim also completed a real four-second relight with 96 video frames and audio covering the duration; the periodic tone is not evidence of exact lip-sync. Wan 2.1 relight validation no longer inherits the unrelated H3 five-second limit; a six-second graph passed the corrected source-selection validation and rendered 144 frames with zero measured audio lag. A 30-second relight rendered 720 frames with zero measured audio lag, although memory use was substantial. The custom-selection limit of 30 seconds is reflected in the interface, while full-source selection remains separate. Real preparation and full-resolution reload tests cover 23.976, 25 and 29.97 fps. Representative real H3, LTX and Wan first/last and H3 reference outputs also matched their requested frame counts. A real OpenJutsu test at a 0.3-second trim exposed a one-frame shortfall: 77 rather than 78 frames for 3.25 seconds. The graph now uses the frame-exact selection node and rejects ranges beyond the source. A repeat produced 78 frames, 3.25 seconds and zero measured source-audio offset. The intermediate is an H.264 CRF 16 clip. On this source, a same-range 78-frame FFmpeg comparison measured 48.89 dB average PSNR against the selected original; this is a compression check, not artist approval of the final generated video. A matching Wan Animate 2 test at a 0.3-second trim also delivered 78 frames and 3.25 seconds with zero measured audio offset. Its source-range validation now rejects requests that would otherwise be silently shortened. Shared Studio preflight and H3 viewport, camera and head-swap adapters now reject custom ranges that extend beyond the available source instead of silently shortening them. A real five-second source passed the common preflight for valid 3.25-second selections across Wan, LTX, H3 and Wan Animate 2; an overlong selection failed in each, and Use source was accepted where the full clip fits the model limit; focused graph tests cover these cases. The head-swap graph also passed its node-schema check against the currently running ComfyUI; this does not replace a new render test. The completed matched-source test and current shared graph regressions close the reported opening/timing case; unseen sources can still require further investigation.
- [x] Implement LTX video outpainting with a simple extension/crop control or existing black-area input, and verify real output with both approaches. The preferred black-guide approach is integrated as a five-second preview and passed a 12-frame real upload-to-render test; Already-black input now uses a reviewed masked fallback: a 12-frame GPU test filled the border and preserved dimensions and audio; a 150-frame guided and feathered masked test preserved audio; the user also approved the full-length preview including all three joins for the optional longer-clip mode; the optional long route, timing, cancellation and production review are implemented and locally installed. The installed interface was visually checked with real footage; full-source selection and the numeric duration were verified. The short workflow also has an interactive trim and source-length option.
- [x] Offer optional compatible installed LoRAs in advanced controls, with model-family validation; do not silently apply incompatible weights. Image, H3, Wan and staged LTX routes have graph tests; starting-frame image generation now has separate LoRA controls and graph coverage. Optional controls now also cover HDR, frame extension, first/last, standard H3 reference video and paintout; Wan 2.2 uses separate phase selectors. Progressive FastH3 supports an experimental optional H3 adapter; real H3 and FastH3 tests confirmed adapter loading, but broad third-party LoRA quality is not guaranteed.
- [x] Support zoom, pan and reset in the main video, image, first/last-frame and reference-video previews; interaction tests cover playback and seeking. Desktop zoom and reset were checked; additional media types still need desktop visual confirmation.
- [x] Confirm FLUX.2 Klein 9B is the image generation default, and investigate face-identity and realistic-skin LoRAs with credible compatibility evidence. FLUX.2 Klein 9B produced a real 512 × 512 render in 12 seconds including model loading. A controlled FLUX.3 Consistency LoRA comparison showed additional skin detail but did not establish better identity; a matched Restore comparison added texture but also altered the face, so neither adapter is a verified identity improvement or enabled by default.
- [x] Run focused automated tests and representative local GPU/UI tests; identify any quality-sensitive feature still requiring artist review and keep unverified modes clearly gated. Evidence includes the updated Paintout backend run (195 passed, two environment skips), 70 top-level staged JavaScript suites, 100 HDR/Paintout/opening and 32 Wan relight/availability checks, actual short HDR endpoint/performance/black-area GPU output, and desktop/mobile workspace, result playback and reopen checks. All 40 selectively installed files match their staged hashes, root browser-node registration is unchanged and all 28 standalone import hashes still match. Native HDR experiments remain default-off pending artist qualification; the matched-source opening-frame retest has also completed, with its evidence described above.

- [x] Show clear, truthful progress across exposed modes, with current-stage/loading/step information or measured pass estimates, targeted cancellation and result recovery. This does not promise a precise total render time. Event routing and stage labels were fixed for frame extension and HDR, and sampler labels clarified for image, first/last and reference video. HDR now retains an active job through transient connection errors and keeps controls disabled until cancellation is confirmed. Image and video model-download panels now reconnect to the same job after a temporary status error instead of falsely declaring it failed; simulated tests confirm no duplicate download is submitted. The model catalogue also exposes the active job so both panels can reconnect after reopening; backend and UI tests cover this without starting a second download. The private long-HDR coordinator reports stage, completed sections and its active prompt, routes sampler events to the requesting Studio client, and waits for its own prompt to leave the queue before declaring cancellation. Simulated queue tests cover running and unrelated prompts, and an isolated three-section GPU test interrupted its second section, reached cancelled with an empty queue and published no partial output. Custom LTX LoRAs are validated before a long run and applied to each section in graph tests. Frame extension also waits for its active prompt to leave the queue before reporting cancellation; an installed multi-window test confirmed this. Image, first/last and paintout recheck completion history when a job disappears between status requests, preventing the finished result from being missed. UI tests pass; live websocket progress was observed in isolated Comfy, alongside representative first/last, frame-extension and main LTX runs. Installed desktop/mobile reopen checks verify retained state without submitting a second run. Paintout cancellation now disables its button while pending, persists that intent across reopen, and allows retry if stopping cannot be confirmed. The full native-HDR result check verifies playback and reopening, rather than live desktop progress; native-HDR artist quality remains separate.

Completion means each exposed control changes the actual rendered result, preserves
existing approved paths, and has truthful limits and actionable errors. Maintain
notes on unsupported model capabilities rather than claiming generic HDR, LoRA or
duration support without evidence.

The first/last-frame workspace now includes an LTX-only output selector in the
main composer: SDR, HLG, HLG + EXR or EXR. Selecting HDR runs the existing LTX
conversion automatically after generation in the same workspace. It checks HDR
dependencies before generating, retains the SDR master, reports conversion
progress and provides final master/archive links with an explicitly SDR preview.
Recovery keys are isolated from the separate HDR importer. Interface tests cover
setup failures, reconnect without duplicate submission, authoritative cancellation,
progress ownership and final-result display. A real browser run completed nine
512 × 512 frames through generation and HDR/EXR delivery in 54.3 seconds; FFprobe
confirmed nine 10-bit HLG frames and the archive contains nine EXRs. Desktop and
390 px mobile layout checks passed without global overflow. This is engineering
evidence for the automatic SDR-to-HDR pass, not native HDR endpoint conditioning
or artist acceptance. HDR remains hidden for H3/Wan. A separate convert action is
retained for older LTX SDR takes. Native HDR input and the remaining LTX generation
routes remain outstanding; these new first/last controls are not yet installed
or released. Evidence is in `work/openjutsu-benchmark/ltx-inline-hdr-check`.

When HDR conversion is opened from paintout, a completed HLG video can now be
loaded directly into paintout without downloading and re-uploading it. The
server resolves only an existing output video and checks its HDR colour tags;
a failed handoff leaves the current paintout source intact. UI and backend
contract tests pass. A route test also loads an actual tagged HLG video and
rejects a tagged SDR video and path traversal; the complete desktop
interaction remains to check.

HDR setup now checks the actual continuation and staging nodes when the longer
preview is selected, and links missing Zura or core ComfyUI nodes to their
respective projects. Unit and interface tests cover switching between short and
long setup. The server now rejects an incomplete long setup before creating a
job, and reports the missing files and nodes; a test confirms no job is queued.
The current long-graph preflight was also checked read-only against the separate
8331 ComfyUI instance: its installed node inventory and reported model files
satisfy both SDR-to-HDR and native-HDR continuation graphs. This is a setup
check only, not a new render or an update to the running instance.
The shared video model setup now prevents double submissions while a download
request is pending. If the start response is lost it checks for the active job
and reconnects; when offline it offers a status check before retrying. Simulated
connection-loss and double-click tests pass.
The image-model setup also reconnects if the start response is lost, and
blocks duplicate submissions while checking. Its simulated connection-loss
and repeated-click tests pass alongside the video setup tests.
Frame extension now identifies the second sampling pass and its decode,
reports sampler steps, and estimates the remaining time for the active pass
once multiple steps have completed. The section number remains visible; a
workspace test checks that polling does not erase the estimate.
HDR sampler progress likewise estimates the current pass from observed step
times, alongside the active section. Changing HDR output now refreshes its
setup check even if the setup panel is closed. Both behaviours have interface
tests; the estimate is not a prediction for the complete multi-section job.
After these changes, focused local UI tests passed for HDR, image and video
model setup, frame extension, paintout handoff, resolution and clip length.
CPU/backend suites also passed for HDR readiness, long jobs, source metadata,
HDR extension canvas, output handoff and Wan 2.1 relight. These are regression
checks, not a fresh model render or a desktop visual review.
The integrated paintout workspace now keeps cancellation visible and disables
repeat cancellation until its own prompt leaves the queue or completes. Late
sampling events cannot replace the cancellation status. A simulated queue test
confirms that an already completed result is still shown if completion wins
the race; no fresh GPU cancellation was run for this UI change.
If paintout loses the response after sending a graph, it searches the queue and
recent history for a unique request marker and reconnects without resubmitting
when found. If the connection is still unavailable or the job is not yet
observable, it warns that the run may have started and asks the artist to check
the ComfyUI queue before retrying. Simulated race and unrelated-job tests pass.

The starting-image resolution slider now permits up to 4 MP (4096 pixels per
side) when the running backend advertises that limit. Older running backends
retain the 2 MP limit so the interface cannot submit an unsupported size.
Unit tests cover matching frontend and backend bounds and model grid alignment;
actual image generation above 2 MP on the 16 GB GPU is not yet qualified and
may require substantial memory. The saved starting frame remains fitted to the
source raster; this setting changes the generation raster, not video delivery.
The Wan 2.1 relight video control now also offers approximately 8.35 MP, with
the matching 4096-pixel reviewed-shot loader and graph limits. Graph and UI tests
verify that 3840 × 2160 reaches both conditioning paths and output; a 4K GPU
render has not been qualified. The reviewed preparation path now accepts the
current v3 cache name as well as v2 while retaining file identity and mask checks;
CPU tests cover real v3 decoded frames and reject a mismatched cache pin.
An experimental HDR import handoff now returns an uploaded HDR video to the
paintout workspace, retaining the selected input colour and HDR/EXR delivery
choice. The server resolves only a verified, unchanged Studio video asset, and
the UI retains the old draft if an editor save fails. Simulated UI and asset
validation tests cover the handoff; it is gated on the updated backend and has
also passed an isolated HTTP upload and source-metadata handoff with a 24-frame
synthetic video; a cross-origin handoff received HTTP 403. This is a plumbing
test only, not HDR colour validation. It has not yet had an end-to-end desktop
or HDR render test. It does not make HDR
available in frame extension or the other LTX workflows.
The handoff now checks HDR transfer and colour metadata before returning the
clip. Synthetic, losslessly encoded 10-bit HLG and PQ fixtures pass detection;
tagged Display-P3 PQ remains in paintout's automatic colour mode. SDR sources
and unsupported or ambiguous automatic tags are rejected rather than silently
entering the HDR path. Explicit HLG/PQ overrides remain available for untagged
footage. These checks do not qualify generative HDR colour fidelity.
An isolated live HTTP test then uploaded a 24-frame 96 × 64 10-bit HLG/BT.2020
fixture and returned `hlg_rec2020` to paintout; an untagged SDR fixture was
rejected with HTTP 400. No generation was run in this test.
Separately, a two-frame HLG fixture passed the real paintout full-frame input,
ACEScct preparation and uncrop delivery, producing two EXRs and a correctly
tagged HLG video. The decoded input was supplied as a stand-in for model output;
this CPU test verifies colour and delivery plumbing only, not the generative
result, motion, or HDR appearance on a display.
An internal frame-extension canvas helper now converts ACEScct to linear
ACEScg before resizing or identifying black, then encodes its padding back to
ACEScct scene black. CPU tests cover black-area detection and retained HDR
highlights. It is not connected to the video graph or exposed in Studio; HDR
inference and delivery still require integration and qualification.
An internal candidate graph now combines that canvas with native HDR input,
the existing in/outpaint adapter and optional source audio. It defaults to a
tone-mapped SDR preview; an internal opt-in can also save explicitly unverified
EXRs for colour evaluation. The adapter's HDR behaviour and an HDR master are
not yet qualified. Structural tests check guide, mask, audio and
node links; no GPU inference has yet been run for this candidate.
Silent and source-audio variants have also been checked against the node
schemas and installed model filenames in the isolated Comfy instance. That
check identified and fixed a VAE filename mismatch; it is not a render test.
An isolated CPU-only Comfy graph loaded nine frames from a tagged HLG fixture,
constructed a 192 × 128 HDR canvas and saved its tone-mapped preview and mask.
The mask pixels were checked against the intended source rectangle. No model
was loaded or sampled.
The same isolated Comfy path also exported its nine canvas frames as an
explicitly unverified EXR archive. OpenImageIO confirmed 192 × 128 ACEScg files,
finite samples and values above scene-linear 1. This exercises the archive
node on ungenerated source pixels; it does not establish model output quality.
The candidate now routes the loader's actual video frame rate to conditioning,
audio trimming, empty-audio setup and the preview clock. Graph tests and the
live Comfy input types confirm the connections. A synthetic 23.976 fps HLG
fixture with continuous audio passed a nine-frame source selection at a
non-zero trim, with the selected audio within two samples of the reference.
This exercises the input nodes, not the rendered candidate or its export.

Latest duration check: a 30-second Wan 2.1 relight on a looped 512 × 288 fixture
produced 720 frames at 24 fps with zero measured audio lag in 200 seconds. Observed
available system memory fell from about 33.7 to 9.6 GiB during the run. This is a
timing and resource check, not a visual sign-off or a guarantee for 720p footage.
Additional source rates and the full desktop path still need verification.
The private long-HDR EXR exporter now preserves negative linear ACEScg
components; a real half-float EXR round-trip verifies negative channels and
highlights. A synthetic 29.97 fps HLG export also retained all 14 frames and
selected audio within one sample at a non-zero trim. Long HDR remains gated
pending the artist and end-to-end checks.
The bounded HDR graph now packages ACEScct directly into ACEScg EXRs without
clipping negative channels; the official decoder remains the SDR preview.
Real EXR and graph tests pass. An isolated GPU run of the revised SDR-to-HDR
graph delivered ten ACEScg-tagged EXRs and ten HLG 10-bit frames with audio;
the revised files are installed locally and require a ComfyUI restart. This
64 × 64 test establishes integration, not production-resolution visual quality.
A separate 512 × 288 ten-frame real-footage GPU test produced the correct HLG
metadata, ten EXRs and zero measured source-audio lag at a five-frame trim.
Longer and 1080p visual quality remain unverified.
An isolated native-HDR HTTP/GPU test also delivered 129 frames in two sections,
129 EXRs, HLG 10-bit and an SDR preview with zero measured source-audio lag.
The first 121-frame section took about 397 seconds at 384 × 216, so performance
is not qualified and the result still needs visual review.
The same 129-frame source rendered with eight overlapping 25-frame sections in
159 seconds of combined model execution (50 seconds initial load, then about
14–16 seconds per section), with all 129 frames and audio in both exports.
This does not include final export time and adds seven joins; visual continuity
must be reviewed before adopting the faster section size.
The private HDR panel offers an explicit shorter-section choice for native HDR
with a more-joins warning. The existing longer-section setting remains default;
the choice is gated with the rest of the long-HDR workflow pending review.
Completed, failed and cancelled private long-HDR jobs now remove their own
expected staging files without recursively deleting unknown files; tests cover
each terminal state. Previous test artifacts are not automatically removed.
An isolated two-section SDR-to-HDR GPU run confirmed that the job's staging
directory was removed after completion while its HLG, EXR and preview outputs
remained available.
An additional live multi-section GPU run was cancelled during sampling: its
owned prompt stopped, the queue was empty, staging was removed and no partial
deliverables were published.
Head-swap setup now links its missing crop, pose, padding, mask and sigma nodes
to the corresponding installed packs' declared upstream repositories. Automatic
node-pack installation remains outstanding.
Qwen Image 2.1 also has an in-app package for its INT8 model, encoder and VAE.
The pinned Comfy-Org repository identifies a research licence and all three local
files matched its published hashes. The image recipe remains experimental and has not received artist quality
sign-off. A single 384 × 640 generation using the full 1408 × 2976 reference
completed in 39.32 seconds on the warm RTX 4080 test instance with automatic
device selection. CPU conditioning did not complete before interruption after
184 seconds; this is not a completed matched benchmark. No peak VRAM was captured.
Qwen Image Edit 2511 now has an in-app package for its exact INT8 model, encoder,
VAE and Lightning adapter. Their pinned hashes match the files on this system;
the INT8 mirror does not state a licence and setup identifies its source.
The private long-HDR coordinator now has a tested in-memory job manager for
reconnection, single-job scheduling and cancellation. Its service validates
Studio asset references and emits output-relative file references. Start,
status and cancellation HTTP handlers pass simulated request tests but are not
registered yet. Studio controls and end-to-end testing remain; it remains
unavailable to users pending visual review.
Long jobs now also generate an SDR review video with the selected soundtrack;
streaming, frame count, audio selection and cancellation pass local tests.
The HDR panel now has a gated longer-clip control, section progress, reconnects,
cancellation and output preview. Interface simulations pass; the control is
disabled by default and requires full desktop and artist validation.
Long-HDR submissions now use a recoverable request ID: the service recognises
repeated requests and the client can recover a lost submission response without
resubmitting. A ComfyUI restart still loses in-memory job state and is reported.
An isolated HTTP-to-GPU long SDR-to-HDR test processed 130 frames in two
sections at 512 × 288, delivered 130 ACEScg EXRs, 130 HLG 10-bit frames and
a 130-frame SDR preview. Source audio measured zero lag in the HLG file. The
source repeats a short clip; the join and appearance await artist review.

FastH3 draft setup now offers its exact pinned INT8 model, BF16 latent upscaler,
shared H3 text encoder and video/audio VAEs through the explicit download flow;
it also links the separately installed SelfLift nodes. The source repository
metadata supplies the pinned sizes and SHA-256 values. Catalogue and UI tests
pass without initiating a download. The local installed files were updated;
ComfyUI needs a restart before its Python catalogue sees the change.

For the private 130-frame SDR-to-HDR test, the eight-frame overlap covers output
frames 113–120 (zero-based). At 128 × 72, mean absolute adjacent-frame RGB
changes across this region measured 0.23–0.97 on an 8-bit scale, compared with
0.39 median and 4.50 maximum across the output. The source's corresponding
changes were 0.06–0.70; this is a coarse engineering check and does not establish
visual continuity or colour quality. The longer route remains gated pending
artist and desktop review.

The camera-angle still graph previously stretched source footage to 1280 × 720
and generated a fixed 1024 × 576 still, independently of the selected video
raster. It now keeps the decoded source proportions and uses the same centre
crop and requested dimensions as the performance video. A real 448 × 768
portrait still rendered successfully on ComfyUI, and 13 camera graph tests
passed (one skipped); the generated image's appearance was not artist-reviewed.
The installed source was updated and needs a ComfyUI restart to take effect.

A follow-up real H3 camera render used that portrait still with a 0.3-second
source trim. The result was 448 × 768, 48 frames at 24 fps, with a two-second
audio stream. The opening retains the portrait composition, while the generated
background lettering changes later; this is an engineering check, not artist
approval or proof of perfect camera stability. Output:
C:/Users/ellio/ComfyUI-Shared/output/genj/final/zura_camera_portrait_test_00001.mp4

A real H3 head-swap timing test selected two seconds starting 0.3 seconds into
an audio-bearing source. The render delivered 48 frames at 24 fps and video and
audio stream durations of two seconds. A mono waveform comparison at the target
start had mean absolute error 0.0062 versus 0.34–0.43 at offsets of ±10–20 ms;
this supports the intended soundtrack alignment but is not a visual quality
review. Output: C:/Users/ellio/ComfyUI-Shared/output/genj/final/zura_head_timing_test_00001.mp4

Standard H3 reference-video setup now has its own exact model, text encoder,
compact video VAE and audio VAE package. Its eight-step adapter remains a
separate recommendation only when needed. A simulated empty setup selects the
smaller matching package instead of pulling unrelated OpenJutsu/SAM files.
Catalogue and interface tests pass; the installed Python catalogue needs a
ComfyUI restart before this becomes available there.

Camera resolution controls now edit the same H3 raster at both the still and
video stages, replacing the stale fixed-landscape message. Source dimensions
are snapped and limited to H3-supported values, and the resulting dimensions
are shown before generation. Interface tests cover portrait source and custom
sizes across both stages. The installed UI file was updated; a desktop visual
check and ComfyUI restart for the related backend fix remain outstanding.

A Studio project persistence test now confirms that changing the camera raster
saves the selected portrait dimensions and invalidates the previously approved
still, so it cannot be accidentally reused at the old framing. All 30 shared
Studio tests pass; this does not substitute for the desktop visual check.

The user accepted the 130-frame SDR-to-HDR result for preview use, including
its section join. This is preview approval, not a release-quality claim.
A separate isolated native-HDR test converted 26 frames of real 1080 × 1920
PQ footage in two overlapping sections, producing 26 frames of 10-bit HLG
Rec.2020 video and a viewable SDR preview. The source has no audio, so this
run does not validate audio; visual quality and longer 1080p clips remain to
be reviewed. Observed available system memory stayed above roughly 12 GiB.
The isolated server was stopped after the job; the main ComfyUI was left open.

The user also accepted the 1080 × 1920 native-HDR test through its join for
preview use. This confirms visual preview acceptance of that short sample;
it does not validate HDR display brightness, longer takes, audio or the full
Studio desktop flow. Long HDR remains gated pending the desktop checks.

The full HDR Python regression suite passed 105 tests when run with the actual
ComfyUI modules on PYTHONPATH. Both bounded and long-HDR client tests also
passed. An initial run without the ComfyUI path produced four missing-module
errors from the standalone test stubs; rerunning with the real installation
resolved them. These checks do not replace the pending desktop visual test.

The separate first/last-frame validation already includes real maximum-length
GPU runs at 256 × 256: H3 produced 362 frames and Wan 2.2 and LTX 2.5 each
produced 361, all at 24 fps with both endpoints connected. Those runs used the
same image at each end and are not high-resolution or visual-quality approval;
see STUDIO_VIDEO_VALIDATION.md for timings and limits.

A guarded integration originally required ZURA_HDR_LONG_PREVIEW=1 at startup.
After the user accepted the longer SDR-to-HDR and 1080p HDR previews, the
development version exposes this explicitly labelled preview by default; setting
ZURA_HDR_LONG_PREVIEW=0 disables it. The UI discovers the capability and
reconnects to a saved job. An isolated instance using the real
Studio upload endpoint converted a 130-frame SDR source in two sections and
returned 130 frames of HLG video and a tone-mapped preview; the HLG video has
a 5.4167-second video and a 5.416-second audio stream. Unit and UI tests pass.
Desktop validation is pending; this is not installed in the normal Studio.

Long HDR's status polling no longer erases live sampler progress when it sees
the same running section. The indicator returns to an indeterminate state when
the prompt or phase changes. A UI regression test covers both transitions; this
change is in the test worktree, not the installed normal Studio.

The staged shared HDR entry is available from the video workspaces without
changing their generation model. It can use the selected LTX first/last,
frame-extension or paintout video, the current LTX shot output, a separately
uploaded video, or an EXR sequence. Selected output paths are resolved inside
ComfyUI's output folder before use. Isolated default-mode and longer-preview
HTTP tests accepted valid output files; the longer route completed a real
10-frame SDR-to-HLG output conversion. Invalid outside-folder references were
rejected. This shared UI and backend are not yet installed in normal Studio;
a desktop check and coordinated restart remain necessary.

The first/last-frame audio attachment now has an accessible X and removes the
saved reference without deleting its source file. Endpoint UI tests pass; the
local frontend files are installed and require a page refresh.

Relight correction, 30 October: the user confirmed that a full clip and Wan 2.1
controls work on the corrected 8330 test instance. A focused public 1.3.37
release excludes the unfinished HDR work, fixes the stale H3 duration guard and
labels, and passes the relight, Studio UI and package checks. GitHub Actions
successfully uploaded 1.3.37 to Comfy Registry; the Registry reports its status
as pending review. A new full relight render was not run for this correction.

HDR range controls now show the selected frame count alongside the source count
and offer an explicit Use full clip action. The source-info endpoint accepts only
a verified Studio upload or a selected output within ComfyUI's output directory;
its real 72-frame, 24000/1001-fps fixture test and traversal rejection pass.
The UI requests sectioned preview when available if the full source exceeds its
per-run limit, and otherwise reports the limit instead of silently shortening.
Race tests reject metadata from a previously selected video and preserve the
chosen HDR colour when switching to sections. This development change still
requires a fresh backend start and a desktop visual check; it does not yet
make every LTX workflow natively HDR-capable.
The HDR range selector also recovers an inherited range that exceeds a newly
selected shorter source. If the artist edits the range while source metadata is
loading, the response preserves that edit and flags a range beyond the source
instead of overwriting it. UI regression tests cover both cases; the change is
still staged for desktop verification.
A fresh isolated Comfy instance has now checked the HDR source-info route over
HTTP: a 25-frame uploaded PQ clip returned 25 frames at 24 fps, a selected
output returned nine frames at 24000/1001 fps, and an outside-path request was
rejected. This verifies source metadata and the file boundary, not the full
visual HDR workflow or a desktop interface check.
The model setup panel now identifies the actual packs for Wan 2.1 relight's
ForLoopOpen/ForLoopClose and SimpleMath+ dependencies, alongside the existing
Easy Use integer node link. Their repository addresses were checked against
the installed packs' own metadata. UI tests cover all four missing nodes and
avoid leaving them as unhelpful unmapped names; installation and restart remain
user-directed and are not performed automatically.
A live setup-panel check against the deliberately limited 8331 Comfy instance
confirmed its four missing relight nodes resolve to links for the three actual
installed-source packs, with no unmapped-node message. This was a read-only
check; no packages were installed and the user's other Comfy sessions remained
open.


Frame-tail fix in development: Wan 2.1 relight now holds a short source
window and extends the final generated frame to the next 4n+1 length. A real
50-frame GPU render returned 53 frames at 24 fps with audio, in 54 seconds;
the final frames were checked for the hold. Original-length selection now
rounds up fractional 24 fps durations. Wan Animate 2 and the H3 camera, head
swap and standard graphs have corresponding held-tail changes and regression
checks. LTX frame-extension source selection also rounds up and its final
delivery holds the tail after joining sections. The running user server has
not been restarted to load these development changes.


Frame-tail follow-up: a real H3 SDR camera test selected 51 frames and saved
56, with the five added frames held and one audio track. Studio's result
collector accepted the actual file. A real LTX SDR frame-extension run through
upload, review, approval and render selected 12 frames and saved 17, retaining
audio; decoded tail frames match. A separate 150-frame blended-section media
test now returns 153 frames and verifies that the original frames and joins
do not change. The full-source trim retains fractional 24 fps endings. An
existing 78-frame OpenJutsu output was passed through the new delivery nodes
in ComfyUI and returned 90 frames with a held tail and zero-lag audio
correlation 0.99585; this verifies delivery, not a new character render.
Wan 2.2 streamed mux padding has CPU media coverage but has not yet had a
new end-to-end model render. H3 remains SDR; HDR experiments use LTX 2.5.
These changes are not installed into the user's running Comfy session.


The source-duration and held-tail change now covers the OpenJutsu delivery
step, Wan 2.2's streamed mux, the LTX scene graphs, and short and long LTX
frame extension. The 25 fps, 53-frame source was also uploaded and reviewed
through the Studio frame-extension endpoint: 51 frames were selected at
24 fps. A fractional 25 fps long-source regression covers full-range review,
section assembly, original audio and a held output tail. A real ComfyUI mux
check using existing video confirmed Wan 2.2's 51-to-53-frame delivery, without
rerunning the Wan video model. Ten targeted Python suites passed with the
installed ComfyUI and Wan preprocessing node pack; the related JS trim and
length tests passed. These checks do not qualify the experimental HDR
frame-extension appearance and do not replace desktop UI verification.

The shared source composer now hides its LTX HDR entry and separator when an
H3 or Wan workflow is selected, including Wan 2.1 relight. The entry remains
available for the LTX route and opens LTX's separate HDR conversion, not
native H3 HDR. The Studio interface regression test covers model switching;
this development change still needs desktop verification and release.
HDR navigation now selects the currently loaded Studio source when opening from the video workspace, instead of retaining an earlier separately imported clip. Workspaces without a selected output or source open at Import video rather than inheriting a different workspace's source. The Studio navigation test covers both transitions; desktop visual verification and installation remain outstanding.
The HDR import buttons now explicitly request the source rather than an earlier output, even when a previous render is still selected. Result-conversion buttons retain their separate behaviour. Studio navigation, outpaint and paintout entry tests pass; desktop verification remains outstanding.
HDR source-info failures now show a retry message instead of silently leaving the frame range unknown; reselecting the source can retry. Stale responses remain ignored. The HDR and Studio UI suites pass; this is not desktop verification.
When HDR import is opened from paintout or the experimental frame-extension workspace, the import panel starts in HDR input mode. Its return button names the actual destination. Interface tests cover the frame-extension label, input mode and handoff; these changes remain local and require desktop review.
A successful retry of HDR source metadata now clears only its own stale error message; it does not overwrite active job status. The HDR, Studio navigation, outpaint and HDR artifact checks passed after this change.
An active model download now keeps its Cancel action visible even if workflow setup or the selected package becomes unavailable. The model-download interface test covers this recovery case; no download was started for the test.
The focused regression pass covered six UI suites and eight HDR/outpaint backend suites, followed by Wan relight, Wan Animate 2, OpenJutsu, H3 head-swap, shared Studio, length and resolution tests. One head-swap test was skipped. These are not a full model render or desktop visual approval.

The user-supplied older-install example `Need relight 3_1.mp4` was checked with tracked-feature similarity estimates. Frame 0→1 estimated a scale of 1.02054 with a vertical shift of about −19.5 pixels (310/961 RANSAC inliers); 1→2 and 2→3 estimated scales of 1.00017 and 1.00004 with 947/999 and 957/998 inliers respectively. This supports a real first-frame framing change in that example, but is not a diagnosis of its old graph or proof that every current workflow is fixed. The prior current-code relight render showed no obvious framing jump; a matched-source current render remains the stronger comparison.
The Wan 2.1 relight regression now also compares the first-frame and video resizing nodes' class, dimensions, interpolation, crop mode and position, grid alignment, padding and device. All 22 relight tests pass. This confirms matching resize configuration, not a matched-source GPU comparison or a guarantee against model-generated framing changes.

Held-frame audio follow-up: the shared soundtrack exporter now trims audio at the selected interval before padding with silence. A real FFmpeg test uses a longer source with a non-zero selection start and verifies both explicit padded lengths and Wan's model-stride path. The long HDR frame-extension HLG and SDR preview exporters also limit audio to the selected duration before silence; a separate real AAC regression covers the offset and both output formats. The previously generated HDR comparison file predates this audio correction. These changes remain local and have not been loaded into the user's normal ComfyUI instance.
Fractional selections now retain their exact requested duration alongside the rounded frame count. Preparation and shared delivery stop the audio at that exact point and pad any held fraction with silence, including when the model needs no additional padding. A real FFmpeg test covers a 0.97-second selection starting at 0.25 seconds; the shared delivery test covers the same fractional boundary. Existing clip records without the new field retain their earlier frame-aligned behaviour.
The longer SDR frame-extension job also carries the exact requested duration through review, render and section assembly. Its CPU integration test processes a 25 fps fractional source range into 153 output frames and verifies audio ends at the requested time with silence across the held tail. This does not qualify HDR appearance or change the separate HDR mode's preview status.
Short SDR frame-extension graphs now retain the requested duration through both mask review and generation, for canvas expansion and black-area fill. The experimental short HDR audio loader also accepts the exact selected duration and pads the remaining fractional frame with silence. Real audio decoding tests, graph checks and HDR review tests pass; this has not had a fresh GPU render or been installed in the running desktop.
Opening HDR conversion from an LTX first/last-frame result now explicitly selects SDR-to-HDR, even if the artist previously used HDR import. A UI test covers the transition and confirms it keeps the selected take. This remains a separate post-conversion, not native HDR generation or the integrated controls requested for every LTX workflow.
The frame-extension result now records whether its delivered file is SDR or HLG, and its HDR handoff selects the corresponding processing mode instead of retaining a previous choice. Invalidation clears the old result reference. UI tests cover both mode transitions; the HDR route remains experimental and requires visual qualification.
Model setup now recognises additional Zura-owned clip preparation, frame-hold, HDR loading and outpaint nodes. When those nodes are missing it links to the Zura Nodes update and restart instructions instead of listing them as unmapped. The model setup UI regression test passes; installing custom node packs automatically is still outstanding.
Short and long frame-extension review keys, including experimental HDR, now include the exact selected duration as well as the rounded frame count. Selections with different fractional endpoints require separate review even when they produce the same number of frames. Existing pre-change reviews will need to be reviewed again after updating. Focused planning, queue, render and media tests pass.
