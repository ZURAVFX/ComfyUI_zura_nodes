# Zura Studio: implementation checklist

Goal: preserve the approved character workflows while making the requested media,
generation and viewing controls dependable and easy to discover. Changes are local
until a release is explicitly requested and the relevant flows are verified.

- [x] Keep H3 OpenJutsu and Wan Animate 2 available for character plus background replacement; retain OpenJutsu's background-preserving route and existing approved workflows.
- [ ] Add LTX-only HDR and SDR processing and delivery following official 2.5 examples. Bounded SDR-to-HDR and HLG-to-HDR previews passed short engineering tests with HLG, EXR and audio. PQ video and ACEScg EXR input passed GPU engineering tests; independently computed PQ/HLG neutral swatches passed ingest and HLG output round-trip checks. Tagged Display-P3/PQ input has independently checked synthetic decoding and colour conversion; unsupported or ambiguous tags are rejected. EXR auto-detection checks every frame. A 121-frame experimental temporal test renders real PQ footage; a 17-frame 1080 × 1920 reference also delivered correctly tagged HLG. Two private SDR-to-HDR GPU tests, with and without a continuation anchor, each rendered a 10-frame synthetic fixture in two sections and delivered ten EXRs and a correctly tagged 10-bit HLG video. An anchored 48-frame real-clip test produced three sections, 48 EXRs and a 10-bit HLG video; source audio cross-correlation measured zero sample lag. Artist review of the joins and longer public workflows remain. HDR previews currently cap runs at 121 frames and often fewer at high resolution. SDR preflight now checks the actual 32-pixel and 8n+1 padding against its software memory budget and reports the frame limit before queuing; for 1920 × 1080 this cap is 17 frames. The HDR panel now requests the limit for the selected source dimensions and displays it before submission, clearly labelled as a software limit rather than a hardware guarantee. When the result dimensions are unknown it does not reuse the source limit.
- [ ] Provide an in-app model setup flow showing missing files, dependencies, sizes and download progress, with explicit user initiation. The FLUX.2/3, OpenJutsu, Wan Animate 2 and partial LTX 2.5 packages are implemented; LTX Gemma, clean plate, outpaint, H3 first/last, H3 control, H3 Ref2VA DMD, two head-swap adapters and Wan relight packages are also listed. The newly added primary model and adapter files match installed files by SHA-256; users must review individual source and upstream terms. An installed H3 INT8 VAE uses a different same-named version from the pinned download, so Studio protects it and describes the mismatch without assuming it is broken. Direct setup appears in main video, first/last-frame, reference-video and Paintout workspaces. Main video setup now includes the selected starting-image model where required, and FLUX 3 is present in its downloadable packages; supplied frames and head swaps do not add unnecessary image-model requirements; frame extension reports graph-derived dependencies for short canvas expansion and black-area fill, and separate dependencies for long clips; switching method or duration updates setup. A fresh isolated Comfy instance returned the distinct short and long dependencies and matched its missing files against the download catalogue; the deliberately limited node whitelist reported its missing LTX nodes. This is not a desktop visual check. HDR setup now checks model-file presence and loaded nodes against the selected bounded graph and output, including the full VAE and encoder. It does not certify model contents or hardware capacity. The exact reduced-rank TaoMate adapter is now included with a pinned source and SHA-256 matching the locally approved file. Remaining workspace entry points and custom-node installation remain outstanding. Paintout's route mapping is tested; its loaded-source panel still needs a visual check in both hosts.
- [x] Make ProRes MOV previews playable while retaining the original media for processing; a real isolated-browser test played a synthetic ProRes/PCM MOV via an H.264 proxy while preserving the original file and SHA for processing.
- [ ] Find and fix opening-frame aspect changes and duration mismatches. The relight crop paths now match and the UI displays frame-aligned lengths. An exact one-frame shortfall at final mux is held to match the selected duration, with a real FFmpeg 23-to-24-frame test; larger shortfalls still fail visibly. LTX first/last audio now pads short references with silence to the selected video length. A one-second relight GPU test produced 24 frames at 24 fps with aligned original audio and no obvious framing jump. A four-second, two-window relight from 60 fps footage at a non-zero trim produced exactly 96 frames with zero measured soundtrack lag. A separate 23.976 fps, non-zero-trim relight also produced 96 frames and zero measured audio lag; its looped source has discontinuous audio, so it does not establish continuous end-to-end audio coverage. A separate continuous-audio FFmpeg fixture covered the output duration. A 29.97 fps fixture with continuous synthetic audio and a non-zero trim also completed a real four-second relight with 96 video frames and audio covering the duration; the periodic tone is not evidence of exact lip-sync. Wan 2.1 relight validation no longer inherits the unrelated H3 five-second limit; a six-second graph passed the corrected source-selection validation and rendered 144 frames with zero measured audio lag. A 30-second relight rendered 720 frames with zero measured audio lag, although memory use was substantial. The custom-selection limit of 30 seconds is reflected in the interface, while full-source selection remains separate. Real preparation and full-resolution reload tests cover 23.976, 25 and 29.97 fps. Representative real H3, LTX and Wan first/last and H3 reference outputs also matched their requested frame counts. A real OpenJutsu test at a 0.3-second trim exposed a one-frame shortfall: 77 rather than 78 frames for 3.25 seconds. The graph now uses the frame-exact selection node and rejects ranges beyond the source. A repeat produced 78 frames, 3.25 seconds and zero measured source-audio offset. The intermediate is an H.264 CRF 16 clip. On this source, a same-range 78-frame FFmpeg comparison measured 48.89 dB average PSNR against the selected original; this is a compression check, not artist approval of the final generated video. A matching Wan Animate 2 test at a 0.3-second trim also delivered 78 frames and 3.25 seconds with zero measured audio offset. Its source-range validation now rejects requests that would otherwise be silently shortened. Shared Studio preflight and H3 viewport, camera and head-swap adapters now reject custom ranges that extend beyond the available source instead of silently shortening them. A real five-second source passed the common preflight for valid 3.25-second selections across Wan, LTX, H3 and Wan Animate 2; an overlong selection failed in each, and Use source was accepted where the full clip fits the model limit; focused graph tests cover these cases. The head-swap graph also passed its node-schema check against the currently running ComfyUI; this does not replace a new render test. Other workflows and unusual-source-rate cases remain to be checked.
- [x] Implement LTX video outpainting with a simple extension/crop control or existing black-area input, and verify real output with both approaches. The preferred black-guide approach is integrated as a five-second preview and passed a 12-frame real upload-to-render test; Already-black input now uses a reviewed masked fallback: a 12-frame GPU test filled the border and preserved dimensions and audio; a 150-frame guided and feathered masked test preserved audio; the user also approved the full-length preview including all three joins for the optional longer-clip mode; the optional long route, timing, cancellation and production review are implemented and locally installed. The installed interface was visually checked with real footage; full-source selection and the numeric duration were verified. The short workflow also has an interactive trim and source-length option.
- [x] Offer optional compatible installed LoRAs in advanced controls, with model-family validation; do not silently apply incompatible weights. Image, H3, Wan and staged LTX routes have graph tests; starting-frame image generation now has separate LoRA controls and graph coverage. Optional controls now also cover HDR, frame extension, first/last, standard H3 reference video and paintout; Wan 2.2 uses separate phase selectors. Progressive FastH3 supports an experimental optional H3 adapter; real H3 and FastH3 tests confirmed adapter loading, but broad third-party LoRA quality is not guaranteed.
- [x] Support zoom, pan and reset in the main video, image, first/last-frame and reference-video previews; interaction tests cover playback and seeking. Desktop zoom and reset were checked; additional media types still need desktop visual confirmation.
- [x] Confirm FLUX.2 Klein 9B is the image generation default, and investigate face-identity and realistic-skin LoRAs with credible compatibility evidence. FLUX.2 Klein 9B produced a real 512 × 512 render in 12 seconds including model loading. A controlled FLUX.3 Consistency LoRA comparison showed additional skin detail but did not establish better identity; a matched Restore comparison added texture but also altered the face, so neither adapter is a verified identity improvement or enabled by default.
- [ ] Run focused automated tests and representative local GPU/UI tests; identify any quality-sensitive feature still requiring artist review and keep unverified modes clearly gated.

