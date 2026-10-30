# LTX 2.5 HDR development

HDR is LTX-specific. The experimental `artist_studio/hdr_delivery.py` graph
builder follows the locally installed official `ComfyUI-LTXVideo` 2.5 HDR
examples. Studio offers a bounded SDR-to-HDR tool for an uploaded source or
the latest LTX result. It is a separate conversion pass, not an HDR-enabled
version of all LTX generation workflows.

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
