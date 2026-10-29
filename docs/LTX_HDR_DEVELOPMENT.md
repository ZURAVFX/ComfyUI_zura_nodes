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
