# LTX 2.5 HDR development

## Native HDR performance experiment, 31 October

`artist_studio/ltx25_hdr_plan.py` adapts the approved staged performance
topology for an original EXR appearance plate and SDR source pose/edge
extraction. This is an opt-in development experiment, disabled by default.
It is not an official HDR Union recipe. The caller must resolve and
verify the EXR manifest, bind it to the approved opening and pin the full HDR
VAE before planning. The template's SDR VAE is replaced before the final basis,
cache identities and graph hashes are computed; no temporary template is run.

Each VAE consumer receives the full float32 VAE. EXR appearance conditioning
does not pass through a PNG or JPEG. Resizing converts ACEScct to linear ACEScg
and back; the pose/edge guide is explicitly encoded into ACEScct for the HDR
VAE. Signed Union guide masks remain inside the first sampling graph, while
ordinary cropped video latents use the existing verified handoff. Frozen audio,
original/replacement/silent semantics and exact finished-frame indices are
retained. HLG and EXR are saved from native decoded frames, with tone mapping
applied only to the browser proxy. This adds no SDR-to-HDR diffusion pass.

A private GPU run executed real source selection, DWPose, text, sampling,
upscaling, refinement and decoding for 17 frames at 288 x 512. The six generation
phases took approximately 76 seconds including loads on this run; this is not a
comparative speed benchmark. Every phase bound actual successful producer
receipts and verified cache files. Delivery validation found 17 10-bit HLG
frames tagged BT.2020 and 17 finite half-float ACEScg/AP1 EXRs, with linear
values above 1. The original soundtrack was present. Private graphs, histories,
receipts, model pins, metadata and contact sheet are under
`work/openjutsu-benchmark/native-hdr-performance-check`.

The reference was a synthetic exposure-expanded SDR image, not native HDR
camera footage. The viewing contact sheet shows appearance/framing changes;
the test does not qualify identity, performance fidelity or HDR display quality.
Do not ship this as a verified workflow. Main Studio EXR import and approval,
native plan resolution and result collection are now integrated behind
`ZURA_LTX_HDR_PERFORMANCE=1`. In LTX whole-scene performance, select a finished
frame and upload one EXR. The existing inline output selector offers HLG,
HLG + EXR or EXR; SDR is unavailable for this native input. No new panel or
separate conversion step is introduced. Each approval binds the original
manifest hash and colour interpretation as well as the viewing PNG hash.
Changing original EXR bytes, switching to an incompatible mode or attempting
to use the proxy as an image-generation reference is rejected. The native
runtime resolves and pins the full VAE before planning; decode collection
rebinds all upstream receipts before checking actual frame/raster/audio,
10-bit HLG tags and the EXR archive. Its final result is identified as native,
so reopening or displaying it cannot submit the SDR-to-HDR diffusion pass.

`native-hdr-performance-ui-check` contains the real EXR import/project records,
graph-derived readiness, desktop/mobile screenshots and playback evidence.
The displayed result is a replay of the prior independently revalidated GPU
fixture, not a new render of the imported project. The CPU server deliberately
excluded DWPose/VHS, and setup correctly reported those missing classes.
There were no page errors, global overflow or generation submissions. All
67 top-level JavaScript suites and 81 combined backend runtime/input/approval
checks pass. A representative real-HDR render and artist review remain before
default exposure or release. The existing SDR generator is unchanged.

HDR is LTX-specific. The experimental `artist_studio/hdr_delivery.py` graph
builder follows the locally installed official `ComfyUI-LTXVideo` 2.5 HDR
examples. Studio offers a bounded SDR-to-HDR tool for an uploaded source or
the latest LTX result. It is a separate conversion pass, not an HDR-enabled
version of all LTX generation workflows. The first/last-frame workspace now
also automates that additional pass when its inline LTX output selector is set
to HDR. It preserves the SDR take and shows an SDR preview with separate HLG/EXR
downloads. This does not add native HDR image conditioning to its endpoint graph.

The SDR-to-HDR path uses LTX 2.5 distilled, its video and audio VAEs, the
SDR-to-HDR IC-LoRA and the matching fixed scene embeddings. Frames must be
accurately decoded as SDR, resized/padded to a multiple of 32, and extended
to 8n+1 frames before sampling. The builder converts sRGB to ACEScct, forces
the video VAE to float32, uses the native IC-LoRA guide and 8-step Euler
sampling, removes guides, decodes, then removes right/bottom and temporal
padding. The caller must supply the correct original raster and frame count.
Audio, if present, is restored from a separately trimmed source.

For video, the official Comfy image-colour conversion maps the ACEScct output
to BT.2100 HLG. `CreateVideo` receives HDR and 10-bit, and `SaveVideo` writes
the result. For EXR, LTX `LTXVHDRDecodePostprocess` writes ACEScg half-float
frames in a job-unique output folder. The caller must collect the EXR folder
and expose a usable download, and must not reuse a job name because LTX's EXR
writer overwrites existing matching frame names.

A CPU-only Comfy run tested the delivery nodes with synthetic, known sRGB to
ACEScct frames. The output video was 10-bit yuv420p with BT.2020 primaries,
BT.2020 non-constant luminance matrix and HLG transfer metadata. EXR output
was half-float with ACEScg `colorSpace` and AP1 chromaticities. This confirms
delivery and tags, not HDR inference quality. All 26 model graph classes and
required input names were found in the live installed Comfy schema.

The user accepted access to the official adapter. Its 1.31 GB LoRA and 12.6 MB
scene embeddings were installed into the configured model folders and verified
against the SHA-256 checksums published by Hugging Face, revision
`c7578ebddb54f4210e534e4d8cad698a5a520692`.

One real SDR-to-HDR inference was then run with the LTX 2.5 INT8 distilled
model and official adapter on the local RTX 4080. A 25-frame, 24 fps city
clip was scaled to 384 x 224 and the complete graph ran in 18.55 seconds.
The output had 25 frames of H.264 yuv420p10le video tagged BT.2020 / HLG,
with one AAC soundtrack, plus 25 half-float ACEScg EXRs. The first EXR
contained finite linear values up to 6.60, including values above 1, confirming
real extended-range data rather than tags alone. This small engineering render
does not establish HDR visual quality, longer-shot behaviour, input transforms,
or the Studio user flow. The inference graph and output are saved privately
under `work/openjutsu-benchmark` and Comfy's `output/genj/hdr` respectively.

The registered `ZuraLTXHDRPrepare` node now reflect-pads SDR input to the
model's 32-pixel grid, holds its last frame to a minimum 9 and 8n+1 frames,
and supplies the original size and length for a crop after decoding. It rejects
unbounded batches, non-finite or out-of-range pixels. The dynamic graph was
tested with real inference: 14 source frames at 370 x 210 were padded to 17
frames at 384 x 224, and the delivered result returned to 14 frames at
370 x 210. The test rendered in 20.2 seconds and produced both HLG video and
EXR. Audio was deliberately omitted from that test; selected-range audio must
be trimmed independently before inclusion. A new `ZuraHDRTrimAudio` node does
that by the original frame count and FPS and has unit tests, but has not yet
been run in a dynamic HDR conversion. It fails if the soundtrack is shorter
than the selected video, rather than hiding a sync problem.

`hdr_probe.py` can classify explicit HLG, PQ and common SDR transfer metadata;
untagged and scene-linear sources remain unknown. It does not convert input
primaries or transfer to sRGB, and must not be used to claim full HDR input.

The Studio tool uses `ZuraHDRLoadSDRSource` to read just the selected source
frames using Paintout's frame-exact 16-bit decode. Supported Rec.709 and sRGB
transfers are converted to sRGB, and tagged HDR is refused. Unknown colour can
only be supplied using an explicit artist selection. It limits each run to
121 frames and 40 million pixel-frames and refuses odd raster sizes. Source
audio is extracted for the exact selected interval. A job-specific, no-overwrite
ZIP contains the ACEScg EXR frames and a separately tone-mapped SDR MP4 is used
for preview. Existing HLG and EXR masters retain their HDR encodings.

