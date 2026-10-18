# Studio execution and memory

Studio submits native Comfy graphs to the same serial worker used by graph view. Model loading, attention and sampling use those native nodes. The interface does not run a second video inference engine.

## Changes

- Unchanged uploaded media, reviews and LTX handoff files reuse a bounded process-local SHA-256 cache. Size, modification time, change time and file identity invalidate it. A file changed during hashing is rejected.
- H3 planning reuses successful conditioning-cache checks. The actual inference loader still validates the tensors and file integrity.
- Graph building runs off the server event loop, keeping progress and unrelated requests responsive.
- Active automatic handoffs are checked every half second. Idle projects are skipped; unchanged records are not continually rewritten or reparsed. The record cache is bounded by both count and source JSON bytes.
- LTX still clears execution caches at the initial handoff and after large motion-frame preparation. Other compatible LTX boundaries unload VRAM while retaining reusable native caches if at least 8 GiB or 12% of system RAM is available, whichever is greater. Low or unavailable memory information falls back to a full clear. Wan preparation/speech boundaries retain their existing full release.
- Progress separates the artist's operation from the active loading or sampling step. A handoff never carries the previous sampler's percentage or ETA into the next operation.

## Evidence and limits

A synthetic 130 MiB file check took approximately 107 ms cold and 0.18 ms warm on the development workstation. This is a file-verification benchmark, not an end-to-end generation speed claim. Changed-file, cache-bound and orchestration regressions are covered by CPU tests.

A local camera integration smoke test on an RTX 4080 completed its 16-step still in 9.24 seconds and its eight-step, two-second 768 × 448 video in 55.53 seconds, including model loading. Output had 48 frames at 24 fps and one audio track. The video started about 17 ms after action creation and was collected about 0.40 seconds after native execution completed. These are one-run measurements, not a matched comparison with a standalone graph or a guarantee for other hardware. The camera view drifted towards the source framing and remains a preview recipe.

The approved H3 character path still pads to at least 124 frames for temporal stability. Its two-second output is therefore not comparable to a standalone 56-frame graph. Camera and viewport routes use their own shorter supported frame counts. Sampling settings and approved image quality have not been reduced to manufacture a speed improvement.

Cold model loading, system RAM pressure and another application's GPU usage still affect elapsed time. A paired end-to-end benchmark of each approved route remains necessary before claiming Studio is faster than graph view.
