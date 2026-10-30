# Longer LTX outpaint: private experiment

The artist approved the two-window and four-window anchored, feathered tests.
The longer masked canvas workflow is separately selectable in local Studio;
it does not replace the artist-approved short black-video canvas workflow.

The private executor reviews the entire selected range in bounded windows,
requires a matching full-range approval, queues the windows sequentially,
checks each decoded result, blends overlaps and attaches the source audio
once. Its 40-million padded pixel-frame ceiling is an engineering bound, not
a general guarantee that all resolutions and hardware will fit. The executor
has no restart recovery. The source scene may change between independent
windows. The overlap blend can ghost moving subjects, and it does not provide
model-level temporal continuity.

Tests on the local RTX 4080 used 150 frames at 24 fps, an office source with a
768 × 432 source rectangle, and a 1152 × 640 expanded canvas. All results
used LTX 2.5 INT8 and fixed seed 42. At that raster the planner used four
overlapping windows of at most 49 frames.

- The existing black-guide method filled the first two windows but left the
  third and fourth almost entirely black in the expanded region. In sampled
  frames 86–149 approximately 99% of each border was below RGB 8. The change
  was clearly visible at the overlap.
- A fresh-process repeat of window 3, with the same source segment, prompt and
  settings, also left 99.5–99.9% of its sampled border near-black. The review
  videos showed the expected source and selected border in all windows. The
  MP4 prompt metadata showed the same model, adapter, guide, sampler, sigmas
  and seed; only source starts, output names and final window length differed.
  This comparison does not establish the cause, but makes stale state from a
  preceding window less likely.
- A separate experimental two-stage native masked in/outpaint recipe filled
  the previously failing window. A four-window test using that recipe produced
  150 frames at 1152 × 640 with original audio in 140.45 seconds including
  review. At sampled seams and endpoints the near-black fraction of each
  border was 0–1.4%. The unmasked source rectangle had a mean absolute RGB
  difference of 5.88–7.97/255 on those frames, so it is not bit-identical.
  Audio decoded to the same sample count as the source at 16 kHz, with a
  0.9989 zero-lag correlation; AAC was re-encoded.
- A contact sheet showed plausible office continuity at sampled overlaps.
  It is not a substitute for a full-motion artist review, additional scenes,
  varying camera motion, or a quality comparison at the user's final output
  size. The initial masked recipe was evaluated in a temporary isolated test
  plugin and did not replace the chosen short method.

The artist reported visible scene changes in the full masked result. A private
follow-up uses a generated frame from the previous window at the exact source
time of the next window's first frame. Native `LTXVImgToVideoInplace` applies
that image to the low-resolution and high-resolution latents, while the
source-video IC guide and reviewed mask remain connected. Nine same-time frames
are blended across the join. A two-window test produced 80 frames at 24 fps,
1152 × 640, with original audio in 94.21 seconds including review. The decoded
previous anchor and next window's first output differed by 2.0 RGB levels on
average out of 255, so the anchor is not a bit-perfect lock. The largest
adjacent full-frame difference around the feather was 1.84/255; a previous
low-pass-only hard-join test had a 4.86/255 difference at its join. These are
different source timestamps and numeric proxies, not a substitute for artist
approval or tests across several joins and moving scenes.

The artist approved the two-window preview, then approved the 150-frame,
four-window anchored and feathered version. That full run retained 150 frames
at 24 fps and one audio track at 1152 × 640, taking 148.76 seconds including
review. Sampled border black fraction was at most 0.2%; the source rectangle
had a mean absolute RGB difference of 6.35–8.45/255. Audio had 0.99889
correlation with the source and zero measured lag. These are results for one
shot and hardware configuration, not guarantees for other footage.

CPU tests cover pixel-budget planning, real FFmpeg overlap assembly and audio,
whole-range approval binding, per-child progress ID mapping, disk checks, and
cancellation both during prompt submission and while waiting. In a separate
GPU run, cancellation at sampler step 1/8 removed the exact child prompt from
the isolated queue. A production-API smoke test on isolated CPU Comfy verified
the full 150-frame review and approval. Long mode cannot be exported as one
editable Comfy graph because it comprises multiple jobs. The tested servers
were stopped without changing the user's running Comfy session. Restart
recovery and broader visual testing across scenes remain future work.
# Cancellation status check

After the guided long workflow was installed, a separate 150-frame local test
cancelled an active child render through Studio's production endpoint. The
parent first reported `cancelling`, then `cancelled` only after that child had
left the isolated Comfy queue. Automated tests also cover a child which remains
running after the interruption request and ensure unrelated queue entries do
not delay or get cancelled by the short-job status check.
