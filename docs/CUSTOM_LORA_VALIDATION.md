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
