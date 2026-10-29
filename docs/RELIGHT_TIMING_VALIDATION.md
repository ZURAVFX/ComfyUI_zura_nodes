# Relight timing and framing validation

Wan 2.1 Relight's approved-source loader previously rounded both source axes
independently to a 64-pixel grid before the model's own resize. This could
distort source proportions: for example, 1280 × 720 became 1280 × 704.
Relight now requests an even-pixel aspect-preserving intermediate; other
workflows retain their existing grid and cached sources are kept separate.
The same centre crop is used for the lighting reference and motion source.

The bounded-media test exercised the actual loader and FFmpeg with an RGB video:
the 48 × 32 source was prepared as 256 × 170, instead of the default 256 × 192.
The cached source and frame count were inspected. The associated relight graph
and legacy loader checks pass without changing other routes.

One real Wan 2.1 GPU render used an already approved one-second source and
lighting image. The output contained exactly 24 frames at 24 fps, 1280 × 720,
and one audio stream; Comfy execution took 245.96 seconds on the test machine.
Decoded source and output audio correlated at 0.99988 with zero measured lag
at 8 kHz, consistent with the original soundtrack being retained. A contact
sheet of the approved still and the first, middle and last generated frames
showed no obvious framing jump in this shot. This is a single short example,
not proof that every source or shot cut will behave identically.

Other existing real video runs in `work/openjutsu-benchmark` delivered 120
frames / five seconds at 24 fps for standard H3, Wan 2.2, LTX 2.5 and
OpenJutsu, and 72 frames / three seconds for Wan Animate 2 and OpenJutsu.
Frame-grid and temporal-padding logic is also covered by CPU/graph tests.
Longer clips, unusual frame rates and every combination of mode, output size,
source codec and audio still need their own end-to-end coverage.