A real full graph test used a 64 x 64 engineering fixture with an explicit
Rec.709 source override and converted
source frames 5–14. The result contained 10 frames of BT.2020/HLG 10-bit video,
AAC audio, ten ACEScg EXRs in a downloadable ZIP, and an SDR preview. Comfy's
file endpoint returned the ZIP successfully. This verifies plumbing, not HDR
visual quality: representative footage, real-world source colour tags, browser
UX and delivery still require artist review. The node does not implement a
safe long-video tiling/continuation strategy.

The separate official native HDR-to-HDR workflow uses an EXR to
ACEScct input, float32 VAE and the `ltx25_general_refine.safetensors` detail
refiner; it is not implemented by the SDR-to-HDR builder. It disables JPEG/CRF
compression on ACEScct frames because it can darken highlights. HDR source
tags and per-mode input colour transforms require their own end-to-end tests.

`hdr_native_source.py` contains a bounded, experimental preparation helper for
HLG/PQ video and ACEScg, ACEScct or linear Rec.709 EXR sequences. It converts
source pixels to the model's ACEScct working space using Paintout's existing
colour transforms. Synthetic tests check that extended ACEScg highlights
survive and that encoded HLG passes through the native colour conversion. This
helper underlies Studio's separate HLG-video preview route. It has not been
validated against HDR camera originals, PQ inputs or EXR sequence uploads.
The example names an
unidentified `ltx25_general_refine.safetensors`; Lightricks' official 2.5
Refine Details IC-LoRA is available and checksum-verified locally, but its
equivalence to that custom-named file is not established.

`hdr_native_graph.py` provides a separate two-stage TiledFusion
experiment using the official Refine Details adapter, native EXR loader,
float32 video VAE and the example's 8+3-step schedules. Its loader documents
EXR sequences as well as stills, but the supplied workflow itself repeats one
EXR still. A real GPU run used nine 64 x 64 engineering EXRs scaled to 512 x
512, and wrote nine 10-bit BT.2020/HLG video frames and nine ACEScg EXRs with
finite values up to 7.01. The run took 78.45 seconds using 256 x 256 tiles;
the current graph uses the example's 1024 x 576 tile setting.

Studio now offers an explicitly labelled HLG-video-to-HDR preview: an uploaded
or selected LTX HLG video is converted to ACEScct; the source is padded rather
than stretched, the last frame is held internally to 8n+1, and padding is cropped
after inference. Selected source audio is restored. A real engineering test on a
384 x 224 generated HLG clip selected frames 5–13 and delivered exactly nine
frames at the same raster, with one AAC soundtrack, a 10-bit BT.2020 HLG master,
nine ACEScg EXRs and a viewable SDR proxy. It ran in 63.24 seconds. It confirms
plumbing and the revised tile setting, not representative HDR visual quality,
retention of the source's motion, seamless long clips, or HDR monitor playback.
The preview now also accepts PQ video and uploaded EXR sequences, with explicit
EXR colour space and frame rate. The loader was exercised with two frames of a
10-bit BT.2020 PQ clip converted from the earlier HLG output and two frames of
the earlier ACEScg EXR output; both decoded to finite ACEScct frames and the
sequence retained its selected 25 fps. Both sources were subsequently run
through the full LTX model on nine 384 × 224 frames. The PQ run took 55.5 s;
the EXR run took 30 s with warm models. Both wrote nine-frame 10-bit BT.2020
HLG videos and ACEScg EXRs. The EXR GPU smoke test used a local sequence
directly; the multipart upload endpoint and manifest validation were separately
exercised with two real EXR frames. Uploaded sequence frames are checked against an integrity manifest before
decoding. Neither source has been visually qualified on an HDR monitor.

All preview inputs remain limited to 1–121 frames, even source dimensions of
32–2048 pixels per side, and a 40-million padded-pixel-frame cap. Seamless long
clips, colour accuracy on representative camera sources, and full desktop UI
review remain outstanding.

## Longer native HDR experiment

An internal, unexposed executor plans 8n+1-compatible memory-bounded chunks,
queues them sequentially through native Comfy, stages float32 ACEScct on disk,
and streams 10-bit HLG with the original audio and/or an ACEScg EXR ZIP. It
performs model/output, encoder and free-space checks before queueing, verifies
staged chunk integrity, and targets only its own current prompt on cancel.
These pieces are not yet restart-recoverable or integrated into Studio.

A two-chunk LTX GPU test using ten 384 × 224 PQ frames produced exactly ten
10-bit Rec.2020 HLG frames and ten EXRs, with scene-linear highlights above 1.
Linear-light crossfade showed visible ghosting around moving pedestrians. A
minimum-error hard cut reduced that ghosting in this example but can create a
motion jump; an optical-flow experiment still showed warping and was rejected.
The test did not contain source audio; an independent FFmpeg test verified audio
offset and duration. Neither result is representative HDR monitor validation or
a licence to lift the Studio limit. Keep the 121-frame guard until temporal
quality, real source audio, cancellation, recovery and display are verified.

A second matched GPU test chained the previous chunk's corresponding generated
frame through `LTXVAddGuide` at the start of both sampling passes, while keeping
the source video IC-LoRA guide. It completed both chunks, but the moving-person
overlap still showed ghosting and became progressively darker than the
unanchored result (mean scene-linear value at frame 9: 0.330 versus 0.352).
This single short test does not justify enabling the option or removing the
121-frame limit. The anchor graph remains internal and defaults off.

A follow-up tested the artist-approved outpaint approach: `LTXVImgToVideoInplace`
sets the previous render's timestamp-aligned frame in both sampling passes,
with the source HDR IC-LoRA guide preserved and nine same-time frames feathered
in linear light. A real 26-frame 384 × 224 HLG test completed with 26 10-bit HLG
frames and 26 ACEScg EXRs. Although technically successful, the two independently
generated windows placed moving pedestrians differently and the feather visibly
doubled them around frames 20–22. Same-time tone-mapped mean RGB difference grew
from 0.015 to 0.033 through the overlap. One short synthetic-source example is
not enough to establish HDR quality; this method remains experimental and the
public limit remains in place.

Private follow-up comparisons tried restricting the feather to areas where the
windows agree and using a hard cut over moving regions. In this example the
output-difference mask covered 86% of the frame after dilation; a source-flow
mask covered 92%. Both were effectively near-global cuts. The least-error cut
had a mean tone-mapped frame difference of 0.032 at the transition versus 0.016
in the previous natural frame. These are diagnostic proxies, not a successful
motion-quality test; the selective strategies are not exposed.

## Single-canvas temporal fusion experiment

The installed LTX tiled-fusion sampler supports one global latent canvas with
overlapping temporal windows, when both IC-LoRA guide nodes use streaming with
the same `tile_frames` as their samplers. A private two-stage test used 129
frames at 384 × 216 and a 65-frame window. Logs confirmed three per-window
guides and three corresponding sampler windows in each pass; canvas tensors
were on CPU. It produced exactly 129 10-bit Rec.2020 HLG frames in 750 s on the
local RTX 4080. Tiled VAE decode used the existing 128-frame temporal setting
and saturated ~15.5 GB VRAM for several minutes. Per-node timestamps were not
captured, so exact stage durations are unknown.

Sampled window boundaries showed no obvious double-exposure in the SDR proxy,
but this is one low-resolution street test whose HLG input was converted from
SDR. It had no audio or EXR output and has not been reviewed on an HDR display.
It therefore proves temporal-fusion plumbing, not representative HDR colour,
quality, practical speed or long-duration readiness. The public Studio limit
is unchanged. A smaller VAE temporal decode tile may improve memory pressure,
but speed and decode seams require a controlled comparison.