- [ ] Show clear, truthful progress across all modes. Event routing and stage labels were fixed for frame extension and HDR, and sampler labels clarified for image, first/last and reference video. HDR now retains an active job through transient connection errors and keeps controls disabled until cancellation is confirmed. Image and video model-download panels now reconnect to the same job after a temporary status error instead of falsely declaring it failed; simulated tests confirm no duplicate download is submitted. The model catalogue also exposes the active job so both panels can reconnect after reopening; backend and UI tests cover this without starting a second download. The private long-HDR coordinator reports stage, completed sections and its active prompt, routes sampler events to the requesting Studio client, and waits for its own prompt to leave the queue before declaring cancellation. Simulated queue tests cover running and unrelated prompts, and an isolated three-section GPU test interrupted its second section, reached cancelled with an empty queue and published no partial output. Custom LTX LoRAs are validated before a long run and applied to each section in graph tests. Frame extension also waits for its active prompt to leave the queue before reporting cancellation; an installed multi-window test confirmed this. Image, first/last and paintout recheck completion history when a job disappears between status requests, preventing the finished result from being missed. UI tests pass; live websocket progress was observed in isolated Comfy and full desktop flow remains to be checked.

Completion means each exposed control changes the actual rendered result, preserves
existing approved paths, and has truthful limits and actionable errors. Maintain
notes on unsupported model capabilities rather than claiming generic HDR, LoRA or
duration support without evidence.

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
