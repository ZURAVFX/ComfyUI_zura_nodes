# HDR frame-extension boundary refinement

The artist reported that the `512ebbec` HLG master was substantially improved,
but its original-footage boundary was still visible. It is not approved.

The experimental HDR compositor now follows its linear-light blend with a
screened harmonic ACEScct exposure/chroma correction in the generated area.
The native plate is retained exactly through its boundary. This avoids a fixed
outer fade edge and lets the correction follow the added scene's gradients.
Soft masks keep the existing linear-light composite; they are not thresholded
into a different selection. Partial strength remains supported.

CPU buffers are processed one frame at a time. A factorisation is reused only
within a batch and released afterwards. Larger masks use sparse iteration
instead of a potentially large direct factorisation; failure to converge stops
delivery rather than publishing a partial correction.

Evidence is in `../openjutsu-benchmark/hdr-boundary-refinement/`:

- `genj/hdr/hdr_boundary_refined_v1_audio.mp4`: 1088×640, 41 frames at 24 fps,
  HEVC 10-bit HLG / Rec.2020, with the previous master's original audio copied.
- `genj/hdr/hdr_boundary_refined_v1.zip`: 41 linear ACEScg EXRs.
- `before-after-sdr-comparison.mp4`: previous master left, new refinement right.
- `tests.json`: 87 focused boundary, outpaint, delivery and HDR timing checks pass.
- `installed-tests.json`: the same 87 checks pass against the installed runtime
  modules. The original and refined masters' copied AAC packet hashes match
  (`e400b1c1e42cc0a820f51c3587beb262be5783992a6bc3661c36ca6592d10557`).

This tests the final refinement stage on retained composite EXRs and native
source frames, without rerunning diffusion. It is not a fresh end-to-end model
run. The original plate is asserted exact before EXR half-precision export.
The HLG tags, frame count and dimensions were inspected with FFprobe.

Artist review of the new HDR master remains required. Native HDR experimental
feature flags stay off by default. Nothing is publicly released by this change.