An additional short engineering test used a publicly available 3840 × 2160
PQ/Rec.2020 sample, proportionally downscaled to 384 × 216 with its PQ tags
and soundtrack retained. The 17-frame LTX run produced 10-bit HLG, 17 tagged
ACEScg EXRs (sampled values up to 5.34), and audio with peak correlation 0.992
at a one-sample offset at 16 kHz. It completed in 48 s. Source fps was
24000/1001; Comfy's video writer represented output as 23.976 (2997/125).
The HDR saver now losslessly remuxes using the source's reconstructed rational
rate and verifies video count, colour metadata and audio. A real Comfy CPU graph
produced 17 frames at exactly 24000/1001, 10-bit Rec.2020 HLG, with audio;
an independent FFmpeg regression confirmed identical decoded frames and audio
across the remux. FFmpeg is required for this output step.
The source publisher warns about mastering, and the test does not qualify HDR
colour accuracy or representative camera content. The original was untouched.

This test revealed that AAC at fractional frame rates could decode a valid
range up to 32 samples short. The audio loader now reads an additional source
frame before trimming to the selected exact sample count, permits at most 1 ms
of timestamp-related padding at an actual audio end, and rejects larger gaps.

The latent was subsequently regenerated with the same seed and saved once;
all short-decode variants below use that same saved latent. Sampling took 63 s.
Temporal VAE tiles of 32/8, 64/16 and 64/32 decoded in 24, 30 and 36 s
respectively. The 32/8 result visibly smeared pedestrians at tile boundaries;
64/16 and 64/32 reduced but did not eliminate visible distortion. A private
64/16 decoder selecting a single tile at each midpoint instead of blending
also distorted moving people and increased one transition's mean adjacent
SDR RGB difference from 7.99 to 9.78/255. The earlier 128-frame reference came
from a separate sample, so its pixel differences cannot isolate decoder effects.
These results do not justify substituting any short decode mode for the existing
quality path or lifting the Studio cap.

A 96/32 decode of the same saved latent took 33 s and looked cleaner at the
sampled moving-person boundaries than the smaller tiles; a full-motion SDR
side-by-side was prepared for artist review. A separate delivery graph using
that saved latent produced 129 10-bit Rec.2020 HLG frames, 129 tagged ACEScg
EXRs and source audio in 36 s. Sampled EXRs were finite and reached 1.07 in
scene-linear highlights. Audio decoded to the same sample count as the source
with 0.99935 zero-lag correlation. A targeted cancel during active GPU decode
produced `execution_interrupted` and no final output, after approximately 28 s.

An inspection of 206 video files in the shared Comfy input folder found none
tagged HLG or PQ. The source for the above experiment was converted from SDR,
and cannot establish colour accuracy on actual HDR camera footage. The 96/32
workflow remains internal pending motion review, representative HDR footage,
and a complete UI integration and validation; the 121-frame public cap remains.

The 40-million padded-pixel-frame guard is a separate, often stricter limit:
1920 × 1080 pads to 1920 × 1088, allowing at most 17 frames (0.71 s at 24 fps).
The official sampler's temporal windows bound inference VRAM, but Studio's
current loader, resize and decode nodes still materialise full video tensors in
system RAM. At 129 frames a single 1080p float RGB tensor alone is ~3.23 GB,
before other full-size copies, model weights, or EXR and ZIP disk space. A
larger 1080p limit needs conservative RAM/disk preflight and representative
GPU testing; the low-resolution test does not establish it is safe.

A private 25-frame 1920 × 1080 test of the PQ sample temporarily raised only
the isolated process's pixel bound to 60 million. Its two 17-frame temporal
windows and 32/8 VAE decode produced 25 frames at 24000/1001, 10-bit HLG,
25 ACEScg EXRs and source audio. Sampled free system RAM fell from 34.2 to
12.95 GiB, peak GPU allocation was 15,308 MiB, and elapsed time was 160 s.
Audio correlation peaked at 0.9968 with zero lag at 16 kHz. This is one test on
potentially mis-mastered footage, not a quality or hardware compatibility
guarantee. The public 40-million-pixel and 121-frame limits are unchanged.

`hdr_1080_preflight.py` is a private, unregistered resource gate reflecting
that single measurement. It accepts only 18–25 frames at exactly 1920 × 1080,
an idle target queue, at least 32 GiB available RAM, 15,500 MiB total and
14,500 MiB free GPU memory, and 10 GiB free in both temp and output storage.
It provides a signal to stop only the caller's own active job below 6 GiB
available RAM. Fresh measurements, orchestration, a working video UI and
broader testing are still required before this can be used publicly.

