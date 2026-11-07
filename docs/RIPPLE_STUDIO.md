# Ripple editing

Choose **Video → Ripple editing**, add footage and click above its filmstrip to
add an edited keyframe. The timeline reuses Paintout's thumbnail cards: each card
shows its original frame until an edited image is attached. Click a card to edit
it, drag the In/Out handles to trim, and zoom the timeline to separate nearby
keyframes. **Edit image** opens Studio's ordinary image editor with that
original video frame as Image 1. Choose a local model or a browser sign-in model,
then return with **Use edited frame**. The image and video stages share the prompt.

Alternatively, **Save frame** exports the full-resolution original for an external
editor. **Import edit** attaches the finished image to that timeline frame.
Imported edits must match the source dimensions. Re-editing always starts from
the original footage rather than a previous generated image.

- **H3 Ripple:** up to 16 edited frames anywhere inside the selected clip.
- **LTX 2.5 Ripple:** one edited image at the first frame of the selected clip.
  Trim the clip to choose a different starting frame. Each model keeps its own
  keyframes when switching, so switching models does not erase edits.

Full, 75%, 50% and 25% processing sizes affect only the AI working raster.
Dimensions round up independently to the model grid: 32 pixels for H3, 64 for
LTX. The working video and edited images stretch to that raster. Decoded results
stretch back to the source dimensions, without cropping or letterboxing.

Every selected source frame is retained. A held final frame supplies any extra
frames needed by the model, and delivery removes that internal padding. Source
frame rate, selected frame count and matching source audio are retained. H3's
native loader resamples to 24 fps; Studio's thin data adapter bypasses that loader
and supplies the original frames directly to the native Ripple conditioning.
Motion quality at other source rates still needs shot-specific review.

Both Ripple recipes currently accept SDR. This does not add HDR support to H3.
The source-sized master and browser playback copy are separate files; **Save
video** downloads the master. Output lives beneath ComfyUI's configured output
folder, in **ZURA STUDIO/ripple**.

Model setup uses Studio's shared one-click installer, including existing external
model folders and gated access. H3 also needs the
[WepeNerd nodes](https://github.com/WepeNerd/ComfyUI-WepeNerd).

The timeline, source-rate delivery, native-node contracts, submission recovery
and image-edit handoff have CPU and mocked UI regression coverage. These checks
do not measure generated-video quality.
