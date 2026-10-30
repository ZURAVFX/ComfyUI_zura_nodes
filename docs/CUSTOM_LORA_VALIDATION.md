# Custom LoRA execution smoke test

A controlled local H3 first-frame test used the browser's native 22-frame,
256 × 256 recipe at 24 fps, four sampling steps and seed 42. The original
Turbo adapter remained in both runs. An installed FL2VA 4-step adapter, whose
metadata names the same H3 base, was added at strength 0.2 only to the second
run through `/zura/studio/loras/apply`.

The returned graph chained the custom adapter between the H3 UNET and the
existing Turbo adapter, and the isolated Comfy run completed both graphs.
Both results have 22 frames and correct dimensions; decoded RGB differs by
1.824 levels on average out of 255. That confirms execution and a measurable
output difference, but the experiment does not establish identity, quality,
performance or determinism. Combining speed adapters is not recommended from
this test. Cold baseline took 21.04 seconds; the 9.05-second modified run was
warm and is not a fair speed comparison.

Test inputs, graph and histories are private local artifacts in
`work/openjutsu-benchmark/lora_h3_smoke_*`. The isolated server was stopped,
and the user's existing Comfy queue was not interrupted. Other LoRA families,
paired Wan phases, and the LTX/HDR guidance combinations still need real GPU
and artist-quality tests.

## FastH3 progressive execution

The installed FastH3 Omni INT8 checkpoint shares all 932 model tensor keys with
normal H3 Ref2VA, plus 166 FastH3-specific keys. A locally installed H3
reference LoRA has 208 low-rank tensor pairs, all matching FastH3 target names
and shapes. A real 56-frame, 256 × 256, 24 fps SelfLift run completed with and
without that adapter at strength 0.2. Comfy logged zero patches on the baseline
and 208 patches on both low- and full-resolution passes with the adapter. The
videos differ, but this single test does not establish subject fidelity or
quality for other LoRAs. FastH3 custom LoRAs are therefore optional and marked
experimental; no adapter is selected by default. Users must check any LoRA's
compatibility, and unrecognised metadata requires explicit confirmation.

The first run was cold and the second warm; their timings are not comparable.
The isolated server was stopped. Graphs and histories remain private local
artifacts in `work/openjutsu-benchmark/fasth3_lora_smoke_*`.