An additional isolated test used a real PQ/Rec.2020 10-bit, 360 × 640,
241-frame clip from the [CHUG HDR-UGC research dataset](https://www.colorado.edu/lab/live/chug-crowdsourced-user-generated-hdr-video-quality-dataset),
provided by the Laboratory for Image and Video Engineering at UT Austin. The
sample is a low-bitrate transcode; its copyright notice accompanies the private
sample and test outputs. The experimental 121-frame, 65-frame temporal-window
graph completed in 117.44 seconds and delivered 121 10-bit Rec.2020 HLG frames.
The source had no audio. The MP4 output retained its requested average duration
to within 0.060 ms, with no frame loss. Sampled SDR previews show scene details
changing and a different appearance; the previews use different tone-mapping
paths, so they do not isolate colour accuracy. Full-motion artist review and
representative higher-resolution HDR tests remain outstanding.

This source exposed a saver failure with the unusual rational frame rate
6007500/200273. MP4's default video timescale rounded the final frame duration,
causing the previous strict equality check to reject the otherwise valid file.
The saver now requests a track timescale matching the reconstructed rate and
accepts at most 1 ms total duration error, while still checking frame count,
colour tags and audio track count. Real FFmpeg regression tests preserve every
decoded frame and audio sample; common rates remain exactly represented.

The CHUG reference version of that same scene was also tested at its original
1080 × 1920 raster. A 17-frame public-limit GPU graph produced 17 correctly
tagged 10-bit HLG frames with 0.009 ms total timing difference, in 120.65 s;
available system RAM fell to at least 16.49 GiB. This silent sample does not
qualify audio, longer 1080p clips, or colour appearance on an HDR display.
The dataset notice is saved alongside both the sample and generated test files.

A preallocated source-loader variant was compared with the existing loader in
separate 64-frame 512 × 512 synthetic CPU processes. Peak RSS growth was
approximately 391 MiB versus 393 MiB, with both taking 0.44 s in this test.
That measurement does not establish a useful memory or speed improvement, so
the change was not retained and the HDR limits remain unchanged.

## Synthetic GPU smoke tests (30 October)

An isolated 9-frame, 96 x 64 HLG/Rec.2020 synthetic fixture completed targeted
paintout on the LTX 2.5 int8 model with the installed Obscura adapter and an
experimental substitution of the full video VAE for the absent conv VAE. The
render took 174.56 seconds, produced nine float32 ACEScg EXRs and a 96 x 64,
24 fps, 10-bit HLG/Rec.2020 MP4. It does not qualify the visual repair or
performance with representative footage. The full clean-plate adapter remains
missing and its HDR path has not been tested.

A separate 9-frame HDR frame-extension experiment completed in 140.27 seconds
at 192 x 128, producing an SDR viewing proxy and an explicitly unverified
ACEScg EXR archive. The experiment used the installed
`ltx-2.3-22b-ic-lora-outpaint.safetensors` adapter in place of the unavailable
filename in the experimental builder; the diffusion model was LTX 2.5. The
synthetic result is not representative of real scenes and does not establish
HDR colour or visual quality. This path is not exposed in Studio.
The integrated targeted HDR paintout workspace now falls back to the full VAE
when the preferred conv VAE is unavailable, records that choice in the run
configuration and labels it experimental. It does not make this substitution
for SDR or full clean plate. The Studio integration has automated coverage and
model-discovery was checked against the test server; artist-quality review on
representative HDR footage is still outstanding.

The separate black-video guidance HDR experiment now reuses the user's approved
SDR expansion recipe, with the native HDR loader, ACEScct canvas and full VAE.
A 9-frame synthetic GPU smoke test completed in 37.78 seconds with the model
already cached, writing an SDR proxy and explicitly unverified EXRs. This is
not comparable to cold-load timings and does not verify the generated scene.
A separate real-PQ-footage experiment was subsequently evaluated below.
The black-guide variant also completed nine frames of real PQ/Rec.2020 source
at 448 x 704 in 36.7 seconds with cached models. Its SDR proxy retained black
margins through the first and final frames instead of filling them. This is a
failed outpaint result and must not be exposed as a working HDR mode. The
fixture was a 24-fps transcode of the CHUG sample cited above; this short,
silent test does not qualify colour or temporal continuity.
On the real PQ fixture, using the black-guide outpaint adapter with the masked
recipe produced a green border. The intended 1.31 GB LTX 2.3 in/outpaint LoRA
was subsequently downloaded (no LTX 2.3 base model) and tested with LTX 2.5.
Its nine-frame SDR proxy filled the border; this is promising but remains a
short, low-resolution test of the masked recipe, which the user had previously
preferred less than the SDR black-guide method. HDR accuracy and the animated
result require further review before exposure.
A subsequent 25-frame PQ test with the intended masked adapter filled the
borders but substantially changed the centre of the frame. An experimental
linear-light, 16-pixel seam composite was added and unit tested. A separate
nine-frame end-to-end GPU render at 448 x 704 completed in 149.6 seconds
from cold loading; its first, middle and final checked EXR frames matched the
source exactly in the interior more than 16 pixels from the seam. This says
nothing about seam appearance, motion, HDR monitor quality, or audio; the
composite remains internal and is not a verified Studio HDR outpaint mode.

The private outpaint experiment now has an explicitly unverified 10-bit HLG
output option alongside its EXR archive. A CPU-only live Comfy graph reloaded
nine previously generated 448 x 704 ACEScg EXRs and muxed an independent
24 fps audio fixture. FFprobe reported nine frames, 24 fps, 0.375-second video
and audio, yuv420p10le, BT.2020 non-constant-luminance and HLG transfer tags.
Audio cross-correlation peaked at zero samples with a 0.9998 normalised score.
This validates the delivery nodes on generated frames, not end-to-end model
colour, seam quality, representative motion or an HDR display. The route stays
internal until those remaining checks and Studio integration are complete.
The same independent outpaint delivery check was repeated at 24000/1001 fps
with a five-frame audio offset. It saved nine frames at the requested rational
rate and 0.375375-second duration; correlation against the correctly offset
source peaked at zero samples (0.9973). No video model was rerun in that check.
Recompositing the existing 25-frame generated EXRs through the live CPU graph
produced a 25-frame SDR preview and EXR archive without another model run.
The generated borders remain visible, but the first/middle/final SDR contact
sheet still shows a scene mismatch at the edge; this does not meet the visual
bar for exposing HDR outpaint. More representative resolution and seam work are
needed, and the user previously preferred the black-guide SDR method.
# Native HDR timeline selection (internal)

An experimental native HDR selector now maps output timestamps to the
corresponding source frames at different constant frame rates, without an SDR
intermediate. It rejects selections extending past the source and leaves
inference padding to a separate stage. CPU tests cover fractional and mixed
rates, a non-zero trim, and a synthetic 60 fps 10-bit video with an explicit
HLG colour interpretation. An internal short outpaint graph now uses this
selection, checks reviewed settings, pads only for inference and trims before
SDR preview, HLG and EXR delivery. A synthetic PCM test confirms a non-frame-
aligned audio start and exact output sample count. This is not exposed in
Studio: individual-node tests do not establish model output quality. An
experimental HDR review graph now uses the same native timeline selector and
canvas as the render instead of the SDR review graph. Its approval key also
binds the chosen colour interpretation. A synthetic 60 fps test compares every
selected HDR canvas frame and mask before and after inference padding. Real
footage, audio, sequence input, final HDR output and visual quality still need
an end-to-end render. A CPU-only synthetic 60 fps fixture also exercises
native selection, canvas expansion, HDR compositing and ACEScg EXR packaging:
the archive contains exactly the four selected frames, preserves the source
centre and retains a generated 4.0 scene-linear highlight. This substitutes
synthetic pixels for model inference and does not qualify visual quality.
The internal review and render graphs also accept a checked EXR manifest; the
approval binds its colour choice and sequence frame rate. A CPU fixture checks
12-to-24 fps selection, ACEScg highlights and rejection of changed frames. Auto
colour detection reads every EXR's tags, so it also verifies every file hash;
this can add noticeable time for large sequences. The route is not yet
exposed in Studio or qualified with a model render.
The HDR review path was also executed on CPU with the installed Comfy and LTX
nodes: a synthetic 60 fps source produced a nine-frame, 24 fps tone-mapped mask
preview at the requested 192 × 128 canvas size. This checks node compatibility
and saved timing; it does not verify the model-generated scene or a desktop UI.

An offline comparison re-composited the saved 25-frame PQ outpaint using 16,
32, 64 and 96 pixel feathers at the first, middle and last frames. Wider
blending softens the transition but does not resolve the changed scene content
or the visible rectangular boundary, and also affects more of the source.
The result remains unqualified; the comparison is saved as
`openjutsu-benchmark/hdr-outpaint-feather-comparison.png`. Further model or
guidance work is needed rather than merely increasing the feather.
The experimental HDR composite previously feathered into the black padded
canvas, darkening generated edge pixels. It now keeps the generated area intact
and feathers only within the source region. Tests verify this invariant and
preservation of the source away from the seam. A saved-frame comparison at four
feather widths removes that particular black-padding contribution, but the
scene still mismatches at the boundary; this is not a visual approval.


## Matched black-guide HDR comparison (30 October)

A 25-frame 448 × 704 PQ-source test used the same source, crop geometry, prompt
and seed as the prior official masked comparison. The LTX 2.5 black-guide graph
completed in 130.46 seconds on the RTX 4080 and generated 25 frames, but the
SDR viewing proxy retains broad black borders where the extension should be.
The official masked graph fills those areas but still exhibits an obvious
boundary and colour mismatch. Neither result qualifies HDR frame extension for
Studio. Comparison: `openjutsu-benchmark/hdr-outpaint-black-vs-official-25.png`;
the HDR EXR archive remains an unverified internal test artifact. These are
not native HDR-display visual evaluations.


## SDR-first HDR outpaint experiment (30 October)

A new internal two-pass LTX 2.5 test tone-mapped the 25-frame PQ source to
sRGB, ran the artist-preferred SDR black-guide outpaint (126.03 s), converted
that result using the LTX 2.5 SDR-to-HDR adapter, then composited the original
PQ source into the ACEScct result (114.85 s). This filled the black borders
seen in the direct HDR black-guide test. The silent 448 × 704 result contains
25 frames at 24 fps; its video is 10-bit Rec.2020 HLG and the archive contains
25 ACEScg EXRs. Against independently reloaded original PQ source, the EXR
interior had mean absolute linear error 0.000075 and maximum error 0.00388,
consistent with half-float storage; a sampled highlight remained 15.42. The
working intermediate is an SDR H.264 file, so the newly generated borders
are reconstructed HDR, not recovered source highlights. The tested composite
is silent, short and low resolution. Motion, seam quality, source-audio
delivery, long sections, larger canvases, and native HDR-display appearance
remain unqualified. It is not exposed in Studio. Compare SDR viewing proxies
at `openjutsu-benchmark/hdr-sdrfirst-final-comparison.png`.

The internal two-stage builders now use native HDR timestamp resampling and can
restore source audio to the HDR output and SDR preview. A real ComfyUI
engineering graph selected 25 output frames at 24 fps from HDR-tagged 30 fps
footage starting at 0.5 seconds. Its chirp audio measured zero sample lag and
0.99987 correlation at 24 kHz. This only validates timeline and audio plumbing;
the earlier model-generated two-stage HDR outpaint test remains silent and
unapproved.

A second two-stage model test used a PQ-tagged 1920 × 1080 source with audio
and a 1088 × 640 canvas. The SDR outpaint stage took 52.33 seconds and the
HDR conversion and composite stage took 48.30 seconds. The output has nine
frames at 24 fps, 10-bit Rec.2020 HLG video and an audio stream. Its first
0.375 seconds of decoded audio correlated 0.9956 with the source at zero
lag. The archive contains nine ACEScg EXRs; a centre-region comparison of
the middle frame with independently resampled original HDR measured mean
absolute linear error 0.000015 and maximum 0.000827. This is a short
engineering test, not a 1080p, long-clip or HDR-display
quality approval; generated borders remain reconstructed from SDR. The
experimental workflow remains unavailable in Studio.

The two-stage experiment also accepts an exact start time, so a future Studio
handoff can use the same fractional trim for the SDR guide, native HDR centre
and original audio. Graph tests cover this alignment and reject invalid times.
A nine-frame GPU test at 1088 × 640 used a 0.517-second trim from the
24000/1001 fps PQ source. The two stages took 51.66 and 57.04 seconds;
the middle EXR centre matched the independently resampled original with mean
absolute linear error 0.0000148 and maximum 0.000746. Decoded output audio
correlated 0.9953 at zero lag with the same source trim. This verifies the
short experimental path, not Studio integration, long-clip continuity or
HDR-display quality.

The user accepted the visual comparison for further development. Internal
builders now bind both stages to the reviewed HDR canvas, exact selection and
colour, pad the source for inference, hold the final delivered image to 8n+1,
and pad source audio to match. Graph tests cover review invalidation, exact
trim, connections and tail handling. These builders currently support bounded
video canvas expansion only; they are not yet wired into Studio or tested by
a new end-to-end GPU run.
Review also checks the original HDR source's pixel-frame budget, not only
the output canvas, so a small output cannot bypass the native decode limit.
The private two-pass coordinator now rechecks approval before the HDR pass,
cleans up its owned intermediate, and targets only its active job on failure
or cancellation. Six asynchronous tests cover sequential submission, changed
selection, connection failure, and cancellation including the submission
race. This coordinator is not yet wired into Studio.
Asset validation and graph construction run off the async event loop; a
blocking-source test confirms cancellation remains responsive while a source
check is in progress.
An internal artifact validator now checks job-owned paths, video raster,
frame count, audio track, 10-bit Rec.2020 HLG tags and the EXR archive frame
sequence before delivery. Unit tests reject wrong paths, SDR tags and missing
frames; a copy of the actual nine-frame output passed these checks. The
validator checks the archive's frame names and sizes, not every EXR's pixels,
and is now used by a private Comfy queue adapter. Queue tests cover validated
outputs, failures, ownership of intermediate cleanup and prompt-specific
cancellation. The adapter is connected to an internal frame-extension job
with an approved HDR review key and returns the preview, HLG and EXR references
only after validation. Mocked job tests and the existing long-SDR job tests pass.
The review and render handlers also support an explicitly enabled internal
test route (`ZURA_HDR_OUTPAINT_EXPERIMENT=1`); it is disabled by default.
Tests check the gate, approval and automatic source
audio detection. The route has not been tested end to end on the GPU.
The test-only capability now enables an HDR output checkbox in the existing
frame-extension composer. It limits the trim to the bounded HDR route, blocks
the SDR long-clip option, labels reconstructed borders, and offers HLG and EXR
downloads alongside the SDR preview. DOM tests cover these controls and the
capability gate; the normal default remains hidden. Model setup now derives
the required files and nodes from the review and both render graphs, and the
backend checks them before queuing. Tests cover the outpaint adapter, HDR
adapter, conditioning and required nodes. Desktop visual and GPU checks remain
pending.
The guarded interface now computes the padded software frame limit from both
source and canvas dimensions before review. At 1920 × 1080 source resolution
the current budget permits 17 frames; larger sources may be rejected even when
the output canvas is small. It labels this as a software limit, not a hardware
guarantee. DOM tests cover over-limit and corrected selections.
The internal job hand-off was exercised with copies of the real nine-frame
1088 × 640 HDR output, SDR preview, EXR archive and intermediate. Queue
submission was simulated, while the actual artifact validators checked the
files and the owned intermediate was removed afterwards. This is not a new
model render or a desktop Studio test.
An internal HDR review submission now queues the HDR canvas preview and binds
its approval to source, geometry, timing and colour space. Mocked queue tests
check that changing colour after approval is rejected and that preview status
returns the correct job-owned output. Normal Studio remains gated.
The reviewed 12-frame graph pair was checked against the live isolated
ComfyUI `/object_info`: all 27 first-pass and 39 second-pass node types and
required inputs are present. This schema check is not a model render.
An attempted reviewed 12-frame GPU run on the isolated 8336 test instance
did not complete: its log reported DXCore and WDDM VRAM query failures and
then a fatal Python abort during model loading. The server stopped answering
requests and no reviewed-stage output was produced. A fresh CUDA process had
reported free VRAM immediately beforehand, so that check alone did not prove
the existing Comfy process healthy. Investigate the GPU/Comfy runtime before
repeating this test; no new HDR quality or Studio integration claim follows.
The installed ComfyUI exposes `--disable-dynamic-vram` as an alternative
model-loading mode. It has not been tested for this path, and could change
memory and speed behaviour; no user instance was restarted or reconfigured.
An isolated 8337 instance using `--disable-dynamic-vram --lowvram` loaded the
test route and completed the real 12-frame HDR review. The render reached CPU
text encoding, but after 447 seconds available system RAM had fallen below
8 GB. The specific test job was cancelled, Comfy confirmed cancellation and
the idle test models were unloaded. No rendered output was produced; this
alternative mode is not a qualified speed or quality solution.

Private long-HDR planning now binds the whole selection and colour space and
calculates overlap windows against both the original HDR source and the output
canvas, including 8n+1 temporal padding. Tests check the full range and window
timing. This is planning only: an anchored HDR executor, blended joins and
their visual validation remain outstanding, and no longer HDR option is exposed.
An internal per-section graph can now add an aligned previous-frame I2V anchor
while retaining the HDR source guide, and trims inference padding before
assembly. Tests bind the section to the full review and reject unsafe anchor
paths. This is a graph test, not evidence of a smooth rendered join.
The complementary conversion graph now takes each time-aligned range from the
assembled SDR video, restores the corresponding original HDR centre and can
stage ACEScct frames through the existing HDR chunk writer with an I2V
continuation anchor. A structural test confirms its chunk plan matches the
writer's plan. Execution, exports and visual continuity are still unverified.
The private SDR first-pass runner now uses the existing overlap assembler and
aligned anchors. A CPU test with generated section videos verified the 24-frame
selection is assembled as 25 frames with the final hold; it does not test model
quality. Both HDR and SDR-preview exporters now accept the exact trim start in
seconds. Non-periodic audio tests measured alignment within one sample at a
0.517-second start. The full two-stage long runner remains unconnected.
An internal streaming delivery wrapper now appends only the final required
held frames after HDR section blending, then exports HLG, EXR and an SDR
preview with the exact audio start. A real CPU media test checked 24-to-25
frames, EXR count, both video counts and audio alignment; cancellation waits
for the active export and removes files this job published. This does not
validate model-generated long-section joins or wire the route into Studio.
The private long conversion factory now validates the assembled SDR file,
review key, source audio and disk budget, then uses the existing cancellable
HDR chunk renderer and streaming delivery. A real-media preflight test checks
the held intermediate, section timing, audio detection and path boundary. No
end-to-end GPU test or public Studio route has been run for this composition.
A private parent job now joins the first pass and HDR conversion and reports
their separate progress. Tests cover cancellation during conversion and while
preparing its staging, plus cleanup after a failed first pass. Adapters still
need to connect this parent to real Studio jobs; no long HDR render or visual
join acceptance has been established.
A private Comfy adapter now submits owned SDR sections, extracts aligned
anchors, validates each child, assembles them and hands the result to the HDR
conversion factory. It preflights disk space and removes only its own verified
child files and anchors. A CPU integration test uses real encoded video and
anchor extraction with simulated model completions; actual GPU execution,
end-to-end cancellation and visual joins remain unverified. It is not a
registered Studio route.
Full-range HDR review graphs and a private review assembler now bind every
section to the same source, timing, geometry and colour. A CPU media test
assembled a 24-frame review without adding inference padding; review children
were simulated. A real review render and Studio route remain outstanding.
The private Comfy review adapter now submits and validates each review child,
assembles the full-range preview and removes owned child files. A CPU test
used real encoded review sections with simulated Comfy completions. A separate
test route requires both `ZURA_HDR_OUTPAINT_EXPERIMENT=1` and
`ZURA_HDR_OUTPAINT_LONG_EXPERIMENT=1`; tests check the gates and approval. No
normal Studio control enables it. GPU and desktop checks remain outstanding.

### Isolated HDR integration test, 30 October

Port 8338 used a fresh isolated ComfyUI instance with dynamic VRAM disabled and the normal memory policy. With approximately 25 GiB of available RAM, the real 1080p PQ source upload and 12-frame selection review completed. The outpaint render was cancelled during model loading when available RAM dropped below 8 GiB; it briefly fell below 1 GiB before cancellation completed. No video result was produced. Its idle model cache was unloaded afterwards. This is not a completed end-to-end render and should not be represented as one. A further model run requires a materially safer memory margin or an identified lower-memory configuration; do not repeat this loading configuration under similar conditions.

Long HDR delivery now checks that its owned HLG and preview videos match the expected dimensions, frame count, audio tracks and frame rate, verifies HLG colour metadata, and checks the EXR sequence before exposing a completed result. These checks passed focused unit tests; a complete long model run still needs verification.

A second isolated 8338 attempt started with about 44 GiB free. During the outpaint model load, available RAM fell below the 12 GiB stop threshold and continued falling while ComfyUI could not interrupt its synchronous load. The explicitly identified isolated 8338 process was stopped to protect the machine; free RAM recovered to about 46 GiB. No render was produced. Normal ComfyUI processes were left running. The log showed the 10 GiB text encoder and 20 GiB INT8 video model in the same phase. Do not repeat this configuration without addressing the loading peak and cancellation latency.
The longer-delivery validator was also exercised on copies of the previously generated nine-frame 1088 × 640 HLG video, SDR preview and EXR archive with audio. All three passed the actual media checks. This validates the delivery gate with real artifacts, not a new long render.

The installed ComfyUI's default RAM-pressure cache retains node results until memory pressure, and it also enables pinned host memory unless `--disable-pinned-memory` is set. The installed CLI offers `--cache-none` and `--disable-pinned-memory` as separate, documented alternatives. These are hypotheses for lowering the peak, not measured fixes. The observed cancellation could not stop a synchronous model load, so any further isolated benchmark must use an external, process-specific memory watchdog capable of terminating only that disposable test instance before available RAM reaches a critical level. Do not apply these flags globally to the user's normal instance without measuring their speed and memory effects.

An isolated watchdog test on port 8339 tried `--disable-dynamic-vram --cache-none --disable-pinned-memory` with 43.5 GiB free initially. The real HDR upload and selection review completed, and the video model loaded and reached the start of sampling. Available RAM dropped to 20 GiB, where an external process-specific watchdog terminated that disposable server immediately; after cleanup 44.5 GiB was available. No model output resulted. This test does not show what the eventual peak would have been, or establish a safe setting. The normal ComfyUI instances were not stopped. A lower-memory graph or measured loading strategy is still required.

A private `split_prompt_graph` prototype now moves the existing positive and negative `CLIPTextEncode` nodes into a separate graph using Zura's existing tensor-only prompt cache. The video graph consumes the saved conditioning while retaining the same frame-rate conditioning. Tests verify the actual outpaint graph, unchanged input prompts, valid links, and rejection of unexpected consumers. No shared Comfy model is unloaded by this helper. A safe queue handoff, cache ownership/cleanup, GPU memory measurement and output equivalence test are still required before this can be enabled.

An isolated 8340 benchmark ran the split prompt graph on the same real nine-frame source and prompt. Text encoding completed in 18.1 seconds, then the idle test instance was asked to unload its models before the video graph. The video graph reached sampling without loading the text encoder, but available RAM still fell below the 20 GiB watchdog threshold from approximately 40 GiB at startup. The watchdog stopped only the isolated instance; the unique prompt cache was removed and free RAM recovered to 38.6 GiB. No video output was produced. Splitting the prompt therefore does not establish a sufficiently safe memory improvement on this machine, and remains an unexposed prototype.

The explicitly gated HDR frame-extension prototype now supports returning a verified HDR video from the import screen. It reuses the Studio asset validation, preserves HLG/PQ input colour in the reviewed job, blocks duplicate interactions during handoff, and retains the existing source if validation fails. Interface tests cover the handoff and unsupported-colour failure. This is not enabled in normal Studio and is not a GPU or desktop qualification.

The earlier successful nine-frame SDR-first and HDR-composite engineering runs in `hold-8336.stderr.log` used ComfyUI's dynamic VRAM loader, whereas the recent watchdog runs used `--disable-dynamic-vram`. The later 8336 failure occurred after several successful runs and reported a DXCore/WDDM query failure. A fresh isolated dynamic-VRAM benchmark may behave differently, but it has not yet been run and is not guaranteed safe. Any comparison must retain the external memory watchdog and must not use an active user GPU session.
A real 1920 × 1080 PQ-tagged video passed upload and the unchanged HDR source-validation endpoint used by the new frame-extension handoff on isolated ComfyUI port 8337. It returned the uploaded asset and `pq_rec2020` as expected. This checks the backend contract only, not the revised desktop interaction or a model render.

A fresh isolated dynamic-VRAM test on port 8341 completed HDR source review, then reached the 20 GiB watchdog threshold during video-stage loading from approximately 28 GiB available; the isolated instance was stopped, so there was no rendered output. Four previously created idle test instances were also stopped after checking their queues and process identities; the unrelated and previously blocked user/test instances were not restarted or stopped. The crashed 8336 process had already exited by the time cleanup was attempted. This test does not measure dynamic-VRAM peak memory or establish a successful render.

A fresh dynamic-VRAM run on isolated port 8342 completed the real reviewed short HDR frame-extension route from a 1920 × 1080 PQ video with audio. Twelve selected source frames produced 17 delivered 512 × 320 frames, 10-bit Rec.2020 HLG video, SDR preview and EXR archive. The model passes took 40.91 and 31.35 seconds; the review took 6.60 seconds. Available RAM remained above the 12 GiB process watchdog. This confirms the route and its output validation at a small output raster, not 1080p output quality.

A second dynamic-VRAM run on isolated port 8343 completed the experimental full review and two-section HDR frame-extension route from the same PQ source. Twenty-four selected frames produced 25 delivered frames, 512 × 320 10-bit Rec.2020 HLG HEVC, audio, preview and EXR archive. Per-section model passes took 41.70, 19.18, 29.00 and 19.62 seconds, after 9.09 and 8.28 seconds of review. The new final-delivery validator accepted the real files. This one-second engineering run does not qualify long-form continuity, full-resolution output, HDR-display appearance or the desktop UI. The job previously reported a stale `converting_hdr` stage after completion; the local job now returns `complete`, and its queue test passes.

An isolated 8344 run exercised the same full-review, two-section HDR frame-extension route at 1088 × 640 using the real 1080p PQ source with audio. It delivered 25 frames at 24 fps as a verified 10-bit Rec.2020 HLG HEVC, an SDR preview and a 25-frame EXR archive. Review sections took 10.59 and 9.42 seconds; the two outpaint passes took 51.06 and 29.62 seconds, and the two HDR passes took 53.41 and 36.97 seconds. The process watchdog remained active at 12 GiB; sampled available RAM briefly reached 12.1 GiB. This is still a one-second engineering run, not a full-resolution or long-form visual qualification. Preview: `hdr_outpaint_7f8431d5761149eeb630b04be9d6327b_preview.mp4` in `openjutsu-benchmark/hdr-shared-long/output/genj/hdr`.

The artist identified a visible seam around the original footage in the 1088 × 640 preview. Inspection found that the old blend alpha jumped from about 0.5 inside the source edge to 1.0 outside it. The experimental HDR composite now ramps to 1.0 at the inside edge while leaving the exterior entirely generated and the source interior untouched. A linear-light synthetic test verifies edge continuity and source preservation; the change has not yet been visually qualified on a new generated output. A 1920 × 1088 two-section test and a nine-frame 1088 × 640 retest were both stopped by the 12 GiB watchdog during model loading, so neither produced an image. Do not treat the earlier artist acceptance as acceptance of this newly observed seam.

A CPU reconstruction of frame 12 from the previously rendered 1088 × 640 EXR and its independently loaded PQ source estimated the effect of the revised edge blend without running the model. On the sampled horizontal boundary, mean absolute linear-channel change between adjacent rows fell from 0.02184 to 0.00338. This reconstruction infers hidden generated pixels from the previous composite, and is not a newly generated result. Visual inspection still shows a broader tonal boundary, so the seam remains unresolved and requires real-render and artist review; the numeric edge reduction alone is not acceptance.
The revised inner-edge ramp also passed synthetic linear-light tests at all four sides and two corners, with exact source preservation away from the transition. On the original unmodified output, decoded HLG and the SDR preview both show a larger average adjacent-row change at the measured source edge than their neighbouring rows; this is evidence of an encoded boundary in both deliveries, but not a perceptual assessment on an HDR display. The user has the original HLG and EXR files for that assessment. No revised model render has yet completed.
The same single-frame CPU reconstruction measured smaller mean adjacent-pixel changes on all four plate edges after the proposed ramp: top 0.021842→0.003378, bottom 0.015104→0.004891, left 0.009524→0.002201, right 0.017056→0.006864 in linear ACEScg. These are estimates reconstructed from a previously composited EXR; they do not measure perceived HDR seam quality, and broad colour differences remain visible in the SDR proxy.
For the remaining representative long-form HDR test, the existing `chug-hdr-reference-1080.mp4` fixture is a 1080 × 1920, approximately 8.03-second PQ/Rec.2020 10-bit source with 241 frames. It has no audio stream; a separate 129-frame 384 × 216 HLG fixture has audio. This metadata check does not qualify either input for the full frame-extension workflow.
The long HDR frame-extension composer now reports its calculated number of overlapping sections and the two generation passes per section before submission. The 1080 × 1920 PQ fixture's 193-frame selection computes 21 sections in both the backend planner and interface test. If the artist trims back to a single-section range while the long option remains selected, the UI now submits the short route and requests its matching dependencies instead of failing with a long-route error. Interface tests pass; a desktop check and full 21-section render remain outstanding.
A boundary regression verifies that a 17-frame HDR selection uses the single-section route, while 18 frames selects and displays two overlapping sections at the 1080p source budget. This is a planning/UI check, not a render.
Sectioned HDR outpaint now reports a phase-only time estimate after it observes a completed section, counts it down during the current section, resets it when conversion begins, and clears it on cancellation. The backend now reports the current HDR conversion section rather than the number already completed. UI and backend tests cover these transitions; no end-to-end timing claim is made.

After closing four additional idle test instances owned by this task, the 1088 × 640 revised-blend render was retried on isolated port 8347. It again reached the 12 GiB watchdog during model loading and was stopped without producing output. Other ComfyUI instances belong to a separate workspace and were left running. The revised seam remains unqualified on an actual rendered clip.

A separate CPU-only local-colour-match experiment was evaluated on one reconstructed frame, without changing the shipped or experimental Studio graph. It estimates a bounded ACEScct colour offset from the inside seam, extends it into a fading band outside the plate, then applies the revised ramp. On this single inferred frame, the sampled top-edge linear jump was 0.00218 versus 0.02184 in the old composite, and a central source region differed by at most 7.4e-7. The SDR proxy looked smoother, but reconstruction, highlights, motion, temporal stability, other scenes and native HDR viewing are unverified; this is an experimental idea, not an implementation or approval.
A full isolated-per-file run of the `test_hdr*.py` unit suites passed after the seam and handoff changes. The optional live-readiness suite was not configured and was skipped. These are automated checks, not visual approval, a new GPU render, or proof of native HDR capability in every LTX mode.

An isolated 8348 rerun completed the revised-ramp short HDR path using the real PQ source at 1088 × 640: nine frames, 10-bit Rec.2020 HLG with audio, EXR and SDR preview. The outpaint and HDR passes took 47.80 and 37.67 seconds, respectively. This is a fresh 0.375-second single-section render, not a like-for-like long-section A/B; a broader tonal transition is still visible in its SDR preview. The user must judge the HLG master on an HDR display. It does not establish temporal continuity or full-length quality.

A fresh isolated 8349 run completed the revised edge ramp through the full three-section HDR path at 1088 × 640. The 1.4-second selection contained 34 source frames and delivered 41 frames at 24 fps, holding the final frame to the model's 8n+1 count; it includes 10-bit Rec.2020 HLG, EXR, audio and SDR preview. Review sections took 19.89, 22.35 and 21.08 seconds; outpaint sections took 67.27, 32.84 and 32.73 seconds; HDR sections took 50.43, 42.96 and 41.58 seconds. The generated HLG master is `hdr_outpaint_60e2fce82f754b31bfe7e43e19c01cd5.mp4`. The SDR preview still shows a broader tonal transition near the edge. Native HDR display, the full user-requested clip length and 1080p output remain unqualified.

The real 34-frame, 41-frame-delivery HDR frame-extension test revealed that its source audio continued into held frames: zero-lag correlation was 0.99691 over the selected range, but the held tail RMS was 0.0417. The long-HDR export now trims audio to the exact requested duration before padding to the held video length for both HLG and SDR preview. A real FFmpeg export test with a non-zero start and fractional 0.93-second selection confirms aligned audio and a silent held tail; existing HDR video/preview suites pass. The earlier shared HLG file still contains that extra audio and has not been modified. A new model run using this change remains outstanding.
# HDR seam diagnostic

## 31 October: bounded colour correction and fresh delivery check

The experimental SDR-first HDR compositor now accepts an optional `colour_match` strength. It estimates a bounded ACEScct offset from the source-side seam ring, smooths it over three frames and fades the correction into the generated border. Black padding is excluded. Existing graphs retain the disabled default; only the gated HDR outpaint experiment enables it. Six CPU tests cover edge behaviour, temporal smoothing, absent references, strength validation and unchanged source/distant pixels.

An isolated port-8350 comparison reused the exact same nine generated SDR frames and HDR seed at 1088 × 640. Both versions delivered valid 10-bit Rec.2020 HLG and nine ACEScg EXRs. Across all nine EXRs, source-interior pixels and generated pixels beyond the correction band were byte-for-byte unchanged. Mean adjacent-pixel boundary steps fell by approximately 30–41% across the four sides. The SDR contact sheet looked smoother, but these measurements do not establish HDR-display acceptance or remove geometric differences. The two conversion timings are cache-dependent and are not a speed comparison. Evidence: `hdr8350-colour-results.json`, `hdr8350-colour-metrics.json` and `hdr8350-colour-contact.png` in the benchmark folder.

A fresh isolated port-8351 run then completed the full reviewed three-section route with this correction and the exact-duration audio fix. Its 1.4-second, 34-frame PQ selection delivered 41 frames at 24 fps, 1088 × 640, as HLG video, SDR preview and an archive of 41 EXRs. FFprobe confirmed `yuv420p10le`, Rec.2020 and HLG tags. Both delivered videos have a silent held audio tail (measured RMS 0). Master: `hdr_outpaint_a03913f5ebd346bf81f3101232bb2a43.mp4`; delivery evidence: `hdr8351-delivery-check.json`. The owned test server stopped after completion. Native HDR viewing, full-length and 1080p quality remain unqualified; the experimental gate stays in place.

Four frames (0, 10, 20 and 30) of the 41-frame experimental HLG/EXR output
`hdr_outpaint_60e2fce82f754b31bfe7e43e19c01cd5` were checked in the
scene-linear ACEScg EXR frames. At the expected top boundary, the mean RGB
step was approximately 0.0055, 0.0031, 0.0026 and 0.0874 respectively.
Neighbouring rows also vary substantially on frame 30, so this measurement
does not isolate a compositor discontinuity or establish perceptual quality.
The test confirms only that the master was inspected, not that the visible
colour seam is absent. HDR-display artist review remains required.
# Native first/last HDR endpoints: 31 October 2026

The opt-in `ZURA_LTX_HDR_ENDPOINTS=1` route now accepts single EXR images in the
existing LTX first/last workspace. Studio keeps the uploaded asset identity and
manifest hash; its tone-mapped PNG is only a viewing proxy. The server rechecks
the manifest and file hashes before generation. The first frame is required;
the last is optional. Both endpoints must be EXR for this preview. Switching to
H3 or Wan with an EXR gives an actionable error rather than feeding the SDR proxy
into another model.

The graph follows the installed official two-stage HDR I2V example: distilled
INT8 transformer, Gemma4 INT8, full video VAE forced to float32, no reference JPEG
compression, first-frame conditioning at both passes, optional last-frame guides
at both passes, latent upscaling and a three-step refinement pass. Output is HLG,
ACEScg EXRs or both, with an explicitly SDR viewing preview. This native route
does not enqueue the separate SDR-to-HDR conversion. Source audio can be frozen
as guidance; generated audio is padded with silence to match the selected length
when the audio latent is shorter. Installed compatible LTX LoRAs remain optional.

Graph-derived setup checks cover both audio paths. The interface reports the
64-pixel grid and 512–2048-pixel side limits. A 40-million-pixel-frame software
budget bounds this preview; it is not a hardware-capacity prediction. Native
endpoint support remains opt-in and is not installed or publicly released.

Evidence in `work/openjutsu-benchmark`:

- `native-hdr-endpoint-check`: real first-only and first/last GPU tests; both
  produced nine 512 × 512 frames, 10-bit BT.2020/HLG video and nine EXRs retaining
  scene-linear values above one. Timings were 42.3 s and 14.0 s, with cache reuse
  on the latter, so these are not a fair performance comparison.
- `native-hdr-endpoint-ui`: real browser EXR uploads, first/last generation,
  final playable preview and HLG/EXR links in 45.2 s, with no page errors.
- `native-hdr-endpoint-confirmation`: first-only generation with a short audio
  reference; live loading stages, eight-step generation and three-step refinement
  were observed. The delivered reference tail is silent and audio is 0.375 s,
  matching the nine-frame video. Desktop and 390 px layout checks had no global
  overflow and retained the central viewer.
- `native-hdr-audio-delivery`: the real generated-audio output, whose native
  stream was 0.330 s, was re-exported through the final CPU delivery graph. Video
  and padded audio are both 0.375 s; HDR tags and nine frames are retained.

Seven Python endpoint tests and the native endpoint UI, automatic delivery and
owned-progress tests pass. These short engineering tests establish connectivity,
asset isolation, output tags and timing. They do not establish long-clip quality,
mixed SDR/EXR endpoints or artist approval on an HDR display. Remaining LTX routes
and longer native endpoint selections still require integration and verification.

## Main performance workspace: inline SDR-to-HDR delivery

The existing main LTX performance composer now includes an output selector with
SDR, HLG video, HLG + EXR and EXR. This is an explicit additional SDR-to-HDR pass,
not native HDR video conditioning. It preflights the conversion dependencies
before generation, includes missing HDR files/nodes in the shared model setup,
and starts one conversion from the actual completed SDR asset and raster.
Changing delivery format preserves the reviewed selection and starting image.
H3 and Wan do not expose this selector.

The original SDR take is retained. Conversion progress, targeted cancellation,
the SDR viewing proxy and HLG/EXR downloads remain in the same workspace. Closing
and reopening observes the same job. Unknown submission identity does not trigger
an automatic repeat conversion. An unconfirmed cancellation remains visible.

The isolated port-8360 browser check used a verified existing nine-frame,
512-square SDR receipt to exercise this new handoff and real HDR inference.
It observed one submission, sampler steps, final playback and both downloads,
then reopened without submitting again. The conversion took 31.409 seconds in
this cache-dependent test. FFprobe confirmed nine 10-bit BT.2020 HLG frames and
matching 0.375-second audio; the archive contains nine EXRs. Desktop controls,
390-pixel mobile controls and the desktop result were visually checked.
Evidence: `main-ltx-hdr-check/results.json`, screenshots and
`delivery-metadata.json` in the benchmark folder.

This does not establish main performance quality, long/high-resolution HDR
delivery, native HDR input or HDR-display acceptance. The main generation recipe
was not rerun by this fixture; its output metadata is covered by backend tests.
The controls and delivery code remain source-only and are not installed or
publicly released. The broad all-LTX HDR checklist remains open.

## Main performance workspace: opt-in native EXR appearance

`ZURA_LTX_HDR_PERFORMANCE=1` enables a separate native experiment in the existing
supplied-frame flow. It accepts an original EXR appearance image alongside the
existing SDR motion source. The tone-mapped PNG is a viewing proxy only. Approval
binds the original manifest, colour interpretation and proxy identity; changed
EXR bytes fail validation even when the PNG is unchanged. This does not claim
native HDR motion-video ingestion or precise masked preservation.

The staged Union plan uses the full float32 video VAE, original EXR conditioning
and native HLG/ACEScg delivery. It does not enqueue a second SDR-to-HDR diffusion
pass. Native outputs are collected only after rebinding decode to the actual
upstream receipts. Every EXR archive entry is CRC-checked and decoded individually,
with finite-pixel, raster and scene-linear ACEScg/AP1 checks. Both the prominent
download and take-card download prefer the HDR master or EXR archive. Playback
uses the explicitly labelled SDR viewing proxy.

The feature refuses switching the active EXR to H3/Wan, SDR output, image
generation or a masked route. An unused supplied EXR does not affect a fresh
Build from references flow. Model setup checks full-VAE, encoder and phase
dependencies without loading weights. Current bounds are five seconds and
40 million padded pixel-frames, not a hardware guarantee.

On 31 October, an isolated GPU instance exercised actual Studio HTTP upload,
project creation, source preparation, automatic supplied-frame binding, frame
approval, all six generation phases and result collection. Preparation/binding
took 2.04 s and generation/delivery took 81.17 s, including loads and polling.
The result has 17 frames at 24 fps, 288 × 512, original audio, HLG video, 17
ACEScg EXRs and a separate SDR preview. The queue was empty after completion.
No image-generator stage or separate HDR conversion was submitted. Earlier
startup attempts exposed missing dependencies in the test server's deliberately
restricted whitelist and model paths; those test configurations were corrected.

The reference remains a synthetic exposure-expanded SDR image. These timings
are not a matched speed comparison, and this run does not establish real-camera
HDR fidelity or artist acceptance. The feature stays source-only and off by
default. All 86 `test_ltx25*.py` checks and 67 top-level JavaScript suites pass.
The stored project from this fresh render was then reopened in a CPU-only test
server. Browser playback, native-master downloads, desktop/mobile containment
and close/reopen passed with no page errors or new generation submissions.
Evidence: `native-hdr-performance-runtime-check` in the benchmark folder;
the separate `native-hdr-performance-ui-check` records the earlier result replay.
